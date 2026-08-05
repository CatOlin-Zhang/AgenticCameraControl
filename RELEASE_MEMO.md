# xpai-camera-control 发布备忘录

> **当前版本：0.5.0** | 传输协议: MCP stdio | MCP 工具数: 17

---

## v0.5.0 变更记录（2026-08-03）

### 新增：补光/夜视模式控制模块 (`illumination.py`)

| 变更 | 说明 |
|---|---|
| 新 MCP 工具 `manage_illumination` | 统一补光入口，action 切换 get/set，15 个参数（daynightmode、filllightmode、brightness、timer、sensitivity 等） |
| 双协议策略 | 创维私有协议 (TCP 9010) 优先 → ONVIF Imaging Service 回退。与 PTZ 方向相反 |
| 能力探测与缓存 | `connect_device` 成功后自动探测补光能力 (`probe_illumination_capability`)，结果持久化到 config.yaml 的 `illumination_modes` 字段 |
| 纵深防御路由修复 | 三处修复确保创维设备始终尝试 TCP 9010：(1) 路由层 always-try-TCP (2) 探测层回写 tcp_port (3) 缓存层补充 tcp_port |

### 新增：云端授权工具 (`device_mgmt.py`)

| 变更 | 说明 |
|---|---|
| 新 MCP 工具 `poll_auth_status` | 轮询云端授权状态，单次查询。connect_device 返回 pending_auth 后调用，Agent 应循环调用（5s 间隔，最长 10 分钟） |
| 新 MCP 工具 `big_connect` | 一站式云端授权：发起请求 + 轮询结果（最长 10 分钟）+ 自动写密码 + 连接设备。可省略 name 参数自动选择唯一设备 |

### 文档更新

| 文件 | 变更 |
|---|---|
| `SKILL.md` | 新增 illumination Extended Capability 行、Quick Reference 示例、References 链接 |
| `SKILL_TECHNICAL_REFERENCE.md` | 新增 §2.5 manage_illumination、§3.5 Illumination 内部函数、调用关系图、双协议策略表 |
| `ARCHITECTURE.md` | 新增 Illumination Mode Control Architecture 章节，含路由决策图 + always-try-TCP rationale |
| `WORKFLOW.md` | 新增 Illumination Mode Control Extended Tools 章节 |
| `references/commands/illumination.md` | 新增完整的工具签名、参数表、返回字段参考 |
| `README.md` | 功能概览、项目结构、工具模块表补全 illumination 条目 |
| `TODOlist.md` | “夜视 / 补光灯控制”标记为已完成，工具计数更新为 17 |

---

## v0.4.5 及以前（UVX 方案，部分已过时）

> **⚠️ 状态：以下内容仅作历史参考。** `pyproject.toml` 和 `scripts/toolkit/paths.py` 已从仓库移除，uvx 三形态改造产物不再存在。实际发布需重新构建打包配置。
>
> 记录时间：2026-07-28
> 备忘录原始版本为 0.3.0

## 一、改造内容回顾

| 交付物 | 说明 |
|---|---|
| `pyproject.toml` | PyPI 打包配置：`scripts/` 目录映射为 `xpai_camera_control` 包；console script 入口 `xpai-camera-control = "xpai_camera_control.mcp_server:cli"` |
| `scripts/toolkit/paths.py` | 双形态路径解析：技能目录直跑（数据落技能根目录）vs pip/uvx 安装（数据落 `~/.xpai-camera-control/`）；环境变量 `XPAI_DATA_DIR` / `XPAI_CONFIG_PATH` 可覆盖 |
| `scripts/mcp_server.py` | 双模式导入（相对导入 → `scripts.` 绝对导入回退）；新增 `cli()` 入口；版本升至 0.3.0 |
| `scripts/toolkit/device_mgmt.py` | `CONFIG_PATH` 改用 `get_config_path()`，注册/读取配置路径统一 |
| `scripts/toolkit/stream.py` | snapshots / recordings 目录改用 `get_snapshots_dir()` / `get_recordings_dir()` |
| `SKILL.md` | Running Mode 改为 uvx 主配置 + 本地开发 fallback；双形态数据目录说明 |

## 二、验证结果（2026-07-28，全部 PASS）

| 形态 | 启动方式 | 结果 |
|---|---|---|
| 技能目录直跑 | `python scripts/mcp_server.py`（Anaconda env） | ✅ serverInfo 0.3.0 |
| pip 安装态 | `python -m xpai_camera_control.mcp_server`（wheel 装临时目录） | ✅ serverInfo 0.3.0 |
| uvx 端到端 | `uvx --from dist\xpai_camera_control-0.3.0-py3-none-any.whl xpai-camera-control` | ✅ serverInfo 0.3.0 |

补充确认：

- lint 检查 4 个改动文件无错误
- initialize 阶段不会创建 `~/.xpai-camera-control/`（toolkit 懒加载，仅真正调用工具时建目录，启动零副作用）
- 已构建产物：`dist\xpai_camera_control-0.3.0-py3-none-any.whl`（约 52 KB）

## 三、上架后用户侧 MCP 配置（零路径）

```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "uvx",
      "args": ["xpai-camera-control"]
    }
  }
}
```

本地开发 fallback（未发布 PyPI 时）：

```json
{
  "mcpServers": {
    "xpai-camera-control": {
      "command": "<绝对路径>/python.exe",
      "args": ["<绝对路径>/xpai-camera-control/scripts/mcp_server.py"]
    }
  }
}
```

## 四、发布前待办清单

- [ ] **PyPI 包名占位确认**：注册时确认 `xpai-camera-control` 是否可用；若被占用需改名（同步改 `pyproject.toml` 的 `name`、`[project.scripts]` 与 SKILL.md 中的 uvx 配置）
- [ ] **TestPyPI 试发布**（推荐先走一遍）：
  ```
  python -m pip install twine
  twine upload --repository testpypi dist/*
  uvx --index-url https://test.pypi.org/simple/ xpai-camera-control   # 验证
  ```
- [ ] **正式发布 PyPI**（需 PyPI 账号 + API token）：
  ```
  twine upload dist/*
  ```
- [ ] **`.gitignore` 增加 `dist/`**（避免构建产物入库）
- [ ] **版本迭代规则**：后续每次发布需同步升 `pyproject.toml` 的 `version` 与 `mcp_server.py` 中 `Server(..., version=...)`

## 五、注意事项 / 坑

- PowerShell 命令行内联中文路径会编码损坏，须用 `$HOME` / `Join-Path` 运行时构造
- `scripts/` 目录名保持不变，直跑形态与 WorkBuddy 技能安装机制（复制到 `~/.workbuddy/skills/` + 专用 venv）均不受影响
- uvx 每次冷启动会解析依赖（opencv-python 较大），首次启动偏慢属正常现象，uv 有缓存后续会快
- 数据目录判定依据：包上级目录是否存在 `SKILL.md`（存在 → 技能直跑形态；不存在 → 安装形态用 `~/.xpai-camera-control/`）
