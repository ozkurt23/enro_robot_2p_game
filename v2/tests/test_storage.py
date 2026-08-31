"""Durable JSONL logging and atomic current-state snapshot checks."""

from __future__ import annotations

import json

from enro_terminal.dialogue import CanonicalActor
from enro_terminal.executor import MockExecutor
from enro_terminal.game import TerminalGame
from enro_terminal.nlu import RuleNlu
from enro_terminal.storage import SessionStore
from enro_terminal.types import PersonaId


def test_game_persists_versioned_event_and_current_state(tmp_path):
    store = SessionStore(tmp_path, session_id="test-session")
    game = TerminalGame(
        persona=PersonaId.SAKAR,
        nlu=RuleNlu(),
        actor=CanonicalActor(),
        executor=MockExecutor(),
        store=store,
        seed=180,
        clock=lambda: 42.0,
    )

    game.process("Mavi cismi ana masaya getir.")
    game.process("Evet, onaylıyorum.")

    event_lines = store.events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 2
    event = json.loads(event_lines[-1])
    assert event["schema_version"] == 1
    assert event["session_id"] == "test-session"
    assert event["event_type"] == "TURN_DECISION"
    assert event["payload"]["decision"]["outcome"] == "accept"
    assert event["payload"]["round_state"]["completed"] == ["blue"]

    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    assert state["schema_version"] == 1
    assert state["session_id"] == "test-session"
    assert state["seed"] == 180
    assert state["gameplay_id"] == "festival"
    assert state["persona"] == "sakar"
    assert state["nlu_backend"] == "rules-test"
    assert state["round_state"]["completed"] == ["blue"]
    assert list(store.runtime_dir.glob("*.tmp")) == []
