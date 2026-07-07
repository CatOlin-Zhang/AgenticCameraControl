"""
精准验证脚本 - 用 OpenCV 实际拉流来确认可用的摄像头
"""
import socket
import time
import cv2
import numpy as np
from typing import Optional, Tuple

# ── 候选 IP ──
CANDIDATES = [
    "172.28.234.22",
    "172.28.234.39",
    "172.28.234.103",
    # 也测试一下只有 RTSP 的设备
    "172.28.234.151",
    "172.28.234.61",
    "172.28.234.99",
]

USERNAME = "admin"
PASSWORD = "1c3589"

# 常见 RTSP 路径
RTSP_PATHS = [
    "/stream1",
    "/stream0",
    "/11",
    "/12",
    "/live/ch0",
    "/live/ch1",
    "/cam/realmonitor?channel=1&subtype=0",
    "/h264/ch1/main/",
    "/onvif1",
    "/Profile1",
]


def get_rtsp_raw_response(ip: str, port: int, path: str, username: str, password: str, timeout: float = 3.0) -> str:
    """
    发送原始 RTSP DESCRIBE 请求，返回完整的状态行。
    用于区分 200 OK / 401 Unauthorized / 404 Not Found 等。
    """
    url = f"rtsp://{username}:{password}@{ip}:{port}{path}"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))

        request = (
            f"DESCRIBE {url} RTSP/1.0\r\n"
            f"CSeq: 1\r\n"
            f"Accept: application/sdp\r\n"
            f"Authorization: Basic\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode())

        response = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if len(response) > 200:
                    break
        except socket.timeout:
            pass

        sock.close()
        resp_str = response.decode("utf-8", errors="ignore")

        # 提取状态行 (RTSP/1.0 xxx ...)
        first_line = resp_str.split("\r\n")[0] if resp_str else "(无响应)"
        return first_line

    except Exception as e:
        return f"(连接失败: {e})"


def test_opencv_capture(rtsp_url: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """
    用 OpenCV 实际拉一帧画面，验证 RTSP 流是否真正可用。
    :return: (是否成功, 描述信息)
    """
    try:
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            return False, "VideoCapture 无法打开"

        # 设置超时：尝试读取 3 秒
        start = time.time()
        frame = None
        while time.time() - start < timeout:
            ret, f = cap.read()
            if ret:
                frame = f
                break
            time.sleep(0.1)

        if frame is not None:
            h, w = frame.shape[:2]
            info = f"{w}x{h}, 成功读取画面"
            cap.release()
            return True, info
        else:
            cap.release()
            return False, "连接成功但无法读取画面"

    except Exception as e:
        return False, str(e)


def test_http_raw(ip: str, port: int, timeout: float = 3.0) -> str:
    """获取 HTTP 原始响应头和部分内容"""
    try:
        import http.client
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
        conn.request("GET", "/")
        resp = conn.getresponse()
        headers = dict(resp.getheaders())
        body = resp.read(4096).decode("utf-8", errors="ignore")
        conn.close()

        server = headers.get("Server", headers.get("server", ""))

        # 提取 title
        import re
        title_match = re.search(r'<title[^>]*>(.*?)</title>', body, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip()[:80] if title_match else ""

        parts = []
        if server:
            parts.append(f"Server: {server}")
        if title:
            parts.append(f"Title: {title}")

        # 查看前 200 字符
        body_preview = body[:200].replace("\n", " ").replace("\r", "").strip()
        if body_preview and not title:
            parts.append(f"Content: {body_preview[:100]}")

        return " | ".join(parts) if parts else "(空响应)"

    except Exception as e:
        return f"(HTTP 错误: {e})"


def main():
    print("\n" + "=" * 65)
    print("  创际 M50 精准识别 (OpenCV 拉流 + 原始 RTSP 响应)")
    print("=" * 65)

    for ip in CANDIDATES:
        print(f"\n{'━' * 65}")
        print(f"  {ip}")
        print(f"{'━' * 65}")

        # 1. HTTP 详情
        http_info = test_http_raw(ip, 80) if socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect_ex((ip, 80)) == 0 else ""
        if not http_info:
            # 试 8080
            http_info = test_http_raw(ip, 8080) if socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect_ex((ip, 8080)) == 0 else "(无 HTTP)"
        print(f"  HTTP: {http_info}")

        # 2. RTSP 原始响应（只看 /stream1）
        rtsp_status = get_rtsp_raw_response(ip, 554, "/stream1", USERNAME, PASSWORD)
        print(f"  RTSP /stream1 原始响应: {rtsp_status}")

        # 3. OpenCV 拉流测试（尝试多个路径）
        print(f"  OpenCV 拉流测试:")
        found = False
        for path in RTSP_PATHS:
            url = f"rtsp://{USERNAME}:{PASSWORD}@{ip}:554{path}"
            ok, info = test_opencv_capture(url, timeout=4.0)
            if ok:
                print(f"    ✓ {path} → {info}")
                found = True
                break
            # 只打印有意义的错误，不刷屏
        if not found:
            # 再试不带认证的
            for path in RTSP_PATHS[:3]:
                url = f"rtsp://{ip}:554{path}"
                ok, info = test_opencv_capture(url, timeout=4.0)
                if ok:
                    print(f"    ✓ {path} (无认证) → {info}")
                    found = True
                    break
            if not found:
                print(f"    ✗ 所有路径均无法拉流")

    print(f"\n{'=' * 65}")
    print("  测试完成！标记 ✓ 的就是可拉流的摄像头。")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
