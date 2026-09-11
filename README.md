# AgenticCameraControl

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/MCP-1.0-green" alt="MCP 1.0">
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="License MIT">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/Version-0.6.0-orange" alt="Version 0.6.0">
  <img src="https://img.shields.io/badge/ONVIF-Supported-blueviolet" alt="ONVIF">
  <img src="https://img.shields.io/badge/Skyworth-Supported-ff6600" alt="Skyworth">
  <img src="https://img.shields.io/badge/Transport-stdio-9cf" alt="Transport stdio">
</p>

> **版本：0.6.0** | 传输协议：MCP stdio | MCP 工具数：20

**[中文](#中文) | [English](#english)**

---

## 中文

局域网 IP 摄像头的智能控制系统。支持 ONVIF 协议摄像头， Sky Worth 协议摄像头，以及 USB 摄像头的自动发现、连接、视频流拉取、云台控制（除USB）、设备管理（除USB）等功能。

核心模块 `xpai-camera-control` 可作为 MCP (Model Context Protocol) Server 运行，将 20 个摄像头控制工具暴露给 AI Agent 使用。分发采用单一技能包设计：`toolkit` 的各平台编译产物共存于同一包内，Windows、macOS、Linux 无需任何修改即可直接运行。

### 功能概览

| 类别         | 能力                                             |
|------------|------------------------------------------------|
| **设备发现**   | 局域网自动搜索摄像头，支持 WS-Discovery、Sky Worth 协议、USB 扫描 |
| **设备连接**   | 自动探测认证方式，凭据缓存与自动重连                             |
| **视频流**    | RTSP 流地址获取、截图、录像（支持定长自动停止）、存储管理                |
| **WebRTC** | RTSP 流转 WebRTC 浏览器实时预览，返回 HTTP 访问地址            |
| **云台控制**   | 8 方向移动+变焦、物理极限保护、云台校准                           |
| **事件监听**   | 报警事件订阅（移动/人形/遮挡等）、事件联动抓拍、本地事件存储                |
| **补光控制**   | 日夜模式切换、补光灯模式/亮度/定时器/灵敏度调节（仅Sky Worth）          |
| **图像设置**   | 亮度/对比度/饱和度/锐度/翻转/白平衡/宽动态等参数调节（仅Sky Worth）      |
| **侦测追踪**   | 人形追踪/车辆追踪/区域检测能力查询与开关控制（仅Sky Worth）            |

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

#### MCP 客户端配置

将以下内容添加到 MCP 客户端（如 Claude Desktop）的配置文件：

```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "python",
      "args": ["scripts/mcp_server.py"],
      "cwd": "/path/to/xpai-camera-control"
    }
  }
}
```

### 跨平台支持

采用**单一技能包**设计，无需按平台选择目录：

| 形态 | 说明 |
|------|------|
| 源码包（本仓库） | `scripts/toolkit/` 为 `.py` 源码，任意平台安装依赖后直接运行 |
| 分发包（构建产物） | `toolkit` 编译为各平台二进制（Windows `.pyd` / macOS、Linux `.so`），按 Python 扩展名后缀共存于同一包内，同一包在三平台直接运行 |

分发包由 `xpai-build/build_toolkit.py` 构建（敏感常量混淆 + Cython 编译），详见 [build_readme.md](xpai-build/build_readme.md)。

### 项目结构

```
AgenticCameraControl/
├── xpai-camera-control/          # 核心技能包（MCP Server，单包全平台通用）
│   ├── scripts/
│   │   ├── mcp_server.py         # MCP Server 入口
│   │   ├── _paths.py             # 路径解析
│   │   ├── toolkit/              # 工具函数集
│   │   │   ├── __init__.py       # 统一导出入口
│   │   │   ├── discovery.py      # 设备发现
│   │   │   ├── device_mgmt.py    # 设备管理与连接
│   │   │   ├── stream.py         # 音视频流与存储
│   │   │   ├── ptz.py            # 云台控制
│   │   │   ├── events.py         # 报警事件接收与本地存储
│   │   │   ├── illumination.py   # 补光/夜视模式控制
│   │   │   ├── image_settings.py # 图像参数设置
│   │   │   └── tracking.py       # 侦测追踪控制
│   │   └── __init__.py
│   ├── references/               # 技术参考文档
│   │   ├── commands/             # 各模块工具签名与参数说明
│   │   ├── CONFIG.md             # config.yaml 完整 schema
│   │   ├── WORKFLOW.md           # 工作流详解
│   │   └── EVENT_INTEGRATION.md  # 事件存储集成契约
│   ├── events/                   # 事件持久化目录
│   ├── snapshots/                # 截图保存目录
│   ├── video/                    # 录像保存目录（运行时自动创建，默认 video/）
│   ├── SKILL.md                  # Agent 技能描述文件
│   ├── config.yaml               # 摄像头配置（运行时自动生成）
│   └── requirements.txt          # Python 依赖
├── xpai-build/                   # 构建工具（源码混淆 + Cython 编译，不进分发包）
└── README.md
```

### 工具模块

8 个功能扇区，共 20 个 MCP 工具：

| 扇区                      | 说明                           | 参考文档                                                                                    |
|-------------------------|------------------------------|-----------------------------------------------------------------------------------------|
| `device_mgmt.py`        | 设备注册、搜索、连接、断开                | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md)       |
| `discovery.py`          | 局域网设备发现（内部模块）                | [commands/discovery.md](xpai-camera-control/references/commands/discovery.md)           |
| `stream.py`             | 视频流、截图、录像、存储                 | [commands/stream.md](xpai-camera-control/references/commands/stream.md)                 |
| `ptz.py`                | 云台方向控制/校准/停止                 | [commands/ptz.md](xpai-camera-control/references/commands/ptz.md)                       |
| `events.py`             | 报警事件订阅、联动抓拍、事件存储与消费          | [commands/events.md](xpai-camera-control/references/commands/events.md)                 |
| `illumination.py`       | 补光/夜视模式查询与控制（双协议）            | [commands/illumination.md](xpai-camera-control/references/commands/illumination.md)     |
| `image_settings.py`     | 图像参数查询与设置（双通道）               | [commands/image_settings.md](xpai-camera-control/references/commands/image_settings.md) |
| `tracking.py`           | 侦测追踪能力查询与开关控制                | [commands/tracking.md](xpai-camera-control/references/commands/tracking.md)             |

### 安全边界

本 skill 包遵循以下安全约束，确保不会对用户计算机产生预期之外的影响：

| 承诺            | 说明                                                             |
|---------------|----------------------------------------------------------------|
| 请求-响应模式       | 工具默认为同步请求-响应；唯一例外是事件监听后台线程，仅在用户显式开启后运行，且行为限于报警订阅与白名单路径写入，可随时关闭 |
| 使用阶段仅局域网通信    | 使用阶段所有网络流量限于局域网内，无外网通信；为保障用户安全，连接阶段会与远程服务器确认连接状态        |
| 文件写入受限        | 仅写入 `config.yaml`、`snapshots/`、`video/`、`events/`              |
| 无系统修改         | 不修改注册表、环境变量、系统服务                                               |
| 无进程派生         | 不启动子进程或外部程序（Agent 框架下的定时任务与守护进程不在此限制内）                         |

### 配置

摄像头配置保存在 `xpai-camera-control/config.yaml`。首次连接成功后凭据会自动持久化，后续会话自动重连。完整 schema 见 [CONFIG.md](xpai-camera-control/references/CONFIG.md)。

### 限制

- 摄像头与主机须在同一局域网
- 截图/录像功能依赖 `opencv-python`
- MCP Server 仅支持 stdio 传输

### 依赖

- `onvif-zeep` — ONVIF 协议（SOAP / WS-Discovery）
- `opencv-python` — 视频采集与处理
- `requests` — HTTP 客户端（设备探测）
- `psutil` — 网络接口枚举（局域网扫描）
- `pyyaml` — config.yaml 读写（凭据持久化）

完整依赖列表见 `xpai-camera-control/requirements.txt`。

### 会话规则

| 规则 | 值 |
|------|------|
| 空闲超时 | **30 秒** — 用户停止交互后 Agent 应断开连接释放控制权 |
| 并发控制 | FIFO：同一时间仅一个 Agent 拥有完全控制权，其余为只读 |
| 单实例锁 | 同一时间仅允许一个 MCP Server 进程运行（端口绑定 + 租约心跳 + 看门狗三层防护） |

### 故障排查

| 现象 | 原因与处理 |
|------|-----------|
| MCP 工具全部不可用，Server 启动即退出（exit code 71） | 实例锁冲突：已有 MCP Server 实例在运行。部分 Agent 架构在会话结束后不会终止 Server 进程，旧进程的租约心跳持续刷新，自动回收不会触发，新会话的 Server 因此无法启动。处理：读取技能包根目录 `.instance_lease.json` 中的 `pid` 字段定位旧进程，确认其命令行属于本技能包的 `mcp_server.py` 后执行 `taskkill /PID <PID> /F /T`（Linux/macOS 用 `kill -9`），再重启 MCP 客户端拉起新实例 |
| 定长录像未按预期停止 | 录像时长应通过 `toggle_recording(action="start", duration=<秒>)` 传入，由 Server 端到时自动停止。不要依赖“启动后延时再调用 stop”的方式——对话过程中的其他任务会淹没该停止操作，导致录像无限持续并占用设备的 RTSP 会话 |

Server 进程退出码：`70` = 看门狗自清理（宿主已放弃该实例）；`71` = 实例锁冲突（另一存活实例持锁，或需手动干预）。

### Agent 集成与使用建议

- 通过任意 Agent 框架的 Skill 安装功能安装本技能包，或在交互中让 Agent 访问 [SkillHub](https://skillhub.agentic.ai/) 获取。
- 事件报警功能提供详细的摄像头告警信息与联动截图，您可以对内容进行进一步处理和分析，也可以直接向 Agent 提问——例如："告诉我今天摄像头都拍到了什么内容"。
- 事件报警功能支持会话内值守模式，开启后可远程实时接收摄像头的报警消息。

### 兼容性与社区

- 本技能包已在 WorkBuddy 与 OpenClaw 中完成功能与兼容性测试，欢迎创作者和使用者提供反馈。如在安装到您自建的 Agent 时遇到问题，请在项目评论区留言。
- 所有摄像头拍摄的截图、录制的视频和事件记录均保存在本地文件夹（`snapshots/`、`video/`、`events/`）中，您可以对这些数据进行进一步处理，也欢迎在社区或评论区分享您的使用创意。
- 如果您有更好的创意或修改建议，欢迎在项目评论区留下想法，优秀的建议将被纳入后续版本更新。

---

## English

An intelligent control system for IP cameras on local networks. Supports ONVIF-compliant cameras, Sky Worth protocol cameras, and USB webcams for auto-discovery, connection, video streaming, PTZ control (excluding USB), and device management (excluding USB).

The core module `xpai-camera-control` runs as an MCP (Model Context Protocol) Server, exposing 20 camera control tools to AI Agents. Distribution uses a single-skill-package design: compiled toolkit artifacts for each platform coexist in the same package, running on Windows, macOS, and Linux without any modification.

### Features

| Category                 | Capabilities                                                                                                      |
|--------------------------|-------------------------------------------------------------------------------------------------------------------|
| **Discovery**            | Auto-search cameras on LAN, supports WS-Discovery, Sky Worth protocol, and USB scanning                           |
| **Connection**           | Auto-detect auth method, credential caching and auto-reconnect                                                    |
| **Streaming**            | RTSP stream URL retrieval, screenshots, recording (fixed-duration auto-stop supported), storage management        |
| **WebRTC**               | RTSP-to-WebRTC browser live preview, returns HTTP access URL                                                      |
| **PTZ Control**          | 8-directional movement + zoom, physical limit guard, calibration                                        |
| **Event Monitoring**     | Alarm event subscription (motion/human/tamper, etc.), snapshot linkage on event, local event store                |
| **Illumination Control** | Day/night mode switching, fill-light mode/brightness/timer/sensitivity adjustment (Sky Worth only)                |
| **Image Settings**       | Brightness/contrast/saturation/sharpness/flip/whitebalance/WDR adjustment (Sky Worth only)                        |
| **Detection & Tracking** | Human tracking, vehicle tracking, area detection capability query and toggle (Sky Worth only)                     |

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

#### MCP Client Configuration

Add the following to your MCP client configuration (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "python",
      "args": ["scripts/mcp_server.py"],
      "cwd": "/path/to/xpai-camera-control"
    }
  }
}
```

### Cross-Platform Support

A **single skill package** design — no need to pick a directory per platform:

| Form | Description |
|------|-------------|
| Source package (this repo) | `scripts/toolkit/` ships as `.py` source; runs on any platform after installing dependencies |
| Distribution package (build artifact) | `toolkit` compiled to per-platform binaries (Windows `.pyd` / macOS & Linux `.so`), coexisting in the same package via Python extension suffixes — one package runs on all three platforms |

The distribution package is built by `xpai-build/build_toolkit.py` (sensitive-constant obfuscation + Cython compilation); see [build_readme.md](xpai-build/build_readme.md).

### Project Structure

```
AgenticCameraControl/
├── xpai-camera-control/          # Core skill package (MCP Server, single package for all platforms)
│   ├── scripts/
│   │   ├── mcp_server.py         # MCP Server entry point
│   │   ├── _paths.py             # Path resolution
│   │   ├── toolkit/              # Tool functions
│   │   │   ├── __init__.py       # Unified export entry
│   │   │   ├── discovery.py      # Device discovery
│   │   │   ├── device_mgmt.py    # Device management & connection
│   │   │   ├── stream.py         # Audio/video streaming & storage
│   │   │   ├── ptz.py            # PTZ control
│   │   │   ├── events.py         # Alarm event receiving & local store
│   │   │   ├── illumination.py   # Illumination / night-vision control
│   │   │   ├── image_settings.py # Image parameter settings
│   │   │   └── tracking.py       # Detection & tracking control
│   │   └── __init__.py
│   ├── references/               # Technical reference docs
│   │   ├── commands/             # Per-module tool signatures & parameters
│   │   ├── CONFIG.md             # config.yaml full schema
│   │   ├── WORKFLOW.md           # Workflow details
│   │   └── EVENT_INTEGRATION.md  # Event storage integration contract
│   ├── events/                   # Event persistence directory
│   ├── snapshots/                # Screenshot directory
│   ├── video/                    # Recording directory (auto-created, default video/)
│   ├── SKILL.md                  # Agent skill description file
│   ├── config.yaml               # Camera config (auto-generated at runtime)
│   └── requirements.txt          # Python dependencies
└── README.md
```

### Toolkit Modules

8 functional sectors, 20 MCP tools in total:

| Sector                    | Description                                                           | Reference                                                                               |
|---------------------------|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| `device_mgmt.py`          | Device registration, search, connection, disconnection                | [commands/device_mgmt.md](xpai-camera-control/references/commands/device_mgmt.md)       |
| `discovery.py`            | LAN device discovery (internal module)                                | [commands/discovery.md](xpai-camera-control/references/commands/discovery.md)           |
| `stream.py`               | Video streaming, screenshots, recording, storage                      | [commands/stream.md](xpai-camera-control/references/commands/stream.md)                 |
| `ptz.py`                  | PTZ directional control / calibration / stop                          | [commands/ptz.md](xpai-camera-control/references/commands/ptz.md)                       |
| `events.py`               | Alarm event subscription, snapshot linkage, event store & consumption | [commands/events.md](xpai-camera-control/references/commands/events.md)                 |
| `illumination.py`         | Illumination / night-vision mode query & control (dual-protocol)      | [commands/illumination.md](xpai-camera-control/references/commands/illumination.md)     |
| `image_settings.py`       | Image parameter query & adjustment (dual-channel)                     | [commands/image_settings.md](xpai-camera-control/references/commands/image_settings.md) |
| `tracking.py`             | Detection & tracking capability query and toggle                      | [commands/tracking.md](xpai-camera-control/references/commands/tracking.md)             |

### Security Boundary

This skill package operates within strict security constraints to ensure no unexpected impact on the user's system:

| Guarantee                          | Description                                                                                                                                                                                                                                      |
|------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Request-response by default        | Tools are synchronous request-response. The only exception is the event listener background thread, which runs only after explicit user enablement, is limited to alarm subscription plus whitelist-path writes, and can be stopped at any time. |
| LAN-only during usage              | All network traffic stays within the local network during usage; during the connection phase, the system communicates with a remote server to verify connection status for user security.                                                         |
| Restricted file writes             | Only writes to `config.yaml`, `snapshots/`, `video/`, and `events/`                                                                                                                                                                              |
| No system modifications            | No registry changes, environment variable modifications, or system service installations.                                                                                                                                                        |
| No process spawning                | No subprocesses or external programs are launched (scheduled tasks and daemons under Agent frameworks are not subject to this restriction).                                                                                                      |

### Configuration

Camera configurations are stored in `xpai-camera-control/config.yaml`. Credentials are automatically persisted after the first successful connection and reused in subsequent sessions. See [CONFIG.md](xpai-camera-control/references/CONFIG.md) for the full schema.

### Limitations

- Cameras and host must be on the same local network
- Screenshot/recording features require `opencv-python`
- MCP Server supports stdio transport only

### Dependencies

- `onvif-zeep` — ONVIF protocol (SOAP / WS-Discovery)
- `opencv-python` — Video capture and processing
- `requests` — HTTP client (device probing)
- `psutil` — Network interface enumeration (LAN scanning)
- `pyyaml` — config.yaml read/write (credential persistence)

See `xpai-camera-control/requirements.txt` for the full dependency list.

### Session Rules

| Rule | Value |
|------|-------|
| Idle timeout | **30 seconds** — Agent must disconnect and release control when user stops interacting |
| Concurrent control | FIFO: only one agent has full control; others are view-only |
| Single-instance lock | Only one MCP server process may run at a time (three-layer defense: port bind + lease heartbeat + watchdog) |

### Troubleshooting

| Symptom | Cause & Resolution |
|---------|--------------------|
| All MCP tools unavailable; server exits immediately on startup (exit code 71) | Instance-lock conflict: another MCP server instance is already running. Some Agent architectures do not terminate the server process when a session ends; the orphaned process keeps its lease heartbeat fresh, automatic recovery never fires, and the new session's server cannot start. Resolution: read the `pid` field from `.instance_lease.json` in the skill package root to locate the stale process, verify its command line belongs to this skill's `mcp_server.py`, then run `taskkill /PID <PID> /F /T` (Linux/macOS: `kill -9`), and restart the MCP client to spawn a fresh instance |
| Fixed-duration recording did not stop as expected | Pass the duration via `toggle_recording(action="start", duration=<seconds>)` — the server auto-stops when time is up. Do not rely on "start, wait, then call stop": intermediate tasks during the conversation will bury the stop step, leaving the recording running indefinitely and holding the device's RTSP session |

Server exit codes: `70` = watchdog self-cleanup (host abandoned the instance); `71` = instance-lock conflict (another live instance holds the lock, or manual intervention needed).

### Agent Integration & Usage Tips

- Install this skill package through any Agent framework's Skill installation feature, or have your Agent access [SkillHub](https://skillhub.agentic.ai/) during interaction.
- The event alarm feature provides detailed camera alert information with linked snapshots. You can further process and analyze the content, or ask your Agent directly — for example: "Tell me what the cameras captured today."
- The event alarm feature supports an in-session guard mode, which enables real-time remote reception of camera alert notifications.

### Compatibility & Community

- This skill package has been tested for functionality and compatibility on WorkBuddy and OpenClaw. Feedback from creators and users is welcome. If you encounter issues installing this Skill in your self-built Agent, please leave a comment in the project discussion.
- All camera screenshots, recordings, and event logs are stored locally in (`snapshots/`, `video/`, `events/`). You can further process this data and are encouraged to share your use cases in the community or comment section.
- If you have ideas or suggestions for improvement, feel free to share them in the project comment section. Outstanding suggestions may be incorporated into future releases.

---

## License

MIT
