# POSTMORTEM-rtsp-idle-disconnect: 同一对话内长时间闲置后再次使用，Agent 报"RTSP 断连"

## 1. 现象

### 1.1 用户观察
- 同一个对话（同一个 MCP server 进程生命周期）内，摄像头工具闲置较长时间后再次调用，Agent 回复"RTSP 断连"。
- 用户自己的架构认知正确：整个 skill 中**只有两处**会维持 RTSP 长连接：
  1. `start_webrtc_stream` → 常驻 `go2rtc` 子进程（浏览器有人看时持有设备会话）；
  2. `manage_camera_events(start)` → `_CameraEventMonitor._private_rtsp_alarm_loop` 常驻告警会话（DESCRIBE/SETUP/PLAY 后长连接读 0x65 交织通道，每 25s 发 OPTIONS 保活）。

### 1.2 关键澄清："断连"其实不是"断"，而是"新建失败"
代码里**没有任何地方会产生"RTSP 断连"这个字符串**。除上述两处长连接外，所有常规操作（截图 / 取流 URL / 录像 / connect 校验）都是**每次调用冷启动一条全新 RTSP 会话**：TCP → DESCRIBE → SETUP → PLAY → 读帧 → release。闲置时根本没有连接存在，所以无所谓"断开"。

Agent 说的"断连"是对下列工具报错的自然语言转述：

| 实际报错（源码位置） | 触发条件 |
|---|---|
| `无法从 {ip}:{port} 获取视频流，请检查 RTSP 路径和认证信息`（stream.py:184） | cv2/FFmpeg 打开主、子码流路径都失败 |
| `无法从流中读取帧数据`（stream.py:313） | 会话建立成功但 6 次 read 全失败（典型 UDP 丢包） |
| `设备 {name}({ip}) RTSP 流不可达`（stream.py:168） | 无 cv2 时 `_probe_stream_access` = unreachable |
| `设备 {ip} 不可达（RTSP 端口 {port} 无响应）`（device_mgmt.py:1326） | connect_device 时 TCP connect_ex 失败 |
| `私有协议监听启动失败（RTSP {ip}:{port} TCP 不可达）`（events.py:760） | 监听启动时 TCP 探测失败 |
| `error_code="timeout"`（mcp_server.py:595） | 工具超预算，`abandon_on_cancel=True` 弃线程 |

### 1.3 时间特征
- 只在"长闲置后的第一次操作"出现；闲置越久概率越高。
- 长连接持有者（监听线程）自己会退避重连自愈，所以**报障的永远是新发起的短连接操作**，这与"闲置时长"强相关而与"是否正在用"弱相关。

## 2. 问题原理（为什么闲置时长会杀死"新建会话"）

冷启动新建会话要闯过四关，每一关都随闲置时长劣化：

1. **IP 关**：TCP 要连的是 config.yaml / `_connected_devices` 里的缓存 IP。摄像机多为 DHCP，租约 renewed 后 IP 变化——闲置期正是 IP 漂移的窗口。SKILL.md Gotchas 已明文承认此问题（"Cached IP goes stale after long idle"），但**只是叮嘱 Agent 先调 `search_devices()`，代码层没有任何强制或自动兜底**；且 `_connected_devices` 内存态里的旧 IP 优先级高于 config（stream.py:76）。
2. **会话名额关**：这类创维摄像机的并发 RTSP 会话名额极少——SKILL.md:77 原话 "concurrent instances would fight for the device's RTSP session slots and **hang the camera**"。闲置期存活/僵死的会话把名额占满后，新会话 SETUP 被拒或设备直接不响应：
   - 监听告警会话：设计内常驻，占 1 个名额（走的还是主流 `/md0_0`，与截图/取流同一路 URL）；
   - go2rtc 未停：浏览器页开着就整晚持有 1 个名额；**更糟的是 go2rtc 是普通 Popen 子进程（无 job object），MCP server 被宿主回收后它成为孤儿**，新进程里全局 `_go2rtc_process=None`，`stop_webrtc_stream()` 直接返回 True——**孤儿 go2rtc 永久占坑且工具层面无法停掉**（对比录像有 `recording_state.json` 落盘 PID 可回收孤儿，go2rtc 没有）；
   - 僵尸会话：`_private_rtsp_alarm_loop` 重连时**从不发 TEARDOWN**，只 close socket（events.py:417-421）；设备端旧会话要等自己的超时 GC。网络抖动/睡眠唤醒期反复重连 → 设备端僵尸会话叠加；
   - 弃线程：工具超时后 `abandon_on_cancel=True`（mcp_server.py:582），线程带着已建立的 cv2 会话继续跑，MCP 已返回错误，设备名额仍被占。
3. **半开连接探测关**：主机睡眠/网络切换后，监听的 TCP 变半开——`recv` 每秒 timeout 被当作"暂无事件"continue，保活 `sendall` 写进本地缓冲区也算成功，要等 TCP 重传耗尽（Windows 上数十秒到分钟级）才 OSError 触发重连；**期间 `status()` 仍报 `rtsp_session=True`**。且 OPTIONS 保活的响应从不被读取校验（直接混进 `parser.feed`），应用层完全不知道对端是否还认这个会话。设备端此时可能已把旧会话判死但名额未释放，恰好在用户回来操作的窗口里挤占名额。
4. **传输关**：`_open_rtsp_capture`（stream.py:63）**不指定 `rtsp_transport`，FFmpeg 默认走 UDP**。闲置后 Wi-Fi 省电、ARP 表老化导致首包丢失率高：TCP 握手能成（有重传），RTP/UDP 流丢包（无重传）→ "open 成功但读不到帧"。对比：录像路径（toggle_recording）有显式 tcp→udp 探测回退，截图/取流路径没有。冷摄像机（编码器休眠）首帧慢，8s open / 5s read 超时也更容易踩中。

另有两处**放大器**（不直接断连，但让现象更糟/更难诊断）：
- `_probe_stream_access`（device_mgmt.py:1646-1683）在 TCP 通但 DESCRIBE 超时（code=0）时**兜底返回 "open"**——connect_device 报成功，随后取流失败，状态自相矛盾，Agent 只能报"断连"。
- references/commands/stream.md 宣称截图/取流走"global serial slot + ffmpeg 子进程 + 超时即杀释放设备会话"，**当前 stream.py 实现（cv2、无串行槽、无子进程）与文档完全不符**——文档承诺的并发保护不存在，Agent 依据文档做的并发假设失效。

## 3. 根因（真正错在哪）

**一句话根因：skill 对"闲置劣化"没有任何代码级防御——它把长闲置后必然发生的四件事（IP 漂移、设备名额被存活者/僵尸占用、半开连接、UDP 首包丢失）全部留给"新建会话当场失败"来暴露，再靠 SKILL.md 的文字叮嘱让 Agent 事后补救；而"RTSP 断连"就是补救话术。**

分层归因：
1. **架构根因**：无会话复用、无预热、无健康检查。每次操作冷启动，会话建立成本与失败率全部暴露在用户操作的关键路径上。
2. **资源治理根因**：设备 RTSP 名额是稀缺资源，但只有录像做了 PID 落盘的孤儿回收；go2rtc 没有、监听重连不发 TEARDOWN、弃线程持有会话不释放——名额泄漏路径多于回收路径，闲置越久泄漏存量越可能压顶。
3. **状态感知根因**：保活只发不验（OPTIONS 响应不读）、半开连接靠 TCP 重传超时兜底、`rtsp_session=True` 可能是假象；`_probe_stream_access` 还会把"不确定"误报成"open"。
4. **一致性根因**：文档（stream.md 串行槽/ffmpeg、SKILL.md 叮嘱式兜底）与代码（cv2 直连、无槽、无强制刷新）脱节，防线只存在于提示词层。

## 4. 方案选项（≥ 2）

| 方案 | 改什么 | 风险 | 工作量 |
|---|---|---|---|
| A. 闲置感知 + 自动刷新兜底 | 在 stream/screenshot/record/connect 入口记录 `last_success_ts`；闲置超阈值（如 10min）或首次失败时：先 TCP 探测缓存 IP → 不通则自动 `search_devices` 按 SN 匹配刷新 IP → 重试一次；把 SKILL.md 的"叮嘱"变成代码强制 | 自动 discovery 增加 10-15s 延迟；SN 匹配失败时需回退原逻辑 | 中 |
| B. 会话名额治理 | ① 监听重连/停止前补发 TEARDOWN；② go2rtc 启动时把 PID 落盘（仿 recording_state.json），server 启动时回收孤儿；③ OPTIONS 保活改为"发送+读响应校验 200"，连续 N 次无响应即主动重连；④ 截图/取流超时的弃线程改为可终止（子进程化或协作取消） | ①③ 改动监听核心循环需回归告警链路；④ 改动面大 | 中大 |
| C. 传输策略统一 | `_open_rtsp_capture` 强制 TCP（`OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp`），失败再回退 UDP，与录像路径对齐；open/read 超时在"冷启动"场景放宽 | TCP 在极少数弱网下延迟高于 UDP，但局域网场景几乎无感 | 小 |
| D. 文档-代码对齐 | 修正 stream.md（删掉不存在的 serial slot 描述或把实现补上）；修正 `_probe_stream_access` 的 code=0 兜底为 "unknown" 并让上层如实上报 | 纯诊断性修复，不解决断连本身 | 小 |

## 5. 推荐方案 & 理由

推荐 **C + B(①②③) 为主，A 为辅，D 顺手做**：
- C 成本最低、直接消灭"open 成功读不到帧"这类最迷惑的伪断连；
- B① B② 堵住两个确定性名额泄漏（僵尸会话、孤儿 go2rtc），B③ 消灭假活会话——这三者正是"闲置越久越容易断"的存量来源；
- A 解决 IP 漂移这个最高频外因，把提示词防线代码化；
- 若只能选一个先做：选 **C**（一行环境变量级别改动，收益立竿见影），随后 B②。

## 6. 验证手段

1. **复现定位**（先确认你的环境里是哪条根因）：
   - 闲置前后各执行 `netstat -ano | findstr :554`，对比到摄像机 554 端口的 ESTABLISHED 数量与 PID（谁在占名额：mcp_server? go2rtc? 孤儿?）；
   - 复现失败时对比 `config.yaml` 里的 IP 与摄像机实际 IP（`arp -a` / 路由器后台）→ 验证 R1；
   - 失败瞬间用 `manage_camera_events(poll)` 看 `monitors.*.rtsp_session / last_error` → 验证假活会话；
   - Wireshark 过滤 `rtsp || rtp`：看 DESCRIBE 是否有响应（名额满通常返回 453/503 或直接不回）、RTP 是否有包到达（UDP 丢包验证）。
2. **修复验收**：
   - C：UDP 环境下人为丢包（或冷启动摄像机）截图 10 次成功率对比；
   - B②：kill mcp_server（不带 /T）→ 重启 → 确认孤儿 go2rtc 被回收（PID 文件 + netstat）；
   - B①：断网 30s 再恢复，抓包确认重连前发出 TEARDOWN、设备端会话数不增长;
   - A：手动改 config.yaml 里 IP 为错误值 → 首次操作应自动 discovery 纠正并成功。

## ⏸ 等用户确认根因 + 选方案
