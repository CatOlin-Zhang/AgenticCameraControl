# AgenticCameraControl

**[中文](#中文) | [English](#english)**

---

## 中文

局域网 IP 摄像头的智能控制系统。支持 ONVIF 协议摄像头和 USB 摄像头的自动发现、连接、视频流拉取、云台控制、设备管理等功能。

核心模块 `xpai-camera-control` 可作为 MCP (Model Context Protocol) Server 运行，将 33 个摄像头控制工具暴露给 AI Agent 使用。

### 功能概览

| 类别 | 能力 |
|------|------|
| **设备发现** | 局域网自动搜索摄像头，支持 WS-Discovery、USB 扫描 |
| **设备连接** | 自动探测认证方式，凭据缓存与自动重连 |
| **视频流** | RTSP 流地址获取、截图、录像、存储管理 |
| **云台控制** | 8 方向移动、变焦、预置点、校准、绝对坐标定位、巡航 |
| **AI 追踪** | 车辆追踪、人形追踪、区域入侵检测 |
| **图像音频** | 画面设置、翻转、夜视、白光灯、麦克风、扬声器 |
| **报警设置** | 报警声音、推送方式配置 |
| **编码与 OSD** | 视频编码参数、OSD 叠加文字设置 |

### 快速开始

#### 环境要求

- Python 3.10+
- 摄像头与主机在同一局域网

#### 安装依赖

```bash
cd xpai-camera-control
pip install -r requirements.txt
```

#### 运行 MCP Server

```bash
python scripts/mcp_server.py
```

Server 通过 stdio 传输协议与 MCP 客户端通信，兼容 Claude Desktop 等 MCP 客户端。

#### 作为 Python 库使用

```python
import scripts.toolkit as tk

# 搜索局域网摄像头
result = tk.search_devices(method="sky_discovery", timeout=10)

# 连接设备
tk.connect_device("my_camera", ip="192.168.1.100")

# 截图
screenshot = tk.capture_video_screenshot("my_camera")
print(screenshot.file_path)

# 云台控制
tk.control_ptz("my_camera", direction="up", duration_seconds=2.0)
```

### 项目结构

```
AgenticCameraControl/
├── xpai-camera-control/          # 核心技能包（MCP Server）
│   ├── scripts/
│   │   ├── mcp_server.py         # MCP Server 入口
│   │   ├── toolkit/              # 工具函数集
│   │   │   ├── discovery.py      # 设备发现
│   │   │   ├── device_mgmt.py    # 设备管理与连接
│   │   │   ├── stream.py         # 音视频流与存储
│   │   │   ├── ptz.py            # 云台控制
│   │   │   ├── tracking.py       # AI 追踪
│   │   │   ├── image_audio.py    # 图像与音频设置
│   │   │   ├── alarm.py          # 报警设置
│   │   │   └── encoding_osd.py   # 编码与 OSD
│   │   └── auth/                 # 认证模块
│   ├── references/               # 技术参考文档
│   │   └── commands/             # 各模块工具签名与参数说明
│   ├── SKILL.md                  # Agent 技能描述文件
│   ├── config.yaml               # 摄像头配置（运行时自动生成）
│   └── requirements.txt          # Python 依赖
├── phase1/                       # 阶段一：动态扫描 + 基础控制
├── phase2/                       # 阶段二：SN 码认证体系
└── phase3/                       # 阶段三：ONVIF 心跳包被动发现
```

### 工具模块

8 个模块，共 33 个 MCP 工具：

| 模块 | 说明 | 参考文档 |
|------|------|----------|
| `device_mgmt.py` | 设备注册、搜索、连接、断开 | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md) |
| `discovery.py` | 局域网设备发现 | [commands/discovery.md](xpai-camera-control/references/commands/discovery.md) |
| `stream.py` | 视频流、截图、录像、存储 | [commands/stream.md](xpai-camera-control/references/commands/stream.md) |
| `ptz.py` | 云台方向/变焦/预置点/校准/巡航 | [commands/ptz.md](xpai-camera-control/references/commands/ptz.md) |
| `tracking.py` | 车辆/人形追踪、区域监控 | [commands/tracking.md](xpai-camera-control/references/commands/tracking.md) |
| `image_audio.py` | 画面/夜视/白光灯/音频设置 | [commands/image_audio.md](xpai-camera-control/references/commands/image_audio.md) |
| `alarm.py` | 报警声音与推送配置 | [commands/alarm.md](xpai-camera-control/references/commands/alarm.md) |
| `encoding_osd.py` | 视频编码与 OSD 文字叠加 | [commands/encoding_osd.md](xpai-camera-control/references/commands/encoding_osd.md) |

### 安全边界

本 skill 包遵循以下安全约束，确保不会对用户计算机产生预期之外的影响：

| 承诺 | 说明 |
|------|------|
| 请求-响应模式 | 所有工具为同步请求-响应，不启动后台线程或守护进程 |
| 仅局域网通信 | 所有网络流量限于局域网内，无外网通信 |
| 文件写入受限 | 仅写入 `config.yaml`、`snapshots/`、`recordings/` |
| 无系统修改 | 不修改注册表、环境变量、系统服务 |
| 无进程派生 | 不启动子进程或外部程序 |

### 配置

摄像头配置保存在 `xpai-camera-control/config.yaml`。首次连接成功后凭据会自动持久化，后续会话自动重连。完整 schema 见 [CONFIG.md](xpai-camera-control/references/CONFIG.md)。

### 限制

- 摄像头与主机须在同一局域网
- 截图/录像功能依赖 `opencv-python`
- MCP Server 仅支持 stdio 传输

---

## English

An intelligent control system for IP cameras on local networks. Supports auto-discovery, connection, video streaming, PTZ control, and device management for ONVIF-compliant cameras and USB webcams.

The core module `xpai-camera-control` runs as an MCP (Model Context Protocol) Server, exposing 33 camera control tools to AI Agents.

### Features

| Category | Capabilities |
|----------|-------------|
| **Discovery** | Auto-search cameras on LAN, supports WS-Discovery and USB scanning |
| **Connection** | Auto-detect auth method, credential caching and auto-reconnect |
| **Streaming** | RTSP stream URL retrieval, screenshots, recording, storage management |
| **PTZ Control** | 8-directional movement, zoom, presets, calibration, absolute positioning, patrol cruise |
| **AI Tracking** | Vehicle tracking, human shape tracking, zone intrusion detection |
| **Image & Audio** | Picture settings, flip display, night vision, floodlight, microphone, speaker |
| **Alarm** | Alarm sound and push notification configuration |
| **Encoding & OSD** | Video encoding parameters, OSD text overlay |

### Quick Start

#### Requirements

- Python 3.10+
- Cameras and host on the same local network

#### Install Dependencies

```bash
cd xpai-camera-control
pip install -r requirements.txt
```

#### Run MCP Server

```bash
python scripts/mcp_server.py
```

The server communicates with MCP clients via stdio transport, compatible with Claude Desktop and other MCP clients.

#### Use as a Python Library

```python
import scripts.toolkit as tk

# Discover cameras on the LAN
result = tk.search_devices(method="sky_discovery", timeout=10)

# Connect to a device
tk.connect_device("my_camera", ip="192.168.1.100")

# Capture a screenshot
screenshot = tk.capture_video_screenshot("my_camera")
print(screenshot.file_path)

# PTZ control
tk.control_ptz("my_camera", direction="up", duration_seconds=2.0)
```

### Project Structure

```
AgenticCameraControl/
├── xpai-camera-control/          # Core skill package (MCP Server)
│   ├── scripts/
│   │   ├── mcp_server.py         # MCP Server entry point
│   │   ├── toolkit/              # Tool functions
│   │   │   ├── discovery.py      # Device discovery
│   │   │   ├── device_mgmt.py    # Device management & connection
│   │   │   ├── stream.py         # Audio/video streaming & storage
│   │   │   ├── ptz.py            # PTZ control
│   │   │   ├── tracking.py       # AI tracking
│   │   │   ├── image_audio.py    # Image & audio settings
│   │   │   ├── alarm.py          # Alarm settings
│   │   │   └── encoding_osd.py   # Encoding & OSD
│   │   └── auth/                 # Authentication module
│   ├── references/               # Technical reference docs
│   │   └── commands/             # Per-module tool signatures & parameters
│   ├── SKILL.md                  # Agent skill description file
│   ├── config.yaml               # Camera config (auto-generated at runtime)
│   └── requirements.txt          # Python dependencies
├── phase1/                       # Phase 1: Dynamic scanning + basic control
├── phase2/                       # Phase 2: SN-based authentication
└── phase3/                       # Phase 3: ONVIF heartbeat passive discovery
```

### Toolkit Modules

8 modules, 33 MCP tools in total:

| Module | Description | Reference |
|--------|-------------|-----------|
| `device_mgmt.py` | Device registration, search, connection, disconnection | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md) |
| `discovery.py` | LAN device discovery | [commands/discovery.md](xpai-camera-control/references/commands/discovery.md) |
| `stream.py` | Video streaming, screenshots, recording, storage | [commands/stream.md](xpai-camera-control/references/commands/stream.md) |
| `ptz.py` | PTZ direction/zoom/presets/calibration/cruise | [commands/ptz.md](xpai-camera-control/references/commands/ptz.md) |
| `tracking.py` | Vehicle/human tracking, zone monitoring | [commands/tracking.md](xpai-camera-control/references/commands/tracking.md) |
| `image_audio.py` | Picture/night vision/floodlight/audio settings | [commands/image_audio.md](xpai-camera-control/references/commands/image_audio.md) |
| `alarm.py` | Alarm sound & push notification config | [commands/alarm.md](xpai-camera-control/references/commands/alarm.md) |
| `encoding_osd.py` | Video encoding & OSD text overlay | [commands/encoding_osd.md](xpai-camera-control/references/commands/encoding_osd.md) |

### Security Boundary

This skill package operates within strict security constraints to ensure no unexpected impact on the user's system:

| Guarantee | Description |
|-----------|-------------|
| Request-response only | All tools are synchronous request-response. No background threads or daemons. |
| LAN-only communication | All network traffic stays within the local network. No internet communication. |
| Restricted file writes | Only writes to `config.yaml`, `snapshots/`, and `recordings/` |
| No system modifications | No registry changes, environment variable modifications, or system service installations. |
| No process spawning | No subprocesses or external programs are launched. |

### Configuration

Camera configurations are stored in `xpai-camera-control/config.yaml`. Credentials are automatically persisted after the first successful connection and reused in subsequent sessions. See [CONFIG.md](xpai-camera-control/references/CONFIG.md) for the full schema.

### Limitations

- Cameras and host must be on the same local network
- Screenshot/recording features require `opencv-python`
- MCP Server supports stdio transport only

---

## License

MIT
