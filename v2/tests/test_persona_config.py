"""Bundled persona configuration is strict and safe to expose selectively."""

from __future__ import annotations

from copy import deepcopy
from importlib import resources
import json
import tomllib

import pytest

from enro_terminal import cli
from enro_terminal.dialogue import QwenPersonaActor, _MOTION_WORDS
from enro_terminal.executor import _MOTION_TURKISH
from enro_terminal.game import _MOTION_AUTHORITY, _MOTION_OWNERS
from enro_terminal.nlu import NluContext, RuleNlu
from enro_terminal.persona_config import (
    PersonaConfigError,
    load_persona_catalog,
    load_persona_config,
    new_persona_state,
    parse_persona_config,
)
from enro_terminal.types import (
    ActionKind,
    Decision,
    DecisionOutcome,
    PersonaId,
    PersonaState,
    RoundState,
    SpecialConcept,
)


EXPECTED_NAMES = {
    PersonaId.LEYDI_SERVO: "Leydi Servo",
    PersonaId.SAMURAY: "Samuray",
    PersonaId.SAKAR: "Sakar",
    PersonaId.NESELI: "Neşeli",
    PersonaId.MERAKLI: "Meraklı",
    PersonaId.UYKUCU: "Uykucu",
    PersonaId.TITIZ: "Titiz",
}


def test_complete_catalog_is_loaded_and_cross_checked_atomically():
    catalog = load_persona_catalog()

    assert set(catalog) == set(PersonaId)
    discovery_ids = [
        egg.discovery_id
        for config in catalog.values()
        for egg in config.easter_eggs.values()
    ]
    assert len(discovery_ids) == len(set(discovery_ids))


def test_persona_egg_actions_match_the_engine_motion_allowlists():
    catalog = load_persona_catalog()
    motion_kinds = set(ActionKind) - {ActionKind.DELIVER_OBJECT}

    assert set(_MOTION_AUTHORITY) == motion_kinds
    assert set(_MOTION_OWNERS) == motion_kinds
    assert set(_MOTION_TURKISH) == motion_kinds
    assert set(_MOTION_WORDS) == motion_kinds

    configured: dict[ActionKind, tuple[PersonaId, SpecialConcept]] = {}
    for persona, config in catalog.items():
        for egg in config.easter_eggs.values():
            if egg.action is not None:
                configured[egg.action] = (persona, egg.concept)

    assert set(configured) == motion_kinds
    for action, (persona, concept) in configured.items():
        assert _MOTION_OWNERS[action] is persona
        assert _MOTION_AUTHORITY[action] is concept


def _document(persona: PersonaId) -> dict[str, object]:
    text = resources.files("enro_terminal").joinpath(
        "persona_configs", f"{persona.value}.toml"
    ).read_text(encoding="utf-8")
    return tomllib.loads(text)


class StubClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[object, dict[str, object]]] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.content


@pytest.mark.parametrize("persona", tuple(PersonaId))
def test_all_bundled_persona_configs_are_typed_and_use_requested_names(persona):
    config = load_persona_config(persona)

    assert config.schema_version == 1
    assert config.persona_id is persona
    assert config.display_name == EXPECTED_NAMES[persona]
    assert config.opening
    assert 1 <= config.voice.max_sentences <= 3
    assert config.conversation.allowed_topics
    assert len(config.hints) == 4
    if persona in {PersonaId.LEYDI_SERVO, PersonaId.SAMURAY, PersonaId.SAKAR}:
        assert config.easter_eggs
    else:
        # Yeni kolay personalara fiziksel motion/effect yetkisi sırf şemayı
        # doldurmak için uydurulmaz.
        assert not config.easter_eggs

    with pytest.raises(TypeError):
        config.lore["worldview"] = "değiştir"  # type: ignore[index]


@pytest.mark.parametrize("persona", tuple(PersonaId))
def test_runtime_state_uses_validated_config_defaults(persona):
    config = load_persona_config(persona)
    state = new_persona_state(persona)

    assert state.persona is persona
    for key, expected in config.state_defaults.items():
        assert getattr(state, key) == expected


@pytest.mark.parametrize("persona", tuple(PersonaId))
def test_actor_bible_excludes_progressive_hints_and_easter_egg_payloads(persona):
    config = load_persona_config(persona)
    bible = config.actor_bible

    assert config.voice.role in bible
    assert config.lore["worldview"] in bible
    assert config.conversation.identity_fact in bible
    for hint in config.hints:
        assert hint not in bible
    for egg in config.easter_eggs.values():
        assert egg.discovery_id not in bible
        if egg.hint:
            assert egg.hint not in bible
        if egg.bonus:
            assert egg.bonus not in bible
        if egg.action:
            assert egg.action.value not in bible
        if egg.effect:
            assert egg.effect not in bible


def test_samuray_actor_uses_config_bible_and_config_sentence_ceiling():
    client = StubClient('{"utterance":"Bir. İki. Üç. Dört."}')
    actor = QwenPersonaActor(client, seed=180)
    state = PersonaState(PersonaId.SAMURAY)
    round_state = RoundState()
    event = RuleNlu().parse(
        "Merhaba",
        NluContext(persona_state=state, round_state=round_state),
    )
    decision = Decision(
        outcome=DecisionOutcome.CHAT,
        reason_code="small_talk",
        dialogue_act="chat",
        canonical_reply="Seni dinliyorum.",
        max_sentences=3,
    )

    reply = actor.render(decision, event, state, round_state, ())

    assert reply.used_fallback
    assert "cümle sınırını" in (reply.error or "")
    assert reply.utterance == "Seni dinliyorum."
    messages, _ = client.calls[0]
    system_prompt = messages[0]["content"]
    envelope = json.loads(messages[1]["content"])
    config = load_persona_config(PersonaId.SAMURAY)
    assert config.voice.role in system_prompt
    assert envelope["max_sentences"] == 3
    assert all(hint not in system_prompt for hint in config.hints)
    assert all(egg.discovery_id not in system_prompt for egg in config.easter_eggs.values())


@pytest.mark.parametrize(
    ("mutation", "error_fragment"),
    [
        (lambda doc: doc.update(schema_version=2), "schema_version"),
        (lambda doc: doc.update(schema_version=1.0), "schema_version"),
        (lambda doc: doc.update(unexpected="x"), "fazla=unexpected"),
        (lambda doc: doc["voice"].update(max_sentences="3"), "max_sentences"),
        (lambda doc: doc["hints"].pop("level_3"), "eksik=level_3"),
        (
            lambda doc: doc["conversation"].update(allowed_topics=["not_a_topic"]),
            "bilinmeyen konu",
        ),
        (
            lambda doc: doc["easter_eggs"]["kata"].update(action="motion.unknown"),
            "bilinmeyen hareket",
        ),
    ],
)
def test_malformed_persona_documents_fail_closed(mutation, error_fragment):
    document = deepcopy(_document(PersonaId.SAMURAY))
    mutation(document)

    with pytest.raises(PersonaConfigError, match=error_fragment):
        parse_persona_config(document, expected_persona=PersonaId.SAMURAY)


def test_resource_identity_mismatch_fails_closed():
    document = _document(PersonaId.SAKAR)

    with pytest.raises(PersonaConfigError, match="kaynak leydi_servo"):
        parse_persona_config(document, expected_persona=PersonaId.LEYDI_SERVO)


def test_cli_prints_config_opening_and_display_name(tmp_path, capsys):
    script = tmp_path / "quit.txt"
    script.write_text("/çıkış\n", encoding="utf-8")
    config = load_persona_config(PersonaId.SAKAR)

    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "sakar",
            "--no-store",
            "--script",
            str(script),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert f"Persona      : {config.display_name}" in captured.out
    assert f"{config.display_name.upper()}: {config.opening}" in captured.out


def test_cli_refuses_to_start_when_persona_config_is_invalid(monkeypatch, capsys):
    def invalid_config(_persona):
        raise PersonaConfigError("test şema hatası")

    class NetworkMustNotStart:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("config doğrulanmadan model bağlantısı açılmamalı")

    monkeypatch.setattr(cli, "load_persona_config", invalid_config)
    monkeypatch.setattr(cli, "LlamaCppClient", NetworkMustNotStart)

    exit_code = cli.main(["--backend", "qwen", "--persona", "samuray"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Persona veya gameplay tanımı geçersiz" in captured.err
    assert "test şema hatası" in captured.err
