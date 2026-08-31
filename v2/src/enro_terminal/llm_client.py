"""Small stdlib client for a loopback llama.cpp OpenAI-compatible server."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import socket
from typing import Any, Mapping, Sequence
from urllib import error, request


class LlmError(RuntimeError):
    pass


class LlmUnavailable(LlmError):
    pass


class LlmProtocolError(LlmError):
    pass


@dataclass(frozen=True, slots=True)
class LlamaCppConfig:
    base_url: str = "http://127.0.0.1:18080"
    model: str = "enro-qwen35-9b-q4km"
    timeout_seconds: float = 25.0
    api_key: str | None = None

    @classmethod
    def from_environment(cls, **overrides: Any) -> "LlamaCppConfig":
        defaults = cls()
        values: dict[str, Any] = {
            "base_url": os.environ.get("ENRO_LLM_URL", defaults.base_url),
            "model": os.environ.get("ENRO_LLM_MODEL", defaults.model),
            "timeout_seconds": float(os.environ.get("ENRO_LLM_TIMEOUT", defaults.timeout_seconds)),
            "api_key": os.environ.get("ENRO_LLM_API_KEY"),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)


class LlamaCppClient:
    def __init__(self, config: LlamaCppConfig | None = None) -> None:
        self.config = config or LlamaCppConfig.from_environment()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _call(self, path: str, *, method: str = "GET", payload: Mapping[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.config.base_url.rstrip("/") + path,
            data=body,
            headers=self._headers(),
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except (error.URLError, error.HTTPError, TimeoutError, socket.timeout) as exc:
            raise LlmUnavailable(f"yerel model sunucusuna erişilemedi: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlmProtocolError("model sunucusu JSON olmayan yanıt döndürdü") from exc

    def health(self) -> bool:
        result = self._call("/health")
        return isinstance(result, Mapping) and result.get("status") in {"ok", "ready"}

    def model_ids(self) -> tuple[str, ...]:
        result = self._call("/v1/models")
        if not isinstance(result, Mapping) or not isinstance(result.get("data"), list):
            raise LlmProtocolError("/v1/models yanıtı geçersiz")
        return tuple(str(item.get("id")) for item in result["data"] if isinstance(item, Mapping))

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        seed: int,
        response_format: Mapping[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "seed": seed,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if response_format is not None:
            payload["response_format"] = response_format
        result = self._call("/v1/chat/completions", method="POST", payload=payload)
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmProtocolError("chat completion alanları eksik") from exc
        if not isinstance(content, str) or not content.strip():
            raise LlmProtocolError("model boş yanıt döndürdü")
        return strip_reasoning(content)


def strip_reasoning(content: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
    value = re.sub(r"^<think>.*$", "", value, flags=re.DOTALL | re.IGNORECASE).strip()
    if not value:
        raise LlmProtocolError("model yalnız düşünme metni döndürdü")
    return value


def extract_json_object(content: str) -> Mapping[str, Any]:
    value = content.strip()
    fence = chr(96) * 3
    if value.startswith(fence):
        first_newline = value.find("\n")
        last_fence = value.rfind(fence)
        if first_newline >= 0 and last_fence > first_newline:
            value = value[first_newline + 1:last_fence].strip()
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise LlmProtocolError("model yanıtında JSON nesnesi bulunamadı")
        try:
            result = json.loads(value[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LlmProtocolError("modelin JSON nesnesi ayrıştırılamadı") from exc
    if not isinstance(result, Mapping):
        raise LlmProtocolError("model yanıtı JSON nesnesi olmalı")
    return result
