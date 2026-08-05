# AgenticCameraControl

**[中文](#中文) | [English](#english)**

---

## 中文

局域网 IP 摄像头的智能控制系统。支持 ONVIF 协议摄像头和 USB 摄像头的自动发现、连接、视频流拉取、云台控制、设备管理等功能。

核心模块 `xpai-camera-control` 可作为 MCP (Model Context Protocol) Server 运行，将 17 个摄像头控制工具暴露给 AI Agent 使用。

### 功能概览

| 类别 | 能力 |
|------|------|
| **设备发现** | 局域网自动搜索摄像头，支持 WS-Discovery、创维私有协议、USB 扫描 |
| **设备连接** | 自动探测认证方式，凭据缓存与自动重连 |
| **视频流** | RTSP 流地址获取、截图、录像、存储管理 |
| **云台控制** | 8 方向移动、物理极限保护、云台校准 |
| **事件监听** | 报警事件订阅（移动/人形/遮挡等）、事件联动抓拍、本地事件存储 |
| **补光控制** | 日夜模式切换、补光灯模式/亮度/定时器/灵敏度调节（创维私有协议 + ONVIF 回退） |

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

#### 交互方式：仅限 MCP

所有摄像头操作**必须**通过 MCP Server 暴露的工具完成。禁止直接 `import scripts.toolkit` 或编写独立脚本调用内部函数——这会绕过技能包的安全约束（操作前确认、参数校验），并且连接状态保存在 MCP Server 进程内存中，跨进程脚本调用会失效。若 MCP 工具未出现在客户端工具列表中，应先注册 MCP Server（见上文配置），而不是退回脚本方式。

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
│   │   │   ├── events.py         # 报警事件接收与本地存储
│   │   │   └── illumination.py   # 补光/夜视模式控制
│   ├── references/               # 技术参考文档
│   │   └── commands/             # 各模块工具签名与参数说明
│   ├── SKILL.md                  # Agent 技能描述文件
│   ├── config.yaml               # 摄像头配置（运行时自动生成）
│   └── requirements.txt          # Python 依赖
├── Toolkit/                      # 独立运行脚本（调试与诊断）
│   ├── device/                   # 设备管理脚本
│   ├── discovery/                # 设备发现脚本
│   ├── diagnostics/              # 诊断工具脚本
│   ├── events/                   # 事件监听脚本
│   ├── illumination/             # 补光控制脚本
│   ├── ptz/                      # 云台控制脚本
│   └── stream/                   # 视频流脚本
```

### 工具模块

6 个模块，共 17 个 MCP 工具：

| 模块 | 说明 | 参考文档 |
|------|------|----------|
| `device_mgmt.py` | 设备注册、搜索、连接、断开 | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md) |
| `discovery.py` | 局域网设备发现（内部模块） | [commands/discovery.md](xpai-camera-control/references/commands/discovery.md) |
| `stream.py` | 视频流、截图、录像、存储 | [commands/stream.md](xpai-camera-control/references/commands/stream.md) |
| `ptz.py` | 云台方向控制/校准/停止 | [commands/ptz.md](xpai-camera-control/references/commands/ptz.md) |
| `events.py` | 报警事件订阅、联动抓拍、事件存储与消费 | [commands/events.md](xpai-camera-control/references/commands/events.md) |
| `illumination.py` | 补光/夜视模式查询与控制（双协议） | [commands/illumination.md](xpai-camera-control/references/commands/illumination.md) |
| `device_mgmt.py` (云端授权) | 云端授权状态轮询、一站式授权连接 | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md) |

### 安全边界

本 skill 包遵循以下安全约束，确保不会对用户计算机产生预期之外的影响：

| 承诺 | 说明 |
|------|------|
| 请求-响应模式 | 工具默认为同步请求-响应；唯一例外是事件监听后台线程，仅在用户显式开启后运行，且行为限于报警订阅与白名单路径写入，可随时关闭 |
| 仅局域网通信 | 所有网络流量限于局域网内，无外网通信 |
| 文件写入受限 | 仅写入 `config.yaml`、`snapshots/`、`recordings/`、`events/` |
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

The core module `xpai-camera-control` runs as an MCP (Model Context Protocol) Server, exposing 17 camera control tools to AI Agents.

### Features

| Category | Capabilities |
|----------|-------------|
| **Discovery** | Auto-search cameras on LAN, supports WS-Discovery, Skyworth private protocol, and USB scanning |
| **Connection** | Auto-detect auth method, credential caching and auto-reconnect |
| **Streaming** | RTSP stream URL retrieval, screenshots, recording, storage management |
| **PTZ Control** | 8-directional movement, physical limit guard, calibration |
| **Event Monitoring** | Alarm event subscription (motion/human/tamper, etc.), snapshot linkage on event, local event store |
| **Illumination Control** | Day/night mode switching, fill-light mode/brightness/timer/sensitivity adjustment (Skyworth private protocol + ONVIF fallback) |

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

#### Interaction Mode: MCP Only

All camera operations **must** go through the tools exposed by the MCP Server. Directly importing `scripts.toolkit` or writing standalone scripts to call internal functions is forbidden — it bypasses the skill's security constraints (pre-operation confirmation, parameter validation), and connection state lives in the MCP Server process memory, so cross-process scripted calls will fail. If the MCP tools are not present in the client's tool list, register the MCP Server first (see configuration above) instead of falling back to scripting.

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
│   │   │   ├── events.py         # Alarm event receiving & local store
│   │   │   └── illumination.py   # Illumination / night-vision control
│   ├── references/               # Technical reference docs
│   │   └── commands/             # Per-module tool signatures & parameters
│   ├── SKILL.md                  # Agent skill description file
│   ├── config.yaml               # Camera config (auto-generated at runtime)
│   └── requirements.txt          # Python dependencies
├── Toolkit/                      # Standalone scripts (debug & diagnostics)
│   ├── device/                   # Device management scripts
│   ├── discovery/                # Device discovery scripts
│   ├── diagnostics/              # Diagnostics scripts
│   ├── events/                   # Event monitoring scripts
│   ├── illumination/             # Illumination control scripts
│   ├── ptz/                      # PTZ control scripts
│   └── stream/                   # Video stream scripts
```

### Toolkit Modules

6 modules, 17 MCP tools in total:

| Module | Description | Reference |
|--------|-------------|-----------|
| `device_mgmt.py` | Device registration, search, connection, disconnection | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md) |
| `discovery.py` | LAN device discovery (internal module) | [commands/discovery.md](xpai-camera-control/references/commands/discovery.md) |
| `stream.py` | Video streaming, screenshots, recording, storage | [commands/stream.md](xpai-camera-control/references/commands/stream.md) |
| `ptz.py` | PTZ directional control / calibration / stop | [commands/ptz.md](xpai-camera-control/references/commands/ptz.md) |
| `events.py` | Alarm event subscription, snapshot linkage, event store & consumption | [commands/events.md](xpai-camera-control/references/commands/events.md) |
| `illumination.py` | Illumination / night-vision mode query & control (dual-protocol) | [commands/illumination.md](xpai-camera-control/references/commands/illumination.md) |
| `device_mgmt.py` (Cloud Auth) | Cloud auth status polling, one-call authorization flow | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md) |

### Security Boundary

This skill package operates within strict security constraints to ensure no unexpected impact on the user's system:

| Guarantee | Description |
|-----------|-------------|
| Request-response by default | Tools are synchronous request-response. The only exception is the event listener background thread, which runs only after explicit user enablement, is limited to alarm subscription plus whitelist-path writes, and can be stopped at any time. |
| LAN-only communication | All network traffic stays within the local network. No internet communication. |
| Restricted file writes | Only writes to `config.yaml`, `snapshots/`, `recordings/`, and `events/` |
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
