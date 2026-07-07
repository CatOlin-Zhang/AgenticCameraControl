"""
Agentic Camera Control - 智能摄像头控制系统
程序入口
"""
import argparse
import sys

from phase1.core.config import load_config, AppConfig
from phase1.core.camera import CameraManager
from phase1.core.events import EventBus
from phase1.core.llm import LocalLLMClient, OllamaClient
from phase1.ui.cli import CLIApp


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
    return parser.parse_args()


def bootstrap(config: AppConfig) -> tuple:
    """
    初始化系统各组件（静默初始化，不自动连接摄像头）
    :return: (CameraManager, LLMClient, EventBus)
    """
    # 1. 事件总线
    event_bus = EventBus()

    # 2. 摄像头管理器（仅注册配置中的摄像头，不自动连接）
    camera_manager = CameraManager(event_bus)
    for cam_config in config.cameras:
        camera_manager.add_camera(cam_config)

    # 3. LLM 客户端（根据配置选择本地或 Ollama 后端）
    if config.llm.backend == "ollama":
        llm_client = OllamaClient(config.llm)
    else:
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

    # 静默初始化组件（不自动连接摄像头，由 LLM 根据用户意图决策）
    camera_manager, llm_client, event_bus = bootstrap(config)

    # 选择 UI 模式
    if args.mode == "gui":
        try:
            from phase1.ui.gui import GUIApp
            app = GUIApp(camera_manager, llm_client, event_bus)
        except NotImplementedError as e:
            print(f"\n[错误] {e}")
            sys.exit(1)
    else:
        app = CLIApp(camera_manager, llm_client, event_bus, app_config=config)

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
