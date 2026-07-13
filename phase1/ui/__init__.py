"""
ui - 用户界面模块
包含 CLI 和 GUI 两种交互方式
"""
from phase1.ui.base import BaseUI
from phase1.ui.cli import CLIApp

try:
    from phase1.ui.gui import GUIApp
except ImportError:
    GUIApp = None  # PySide6 未安装时 GUI 不可用
