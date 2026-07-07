"""
phase2 - Agentic Camera Control 第二阶段
SN 码认证 + LLM 对话控制 + 摄像头发现/拉流

程序入口：python -m phase2.main
"""
import argparse
import sys

from phase2.core.config import load_config, AppConfig, SN_CACHE_FILE
from phase2.core.camera import CameraManager
from phase2.core.events import EventBus
from phase2.core.auth import SNDecoder
from phase2.core.llm import LocalLLMClient, OllamaClient
from phase2.ui.cli import CLIApp


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Agentic Camera Control Phase2 - SN 码认证 + 智能控制",
    )
    parser.add_argument(
        "--config", "-c", type=str, default=None,
        help="指定配置文件路径（默认 phase2/config.yaml）",
    )
    parser.add_argument(
        "--mode", "-m", type=str, choices=["cli", "gui"], default="cli",
        help="运行模式：cli（命令行）或 gui（图形界面，尚未实现）",
    )
    parser.add_argument(
        "--auto-connect", action="store_true", default=False,
        help="启动时自动连接所有已注册的摄像头",
    )
    return parser.parse_args()


def bootstrap(config: AppConfig, auto_connect: bool = False) -> tuple:
    """
    初始化系统各组件。
    Phase2 新增：初始化 SNDecoder 并传递给 CameraManager。

    :return: (CameraManager, LLMClient, EventBus, SNDecoder)
    """
    # 1. 事件总线
    event_bus = EventBus()

    # 2. SN 解码器（Phase2 核心新增）
    sn_decoder = SNDecoder(cache_file=SN_CACHE_FILE)
    print("[Auth] SN 码解码器已初始化")

    # 3. 摄像头管理器（传入 SN 解码器）
    camera_manager = CameraManager(event_bus, sn_decoder=sn_decoder)
    for cam_config in config.cameras:
        camera_manager.add_camera(cam_config)

    # 4. 自动连接所有已配置的摄像头
    for cam_config in config.cameras:
        if auto_connect or cam_config.password or cam_config.sn_code:
            ok = camera_manager.connect(cam_config.name)
            mode = cam_config.connection_type.upper()
            status = "成功" if ok else "失败"
            print(f"[启动] {mode} 摄像头 {cam_config.name} 连接{status}")

    # 5. LLM 客户端
    if config.llm.backend == "ollama":
        print("[LLM] 使用 Ollama 后端")
        llm_client = OllamaClient(config.llm)
    else:
        print("[LLM] 使用本地 llama-cpp-python 后端")
        llm_client = LocalLLMClient(config.llm)

    return camera_manager, llm_client, event_bus, sn_decoder


def main() -> None:
    """主入口"""
    args = parse_args()

    # 加载配置
    if args.config:
        config = load_config(args.config)
    else:
        config = load_config()

    # 初始化组件
    camera_manager, llm_client, event_bus, sn_decoder = bootstrap(
        config, auto_connect=args.auto_connect
    )

    # CLI 模式
    app = CLIApp(camera_manager, llm_client, event_bus, sn_decoder)

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
