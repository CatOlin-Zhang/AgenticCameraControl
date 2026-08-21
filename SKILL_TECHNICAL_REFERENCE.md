# xpai-camera-control 技能包工具清单与调用关系

> 版本: 0.6.0 | 传输协议: MCP stdio | 生成日期: 2026-08-07

---

## 一、总览

| 分类 | MCP 外部工具 | 内部函数（不暴露给 Agent） |
|------|:---:|:---:|
| 设备管理 (device_mgmt) | 5 | 8 |
| 音视频流 (stream) | 6 | 0 |
| 云台控制 (ptz) | 4 | 1 |
| 事件监听 (events) | 1 | 5 |
| 补光控制 (illumination) | 1 | 6 |
| 图像设置 (image_settings) | 1 | 3 |
| 侦测追踪 (tracking) | 2 | 3 |
| **合计** | **20** | **26+** |

> 注: `discovery.py` 中的 `send_tcp_command`、`discover_sky_devices` 等为内部函数，由 device_mgmt / ptz / illumination 等模块间接调用，不注册为 MCP 工具。

---

## 二、MCP 外部工具清单（Agent 可调用）

### 2.1 设备管理 — `device_mgmt.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 1 | `get_registered_cameras` | 从 config.yaml 加载所有已注册摄像头配置 | 无 |
| 2 | `register_camera` | 将摄像头凭据持久化到 config.yaml | name(必填), ip, port, username, password, rtsp_port, rtsp_path, device_class, sn_code, pkdk 等 |
| 3 | `search_devices` | 搜索局域网摄像头（WS-Discovery / 创维私有 / USB） | timeout |
| 4 | `connect_device` | 连接摄像头（自动缓存凭据、探测 ONVIF 端口、内部云端授权） | camera_name(必填), password, ip, port, rtsp_port, rtsp_path, username, sn_code |
| 5 | `disconnect_device` | 断开连接并释放资源 | camera_name(必填) |

### 2.2 音视频流 — `stream.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 6 | `get_audio_video_stream` | 获取实时视频流 URL 及元数据 | camera_name(必填), sub_stream |
| 7 | `capture_video_screenshot` | 截取当前画面保存为 JPEG | camera_name(必填), save_path |
| 8 | `toggle_recording` | 启动/停止/查询本地录像 (MP4, ffmpeg remux) | camera_name(必填), action(start\|stop\|status), save_path, duration |
| 9 | `manage_storage_status` | 查询/设置存储路径、格式与策略 | camera_name(必填), action(query\|set), path, format, policy |
| 10 | `start_webrtc_stream` | 启动 go2rtc WebRTC 实时预览 | camera_name(必填), sub_stream, port |
| 11 | `stop_webrtc_stream` | 停止 go2rtc WebRTC 转流 | 无 |

### 2.3 云台控制 — `ptz.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 12 | `control_ptz` | 步进式控制云台方向（8方向+变焦，内置物理极限守护） | camera_name(必填), direction, speed, duration_seconds, degrees |
| 13 | `get_ptz_parameters` | 获取云台当前位置、范围和运动状态 | camera_name(必填) |
| 14 | `calibrate_ptz` | 执行云台物理校准（回初始位标定零位，10–30s） | camera_name(必填), action(set_home\|go_home) |
| 15 | `stop_ptz` | 立即停止云台所有移动 | camera_name(必填) |

### 2.4 事件监听 — `events.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 16 | `manage_camera_events` | 统一事件入口（action 切换四种模式） | action(start\|stop\|poll\|wait), camera_name, debounce_seconds, limit, timeout_seconds |

### 2.5 补光控制 — `illumination.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 17 | `manage_illumination` | 统一补光入口（action 切换查询/设置，双协议） | action(get\|set), camera_name, daynightmode, filllightmode, duration, brightnessmode, brightness, irmode, irbrightness, begintime, endtime, repeatdays, enable, whiteonvalue, whiteoffvalue, ironvalue, iroffvalue |

### 2.6 图像设置 — `image_settings.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 18 | `manage_image_settings` | 图像参数统一入口（get/set，双通道） | action(get\|set), camera_name, brightness, contrast, saturation, sharpness, flip, whitebalance, wdr, face_mode, plate_mode, restore_default |

### 2.7 侦测追踪 — `tracking.py`

| # | 工具名 | 功能 | 关键参数 |
|---|--------|------|----------|
| 19 | `query_tracking_capabilities` | 查询侦测追踪能力及当前配置值 | camera_name(必填), detect_type(human\|vehicle\|area\|motion\|line\|all) |
| 20 | `set_tracking` | 开启/关闭侦测追踪功能 | camera_name(必填), detect_type(human\|vehicle\|area\|motion\|line), enable, tracking, sensitivity_level |

---

## 三、内部函数清单（不暴露给 Agent）

### 3.1 PTZ 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `_move_to_position` | 移动云台到指定绝对坐标 (x, y, z) | 内部/二次开发；不在 MCP 注册 |

### 3.2 Discovery 模块（全部内部，不注册 MCP 工具）

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `send_tcp_command` | 通过 TCP 通道（端口 9010）发送 JSON 命令 | `connect_device`、`control_ptz`、`calibrate_ptz`、`get_ptz_parameters`、`manage_illumination` 等高层工具内部调用 |
| `discover_sky_devices` | 搜索局域网创维摄像头（私有协议组播） | `search_devices` 内部调用 |

### 3.3 Device Management 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `request_cloud_auth` | 发起云端授权请求（内部函数，v0.6.0 降级） | `connect_device` 内部自动调用 |
| `poll_auth_status` | 轮询云端授权状态（内部函数，v0.6.0 降级） | `connect_device` 内部自动调用 |
| `big_connect` | 一站式云端授权（内部函数，v0.6.0 降级） | `connect_device` 内部自动调用 |
| `_build_rtsp_url` | 构造完整 RTSP URL（自动注入凭据） | `get_audio_video_stream`、`capture_video_screenshot` |
| `_onvif_digest_auth_header` | 生成 ONVIF WS-UsernameToken SOAP Header | `_onvif_post_with_auth` |
| `_onvif_post_with_auth` | POST SOAP 到 ONVIF endpoint（自动注入鉴权） | 事件监听 ONVIF 订阅/拉取、illumination ONVIF 回退 |
| `_probe_onvif_port` | 探测设备真实 ONVIF 服务端口 | `connect_device`、`start_event_monitor` |
| `_probe_stream_access` | 探测 RTSP 流是否可访问 | `connect_device`、`search_devices`(WS) |
| `_find_cached_camera` | 从 config.yaml 查找指定摄像头配置 | `connect_device`、流/录像/事件/补光/图像/追踪工具 |
| `_probe_and_save_illumination` | 连接后探测并持久化补光能力 | `connect_device` |

### 3.4 Events 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `start_event_monitor` | 启动事件监听（后台线程） | `manage_camera_events`(action=start) |
| `stop_event_monitor` | 停止事件监听 | `manage_camera_events`(action=stop) |
| `get_pending_events` | 读取未消费事件并推进游标 | `manage_camera_events`(action=poll) |
| `wait_for_events` | 长轮询阻塞等待新事件 | `manage_camera_events`(action=wait) |
| `resume_persisted_monitors` | 按落盘意图恢复监听（进程重启后自动） | MCP server 启动时 + poll/wait 入口 |

### 3.5 Illumination 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `probe_illumination_capability` | 探测设备补光能力（双协议：TCP 优先 → ONVIF 回退） | `_probe_and_save_illumination`(device_mgmt) |
| `_sk_get_filllight_option` | 查询补光能力 (SK_SETTING_GET_FILLLIGHT_OPTION) | `probe_illumination_capability`、`manage_illumination`(get) |
| `_sk_get_filllight` | 查询当前补光设置 (SK_SETTING_GET_FILLLIGHT) | `manage_illumination`(get/set) |
| `_sk_set_filllight` | 设置补光参数 (SK_SETTING_SET_FILLLIGHT) | `manage_illumination`(set) |
| `_send_sk_filllight` | 通过 TCP 通道发送补光命令 | `_sk_get/set_filllight*` |
| `_get_device_connection` | 获取设备连接信息 | `_send_sk_filllight` |

### 3.6 Image Settings 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `_sk_get_image_option` | 查询图像参数能力 (SK HTTP) | `manage_image_settings`(get) |
| `_sk_get_image` | 查询当前图像设置 (SK HTTP) | `manage_image_settings`(get/set) |
| `_sk_set_image` | 设置图像参数 (SK HTTP) | `manage_image_settings`(set) |

### 3.7 Tracking 模块

| 函数名 | 功能 | 调用者 |
|--------|------|--------|
| `_sk_get_detect_option` | 查询侦测追踪能力 (SK HTTP) | `manage_tracking`(get) |
| `_sk_get_detect` | 查询当前侦测设置 (SK HTTP) | `manage_tracking`(get/set) |
| `_sk_set_detect` | 设置侦测追踪参数 (SK HTTP) | `manage_tracking`(set) |


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
│  │                        ├─→ _probe_stream_access              │   │
│  │                        ├─→ _probe_and_save_illumination      │   │
│  │                        │     └─→ probe_illumination_capability│  │
│  │                        ├─→ request_cloud_auth (内部)       │   │
│  │                        │     └─→ poll_auth_status (内部轮询) │   │
│  │                        └─→ register_camera (自动缓存)        │   │
│  │                                                              │   │
│  │  [MCP] disconnect_device ──→ _connected_devices.pop()        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── stream ───────────────────────────────────────────────────┐   │
│  │  [MCP] get_audio_video_stream ──→ _build_rtsp_url            │   │
│  │                                 ──→ _probe_stream_access      │   │
│  │                                 ──→ cv2.VideoCapture          │   │
│  │  [MCP] capture_video_screenshot ──→ _build_rtsp_url          │   │
│  │                                   ──→ cv2.VideoCapture/Write  │   │
│  │  [MCP] toggle_recording ──→ ffmpeg 子进程 (-c:v copy remux)  │   │
│  │  [MCP] manage_storage_status ──→ 直接操作文件系统             │   │
│  │  [MCP] start_webrtc_stream ──→ go2rtc 子进程                  │   │
│  │  [MCP] stop_webrtc_stream ──→ 终止 go2rtc 进程              │   │
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
│                                                                     │
│  ┌─── illumination ────────────────────────────────────────────┐   │
│  │  [MCP] manage_illumination                                   │   │
│  │    ├─ 路由: 有 IP → 尝试创维私有协议 (TCP 9010)           │   │
│  │    │     ├─ _sk_get_filllight_option → capabilities          │   │
│  │    │     ├─ _sk_get_filllight → current_settings             │   │
│  │    │     └─ _sk_set_filllight (GET→merge→SET)                │   │
│  │    │           └─→ send_tcp_command (discovery 模块)         │   │
│  │    │     TCP 成功 → 回写 tcp_port 到 _connected_devices    │   │
│  │    └─ 路由: TCP 失败 → ONVIF Imaging Service 回退         │   │
│  │          ├─ _imaging_post → _onvif_post_with_auth            │   │
│  │          ├─ _parse_illumination_modes_from_move_options      │   │
│  │          └─ _parse_current_mode_from_imaging_settings        │   │
│  │                                                              │   │
│  │  [内部] probe_illumination_capability                        │   │
│  │    ├─ 尝试 TCP: send_tcp_command (SK_SETTING_GET_FILLLIGHT_OPTION)│
│  │    └─ 回退 ONVIF: _imaging_post (GetMoveOptions)             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── image_settings ─────────────────────────────────────────┐   │
│  │  [MCP] manage_image_settings                                │   │
│  │    ├─ 路由: SK HTTP 私有协议 (TCP 9010) 优先           │   │
│  │    │     ├─ _sk_get_image_option → capabilities             │   │
│  │    │     ├─ _sk_get_image → current_settings                │   │
│  │    │     └─ _sk_set_image (GET→merge→SET)                  │   │
│  │    └─ 路由: ONVIF Imaging Service 回退                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─── tracking ───────────────────────────────────────────────┐   │
│  │  [MCP] query_tracking_capabilities                          │   │
│  │    └─ _sk_get_detect_option → 侦测能力 + 当前值            │   │
│  │  [MCP] set_tracking                                         │   │
│  │    └─ _sk_set_detect (enable/tracking/sensitivity)          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

```

---

## 五、跨模块依赖关系

```
device_mgmt ──imports──→ discovery  (send_tcp_command, discover_sky_devices, SK_TCP_PORT)
device_mgmt ──imports──→ illumination (probe_illumination_capability)
ptz         ──imports──→ discovery  (send_tcp_command, SK_TCP_PORT)
stream      ──imports──→ device_mgmt (_connected_devices, _find_cached_camera, _build_rtsp_url, _probe_stream_access)
events      ──imports──→ device_mgmt (_connected_devices, _find_cached_camera, _probe_onvif_port, _onvif_post_with_auth)
events      ──imports──→ stream      (capture_video_screenshot — 联动快照)
illumination──imports──→ discovery   (send_tcp_command, SK_TCP_PORT)
illumination──imports──→ device_mgmt (_connected_devices, _find_cached_camera, _onvif_post_with_auth)
image_settings──imports→ discovery   (send_tcp_command, SK_TCP_PORT)
image_settings──imports→ device_mgmt (_connected_devices, _find_cached_camera, _onvif_post_with_auth)
tracking    ──imports──→ discovery   (send_tcp_command, SK_TCP_PORT)
tracking    ──imports──→ device_mgmt (_connected_devices, _find_cached_camera)
```

---

## 六、双协议策略说明

多个工具遵循 **ONVIF 优先、创维私有协议兜底** 的双协议策略（illumination 方向相反：私有协议优先、ONVIF 回退）：

| 工具 | ONVIF 路径 | 私有协议路径 |
|------|-----------|-------------|
| `control_ptz` | `ContinuousMove` via ONVIF PTZ Service | `SK_SETTING_SET_PTZ` via TCP 9010 |
| `get_ptz_parameters` | `GetStatus` via ONVIF PTZ Service | `SK_SETTING_GET_PTZ` via TCP 9010 |
| `stop_ptz` | `Stop` via ONVIF PTZ Service | `SK_SETTING_SET_PTZ cmd=stop` via TCP 9010 |
| `calibrate_ptz` | ❌ 不支持 | `SK_SETTING_SET_PTZ cmd=calibrate` |
| `_move_to_position` | ❌ 不支持 | `SK_SETTING_SET_PTZ cmd=move` |
| `manage_camera_events` | `CreatePullPointSubscription` + `PullMessages` | RTSP interleaved channel 0x65 报警 JSON |
| `manage_illumination` | `GetMoveOptions` / `GetImagingSettings` / `SetImagingSettings` (回退) | `SK_SETTING_GET_FILLLIGHT_OPTION` / `GET_FILLLIGHT` / `SET_FILLLIGHT` (主路径, always-try-TCP) |
| `manage_image_settings` | `GetImagingSettings` / `SetImagingSettings` (回退) | `SK_SETTING_GET_IMAGE_OPTION` / `GET_IMAGE` / `SET_IMAGE` (主路径, always-try-TCP) |
| `query_tracking_capabilities` | ❌ 不支持 | `SK_SETTING_GET_DETECT_OPTION` / `GET_DETECT` (SK HTTP) |
| `set_tracking` | ❌ 不支持 | `SK_SETTING_SET_DETECT` (SK HTTP) |

---

## 七、安全边界

| 工具/函数 | 暴露类型 | 安全说明 |
|-----------|---------|---------|
| `send_tcp_command` | **内部函数** | 原始 TCP 通信能力不暴露给 Agent，仅由高层工具内部调用 |
| `_move_to_position` | **内部函数** | 绝对坐标移动降级为内部函数，不作为 MCP 工具 |
| `connect_device` | MCP 工具 | 密码认证失败时提示用户输入正确密码 |
| `manage_camera_events` (start) | MCP 工具 | 后台线程仅用户显式确认后启动；行为限于报警订阅 + 白名单路径写入 |
| `manage_illumination` (set) | MCP 工具 | 硬件参数修改，需用户确认；set 操作自动 GET→merge→SET，不覆盖未指定参数 |
| `manage_image_settings` (set) | MCP 工具 | 硬件参数修改，需用户确认；读-校验-合并-写-回读 |
| `set_tracking` | MCP 工具 | 硬件设置修改，需用户确认；修改侦测追踪功能开关 |
