"""
phase2 - 认证模块 - SN 码解码与摄像头权限管理

核心功能：
  - 用户输入设备 SN 码
  - 通过解码算法将 SN 码转换为摄像头登录密码
  - 管理 SN → 密码的映射缓存
  - 支持多设备多 SN 码

解码算法：当前为占位实现（TODO），实际算法需要根据具体厂商协议填充。
"""
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class DeviceAuth:
    """单个设备的认证信息"""
    sn_code: str                           # 设备 SN 码（用户输入）
    decoded_password: str = ""             # 解码后的密码
    username: str = "admin"                # 登录用户名（通常固定为 admin）
    is_decoded: bool = False               # 是否已成功解码
    device_ip: str = ""                    # 关联的设备 IP（可选）
    device_model: str = ""                 # 设备型号（可选）


# ──────────────────────────────────────────────
#  SN 码解码器
# ──────────────────────────────────────────────

class SNDecoder:
    """
    SN 码解码器 - 将设备序列号转换为登录密码。

    解码算法说明：
      当前为占位实现。实际使用时，需要根据摄像头厂商提供的
      SN-密码映射规则来实现 decode() 方法。

    常见的 SN 解码思路（仅供实现参考）：
      1. 哈希派生：password = hash(sn + salt)[:N]
      2. 查表法：厂商预置 SN→密码 对照表
      3. 加密算法：AES/RSA 解密 SN 得到密码
      4. 自定义编码：位运算、字符替换等
    """

    def __init__(self, cache_file: str = ""):
        self._cache: Dict[str, DeviceAuth] = {}
        self._cache_file = cache_file
        if cache_file and os.path.isfile(cache_file):
            self._load_cache()

    # ── 核心解码方法 ──

    def decode(self, sn_code: str) -> str:
        """
        将 SN 码解码为摄像头登录密码。

        ⚠️ TODO: 此处为占位实现，需要替换为实际的解码算法。

        当前占位逻辑：
          - 如果 SN 码为空，返回空字符串
          - 否则使用 SN 码的 MD5 哈希前 8 位作为临时密码
            （这只是一个演示，实际密码算法需要根据厂商协议实现）

        :param sn_code: 设备 SN 码
        :return: 解码后的密码字符串
        """
        if not sn_code or not sn_code.strip():
            raise ValueError("SN 码不能为空")

        sn_code = sn_code.strip()

        # ═══════════════════════════════════════════════════
        #  TODO: 在此处实现实际的 SN → 密码 解码算法
        #
        #  示例占位实现（需要替换）：
        #    - 方案 A：哈希派生
        #      raw = sn_code + "YOUR_SECRET_SALT"
        #      password = hashlib.sha256(raw.encode()).hexdigest()[:8]
        #
        #    - 方案 B：查表法
        #      password = VENDOR_PASSWORD_TABLE.get(sn_code, "")
        #
        #    - 方案 C：调用厂商 API
        #      password = vendor_api.decode_sn(sn_code)
        #
        #    - 方案 D：自定义编码算法
        #      password = custom_decode(sn_code)
        # ═══════════════════════════════════════════════════

        # --- 占位实现开始 ---
        raw = sn_code.encode("utf-8")
        password = hashlib.md5(raw).hexdigest()[:8]
        # --- 占位实现结束 ---

        return password

    def decode_and_cache(self, sn_code: str, username: str = "admin",
                         device_ip: str = "", device_model: str = "") -> DeviceAuth:
        """
        解码 SN 码并缓存结果。

        :param sn_code: 设备 SN 码
        :param username: 登录用户名
        :param device_ip: 设备 IP（可选）
        :param device_model: 设备型号（可选）
        :return: DeviceAuth 对象
        """
        password = self.decode(sn_code)
        auth = DeviceAuth(
            sn_code=sn_code.strip(),
            decoded_password=password,
            username=username,
            is_decoded=True,
            device_ip=device_ip,
            device_model=device_model,
        )
        self._cache[sn_code.strip()] = auth
        self._save_cache()
        return auth

    def get_cached(self, sn_code: str) -> Optional[DeviceAuth]:
        """获取已缓存的设备认证信息"""
        return self._cache.get(sn_code.strip())

    def get_password(self, sn_code: str) -> str:
        """获取 SN 码对应的密码（优先从缓存获取，否则解码）"""
        cached = self.get_cached(sn_code)
        if cached and cached.is_decoded:
            return cached.decoded_password
        return self.decode(sn_code)

    def list_cached(self) -> Dict[str, DeviceAuth]:
        """返回所有缓存的设备认证信息"""
        return dict(self._cache)

    def clear_cache(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._save_cache()

    # ── 缓存持久化 ──

    def _save_cache(self) -> None:
        """将缓存保存到文件"""
        if not self._cache_file:
            return
        try:
            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            data = {}
            for sn, auth in self._cache.items():
                data[sn] = {
                    "sn_code": auth.sn_code,
                    "decoded_password": auth.decoded_password,
                    "username": auth.username,
                    "is_decoded": auth.is_decoded,
                    "device_ip": auth.device_ip,
                    "device_model": auth.device_model,
                }
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Auth] 保存缓存失败: {e}")

    def _load_cache(self) -> None:
        """从文件加载缓存"""
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sn, info in data.items():
                self._cache[sn] = DeviceAuth(**info)
            if self._cache:
                print(f"[Auth] 已加载 {len(self._cache)} 条 SN 缓存")
        except Exception as e:
            print(f"[Auth] 加载缓存失败: {e}")
