# Event Store — External Consumer Contract

> 面向：任何希望在本技能之上构建上层场景的 skill 作者、外部转发器 / agent-side 模块的作者
> 消费方式：纯磁盘读取（无 MCP 依赖、无进程通信），任何语言 / 框架均可接入
> 对应技能包版本：0.4.2（schema 1.0）

本技能会把报警事件以结构化方式写入一个本地文本文件，供其他 skill 或外部模块消费。这是本技能与外部协作的**唯一公开契约** —— 内部协议、RTSP 地址、凭据、连接状态全部不暴露。

---

## 一、典型上层场景

| 场景 | 消费方 | 说明 |
|------|--------|------|
| 即时消息转发 | 转发器 skill / agent-side 模块 | 把事件 + 抓拍图推送到微信、Slack、Telegram、钉钉等 |
| 智能家居联动 | home-automation skill | 收到 `region_intrusion` / `line_crossing` 事件时触发灯光、蜂鸣器等 |
| 多机位巡检 | 巡检 skill | 按 camera 轮询 backlog，做日报 / 周报汇总 |
| 桌面通知 | agent-side 模块 | 无活跃会话时由 MCP 进程触发系统通知（skill 侧 roadmap） |

本技能只负责"产生 + 落盘"，上层场景的具体行为由消费方自行决定。

## 二、路径（相对于技能包根目录）

| 内容 | 相对路径 | 说明 |
|------|---------|------|
| 事件存储 | `events/camera_events.txt` | 每行一条 schema 1.0 JSON，UTF-8，追加写 |
| 抓拍快照 | `snapshots/` | 事件行内 `snapshot_path` 字段给出**绝对路径**，直接读取即可 |
| Agent 消费游标 | `events/events_cursor.json` | ⚠️ 属于本技能自己的 MCP 端 `poll`/`wait` 消费进度，**外部消费者禁止读写** |
| 监听意图 | `events/monitor_state.json` | ⚠️ 本技能内部状态（start 记录 / stop 清除，用于进程重启后自动恢复监听），**外部消费者禁止读写** |
| 调试转储 | `events/raw_debug.flag` / `events/raw_packets_debug.txt` | ⚠️ 本技能内部调试产物（原始协议包转储，仅排障时临时开启），**非契约内容，外部消费者不得依赖** |

技能包根目录 = 含 `SKILL.md` 的那个目录。若技能被某个 agent 平台按"复制技能目录"的方式安装，根目录就是 `~/.{platform}/skills/xpai-camera-control/`（具体路径以实际平台为准）。

## 三、写入语义（消费者需遵守的约定）

- **编码**：UTF-8，`ensure_ascii=False`（中文原文直接可读）
- **格式**：每行一条完整 JSON，行尾 `\n`；本技能单次 `write(行+\n)` 追加写入
- **只处理完整行**：仅消费以换行符结束的行；空行跳过；JSON 解析失败的行跳过
- **文件可能不存在**：监听从未启动过时无此文件，按"暂无事件"处理
- **目前不做轮转**：不要假设文件会被截断；但需要容忍未来文件被清理后 offset 失效（offset > 文件大小时重置为 0 或文件尾）

## 四、schema 1.0 字段

```json
{
  "schema_version": "1.0",
  "event_id": "20260729_093000_frontdoor_motion",
  "event_type": "motion",
  "camera_id": "frontdoor",
  "camera_name": "前门",
  "timestamp": "2026-07-29T09:30:00+08:00",
  "severity": "warning",
  "title": "前门 检测到移动",
  "message": "前门摄像头在 09:30:00 检测到画面移动，已抓拍。",
  "label": "person",
  "confidence": 0.92,
  "snapshot_path": "C:/.../snapshots/前门_20260729_093000.jpg",
  "tags": ["guardian"]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定 `"1.0"`；消费者应校验，遇到未知版本降级为只转发 `title`/`message` |
| `event_id` | string | `{YYYYMMDD_HHMMSS}_{camera_id}_{event_type}`，**幂等去重键** |
| `event_type` | string | `motion` / `human` / `vehicle` / `tamper` / `region_intrusion` / `line_crossing` / `high_temp` / `low_temp`（可能扩展，未知值按 `info` 处理） |
| `camera_id` | string | 摄像头注册名（`config.yaml` 中的键） |
| `camera_name` | string | 可选。展示名，无独立展示名时同 `camera_id` |
| `timestamp` | string | ISO 8601 含本地时区，秒精度 |
| `severity` | string | 可选。`info` / `warning`（motion/human/vehicle） / `critical`（tamper/入侵/越界/温度） |
| `title` | string | 现成的通知标题（中文） |
| `message` | string | 现成的通知正文（中文，含时间与是否抓拍） |
| `label` | string \| null | 目标类别（person/car/truck…），无法提取时 `null` |
| `confidence` | number \| null | 置信度 0~1，协议未提供时 `null` |
| `snapshot_path` | string | 快照绝对路径；**可能为空串**（限流窗口内未抓拍），此时只发文字 |
| `tags` | string[] | 可选。当前固定 `["guardian"]` |

## 五、消费方接入建议

1. **只读 tail 消费**：轮询（建议 2~5 s）或文件监听检测新增内容；维护**消费者自己的**字节偏移 / 行号（持久化在消费者自己的目录，不要碰 `events/` 下的任何文件）
2. **幂等**：按 `event_id` 去重，避免 offset 重置或重启后重复处理
3. **通知文案**：转发类消费方可直接使用 `title` + `message`，附图读 `snapshot_path`（为空则纯文字）——本技能只报警，不做画面分析；深度分析由上层场景自行完成
4. **降噪（可选）**：按 `severity` 过滤（如仅 `warning`/`critical`）；同 `camera_id`+`event_type` 加消费者端冷却窗口（本技能已做 5 s 去重，消费侧可再加分钟级冷却）
5. **对技能包目录的操作权限**：`events/` 与 `snapshots/` 一律**只读**；游标文件 `events_cursor.json` 是本技能 MCP 端的消费进度，外部消费者复用会"吃掉"本技能 `poll`/`wait` 的待读事件

## 六、安全约束（硬性）

- **默认关闭**：任何"把事件 / 快照发往本局域网外"的上层场景，必须在用户**显式授权后**才启用，且要告知用户如何关闭；本技能默认只在本地落盘
- **本地为权威副本**：外部消费只是本地存储之上的可选附加通道，任何消费失败不应影响本地事件链路
- **只读、不分析**：转发内容限于 schema 1.0 中的文案与快照，不暴露凭据、RTSP 地址、连接状态等任何配置信息

## 七、版本演进

- 当前契约版本：`schema_version = "1.0"`
- 字段扩展方式：新增字段采用 `Optional` 语义（消费者应容忍旧数据缺少新字段）；不得删除现有字段；若字段语义发生变化，递增 `schema_version` 主版本号并同步更新本文档
