"""
Agentic Camera Control - 智能摄像头控制系统
程序入口
"""
import argparse
import sys

from core.config import load_config, AppConfig
from core.camera import CameraManager
from core.events import EventBus
from core.llm import LocalLLMClient, OllamaClient
from ui.cli import CLIApp


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Agentic Camera Control - 智能摄像头控制系统",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="指定配置文件路径（默认使用项目根目录下的 config.yaml）",
    )
    parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=["cli", "gui"],
        default="cli",
        help="运行模式：cli（命令行）或 gui（图形界面，尚未实现）",
    )
    parser.add_argument(
        "--auto-connect",
        action="store_true",
        default=False,
        help="启动时自动连接所有已注册的摄像头",
    )
    return parser.parse_args()


def bootstrap(config: AppConfig, auto_connect: bool = False) -> tuple:
    """
    初始化系统各组件
    :return: (CameraManager, LLMClient, EventBus)
    """
    # 1. 事件总线
    event_bus = EventBus()

    # 2. 摄像头管理器
    camera_manager = CameraManager(event_bus)
    for cam_config in config.cameras:
        camera_manager.add_camera(cam_config)

    # 3. 自动连接所有摄像头（USB 直连 + ONVIF/RTSP 均自动连接）
    for cam_config in config.cameras:
        ok = camera_manager.connect(cam_config.name)
        mode = cam_config.connection_type.upper()
        status = "成功" if ok else "失败"
        print(f"[启动] {mode} 摄像头 {cam_config.name} 连接{status}")

    # 4. LLM 客户端（根据配置选择本地或 Ollama 后端）
    if config.llm.backend == "ollama":
        print("[LLM] 使用 Ollama 后端")
        llm_client = OllamaClient(config.llm)
    else:
        print("[LLM] 使用本地 llama-cpp-python 后端")
        llm_client = LocalLLMClient(config.llm)

    return camera_manager, llm_client, event_bus


def main() -> None:
    """主入口"""
    args = parse_args()

    # 加载配置
    if args.config:
        config = load_config(args.config)
    else:
        config = load_config()

    # 如果配置文件刚被创建（cameras 为空），提示用户编辑后退出
    if not config.cameras:
        print("\n请先编辑 config.yaml 填入摄像头信息后重新运行。")
        sys.exit(1)

    # 初始化组件
    camera_manager, llm_client, event_bus = bootstrap(
        config, auto_connect=args.auto_connect
    )

    # 选择 UI 模式
    if args.mode == "gui":
        try:
            from ui.gui import GUIApp
            app = GUIApp(camera_manager, llm_client, event_bus)
        except NotImplementedError as e:
            print(f"\n[错误] {e}")
            sys.exit(1)
    else:
        app = CLIApp(camera_manager, llm_client, event_bus)

    # 启动
    try:
        app.start()
    except Exception as e:
        print(f"\n[致命错误] {e}")
        camera_manager.disconnect_all()
        llm_client.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
