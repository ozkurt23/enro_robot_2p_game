"""Shared fixtures for the terminal MVP tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from enro_terminal.types import TurnEvent


@pytest.fixture
def valid_turn_payload() -> dict[str, object]:
    """Return a minimal, schema-valid model response as a fresh mapping."""

    return {
        "speech_acts": ["task_request"],
        "task": {
            "requested": True,
            "operation": "deliver",
            "colors": ["blue"],
            "destination": "main_table",
            "negated": False,
            "uses_pronoun": False,
            "refers_pending": False,
        },
        "social": {
            "polite": True,
            "direct": True,
            "hedged": False,
            "correct_title": False,
            "thanks": False,
            "apology": False,
            "challenge": False,
            "compliment": False,
            "insult_level": "none",
            "valor_answer": "none",
        },
        "special_candidates": [],
        "chat": {"topic": "none", "question": False},
        "memory_candidates": {"player_name": None},
        "confidence": {
            "overall": 0.99,
            "task": 0.99,
            "colors": 0.99,
            "destination": 0.99,
        },
        "evidence": ["mavi", "ana masa", "getir"],
    }


@pytest.fixture
def payload_copy(valid_turn_payload):
    """Provide a helper so nested mutations never leak between assertions."""

    return lambda: deepcopy(valid_turn_payload)


@pytest.fixture
def event_factory(valid_turn_payload):
    """Build typed policy inputs without involving either NLU backend."""

    def make_event(
        *,
        text: str = "sohbet",
        acts: tuple[str, ...] = ("unknown_chat",),
        requested: bool = False,
        colors: tuple[str, ...] = (),
        destination: str | None = None,
        negated: bool = False,
        uses_pronoun: bool = False,
        refers_pending: bool = False,
        polite: bool = False,
        direct: bool = True,
        hedged: bool = False,
        correct_title: bool = False,
        thanks: bool = False,
        apology: bool = False,
        challenge: bool = False,
        compliment: bool = False,
        insult_level: str = "none",
        valor_answer: str = "none",
        specials: tuple[str, ...] = (),
        overall_confidence: float = 0.99,
        task_confidence: float = 0.99,
        colors_confidence: float | None = None,
        destination_confidence: float | None = None,
    ) -> TurnEvent:
        payload = deepcopy(valid_turn_payload)
        payload["speech_acts"] = list(acts)
        payload["task"] = {
            "requested": requested,
            "operation": "deliver" if requested else "none",
            "colors": list(colors),
            "destination": destination,
            "negated": negated,
            "uses_pronoun": uses_pronoun,
            "refers_pending": refers_pending,
        }
        payload["social"] = {
            "polite": polite,
            "direct": direct,
            "hedged": hedged,
            "correct_title": correct_title,
            "thanks": thanks,
            "apology": apology,
            "challenge": challenge,
            "compliment": compliment,
            "insult_level": insult_level,
            "valor_answer": valor_answer,
        }
        payload["special_candidates"] = [
            {
                "id": concept,
                "confidence": 1.0,
                "negated": False,
                "evidence": text[:160],
            }
            for concept in specials
        ]
        payload["chat"] = {"topic": "general", "question": "?" in text}
        payload["confidence"] = {
            "overall": overall_confidence,
            "task": task_confidence,
            "colors": (
                colors_confidence
                if colors_confidence is not None
                else (0.99 if colors else 0.0)
            ),
            "destination": (
                destination_confidence
                if destination_confidence is not None
                else (0.99 if destination else 0.0)
            ),
        }
        payload["evidence"] = [text[:160]]
        return TurnEvent.from_mapping(
            payload,
            raw_text=text,
            normalized_text=text.casefold(),
        )

    return make_event
