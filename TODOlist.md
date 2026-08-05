## Roadmap: Guardian Mode

> **Status:** Foundation (skill-side) 已全部实现。以下为尚未实现的遗留项。

### Foundation 遗留项（skill-side，需写代码）

- [ ] **Per-camera protocol recording** — `connect_device` 成功后将实际使用的协议（onvif / sky_private）持久化到 config.yaml，供后续连接直接选择（当前每次连接都要重新探测）
- [ ] **Snapshot & event retention** — 将 `events/` 和事件快照接入 `manage_storage_status` 策略（max age / max count 清理），防止存储无限膨胀
- [ ] **Desktop notification fallback** — MCP server 进程在事件到达时弹出 Windows toast 通知（不依赖 Agent 会话存活；用户打开聊天后可获取完整分析）

### Cloud Authorization（云端授权 — 已实现基础能力）

> **Status:** 云端授权基础流程已实现。`poll_auth_status` 和 `big_connect` 已作为 MCP 工具暴露，支持与云端服务器的签名通信（HTTP + scSign）。以下为未实现的优化项。

- [x] **云端授权服务器对接** — ✅ v0.5.0 已实现。`poll_auth_status`（单次查询）和 `big_connect`（一站式授权）已作为 MCP 工具暴露，支持签名请求、自动密码持久化
- [ ] **授权流程内部化** — 云端授权作为 `connect_device` 的内部环节（密码认证失败 → 自动发起云端授权 → 轮询状态 → 获取密码），不作为独立 MCP 工具暴露给 Agent；现有 `poll_auth_status` / `big_connect` 两个 MCP 工具降级为内部函数
- [x] **授权状态轮询** — ✅ `big_connect` 内部已实现 5s×120=600s 轮询循环
- [ ] **本地授权兼容降级** — 云端不可达时自动降级到本地 `local_auth_server`（如已启动），两者均不可达时返回 `needs_password` 提示用户手动输入

### Camera Tracking & Night Vision（摄像头追踪与夜视控制）

- [ ] **Auto-tracking 目标追踪** — 基于事件告警（motion / human / vehicle）的自动追踪：事件到达后调用 `get_ptz_parameters` 获取当前位姿，结合告警方向信息计算目标偏移量，通过 `control_ptz` 步进跟踪；需定义追踪策略（追踪灵敏度、最大追踪时长、回归初始位逻辑）
- [x] **夜视 / 补光灯控制** — ✅ v0.5.0 已实现。`manage_illumination` MCP 工具，双协议（创维 TCP 9010 优先 → ONVIF Imaging 回退），17 个参数（daynightmode / filllightmode / brightness / timer / sensitivity 等），连接时自动探测能力并缓存到 config.yaml

### Tiered Guardian Modes（agent-side，运行时选择）

Agent 首次收到监控请求时，执行一次能力探测决策树，选取可用的最高层级：

| Tier | 宿主能力要求 | Agent 行为 |
|------|-------------|-----------|
| **T1 — On-demand** | 无（基线） | 用户提问 → Agent 调用 `manage_camera_events(action="poll")` → 读快照 → 报告积压 |
| **T2 — In-session guard** | 无（基线） | 用户说"看着" → Agent 循环调用 `manage_camera_events(action="wait")` → 事件到达即分析+报告 |
| **T3 — Heartbeat guard** | 宿主提供调度机制（agent-writable file / cron tool） | Agent 注册定时任务，周期性 poll 事件并通知用户 |
| **T4 — Event-driven wake** | 宿主暴露 webhook 入口 | `toolkit/events.py` 增加 outbound webhook POST → 宿主唤醒 Agent 并传入事件 payload |

- T1/T2 不需要技能包额外代码，当前已可用
- T3 纯 Agent 侧行为，技能包无需改动
- T4 需要技能包增加 webhook POST 能力（依赖宿主先提供 webhook 接口）

### MCP Tool Surface Optimization（MCP 工具面优化）

> **Status:** 评估完成，待实施。当前 17 个 MCP 工具，目标通过参数裁剪、描述精简和子流程内部化降低 Agent 上下文开销。

#### Phase A — Schema 瘦身（零行为变更）

- [ ] **`register_camera` 参数裁剪 10→6** — 保留 `name`、`ip`、`password`、`device_class`、`sn_code`（云端授权依赖）、`rtsp_port`（非标端口需要）；移除 `username`（永远 admin）、`port`（connect_device 自动探测回写）、`rtsp_path`（默认 /stream1 + fallback）、`rtsp_sub_path`（极少用）、`connection_type`（永远 onvif）、`pkdk`（高级字段）
- [ ] **`connect_device` 参数裁剪 7→4** — 保留 `camera_name`、`password`、`ip`、`rtsp_port`；移除 `username`（永远 admin）、`port`（工具自动探测）、`rtsp_path`（工具自动探测）
- [ ] **`request_cloud_auth` 参数裁剪 4→1** — 只保留 `camera_name`；移除 `sn`（自动查找）、`device_ip`（自动查找）、`device_model`（自动查找）
- [ ] **Description 精简** — 移除 5 个工具中的实现细节和行为指引：`control_ptz`（物理极限守护描述）、`manage_camera_events`（四模式实现细节）、`request_cloud_auth`（"模拟智慧云"）、`poll_auth_status`（轮询间隔指引）、`connect_device`（缓存凭据细节）

#### Phase B — 子流程内部化（行为变更）

- [ ] **授权流程内部化** — `request_cloud_auth` + `poll_auth_status` 降级为 `connect_device` 内部环节；`connect_device` 返回 `pending_auth` 时 Agent 只需告知用户打开授权链接并重新调用，内部完成轮询循环（5s×24=120s）；MCP 工具从 17 降至 15
- [ ] **注册自动化** — `register_camera` 降级为 `connect_device` 的内部副作用（连接成功后自动持久化凭据到 config.yaml）；MCP 工具从 15 降至 14
- [ ] **设备列表合并** — `get_registered_cameras` 功能合并到 `search_devices`（无参调用时先返回已注册列表，再补充分发现结果）；MCP 工具从 14 降至 13

#### 优化后工具清单（13 个）

| 扇区 | 工具 | 数量 |
|------|------|------|
| 设备生命周期 | `search_devices`、`connect_device`、`disconnect_device` | 3 |
| 流与媒体 | `get_audio_video_stream`、`capture_video_screenshot`、`toggle_recording`、`manage_storage_status` | 4 |
| PTZ 控制 | `control_ptz`、`get_ptz_parameters`、`calibrate_ptz`、`stop_ptz` | 4 |
| 事件监控 | `manage_camera_events` | 1 |
| 补光控制 | `manage_illumination` | 1 |

#### 远期可选合并（视可靠性评估结果）

- [ ] **PTZ 四合一** `ptz(action=move|get|calibrate|stop)` — 13→10，但需解决 action 选错、参数误传、返回值歧义风险（当前评估为不推荐）
- [ ] **Stream 二合一** `stream(action=url|screenshot)` — 10→9，收益小（~30 token）
- [ ] **理论极限** — 7 个工具（设备 / 流URL / 截图 / 录像 / 存储 / PTZ / 事件），但语义清晰度和可靠性会显著下降

### Structured Error Codes（渐进式错误码系统）

> **Status:** 评估完成，暂缓实施。当前 `error_message` 自然语言 + `status` + `degraded` 三位一体已覆盖 90% 场景，大模型 Agent 可直接理解转述。当小模型/多 Agent 协作成为主力场景时再启动。

- **现有错误传递机制：**
- `success: bool` + `error_message: str` — 全部 17 个工具
- `status: str`（`pending_auth` / `needs_password` / `failed`）— `connect_device`
- `degraded: bool` + `degrade_reason: str` — `control_ptz`

**触发条件：** 当观察到 Agent 频繁对同类错误做出不一致分支决策时启动实施。

**渐进方案（非全面错误码）：**

- [ ] **定义分支决策错误码** — 仅给 Agent 需要根据错误类型做不同操作的场景添加 `error_code` 字段，预定义约 5-6 个码：`AUTH_EXPIRED`（提示重新输入密码）、`DEVICE_OFFLINE`（跳过该设备）、`NETWORK_TIMEOUT`（重试一次）、`PHYSICAL_LIMIT`（展示 degrade_reason，已有 degraded 字段）、`STORAGE_FULL`（提示清理或切换策略）、`STREAM_UNAVAILABLE`（提示检查连接）
- [ ] **扩展 ToolResult 基类** — 在现有 `success` + `error_message` 基础上新增可选 `error_code: str = ""` 字段，仅在分支场景填充，与现有机制完全兼容
- [ ] **关键工具注入错误码** — 在 `connect_device`、`capture_video_screenshot`、`toggle_recording`、`manage_storage_status`、`control_ptz` 的异常处理中添加 `error_code` 赋值（约 30 行改动）
- [ ] **SKILL.md 错误码映射表** — 在文档中增加 `error_code → Agent 预定义动作` 映射表，Agent 有码按码执行，无码照旧读 `error_message`

### External alert channel（外部转发器 — 不在技能包内）

- 转发器作为独立技能/模块，直接从磁盘消费 `events/camera_events.txt`（schema 1.0 JSON lines）和快照文件
- 技能包只定义磁盘存储格式作为**唯一公开集成契约**，不实现、不发布、不感知任何具体转发器
- 集成细节见 `xpai-camera-control/references/EVENT_INTEGRATION.md`
- **Consent-gated:** 快照跨 LAN 推送默认关闭，需用户显式授权


针对 MCP 后端
7. bootstrap 有风险 → 确认 skill 加载时自动拉起 mcp_server.py，避免"工具缺失→手动注册"卡住。