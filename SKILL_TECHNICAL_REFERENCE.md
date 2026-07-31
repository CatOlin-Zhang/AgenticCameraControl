# xpai-camera-control 技能包工具清单与调用关系

> 版本: 0.4.5 | 传输协议: MCP stdio | 生成日期: 2026-07-31

---

## 一、总览

| 分类 | MCP 外部工具 | 内部函数（不暴露给 Agent） |
|------|:---:|:---:|
| 设备管理 (device_mgmt) | 7 | 8 |
| 音视频流 (stream) | 4 | 0 |
| 云台控制 (ptz) | 4 | 1 |
| 创维私有发现 (discovery) | 1 | 1 |
| 事件监听 (events) | 1 | 4 |
| 鉴权模块 (auth) | 0 | 全部内部 |
| **合计** | **17** | **14+** |

---

## 二、MCP 外部工具清单（Agent 可调用）

### 2.1 设备管理 — `device_mgmt.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 1 | `get_registered_cameras` | 从 config.yaml 加载所有已注册摄像头配置 | 无 |
| 2 | `register_camera` | 将摄像头凭据持久化到 config.yaml | name(必填), ip, port, username, password, rtsp_port, rtsp_path, device_class, sn_code, pkdk 等 |
| 3 | `search_devices` | 搜索局域网摄像头（WS-Discovery / 创维私有 / USB） | method(ws_discovery\|sky_discovery\|usb), timeout |
| 4 | `connect_device` | 连接摄像头（自动缓存凭据、探测 ONVIF 端口、本地授权降级） | camera_name(必填), password, ip, port, rtsp_port, rtsp_path, username |
| 5 | `disconnect_device` | 断开连接并释放资源 | camera_name(必填) |
| 6 | `request_cloud_auth` | 向本地授权服务器发起授权请求（模拟智慧云） | camera_name(必填), sn, device_ip, device_model |
| 7 | `poll_auth_status` | 轮询本地授权服务器检查授权状态 | camera_name(必填) |

### 2.2 音视频流 — `stream.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 8 | `get_audio_video_stream` | 获取实时视频流 URL 及元数据 | camera_name(必填), sub_stream |
| 9 | `capture_video_screenshot` | 截取当前画面保存为 JPEG | camera_name(必填), save_path |
| 10 | `toggle_recording` | 启动/停止本地录像 (MP4) | camera_name(必填), action(start\|stop), save_path |
| 11 | `manage_storage_status` | 查询/设置存储路径、格式与策略 | camera_name(必填), action(query\|set), path, format, policy |

### 2.3 云台控制 — `ptz.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 12 | `control_ptz` | 步进式控制云台方向（8方向，内置物理极限守护） | camera_name(必填), direction, speed, duration_seconds |
| 13 | `get_ptz_parameters` | 获取云台当前位置、范围和运动状态 | camera_name(必填) |
| 14 | `calibrate_ptz` | 执行云台物理校准（回初始位标定零位，10–30s） | camera_name(必填) |
| 15 | `stop_ptz` | 立即停止云台所有移动 | camera_name(必填) |

### 2.4 创维私有发现 — `discovery.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 16 | `discover_sky_devices` | 搜索局域网内的创维摄像头（私有协议组播） | timeout |

### 2.5 事件监听 — `events.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 17 | `manage_camera_events` | 统一事件入口（action 切换四种模式） | action(start\|stop\|poll\|wait), camera_name, protocols, debounce_seconds, limit, timeout_seconds |

---

## 三、内部函数清单（不暴露给 Agent）

### 3.1 PTZ 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `_move_to_position` | 移动云台到指定绝对坐标 (x, y, z) | 内部/二次开发；不在 MCP 注册 |

### 3.2 Discovery 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `send_tcp_command` | 通过 TCP 通道（端口 9010）发送 JSON 命令 | `connect_device`、`control_ptz`、`calibrate_ptz`、`get_ptz_parameters` 等高层工具内部调用 |

### 3.3 Device Management 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `_build_rtsp_url` | 构造完整 RTSP URL（自动注入凭据） | `get_audio_video_stream`、`capture_video_screenshot` |
| `generate_claw_id` | 生成 Claw ID（MAC + 时间戳） | `get_or_create_claw_id` |
| `get_or_create_claw_id` | 从 config.yaml 读取或生成并持久化 Claw ID | `request_cloud_auth`、`poll_auth_status` |
| `_onvif_digest_auth_header` | 生成 ONVIF WS-UsernameToken SOAP Header | `_onvif_post_with_auth` |
| `_onvif_post_with_auth` | POST SOAP 到 ONVIF endpoint（自动注入鉴权） | 事件监听 ONVIF 订阅/拉取 |
| `_probe_onvif_port` | 探测设备真实 ONVIF 服务端口 | `connect_device`、`start_event_monitor` |
| `_probe_stream_access` | 探测 RTSP 流是否可访问 | `connect_device`、`search_devices`(WS) |
| `_find_cached_camera` | 从 config.yaml 查找指定摄像头配置 | `connect_device`、流/录像/事件工具 |

### 3.4 Events 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `start_event_monitor` | 启动事件监听（后台线程） | `manage_camera_events`(action=start) |
| `stop_event_monitor` | 停止事件监听 | `manage_camera_events`(action=stop) |
| `get_pending_events` | 读取未消费事件并推进游标 | `manage_camera_events`(action=poll) |
| `wait_for_events` | 长轮询阻塞等待新事件 | `manage_camera_events`(action=wait) |
| `resume_persisted_monitors` | 按落盘意图恢复监听（进程重启后自动） | MCP server 启动时 + poll/wait 入口 |

### 3.5 Auth 模块（全部内部，不注册 MCP 工具）

| 子模块 | 函数 | 功能 |
|--------|------|------|
| token_manager | `parse_token` / `validate_token` / `destroy_token` / `is_token_expired` / `has_permission` | Token 生命周期管理 |
| cloud_client | `request_authorization` / `notify_connection` / `check_internet_available` | 智慧云 API 客户端 |
| session | `create_session` / `send_heartbeat` / `release_session` / `get_active_sessions` / `get_fifo_queue` / `auto_release_check` | 会话管理（心跳/释放/FIFO） |

---

## 四、调用关系图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MCP Server (mcp_server.py)                   │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  _call_tool(name, args)  →  路由到 toolkit 对应函数            │ │
│  └────────────────────────────────────────────────────────────────┘ │
└──────────────┬──────────────────────────────────────────────────────┘
               │ 调用
               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Toolkit (scripts/toolkit/)                       │
│                                                                     │
│  ┌─── device_mgmt ──────────────────────────────────────────────┐   │
│  │                                                              │   │
│  │  [MCP] get_registered_cameras ──→ _load_config_cameras       │   │
│  │  [MCP] register_camera ──→ 直接写 config.yaml                │   │
│  │  [MCP] search_devices ─┬─→ _search_ws_discovery_devices      │   │
│  │                        ├─→ _search_sky_devices               │   │
│  │                        │     └──→ discover_sky_devices       │   │
│  │                        │          (discovery 模块)            │   │
│  │                        └─→ _search_usb_devices (cv2)         │   │
│  │                                                              │   │
│  │  [MCP] connect_device ─┬─→ _find_cached_camera               │   │
│  │                        ├─→ _try_connect_with_password        │   │
│  │                        │     ├─→ _probe_onvif_port           │   │
│  │                        │     ├─→ send_tcp_command (discovery)│   │
│  │                        │     └─→ ONVIFCamera (onvif 库)      │   │
│  │                        ├─→ request_cloud_auth                │   │
│  │                        │     └─→ get_or_create_claw_id       │   │
│  │                        │          └─→ generate_claw_id       │   │
│  │                        ├─→ _probe_stream_access              │   │
│  │                        └─→ register_camera (自动缓存)        │   │
│  │                                                              │   │
│  │  [MCP] disconnect_device ──→ _connected_devices.pop()        │   │
│  │  [MCP] request_cloud_auth ──→ get_or_create_claw_id          │   │
│  │  [MCP] poll_auth_status ──→ get_or_create_claw_id            │   │
│  │                           ──→ _find_cached_camera             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── stream ───────────────────────────────────────────────────┐   │
│  │  [MCP] get_audio_video_stream ──→ _build_rtsp_url            │   │
│  │                                 ──→ _probe_stream_access      │   │
│  │                                 ──→ cv2.VideoCapture          │   │
│  │  [MCP] capture_video_screenshot ──→ _build_rtsp_url          │   │
│  │                                   ──→ cv2.VideoCapture/Write  │   │
│  │  [MCP] toggle_recording ──→ get_audio_video_stream (内部复用) │   │
│  │                           ──→ cv2.VideoWriter                 │   │
│  │  [MCP] manage_storage_status ──→ 直接操作文件系统             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── ptz ──────────────────────────────────────────────────────┐   │
│  │  [MCP] control_ptz ─┬─→ _onvif_ptz_move (ONVIF 优先)        │   │
│  │                     ├─→ _sk_ptz_move (私有协议兜底)          │   │
│  │                     │     └─→ _send_sk_ptz_command           │   │
│  │                     │          └─→ send_tcp_command           │   │
│  │                     ├─→ _guarded_wait (物理极限守护)         │   │
│  │                     │     └─→ _query_ptz_position             │   │
│  │                     │          └─→ _send_sk_ptz_command       │   │
│  │                     └─→ _onvif_stop / _sk_ptz_stop (自动停)  │   │
│  │                                                              │   │
│  │  [MCP] get_ptz_parameters ─┬─→ _onvif_get_status             │   │
│  │                            └─→ _sk_get_ptz_params            │   │
│  │  [MCP] calibrate_ptz ──→ _sk_ptz_calibrate                   │   │
│  │  [MCP] stop_ptz ─┬─→ _onvif_stop                             │   │
│  │                  └─→ _sk_ptz_stop                             │   │
│  │  [内部] _move_to_position ──→ _sk_ptz_move_to                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── discovery ────────────────────────────────────────────────┐   │
│  │  [MCP] discover_sky_devices ──→ 组播/广播 UDP 搜索           │   │
│  │  [内部] send_tcp_command ──→ TCP 通道 (端口 9010) JSON 通信  │   │
│  │  [内部] SkyDiscoveryListener ──→ 后台持续发现监听器           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── events ───────────────────────────────────────────────────┐   │
│  │  [MCP] manage_camera_events                                  │   │
│  │    ├─ action=start → start_event_monitor                     │   │
│  │    │     ├─→ _CameraEventMonitor.start()                     │   │
│  │    │     │     ├─→ ONVIF PullPoint 订阅 (后台线程)           │   │
│  │    │     │     │     └─→ _onvif_post_with_auth               │   │
│  │    │     │     └─→ RTSP 报警会话 (后台线程)                  │   │
│  │    │     │           └─→ _InterleavedFrameParser              │   │
│  │    │     └─→ _record_monitor_intent (落盘意图)               │   │
│  │    ├─ action=stop  → stop_event_monitor                      │   │
│  │    │     └─→ _clear_monitor_intent                           │   │
│  │    ├─ action=poll  → get_pending_events                      │   │
│  │    │     ├─→ resume_persisted_monitors (自动恢复)            │   │
│  │    │     └─→ _collect_pending (读磁盘+推游标)                │   │
│  │    └─ action=wait  → wait_for_events                         │   │
│  │          ├─→ resume_persisted_monitors (自动恢复)            │   │
│  │          └─→ _collect_pending (阻塞等待)                     │   │
│  │                                                              │   │
│  │  事件联动: _CameraEventMonitor._capture_snapshot             │   │
│  │    └─→ stream.capture_video_screenshot (同进程内部调用)      │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     Auth (scripts/auth/) — 全部内部                  │
│  token_manager: parse / validate / destroy / is_expired / has_perm  │
│  cloud_client:  request_authorization / notify_connection           │
│  session:       create / heartbeat / release / fifo_queue           │
│  注: 当前 device_mgmt 中的本地授权服务器直接通信，                   │
│      未走 auth 模块（auth 模块为智慧云方案预留）                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 五、跨模块依赖关系

```
device_mgmt ──imports──→ discovery  (send_tcp_command, discover_sky_devices, SK_TCP_PORT)
ptz         ──imports──→ discovery  (send_tcp_command, SK_TCP_PORT)
stream      ──imports──→ device_mgmt (_connected_devices, _find_cached_camera, _build_rtsp_url, _probe_stream_access)
events      ──imports──→ device_mgmt (_connected_devices, _find_cached_camera, _probe_onvif_port, _onvif_post_with_auth)
events      ──imports──→ stream      (capture_video_screenshot — 联动快照)
```

---

## 六、双协议策略说明

多个工具遵循 **ONVIF 优先、创维私有协议兜底** 的双协议策略：

| 工具 | ONVIF 路径 | 私有协议路径 |
|------|-----------|-------------|
| `control_ptz` | `ContinuousMove` via ONVIF PTZ Service | `SK_SETTING_SET_PTZ` via TCP 9010 |
| `get_ptz_parameters` | `GetStatus` via ONVIF PTZ Service | `SK_SETTING_GET_PTZ` via TCP 9010 |
| `stop_ptz` | `Stop` via ONVIF PTZ Service | `SK_SETTING_SET_PTZ cmd=stop` via TCP 9010 |
| `calibrate_ptz` | ❌ 不支持 | `SK_SETTING_SET_PTZ cmd=calibrate` |
| `_move_to_position` | ❌ 不支持 | `SK_SETTING_SET_PTZ cmd=move` |
| `manage_camera_events` | `CreatePullPointSubscription` + `PullMessages` | RTSP interleaved channel 0x65 报警 JSON |

---

## 七、安全边界

| 工具/函数 | 暴露类型 | 安全说明 |
|-----------|---------|---------|
| `send_tcp_command` | **内部函数** | 原始 TCP 通信能力不暴露给 Agent，仅由高层工具内部调用 |
| `_move_to_position` | **内部函数** | 绝对坐标移动降级为内部函数，不作为 MCP 工具 |
| `request_cloud_auth` | MCP 工具 | 不携带密码，仅发送 SN + ClawID 发起授权请求 |
| `connect_device` | MCP 工具 | 密码认证失败时降级到本地授权或提示用户输入 |
| `manage_camera_events` (start) | MCP 工具 | 后台线程仅用户显式确认后启动；行为限于报警订阅 + 白名单路径写入 |
| Auth 模块全部函数 | **内部函数** | 智慧云 Token/会话管理不暴露给 Agent |
