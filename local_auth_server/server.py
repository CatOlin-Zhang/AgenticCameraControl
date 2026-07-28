"""
本地授权服务器 — 模拟智慧云端授权流程

启动后自动打开浏览器，用户在网页上点击「授权」或「拒绝」，
Skill 通过轮询 /api/auth/status 接口获取授权结果。

用法:
    python local_auth_server/server.py              # 默认端口 18899
    python local_auth_server/server.py --port 9090  # 自定义端口

API:
    POST /api/auth/request   — Skill 提交授权请求 {sn, claw_id, device_ip, device_model}
    GET  /api/auth/status    — Skill 轮询授权状态 ?sn=xxx&claw_id=yyy
    POST /api/auth/action    — 用户在网页提交操作 {sn, claw_id, action}
    GET  /                   — 授权管理网页
"""

import argparse
import json
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ──────────────────────────────────────────────
#  内存状态管理
# ──────────────────────────────────────────────

_auth_requests: dict = {}  # key: (sn, claw_id) -> {status, device_ip, device_model, created_at, message}
_lock = threading.Lock()


def _add_request(sn: str, claw_id: str, device_ip: str = "", device_model: str = "") -> None:
    with _lock:
        _auth_requests[(sn, claw_id)] = {
            "status": "pending",
            "device_ip": device_ip,
            "device_model": device_model,
            "created_at": time.time(),
            "message": "等待用户确认",
        }


def _get_status(sn: str, claw_id: str) -> dict:
    with _lock:
        entry = _auth_requests.get((sn, claw_id))
        if entry is None:
            return {"status": "error", "message": f"未找到授权请求: sn={sn}"}
        return {"status": entry["status"], "message": entry["message"]}


def _set_action(sn: str, claw_id: str, action: str) -> dict:
    with _lock:
        entry = _auth_requests.get((sn, claw_id))
        if entry is None:
            return {"success": False, "message": f"未找到授权请求: sn={sn}"}
        if action == "authorize":
            entry["status"] = "authorized"
            entry["message"] = "用户已授权"
        elif action == "reject":
            entry["status"] = "rejected"
            entry["message"] = "用户拒绝授权"
        else:
            return {"success": False, "message": f"未知操作: {action}"}
        return {"success": True, "message": entry["message"]}


def _get_all_pending() -> list:
    with _lock:
        result = []
        for (sn, claw_id), entry in _auth_requests.items():
            result.append({
                "sn": sn,
                "claw_id": claw_id,
                "status": entry["status"],
                "device_ip": entry["device_ip"],
                "device_model": entry["device_model"],
                "message": entry["message"],
            })
        return result


# ──────────────────────────────────────────────
#  Web UI HTML
# ──────────────────────────────────────────────

_HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>摄像头授权管理</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f5f5; padding: 20px; }
  h1 { text-align: center; margin-bottom: 24px; color: #333; }
  .card { background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.1); padding: 20px; margin-bottom: 16px; max-width: 600px; margin-left: auto; margin-right: auto; }
  .card h3 { margin-bottom: 8px; color: #1a73e8; }
  .card p { color: #666; margin-bottom: 4px; font-size: 14px; }
  .card .status { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; color: #fff; margin-bottom: 12px; }
  .status.pending { background: #f9a825; }
  .status.authorized { background: #43a047; }
  .status.rejected { background: #e53935; }
  .btn-group { display: flex; gap: 10px; margin-top: 12px; }
  .btn { flex: 1; padding: 10px; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; color: #fff; font-weight: 600; }
  .btn-authorize { background: #43a047; }
  .btn-authorize:hover { background: #2e7d32; }
  .btn-reject { background: #e53935; }
  .btn-reject:hover { background: #c62828; }
  .empty { text-align: center; color: #999; padding: 40px; }
  .toast { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); background: #333; color: #fff; padding: 10px 24px; border-radius: 8px; display: none; z-index: 999; }
</style>
</head>
<body>
<h1>摄像头授权管理</h1>
<div id="container"><div class="empty">加载中...</div></div>
<div id="toast" class="toast"></div>

<script>
async function refresh() {
  const res = await fetch("/api/auth/list");
  const list = await res.json();
  const c = document.getElementById("container");
  if (!list.length) { c.innerHTML = '<div class="empty">暂无授权请求</div>'; return; }
  c.innerHTML = list.map(r => `
    <div class="card">
      <span class="status ${r.status}">${r.status === 'pending' ? '待确认' : r.status === 'authorized' ? '已授权' : '已拒绝'}</span>
      <h3>设备: ${r.device_model || r.sn}</h3>
      <p>SN: ${r.sn}</p>
      <p>IP: ${r.device_ip || '未知'}</p>
      <p>Claw ID: ${r.claw_id}</p>
      <p>${r.message}</p>
      ${r.status === 'pending' ? `
        <div class="btn-group">
          <button class="btn btn-authorize" onclick="act('${r.sn}','${r.claw_id}','authorize')">授权</button>
          <button class="btn btn-reject" onclick="act('${r.sn}','${r.claw_id}','reject')">拒绝</button>
        </div>` : ''}
    </div>
  `).join("");
}

async function act(sn, clawId, action) {
  const res = await fetch("/api/auth/action", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({sn, claw_id: clawId, action})
  });
  const data = await res.json();
  showToast(data.message || (data.success ? "操作成功" : "操作失败"));
  refresh();
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.display = "block";
  setTimeout(() => t.style.display = "none", 2000);
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
#  HTTP Handler
# ──────────────────────────────────────────────

class AuthHandler(BaseHTTPRequestHandler):
    """处理 API 和 Web UI 请求"""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self._send_html(200, _HTML_PAGE)
            return

        if parsed.path == "/api/auth/status":
            qs = parse_qs(parsed.query)
            sn = qs.get("sn", [""])[0]
            claw_id = qs.get("claw_id", [""])[0]
            result = _get_status(sn, claw_id)
            self._send_json(200, result)
            return

        if parsed.path == "/api/auth/list":
            self._send_json(200, _get_all_pending())
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._read_body()

        if parsed.path == "/api/auth/request":
            sn = body.get("sn", "")
            claw_id = body.get("claw_id", "")
            device_ip = body.get("device_ip", "")
            device_model = body.get("device_model", "")
            if not sn:
                self._send_json(400, {"success": False, "message": "缺少 sn 参数"})
                return
            _add_request(sn, claw_id, device_ip, device_model)
            self._send_json(200, {"success": True, "message": "授权请求已提交"})
            return

        if parsed.path == "/api/auth/action":
            sn = body.get("sn", "")
            claw_id = body.get("claw_id", "")
            action = body.get("action", "")
            result = _set_action(sn, claw_id, action)
            self._send_json(200, result)
            return

        self._send_json(404, {"error": "Not Found"})

    def _read_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code: int, html: str):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """静默日志（仅打印 API 请求）"""
        if "/api/" in str(args[0]) if args else False:
            print(f"[AuthServer] {self.address_string()} - {format % args}")


# ──────────────────────────────────────────────
#  入口
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="本地摄像头授权服务器")
    parser.add_argument("--port", type=int, default=18899, help="监听端口 (默认 18899)")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), AuthHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"[AuthServer] 本地授权服务器已启动: {url}")
    print(f"[AuthServer] 请在浏览器中打开上述地址进行授权管理")
    print(f"[AuthServer] 按 Ctrl+C 停止服务器")

    # 自动打开浏览器
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AuthServer] 服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
