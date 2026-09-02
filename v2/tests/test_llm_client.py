"""Protocol and transport tests for the dependency-free llama.cpp client."""

from __future__ import annotations

import json
import socket
from urllib import error

import pytest

from enro_terminal import llm_client
from enro_terminal.llm_client import (
    LlamaCppClient,
    LlamaCppConfig,
    LlmProtocolError,
    LlmUnavailable,
    extract_json_object,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body


def test_chat_posts_expected_payload_and_authorization(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["request"] = req
        captured["timeout"] = timeout
        body = {"choices": [{"message": {"content": "<think>gizli</think> tamam"}}]}
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)
    client = LlamaCppClient(
        LlamaCppConfig(
            base_url="http://127.0.0.1:9999/",
            model="local-test",
            timeout_seconds=3.5,
            api_key="secret",
        )
    )

    content = client.chat(
        [{"role": "user", "content": "merhaba"}],
        temperature=0.0,
        max_tokens=99,
        seed=12,
        response_format={"type": "json_object"},
    )

    assert content == "tamam"
    req = captured["request"]
    assert req.full_url == "http://127.0.0.1:9999/v1/chat/completions"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer secret"
    assert captured["timeout"] == 3.5
    payload = json.loads(req.data)
    assert payload["model"] == "local-test"
    assert payload["seed"] == 12
    assert payload["stream"] is False
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    "transport_error",
    [
        error.URLError("kapalı"),
        TimeoutError("geç kaldı"),
        socket.timeout("geç kaldı"),
    ],
)
def test_transport_failures_have_one_public_error_type(monkeypatch, transport_error):
    def fail(*args, **kwargs):
        raise transport_error

    monkeypatch.setattr(llm_client.request, "urlopen", fail)

    with pytest.raises(LlmUnavailable, match="erişilemedi"):
        LlamaCppClient().health()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"\xff\xfe", "UTF-8"),
        (b"this is not json", "JSON olmayan"),
    ],
)
def test_invalid_http_response_encoding_and_json_are_protocol_errors(
    monkeypatch,
    body,
    message,
):
    monkeypatch.setattr(
        llm_client.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(body),
    )

    with pytest.raises(LlmProtocolError, match=message):
        LlamaCppClient().health()


@pytest.mark.parametrize("status", [None, [], {}, 1, True, "starting"])
def test_health_is_false_for_every_non_ready_status(monkeypatch, status):
    monkeypatch.setattr(
        LlamaCppClient,
        "_call",
        lambda *args, **kwargs: {"status": status},
    )

    assert LlamaCppClient().health() is False


@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        {},
        {"choices": None},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "   "}}]},
    ],
)
def test_malformed_chat_envelopes_never_leak_index_or_type_errors(
    monkeypatch,
    result,
):
    monkeypatch.setattr(LlamaCppClient, "_call", lambda *args, **kwargs: result)

    with pytest.raises(LlmProtocolError):
        LlamaCppClient().chat(
            [],
            temperature=0.0,
            max_tokens=10,
            seed=1,
        )


def test_strict_json_accepts_bare_or_fenced_single_object():
    assert extract_json_object('{"ok": true}', strict=True) == {"ok": True}
    assert extract_json_object("```json\n{\"ok\": true}\n```", strict=True) == {
        "ok": True,
    }


@pytest.mark.parametrize(
    "content",
    [
        "önce {\"ok\": true}",
        "{\"ok\": true} sonra",
        "{\"ok\": true}{\"other\": false}",
        "{\"ok\": NaN}",
        "{\"ok\": true, \"ok\": false}",
        "```json\n{\"ok\": true}\n``` trailing",
    ],
)
def test_strict_json_rejects_wrappers_duplicates_and_non_finite_values(content):
    with pytest.raises(LlmProtocolError):
        extract_json_object(content, strict=True)


def test_strict_json_turns_parser_recursion_into_a_protocol_error(monkeypatch):
    def recursive_parser(content):
        raise RecursionError("too deep")

    monkeypatch.setattr(llm_client, "_strict_json_loads", recursive_parser)

    with pytest.raises(LlmProtocolError):
        extract_json_object('{"value": 1}', strict=True)


def test_legacy_json_extraction_remains_available_for_dialogue_text():
    assert extract_json_object("Açıklama: {\"reply\": \"merhaba\"}") == {
        "reply": "merhaba",
    }
