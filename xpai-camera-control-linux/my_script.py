"""
my_script.py — 调用编译后的 toolkit 函数示例

用法：
  1. 把此文件放到 xpai-camera-control/ 目录下（和 config.yaml 同级）
  2. 执行：
     /tmp/mcp-camera-build-venv/bin/python3 my_script.py
"""

from scripts.toolkit import (
    get_registered_cameras,
    capture_video_screenshot,
    control_ptz,
    toggle_recording,
)

# ── 1. 查看已注册摄像头 ──
cameras = get_registered_cameras()
print(f"共 {len(cameras)} 个摄像头：")
for cam in cameras:
    print(f"  {cam.name} @ {cam.ip}:{cam.port}")

if not cameras:
    print("请先在 config.yaml 中配置摄像头")
    exit()

name = cameras[0].name  # 取第一个摄像头

# ── 2. 截图 ──
result = capture_video_screenshot(name)
print(f"\n截图完成: {result.filepath}")

# ── 3. 云台控制（方向移动 1 秒）──
# result = control_ptz(name, direction="up", duration=1)
# print(f"\n云台: {result.status}")

# ── 4. 录像 ──
# toggle_recording(name, action="start")
# import time; time.sleep(5)
# toggle_recording(name, action="stop")
# print("\n录像完成")
