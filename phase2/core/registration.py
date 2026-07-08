"""
phase2 - 摄像头注册模块 - 向远程授权服务器注册摄像头设备

核心功能：
  - 读取项目根目录下的 auth_server.yaml 获取远程授权服务器地址
  - 用户输入设备 SN 码后，获取本机 IP
  - 向授权服务器发送 HTTP POST 请求（包含本机 IP 和设备 SN 码）
  - 处理并返回服务器响应

配置文件位置：项目根目录 / auth_server.yaml
"""
import os
import socket
from typing import Optional

import httpx
import yaml


class CameraRegistrar:
    """
    摄像头注册器 - 向远程授权服务器注册设备。

    使用流程：
      1. 用户输入设备 SN 码
      2. 自动获取本机 IP 地址
      3. 向 auth_server.yaml 中配置的服务器地址发送 HTTP POST 请求
      4. 请求体: {"sn_code": "...", "local_ip": "..."}
    """

    # 授权服务器配置文件路径（项目根目录下）
    # phase2/core/registration.py -> phase2/core -> phase2 -> 项目根
    CONFIG_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "auth_server.yaml",
    )

    def __init__(self):
        self.server_url: str = ""
        self.timeout: float = 30.0
        self._load_config()

    # ── 配置加载 ──

    def _load_config(self) -> None:
        """从项目根目录的 auth_server.yaml 加载服务器地址。"""
        if not os.path.exists(self.CONFIG_PATH):
            print(f"[注册] 未找到授权服务器配置文件: {self.CONFIG_PATH}")
            print("[注册] 已生成默认配置模板，请编辑后使用。")
            self._create_default_config()
            return

        try:
            with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.server_url = data.get("server_url", "")
            self.timeout = float(data.get("timeout", 30))

            if not self.server_url:
                print("[注册] 警告: 授权服务器地址为空，请编辑 auth_server.yaml")
            else:
                print(f"[注册] 授权服务器地址: {self.server_url}")
        except Exception as e:
            print(f"[注册] 加载配置失败: {e}")

    def _create_default_config(self) -> None:
        """生成默认配置模板文件。"""
        default = {
            "server_url": "http://192.168.1.200:8080/api/camera/register",
            "timeout": 30,
        }
        try:
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(default, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            print(f"[注册] 默认配置已写入: {self.CONFIG_PATH}")
        except Exception as e:
            print(f"[注册] 写入默认配置失败: {e}")

    # ── 本机 IP 获取 ──

    @staticmethod
    def get_local_ip() -> Optional[str]:
        """获取本机局域网 IP 地址。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return None

    # ── 核心注册方法 ──

    def register(self, sn_code: str) -> dict:
        """
        向远程授权服务器注册摄像头。

        :param sn_code: 设备 SN 码
        :return: 服务器响应（dict）
        :raises ValueError: SN 码为空或服务器地址未配置
        :raises httpx.HTTPStatusError: 服务器返回错误状态码
        :raises Exception: 网络请求失败
        """
        if not sn_code or not sn_code.strip():
            raise ValueError("SN 码不能为空")

        if not self.server_url:
            raise ValueError("授权服务器地址未配置，请编辑项目根目录下的 auth_server.yaml")

        sn_code = sn_code.strip()
        local_ip = self.get_local_ip()
        if not local_ip:
            raise ValueError("无法获取本机 IP 地址")

        payload = {
            "sn_code": sn_code,
            "local_ip": local_ip,
        }

        print(f"[注册] 正在向授权服务器发送注册请求...")
        print(f"[注册]   服务器: {self.server_url}")
        print(f"[注册]   设备 SN: {sn_code}")
        print(f"[注册]   本机 IP: {local_ip}")

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.server_url, json=payload)
            response.raise_for_status()
            result = response.json()

        print(f"[注册] 注册请求已发送，服务器响应: {result}")
        return result

    def is_configured(self) -> bool:
        """检查授权服务器地址是否已配置。"""
        return bool(self.server_url)
