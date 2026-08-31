#!/usr/bin/env python3
"""Loopback-only health, warm-up, and structured-output probes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from runtime_lock import DEFAULT_LOCK, load_lock


class ProbeError(RuntimeError):
    pass


def _loopback_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProbeError(f"yalnız loopback http URL kabul edilir: {url}")
    if parsed.username or parsed.password:
        raise ProbeError("URL içinde kimlik bilgisi kabul edilmez")


def _headers() -> dict[str, str]:
    result = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.environ.get("ENRO_LLM_API_KEY", "")
    if api_key:
        result["Authorization"] = f"Bearer {api_key}"
    return result


def request_json(
    url: str,
    *,
    timeout: float,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    _loopback_url(url)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    method = "GET" if payload is None else "POST"
    request = urllib.request.Request(url, data=body, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise ProbeError(f"HTTP {exc.code}: {detail}") from exc
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise ProbeError(str(exc)) from exc
    try:
        decoded = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise ProbeError(f"JSON olmayan yanıt: {raw[:200]!r}") from exc
    if not isinstance(decoded, dict):
        raise ProbeError("JSON object yanıt bekleniyordu")
    return status, decoded


def completion_payload(model: str, user_text: str, *, structured: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Sen ENRO oyununun dar kapsamlı Türkçe olay çıkarıcısısın. "
                    "deliver, bir cismi ana masaya götürme isteğidir. Renkleri "
                    "blue, green, red olarak yaz. Görev yoksa operation ve color "
                    "alanlarını none yap. Yalnız istenen yapılandırılmış yanıtı üret."
                ),
            },
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 64,
        "stream": False,
    }
    if structured:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "enro_runtime_probe",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["deliver", "none"],
                        },
                        "color": {
                            "type": "string",
                            "enum": ["blue", "green", "red", "none"],
                        },
                    },
                    "required": ["operation", "color"],
                },
            },
        }
    return payload


def _assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProbeError("chat completion choices bulunamadı")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProbeError("assistant message bulunamadı")
    content = message.get("content")
    if not isinstance(content, str):
        raise ProbeError("assistant content string değil")
    leaked_reasoning = message.get("reasoning_content")
    if leaked_reasoning not in {None, ""} or "<think" in content.lower() or "</think" in content.lower():
        raise ProbeError("reasoning/thinking çıktıya sızdı")
    return message


def health(url: str, timeout: float) -> None:
    status, body = request_json(url, timeout=timeout)
    if status != 200:
        raise ProbeError(f"health HTTP status={status}")
    state = body.get("status")
    if state not in {None, "ok"}:
        raise ProbeError(f"sunucu henüz hazır değil: status={state!r}")


def warmup(base_url: str, model: str, timeout: float) -> None:
    _, response = request_json(
        f"{base_url}/chat/completions",
        timeout=timeout,
        payload=completion_payload(model, "Merhaba. Görev istemiyorum.", structured=False),
    )
    _assistant_message(response)


def live_eval(base_url: str, model: str, timeout: float, quiet: bool) -> None:
    cases = (
        ("mavi cismi ana masaya götür", {"operation": "deliver", "color": "blue"}),
        ("yeşl objeyi masaya getirr lütfen", {"operation": "deliver", "color": "green"}),
        ("krımızı şeyi ana maasya koy", {"operation": "deliver", "color": "red"}),
        ("merhaba, bugün nasılsın?", {"operation": "none", "color": "none"}),
    )
    for utterance, expected in cases:
        _, response = request_json(
            f"{base_url}/chat/completions",
            timeout=timeout,
            payload=completion_payload(model, utterance, structured=True),
        )
        message = _assistant_message(response)
        try:
            actual = json.loads(message["content"])
        except json.JSONDecodeError as exc:
            raise ProbeError(f"schema probe JSON değil: {message['content']!r}") from exc
        if actual != expected:
            raise ProbeError(
                f"semantik probe başarısız: {utterance!r}; beklenen={expected!r}; gelen={actual!r}"
            )
        if not quiet:
            print(f"OK: {utterance!r} -> {actual}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--quiet", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("health", "warmup", "live-eval"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--timeout", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        lock = load_lock(args.lock.resolve())
        server = lock["server"]
        health_url = f"http://{server['host']}:{server['port']}{server['health_path']}"
        base_url = f"http://{server['host']}:{server['port']}{server['api_base_path']}"
        if args.command == "health":
            health(health_url, args.timeout or 2.0)
        elif args.command == "warmup":
            warmup(base_url, server["alias"], args.timeout or server["warmup_timeout_seconds"])
        elif args.command == "live-eval":
            live_eval(
                base_url,
                server["alias"],
                args.timeout or server["warmup_timeout_seconds"],
                args.quiet,
            )
        if not args.quiet:
            print(f"OK: {args.command}")
        return 0
    except (ProbeError, ValueError) as exc:
        if not args.quiet:
            print(f"HATA: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

