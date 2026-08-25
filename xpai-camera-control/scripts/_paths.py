"""
路径解析兼容层

支持三种运行模式：
  - 开发模式：基于源码目录树定位项目根
  - PyInstaller 编译模式：基于 CWD（用户执行二进制的当前目录）
  - Wheel 安装模式（pip install 后 import）：基于 CWD（用户脚本工作目录）
"""

import sys
from pathlib import Path


def _is_wheel_installed() -> bool:
    """检测是否通过 pip install 安装到 site-packages。"""
    path_str = str(Path(__file__).resolve())
    return "site-packages" in path_str


def get_skill_root() -> Path:
    """项目根目录。

    - 开发模式（python scripts/mcp_server.py）：
        __file__ → scripts/_paths.py → parent.parent = 项目根
    - 编译模式（./mcp-camera-server）：
        返回 CWD，即用户执行二进制的当前目录
    - Wheel 安装模式（pip install 后 import）：
        返回 CWD，即用户脚本的工作目录
    """
    if getattr(sys, "frozen", False):
        return Path.cwd()
    if _is_wheel_installed():
        return Path.cwd()
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """数据目录（config.yaml / snapshots / video / events）。

    与 get_skill_root() 相同：
    - 开发模式 = 源码项目根
    - 编译模式 = CWD
    - Wheel 安装模式 = CWD
    """
    return get_skill_root()
