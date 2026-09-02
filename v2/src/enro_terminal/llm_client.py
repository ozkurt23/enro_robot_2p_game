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
                raw_bytes = response.read()
        except (error.URLError, error.HTTPError, TimeoutError, socket.timeout, OSError) as exc:
            raise LlmUnavailable(f"yerel model sunucusuna erişilemedi: {exc}") from exc
        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LlmProtocolError("model sunucusu UTF-8 olmayan yanıt döndürdü") from exc
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise LlmProtocolError("model sunucusu JSON olmayan yanıt döndürdü") from exc

    def health(self) -> bool:
        result = self._call("/health")
        if not isinstance(result, Mapping):
            return False
        status = result.get("status")
        return isinstance(status, str) and status in {"ok", "ready"}

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
        if not isinstance(result, Mapping):
            raise LlmProtocolError("chat completion yanıtı nesne olmalı")
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmProtocolError("chat completion choices alanı eksik")
        first = choices[0]
        if not isinstance(first, Mapping) or not isinstance(first.get("message"), Mapping):
            raise LlmProtocolError("chat completion message alanı eksik")
        content = first["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise LlmProtocolError("model boş yanıt döndürdü")
        return strip_reasoning(content)


def strip_reasoning(content: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
    value = re.sub(r"^<think>.*$", "", value, flags=re.DOTALL | re.IGNORECASE).strip()
    if not value:
        raise LlmProtocolError("model yalnız düşünme metni döndürdü")
    return value


def _strict_json_loads(value: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise LlmProtocolError(f"model JSON yanıtında yinelenen alan var: {key}")
            result[key] = item
        return result

    def reject_non_finite(value: str) -> None:
        raise LlmProtocolError(f"model JSON yanıtında geçersiz sayı var: {value}")

    return json.loads(
        value,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_non_finite,
    )


def extract_json_object(content: str, *, strict: bool = False) -> Mapping[str, Any]:
    """Extract one model-produced JSON object.

    ``strict=True`` is intended for action-adjacent structured output.  It
    accepts either a bare object or a single Markdown JSON fence, but rejects
    prose wrappers, duplicate keys and non-finite numbers.  The default keeps
    the historical best-effort extraction used by non-action dialogue code.
    """

    if not isinstance(content, str):
        raise LlmProtocolError("model yanıtı metin olmalı")
    value = content.strip()
    fence = chr(96) * 3
    if value.startswith(fence):
        match = re.fullmatch(
            r"```(?:json)?[ \t]*\r?\n(?P<body>.*?)\r?\n?```",
            value,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if match is not None:
            value = match.group("body").strip()
        elif strict:
            raise LlmProtocolError("modelin JSON kod bloğu geçersiz")
    try:
        result = _strict_json_loads(value) if strict else json.loads(value)
    except (json.JSONDecodeError, RecursionError):
        if strict:
            raise LlmProtocolError("model yanıtı yalnız bir JSON nesnesi olmalı")
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise LlmProtocolError("model yanıtında JSON nesnesi bulunamadı")
        try:
            result = json.loads(value[start:end + 1])
        except (json.JSONDecodeError, RecursionError) as exc:
            raise LlmProtocolError("modelin JSON nesnesi ayrıştırılamadı") from exc
    if not isinstance(result, Mapping):
        raise LlmProtocolError("model yanıtı JSON nesnesi olmalı")
    return result
