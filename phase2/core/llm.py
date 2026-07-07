"""
phase2 - 大模型集成模块 - 支持本地 llama-cpp-python 推理和 Ollama 服务
"""
import json
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from phase2.core.config import LLMConfig


@dataclass
class ParsedCommand:
    """大模型解析出的结构化命令"""
    command: str
    params: Dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""
    confidence: float = 1.0

    @property
    def is_valid(self) -> bool:
        return bool(self.command)


@dataclass
class ChatMessage:
    """单条对话消息"""
    role: str       # "system" | "user" | "assistant"
    content: str


# ─────────────────────────────────────────────────
#  公共工具
# ─────────────────────────────────────────────────

def _extract_command(response: str) -> ParsedCommand:
    """从 LLM 回复中提取结构化 JSON 命令"""
    try:
        data = json.loads(response)
        return ParsedCommand(command=data.get("command", ""), params=data.get("params", {}), raw_response=response)
    except json.JSONDecodeError:
        pass
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            return ParsedCommand(command=data.get("command", ""), params=data.get("params", {}), raw_response=response)
        except json.JSONDecodeError:
            pass
    brace_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
    if brace_match:
        try:
            data = json.loads(brace_match.group())
            return ParsedCommand(command=data.get("command", ""), params=data.get("params", {}), raw_response=response)
        except json.JSONDecodeError:
            pass
    return ParsedCommand(command="chat", params={"message": response}, raw_response=response)


def _trim_history(messages: List[ChatMessage], max_turns: int = 10) -> List[ChatMessage]:
    """裁剪对话历史"""
    if len(messages) <= max_turns + 1:
        return messages
    return [messages[0]] + messages[-(max_turns):]


# ─────────────────────────────────────────────────
#  本地 LLM 客户端 (llama-cpp-python)
# ─────────────────────────────────────────────────

class LocalLLMClient:
    """本地 LLM 客户端 - llama-cpp-python 直接推理，无需外部服务。"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._llm = None
        self._history: List[ChatMessage] = []
        self._history.append(ChatMessage(role="system", content=config.system_prompt))

    def _ensure_model(self):
        if self._llm is not None:
            return
        from llama_cpp import Llama
        model_path = self.config.model_path
        if model_path and os.path.isfile(model_path):
            print(f"[LLM] 加载本地模型: {model_path}")
            self._llm = Llama(
                model_path=model_path, n_ctx=1024, n_threads=4,
                verbose=False, chat_format="qwen",
            )
            return
        raise FileNotFoundError(f"模型文件未找到: {model_path}")

    def close(self) -> None:
        self._llm = None

    def is_available(self) -> bool:
        try:
            self._ensure_model()
            return self._llm is not None
        except Exception:
            return False

    def list_models(self) -> List[str]:
        name = Path(self.config.model_path).name if self.config.model_path else "unknown"
        status = "已加载" if self._llm is not None else "未加载"
        return [f"{name} ({status})"]

    def parse_command(self, user_input: str) -> ParsedCommand:
        self._history.append(ChatMessage(role="user", content=user_input))
        raw_response = self._chat(self._history)
        self._history.append(ChatMessage(role="assistant", content=raw_response))
        return _extract_command(raw_response)

    def chat(self, user_input: str) -> str:
        self._history.append(ChatMessage(role="user", content=user_input))
        raw_response = self._chat(self._history)
        self._history.append(ChatMessage(role="assistant", content=raw_response))
        return raw_response

    def stream_chat(self, user_input: str, on_chunk: Callable[[str], None]) -> str:
        self._history.append(ChatMessage(role="user", content=user_input))
        full_response = self._stream_chat(self._history, on_chunk)
        self._history.append(ChatMessage(role="assistant", content=full_response))
        return full_response

    def clear_history(self) -> None:
        self._history = [self._history[0]]

    def get_history(self) -> List[ChatMessage]:
        return list(self._history)

    @staticmethod
    def _extract_command(response: str) -> ParsedCommand:
        return _extract_command(response)

    def _chat(self, messages: List[ChatMessage]) -> str:
        try:
            self._ensure_model()
            trimmed = _trim_history(messages)
            msg_list = [{"role": m.role, "content": m.content} for m in trimmed]
            response = self._llm.create_chat_completion(
                messages=msg_list, temperature=self.config.temperature, max_tokens=256,
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[错误] 本地 LLM 推理失败: {e}"

    def _stream_chat(self, messages: List[ChatMessage], on_chunk: Callable[[str], None]) -> str:
        full_response = ""
        try:
            self._ensure_model()
            trimmed = _trim_history(messages)
            msg_list = [{"role": m.role, "content": m.content} for m in trimmed]
            stream = self._llm.create_chat_completion(
                messages=msg_list, temperature=self.config.temperature,
                max_tokens=256, stream=True,
            )
            for chunk in stream:
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_response += content
                    on_chunk(content)
        except Exception as e:
            if not full_response:
                full_response = f"[错误] 本地 LLM 流式推理失败: {e}"
        return full_response


# ─────────────────────────────────────────────────
#  Ollama 客户端 (保留兼容)
# ─────────────────────────────────────────────────

class OllamaClient:
    """Ollama 大模型客户端（需启动 Ollama 服务）。"""

    def __init__(self, config: LLMConfig):
        import httpx
        self._httpx = httpx
        self.config = config
        self._history: List[ChatMessage] = []
        self._client = None
        self._history.append(ChatMessage(role="system", content=config.system_prompt))

    def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = self._httpx.Client(
                base_url=self.config.base_url, timeout=self.config.timeout,
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def is_available(self) -> bool:
        try:
            client = self._get_client()
            return client.get("/api/tags").status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            client = self._get_client()
            resp = client.get("/api/tags")
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    def parse_command(self, user_input: str) -> ParsedCommand:
        self._history.append(ChatMessage(role="user", content=user_input))
        raw_response = self._chat(self._history)
        self._history.append(ChatMessage(role="assistant", content=raw_response))
        return _extract_command(raw_response)

    def chat(self, user_input: str) -> str:
        self._history.append(ChatMessage(role="user", content=user_input))
        raw_response = self._chat(self._history)
        self._history.append(ChatMessage(role="assistant", content=raw_response))
        return raw_response

    def stream_chat(self, user_input: str, on_chunk: Callable[[str], None]) -> str:
        self._history.append(ChatMessage(role="user", content=user_input))
        full_response = self._stream_chat(self._history, on_chunk)
        self._history.append(ChatMessage(role="assistant", content=full_response))
        return full_response

    def clear_history(self) -> None:
        self._history = [self._history[0]]

    def get_history(self) -> List[ChatMessage]:
        return list(self._history)

    @staticmethod
    def _extract_command(response: str) -> ParsedCommand:
        return _extract_command(response)

    def _chat(self, messages: List[ChatMessage]) -> str:
        client = self._get_client()
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": self.config.temperature, "num_ctx": 1024, "num_predict": 256},
        }
        try:
            resp = client.post("/api/chat", json=payload)
            if resp.status_code != 200:
                return f"[错误] Ollama 返回 {resp.status_code}: {resp.text[:200]}"
            return resp.json().get("message", {}).get("content", "")
        except Exception as e:
            return f"[错误] Ollama 调用失败: {e}"

    def _stream_chat(self, messages: List[ChatMessage], on_chunk: Callable[[str], None]) -> str:
        client = self._get_client()
        trimmed = _trim_history(messages)
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in trimmed],
            "stream": True,
            "options": {"temperature": self.config.temperature, "num_ctx": 1024, "num_predict": 256},
        }
        full_response = ""
        try:
            with client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    return f"[错误] Ollama 返回 {resp.status_code}"
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        token = json.loads(line).get("message", {}).get("content", "")
                        if token:
                            full_response += token
                            on_chunk(token)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            if not full_response:
                full_response = f"[错误] Ollama 流式调用失败: {e}"
        return full_response
