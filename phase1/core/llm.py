"""
大模型集成模块 - 支持本地 llama-cpp-python 推理 和 Ollama 服务
功能：
  - LocalLLMClient: 纯 Python 本地推理（无需 Ollama 服务）
  - OllamaClient: 通过 Ollama HTTP API 推理（需启动 Ollama 服务）
  - 将用户自然语言转换为结构化控制命令
  - 支持流式输出（CLI 对话体验）
  - 对话历史管理
  - 自动下载模型（首次运行时从 ModelScope / HuggingFace 下载）
"""
import json
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from phase1.core.config import LLMConfig


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


# 命令提取专用 prompt —— 独立于对话历史，强制模型只返回 JSON
_COMMAND_EXTRACT_PROMPT = (
    "你是命令解析器。判断用户想执行什么操作，只返回JSON。\n"
    "格式: {\"command\":\"命令名\"}\n"
    "\n"
    "可用命令:\n"
    "discover_network - 扫描局域网摄像头\n"
    "connect_camera - 连接摄像头\n"
    "watch_camera - 连接并拉流预览\n"
    "get_stream - 获取视频流\n"
    "take_photo - 截图\n"
    "open_preview - 打开预览\n"
    "get_status - 查看状态\n"
    "list_cameras - 列出摄像头\n"
    "set_password - 设置密码\n"
    "auto_setup - 自动扫描+连接+拉流\n"
    "\n"
    "闲聊返回: {\"command\":\"chat\"}\n"
    "只返回JSON，不要加任何参数。\n"
)


# ─────────────────────────────────────────────────
#  公共工具
# ─────────────────────────────────────────────────

def _get_params(data: dict) -> dict:
    """从解析的 JSON 中提取参数：有 params 键则用它，否则返回整个 dict（去掉 command）"""
    if "params" in data and isinstance(data["params"], dict):
        return data["params"]
    return {k: v for k, v in data.items() if k != "command"}


def _extract_command(response: str) -> ParsedCommand:
    """从 LLM 回复中提取结构化 JSON 命令（支持嵌套大括号 + 自动修复漏括号）"""
    # 尝试直接解析
    try:
        data = json.loads(response)
        return ParsedCommand(command=data.get("command", ""), params=_get_params(data), raw_response=response)
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown 代码块中提取
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            return ParsedCommand(command=data.get("command", ""), params=_get_params(data), raw_response=response)
        except json.JSONDecodeError:
            pass

    # 查找支持嵌套的 JSON 块（大括号计数法）
    json_str = _extract_nested_json(response)
    if json_str:
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "command" in data:
                return ParsedCommand(command=data["command"], params=_get_params(data), raw_response=response)
        except json.JSONDecodeError:
            pass
        # 尝试自动修复：补齐缺失的右大括号
        opens = json_str.count('{')
        closes = json_str.count('}')
        if opens > closes:
            fixed = json_str + '}' * (opens - closes)
            try:
                data = json.loads(fixed)
                if isinstance(data, dict) and "command" in data:
                    return ParsedCommand(command=data["command"], params=_get_params(data), raw_response=response)
            except json.JSONDecodeError:
                pass

    # 回退：平坦匹配（无嵌套的简单 JSON）
    brace_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
    if brace_match:
        try:
            data = json.loads(brace_match.group())
            cmd = data.get("command", "")
            if cmd:
                return ParsedCommand(command=cmd, params=_get_params(data), raw_response=response)
        except json.JSONDecodeError:
            pass

    return ParsedCommand(command="chat", params={"message": response}, raw_response=response)


def _extract_nested_json(text: str) -> Optional[str]:
    """从文本中提取第一个包含嵌套大括号的 JSON 字符串（大括号计数法）"""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    # 未闭合，返回从 start 到末尾的内容（后续由调用者尝试补齐）
    remainder = text[start:].strip()
    if remainder:
        return remainder
    return None


@staticmethod
def _trim_history(messages: List[ChatMessage], max_turns: int = 10) -> List[ChatMessage]:
    """裁剪对话历史：保留 system prompt + 最近 max_turns 轮对话"""
    if len(messages) <= max_turns + 1:
        return messages
    return [messages[0]] + messages[-(max_turns):]


# ─────────────────────────────────────────────────
#  本地 LLM 客户端 (llama-cpp-python)
# ─────────────────────────────────────────────────

# 默认模型下载源配置
_DEFAULT_HF_REPO = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
_DEFAULT_HF_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
_DEFAULT_MS_REPO = "Qwen/Qwen2.5-0.5B-Instruct-GGUF"


class LocalLLMClient:
    """
    本地 LLM 客户端 - 使用 llama-cpp-python 直接在 Python 中推理。
    无需 Ollama 等外部服务，在 PyCharm 中一键运行。
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._llm = None  # lazy init
        self._history: List[ChatMessage] = []
        self._history.append(ChatMessage(role="system", content=config.system_prompt))

    def _ensure_model(self):
        """确保模型已加载（懒加载 + 自动下载）"""
        if self._llm is not None:
            return

        from llama_cpp import Llama

        model_path = self.config.model_path

        # 1. 如果指定了本地路径且文件存在，直接加载
        if model_path and os.path.isfile(model_path):
            print(f"[LLM] 加载本地模型: {model_path}")
            self._llm = Llama(
                model_path=model_path,
                n_ctx=1024,
                n_threads=4,
                verbose=False,
                chat_format="qwen",
            )
            return

        # 2. 自动下载
        downloaded = self._auto_download()
        if downloaded:
            print(f"[LLM] 加载本地模型: {downloaded}")
            self._llm = Llama(
                model_path=downloaded,
                n_ctx=1024,
                n_threads=4,
                verbose=False,
                chat_format="qwen",
            )
            return

        raise FileNotFoundError(
            f"模型文件未找到。\n"
            f"  期望路径: {model_path}\n"
            f"  请手动下载 GGUF 模型文件放到该路径。\n"
            f"  下载地址: https://hf-mirror.com/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        )

    def _auto_download(self) -> Optional[str]:
        """自动下载模型，依次尝试 ModelScope → HuggingFace 镜像 → 直接下载"""
        model_dir = "D:\\OllamaModels"
        os.makedirs(model_dir, exist_ok=True)
        target = os.path.join(model_dir, "qwen2.5-0.5b-instruct-q4_k_m.gguf")

        if os.path.isfile(target) and os.path.getsize(target) > 100_000:
            return target

        print("[LLM] 首次运行，正在自动下载模型（约 400MB，请耐心等待）...")

        # ── 方法 1: 直接 URL 下载（最可靠） ──
        urls = [
            f"https://hf-mirror.com/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
            f"https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        ]
        for url in urls:
            try:
                print(f"[LLM] 正在从 {url[:60]}... 下载")
                return self._download_file(url, target)
            except Exception as e:
                print(f"[LLM] 下载失败: {e}")
                continue

        # ── 方法 2: ModelScope SDK ──
        try:
            import ssl as _ssl
            _ssl._create_default_https_context = _ssl._create_unverified_context
            from modelscope import snapshot_download
            model_dir_ms = snapshot_download(_DEFAULT_MS_REPO, cache_dir="D:\\OllamaModels")
            # 在下载的目录中查找 GGUF 文件
            for f in Path(model_dir_ms).rglob("*.gguf"):
                return str(f)
        except Exception:
            pass

        # ── 方法 3: huggingface_hub with mirror ──
        try:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            from huggingface_hub import hf_hub_download
            return hf_hub_download(
                repo_id=_DEFAULT_HF_REPO,
                filename=_DEFAULT_HF_FILE,
                local_dir="D:/OllamaModels",
            )
        except Exception:
            pass

        return None

    @staticmethod
    def _download_file(url: str, dest: str) -> str:
        """带进度显示的文件下载"""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers={"User-Agent": "AgenticCameraControl/1.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            tmp_path = dest + ".tmp"

            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded / total * 100
                        mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        print(f"\r[LLM] 下载进度: {mb:.1f}/{total_mb:.1f} MB ({pct:.0f}%)", end="", flush=True)

            print()  # 换行
            os.replace(tmp_path, dest)
            print(f"[LLM] 模型已保存: {dest}")
            return dest

    # ── 公共接口 ──

    def close(self) -> None:
        self._llm = None

    def extract_command(self, user_input: str, context: str = "") -> ParsedCommand:
        """独立的命令提取调用：不污染对话历史，用专用 prompt 强制输出 JSON"""
        self._ensure_model()
        content = f"{context}\n用户：{user_input}" if context else user_input
        messages = [
            {"role": "system", "content": _COMMAND_EXTRACT_PROMPT},
            {"role": "user", "content": content},
        ]
        try:
            response = self._llm.create_chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=64,
            )
            raw = response["choices"][0]["message"]["content"]
            return _extract_command(raw)
        except Exception as e:
            return ParsedCommand(command="chat", params={"error": str(e)})

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

    # 兼容 OllamaClient 的 _extract_command 引用
    @staticmethod
    def _extract_command(response: str) -> ParsedCommand:
        return _extract_command(response)

    # ── 内部推理 ──

    def _chat(self, messages: List[ChatMessage]) -> str:
        try:
            self._ensure_model()
            trimmed = _trim_history(messages)
            msg_list = [{"role": m.role, "content": m.content} for m in trimmed]
            response = self._llm.create_chat_completion(
                messages=msg_list,
                temperature=self.config.temperature,
                max_tokens=256,
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
                messages=msg_list,
                temperature=self.config.temperature,
                max_tokens=256,
                stream=True,
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
#  Ollama 客户端 (保留兼容，需启动 Ollama 服务)
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
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def extract_command(self, user_input: str, context: str = "") -> ParsedCommand:
        """独立的命令提取调用：不污染对话历史，用专用 prompt 强制输出 JSON"""
        client = self._get_client()
        content = f"{context}\n用户：{user_input}" if context else user_input
        messages = [
            {"role": "system", "content": _COMMAND_EXTRACT_PROMPT},
            {"role": "user", "content": content},
        ]
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 512, "num_predict": 64},
        }
        try:
            resp = client.post("/api/chat", json=payload)
            if resp.status_code != 200:
                return ParsedCommand(command="chat", params={"error": f"HTTP {resp.status_code}"})
            data = resp.json()
            raw = data.get("message", {}).get("content", "")
            return _extract_command(raw)
        except Exception as e:
            return ParsedCommand(command="chat", params={"error": str(e)})

    def is_available(self) -> bool:
        try:
            client = self._get_client()
            resp = client.get("/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            client = self._get_client()
            resp = client.get("/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            print(f"[LLM] 获取模型列表失败: {e}")
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
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": 1024,
                "num_predict": 256,
            },
        }
        try:
            resp = client.post("/api/chat", json=payload)
            if resp.status_code != 200:
                return self._format_ollama_error(resp.status_code, resp.text)
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except self._httpx.TimeoutException:
            return "[错误] Ollama 请求超时，请检查服务状态。"
        except self._httpx.ConnectError:
            return "[错误] 无法连接到 Ollama 服务，请确认服务已启动。"
        except Exception as e:
            return f"[错误] Ollama 调用失败: {e}"

    @staticmethod
    def _format_ollama_error(status_code: int, body: str) -> str:
        error_msg = ""
        try:
            data = json.loads(body)
            error_msg = data.get("error", body)
        except (json.JSONDecodeError, ValueError):
            error_msg = body[:300]
        if status_code == 404:
            return (
                f"[错误] 模型未找到 (404)。\n"
                f"  详情: {error_msg}\n"
                f"  请运行 `ollama pull <模型名>` 下载模型。"
            )
        elif status_code == 500:
            return f"[错误] Ollama 内部错误 (500): {error_msg}"
        elif status_code == 503:
            return f"[错误] 模型服务暂不可用 (503): {error_msg}"
        return f"[错误] Ollama 返回 {status_code}: {error_msg}"

    def _stream_chat(self, messages: List[ChatMessage], on_chunk: Callable[[str], None]) -> str:
        client = self._get_client()
        trimmed = _trim_history(messages)
        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in trimmed],
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": 1024,
                "num_predict": 256,
            },
        }
        full_response = ""
        try:
            with client.stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    error_body = b""
                    for chunk in resp.iter_bytes():
                        error_body += chunk
                        if len(error_body) > 2000:
                            break
                    error_text = error_body.decode("utf-8", errors="ignore")
                    return self._format_ollama_error(resp.status_code, error_text)
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
        except self._httpx.TimeoutException:
            full_response = "[错误] Ollama 流式请求超时。"
        except self._httpx.ConnectError:
            full_response = "[错误] 无法连接到 Ollama 服务。"
        except Exception as e:
            full_response = f"[错误] Ollama 流式调用失败: {e}"
        return full_response
