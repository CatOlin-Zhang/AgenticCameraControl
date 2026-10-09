# POSTMORTEM-ptz-udp-tcp-freeze: 转动云台导致 UDP 视频流断流卡死，项目改用 TCP 优先的原因分析（口述信息还原）

> 本任务为纯 RCA / 设计考古，信息源为他人转述（可能有表达误差），无 git 历史可查（目录非 git 仓库），结论基于当前代码形态反推。

## 1. 现象

### 1.1 口述原文还原
"转动云台的时候，会导致 UDP 会话断点（按：应为'断流'）卡死，（后来）改成 TCP 连接。"

### 1.2 口述纠偏（代码事实）
**PTZ 命令面从不走 UDP**：
- SK 类：`control_ptz → _sk_ptz_set → camera_proto.ptz_set`（native `sk_ptz_set`），走创维私有协议 **TCP/HTTP 通道，端口 9010**（`device_mgmt.py:_SK_TCP_PORT = 9010`）。
- J 类：ONVIF `ContinuousMove/Stop`，HTTP over **TCP**。

所以被转动"卡死"的 UDP 会话只能是**数据面的 RTP/UDP 视频流会话**（预览 / 截图 / 取流探测 / 录像建立期）。口述的准确表述：
> 云台转动期间，走 RTP/UDP 的 RTSP 视频流断流、画面冻结；因此项目把流传输改成 TCP 优先。

### 1.3 现象的两个层次
1. **画面层**：预览/录像画面在转动瞬间花屏 → 冻结，直到下一个 I 帧才恢复（UDP 无重传，解码端只能等关键帧）。
2. **工具层（本 skill 特有）**：断流后 `cap.read()` 阻塞至 READ_TIMEOUT（5s，部分 OpenCV 版本对 RTP 不生效则更久）→ 截图循环最多 6 次 read → 工具 45s 预算耗尽 → `mcp_server.py:582 abandon_on_cancel=True` 弃线程 → **僵尸线程继续持有设备 RTSP 会话名额** → 后续操作全部"RTSP 断连"（与 rtsp-idle-disconnect 任务的 R2/R4 串联）。

## 2. 问题原理（为什么"转动"专门杀 UDP 流）

三因素在转动瞬间叠加：

1. **编码器码率突发**：云台运动 = 全画面全局运动，H.26x P 帧差值暴涨，剧烈转动还可能强制 I 帧；瞬时码率数倍于静态场景。UDP 无背压无重传：突发超出摄像机 Wi-Fi 发送能力 / socket 缓冲 → 成片丢包 → 解码端冻结等 I 帧。
2. **设备固件资源竞争**：低端 IPC 单 SoC 上，电机控制、私有协议 TCP 请求（且 `_guarded_wait` 在转动期间每 0.4s 轮询一次 `ptz_get`，加重请求面负载）、RTP 发送任务抢同一颗 CPU。转动期间 RTP 发送任务被饿死 → UDP 直接断流；TCP 的内核缓冲 + 重传把"饿死"掩盖成"迟到"，流不断只抖。
3. **无线链路**：摄像机多为 Wi-Fi 接入，省电模式 / 重传竞争窗口在码率突发期进一步放大 UDP 丢包。

**TCP（RTP/AVP/TCP interleaved）为何能治**：丢包 → 重传 → 帧迟到但完整，解码端不用等 I 帧；背压让固件发送端不溢出缓冲。代价是队头阻塞延迟，LAN 下可忽略。这是"LAN 内 RTSP 一律 TCP 优先"的经典工程取舍。

**高发场景锁定**：SKILL.md 的 PTZ 标准工作流 = 转动前截图 → 转动 → 转动后截图（对比估算位移）。截图恰好总落在转动/余震窗口内 → 这是口述现象在本 skill 里的最高频触发路径。

## 3. 根因（真正错在哪）

**一句话根因：UDP 传输对"转动引发的码率突发 + 固件资源竞争"零容忍（丢包即冻结），项目已在长连接与录像路径改为 TCP 优先，但截图/取流探测路径（`_open_rtsp_capture`，cv2/FFmpeg）至今未指定 `rtsp_transport`、仍走 FFmpeg 默认 UDP，且断流后弃线程持有设备会话名额，把画面级卡顿放大成工具级"断连"。**

分层归因：
1. **传输选型根因**：数据面对丢包敏感场景（转动、弱 Wi-Fi、冷启动）必须 TCP 优先；UDP 只应作为 TCP 失败后的回退。
2. **实现不一致根因**（"改成 TCP"只改了一半）：
   | 路径 | transport 现状 | 证据 |
   |---|---|---|
   | 告警监听会话 | ✅ 显式 `RTP/AVP/TCP;interleaved` | events.py:540 |
   | 录像 + 尺寸探测 | ✅ 计划 `["tcp","udp"]`，TCP 先探测 | stream.py:368-380, 386, 737-751 |
   | 截图 / get_audio_video_stream | ❌ cv2 默认（UDP），文档却宣称 "transport tcp→udp fallback" | stream.py:60-68 vs references/commands/stream.md:20,49 |
   | go2rtc 预览 | ❌ 生成配置未固定 transport，依赖 go2rtc 默认 | stream.py:1122-1127 |
3. **故障放大根因**：`abandon_on_cancel=True` + cv2 同步阻塞读 → 断流演变为僵尸线程占会话名额（无 TEARDOWN、无子进程可杀），与设备稀缺会话名额冲突，级联出"RTSP 断连"。
4. **文档-代码脱节**：stream.md 承诺的串行槽 / ffmpeg 子进程 / tcp→udp 回退在截图路径均不存在，掩盖了缺口。

## 4. 方案选项（≥ 2）

| 方案 | 改什么 | 风险 | 工作量 |
|---|---|---|---|
| A. cv2 路径 TCP 优先 | `_open_rtsp_capture` 通过 `cv2.VideoCapture(url, CAP_FFMPEG, [CAP_PROP_OPEN_TIMEOUT_MSEC, ..., OPENCV_FFMPEG_CAPTURE_OPTIONS, "rtsp_transport", "tcp"])`（或环境变量）强制 TCP；打开失败/读不到帧时回退 UDP 重试一次 | 极弱网下 TCP 队头阻塞延迟略增（LAN 可忽略）；老版 OpenCV 对 CAP_PROP_OPEN_TIMEOUT_MSEC 参数数组兼容性需 try/except 兜底（现有代码已有此模式） | 小 |
| B. 截图/取流子进程化 | 按 stream.md 文档的描述把实现补齐：ffmpeg 子进程 + 全局串行槽 + 超时 kill，彻底消灭弃线程占会话名额问题 | 改动面大；引入 ffmpeg 依赖路径（录像已依赖，风险可控） | 中大 |
| C. go2rtc 固定 TCP | 生成 go2rtc.yaml 时在 source URL 上固定 TCP transport（go2rtc 支持 source 级 `rtsp_transport`/query 参数，需按所用版本核实语法），并在预览卡顿时给出明确诊断 | 依赖 go2rtc 版本行为 | 小 |
| D. 转动期避让 | `control_ptz` 结束后加短暂 settle 窗口（或文档要求转动后延迟 ~1s 再截图），避开码率突发峰值 | 治标；延长 PTZ 工作流耗时 | 小 |

## 5. 推荐方案 & 理由

推荐 **A（必做）+ C，B 作为与 rtsp-idle-disconnect 任务合并的中期重构，D 作为文档级建议**：
- A 直接命中口述现象的现存缺口（截图/取流仍是裸 UDP），一处函数改动即可让"改成 TCP"的策略真正全覆盖；
- C 消灭预览路径的同类问题；
- B 同时解决上一任务的弃线程占名额问题，两案合并做收益最大；
- 与 rtsp-idle-disconnect 的方案 C 完全同源（都是 `_open_rtsp_capture` 强制 TCP），**两个 RCA 可共享同一个修复**。

## 6. 验证手段

1. **复现**：`ffplay`/VLC 分别以 UDP、TCP 打开同一路流，同时 `control_ptz` 连续转动 10s：UDP 端应现花屏/冻结，TCP 端仅抖动 —— 直接验证机理链。
2. **丢包计数**：转动期间 Wireshark 过滤 `rtp && ip.addr==<cam>`，统计 UDP 丢包/乱序 vs TCP interleaved 重传数。
3. **工具层验证**：修复 A 后，在转动窗口内连续 `capture_video_screenshot` 10 次，成功率应显著高于修复前；同时 `netstat -ano | findstr :554` 确认无残留 ESTABLISHED（无弃线程占坑）。
4. **go2rtc**：预览页开着转动云台，对比 C 修复前后的冻结时长（浏览器 webrtc-internals 看 framesDecoded/freezeCount）。

## ⏸ 等用户确认根因 + 选方案（或仅存档本 RCA）
