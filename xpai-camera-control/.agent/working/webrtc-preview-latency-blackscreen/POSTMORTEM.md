# POSTMORTEM-webrtc-preview-latency-blackscreen: WebRTC 预览延迟非常高、看一小会儿黑屏

> 分析日期 2026-10-08（当晚更新）。信息源：线上运行副本代码 + go2rtc 1.9.14 源码核实（GitHub tag；与部署二进制 revision b5948cf、上游最新 release 2026-01-19 一致）+ 本机实验（假源/合成源，未占用真实相机做破坏性操作）+ ffmpeg 只读探测两台真实相机码流 + **部署二进制内置播放器资产提取与全文分析（video-rtc.js v1.6.0）** + **本机无头浏览器能力探测（Edge/Chrome 154）**。**未修改任何代码。**

## 1. 现象

### 1.1 用户报告
- 使用 skill 的 WebRTC 实时预览（`start_webrtc_stream`）时：**延迟非常高**；**看一小会儿就黑屏，无法继续看**。
- 现场痕迹：部署副本 `C:\Users\XPT0416\.qoder\skills\xpai-camera-control\go2rtc.yaml`（11:46 写入）指向 **ZCR461_125 主码流 `/md0_0`**，即本次问题发生在该预览会话。
- 2026-10-08 16:05 复查（netstat）：无 :1984 监听、无 :554 连接——**当前无 go2rtc 进程存活**，无法回取当时进程内部状态。

### 1.2 需要先纠正的认知：用户打开的不是"WebRTC 页面"
`start_webrtc_stream`（stream.py:1149-1215）只做三件事：生成 go2rtc.yaml（**仅 `streams` + `api` 两节**，无任何转码/播放模式配置）→ `Popen` 启动 go2rtc.exe → 返回 `http://localhost:1984`（**根地址，不是播放页**）。

用户在 Web UI 里**默认点击流名进入的是 `stream.html`**（go2rtc v1.9.14 `www/index.html:49` 的 `<a href="stream.html?src={name}">`）。该页面并非"MSE 单通路"，而是 **MSE 与 WebRTC 双通路赛跑、按优先级裁决**（§2.5）——是否真走 WebRTC 取决于浏览器能力，而本机默认浏览器 Edge **不具备 H265-WebRTC**（§2.6），因此"延迟非常高"在该路径下是必然结果。skill 的文档（MCP_TOOLS_API.md §5）只给了根地址，没有给任何播放页深链或模式说明。

### 1.3 用户答复（2026-10-08 晚）

| # | 问题 | 答复 | 推论 |
|---|---|---|---|
| 1 | 打开哪个页面/浏览器 | `http://localhost:1984` 根页面，用**默认浏览器**（注册表实查：默认 = Edge 154） | 进入 stream.html 双通路赛跑；Edge 无 H265-WebRTC（§2.6）→ 只能落 MSE |
| 2 | 黑屏后刷新是否恢复 | 未试过 | **唯一关键判别仍缺失**（T1，§6.1） |
| 3 | 黑屏时 go2rtc 进程 | 应该还在 | 排除"进程被杀"类；但不能区分"进程在但内部卡死"（§2.4-d/f） |
| 4 | 黑屏前后有何其他操作 | 无 | 排除并发工具操作引发的名额竞争（历史孤儿残留仍不能排除） |
| 5 | 主/子码流 | 子码流**刚开始更稳**，后续同样黑 | **负载相关退化证据**：低负载（640x360）存活更久 → 支持解码/缓冲类机理（§2.4-f）与"时间累积型"退化 |

### 1.4 实机对照实验（2026-10-08 晚；用户操作 + 只读取证，未改任何配置）

**实验设计**：同一个 go2rtc 进程、同一条源流（ZCR461_125 主码流 /md0_0），先后用两个浏览器打开同一 URL `http://localhost:1984`。

| 阶段 | 客户端 | 表现 |
|---|---|---|
| ① | **WorkBuddy 内置浏览器**（Electron 37.10.3 = **Chromium 138**，§2.6） | **延迟很小、连续观看约 1 分钟**，用户手动关闭 |
| ② | **Microsoft Edge 154**（本机默认；无 H265-WebRTC，§2.6） | **播放几秒即卡死 → 过一会儿恢复一下 → 再次卡死**；页面保持打开 |

**go2rtc API 只读取证（卡死时刻）**：
- `/api/streams`：源端 producer 全程健康——`rtsp+tcp` 已连、累计接收 ≈28.9MB（≈2.3 分钟实时码流）、相机会话 ESTABLISHED；**唯一活跃消费者 = Edge 的 `mse/fmp4`（WebSocket）**，累计发送仅 ≈4.26MB（≈20 秒的量）、含 `flac` 音轨、`drops:122` → **消费端停读、源端持续供流，且 WS 未断开**（若断开，15s 自动重连会恢复）。
- `/api/log`：仅 8 行启动日志，**零 `WRN`** → 无源侧错误/重连事件。
- 进程溯源：go2rtc = 20:03 由 .workbuddy 副本启动的 PID 3056（该副本 stream.py 与 G 源、.qoder 副本的 WebRTC 段逐行一致）。

**结论（实机闭环）**：同一源、同一进程下，"WorkBuddy 低延迟稳定 ↔ Edge 秒级卡死"完全由**浏览器能力**（能否 H265-RTC）决定；延迟与黑屏均发生在 **Edge 的 MSE 消费端**，源/网络/go2rtc 三方取证全部健康。

## 2. 问题原理（为什么会触发）

### 2.1 输入流事实（ffmpeg 只读实测，2026-10-08）

| 相机 | 主码流 | 子码流 | 音频 | I 帧间隔 |
|---|---|---|---|---|
| ZCR461_125（本次预览对象） | hevc(Main) 2880x1620@20fps | hevc 640x360@20fps | pcm_alaw 8k | **5.0s（100 帧）** |
| CSDE2_107 | hevc(Main) 2560x1440@25fps | hevc 704x576@25fps | pcm_alaw 8k | 未测（同平台推定同量级） |

**所有码流都是 H.265，且 GOP 长达 5 秒。**这是整条链路的根本约束，直接决定：浏览器兼容语境、延迟下限、断流恢复粒度（见 2.4/2.5）。

### 2.2 go2rtc 1.9.14 实际行为（源码核实 + 本机实测互证）

- **RTSP 客户端默认即 TCP interleaved**（`pkg/rtsp/client.go:41-54`：transport 为空 → `tcp.Dial` + `rtsp+tcp`），并按会话 timeout 定期发 OPTIONS 保活（`conn.go:96-105`）。→ **传输层与保活无缺陷**；历史上"go2rtc 未固定 transport 依赖默认"的担忧（ptz-udp-tcp-freeze POSTMORTEM 方案 C）经核实**无需修**。
- **源断自动重连、消费者自动存活**（`internal/streams/producer.go:160-198`）：重试阶梯 1s→5s→10s→60s 无限重试；MSE 的 WebSocket 不断开、WebRTC 连接保留，恢复后从下一个 I 帧继续（`pkg/mp4/consumer.go:94-115`）。**本机实测**：合成源播放中强杀 ffmpeg 子进程 → 1 秒内自动拉起新源、消费者字节流连续不断。→ **"源断=必然黑到死"不成立，黑屏持续的条件是"重连一直失败"或"消费端自己卡死"。**
- **默认日志极少**：启动约 500B；HTTP 请求不记日志；健康观看 ≈0 B/min（本机实测 40s 全程仅 +276B 一条 WRN）。→ 排查棘手的来源之一，但见 2.4(d)。
- WebRTC 消费者对 H265 的处理是**浏览器 offer 驱动**：浏览器不支持则视频轨不匹配（仅音频匹配时甚至会连成"只有声音"），不会自动转码（`pkg/webrtc/server.go:9-48`、`internal/streams/add_consumer.go:48`）。MSE 则是**把 H265 直通给浏览器，由浏览器自己决定能否解码**（`www/video-rtc.js` 用 `MediaSource.isTypeSupported` 筛选）。

### 2.3 "延迟非常高"的成因（按贡献排序；当晚修订）

1. **通路被钉死在 MSE（决定性）**：stream.html 双通路赛跑在默认浏览器 Edge 上必落 MSE（Edge 无 H265-WebRTC，§2.6）——MSE 是缓冲通路，本身即秒级延迟档位。Chrome（本机已安装）支持 H265-WebRTC，同页会切到 RTC 亚秒级通路（T0 可实测）。
2. **4MP H265 解码/追帧压力**：MSE 控制器用 `playbackRate=gap` 追帧（§2.5）；解码若跟不上，gap 反复拉大 → 追帧更吃力（正反馈）→ 延迟随时间递增、卡感明显。**子码流"刚开始更稳"正是低负载佐证**（§1.3-5）。
3. **GOP=5s 放大一切等待**：打开/恢复都要等 I 帧（平均 2.5s、最坏 5s）。
4. 源侧若有积压（相机/Wi-Fi 推 4MP 吃力）会叠加其上；T0（Chrome 开 webrtc.html）可把源侧因素单独隔离出来。

### 2.4 "看一小会儿黑屏"的候选机理（当晚修订）

| # | 机理 | 触发条件 | 吻合度 | 证据 |
|---|---|---|---|---|
| f | **浏览器侧 MSE 播放器退化卡死（实锤，§1.4）**：内置播放器 2MB 定长缓冲无边界检查 + `appendBuffer` 异常吞噬且 `bufLen` 不复位 → 最终 `RangeError` 洪泛、SourceBuffer 断粮 → 画面冻结/黑，**且不触发任何重连**（该路径不经 WS close），只有刷新页面可解；4MP H265 解码/追帧压力是促发器 | 解码跟不上追帧、瞬时解码/配额异常 | **实锤**（§1.4：Edge 停读 4.26MB 而源端持续供流 28.9MB、WS 未重连；WorkBuddy 同源稳定） | §2.5 代码实证 + §1.4 实测 |
| a | **源会话被掐且重连持续失败**：预览长期占着相机的稀缺 RTSP 会话名额；本项目已知"名额易被僵尸/孤儿占满、设备会话竞争时可能挂"（SKILL.md:77、rtsp-idle-disconnect POSTMORTEM §2）。源被相机掐断后 go2rtc 无限重连，但只要相机侧名额不释放就**一直黑** | 相机侧名额耗尽/半开/设备忙碌 | 高 | 重连阶梯与消费者存活为源码+实测结论；名额稀缺为项目既有事实 |
| b | **解码端饥饿等 I 帧**：任何一次网络/解码打嗝，MSE 要等下一个关键帧才恢复，5s 粒度 | 网络抖动、解码卡顿 | 中 | GOP=5s 实测 |
| c | 浏览器解码器异常（驱动重置/GPU 进程级，非 f 的负载路径） | 硬解异常 | 中低 | 需 media-internals 佐证 |
| d | **4KB 管道楔死（条件致命）**：`Popen(stdout=PIPE, stderr=PIPE)` 无任何读取方（已核实全代码库仅 stream.py 触达 `_go2rtc_process`，无排空）；Windows 管道容量**实测仅 4KB**。若相机进入"TCP 可连但 PLAY 快速失败"状态，重连循环的 WRN 日志可把管道写满 → go2rtc 日志互斥锁阻塞 → 重连协程永久卡死 → **黑且不自愈（进程仍在）** | 快速失败重连循环 ≥~20 次 | 中低 | 管道容量与日志量为本机实测 |
| e | 孤儿/端口冲突衍生：MCP server 重启后孤儿 go2rtc 占坑或占着 1984 端口（rtsp-idle-disconnect POSTMORTEM §2 已记录） | 预览中途重启 MCP/server | 低 | 既有 POSTMORTEM |

**上游关联**：go2rtc #2205（H265 MSE 在 Chrome 120+ 连上即断；Draft PR #2253 未合并；官方 workaround = H264 子码流）——症状不同（立即失败 vs 先播后黑），但印证 **H265-MSE 为 upstream 已知脆弱区**，长期方案不应押注该通路。

**§1.3 答复后的排除 + §1.4 实机定界**：进程被杀 ✗、并发操作 ✗；"子码流更持久"支持 f 的负载路径。**§1.4 实机对照直接实锤 f**（Edge 消费端停摆、源端健康、WS 未重连）；T1（黑屏刷新）降级为可选自证手段（下次复发顺手验证即可）。

### 2.5 播放器实现证据（video-rtc.js v1.6.0，从部署版 go2rtc.exe 提取的内置资产）

**stream.html 不是 MSE 单通路，而是"双通路赛跑 + 优先级裁决"**（video-stream.js → video-rtc.js）：
- 页面同时建立 MSE 与 WebRTC 两路消费者（默认 `mode='webrtc,mse,hls,mjpeg'`），WebRTC 若取到视频轨，由 `onpcvideo()` 打分裁决：`H265+RTC = 0x240 (+音频 0x102)` vs `H265+MSE = 0x230 (+音频 0x101)` vs `H264+RTC = 0x220`。
- 本机推算：**Edge**（无 H265-RTC，至多"仅音频 RTC" 0x102）→ 永远小于 MSE 的 0x230 → **钉死 MSE**；**Chrome**（H265-RTC，0x342）→ RTC 接管。
- 页面右上角小字标签会显示当前模式（`MSE` / `RTC`）——实机测试时可肉眼确认。

**MSE 缓冲控制与缺陷（黑屏机理核心）**：
- 追帧控制：`playbackRate = gap>0.1 ? gap : 0.1`（gap=缓冲实时沿−播放位置），控制器平衡点 ~1s；缓冲窗滚动保留近 5s（`remove(start0, end-5)` + `setLiveSeekableRange`）。
- **缺陷链（2MB 定长缓冲）**：`buf = new Uint8Array(2*1024*1024)`；接收分支 `if (sb.updating || bufLen>0) buf.set(b, bufLen); bufLen += len`（**无边界检查**）；`appendBuffer` 在接收与 updateend 两处均被 `catch(e){}` 吞掉且**异常时不复位 bufLen**。→ 一旦 SourceBuffer 持续拒绝数据（配额/解码异常），新数据只能堆进 2MB 数组：先"失血"（正常直投路径被卡在缓冲分支），最终 `buf.set` 越界 `RangeError` 洪泛 → `ondata` 全部抛错、SourceBuffer 永久断粮 → **冻结/黑，无自愈**（可恢复的 `video.error`(MEDIA_ERR_DECODE)→WS close 路径在此场景根本不出现）。
- WS 层重连语义：最小 15s 间隔自动重连——只在 WS close 时生效，**救不了上述卡死**。
- **MSE 音频通路（修正）**：go2rtc 将相机 PCMA 音频转封装为 **FLAC** 写入 fMP4（用内嵌编码器，无需外部 ffmpeg；§1.4 `/api/streams` 消费端 codec 显示 `flac`，video-rtc.js 的 `CODECS` 列表亦含 `'flac'`）→ **Edge 的 MSE 实为 H265+FLAC 双轨**，此前"MSE 无音轨"判断作废。

### 2.6 本机浏览器能力实测（2026-10-08，headless 探测，未动相机）

| 能力 | Edge 154（**默认浏览器**） | Chrome 154（已安装） |
|---|---|---|
| MSE H265（hvc1/hev1）、H264 | ✅ | ✅ |
| **WebRTC H265**（offer 含 H265/90000） | ❌（仅 VP8/VP9/H264/AV1） | ✅ |

- 探测方法（无相机依赖）：本地 HTML 执行 `MediaSource.isTypeSupported` + `RTCRtpReceiver.getCapabilities` + 空 offer 检查 `H265/90000`，`--headless=new --virtual-time-budget --dump-dom` 取回。
- 注意：headless 与有头浏览器可能略有差异，Edge 无 H265-RTC 的结论由 T0 实机复核。
- 这同时解释并修正 §2.3：**用户看到的高延迟 = Edge 上 MSE 被迫接管**；换 Chrome 打开同一页面，标签应变 `RTC`、延迟应变亚秒级。
- **WorkBuddy 内置浏览器 = Electron 37.10.3（Chromium 138）**（`D:\Workapp\workbuddy\WorkBuddy.exe`，版本文件 `37.10.3-24`）——Chromium 138 恰为 H265-WebRTC 默认启用的版本线 → **支持 RTC**，与 §1.4 实机表现（低延迟、稳定）完全吻合。

### 2.7 两台相机的编码配置能力实测（2026-10-08 晚；只读查询，未改设备）

查询通道 = SK 私有设置通道（`POST http://<ip>:9010/xiaopaitech/device_service`；鉴权 = `SK_SETTING_GET_MAGIC` 取 stamp → `Basic base64(sha1(stamp+sn+key))`；报文格式复刻自 `native-runtime-distribution/before/binary/native/camera_proto.c`）。命令 `SK_SETTING_GET_VIDEO_OPTION`（能力）与 `SK_SETTING_GET_VIDEO`（现状），两台设备均 `C0000` 正常应答：

| 设备 | 当前主码流 | 当前子码流 | **设备报告的 encode 能力** | 主码流分辨率能力 | gop 范围 |
|---|---|---|---|---|---|
| ZCR461_125 | H265 2880*1620@20 VBR 1536k gop=100 | H265 640*360@20 VBR 512k gop=50 | **主/子均 ["H264","H265"]** | 2880*1620 / 2560*1440 / 2304*1296 / 1920*1080 / 1280*720 | 1–200 |
| CSDE2_107 | H265 2560*1440@25 VBR 2048k gop=100 | H265 704*576@25 VBR 384k gop=100 | **主/子均 ["H264","H265"]** | 2560*1440 / 2304*1296 / 1920*1080 / 1280*960 / 1280*720 | 1–200 |

结论：
1. **两台相机主/子码流都支持切到 H264**（设备自报能力，本固件不支持 "H265+"，仅 H264/H265）→ **方案 B 的设备可行性成立**。
2. **SK 通道即可读写视频参数**：GET_VIDEO_OPTION / GET_VIDEO 实测通过；设置命令 `SK_SETTING_SET_VIDEO` 与现有 image/filllight 系列同族同链路 → skill 若要做"预览码流 H264 化"，按既有 `sk_image_*` 模式新增 `sk_video_get/set` 即可（当前 DLL 未暴露，需改 C + facade）。
3. **fps 下限 10**（125 主 10–20；107 主 10–25）；设置后应 set→get 校验。
4. 旁证与对照：JCP `devvecfg -act list` 同读数（codec=7=H265，与 ffmpeg 实测互证）；**ONVIF 编码配置是 decoupled stub（报 H264 但实为 H265）→ 不可信、不作为能力依据**。SK doc 备注"主/子码流 encode 相同"——本两台能力表主/子独立列出，实际耦合约束待 set 时验证。
5. 边界须知：改码流会影响其他使用方（NVR 录像/其他客户端）；H264 同分辨率下码率效率低于 H265，2880*1620@H264 顶 2048k 上限画质会降，可能需同时下调分辨率/fps。

## 3. 根因（真正错在哪；§1.4 实机对照后定稿）

**一句话根因：预览把"实时"的路径选择交给了 go2rtc 默认 UI 的"赛跑"逻辑，而默认浏览器（Edge）恰好赢不了 WebRTC 赛跑 → 被钉死在 MSE；MSE 通路上"4MP H265 解码压力 + 播放器自身 2MB 缓冲缺陷 + 5s GOP"叠加出高延迟与"无自愈黑屏"；skill 侧的无日志/无进程治理又消灭了最后的自救与可诊断性。**

分层归因：
1. **通路选择根因（延迟高的决定项）**：`web_url` 只回根地址；UI 默认页双通路赛跑由浏览器能力裁决；Edge 无 H265-WebRTC → 必落 MSE。skill 未提供按浏览器能力选通路/深链的任何机制。
2. **播放器质量根因（黑屏实锤）**：video-rtc.js v1.6.0 的 MSE 缓冲缺陷（§2.5）+ 4MP H265 解码/追帧压力 → Edge 上永久卡死；§1.4 实机对照（同源同进程：WorkBuddy 稳定 vs Edge 秒级卡死；Edge 消费停摆在 4.26MB 而源端持续供流 28.9MB、WS 未重连）已实锤为**浏览器侧消费端问题**。
3. **源侧稳定性（并行机理，本次未触发）**：相机名额稀缺 + 孤儿/僵尸占坑（既有 RCA）——§1.4 全程源端健康（bytes_recv 持续增长、零 WRN）；若未来出现"刷新仍黑/极慢"再升为排查主因。
4. **可观测/治理根因**：Popen 管道未排空（4KB 楔死）、无 PID 落盘、黑屏零提示——一切故障统一呈现为"黑屏看不了了"。
5. **上游风控**：H265-MSE 通路上游亦脆弱（#2205 未修复）——长期方案不应押注该通路。

## 4. 方案选项（≥ 2；当晚修订）

| 方案 | 改什么 | 风险 | 工作量 |
|---|---|---|---|
| A. 转码直出 H264（配合深链） | go2rtc.yaml 的 source 加转码（`#video=h264` 模板，需 ffmpeg 可执行文件）。本机 PATH 存在 ffmpeg（.workbuddy env），但 skill 部署目录**未捆绑**、MCP 运行环境 PATH 不可保证 → 落地需随包捆绑 ffmpeg | 转码 CPU 开销（建议先子码流验证）；新增二进制依赖与校验 | 中 |
| B. 设备侧编码调整（根治方向） | 相机支持则：码流 H265→H264（**Edge/Chrome 的 WebRTC 均支持 H264**，MSE 也更稳）、I 帧 5s→1-2s。**§2.7 已实测确认：两台设备主/子码流均支持 H264，SK 通道读写链路成立** | 改设备配置影响其他使用方（NVR/客户端，§2.7-5）；skill 需新增编码配置能力（改 C + facade，按 sk_image_* 模式） | 中 |
| C. 引导层修复 | `web_url` 深链 `webrtc.html?src=<name>`；文档说明两条通路的延迟档位与浏览器要求（Chrome 可 RTC；Edge 暂不行） | 无（纯体验）；Edge 用户无 RTC 可用 | 小 |
| D. 稳定性工程（与既有 RCA 合并） | ① Popen 输出 DEVNULL/落盘日志（消灭 4KB 楔死）；② go2rtc PID 落盘 + 孤儿回收（照抄 recording_state.json 模式）；③ 黑屏可观测提示 | ②涉及跨进程回收需回归 | 小-中 |
| E. 仅文档说明 | 写明"预览为 MSE 秒级延迟、黑屏刷新页面" | 不解决 | 小 |
| F. 自产修正版播放页（本次新增） | skill 内置一个修正的播放页（修 2MB 缺陷：异常即重建 SourceBuffer/主动重连/显示"重连中"）+ 显式"RTC 优先→MSE 兜底"选择逻辑，`web_url` 指向它 | 播放页需小样验证（file:// 直连本机 ws 的兼容性）；维护自研前端 | 中 |

**不建议**：改 RTSP transport 为 UDP、自定义缓冲参数等——默认即 TCP（§2.2），无收益且有回退风险。

## 5. 推荐方案 & 理由（§1.4 实机对照后更新）

**§1.4 已把病灶锁定在消费端通路**：同一源、同一 go2rtc 进程下，支持 H265-RTC 的 WorkBuddy（Chromium 138）稳定低延迟，Edge（无 H265-RTC → 被钉死在 MSE）秒级卡死且不自愈；源端全程健康。→ 问题定义为"**Edge 用户被钉死在有缺陷的 MSE 通路上**"，修复主线围绕"把用户送上 RTC 通路 + 治理与兜底"展开：

1. **即时可用（零代码）**：用 **WorkBuddy 内置浏览器或 Chrome** 打开预览（均支持 H265-WebRTC → RTC 亚秒级、稳定）；Edge 暂避开。
2. **修复主线（按序）：C + D① + B**
   - **C**：`web_url` 深链 + 通路说明（按浏览器能力引导到正确通路，不再靠"赛跑"碰运气）；
   - **D①**：Popen 输出落盘（消灭 4KB 楔死 + 恢复可诊断性，零风险）；
   - **B**：设备侧码流 H264 化——**§2.7 已实测两台设备主/子流均支持 H264、SK 通道读写成立**，是完全可行的根治路线（Edge/Chrome 双双 RTC 可用、MSE 退为安全网，短 GOP 顺带解决恢复粒度）；落地含"skill 新增编码配置能力"或"用户手动改一次设备配置"两种执行方式。
3. **A 兜底**：B 不可行时改用转码源（H265→H264），达成同样的"Edge 可 RTC"；需随包捆绑 ffmpeg（成本中）。
4. **F 兜底**：若必须长期支持"Edge + H265-MSE"（不动设备也不转码），才自产修正版播放页（修 2MB 缺陷 + 异常即重建 + 黑屏提示）。
5. **T1/T3 转为后续定界手段**（本次判别已被 §1.4 实机对照替代，不再阻塞方案选择）；T0 可选做一次（Chrome 实机复核 RTC 标签与延迟）。

## 6. 验证手段

### 6.1 判别问题（1/3/4/5 已答；核心判别已由 §1.4 实机对照替代；T0/T2 可选复核）
- ✅ 页面：根页面默认点入（双通路赛跑；Edge 必落 MSE）；浏览器=默认 Edge 154。
- ✅ 无并发操作；✅ 黑屏时进程仍在；✅ 子码流初稳后同样黑。
- ✅ **T1 等价结论（§1.4 直接给出）**：卡死时源端健康、消费端停读、WS 未重连 → 浏览器侧卡死（f）实锤。下次复发可按 F5 顺手自证（快恢复=确认 f）。
- ❌ **T2（可选）：画面停时页面右上角标签显示什么（MSE/RTC）？** 预期 Edge 恒为 MSE。
- ✅ **T3 等价结论（§1.4 直接给出）**：卡死时相机会话仍 ESTABLISHED（源侧在，指向浏览器侧）。
- ❌ **T0（可选）：用 Chrome 打开 `http://localhost:1984/webrtc.html?src=ZCR461_125`**——标签应显 RTC、延迟应亚秒级（实机复核 headless 结论）。

### 6.2 复现与定位（可执行）
- **延迟定量**：同一相机分别开 `stream.html`（Edge）与 `webrtc.html`（Chrome），用手机秒表对拍视频画面报时，记录两种模式延迟差。
- **解码器确认**：观看时开 `chrome://media-internals`（Edge 为 `edge://media-internals`），看使用的解码器（硬解/软解）与 pipeline 错误。
- **名额占用观测**：黑屏时刻 `netstat -ano | findstr :554` + `tasklist`，对照 rtsp-idle-disconnect POSTMORTEM §6.1 的排查方法。
- **播放器资产提取（已验证可复用）**：`go2rtc.exe -config <临时yaml：api 端口≠1984、空 streams>` 后 `curl /stream.html /video-rtc.js /video-stream.js`，即得当前部署版内置播放器源码。
- **浏览器能力探针（已验证可复用）**：见 §2.6 方法（本地测试页 + `--headless=new --virtual-time-budget --dump-dom`）。
- **go2rtc 日志直读**：因 Popen 未排空管道，排查时改为"手动控制台运行 go2rtc（同一 yaml）"即可看实时日志——黑屏时刻出现重连 `WRN` → 源侧；全程安静而画面黑 → 浏览器侧。
- 修复后按所选方案各自的验收点复测（F：构造解码异常观察自动恢复；D①：卡死场景日志完整性；A/B：延迟定量对比）。

## ⏸ 等用户确认根因 + 选方案
