---
name: xpai-camera-control
description: Discover, connect, and control ONVIF/RTSP network cameras and USB cameras on a local network. Capabilities include WS-Discovery device detection, RTSP streaming, snapshot capture, PTZ pan/tilt/zoom control, device management, AI tracking, alarm configuration, video encoding settings, and picture/audio adjustments. Use when the user wants to discover cameras, view a camera feed, capture snapshots, control PTZ, manage camera settings, or mentions ONVIF, RTSP, IP camera, webcam, or Skyworth/创维 cameras.
license: MIT
compatibility: Requires Python 3.10+, OpenCV, onvif-zeep, requests, psutil. Cameras must be on the same LAN for discovery.
metadata:
  version: "0.4.0"
  agent_created: "true"
---

# Camera Control Skill

## When to Use

Trigger this skill when the user:
- Wants to see a camera feed, capture a snapshot, or record video
- Asks to find or discover cameras on the network
- Requests pan, tilt, zoom, or camera movement
- Mentions ONVIF, RTSP, IP camera, webcam, or specific camera brands (Skyworth/创维, Hikvision/海康, Dahua/大华)
- Wants to configure camera settings (night vision, alarms, encoding, OSD)

## Core Workflow

### Phase 0 — Session Init (每次对话必做)

每次对话开始时，先检查 config.yaml 中是否有已注册摄像头：

1. 调用 `get_registered_cameras()` 读取 config.yaml 中保存的摄像头配置（含凭据）
2. 对每台已注册摄像头调用 `connect_device(cam.name)` — 工具自动使用 config.yaml 中的凭据连接，**用户无需再输入密码**
3. 若 config.yaml 为空或所有注册摄像头连接失败 → 进入 Phase 1

### Phase 1 — Discover Cameras

Phase 0 缓存不可用时，调用 `search_devices()` 发现局域网摄像头。

### Phase 2 — Connect & Authorize

对发现的摄像头，调用 `connect_device()` 连接。**具体连接流程由工具内部实现**，Agent 的职责如下：

| 场景 | Agent 操作 |
|------|-----------|
| **direct_connect 摄像头** | 直接调用 `connect_device()` → 无需凭据 |
| **password_required（config.yaml 已有凭据）** | 直接调用 `connect_device()` → 工具自动读取 config.yaml 中的 username/password |
| **password_required（无缓存凭据）** | ① 调用 `connect_device()` → 工具向远程授权服务器发起请求 ② Agent 调用 `poll_auth_status()` 轮询远程服务器接口，检查授权状态 ③ 一旦授权状态变为 `authorized`，工具列出局域网摄像头 ④ Agent 提示用户输入密码 ⑤ 用户输入后，Agent 将密码传入 `connect_device()` 完成连接 |
| **连接成功后** | 调用 `register_camera()` 将凭据写入 config.yaml → 下次对话 Phase 0 自动复用，**无需再次输入密码** |

### Phase 3 — Stream & Capture

连接成功后执行流媒体操作：`capture_video_screenshot()` 截图、`get_audio_video_stream()` 取流地址、`toggle_recording()` 录像。截图文件存到系统临时目录。

### Phase 4 — PTZ Control

仅 ONVIF 摄像头支持：`control_ptz()` 方向控制、`save_ptz_preset()` / `go_to_preset()` 预置位。USB 和纯 RTSP 摄像头不支持 PTZ。

详细的代码示例和参数说明见 [references/WORKFLOW.md](references/WORKFLOW.md)。

## Toolkit Modules

7 个模块在 `scripts/toolkit/` 中，通过 `import scripts.toolkit as tk` 调用：

| Module | Key Functions | Purpose |
|--------|--------------|---------|
| `device_mgmt.py` | `get_registered_cameras`, `register_camera`, `search_devices`, `connect_device`, `disconnect_device`, `poll_auth_status` | Config、发现、连接、授权 |
| `stream.py` | `capture_video_screenshot`, `get_audio_video_stream`, `toggle_recording` | 流媒体、截图、录像 |
| `ptz.py` | `control_ptz`, `control_lens_zoom`, `save_ptz_preset`, `go_to_preset` | 云台控制 |
| `tracking.py` | `track_human_shapes`, `track_vehicles`, `monitor_zone_entry` | AI 跟踪 |
| `image_audio.py` | `adjust_picture_settings`, `configure_night_vision`, `configure_microphone` | 画面、夜视、音频 |
| `alarm.py` | `configure_alarm_settings`, `configure_alarm_push` | 报警设置 |
| `encoding_osd.py` | `configure_video_encoding`, `configure_osd_settings` | 编码、OSD |

完整函数签名和安全约束见 [references/COMMANDS.md](references/COMMANDS.md)。

## Security Constraints

| Constraint | Rule | Applies To |
|------------|------|-----------|
| **Explicit Prompt** | 执行前告知用户操作内容，等待确认 | PTZ、流媒体、截图、画面设置、跟踪 |
| **Code Validation** | 校验参数、设备状态、连接可用性 | 录像、麦克风/扬声器、固件更新、报警配置 |
| **Explicit Authorization** | 需摄像头 APP 端云端授权 | 固件更新、重启、恢复出厂、报警推送 |
| **Never Expose Credentials** | 不在输出中显示用户名、密码、Token、SN | 所有涉及凭据的操作 |

## Configuration

摄像头配置保存在 skill 根目录的 `config.yaml` 中。首次连接成功后自动写入，后续对话自动读取。完整 schema 见 [references/CONFIG.md](references/CONFIG.md)。

## Limitations

- 摄像头和主机必须在同一局域网（WS-Discovery 依赖多播）
- RTSP 流需要本地网络连通
- 云端授权需要互联网访问
- 无互联网的 WiFi 下，password_required 摄像头拒绝连接

## Demo Mode

内置演示模式，所有函数返回模拟数据。`capture_video_screenshot` 生成真实的 JPEG 图像。

```python
import scripts.toolkit as tk
tk.enable_demo_mode()
```

使用 `import scripts.toolkit as tk` 调用（确保 monkey-patched demo 函数生效），不要用 `from scripts.toolkit import xxx`。演示模式包含 3 台模拟摄像头和 32 个工具函数。详细用法见 [references/WORKFLOW.md](references/WORKFLOW.md)。

## References

- [references/WORKFLOW.md](references/WORKFLOW.md) — 完整工作流示例、代码片段、演示模式详细用法
- [references/COMMANDS.md](references/COMMANDS.md) — 全部函数签名、参数、返回值、安全约束
- [references/ARCHITECTURE.md](references/ARCHITECTURE.md) — 系统架构、云端授权流程、设备身份模型
- [references/CONFIG.md](references/CONFIG.md) — config.yaml 完整 schema 与示例
