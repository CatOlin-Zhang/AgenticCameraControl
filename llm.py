"""
大模型集成模块 - 通过本地 Ollama 服务解析自然语言指令
功能：
  - 调用 Ollama Chat API 进行意图理解
  - 将用户自然语言转换为结构化控制命令
  - 支持流式输出（CLI 对话体验）
  - 对话历史管理
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

from config import OllamaConfig


# ──────────────────────────────────────────────
#  解析后的命令结构
# ──────────────────────────────────────────────
@dataclass
class ParsedCommand:
    """大模型解析出的结构化命令"""
    command: str                             # 命令名称
    params: Dict[str, Any] = field(default_factory=dict)  # 命令参数
    raw_response: str = ""                   # 模型原始回复
    confidence: float = 1.0                  # 置信度（预留）

    @property
    def is_valid(self) -> bool:
        return bool(self.command)


# ──────────────────────────────────────────────
#  对话消息
# ──────────────────────────────────────────────
@dataclass
class ChatMessage:
    """单条对话消息"""
    role: str       # "system" | "user" | "assistant"
    content: str


# ──────────────────────────────────────────────
#  Ollama LLM 客户端
# ──────────────────────────────────────────────
class OllamaClient:
    """
    Ollama 大模型客户端。
    负责与本地 Ollama 服务通信，实现自然语言 → 控制命令的转换。
    """

    def __init__(self, config: OllamaConfig):
        self.config = config
        self._history: List[ChatMessage] = []
        self._client: Optional[httpx.Client] = None

        # 初始化对话历史（加入 system prompt）
        self._history.append(ChatMessage(role="system", content=config.system_prompt))

    # ── 连接管理 ────────────────────────────────

    def _get_client(self) -> httpx.Client:
        """获取或创建 HTTP 客户端（懒加载）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
        return self._client

    def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            self._client.close()

    def is_available(self) -> bool:
        """
        检查 Ollama 服务是否可用
        :return: True 表示服务在线
        """
        try:
            client = self._get_client()
            resp = client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """列出 Ollama 中可用的模型"""
        try:
            client = self._get_client()
            resp = client.get("/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            print(f"[LLM] 获取模型列表失败: {e}")
        return []

    # ── 核心：自然语言 → 命令 ────────────────────

    def parse_command(self, user_input: str) -> ParsedCommand:
        """
        将用户自然语言输入解析为结构化命令。
        :param user_input: 用户输入文本
        :return: ParsedCommand 对象
        """
        # 加入用户消息到历史
        self._history.append(ChatMessage(role="user", content=user_input))

        # 调用 Ollama
        raw_response = self._chat(self._history)

        # 加入助手回复到历史
        self._history.append(ChatMessage(role="assistant", content=raw_response))

        # 从回复中提取 JSON 命令
        return self._extract_command(raw_response)

    def chat(self, user_input: str) -> str:
        """
        纯对话模式（不强制解析为命令）。
        用于闲聊、问答等场景。
        :param user_input: 用户输入
        :return: 模型回复文本
        """
        self._history.append(ChatMessage(role="user", content=user_input))
        raw_response = self._chat(self._history)
        self._history.append(ChatMessage(role="assistant", content=raw_response))
        return raw_response

    def stream_chat(self, user_input: str, on_chunk: Callable[[str], None]) -> str:
        """
        流式对话 - 逐 token 回调，适合 CLI 场景。
        :param user_input: 用户输入
        :param on_chunk: 每收到一个 token 片段时调用
        :return: 完整的模型回复
        """
        self._history.append(ChatMessage(role="user", content=user_input))

        full_response = self._stream_chat(self._history, on_chunk)

        self._history.append(ChatMessage(role="assistant", content=full_response))
        return full_response

    # ── 对话历史管理 ────────────────────────────

    def clear_history(self) -> None:
        """清空对话历史（保留 system prompt）"""
        self._history = [self._history[0]]

    def get_history(self) -> List[ChatMessage]:
        """获取对话历史"""
        return list(self._history)

    # ── 内部实现 ────────────────────────────────

    def _chat(self, messages: List[ChatMessage]) -> str:
        """非流式调用 Ollama Chat API"""
        client = self._get_client()
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
            },
        }

        try:
            resp = client.post("/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except httpx.TimeoutException:
            return "[错误] Ollama 请求超时，请检查服务状态。"
        except httpx.ConnectError:
            return "[错误] 无法连接到 Ollama 服务，请确认服务已启动。"
        except Exception as e:
            return f"[错误] Ollama 调用失败: {e}"

    def _stream_chat(self, messages: List[ChatMessage], on_chunk: Callable[[str], None]) -> str:
        """流式调用 Ollama Chat API"""
        client = self._get_client()
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
            },
        }

        full_response = ""
        try:
            with client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk_data = json.loads(line)
                        token = chunk_data.get("message", {}).get("content", "")
                        if token:
                            full_response += token
                            on_chunk(token)
                    except json.JSONDecodeError:
                        continue
        except httpx.TimeoutException:
            full_response = "[错误] Ollama 流式请求超时。"
        except httpx.ConnectError:
            full_response = "[错误] 无法连接到 Ollama 服务。"
        except Exception as e:
            full_response = f"[错误] Ollama 流式调用失败: {e}"

        return full_response

    @staticmethod
    def _extract_command(response: str) -> ParsedCommand:
        """
        从模型回复中提取 JSON 格式的命令。
        支持直接 JSON 和 markdown 代码块包裹两种格式。
        """
        # 尝试直接解析 JSON
        try:
            data = json.loads(response)
            return ParsedCommand(
                command=data.get("command", ""),
                params=data.get("params", {}),
                raw_response=response,
            )
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取 JSON
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return ParsedCommand(
                    command=data.get("command", ""),
                    params=data.get("params", {}),
                    raw_response=response,
                )
            except json.JSONDecodeError:
                pass

        # 尝试从回复中查找第一个 {...} 块
        brace_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if brace_match:
            try:
                data = json.loads(brace_match.group())
                return ParsedCommand(
                    command=data.get("command", ""),
                    params=data.get("params", {}),
                    raw_response=response,
                )
            except json.JSONDecodeError:
                pass

        # 无法解析，返回原始回复作为闲聊
        return ParsedCommand(
            command="chat",
            params={"message": response},
            raw_response=response,
        )
