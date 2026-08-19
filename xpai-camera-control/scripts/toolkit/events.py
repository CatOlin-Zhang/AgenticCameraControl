"""
Toolkit 6: IPC 事件接收 (Guardian Mode Foundation)

工具清单：
  - manage_camera_events  统一事件入口（唯一 MCP 工具），action 切换工作模式:
      start — 启动指定摄像头的事件监听（双协议，后台线程）
      stop  — 停止事件监听
      poll  — 读取未消费事件（磁盘存储 + 消费游标）
      wait  — 长轮询阻塞等待新事件（默认/上限 60s）
  注: start_event_monitor / stop_event_monitor / get_pending_events /
      wait_for_events 为各模式的内部实现，保留导出供二次开发直接调用，
      但不作为 MCP 工具单独暴露（降低 MCP schema 负载）

双协议事件源：
  1. ONVIF Event Service — CreatePullPointSubscription + PullMessages 循环
     （创维 ONVIF 端口实测 2000）
  2. 创维私有协议 — 报警消息通过 RTSP interleaved 通道 0x65 上报（alarm.py 实测）：
     建立 RTSP 会话后（User-Agent 须为 "skyworth"），对 SDP 每个视频轨道
     逐一 SETUP（interleaved=0-1, 2-3...），设备识别 UA 后在同一 TCP 连接的
     channel 0x65 上推送报警 JSON（~94 字节，可能是纯 JSON 或 RTP 包裹）：
       {"ser":"alarm","alm":"MP","dat":"01:16 5:01:2026 -07-30 1",
        "dir":0,"fn":"","fmt":"JPEG"}
     兼容 serv/ser、date/dat 两套字段名（不同固件版本）。
     alm 取值: MD/MP移动/HD人形/VGR区域/VGL越界/VS遮挡/VD车辆/HTD高温/LTD低温

落盘存储（单一真相源，见 TODOlist.md Guardian Mode）：
  - 原始协议消息（ONVIF NotificationMessage / 私有协议报警 JSON）不落盘、
    不转发；经 _process_event_message() 加工成 schema 1.0 格式后写入：
  - events/camera_events.txt — 每事件一行 schema 1.0 JSON，追加写
  - events/events_cursor.json  — 各消费游标（按相机记录已消费的行号）
  - events/monitor_state.json  — 监听意图（start 记录 / stop 清除）：MCP 进程
    可能被宿主随时回收，监听线程随之消亡；意图落盘后，server 启动时与
    poll/wait 入口会自动恢复用户尚未撤销的监听（resume_persisted_monitors）
  - MCP server 进程不跨 session 存活，因此内存队列仅作热缓存，
    poll / wait 一律读磁盘存储

schema 1.0 落盘格式（camera_name / severity / tags 为可选字段）：
  {"schema_version": "1.0", "event_id": "20260729_093000_frontdoor_motion",
   "event_type": "motion", "camera_id": "frontdoor", "camera_name": "前门",
   "timestamp": "2026-07-29T09:30:00+08:00", "severity": "warning",
   "title": "前门 检测到移动", "message": "前门摄像头在 09:30:00 检测到画面移动，已抓拍。",
   "label": "person", "confidence": 0.92, "snapshot_path": "...", "tags": ["guardian"]}

去重（debounce）：
  - 同一 (camera, 归一化 topic) 在去重窗口（默认 5s）内只落盘一条，
    跨协议重复（ONVIF 与私有协议同时上报同一动侦）同样被合并
  - 快照按相机限流：窗口内同机只截一张，防止磁盘被爆发事件刷爆

安全边界：
  - 后台线程仅用于事件监听，且只在用户通过 start_event_monitor 显式
    启用后才启动；行为限于报警订阅 + 写入 snapshots/ 与 events/ 白名单路径
  - 自动恢复不新增授权面：monitor_state.json 只在用户显式 start 时写入、
    stop 时清除，恢复动作仅重建用户尚未撤销的监听，不会自行开启新监听
"""
import json
import re
import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    import requests as _requests_lib
except ImportError:
    _requests_lib = None


# ──────────────────────────────────────────────
#  常量与路径
# ──────────────────────────────────────────────

_SKILL_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = _SKILL_ROOT / "events"                      # 事件落盘目录（白名单路径）
EVENT_STORE_PATH = EVENTS_DIR / "camera_events.txt"      # 事件存储（追加写，单一真相源）
EVENT_CURSOR_PATH = EVENTS_DIR / "events_cursor.json"    # 消费游标（按相机）
MONITOR_STATE_PATH = EVENTS_DIR / "monitor_state.json"   # 监听意图（start 记录 / stop 清除，跨进程存活）

EVENT_SCHEMA_VERSION = "1.0"      # 落盘消息的 schema 版本

DEFAULT_DEBOUNCE_SECONDS = 5.0    # 去重/快照限流窗口
WAIT_TIMEOUT_CAP = 60.0           # wait_for_events 阻塞上限（对齐 MCP 客户端 stdio 超时）
_STORE_MAX_READ = 10000           # 单次最多读取的存储行数（防止超大文件拖垮）
_RESUME_RETRY_SECONDS = 60.0      # 自动恢复失败后的重试冷却（防止离线相机被频繁探测）

# 创维私有报警通道号（RTSP interleaved channel），设备通过此通道推送报警 JSON
SK_ALARM_CHANNEL = 0x65           # 101（创维），杰高用 0x63=99
# RTSP User-Agent：设备端检查此值，仅 "skyworth" / "Jabsco" 推送报警
SK_RTSP_USER_AGENT = "skyworth"

# 私有协议 alm 代码 → 归一化 topic（与 ONVIF 侧共用同一命名空间，跨协议去重的前提）
SK_ALM_TOPIC_MAP = {
    "MD": "motion",           # 移动侦测
    "MP": "motion",           # 移动侦测（部分固件用 MP）
    "HD": "human",            # 人形侦测
    "VGR": "region_intrusion",  # 区域侦测
    "VGL": "line_crossing",   # 越界侦测
    "VS": "tamper",           # 遮挡侦测
    "VD": "vehicle",          # 车辆侦测
    "HTD": "high_temp",       # 高温侦测
    "LTD": "low_temp",        # 低温侦测
}

# ONVIF Topic 关键字 → 归一化 topic（按顺序匹配，先命中先得）
_ONVIF_TOPIC_RULES: List[Tuple[str, str]] = [
    ("tamper", "tamper"),
    ("shield", "tamper"),
    ("motion", "motion"),
    ("human", "human"),
    ("people", "human"),
    ("person", "human"),
    ("line", "line_crossing"),
    ("crossed", "line_crossing"),
    ("field", "region_intrusion"),
    ("intrusion", "region_intrusion"),
    ("vehicle", "vehicle"),
]

# PullMessages 里表示"事件是否激活"的布尔字段名（小写比较）
_ONVIF_BOOL_ITEM_NAMES = {"ismotion", "state", "istamper", "isinside", "logicalstate", "alarm"}

# event_type → severity（schema 可选字段，缺省按此映射）
EVENT_SEVERITY_MAP = {
    "motion": "warning",
    "human": "warning",
    "vehicle": "warning",
    "tamper": "critical",
    "region_intrusion": "critical",
    "line_crossing": "critical",
    "high_temp": "critical",
    "low_temp": "critical",
}

# event_type → (title 短语, message 描述)，用于生成人可读文案
_EVENT_TEXT_MAP = {
    "motion": ("检测到移动", "检测到画面移动"),
    "human": ("检测到人形", "检测到有人出现"),
    "vehicle": ("检测到车辆", "检测到车辆出现"),
    "tamper": ("镜头遭遮挡", "检测到镜头被遮挡"),
    "region_intrusion": ("区域入侵告警", "检测到目标进入警戒区域"),
    "line_crossing": ("越界告警", "检测到目标跨越警戒线"),
    "high_temp": ("高温告警", "检测到高温异常"),
    "low_temp": ("低温告警", "检测到低温异常"),
}

# 私有协议 data 字段 SUBTYPE → 归一化 label（未命中则用小写原值）
_SUBTYPE_LABEL_MAP = {
    "person": "person",
    "human": "person",
    "salooncar": "car",
    "car": "car",
    "truck": "truck",
    "bus": "bus",
    "motorcycle": "motorcycle",
    "bicycle": "bicycle",
}


# ──────────────────────────────────────────────
#  RTSP Interleaved 帧解析器（移植自 alarm.py _FrameParser）
# ──────────────────────────────────────────────

class _InterleavedFrameParser:
    """RTSP over TCP interleaved 帧解析器（RFC 2326 §10.12）。

    协议格式: '$' <channel_id: uint8> <length: uint16 big-endian> <payload: bytes>
    解析器同时兼容跳过 RTSP 文本响应（以 "RTSP/" 开头的行）和空白字节。
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        """追加原始 TCP 数据，返回已解析的 (channel_id, payload) 列表。"""
        self._buf.extend(data)
        frames: List[Tuple[int, bytes]] = []

        while len(self._buf) >= 4:
            # ── 跳过 RTSP 文本响应行（OPTIONS 等响应残留） ──
            if self._buf[0:5] == b"RTSP/" or (
                self._buf[0:1] != b"$" and self._buf[0:1] in b" \t\r\n"
            ):
                nl = self._buf.find(b"\n")
                if nl == -1:
                    break  # 等待更多数据
                del self._buf[: nl + 1]
                continue

            # ── 必须是 $ 开头 ──
            if self._buf[0:1] != b"$":
                # 未知字节，跳过直到下一个 $
                idx = self._buf.find(b"$", 1)
                if idx == -1:
                    self._buf.clear()
                    break
                del self._buf[:idx]
                continue

            # 解析 $ <ch:1> <len:2>
            if len(self._buf) < 4:
                break
            ch = self._buf[1]
            length = struct.unpack("!H", self._buf[2:4])[0]

            # 合理性检查（单帧 ≤ 64 KB）
            if length > 65536 or length == 0:
                del self._buf[:1]
                continue

            # 等完整 payload
            if len(self._buf) < 4 + length:
                break

            payload = bytes(self._buf[4: 4 + length])
            del self._buf[: 4 + length]
            frames.append((ch, payload))

        return frames


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

class EventAction(Enum):
    """manage_camera_events 工作模式"""
    START = "start"   # 启动监听（后台线程）
    STOP = "stop"     # 停止监听
    POLL = "poll"     # 读取未消费事件并推进游标
    WAIT = "wait"     # 长轮询阻塞等待新事件


@dataclass
class CameraEvent:
    """一条已落盘的摄像头事件（schema 1.0，即落盘/对外格式，不含原始协议字段）"""
    schema_version: str = EVENT_SCHEMA_VERSION
    event_id: str = ""                # {YYYYMMDD_HHMMSS}_{camera_id}_{event_type}
    event_type: str = ""              # 归一化事件类型 (motion / human / tamper / ...)
    camera_id: str = ""               # 摄像头注册名（config.yaml 键）
    camera_name: str = ""             # 展示名（可选，无独立展示名时同 camera_id）
    timestamp: str = ""               # ISO 8601 含时区 (2026-07-29T09:30:00+08:00)
    severity: str = ""                # 可选: info / warning / critical
    title: str = ""                   # 人可读标题
    message: str = ""                 # 人可读正文
    label: Optional[str] = None       # 目标类别（如 person/car），无法提取时为 null
    confidence: Optional[float] = None  # 置信度，协议未提供时为 null
    snapshot_path: str = ""           # 联动快照路径（限流窗口内可能为空）
    tags: List[str] = field(default_factory=lambda: ["guardian"])  # 可选标签


@dataclass
class EventMonitorResult:
    """start/stop_event_monitor 返回结果"""
    success: bool                     # 操作是否成功
    camera_name: str = ""             # 摄像头名称
    running: bool = False             # 监听是否在运行
    active_channels: List[str] = field(default_factory=list)  # 已激活的协议通道
    error_message: str = ""           # 失败原因


@dataclass
class PendingEventsResult:
    """get_pending_events / wait_for_events 返回结果"""
    success: bool                     # 操作是否成功
    events: List[CameraEvent] = field(default_factory=list)  # 本次消费的事件
    remaining: int = 0                # 存储中尚未消费的事件数
    monitors: Dict[str, Any] = field(default_factory=dict)   # 各监听器运行状态
    error_message: str = ""           # 失败原因


# ──────────────────────────────────────────────
#  落盘存储（单一真相源）
# ──────────────────────────────────────────────

_store_lock = threading.Lock()
_event_arrived = threading.Condition(_store_lock)   # wait_for_events 唤醒信号


def _ensure_events_dir() -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def _append_event_to_store(event: Dict[str, Any]) -> None:
    """追加一条 schema 1.0 事件到 txt 存储（每行一条 JSON）并唤醒等待者（线程安全）"""
    with _event_arrived:
        _ensure_events_dir()
        with open(EVENT_STORE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        _event_arrived.notify_all()


def _read_store_lines() -> List[Dict[str, Any]]:
    """读取全部事件行（调用方须持有 _store_lock）"""
    if not EVENT_STORE_PATH.exists():
        return []
    events = []
    try:
        with open(EVENT_STORE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(events) >= _STORE_MAX_READ:
                    break
    except OSError:
        return []
    return events


def _load_cursor() -> Dict[str, int]:
    """加载各相机的消费游标 {camera: 已消费到的全局行号}（调用方须持有 _store_lock）"""
    if not EVENT_CURSOR_PATH.exists():
        return {}
    try:
        with open(EVENT_CURSOR_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cursor(cursor: Dict[str, int]) -> None:
    """持久化消费游标（调用方须持有 _store_lock）"""
    _ensure_events_dir()
    with open(EVENT_CURSOR_PATH, "w", encoding="utf-8") as f:
        json.dump(cursor, f, ensure_ascii=False, indent=2)


def _collect_pending(
    camera_name: Optional[str],
    limit: int,
    advance: bool,
) -> Tuple[List[Dict[str, Any]], int]:
    """从磁盘存储收集未消费事件并（可选）推进游标。

    游标语义：cursor[camera] = 该相机已消费到的全局行号（行号之前的该相机事件均已消费）。
    按相机独立推进，get_pending_events(camera_name=X) 不会吞掉其他相机的事件。

    Returns:
        (pending_events, remaining_count)
    """
    with _store_lock:
        lines = _read_store_lines()
        cursor = _load_cursor()
        new_cursor = dict(cursor)
        pending: List[Dict[str, Any]] = []

        for idx, evt in enumerate(lines):
            cam = str(evt.get("camera_id", ""))
            if camera_name and cam != camera_name:
                continue
            if idx < cursor.get(cam, 0):
                continue
            if len(pending) >= limit:
                break
            pending.append(evt)
            new_cursor[cam] = idx + 1

        # 统计剩余未消费数（含因 limit 截断的部分）
        remaining = 0
        for idx, evt in enumerate(lines):
            cam = str(evt.get("camera_id", ""))
            if camera_name and cam != camera_name:
                continue
            if idx >= new_cursor.get(cam, 0):
                remaining += 1

        if advance and pending:
            _save_cursor(new_cursor)

    return pending, remaining


def _dict_to_camera_event(d: Dict[str, Any]) -> CameraEvent:
    return CameraEvent(
        schema_version=str(d.get("schema_version", EVENT_SCHEMA_VERSION)),
        event_id=str(d.get("event_id", "")),
        event_type=str(d.get("event_type", "")),
        camera_id=str(d.get("camera_id", "")),
        camera_name=str(d.get("camera_name", "")),
        timestamp=str(d.get("timestamp", "")),
        severity=str(d.get("severity", "")),
        title=str(d.get("title", "")),
        message=str(d.get("message", "")),
        label=d.get("label"),
        confidence=d.get("confidence"),
        snapshot_path=str(d.get("snapshot_path", "")),
        tags=d.get("tags", []) if isinstance(d.get("tags"), list) else [],
    )


# ──────────────────────────────────────────────
#  消息处理（原始协议消息 → schema 1.0 落盘格式）
# ──────────────────────────────────────────────

def _parse_private_data_field(data: str) -> Dict[str, str]:
    """解析私有协议 data 字段（"SUBTYPE=SaloonCar;X=30;..."）为键值对"""
    result: Dict[str, str] = {}
    for part in (data or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip().upper()] = v.strip()
    return result


def _extract_label_confidence(
    event_type: str,
    source: str,
    detail: Dict[str, Any],
) -> Tuple[Optional[str], Optional[float]]:
    """从协议原始字段提取目标类别与置信度；无法提取时为 None"""
    label: Optional[str] = None
    confidence: Optional[float] = None

    if source == "private":
        kv = _parse_private_data_field(str(detail.get("data", "")))
        subtype = kv.get("SUBTYPE", "")
        if subtype:
            label = _SUBTYPE_LABEL_MAP.get(subtype.lower(), subtype.lower())
        for key in ("CONFIDENCE", "CONF", "PROB"):
            if key in kv:
                try:
                    val = float(kv[key])
                    confidence = round(val / 100.0 if val > 1.0 else val, 4)
                except ValueError:
                    pass
                break

    # 事件类型本身即目标类别时的兜底
    if label is None and event_type == "human":
        label = "person"
    elif label is None and event_type == "vehicle":
        label = "vehicle"
    return label, confidence


def _process_event_message(
    camera_id: str,
    event_type: str,
    source: str,
    detail: Optional[Dict[str, Any]],
    snapshot_path: str,
    display_name: str = "",
) -> Dict[str, Any]:
    """消息处理逻辑：把协议原始消息加工成 schema 1.0 落盘格式。

    原始协议字段（ONVIF Topic 全文、私有协议 fn/num/data 等）处理完即丢弃，
    仅提炼出 label / confidence；落盘内容严格等于 schema 1.0 字段集。
    """
    dt = datetime.now().astimezone()
    name = display_name or camera_id
    title_phrase, message_phrase = _EVENT_TEXT_MAP.get(
        event_type, (f"{event_type} 告警", f"上报 {event_type} 事件")
    )
    label, confidence = _extract_label_confidence(event_type, source, detail or {})
    suffix = "，已抓拍。" if snapshot_path else "。"

    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": f"{dt.strftime('%Y%m%d_%H%M%S')}_{camera_id}_{event_type}",
        "event_type": event_type,
        "camera_id": camera_id,
        "camera_name": name,
        "timestamp": dt.isoformat(timespec="seconds"),
        "severity": EVENT_SEVERITY_MAP.get(event_type, "info"),
        "title": f"{name} {title_phrase}",
        "message": f"{name}摄像头在 {dt.strftime('%H:%M:%S')} {message_phrase}{suffix}",
        "label": label,
        "confidence": confidence,
        "snapshot_path": snapshot_path,
        "tags": ["guardian"],
    }


# ──────────────────────────────────────────────
#  Topic 归一化
# ──────────────────────────────────────────────

def _normalize_onvif_topic(raw_topic: str) -> str:
    """把 ONVIF Topic（如 tns1:RuleEngine/CellMotionDetector/Motion）归一化"""
    low = (raw_topic or "").lower()
    for keyword, topic in _ONVIF_TOPIC_RULES:
        if keyword in low:
            return topic
    # 兜底：取路径最后一段
    tail = re.split(r"[/:]", raw_topic.strip())[-1] if raw_topic.strip() else "unknown"
    return tail.lower() or "unknown"


def _normalize_private_topic(alm: str) -> str:
    """把私有协议 alm 代码归一化"""
    return SK_ALM_TOPIC_MAP.get((alm or "").strip().upper(), (alm or "unknown").lower())


# ──────────────────────────────────────────────
#  事件监听器（后台线程，仅经 start_event_monitor 显式启用）
# ──────────────────────────────────────────────

class _CameraEventMonitor:
    """单相机双协议事件监听器。

    - ONVIF 通道: PullPoint 订阅 + PullMessages 长轮询线程
    - 私有通道:   RTSP 会话内报警 JSON 推送监听线程
    两通道产生的事件统一经 _emit() 去重后落盘。
    """

    def __init__(
        self,
        camera_name: str,
        ip: str,
        onvif_port: int,
        rtsp_port: int,
        rtsp_path: str,
        username: str,
        password: str,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    ):
        self.camera_name = camera_name
        self.ip = ip
        self.onvif_port = onvif_port
        self.rtsp_port = rtsp_port
        self.rtsp_path = rtsp_path or "/stream2"
        self.username = username
        self.password = password
        self.debounce = max(0.5, float(debounce_seconds))

        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._channels: Dict[str, bool] = {}          # 协议通道 → 是否激活
        self._subscription_url: str = ""              # ONVIF PullPoint 订阅地址
        self._last_emit: Dict[Tuple[str, str], float] = {}   # (camera, topic) → 上次落盘时间
        self._last_snapshot: float = 0.0              # 上次联动快照时间（按相机限流）
        self._suppressed_count = 0                    # 被去重合并掉的事件数
        self._emitted_count = 0                       # 已落盘事件数
        self._lock = threading.Lock()

    # ── 状态 ──

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "channels": dict(self._channels),
            "emitted": self._emitted_count,
            "suppressed": self._suppressed_count,
            "debounce_seconds": self.debounce,
        }

    # ── 启动 / 停止 ──

    def start(self, protocols: str = "both") -> List[str]:
        """启动监听通道。protocols: both / onvif / private。返回激活的通道列表。"""
        active = []

        if protocols in ("both", "onvif", "auto"):
            if self._try_create_subscription():
                self._channels["onvif"] = True
                t = threading.Thread(
                    target=self._onvif_pull_loop,
                    name=f"EventMonitor-onvif-{self.camera_name}",
                    daemon=True,
                )
                t.start()
                self._threads.append(t)
                active.append("onvif")
            else:
                self._channels["onvif"] = False

        if protocols in ("both", "private", "auto"):
            # auto 语义: ONVIF 订阅成功时私有通道仍启动（跨协议去重兜底漏报）
            if self._probe_tcp(self.ip, self.rtsp_port):
                self._channels["private"] = True
                t = threading.Thread(
                    target=self._private_rtsp_alarm_loop,
                    name=f"EventMonitor-private-{self.camera_name}",
                    daemon=True,
                )
                t.start()
                self._threads.append(t)
                active.append("private")
            else:
                self._channels["private"] = False

        return active

    def stop(self) -> None:
        self._stop_event.set()
        self._try_unsubscribe()
        for t in self._threads:
            t.join(timeout=3)
        self._threads = []
        self._channels = {k: False for k in self._channels}

    @staticmethod
    def _probe_tcp(ip: str, port: int, timeout: float = 3.0) -> bool:
        try:
            sock = socket.create_connection((ip, port), timeout=timeout)
            sock.close()
            return True
        except OSError:
            return False

    # ── 去重 + 落盘（两协议共用出口） ──

    def _emit(
        self,
        topic: str,
        source: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = time.time()
        key = (self.camera_name, topic)

        with self._lock:
            # 去重：同 (camera, topic) 窗口内只落盘一条（跨协议同样命中）
            if now - self._last_emit.get(key, 0.0) < self.debounce:
                self._suppressed_count += 1
                return
            self._last_emit[key] = now

            # 快照限流：窗口内同机只截一张
            take_snapshot = (now - self._last_snapshot) >= self.debounce
            if take_snapshot:
                self._last_snapshot = now

        snapshot_path = ""
        if take_snapshot:
            snapshot_path = self._capture_snapshot()

        # 消息处理：原始协议消息不落盘，加工成 schema 1.0 后写入存储
        event = _process_event_message(
            camera_id=self.camera_name,
            event_type=topic,
            source=source,
            detail=detail,
            snapshot_path=snapshot_path,
        )
        _append_event_to_store(event)
        with self._lock:
            self._emitted_count += 1

    def _capture_snapshot(self) -> str:
        """事件联动快照（同进程内部调用，不经 Agent）。失败不阻断事件落盘。"""
        try:
            from .stream import capture_video_screenshot
            result = capture_video_screenshot(self.camera_name)
            if result.success:
                return result.file_path
        except Exception:
            pass
        return ""

    # ══════════════════════════════════════════
    #  通道 1: ONVIF PullPoint
    # ══════════════════════════════════════════

    _CREATE_SUBSCRIPTION_BODY = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tev="http://www.onvif.org/ver10/events/wsdl">'
        '<soap:Header/><soap:Body>'
        '<tev:CreatePullPointSubscription>'
        '<tev:InitialTerminationTime>PT600S</tev:InitialTerminationTime>'
        '</tev:CreatePullPointSubscription>'
        '</soap:Body></soap:Envelope>'
    )

    _PULL_MESSAGES_BODY = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tev="http://www.onvif.org/ver10/events/wsdl">'
        '<soap:Header/><soap:Body>'
        '<tev:PullMessages>'
        '<tev:Timeout>PT10S</tev:Timeout>'
        '<tev:MessageLimit>32</tev:MessageLimit>'
        '</tev:PullMessages>'
        '</soap:Body></soap:Envelope>'
    )

    _UNSUBSCRIBE_BODY = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2">'
        '<soap:Header/><soap:Body><wsnt:Unsubscribe/></soap:Body></soap:Envelope>'
    )

    # 事件服务候选路径（创维实测 device_service 同端口提供 event 服务）
    _EVENT_SERVICE_PATHS = ["/onvif/event_service", "/onvif/Events", "/onvif/device_service"]

    def _try_create_subscription(self) -> bool:
        """创建 PullPoint 订阅，成功则记录订阅地址"""
        if not self.onvif_port or _requests_lib is None:
            return False
        from .device_mgmt import _onvif_post_with_auth
        for path in self._EVENT_SERVICE_PATHS:
            try:
                status, body = _onvif_post_with_auth(
                    self.ip, self.onvif_port, path,
                    self._CREATE_SUBSCRIPTION_BODY,
                    self.username, self.password, timeout=8.0,
                )
            except Exception:
                continue
            if status != 200 or "SubscriptionReference" not in body:
                continue
            addr = self._parse_subscription_address(body)
            if addr:
                self._subscription_url = addr
                return True
        return False

    @staticmethod
    def _parse_subscription_address(body: str) -> str:
        """从 CreatePullPointSubscriptionResponse 提取订阅 Address"""
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return ""
        for el in root.iter():
            if el.tag.endswith("SubscriptionReference"):
                for child in el.iter():
                    if child.tag.endswith("Address") and (child.text or "").strip():
                        return child.text.strip()
        return ""

    def _onvif_pull_loop(self) -> None:
        """PullMessages 长轮询循环；订阅失效时自动重建"""
        from .device_mgmt import _onvif_post_with_auth
        consecutive_failures = 0

        while not self._stop_event.is_set():
            if not self._subscription_url:
                if not self._try_create_subscription():
                    self._channels["onvif"] = False
                    if self._stop_event.wait(30.0):
                        return
                    continue
                self._channels["onvif"] = True

            parsed = urlparse(self._subscription_url)
            sub_ip = parsed.hostname or self.ip
            sub_port = parsed.port or self.onvif_port
            sub_path = parsed.path or "/onvif/event_service"

            try:
                status, body = _onvif_post_with_auth(
                    sub_ip, sub_port, sub_path,
                    self._PULL_MESSAGES_BODY,
                    self.username, self.password, timeout=15.0,
                )
            except Exception:
                status, body = 0, ""

            if status == 200 and "Envelope" in body:
                consecutive_failures = 0
                self._handle_pull_response(body)
            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    # 订阅过期/失效 → 丢弃并重建
                    self._subscription_url = ""
                    consecutive_failures = 0
                self._stop_event.wait(2.0)

    def _handle_pull_response(self, body: str) -> None:
        """解析 PullMessagesResponse 中的 NotificationMessage 并逐条上报"""
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return

        for msg in root.iter():
            if not msg.tag.endswith("NotificationMessage"):
                continue

            raw_topic = ""
            prop_op = ""
            items: Dict[str, str] = {}
            for el in msg.iter():
                if el.tag.endswith("Topic") and (el.text or "").strip():
                    raw_topic = el.text.strip()
                elif el.tag.endswith("SimpleItem"):
                    name = el.get("Name", "")
                    if name:
                        items[name] = el.get("Value", "")
                if el.get("PropertyOperation"):
                    prop_op = el.get("PropertyOperation", "")

            # 订阅（重）建立时设备推送 Initialized 状态快照（非真实事件），必须忽略：
            # 否则 DigitalInput 等常开布尔项（LogicalState=true）每次订阅重建都会被误报
            init_snapshot = prop_op.strip().lower() == "initialized"

            # 布尔状态项：只上报"激活"沿（true/1），忽略清除沿；无布尔项则直接上报
            bool_values = [
                v.strip().lower() for k, v in items.items()
                if k.strip().lower() in _ONVIF_BOOL_ITEM_NAMES
            ]
            cleared = bool(bool_values) and not any(v in ("true", "1") for v in bool_values)
            skipped = init_snapshot or cleared
            topic = _normalize_onvif_topic(raw_topic)

            if skipped:
                continue

            self._emit(
                topic=topic,
                source="onvif",
                detail=items,
            )

    def _try_unsubscribe(self) -> None:
        """停止时尽力注销订阅（失败静默，订阅会自行超时）"""
        if not self._subscription_url or _requests_lib is None:
            return
        try:
            from .device_mgmt import _onvif_post_with_auth
            parsed = urlparse(self._subscription_url)
            _onvif_post_with_auth(
                parsed.hostname or self.ip,
                parsed.port or self.onvif_port,
                parsed.path or "/onvif/event_service",
                self._UNSUBSCRIBE_BODY,
                self.username, self.password, timeout=5.0,
            )
        except Exception:
            pass
        self._subscription_url = ""

    # ══════════════════════════════════════════
    #  通道 2: 创维私有协议（RTSP 通道报警上报）
    # ══════════════════════════════════════════

    def _private_rtsp_alarm_loop(self) -> None:
        """维持 RTSP 会话并监听 interleaved 通道 0x65 的报警 JSON 推送，断线自动重连（指数退避封顶 30s）。

        设备在同一 TCP 连接的 channel 0x65 上推送报警 JSON（~94 字节），
        User-Agent 须为 "skyworth"，SETUP interleaved=0-101。
        """
        backoff = 2.0
        while not self._stop_event.is_set():
            sock = None
            session_start = 0.0
            try:
                sock = self._open_rtsp_alarm_session()
                self._channels["private"] = True
                session_start = time.time()
                self._read_alarm_stream(sock)
            except Exception as e:
                pass
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

            if self._stop_event.is_set():
                return
            self._channels["private"] = False
            # 会话存活超过 30s 才视为"曾经健康"并重置退避；
            # 立即断开（如设备拒绝会话）时持续指数退避，避免 2s 重连轰炸设备
            if session_start and time.time() - session_start > 30.0:
                backoff = 2.0
            if self._stop_event.wait(backoff):
                return
            backoff = min(backoff * 2, 30.0)

    def _open_rtsp_alarm_session(self) -> socket.socket:
        """建立 RTSP 会话（TCP interleaved）供设备推送报警。

        对齐 alarm.py 已验证方案：
        - User-Agent 须为 "skyworth"（设备端检查，DESCRIBE 前即设好）
        - 解析 SDP 中所有 a=control: 轨道，逐一 SETUP（每轨道 interleaved=0-1,2-3...）
        - 设备识别 User-Agent 后在同一会话的私有通道 0x65 推送报警 JSON
        - 支持 Basic 与 Digest 鉴权；DESCRIBE/SETUP/PLAY 失败时降级
        """
        import base64
        import hashlib

        sock = socket.create_connection((self.ip, self.rtsp_port), timeout=5.0)
        sock.settimeout(1.0)

        base_url = f"rtsp://{self.ip}:{self.rtsp_port}{self.rtsp_path}"
        # 鉴权状态：首个请求不携带凭据，收到 401 挑战后再按设备要求的方案重试。
        # ZLMediaKit 固件实测：首请求若携带验证失败的 Authorization（如预发 Basic），
        # 回完 401 后会直接断开连接；且其 Digest nonce 绑定会话，必须
        # "先裸请求拿挑战、同一连接上重试"（ffmpeg/VLC 标准流程）
        digest_realm = ""
        digest_nonce = ""
        use_basic = False

        def build_auth(method: str, url: str) -> str:
            if not self.username:
                return ""
            if digest_nonce:
                ha1 = hashlib.md5(
                    f"{self.username}:{digest_realm}:{self.password}".encode()
                ).hexdigest()
                ha2 = hashlib.md5(f"{method}:{url}".encode()).hexdigest()
                resp = hashlib.md5(f"{ha1}:{digest_nonce}:{ha2}".encode()).hexdigest()
                return (
                    f'Authorization: Digest username="{self.username}", '
                    f'realm="{digest_realm}", nonce="{digest_nonce}", '
                    f'uri="{url}", response="{resp}"\r\n'
                )
            if use_basic:
                token = base64.b64encode(
                    f"{self.username}:{self.password}".encode()
                ).decode()
                return f"Authorization: Basic {token}\r\n"
            return ""

        cseq_counter = [0]

        def send_req(method: str, url: str, extra: str = "") -> str:
            cseq_counter[0] += 1
            req = (
                f"{method} {url} RTSP/1.0\r\n"
                f"CSeq: {cseq_counter[0]}\r\n"
                f"User-Agent: {SK_RTSP_USER_AGENT}\r\n"
                f"{build_auth(method, url)}{extra}\r\n"
            )
            sock.sendall(req.encode("utf-8"))
            resp = b""
            deadline = time.time() + 5.0
            while time.time() < deadline:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                resp += chunk
                if b"\r\n\r\n" in resp:
                    break
            return resp.decode("utf-8", errors="ignore")

        # DESCRIBE（首次不带凭据；收到 401 挑战后在同一连接上按挑战方案重试）
        describe = send_req("DESCRIBE", base_url, "Accept: application/sdp\r\n")
        retried = False
        if describe and "401" in describe.splitlines()[0] and self.username:
            rm = re.search(r'realm="([^"]+)"', describe)
            nm = re.search(r'nonce="([^"]+)"', describe)
            if "Digest" in describe and rm and nm:
                digest_realm, digest_nonce = rm.group(1), nm.group(1)
            else:
                use_basic = True
            retried = True
            describe = send_req("DESCRIBE", base_url, "Accept: application/sdp\r\n")
        describe_ok = bool(describe) and "200" in describe.splitlines()[0]
        if not describe_ok:
            self._rtsp_session_id = ""
            return sock

        # ── 解析 SDP 所有轨道（对齐 alarm.py _parse_sdp_tracks） ──
        track_urls: List[str] = []
        sdp_base_url = base_url
        current_control = ""
        for line in describe.split("\r\n"):
            if line.startswith("a=control:"):
                ctrl = line.split(":", 1)[1].strip()
                if ctrl and ctrl != "*":
                    current_control = ctrl
            if line.startswith("m=") and current_control:
                if current_control.lower().startswith("rtsp://"):
                    track_urls.append(current_control)
                else:
                    track_urls.append(
                        f"{sdp_base_url.rstrip('/')}/{current_control}"
                    )
                current_control = ""
        if not track_urls:
            # 回退：取第一个非 * 的 a=control:
            controls = [c.strip() for c in re.findall(r"a=control:(\S+)", describe)]
            control = next((c for c in controls if c != "*"), "")
            if control:
                if control.lower().startswith("rtsp://"):
                    track_urls.append(control)
                else:
                    track_urls.append(base_url.rstrip("/") + "/" + control.lstrip("/"))
            else:
                track_urls.append(base_url)

        # ── 多轨道 SETUP（每轨道 interleaved=0-1, 2-3, ...） ──
        session_id = ""
        interleaved_base = 0
        for track_url in track_urls:
            transport = (
                f"Transport: RTP/AVP/TCP;interleaved={interleaved_base}"
                f"-{interleaved_base + 1}\r\n"
            )
            setup = send_req("SETUP", track_url, transport)
            setup_status = setup.splitlines()[0] if setup else ""

            # 401 → 认证后重试一次
            if "401" in setup_status:
                rm = re.search(r'realm="([^"]+)"', setup)
                nm = re.search(r'nonce="([^"]+)"', setup)
                if "Digest" in setup and rm and nm:
                    digest_realm, digest_nonce = rm.group(1), nm.group(1)
                else:
                    use_basic = True
                setup = send_req("SETUP", track_url, transport)
                setup_status = setup.splitlines()[0] if setup else ""

            sm = re.search(r"Session:\s*([^;\r\n]+)", setup)
            if sm and "200" in setup_status:
                sid = sm.group(1).strip()
                if not session_id:
                    session_id = sid
                interleaved_base += 2  # 下一个轨道用下两个 interleaved 通道

        # ── PLAY（使用第一个轨道 URL，附带 Session + Range） ──
        if session_id:
            play_target = track_urls[0] if track_urls else base_url
            send_req(
                "PLAY", play_target,
                f"Session: {session_id}\r\nRange: npt=0.000-\r\n",
            )
            self._rtsp_session_id = session_id
        else:
            self._rtsp_session_id = ""

        return sock

    def _read_alarm_stream(self, sock: socket.socket) -> None:
        """持续读取 RTSP 连接数据，通过 _InterleavedFrameParser 解析帧，
        提取报警通道（0x65）的 JSON。

        视频/音频通道的帧静默跳过。OPTIONS keepalive 保活（25s 间隔）。
        """
        parser = _InterleavedFrameParser()
        last_keepalive = time.time()
        cseq = 10
        base_url = f"rtsp://{self.ip}:{self.rtsp_port}{self.rtsp_path}"

        while not self._stop_event.is_set():
            # OPTIONS 保活（25s 间隔）
            if time.time() - last_keepalive > 25.0:
                last_keepalive = time.time()
                cseq += 1
                session_hdr = ""
                if getattr(self, "_rtsp_session_id", ""):
                    session_hdr = f"Session: {self._rtsp_session_id}\r\n"
                try:
                    sock.sendall(
                        f"OPTIONS {base_url} RTSP/1.0\r\nCSeq: {cseq}\r\n"
                        f"User-Agent: {SK_RTSP_USER_AGENT}\r\n{session_hdr}\r\n".encode()
                    )
                except OSError:
                    return  # 连接失效，外层重连

            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                continue
            except OSError:
                return
            if not chunk:
                return  # 对端关闭

            # 用帧解析器解析（自动跳过 RTSP 文本响应和空白字节）
            for channel, payload in parser.feed(chunk):
                if channel == SK_ALARM_CHANNEL:
                    self._process_alarm_channel_payload(payload)
                # 其他通道（视频/音频）静默跳过

    @staticmethod
    def _extract_rtp_payload(rtp_data: bytes) -> str:
        """从 RTP 数据包中提取 Payload 并解码为 UTF-8 字符串。

        RTP 固定头 12 字节 + CC*4 CSRC + 可选 Extension + Payload。
        当报警通道 payload 不是纯 JSON 时调用（兼容 RTP 包裹的情况）。
        """
        if len(rtp_data) < 12:
            return ""
        cc = rtp_data[0] & 0x0F
        ext_flag = (rtp_data[0] >> 4) & 0x1
        offset = 12 + cc * 4
        if offset > len(rtp_data):
            return ""
        if ext_flag and offset + 4 <= len(rtp_data):
            ext_len = struct.unpack("!H", rtp_data[offset + 2: offset + 4])[0]
            offset += 4 + ext_len * 4
        if offset >= len(rtp_data):
            return ""
        return rtp_data[offset:].decode("utf-8", errors="replace").strip()

    def _process_alarm_channel_payload(self, payload: bytes) -> None:
        """从报警通道（0x65）payload 中提取 JSON 并处理报警事件。

        优先尝试直接解析 JSON（实测为纯 JSON ~94 字节）；
        失败时尝试剥离 RTP 头后再解析（兼容 RTP 包裹的情况）。
        兼容 serv/ser、date/dat 两套字段名。
        """
        text = payload.decode("utf-8", errors="ignore").strip()
        alarm_json = text

        # 优先直接解析 JSON
        try:
            obj = json.loads(alarm_json)
        except (json.JSONDecodeError, ValueError):
            # 直接解析失败 → 尝试剥离 RTP 头
            alarm_json = self._extract_rtp_payload(payload)
            if not alarm_json:
                return
            try:
                obj = json.loads(alarm_json)
            except (json.JSONDecodeError, ValueError):
                return

        if not isinstance(obj, dict):
            return

        # 兼容 serv/ser 两套字段名
        serv_val = obj.get("serv", obj.get("ser", ""))
        if serv_val == "alarm":
            self._handle_private_alarm(obj)

    def _handle_private_alarm(self, obj: Dict[str, Any]) -> None:
        """处理一条私有协议报警 JSON。

        兼容两套字段名: serv/ser、date/dat（alarm.py 实测两种固件都有）。
        """
        alm = str(obj.get("alm", ""))
        detail = {
            k: obj[k] for k in ("fn", "fmt", "num", "data", "dir") if k in obj
        }
        # 补充 date/dat 到 detail（方便下游追溯报警时间）
        date_val = obj.get("date", obj.get("dat", ""))
        if date_val:
            detail["date"] = date_val
        self._emit(
            topic=_normalize_private_topic(alm),
            source="private",
            detail=detail,
        )


# ──────────────────────────────────────────────
#  监听器注册表
# ──────────────────────────────────────────────

_monitors: Dict[str, _CameraEventMonitor] = {}
_monitors_lock = threading.Lock()

# 自动恢复重试冷却：camera → 上次恢复尝试失败时间（进程内，不落盘）
_resume_last_attempt: Dict[str, float] = {}
_resume_lock = threading.Lock()   # 防止 server 启动线程与 poll/wait 入口并发恢复同一相机


def _monitor_status_summary() -> Dict[str, Any]:
    with _monitors_lock:
        return {name: m.status() for name, m in _monitors.items()}


# ──────────────────────────────────────────────
#  监听意图持久化（跨进程存活，修复 MCP 进程被宿主回收后监听丢失）
# ──────────────────────────────────────────────

def _load_monitor_state() -> Dict[str, Dict[str, Any]]:
    """加载已落盘的监听意图 {camera: {protocols, debounce_seconds, enabled_at}}"""
    if not MONITOR_STATE_PATH.exists():
        return {}
    try:
        with open(MONITOR_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): v for k, v in data.items() if isinstance(v, dict)} \
            if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_monitor_state(state: Dict[str, Dict[str, Any]]) -> None:
    _ensure_events_dir()
    with open(MONITOR_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _record_monitor_intent(camera_name: str, protocols: str, debounce_seconds: float) -> None:
    """start 成功后记录监听意图（用户授权的持久化凭证，直到显式 stop）"""
    state = _load_monitor_state()
    state[camera_name] = {
        "protocols": protocols,
        "debounce_seconds": debounce_seconds,
        "enabled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _save_monitor_state(state)


def _clear_monitor_intent(camera_name: str) -> None:
    """stop 时清除监听意图，后续进程重启不再自动恢复"""
    state = _load_monitor_state()
    if camera_name in state:
        state.pop(camera_name)
        _save_monitor_state(state)
    _resume_last_attempt.pop(camera_name, None)


def resume_persisted_monitors() -> Dict[str, str]:
    """按已落盘的监听意图重新拉起不在运行的监听器（进程重启后的自动恢复）。

    调用时机：MCP server 启动时 + poll/wait 入口。不新增用户授权面：
    意图只在用户显式 start 时写入、stop 时清除，这里仅恢复用户尚未撤销的授权。
    失败的相机进入 _RESUME_RETRY_SECONDS 冷却，避免离线设备被每次 poll 阻塞式探测。

    Returns:
        {camera: "resumed" | "already_running" | "cooldown" | "failed: <原因>"}
    """
    # 非阻塞互斥：已有恢复在进行（如 server 启动线程）时直接跳过，
    # 避免同一相机被并发拉起两份监听，也避免 poll/wait 被启动恢复阻塞
    if not _resume_lock.acquire(blocking=False):
        return {}
    try:
        outcome: Dict[str, str] = {}
        for camera_name, spec in _load_monitor_state().items():
            with _monitors_lock:
                existing = _monitors.get(camera_name)
                if existing and existing.running:
                    outcome[camera_name] = "already_running"
                    continue

            now = time.time()
            if now - _resume_last_attempt.get(camera_name, 0.0) < _RESUME_RETRY_SECONDS:
                outcome[camera_name] = "cooldown"
                continue

            # 启动前复读意图：恢复过程中用户可能已 stop（意图被清除）
            if camera_name not in _load_monitor_state():
                outcome[camera_name] = "cancelled"
                continue

            result = start_event_monitor(
                camera_name,
                protocols=str(spec.get("protocols", "both")),
                debounce_seconds=float(spec.get("debounce_seconds", DEFAULT_DEBOUNCE_SECONDS)),
                _resuming=True,
            )
            if result.success:
                _resume_last_attempt.pop(camera_name, None)
                outcome[camera_name] = "resumed"
            else:
                _resume_last_attempt[camera_name] = now
                outcome[camera_name] = f"failed: {result.error_message}"
        return outcome
    finally:
        _resume_lock.release()


# ──────────────────────────────────────────────
#  工具函数（MCP 工具入口）
# ──────────────────────────────────────────────

def start_event_monitor(
    camera_name: str,
    protocols: str = "both",
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    _resuming: bool = False,
) -> EventMonitorResult:
    """
    启动指定摄像头的事件监听（后台线程，用户显式开启）。

    双协议同时监听：ONVIF PullPoint 订阅 + 创维私有协议 RTSP 通道报警，
    两侧事件按 (camera, 归一化 topic) 在去重窗口内合并，避免跨协议重复。
    事件到达时同进程联动快照（窗口内同机只截一张），经消息处理层加工成
    schema 1.0 格式后落盘到 events/camera_events.txt（单一真相源，跨 session 可读）。

    启动成功后监听意图落盘到 events/monitor_state.json：MCP 进程被宿主回收后，
    server 重启 / poll / wait 会据此自动恢复监听，直到用户显式 stop。

    安全约束: 显式提示 — 后台线程仅在用户确认后启动；行为限于报警订阅 +
              snapshots/ 与 events/ 白名单路径写入

    Args:
        camera_name:      摄像头名称（须已注册于 config.yaml 或已连接）
        protocols:        监听协议: "both"(默认) / "onvif" / "private"
        debounce_seconds: 去重与快照限流窗口（秒，默认 5.0）
        _resuming:        内部参数：resume_persisted_monitors 自动恢复时为 True，
                          不重复写入监听意图

    Returns:
        EventMonitorResult:
            - success: 是否至少启动了一个协议通道
            - active_channels: 已激活的通道列表 ["onvif", "private"]
            - error_message: 全部通道启动失败时的原因
    """
    if protocols not in ("both", "onvif", "private", "auto"):
        return EventMonitorResult(
            success=False, camera_name=camera_name,
            error_message=f"无效的 protocols 参数: {protocols}（可选 both/onvif/private）",
        )

    with _monitors_lock:
        existing = _monitors.get(camera_name)
        if existing and existing.running:
            return EventMonitorResult(
                success=True, camera_name=camera_name, running=True,
                active_channels=[k for k, v in existing._channels.items() if v],
                error_message="监听已在运行，无需重复启动",
            )

    # 取连接信息：优先内存连接态，其次 config.yaml
    from .device_mgmt import _connected_devices, _find_cached_camera, _probe_onvif_port
    conn = _connected_devices.get(camera_name)
    if conn:
        ip = conn.get("ip", "")
        onvif_port = int(conn.get("port", 0) or 0)
        rtsp_port = int(conn.get("rtsp_port", 554) or 554)
        rtsp_path = conn.get("rtsp_sub_path", "") or conn.get("rtsp_path", "/stream2")
        username = conn.get("username", "admin")
        password = conn.get("password", "")
    else:
        cached = _find_cached_camera(camera_name)
        if not cached or not cached.ip:
            return EventMonitorResult(
                success=False, camera_name=camera_name,
                error_message=f"设备 {camera_name} 未连接且 config.yaml 中无配置，"
                              f"请先调用 connect_device()",
            )
        ip = cached.ip
        onvif_port = cached.port
        rtsp_port = cached.rtsp_port
        rtsp_path = cached.rtsp_sub_path or cached.rtsp_path
        username = cached.username
        password = cached.password

    # ONVIF 端口未知时探测（创维实测 2000）
    if not onvif_port and protocols in ("both", "onvif", "auto"):
        onvif_port = _probe_onvif_port(ip)

    monitor = _CameraEventMonitor(
        camera_name=camera_name,
        ip=ip,
        onvif_port=onvif_port,
        rtsp_port=rtsp_port,
        rtsp_path=rtsp_path,
        username=username,
        password=password,
        debounce_seconds=debounce_seconds,
    )
    active = monitor.start(protocols)

    if not active:
        return EventMonitorResult(
            success=False, camera_name=camera_name,
            error_message=f"所有协议通道启动失败（ONVIF 端口 {onvif_port or '未知'} 订阅失败，"
                          f"RTSP 端口 {rtsp_port} 不可达）",
        )

    with _monitors_lock:
        _monitors[camera_name] = monitor

    # 监听意图落盘：进程被回收后可自动恢复（自动恢复路径不重复写入）
    if not _resuming:
        _record_monitor_intent(camera_name, protocols, debounce_seconds)

    return EventMonitorResult(
        success=True, camera_name=camera_name,
        running=True, active_channels=active,
    )


def stop_event_monitor(
    camera_name: str,
) -> EventMonitorResult:
    """
    停止指定摄像头的事件监听，注销 ONVIF 订阅并关闭 RTSP 报警会话；
    同时清除已落盘的监听意图，后续进程重启不再自动恢复。

    安全约束: 无特殊约束

    Args:
        camera_name: 摄像头名称

    Returns:
        EventMonitorResult:
            - success: 停止是否成功
            - running: 停止后恒为 False
    """
    _clear_monitor_intent(camera_name)

    with _monitors_lock:
        monitor = _monitors.pop(camera_name, None)

    if monitor is None:
        return EventMonitorResult(
            success=True, camera_name=camera_name, running=False,
            error_message="该摄像头没有正在运行的事件监听",
        )

    monitor.stop()
    return EventMonitorResult(success=True, camera_name=camera_name, running=False)


def get_pending_events(
    camera_name: Optional[str] = None,
    limit: int = 100,
) -> PendingEventsResult:
    """
    读取未消费事件并推进消费游标（读磁盘存储，跨 session 可用）。

    游标按相机独立持久化于 events/events_cursor.json：
    指定 camera_name 时只消费该相机的事件，不影响其他相机的游标；
    不指定时消费所有相机的未读事件。

    安全约束: 无特殊约束（只读存储 + 写游标文件）

    Args:
        camera_name: 摄像头名称（可选，默认全部）
        limit:       单次最多返回的事件数（默认 100）

    Returns:
        PendingEventsResult:
            - events: 本次消费的事件列表（含 snapshot_path）
            - remaining: 存储中尚未消费的事件数（因 limit 截断时 > 0）
            - monitors: 各监听器运行状态
    """
    # 入口自动恢复：MCP 进程被宿主回收后，据落盘意图重新拉起监听
    try:
        resume_persisted_monitors()
    except Exception:
        pass  # 恢复失败不阻断读取已落盘事件

    try:
        pending, remaining = _collect_pending(camera_name, max(1, int(limit)), advance=True)
    except Exception as e:
        return PendingEventsResult(success=False, error_message=f"读取事件存储失败: {e}")

    return PendingEventsResult(
        success=True,
        events=[_dict_to_camera_event(d) for d in pending],
        remaining=remaining,
        monitors=_monitor_status_summary(),
    )


def wait_for_events(
    camera_name: Optional[str] = None,
    timeout_seconds: float = 60.0,
) -> PendingEventsResult:
    """
    长轮询阻塞等待新事件：有事件立即返回（并消费），超时返回空列表。

    阻塞上限 60s（对齐 MCP 客户端 stdio 工具超时）——需要更长守护时
    由 Agent 循环调用本工具，而不是单次长阻塞。

    安全约束: 无特殊约束

    Args:
        camera_name:     摄像头名称（可选，默认任意相机的事件都触发返回）
        timeout_seconds: 阻塞超时（秒，默认 60，上限 60）

    Returns:
        PendingEventsResult:
            - events: 等到的事件列表（超时为空且 success=True）
            - remaining: 剩余未消费事件数
            - monitors: 各监听器运行状态
    """
    # 入口自动恢复：长循环守护中进程被回收后，下一轮 wait 即可拉回监听
    try:
        resume_persisted_monitors()
    except Exception:
        pass

    timeout = min(max(1.0, float(timeout_seconds)), WAIT_TIMEOUT_CAP)
    deadline = time.time() + timeout

    while True:
        try:
            pending, remaining = _collect_pending(camera_name, limit=100, advance=True)
        except Exception as e:
            return PendingEventsResult(success=False, error_message=f"读取事件存储失败: {e}")

        if pending:
            return PendingEventsResult(
                success=True,
                events=[_dict_to_camera_event(d) for d in pending],
                remaining=remaining,
                monitors=_monitor_status_summary(),
            )

        wait_left = deadline - time.time()
        if wait_left <= 0:
            return PendingEventsResult(
                success=True, events=[], remaining=0,
                monitors=_monitor_status_summary(),
            )

        # 以 2s 切片等待：既响应本进程 notify，也能发现其他进程写入的存储
        with _event_arrived:
            _event_arrived.wait(timeout=min(2.0, wait_left))


def manage_camera_events(
    action: "EventAction",
    camera_name: Optional[str] = None,
    protocols: str = "both",
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    limit: int = 100,
    timeout_seconds: float = 60.0,
):
    """
    统一事件入口（唯一注册的 MCP 工具），通过 action 切换工作模式：

      - START: 启动监听（需 camera_name；参数 protocols / debounce_seconds）
      - STOP:  停止监听（需 camera_name）
      - POLL:  读取未消费事件并推进游标（camera_name 可选；参数 limit）
      - WAIT:  长轮询阻塞等待新事件（camera_name 可选；参数 timeout_seconds）

    安全约束: START 模式启动后台监听线程，须用户确认后调用；其余模式无特殊约束

    Returns:
        START/STOP → EventMonitorResult；POLL/WAIT → PendingEventsResult
    """
    if action in (EventAction.START, EventAction.STOP):
        if not camera_name:
            return EventMonitorResult(
                success=False,
                error_message=f"action={action.value} 需要 camera_name 参数",
            )
        if action == EventAction.START:
            return start_event_monitor(camera_name, protocols, debounce_seconds)
        return stop_event_monitor(camera_name)

    if action == EventAction.POLL:
        return get_pending_events(camera_name, limit)

    if action == EventAction.WAIT:
        return wait_for_events(camera_name, timeout_seconds)

    return PendingEventsResult(
        success=False,
        error_message=f"未知的 action: {action}（可选 start/stop/poll/wait）",
    )
