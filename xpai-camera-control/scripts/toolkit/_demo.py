"""
XPAI Camera Control — Demo Mode Implementations

All 27 toolkit functions, patched via enable_demo_mode().
Provides realistic mock data and generates a real JPEG image for snapshots.
"""
import os
import struct
import time
from typing import Dict, List, Optional, Any

# ── Demo Devices Database ──
_DEMO_DEVICES: List[Dict[str, Any]] = [
    {
        "name": "客厅摄像头",
        "ip": "192.168.1.100",
        "onvif_port": 80,
        "rtsp_port": 554,
        "device_class": "password_required",
        "sn_code": "SKY-A22-20240115001",
        "model": "Skyworth IPC-A22",
        "manufacturer": "Skyworth",
        "rtsp_path": "/stream1",
        "firmware": "v2.4.1",
        "mac": "AA:BB:CC:11:22:33",
        "supported_media": ["H.264", "H.265", "MJPEG"],
    },
    {
        "name": "门口摄像头",
        "ip": "192.168.1.101",
        "onvif_port": 80,
        "rtsp_port": 554,
        "device_class": "password_required",
        "sn_code": "SKY-D10-20240320002",
        "model": "Skyworth IPC-D10",
        "manufacturer": "Skyworth",
        "rtsp_path": "/stream1",
        "firmware": "v2.4.0",
        "mac": "AA:BB:CC:44:55:66",
        "supported_media": ["H.264", "H.265"],
    },
    {
        "name": "书房摄像头",
        "ip": "192.168.1.102",
        "onvif_port": 80,
        "rtsp_port": 554,
        "device_class": "direct_connect",
        "sn_code": "SKY-S30-20240510003",
        "model": "Skyworth IPC-S30",
        "manufacturer": "Skyworth",
        "rtsp_path": "/stream1",
        "firmware": "v2.3.8",
        "mac": "AA:BB:CC:77:88:99",
        "supported_media": ["H.264", "MJPEG"],
    },
]


def _get_device(camera_name: str) -> Optional[Dict[str, Any]]:
    """Look up a demo device by name."""
    for d in _DEMO_DEVICES:
        if d["name"] == camera_name:
            return d
    return None


# ── Demo State ──

_demo_ptz_state: Dict[str, float] = {"pan": 0.0, "tilt": 0.0, "zoom": 1.0}
_demo_presets: Dict[str, Dict[str, float]] = {}
_demo_recording_state: Dict[str, Any] = {
    "is_recording": False,
    "start_time": 0.0,
    "file_path": "",
}
_demo_tracking_state: Dict[str, Any] = {}
_demo_connected_devices: Dict[str, bool] = {}

# Picture settings per camera
_demo_picture_settings: Dict[str, Dict[str, int]] = {}
# Night vision per camera
_demo_night_vision: Dict[str, str] = {}
# Floodlight per camera
_demo_floodlight_mode: Dict[str, str] = {}
_demo_floodlight_type: Dict[str, str] = {}
# Microphone per camera
_demo_microphone: Dict[str, Dict[str, Any]] = {}
# Speaker per camera
_demo_speaker: Dict[str, Dict[str, Any]] = {}
# Encoding per camera
_demo_encoding: Dict[str, Dict[str, Any]] = {}
# OSD per camera
_demo_osd: Dict[str, Dict[str, Any]] = {}
# Alarm per camera
_demo_alarm: Dict[str, Dict[str, Any]] = {}
# Alarm push per camera
_demo_alarm_push: Dict[str, Dict[str, Any]] = {}


def _get_font(draw, size=18):
    """Get a Chinese-capable font."""
    from PIL import ImageFont
    try:
        return ImageFont.truetype("msyh.ttc", size)
    except Exception:
        try:
            return ImageFont.truetype("simhei.ttf", size)
        except Exception:
            try:
                return ImageFont.truetype("NotoSansCJK-Regular.ttc", size)
            except Exception:
                return ImageFont.load_default()


def _osd_overlay(draw, camera_name, width, height):
    """Add OSD overlay with camera name and timestamp."""
    from datetime import datetime
    font = _get_font(draw, 18)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{camera_name}  |  {ts}"
    draw.text((10, 5), text, fill=(255, 255, 255),
              font=font, stroke_width=1, stroke_fill=(0, 0, 0))


def _draw_living_room(draw, width, height):
    """Draw a living room scene."""
    # Ceiling
    draw.rectangle([(0, 0), (width, 100)], fill=(230, 225, 215))
    # Back wall
    draw.rectangle([(0, 100), (width, height - 150)], fill=(240, 235, 225))
    # Floor
    draw.rectangle([(0, height - 150), (width, height)], fill=(180, 160, 130))

    # Window (left)
    draw.rectangle([(80, 160), (380, 460)], fill=(160, 210, 240), outline=(100, 100, 100), width=4)
    draw.line([(230, 160), (230, 460)], fill=(100, 100, 100), width=3)
    draw.line([(80, 310), (380, 310)], fill=(100, 100, 100), width=3)
    # Curtains
    draw.rectangle([(60, 140), (85, 480)], fill=(200, 180, 160))
    draw.rectangle([(375, 140), (400, 480)], fill=(200, 180, 160))

    # Sofa (bottom-center)
    draw.rectangle([(200, 420), (600, 520)], fill=(120, 100, 80), outline=(80, 60, 40), width=2)
    draw.rectangle([(200, 420), (600, 450)], fill=(140, 120, 100), outline=(80, 60, 40), width=2)
    draw.rectangle([(180, 400), (210, 530)], fill=(110, 90, 70), outline=(80, 60, 40), width=2)
    draw.rectangle([(590, 400), (620, 530)], fill=(110, 90, 70), outline=(80, 60, 40), width=2)
    draw.ellipse([(300, 445), (370, 495)], fill=(180, 60, 40))
    draw.ellipse([(430, 445), (500, 495)], fill=(60, 100, 180))

    # Coffee table
    draw.rectangle([(280, 530), (520, 560)], fill=(160, 120, 60), outline=(100, 70, 30), width=2)
    draw.rectangle([(290, 515), (300, 530)], fill=(140, 100, 50))
    draw.rectangle([(500, 515), (510, 530)], fill=(140, 100, 50))
    draw.rectangle([(340, 510), (370, 530)], fill=(200, 200, 200), outline=(150, 150, 150))
    draw.ellipse([(410, 515), (440, 530)], fill=(80, 160, 60))
    draw.ellipse([(415, 505), (435, 520)], fill=(40, 140, 30))

    # TV on wall
    draw.rectangle([(500, 160), (780, 380)], fill=(40, 40, 40), outline=(60, 60, 60), width=6)
    draw.rectangle([(520, 175), (760, 365)], fill=(30, 50, 80))
    draw.ellipse([(760, 350), (772, 362)], fill=(0, 200, 0))

    # Lamp
    draw.rectangle([(660, 300), (670, 500)], fill=(140, 100, 50))
    draw.polygon([(630, 300), (700, 300), (690, 240), (640, 240)], fill=(220, 200, 160), outline=(180, 160, 120))

    # Bookshelf (far right)
    draw.rectangle([(830, 140), (width - 20, 500)], fill=(140, 100, 60), outline=(100, 70, 30), width=3)
    for row_y in range(160, 480, 50):
        draw.line([(835, row_y), (width - 25, row_y)], fill=(100, 70, 30), width=2)
    colors = [(200, 50, 40), (50, 80, 180), (200, 160, 30), (80, 150, 60), (150, 40, 130)]
    for row, row_y in enumerate(range(160, 480, 50)):
        for col, cx in enumerate(range(840, width - 30, 22)):
            if col < 5:
                draw.rectangle([(cx, row_y + 3), (cx + 18, row_y + 42)],
                               fill=colors[(row + col) % len(colors)], outline=(60, 60, 60))

    # Plant
    draw.rectangle([(60, 460), (100, 520)], fill=(160, 120, 40))
    draw.ellipse([(40, 380), (120, 470)], fill=(40, 140, 30))
    draw.ellipse([(30, 400), (90, 450)], fill=(30, 160, 40))
    draw.ellipse([(70, 370), (140, 440)], fill=(50, 130, 35))

    # Picture frame
    draw.rectangle([(150, 180), (250, 280)], fill=(180, 200, 120), outline=(100, 70, 30), width=4)
    draw.rectangle([(158, 220), (242, 272)], fill=(140, 200, 240))
    draw.polygon([(160, 260), (190, 230), (220, 250), (240, 260)], fill=(80, 160, 40))


def _draw_entrance(draw, width, height):
    """Draw an entrance/doorway scene."""
    # Sky
    draw.rectangle([(0, 0), (width, int(height * 0.45))], fill=(180, 210, 230))
    # Ground / floor mat area
    draw.rectangle([(0, int(height * 0.45)), (width, height)], fill=(200, 180, 160))
    # Floor tiles
    for tx in range(0, width, 80):
        for ty in range(int(height * 0.45), height, 80):
            draw.rectangle([(tx, ty), (tx + 80, ty + 80)], outline=(180, 160, 140), width=1)

    # Door frame
    door_left, door_right = 250, 550
    door_top, door_bottom = int(height * 0.08), int(height * 0.78)
    draw.rectangle([(door_left - 20, door_top - 20), (door_right + 20, door_bottom + 10)],
                   fill=(160, 120, 80), outline=(100, 70, 30), width=3)
    # Door
    draw.rectangle([(door_left, door_top), (door_right, door_bottom)],
                   fill=(140, 100, 60), outline=(100, 70, 30), width=4)
    # Door panels
    for py in range(door_top + 30, door_bottom - 60, 120):
        draw.rectangle([(door_left + 25, py), (door_right - 25, py + 100)],
                       fill=(130, 90, 50), outline=(100, 70, 30), width=3)
    # Door knob
    draw.ellipse([(door_right - 50, door_bottom // 2 - 10), (door_right - 30, door_bottom // 2 + 10)],
                 fill=(200, 170, 50), outline=(150, 120, 20), width=2)
    # Peephole
    draw.ellipse([(door_left + 120, door_top + 60), (door_left + 142, door_top + 82)],
                 fill=(60, 60, 60), outline=(30, 30, 30), width=2)
    # Door lock plate
    draw.rectangle([(door_right - 55, door_bottom // 2 - 5), (door_right - 45, door_bottom // 2 + 45)],
                   fill=(180, 170, 50))

    # Welcome mat
    draw.rectangle([(door_left - 30, door_bottom + 5), (door_right + 30, door_bottom + 25)],
                   fill=(140, 80, 50), outline=(100, 50, 20), width=2)
    font_small = _get_font(draw, 10)
    draw.text((door_left + 40, door_bottom + 8), "WELCOME", fill=(220, 200, 160), font=font_small)

    # Shoe rack (right of door)
    draw.rectangle([(door_right + 50, int(height * 0.55)), (door_right + 190, int(height * 0.78))],
                   fill=(150, 110, 60), outline=(100, 70, 30), width=2)
    for sy in range(int(height * 0.57), int(height * 0.78), 30):
        draw.line([(door_right + 55, sy), (door_right + 185, sy)], fill=(100, 70, 30), width=1)
    # Shoes
    shoe_colors = [(40, 40, 40), (180, 60, 40), (30, 30, 80), (200, 180, 160)]
    for si in range(4):
        sx = door_right + 70 + (si % 2) * 60
        sy_off = (si // 2) * 32
        draw.ellipse([(sx, int(height * 0.58) + sy_off), (sx + 40, int(height * 0.75) + sy_off)],
                     fill=shoe_colors[si])

    # Coat hooks on wall (left of door)
    draw.rectangle([(80, int(height * 0.2)), (door_left - 50, int(height * 0.22))],
                   fill=(120, 70, 30), outline=(80, 40, 10), width=2)
    for hx in range(110, door_left - 50, 40):
        draw.ellipse([(hx, int(height * 0.23)), (hx + 12, int(height * 0.27))],
                     fill=(180, 170, 50), outline=(140, 130, 20), width=1)
        # Hanging coat
        draw.rectangle([(hx - 10, int(height * 0.27)), (hx + 20, int(height * 0.48))],
                       fill=(60, 80, 140))

    # Light fixture on wall
    draw.rectangle([(door_left - 60, int(height * 0.12)), (door_left - 30, int(height * 0.18))],
                   fill=(220, 220, 200), outline=(180, 180, 160), width=2)
    draw.ellipse([(door_left - 70, int(height * 0.09)), (door_left - 20, int(height * 0.12))],
                 fill=(255, 255, 200))

    # Outdoor view through peephole-like small window at top
    draw.rectangle([(door_left + 80, door_top - 40), (door_right - 10, door_top + 30)],
                   fill=(120, 180, 220), outline=(60, 60, 60), width=3)
    # Clouds
    draw.ellipse([(400, door_top - 30), (430, door_top - 15)], fill=(240, 245, 250))
    draw.ellipse([(470, door_top - 25), (500, door_top - 10)], fill=(235, 240, 248))

    # Wall on sides
    draw.rectangle([(0, 0), (door_left - 30, height)], fill=(235, 225, 210))
    draw.rectangle([(door_right + 35, 0), (width, height)], fill=(235, 225, 210))

    # Security camera visible (the one we're viewing from!)
    draw.rectangle([(40, 20), (70, 50)], fill=(60, 60, 60), outline=(40, 40, 40), width=2)
    draw.ellipse([(45, 25), (65, 45)], fill=(30, 30, 50))
    draw.ellipse([(52, 32), (58, 38)], fill=(0, 180, 0))
    font_tiny = _get_font(draw, 8)
    draw.text((42, 52), "CAM-01", fill=(100, 100, 100), font=font_tiny)


def _draw_study(draw, width, height):
    """Draw a study room scene."""
    # Ceiling
    draw.rectangle([(0, 0), (width, 80)], fill=(235, 230, 220))
    # Walls
    draw.rectangle([(0, 80), (width, height - 120)], fill=(245, 240, 230))
    # Floor
    draw.rectangle([(0, height - 120), (width, height)], fill=(170, 140, 100))
    # Wood floor lines
    for fl in range(0, width, 60):
        draw.line([(fl, height - 120), (fl, height)], fill=(160, 130, 90), width=1)

    # Desk (center)
    draw.rectangle([(200, int(height * 0.5)), (800, int(height * 0.88))],
                   fill=(140, 100, 50), outline=(100, 70, 30), width=3)
    # Desk legs
    draw.rectangle([(210, int(height * 0.88)), (230, height)], fill=(100, 70, 30))
    draw.rectangle([(770, int(height * 0.88)), (790, height)], fill=(100, 70, 30))

    # Monitor
    draw.rectangle([(380, int(height * 0.22)), (620, int(height * 0.48))],
                   fill=(30, 30, 30), outline=(60, 60, 60), width=4)
    draw.rectangle([(395, int(height * 0.25)), (605, int(height * 0.45))],
                   fill=(40, 60, 100))
    # Monitor stand
    draw.rectangle([(470, int(height * 0.48)), (530, int(height * 0.52))],
                   fill=(50, 50, 50))
    draw.rectangle([(490, int(height * 0.52)), (510, int(height * 0.56))],
                   fill=(70, 70, 70))
    # Screen content
    draw.rectangle([(420, int(height * 0.29)), (580, int(height * 0.32))], fill=(60, 80, 120))
    draw.rectangle([(420, int(height * 0.35)), (500, int(height * 0.38))], fill=(50, 60, 80))
    draw.rectangle([(420, int(height * 0.41)), (550, int(height * 0.44))], fill=(50, 60, 80))

    # Keyboard
    draw.rectangle([(340, int(height * 0.56)), (540, int(height * 0.60))],
                   fill=(50, 50, 50), outline=(30, 30, 30), width=1)

    # Mouse
    draw.ellipse([(590, int(height * 0.57)), (615, int(height * 0.65))],
                 fill=(40, 40, 40))

    # Bookshelf (left wall)
    draw.rectangle([(30, 90), (170, int(height * 0.80))],
                   fill=(120, 80, 40), outline=(80, 50, 20), width=3)
    for by in range(110, int(height * 0.80), 40):
        draw.line([(35, by), (165, by)], fill=(80, 50, 20), width=2)
    # Books on shelves
    bcolors = [(180, 50, 40), (40, 70, 170), (180, 150, 30), (60, 140, 50), (140, 40, 120), (200, 80, 30)]
    for bi, by in enumerate(range(110, int(height * 0.80), 40)):
        for bj, bx in enumerate(range(40, 160, 18)):
            if bj < 6:
                draw.rectangle([(bx, by + 2), (bx + 14, by + 35)],
                               fill=bcolors[(bi + bj) % len(bcolors)], outline=(60, 60, 60))

    # Office chair
    draw.rectangle([(640, int(height * 0.60)), (720, int(height * 0.84))],
                   fill=(60, 60, 70), outline=(40, 40, 50), width=2)
    draw.ellipse([(635, int(height * 0.56)), (725, int(height * 0.64))],
                 fill=(50, 50, 60), outline=(30, 30, 40), width=2)
    # Chair base
    draw.rectangle([(660, int(height * 0.84)), (700, int(height * 0.88))],
                   fill=(100, 100, 100))
    draw.line([(680, int(height * 0.88)), (640, int(height * 0.94))], fill=(80, 80, 80), width=4)
    draw.line([(680, int(height * 0.88)), (720, int(height * 0.94))], fill=(80, 80, 80), width=4)

    # Lamp on desk
    draw.rectangle([(750, int(height * 0.36)), (760, int(height * 0.52))],
                   fill=(140, 140, 140))
    draw.polygon([(720, int(height * 0.36)), (790, int(height * 0.36)),
                  (780, int(height * 0.28)), (730, int(height * 0.28))],
                 fill=(240, 230, 180), outline=(200, 180, 140))

    # Window (right wall)
    draw.rectangle([(860, 120), (990, 380)], fill=(150, 200, 240), outline=(80, 80, 80), width=4)
    draw.line([(925, 120), (925, 380)], fill=(80, 80, 80), width=2)
    draw.line([(860, 250), (990, 250)], fill=(80, 80, 80), width=2)
    # Curtains
    draw.rectangle([(845, 100), (865, 400)], fill=(180, 160, 140))
    draw.rectangle([(985, 100), (1005, 400)], fill=(180, 160, 140))

    # Clock on wall
    draw.ellipse([(840, 130), (880, 170)], fill=(255, 255, 255), outline=(80, 80, 80), width=3)
    draw.line([(860, 150), (860, 140)], fill=(40, 40, 40), width=2)
    draw.line([(860, 150), (870, 155)], fill=(40, 40, 40), width=2)

    # Potted plant (corner right)
    draw.rectangle([(870, 420), (900, 480)], fill=(140, 100, 40))
    draw.ellipse([(850, 360), (920, 430)], fill=(30, 140, 40))
    draw.ellipse([(840, 380), (890, 410)], fill=(40, 150, 35))


# Scene dispatcher by camera
_SCENE_MAP = {
    "客厅摄像头": _draw_living_room,
    "门口摄像头": _draw_entrance,
    "书房摄像头": _draw_study,
}


def _make_jpeg(path: str, camera_name: str = "客厅摄像头",
               width: int = 1280, height: int = 720) -> str:
    """Generate a JPEG image of a scene matching the camera's location."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return _make_jpeg_raw(path, width, height)

    img = Image.new("RGB", (width, height), (245, 240, 230))
    draw = ImageDraw.Draw(img)

    # Draw the scene based on camera location
    scene_fn = _SCENE_MAP.get(camera_name, _draw_living_room)
    scene_fn(draw, width, height)

    # OSD Overlay
    _osd_overlay(draw, camera_name, width, height)

    img.save(path, "JPEG", quality=92)
    return path


def _make_jpeg_raw(path: str, width: int = 1280, height: int = 720) -> str:
    """Fallback: generate a minimal valid JPEG without PIL."""
    # Minimal JPEG: 8x8 single-color block
    # This is a valid JPEG file with a single gray block
    jpeg_data = bytes([
        # SOI
        0xFF, 0xD8,
        # APP0
        0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
        # DQT
        0xFF, 0xDB, 0x00, 0x43, 0x00,
    ] + bytes([8] * 64) + bytes([8] * 64) + bytes([
        # SOF0 (Baseline DCT)
        0xFF, 0xC0, 0x00, 0x11, 0x08,
        (height >> 8) & 0xFF, height & 0xFF,
        (width >> 8) & 0xFF, width & 0xFF,
        0x03,  # 3 components
        0x01, 0x11, 0x00,   # Y: 1x1 sampling
        0x02, 0x11, 0x01,   # Cb: 1x1 sampling
        0x03, 0x11, 0x01,   # Cr: 1x1 sampling
        # DHT
        0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
        0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B,
        0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03, 0x03,
        0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01,
        0x7D, 0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21,
        0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14,
        0x32, 0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1, 0x15,
        0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0A,
        0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28, 0x29,
        0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44,
        0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56,
        0x57, 0x58, 0x59, 0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
        0x69, 0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7A,
        0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x92, 0x93,
        0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3, 0xA4,
        0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5,
        0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6,
        0xC7, 0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,
        0xD8, 0xD9, 0xDA, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7,
        0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
        0xF8, 0xF9, 0xFA,
        # SOS
        0xFF, 0xDA, 0x00, 0x0C, 0x03, 0x01, 0x00, 0x02, 0x11, 0x03,
        0x11, 0x00, 0x3F, 0x00,
        # Compressed data (minimal)
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        # EOI
        0xFF, 0xD9,
    ]))
    with open(path, "wb") as f:
        f.write(jpeg_data)
    return path


# ═══════════════════════════════════════════════
#  device_mgmt  demo functions
# ═══════════════════════════════════════════════

def _demo_search_devices(*args, **kwargs):
    from .device_mgmt import (
        DiscoveredDevice, SearchResult, DiscoveryMethod, DeviceClass,
    )
    devices = []
    for d in _DEMO_DEVICES:
        devices.append(DiscoveredDevice(
            ip=d["ip"],
            onvif_port=d["onvif_port"],
            rtsp_port=d["rtsp_port"],
            device_class=DeviceClass(d["device_class"]),
            sn_code=d["sn_code"],
            model=d["model"],
            manufacturer=d["manufacturer"],
            supported_media=d["supported_media"],
        ))
    return SearchResult(success=True, devices=devices)


def _demo_connect_device(camera_name: str, token: Optional[str] = None):
    from .device_mgmt import ConnectResult
    device = _get_device(camera_name)
    if device is None:
        return ConnectResult(success=False, error_message=f"未找到设备: {camera_name}")
    dc = device["device_class"]
    auth_method = "token" if dc == "password_required" else "direct"
    token_used = dc == "password_required"
    _demo_connected_devices[camera_name] = True
    return ConnectResult(success=True, auth_method=auth_method, token_used=token_used)


def _demo_disconnect_device(camera_name: str):
    from .device_mgmt import DisconnectResult
    was_connected = _demo_connected_devices.pop(camera_name, False)
    return DisconnectResult(success=True, session_released=was_connected)


def _demo_query_device_model(camera_name: str):
    from .device_mgmt import DeviceInfo, DeviceInfoResult
    device = _get_device(camera_name)
    if device is None:
        return DeviceInfoResult(success=False, error_message=f"未找到设备: {camera_name}")
    info = DeviceInfo(
        manufacturer=device["manufacturer"],
        model=device["model"],
        firmware_version=device["firmware"],
        serial_number=device["sn_code"],
        hardware_id=f"HW-{device['sn_code'][-8:]}",
        ip_address=device["ip"],
        mac_address=device["mac"],
        is_online=True,
        network_type="WiFi",
    )
    return DeviceInfoResult(success=True, info=info)


def _demo_update_firmware(camera_name: str, firmware_path: Optional[str] = None):
    from .device_mgmt import FirmwareResult
    device = _get_device(camera_name)
    if device is None:
        return FirmwareResult(success=False, error_message=f"未找到设备: {camera_name}")
    old_ver = device["firmware"]
    new_ver = "v2.5.0" if firmware_path else "v2.4.2"
    return FirmwareResult(success=True, old_version=old_ver, new_version=new_ver)


def _demo_system_maintenance(camera_name: str, action=None):
    from .device_mgmt import MaintenanceResult, MaintenanceAction
    if action is None:
        action = MaintenanceAction.REBOOT
    device = _get_device(camera_name)
    if device is None:
        return MaintenanceResult(success=False, error_message=f"未找到设备: {camera_name}")
    action_name = action.value if hasattr(action, "value") else str(action)
    return MaintenanceResult(success=True, action_performed=action_name)


# ═══════════════════════════════════════════════
#  stream  demo functions
# ═══════════════════════════════════════════════

def _demo_get_audio_video_stream(camera_name: str, sub_stream: bool = False):
    from .stream import StreamResult
    device = _get_device(camera_name)
    if device is None:
        return StreamResult(success=False, error_message=f"未找到设备: {camera_name}")
    url = f"rtsp://{device['ip']}:{device['rtsp_port']}{device['rtsp_path']}"
    return StreamResult(
        success=True,
        stream_url=url,
        codec="H.264" if not sub_stream else "H.265",
        resolution="1920x1080" if not sub_stream else "640x360",
        fps=25.0 if not sub_stream else 15.0,
        bitrate=4096 if not sub_stream else 1024,
    )


def _demo_capture_video_screenshot(camera_name: str, save_path: Optional[str] = None):
    from .stream import ScreenshotResult
    device = _get_device(camera_name)
    if device is None:
        return ScreenshotResult(success=False, error_message=f"未找到设备: {camera_name}")
    temp_dir = os.environ.get("TEMP", "/tmp")
    if save_path:
        file_path = os.path.join(save_path, f"screenshot_{camera_name}_{int(time.time())}.jpg")
    else:
        file_path = os.path.join(temp_dir, f"screenshot_{camera_name}_{int(time.time())}.jpg")
    os.makedirs(os.path.dirname(file_path) or temp_dir, exist_ok=True)
    _make_jpeg(file_path, camera_name=camera_name)
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    return ScreenshotResult(
        success=True,
        file_path=file_path,
        width=1280,
        height=720,
    )


def _demo_toggle_recording(camera_name: str, action, save_path: Optional[str] = None):
    from .stream import RecordingResult, RecordingAction
    device = _get_device(camera_name)
    if device is None:
        return RecordingResult(success=False, error_message=f"未找到设备: {camera_name}")
    action_str = action.value if hasattr(action, "value") else str(action)
    if action_str in ("start", "START"):
        _demo_recording_state["is_recording"] = True
        _demo_recording_state["start_time"] = time.time()
        return RecordingResult(success=True, is_recording=True, file_path="")
    else:
        duration = time.time() - _demo_recording_state["start_time"]
        temp_dir = os.environ.get("TEMP", "/tmp")
        file_path = os.path.join(temp_dir, f"recording_{camera_name}_{int(time.time())}.mp4")
        _demo_recording_state["is_recording"] = False
        _demo_recording_state["start_time"] = 0.0
        _demo_recording_state["file_path"] = file_path
        return RecordingResult(
            success=True, is_recording=False,
            file_path=file_path, duration_seconds=round(duration, 1),
        )


def _demo_manage_storage_status(camera_name: str, action=None, path=None, format=None, policy=None):
    from .stream import StorageResult, StorageAction
    device = _get_device(camera_name)
    if device is None:
        return StorageResult(success=False, error_message=f"未找到设备: {camera_name}")
    action_str = action.value if action and hasattr(action, "value") else "query"
    return StorageResult(
        success=True,
        used_space_mb=1250.5,
        available_space_mb=28749.5,
        storage_path="/mnt/sdcard/recordings",
        format=format or "mp4",
        policy=policy or "overwrite",
    )


# ═══════════════════════════════════════════════
#  ptz  demo functions
# ═══════════════════════════════════════════════

# Direction to pan/tilt delta mapping
_PTZ_DELTA: Dict[str, tuple] = {
    "up": (0.0, 8.0),
    "down": (0.0, -8.0),
    "left": (-8.0, 0.0),
    "right": (8.0, 0.0),
    "上": (0.0, 8.0),
    "下": (0.0, -8.0),
    "左": (-8.0, 0.0),
    "右": (8.0, 0.0),
}


def _demo_control_ptz(camera_name: str, direction, speed: float = 0.5):
    from .ptz import PTZMoveResult, PTZDirection
    device = _get_device(camera_name)
    if device is None:
        return PTZMoveResult(success=False, error_message=f"未找到设备: {camera_name}")
    dir_key = direction.value if hasattr(direction, "value") else str(direction)
    delta = _PTZ_DELTA.get(dir_key, (0.0, 0.0))
    scale = max(0.1, min(1.0, speed))
    _demo_ptz_state["pan"] += delta[0] * scale
    _demo_ptz_state["tilt"] += delta[1] * scale
    _demo_ptz_state["pan"] = max(-170.0, min(170.0, _demo_ptz_state["pan"]))
    _demo_ptz_state["tilt"] = max(-20.0, min(90.0, _demo_ptz_state["tilt"]))
    return PTZMoveResult(
        success=True,
        current_pan=_demo_ptz_state["pan"],
        current_tilt=_demo_ptz_state["tilt"],
        current_zoom=_demo_ptz_state["zoom"],
    )


def _demo_control_lens_zoom(camera_name: str, action, speed: float = 0.5):
    from .ptz import PTZMoveResult
    device = _get_device(camera_name)
    if device is None:
        return PTZMoveResult(success=False, error_message=f"未找到设备: {camera_name}")
    action_str = action.value if hasattr(action, "value") else str(action)
    scale = max(0.1, min(1.0, speed))
    if action_str in ("in", "IN"):
        _demo_ptz_state["zoom"] = min(32.0, _demo_ptz_state["zoom"] + scale * 1.5)
    else:
        _demo_ptz_state["zoom"] = max(1.0, _demo_ptz_state["zoom"] - scale * 1.5)
    return PTZMoveResult(
        success=True,
        current_pan=_demo_ptz_state["pan"],
        current_tilt=_demo_ptz_state["tilt"],
        current_zoom=round(_demo_ptz_state["zoom"], 1),
    )


def _demo_get_ptz_parameters(camera_name: str):
    from .ptz import PTZParameters
    device = _get_device(camera_name)
    if device is None:
        return PTZParameters(pan=0, tilt=0, zoom=0, pan_speed=0, tilt_speed=0, is_moving=False)
    return PTZParameters(
        pan=_demo_ptz_state["pan"],
        tilt=_demo_ptz_state["tilt"],
        zoom=_demo_ptz_state["zoom"],
        pan_speed=0.0,
        tilt_speed=0.0,
        is_moving=False,
    )


def _demo_save_ptz_preset(camera_name: str, preset_name: str):
    from .ptz import PTZPresetResult
    device = _get_device(camera_name)
    if device is None:
        return PTZPresetResult(success=False, error_message=f"未找到设备: {camera_name}")
    token = f"preset_{len(_demo_presets) + 1:03d}"
    _demo_presets[preset_name] = {
        "pan": _demo_ptz_state["pan"],
        "tilt": _demo_ptz_state["tilt"],
        "zoom": _demo_ptz_state["zoom"],
    }
    return PTZPresetResult(success=True, preset_name=preset_name, preset_token=token)


def _demo_go_to_preset(camera_name: str, preset_name: str, speed: float = 1.0):
    from .ptz import PTZMoveResult
    device = _get_device(camera_name)
    if device is None:
        return PTZMoveResult(success=False, error_message=f"未找到设备: {camera_name}")
    if preset_name not in _demo_presets:
        return PTZMoveResult(success=False, error_message=f"预置点不存在: {preset_name}")
    preset = _demo_presets[preset_name]
    _demo_ptz_state.update(preset)
    return PTZMoveResult(
        success=True,
        current_pan=_demo_ptz_state["pan"],
        current_tilt=_demo_ptz_state["tilt"],
        current_zoom=_demo_ptz_state["zoom"],
    )


def _demo_calibrate_ptz(camera_name: str):
    from .ptz import CalibrateResult
    device = _get_device(camera_name)
    if device is None:
        return CalibrateResult(success=False, error_message=f"未找到设备: {camera_name}")
    _demo_ptz_state.update({"pan": 0.0, "tilt": 0.0, "zoom": 1.0})
    return CalibrateResult(success=True)


def _demo_start_patrol_cruise(camera_name: str, cruise_name: Optional[str] = None):
    from .ptz import CruiseResult
    device = _get_device(camera_name)
    if device is None:
        return CruiseResult(success=False, error_message=f"未找到设备: {camera_name}")
    name = cruise_name or "默认巡航"
    count = len(_demo_presets)
    return CruiseResult(success=True, cruise_name=name, preset_count=count)


# ═══════════════════════════════════════════════
#  tracking  demo functions
# ═══════════════════════════════════════════════

def _demo_track_vehicles(camera_name: str, action=None):
    from .tracking import TrackingResult, TrackingAction
    device = _get_device(camera_name)
    if device is None:
        return TrackingResult(success=False, error_message=f"未找到设备: {camera_name}")
    action_str = action.value if action and hasattr(action, "value") else "start"
    is_tracking = action_str in ("start", "START")
    _demo_tracking_state["vehicle"] = is_tracking
    return TrackingResult(success=True, is_tracking=is_tracking, algorithm="vehicle_detection_v2")


def _demo_track_human_shapes(camera_name: str, action=None):
    from .tracking import TrackingResult, TrackingAction
    device = _get_device(camera_name)
    if device is None:
        return TrackingResult(success=False, error_message=f"未找到设备: {camera_name}")
    action_str = action.value if action and hasattr(action, "value") else "start"
    is_tracking = action_str in ("start", "START")
    _demo_tracking_state["human"] = is_tracking
    return TrackingResult(success=True, is_tracking=is_tracking, algorithm="human_tracking_v3")


def _demo_monitor_zone_entry(camera_name: str, action=None, zone=None):
    from .tracking import ZoneMonitorResult, ZoneAction
    device = _get_device(camera_name)
    if device is None:
        return ZoneMonitorResult(success=False, error_message=f"未找到设备: {camera_name}")
    action_str = action.value if action and hasattr(action, "value") else "start"
    is_monitoring = action_str in ("start", "START")
    _demo_tracking_state["zone"] = is_monitoring
    return ZoneMonitorResult(
        success=True, is_monitoring=is_monitoring,
        zone_triggered=False, trigger_type="",
    )


def _demo_stop_tracking_service(camera_name: str):
    from .tracking import StopTrackingResult
    stopped = []
    for key, active in list(_demo_tracking_state.items()):
        if active:
            stopped.append(f"{key}_tracking")
            _demo_tracking_state[key] = False
    return StopTrackingResult(success=True, stopped_services=stopped)


# ═══════════════════════════════════════════════
#  image_audio  demo functions
# ═══════════════════════════════════════════════

def _demo_adjust_picture_settings(camera_name: str, brightness=None, contrast=None,
                                  saturation=None, sharpness=None):
    from .image_audio import PictureResult, PictureSettings
    device = _get_device(camera_name)
    if device is None:
        return PictureResult(success=False, error_message=f"未找到设备: {camera_name}")
    settings = _demo_picture_settings.setdefault(camera_name, {
        "brightness": 128, "contrast": 128, "saturation": 128, "sharpness": 128,
    })
    if brightness is not None:
        settings["brightness"] = max(0, min(255, brightness))
    if contrast is not None:
        settings["contrast"] = max(0, min(255, contrast))
    if saturation is not None:
        settings["saturation"] = max(0, min(255, saturation))
    if sharpness is not None:
        settings["sharpness"] = max(0, min(255, sharpness))
    return PictureResult(success=True, current_settings=PictureSettings(**settings))


def _demo_flip_video_display(camera_name: str, mode=None):
    from .image_audio import FlipResult
    device = _get_device(camera_name)
    if device is None:
        return FlipResult(success=False, error_message=f"未找到设备: {camera_name}")
    return FlipResult(success=True, current_mode=mode)


def _demo_configure_night_vision(camera_name: str, mode=None):
    from .image_audio import NightVisionResult
    device = _get_device(camera_name)
    if device is None:
        return NightVisionResult(success=False, error_message=f"未找到设备: {camera_name}")
    if mode is not None:
        _demo_night_vision[camera_name] = mode.value if hasattr(mode, "value") else str(mode)
    current = _demo_night_vision.get(camera_name, "infrared")
    try:
        from .image_audio import NightVisionMode
        current = NightVisionMode(current)
    except Exception:
        pass
    return NightVisionResult(success=True, current_mode=current)


def _demo_set_floodlight_mode(camera_name: str, mode=None):
    from .image_audio import FloodlightModeResult
    device = _get_device(camera_name)
    if device is None:
        return FloodlightModeResult(success=False, error_message=f"未找到设备: {camera_name}")
    if mode is not None:
        _demo_floodlight_mode[camera_name] = mode.value if hasattr(mode, "value") else str(mode)
    current = _demo_floodlight_mode.get(camera_name, "auto")
    try:
        from .image_audio import FloodlightMode
        current = FloodlightMode(current)
    except Exception:
        pass
    return FloodlightModeResult(success=True, current_mode=current)


def _demo_configure_floodlight_type(camera_name: str, floodlight_type=None):
    from .image_audio import FloodlightTypeResult
    device = _get_device(camera_name)
    if device is None:
        return FloodlightTypeResult(success=False, error_message=f"未找到设备: {camera_name}")
    if floodlight_type is not None:
        _demo_floodlight_type[camera_name] = floodlight_type.value if hasattr(floodlight_type, "value") else str(floodlight_type)
    current = _demo_floodlight_type.get(camera_name, "white")
    try:
        from .image_audio import FloodlightType
        current = FloodlightType(current)
    except Exception:
        pass
    return FloodlightTypeResult(success=True, current_type=current)


def _demo_configure_microphone(camera_name: str, enabled: bool = True,
                               gain=None, noise_reduction=None):
    from .image_audio import MicrophoneResult
    device = _get_device(camera_name)
    if device is None:
        return MicrophoneResult(success=False, error_message=f"未找到设备: {camera_name}")
    mic = _demo_microphone.setdefault(camera_name, {
        "enabled": True, "gain": 50, "noise_reduction": True,
    })
    mic["enabled"] = enabled
    if gain is not None:
        mic["gain"] = gain
    if noise_reduction is not None:
        mic["noise_reduction"] = noise_reduction
    return MicrophoneResult(
        success=True, enabled=mic["enabled"],
        gain=mic["gain"], noise_reduction=mic["noise_reduction"],
    )


def _demo_configure_speaker(camera_name: str, enabled: bool = True, volume=None):
    from .image_audio import SpeakerResult
    device = _get_device(camera_name)
    if device is None:
        return SpeakerResult(success=False, error_message=f"未找到设备: {camera_name}")
    spk = _demo_speaker.setdefault(camera_name, {"enabled": True, "volume": 50})
    spk["enabled"] = enabled
    if volume is not None:
        spk["volume"] = max(0, min(100, volume))
    return SpeakerResult(success=True, enabled=spk["enabled"], volume=spk["volume"])


# ═══════════════════════════════════════════════
#  alarm  demo functions
# ═══════════════════════════════════════════════

def _demo_configure_alarm_settings(camera_name: str, sound_enabled=None,
                                   trigger_frequency=None, sensitivity=None):
    from .alarm import AlarmSettingsResult
    device = _get_device(camera_name)
    if device is None:
        return AlarmSettingsResult(success=False, error_message=f"未找到设备: {camera_name}")
    alarm = _demo_alarm.setdefault(camera_name, {
        "sound_enabled": True, "trigger_frequency": "每30秒最多1次", "sensitivity": 70,
    })
    if sound_enabled is not None:
        alarm["sound_enabled"] = sound_enabled
    if trigger_frequency is not None:
        alarm["trigger_frequency"] = trigger_frequency
    if sensitivity is not None:
        alarm["sensitivity"] = max(0, min(100, sensitivity))
    return AlarmSettingsResult(
        success=True,
        sound_enabled=alarm["sound_enabled"],
        trigger_frequency=alarm["trigger_frequency"],
        sensitivity=alarm["sensitivity"],
    )


def _demo_configure_alarm_push(camera_name: str, push_type=None,
                               time_range=None, enabled=None):
    from .alarm import AlarmPushResult, PushType
    device = _get_device(camera_name)
    if device is None:
        return AlarmPushResult(success=False, error_message=f"未找到设备: {camera_name}")
    push = _demo_alarm_push.setdefault(camera_name, {
        "push_type": "app", "time_range": "08:00-22:00", "enabled": True,
    })
    if push_type is not None:
        push["push_type"] = push_type.value if hasattr(push_type, "value") else str(push_type)
    if time_range is not None:
        push["time_range"] = time_range
    if enabled is not None:
        push["enabled"] = enabled
    current_pt = push["push_type"]
    try:
        current_pt = PushType(current_pt)
    except Exception:
        pass
    return AlarmPushResult(
        success=True, push_type=current_pt,
        time_range=push["time_range"], enabled=push["enabled"],
    )


# ═══════════════════════════════════════════════
#  encoding_osd  demo functions
# ═══════════════════════════════════════════════

def _demo_configure_video_encoding(camera_name: str, stream_type=None, codec=None,
                                   resolution=None, bitrate_kbps=None, fps=None,
                                   gop=None, bitrate_mode=None):
    from .encoding_osd import EncodingResult, EncodingSettings, StreamType, VideoCodec, BitrateMode
    device = _get_device(camera_name)
    if device is None:
        return EncodingResult(success=False, error_message=f"未找到设备: {camera_name}")
    enc = _demo_encoding.setdefault(camera_name, {
        "stream_type": "main", "codec": "H.264", "resolution": "1920x1080",
        "bitrate_kbps": 4096, "fps": 25, "gop": 50, "bitrate_mode": "vbr",
    })
    if stream_type is not None:
        enc["stream_type"] = stream_type.value if hasattr(stream_type, "value") else str(stream_type)
    if codec is not None:
        enc["codec"] = codec.value if hasattr(codec, "value") else str(codec)
    if resolution is not None:
        enc["resolution"] = resolution
    if bitrate_kbps is not None:
        enc["bitrate_kbps"] = bitrate_kbps
    if fps is not None:
        enc["fps"] = fps
    if gop is not None:
        enc["gop"] = gop
    if bitrate_mode is not None:
        enc["bitrate_mode"] = bitrate_mode.value if hasattr(bitrate_mode, "value") else str(bitrate_mode)
    settings = EncodingSettings(
        stream_type=StreamType(enc["stream_type"]),
        codec=VideoCodec(enc["codec"]),
        resolution=enc["resolution"],
        bitrate_kbps=enc["bitrate_kbps"],
        fps=enc["fps"],
        gop=enc["gop"],
        bitrate_mode=BitrateMode(enc["bitrate_mode"]),
    )
    return EncodingResult(success=True, current_settings=settings)


def _demo_configure_osd_settings(camera_name: str, show_time=None, show_weekday=None,
                                 device_name=None, osd_name=None, alignment=None):
    from .encoding_osd import OSDResult, OSDSettings, OSDAlignment
    device = _get_device(camera_name)
    if device is None:
        return OSDResult(success=False, error_message=f"未找到设备: {camera_name}")
    osd = _demo_osd.setdefault(camera_name, {
        "show_time": True, "show_weekday": False,
        "device_name": camera_name, "osd_name": camera_name,
        "alignment": "top_left",
    })
    if show_time is not None:
        osd["show_time"] = show_time
    if show_weekday is not None:
        osd["show_weekday"] = show_weekday
    if device_name is not None:
        osd["device_name"] = device_name
    if osd_name is not None:
        osd["osd_name"] = osd_name
    if alignment is not None:
        osd["alignment"] = alignment.value if hasattr(alignment, "value") else str(alignment)
    settings = OSDSettings(
        show_time=osd["show_time"],
        show_weekday=osd["show_weekday"],
        device_name=osd["device_name"],
        osd_name=osd["osd_name"],
        alignment=OSDAlignment(osd["alignment"]),
    )
    return OSDResult(success=True, current_settings=settings)
