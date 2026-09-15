# XPAI Camera Control — MCP Server 工具函数技术文档

> **版本**: v0.6.0 | **传输协议**: stdio (JSON-RPC) | **服务名**: `xpai-camera-control`

所有工具函数通过 MCP (Model Context Protocol) 暴露，调用方发送 JSON-RPC 请求，返回值统一序列化为 JSON 对象。调用异常时返回 `{"success": false, "error": "<错误信息>"}`。

---

## 目录

1. [设备管理 (Device Management)](#1-设备管理)
2. [音视频流与存储 (Stream)](#2-音视频流与存储)
3. [云台控制 (PTZ)](#3-云台控制)
4. [事件监听 (Events)](#4-事件监听)
5. [WebRTC 实时预览](#5-webrtc-实时预览)
6. [补光控制 (Illumination)](#6-补光控制)
7. [图像参数设置 (Image Settings)](#7-图像参数设置)
8. [侦测追踪 (Tracking)](#8-侦测追踪)

---

## 1. 设备管理

### `get_registered_cameras`

从 `config.yaml` 加载所有已注册摄像头的配置信息（含凭据）。不扫描网络，仅读取本地保存的记录。**会话开始时首先调用**。

**参数**: 无

**返回值**: `CameraConfig[]`

| 字段                   | 类型       | 说明                                         |
|----------------------|----------|--------------------------------------------|
| `name`               | string   | 摄像头名称                                      |
| `connection_type`    | string   | `"onvif"` / `"usb"`                        |
| `ip`                 | string   | IP 地址                                      |
| `port`               | int      | ONVIF 端口（0=未知）                             |
| `username`           | string   | 登录用户名                                      |
| `password`           | string   | 登录密码                                       |
| `rtsp_port`          | int      | RTSP 端口                                    |
| `rtsp_path`          | string   | 主流路径                                       |
| `rtsp_sub_path`      | string   | 子流路径                                       |
| `device_class`       | string   | `"password_required"` / `"direct_connect"` |
| `sn_code`            | string   | 序列号                                        |
| `pkdk`               | string   | 设备公钥标识                                     |
| `illumination_modes` | string[] | 支持的补光模式列表                                  |

---

### `register_camera`

将摄像头凭据写入 `config.yaml` 持久化。支持重命名：当传入新名称但 IP 或 SN 与已有条目匹配时，自动替换旧名称。通常由 `connect_device` 内部自动调用。

**参数**:

| 参数                | 类型     | 必填 | 默认值                | 说明                                         |
|-------------------|--------|:--:|--------------------|--------------------------------------------|
| `name`            | string | ✅  | —                  | 摄像头唯一名称                                    |
| `ip`              | string |    | `""`               | IP 地址                                      |
| `port`            | int    |    | `0`                | ONVIF 端口（只传验证过的真实端口）                       |
| `username`        | string |    | `"admin"`          | 登录用户名                                      |
| `password`        | string |    | `""`               | 登录密码                                       |
| `rtsp_port`       | int    |    | `554`              | RTSP 端口                                    |
| `rtsp_path`       | string |    | `"/md0_0"`         | 主流路径                                       |
| `device_class`    | string |    | `"direct_connect"` | `"password_required"` / `"direct_connect"` |
| `connection_type` | string |    | `"onvif"`          | `"onvif"` / `"usb"`                        |
| `sn_code`         | string |    | `""`               | 序列号                                        |
| `pkdk`            | string |    | `""`               | 设备公钥标识                                     |
| `rtsp_sub_path`   | string |    | `"/md0_1"`         | 子流路径                                       |

**返回值**: `RegisterResult`

| 字段              | 类型     | 说明          |
|-----------------|--------|-------------|
| `success`       | bool   | 注册是否成功      |
| `camera_name`   | string | 注册的摄像头名称    |
| `error_message` | string | 失败原因（成功时为空） |

---

### `search_devices`

扫描局域网发现可用摄像头（WS-Discovery + 创维私有协议双协议搜索，按 IP 去重）。**发现多个设备时必须将全部设备逐一展示给用户，不得省略。**

**参数**:

| 参数        | 类型     | 必填 | 默认值    | 说明   |
|-----------|--------|:--:|--------|------|
| `timeout` | number |    | `15.0` | 超时秒数 |

**返回值**: `SearchResult`（附加 `device_count` 和 `_display_instruction`）

| 字段                     | 类型                 | 说明         |
|------------------------|--------------------|------------|
| `success`              | bool               | 搜索是否成功     |
| `devices`              | DiscoveredDevice[] | 发现的设备列表    |
| `device_count`         | int                | 设备数量（附加字段） |
| `_display_instruction` | string             | 展示指令（附加字段） |
| `error_message`        | string             | 失败原因       |

**DiscoveredDevice 字段**:

| 字段                 | 类型     | 说明                                         |
|--------------------|--------|--------------------------------------------|
| `ip`               | string | IP 地址                                      |
| `onvif_port`       | int    | ONVIF 端口（0=未知）                             |
| `rtsp_port`        | int    | RTSP 端口                                    |
| `device_class`     | string | `"password_required"` / `"direct_connect"` |
| `sn_code`          | string | 设备序列号                                      |
| `model`            | string | 设备型号                                       |
| `manufacturer`     | string | 厂商                                         |
| `sky_subtype`      | string | 设备子类型: `1`枪机/`2`球机/`3`半球/`5`摇头机/`6`枪球      |
| `sky_name`         | string | 设备名称                                       |
| `sky_channels`     | int    | 通道数（0=非创维, 1=单目, 2=双目）                     |
| `sky_hw_version`   | string | 硬件版本                                       |
| `sky_sw_version`   | string | 软件版本                                       |
| `sky_mac`          | string | MAC 地址                                     |
| `discovery_method` | string | 发现方式: `"ws_discovery"` / `"sky_discovery"` |

---

### `connect_device`

连接摄像头。自动加载缓存凭据（TCP/ONVIF/RTSP 三通道验证）；缓存失效时先尝试云端重新授权，仍失败再请用户输入。

**参数**:

| 参数            | 类型     | 必填 | 默认值 | 说明                |
|---------------|--------|:--:|-----|-------------------|
| `camera_name` | string | ✅  | —   | 摄像头名称             |
| `password`    | string |    | —   | 用户密码（可选）          |
| `ip`          | string |    | —   | 设备 IP             |
| `port`        | int    |    | —   | ONVIF 端口（不传则自动探测） |
| `rtsp_port`   | int    |    | —   | RTSP 端口           |
| `rtsp_path`   | string |    | —   | RTSP 路径           |
| `username`    | string |    | —   | 登录用户名             |
| `sn_code`     | string |    | —   | 设备 SN             |

**返回值**: `ConnectResult`

| 字段               | 类型     | 说明                                                                                                     |
|------------------|--------|--------------------------------------------------------------------------------------------------------|
| `success`        | bool   | 连接是否成功                                                                                                 |
| `status`         | string | `"connected"` / `"needs_password"` / `"no_sn"` / `"failed"` / `"auth_rejected"` / `"cloud_pwd_failed"` |
| `auth_method`    | string | 认证方式: `"password"` / `"direct"`                                                                        |
| `needs_password` | bool   | 是否需要用户提供密码                                                                                             |
| `onvif_port`     | int    | 验证过的 ONVIF 端口（0=未验证）                                                                                   |
| `error_message`  | string | 失败原因                                                                                                   |

**status 状态处理**:
- `connected` → 已连接，可操作
- `needs_password` → 请用户提供密码后重新调用
- `auth_rejected` → 云端拒绝授权
- `cloud_pwd_failed` → 云端密码验证不通过，请用户输入正确密码

---

### `disconnect_device`

断开摄像头连接，释放所有资源。

**参数**:

| 参数            | 类型     | 必填 | 说明    |
|---------------|--------|:--:|-------|
| `camera_name` | string | ✅  | 摄像头名称 |

**返回值**: `DisconnectResult`

| 字段                 | 类型     | 说明        |
|--------------------|--------|-----------|
| `success`          | bool   | 断开是否成功    |
| `session_released` | bool   | 是否释放了云端会话 |
| `error_message`    | string | 失败原因      |

---

## 2. 音视频流与存储

### `get_audio_video_stream`

获取摄像头的 RTSP 实时视频流 URL 及元数据。仅返回流地址，不抓取画面。

**参数**:

| 参数            | 类型     | 必填 | 默认值     | 说明         |
|---------------|--------|:--:|---------|------------|
| `camera_name` | string | ✅  | —       | 摄像头名称      |
| `sub_stream`  | bool   |    | `false` | 使用子码流（低画质） |

**返回值**: `StreamResult`

| 字段              | 类型     | 说明                           |
|-----------------|--------|------------------------------|
| `success`       | bool   | 是否成功                         |
| `stream_url`    | string | RTSP 流地址（含凭据）                |
| `codec`         | string | 编码格式（如 `"H.264"`, `"H.265"`） |
| `resolution`    | string | 分辨率（如 `"1920x1080"`）         |
| `fps`           | float  | 帧率                           |
| `bitrate`       | int    | 码率                           |
| `error_message` | string | 失败原因                         |

---

### `capture_video_screenshot`

从视频流中截取一帧画面保存为 JPEG 图片（单帧快照）。默认保存到 `snapshots/` 目录。

**参数**:

| 参数            | 类型     | 必填 | 默认值          | 说明          |
|---------------|--------|:--:|--------------|-------------|
| `camera_name` | string | ✅  | —            | 摄像头名称       |
| `save_path`   | string |    | `snapshots/` | 保存目录或完整文件路径 |

**返回值**: `ScreenshotResult`

| 字段              | 类型     | 说明       |
|-----------------|--------|----------|
| `success`       | bool   | 是否成功     |
| `file_path`     | string | 截图文件路径   |
| `width`         | int    | 图片宽度（像素） |
| `height`        | int    | 图片高度（像素） |
| `error_message` | string | 失败原因     |

---

### `toggle_recording`

启动、停止或查询本地 MP4 录像。默认保存到 `video/` 目录。

**参数**:

| 参数            | 类型     | 必填 | 默认值      | 说明                                |
|---------------|--------|:--:|----------|-----------------------------------|
| `camera_name` | string | ✅  | —        | 摄像头名称                             |
| `action`      | string | ✅  | —        | `"start"` / `"stop"` / `"status"` |
| `save_path`   | string |    | `video/` | 录像保存目录                            |
| `duration`    | number |    | —        | 录像时长（秒），仅 `start` 时有效，设置后自动停止     |

**返回值**: `RecordingResult`

| 字段                 | 类型     | 说明        |
|--------------------|--------|-----------|
| `success`          | bool   | 是否成功      |
| `is_recording`     | bool   | 当前是否正在录像  |
| `file_path`        | string | 录像文件路径    |
| `duration_seconds` | float  | 录像时长（秒）   |
| `auto_stop`        | bool   | 是否设置了自动停止 |
| `error_message`    | string | 失败/异常原因   |

**注意**:
- 多台设备同时录像时逐台调用（每台间隔 2-3 秒），避免并发启动失败
- 长时间录像（>10 分钟）可能因网络波动中断，建议定期用 `status` 巡检
- 录像异常时可查看与视频同名的 `.log` 文件获取 ffmpeg 退出原因

---

### `manage_storage_status`

查询录像/截图的磁盘占用与可用空间，或设置存储路径、文件格式与存储策略。

**参数**:

| 参数            | 类型     | 必填 | 默认值       | 说明                                                         |
|---------------|--------|:--:|-----------|------------------------------------------------------------|
| `camera_name` | string | ✅  | —         | 摄像头名称                                                      |
| `action`      | string |    | `"query"` | `"query"` / `"set"`                                        |
| `path`        | string |    | —         | 存储路径（仅 `set`）                                              |
| `format`      | string |    | —         | `"mp4"` / `"avi"` / `"jpg"`（仅 `set`）                       |
| `policy`      | string |    | —         | `"overwrite"` / `"stop_when_full"` / `"circular"`（仅 `set`） |

**返回值**: `StorageResult`

| 字段                   | 类型     | 说明       |
|----------------------|--------|----------|
| `success`            | bool   | 是否成功     |
| `used_space_mb`      | float  | 已用空间（MB） |
| `available_space_mb` | float  | 可用空间（MB） |
| `storage_path`       | string | 当前存储路径   |
| `format`             | string | 当前文件格式   |
| `policy`             | string | 当前存储策略   |
| `error_message`      | string | 失败原因     |

---

## 3. 云台控制

### `control_ptz`

控制云台转动方向或变焦。支持 8 方向和变焦。内置物理极限保护，到达边界时自动提前停止。

**参数**:

| 参数                 | 类型     | 必填 | 默认值   | 说明                                         |
|--------------------|--------|:--:|-------|--------------------------------------------|
| `camera_name`      | string | ✅  | —     | 摄像头名称                                      |
| `direction`        | string | ✅  | —     | 方向，见下表                                     |
| `speed`            | number |    | `0.5` | 速度 0.0–1.0（当前 SK 方向命令不支持调速）                |
| `duration_seconds` | number |    | —     | 转动时长（秒），与 `degrees` 二选一；都不传默认 `1.0`        |
| `degrees`          | number |    | —     | 转动角度（按 1秒=34度 换算），与 `duration_seconds` 二选一 |

**direction 可选值**: `up` / `down` / `left` / `right` / `upleft` / `upright` / `downleft` / `downright` / `zoom_in` / `zoom_out`

**返回值**: `PTZMoveResult`

| 字段                           | 类型     | 说明                                               |
|------------------------------|--------|--------------------------------------------------|
| `success`                    | bool   | 是否成功                                             |
| `protocol`                   | string | 使用的协议（`"sky_private"`）                           |
| `current_pan`                | float  | 当前水平位置                                           |
| `current_tilt`               | float  | 当前垂直位置                                           |
| `current_zoom`               | float  | 当前变焦倍数                                           |
| `requested_duration_seconds` | float  | 请求的移动时长                                          |
| `actual_duration_seconds`    | float  | 实际移动时长                                           |
| `limit_reached`              | bool   | 是否到达物理极限                                         |
| `degrees`                    | float  | 角度模式时的请求角度                                       |
| `method`                     | string | 执行方式: `"sk_time"` / `"sk_degrees"` / `"sk_zoom"` |
| `error_message`              | string | 失败原因                                             |

---

### `get_ptz_parameters`

读取云台当前位置坐标、运动范围和状态（只读查询）。

**参数**:

| 参数            | 类型     | 必填 | 说明    |
|---------------|--------|:--:|-------|
| `camera_name` | string | ✅  | 摄像头名称 |

**返回值**: `PTZParameters`

| 字段              | 类型     | 说明     |
|-----------------|--------|--------|
| `pan`           | float  | 当前水平位置 |
| `tilt`          | float  | 当前垂直位置 |
| `zoom`          | float  | 当前变焦倍数 |
| `pan_range`     | float  | 水平运动范围 |
| `tilt_range`    | float  | 垂直运动范围 |
| `zoom_range`    | float  | 变焦范围   |
| `is_moving`     | bool   | 是否正在移动 |
| `protocol`      | string | 使用的协议  |
| `error_message` | string | 查询失败原因 |

---

### `calibrate_ptz`

云台物理校准与归位。硬件校准操作，约 10-30 秒。

**参数**:

| 参数            | 类型     | 必填 | 默认值          | 说明                                        |
|---------------|--------|:--:|--------------|-------------------------------------------|
| `camera_name` | string | ✅  | —            | 摄像头名称                                     |
| `action`      | string |    | `"set_home"` | `"set_home"` 校准并存位 / `"go_home"` 回到存储的初始位 |

**返回值**: `CalibrateResult`

| 字段              | 类型     | 说明                      |
|-----------------|--------|-------------------------|
| `success`       | bool   | 是否成功                    |
| `protocol`      | string | 使用的协议                   |
| `action`        | string | 执行的操作                   |
| `home_position` | string | Home 位坐标（如 `"x=0,y=0"`） |
| `error_message` | string | 失败原因                    |

---

### `stop_ptz`

立即紧急停止云台所有正在进行的移动。

**参数**:

| 参数            | 类型     | 必填 | 说明    |
|---------------|--------|:--:|-------|
| `camera_name` | string | ✅  | 摄像头名称 |

**返回值**: `PTZMoveResult`

| 字段              | 类型     | 说明              |
|-----------------|--------|-----------------|
| `success`       | bool   | 是否成功停止          |
| `protocol`      | string | `"sky_private"` |
| `error_message` | string | 失败原因            |

---

## 4. 事件监听

### `manage_camera_events`

摄像头告警事件统一管理入口，通过 `action` 切换四种工作模式。

**参数**:

| 参数                 | 类型     | 必填 | 默认值   | 说明                                               |
|--------------------|--------|:--:|-------|--------------------------------------------------|
| `action`           | string | ✅  | —     | `"start"` / `"stop"` / `"poll"` / `"wait"`       |
| `camera_name`      | string |    | —     | 摄像头名称（`start`/`stop` 必填；`poll`/`wait` 省略则面向全部相机） |
| `debounce_seconds` | number |    | `5.0` | 去重窗口（秒，仅 `start`）                                |
| `limit`            | int    |    | `100` | 单次最多返回事件数（仅 `poll`）                              |
| `timeout_seconds`  | number |    | `60`  | 阻塞超时（秒，上限 60，仅 `wait`）                           |

**返回值**:

- **`start` / `stop`** → `EventMonitorResult`:

| 字段                | 类型       | 说明                        |
|-------------------|----------|---------------------------|
| `success`         | bool     | 操作是否成功                    |
| `camera_name`     | string   | 摄像头名称                     |
| `running`         | bool     | 监听是否在运行                   |
| `active_channels` | string[] | 已激活的协议通道（如 `["private"]`） |
| `error_message`   | string   | 失败原因                      |

- **`poll` / `wait`** → `PendingEventsResult`:

| 字段              | 类型            | 说明          |
|-----------------|---------------|-------------|
| `success`       | bool          | 操作是否成功      |
| `events`        | CameraEvent[] | 本次消费的事件列表   |
| `remaining`     | int           | 存储中尚未消费的事件数 |
| `monitors`      | object        | 各监听器运行状态    |
| `error_message` | string        | 失败原因        |

**CameraEvent 字段**:

| 字段               | 类型       | 说明                                                                                                     |
|------------------|----------|--------------------------------------------------------------------------------------------------------|
| `schema_version` | string   | `"1.0"`                                                                                                |
| `event_id`       | string   | 事件唯一 ID                                                                                                |
| `event_type`     | string   | 归一化事件类型: `motion`/`human`/`vehicle`/`tamper`/`region_intrusion`/`line_crossing`/`high_temp`/`low_temp` |
| `camera_id`      | string   | 摄像头注册名                                                                                                 |
| `camera_name`    | string   | 展示名                                                                                                    |
| `timestamp`      | string   | ISO 8601 时间戳                                                                                           |
| `severity`       | string   | `"info"` / `"warning"` / `"critical"`                                                                  |
| `title`          | string   | 人可读标题                                                                                                  |
| `message`        | string   | 人可读正文                                                                                                  |
| `label`          | string?  | 目标类别（如 `"person"`, `"car"`），无法提取时为 `null`                                                              |
| `confidence`     | float?   | 置信度，协议未提供时为 `null`                                                                                     |
| `snapshot_path`  | string   | 联动快照路径（限流窗口内可能为空）                                                                                      |
| `tags`           | string[] | 标签（如 `["guardian"]`）                                                                                   |

---

## 5. WebRTC 实时预览

### `start_webrtc_stream`

启动 WebRTC 实时预览，将 RTSP 流转为浏览器可直接播放的 WebRTC 流，返回 HTTP 访问地址。

**参数**:

| 参数            | 类型     | 必填 | 默认值     | 说明         |
|---------------|--------|:--:|---------|------------|
| `camera_name` | string | ✅  | —       | 摄像头名称      |
| `sub_stream`  | bool   |    | `false` | 使用子码流（低画质） |
| `port`        | int    |    | `1984`  | Web UI 端口  |

**返回值**: `WebRTCResult`

| 字段              | 类型     | 说明                                   |
|-----------------|--------|--------------------------------------|
| `success`       | bool   | 是否成功                                 |
| `web_url`       | string | 浏览器访问地址（如 `"http://localhost:1984"`） |
| `rtsp_url`      | string | 源 RTSP 地址                            |
| `error_message` | string | 失败原因                                 |

---

### `stop_webrtc_stream`

停止 WebRTC 实时预览，关闭转流进程。

**参数**: 无

**返回值**: `bool`（`true` 表示已停止）

---

## 6. 补光控制

### `manage_illumination`

查询或设置摄像头补光与夜视模式。仅支持 `daynightmode`（日夜模式）与 `filllightmode`（补光方式）两项调节。控制物理补光硬件，与 `manage_image_settings` 不同。

**参数**:

| 参数              | 类型         | 必填 | 默认值 | 说明                |
|-----------------|------------|:--:|-----|-------------------|
| `action`        | string     | ✅  | —   | `"get"` / `"set"` |
| `camera_name`   | string     | ✅  | —   | 摄像头名称             |
| `daynightmode`  | int/string |    | —   | 日夜模式（仅 `set`）     |
| `filllightmode` | int/string |    | —   | 补光方式（仅 `set`）     |

**daynightmode 取值**:

| 值 | 别名             | 说明   |
|:-:|----------------|------|
| 0 | `day` / `白天`   | 白天模式 |
| 1 | `night` / `夜晚` | 夜晚模式 |
| 2 | `auto` / `自动`  | 自动模式 |
| 3 | `timer` / `定时` | 定时模式 |
| 4 | `smart` / `智能` | 智能模式 |

**filllightmode 取值**:

| 值 | 别名               | 说明   |
|:-:|------------------|------|
| 0 | `color` / `全彩`   | 全彩模式 |
| 1 | `ir` / `红外`      | 红外模式 |
| 2 | `smart` / `智能夜视` | 智能夜视 |

**返回值**:

- **`get`** → `FilllightQueryResult`:

| 字段             | 类型     | 说明                                                                    |
|----------------|--------|-----------------------------------------------------------------------|
| `ok`           | bool   | 是否成功                                                                  |
| `camera`       | string | 摄像头名称                                                                 |
| `channel`      | string | 实际生效协议通道（`"sk"`）                                                      |
| `capabilities` | array  | 能力列表（含 `name`/`label`/`min`/`max`/`current`/`current_text`/`options`） |
| `current`      | object | 当前值（如 `{"daynightmode": 2, "filllightmode": 0}`）                      |
| `error_code`   | string | 错误码                                                                   |
| `message`      | string | 说明信息                                                                  |

- **`set`** → `FilllightSetResult`:

| 字段           | 类型     | 说明            |
|--------------|--------|---------------|
| `ok`         | bool   | 是否成功          |
| `camera`     | string | 摄像头名称         |
| `channel`    | string | `"sk"`        |
| `updated`    | object | 本次生效的字段（回读确认） |
| `current`    | object | 设置后回读的当前值     |
| `verified`   | bool   | 是否回读验证        |
| `error_code` | string | 错误码           |
| `message`    | string | 说明信息          |

---

## 7. 图像参数设置

### `manage_image_settings`

查询或设置摄像头画面参数。纯 SK 私有协议单通道，无 ONVIF 回退。调节画面成像参数，与 `manage_illumination`（控制物理补光灯）不同。

**参数**:

| 参数            | 类型     | 必填 | 默认值 | 说明                |
|---------------|--------|:--:|-----|-------------------|
| `action`      | string | ✅  | —   | `"get"` / `"set"` |
| `camera_name` | string | ✅  | —   | 摄像头名称             |
| `brightness`  | int    |    | —   | 亮度（仅 `set`）       |
| `contrast`    | int    |    | —   | 对比度（仅 `set`）      |
| `saturation`  | int    |    | —   | 饱和度（仅 `set`）      |
| `sharpness`   | int    |    | —   | 锐度（仅 `set`）       |
| `flip`        | int    |    | —   | 图像翻转（仅 `set`），见下表 |

**flip 取值**:

| 值 | 说明   |
|:-:|------|
| 0 | 正常   |
| 1 | 对角翻转 |
| 2 | 水平翻转 |
| 3 | 垂直翻转 |

**返回值**:

- **`get`** → `ImageQueryResult`:

| 字段             | 类型     | 说明                                                                    |
|----------------|--------|-----------------------------------------------------------------------|
| `ok`           | bool   | 是否成功                                                                  |
| `camera`       | string | 摄像头名称                                                                 |
| `channel`      | string | `"sk"`                                                                |
| `capabilities` | array  | 能力列表（含 `name`/`label`/`min`/`max`/`current`/`current_text`/`options`） |
| `current`      | object | 当前值（如 `{"brightness": 128, "contrast": 50, ...}`）                     |
| `error_code`   | string | 错误码                                                                   |
| `message`      | string | 说明信息                                                                  |

- **`set`** → `ImageSetResult`:

| 字段           | 类型     | 说明            |
|--------------|--------|---------------|
| `ok`         | bool   | 是否成功          |
| `camera`     | string | 摄像头名称         |
| `channel`    | string | `"sk"`        |
| `updated`    | object | 本次生效的字段（回读确认） |
| `current`    | object | 设置后回读的全量当前值   |
| `error_code` | string | 错误码           |
| `message`    | string | 说明信息          |

---

## 8. 侦测追踪

### `query_tracking_capabilities`

查询摄像头的智能侦测与追踪能力，返回各侦测类型的可用参数和当前设置值。只读查询。

**参数**:

| 参数            | 类型     | 必填 | 默认值     | 说明       |
|---------------|--------|:--:|---------|----------|
| `camera_name` | string | ✅  | —       | 摄像头名称    |
| `detect_type` | string |    | `"all"` | 侦测类型，见下表 |

**detect_type 可选值**: `human`(人形) / `vehicle`(车辆) / `area`(区域) / `motion`(移动) / `line`(越界) / `all`(全部)

**返回值**: `TrackingQueryResult`

| 字段                     | 类型     | 说明                                                |
|------------------------|--------|---------------------------------------------------|
| `ok`                   | bool   | 是否成功                                              |
| `camera`               | string | 摄像头名称                                             |
| `channel`              | string | `"sk"`                                            |
| `human_capabilities`   | array  | 人形侦测能力（含 `name`/`label`/`current`/`current_text`） |
| `human_current`        | object | 人形侦测当前值                                           |
| `vehicle_capabilities` | array  | 车辆侦测能力                                            |
| `vehicle_current`      | object | 车辆侦测当前值                                           |
| `area_capabilities`    | array  | 区域侦测能力                                            |
| `area_current`         | object | 区域侦测当前值                                           |
| `motion_capabilities`  | array  | 移动侦测能力                                            |
| `motion_current`       | object | 移动侦测当前值                                           |
| `line_capabilities`    | array  | 越界侦测能力                                            |
| `line_current`         | object | 越界侦测当前值                                           |
| `error_code`           | string | 错误码                                               |
| `message`              | string | 查询结果摘要                                            |

**可设置字段**（各侦测类型通用）: `enable`(使能开关) / `tracking`(追踪) / `level`(灵敏度等级 0-3)

---

### `set_tracking`

开启或关闭摄像头的智能侦测与追踪功能。修改硬件设置，需用户确认。仅传需修改的参数，未传的参数保持不变。

**参数**:

| 参数                  | 类型     | 必填 | 默认值 | 说明                                                         |
|---------------------|--------|:--:|-----|------------------------------------------------------------|
| `camera_name`       | string | ✅  | —   | 摄像头名称                                                      |
| `detect_type`       | string | ✅  | —   | `"human"` / `"vehicle"` / `"area"` / `"motion"` / `"line"` |
| `enable`            | bool   |    | —   | 是否开启该侦测功能                                                  |
| `tracking`          | bool   |    | —   | 是否开启追踪（仅 `human`/`vehicle`/`motion` 有效）                    |
| `sensitivity_level` | int    |    | —   | 灵敏度等级 `0`关闭 / `1`低 / `2`中 / `3`高                           |

**返回值**: `TrackingSetResult`

| 字段            | 类型     | 说明            |
|---------------|--------|---------------|
| `ok`          | bool   | 是否成功          |
| `camera`      | string | 摄像头名称         |
| `channel`     | string | `"sk"`        |
| `detect_type` | string | 操作的侦测类型       |
| `updated`     | object | 本次生效的字段（回读确认） |
| `current`     | object | 设置后回读的当前值     |
| `message`     | string | 说明信息          |
| `error_code`  | string | 错误码           |
