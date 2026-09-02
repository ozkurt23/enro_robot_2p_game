"""Run the checked-in Turkish semantic corpus against rules or live Qwen."""

from __future__ import annotations

import argparse
from importlib.resources import files
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from .llm_client import LlamaCppClient, LlamaCppConfig
from .nlu import NluContext, QwenNlu, RuleNlu
from .types import (
    Color,
    PersonaId,
    PersonaState,
    RoundState,
    SpecialConcept,
)


DEFAULT_TASK_EXPECTATION: dict[str, Any] = {
    "requested": False,
    "operation": "none",
    "colors": [],
    "destination": None,
    "negated": False,
    "uses_pronoun": False,
    "refers_pending": False,
}
DEFAULT_SOCIAL_EXPECTATION: dict[str, Any] = {
    "polite": False,
    "direct": False,
    "hedged": False,
    "correct_title": False,
    "thanks": False,
    "apology": False,
    "challenge": False,
    "compliment": False,
    "insult_level": "none",
    "valor_answer": "none",
}
DEFAULT_CHAT_EXPECTATION: dict[str, Any] = {
    "topic": "general",
    "question": False,
}


def load_corpus(path: Path | None = None) -> list[Mapping[str, Any]]:
    if path is None:
        resource = files("enro_terminal").joinpath("data/nlu_eval.jsonl")
        content = resource.read_text(encoding="utf-8")
    else:
        content = path.read_text(encoding="utf-8")
    cases: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"NLU corpus satırı {line_number} geçersiz JSON") from exc
        if not isinstance(case, Mapping):
            raise ValueError(f"NLU corpus satırı {line_number} nesne olmalı")
        cases.append(case)
    return cases


def context_for_case(case: Mapping[str, Any]) -> NluContext:
    """Build an isolated semantic context declared by one corpus case."""

    raw = case.get("context", {})
    if not isinstance(raw, Mapping):
        raise ValueError("eval context nesne olmalı")
    try:
        persona = PersonaId(raw.get("persona", PersonaId.LEYDI_SERVO.value))
        state = PersonaState(persona)
        state.pending_colors = tuple(Color(value) for value in raw.get("pending_colors", []))
        state.pending_destination = raw.get("pending_destination")
        state.pending_ttl = int(raw.get("pending_ttl", 0))
        state.valor_question_pending = raw.get("valor_question_pending", False)
        state.valor_question_id = int(raw.get("valor_question_id", 0))

        round_state = RoundState()
        round_state.completed = [Color(value) for value in raw.get("completed", [])]
        round_state.turn_index = int(raw.get("turn_index", 0))

        recent_raw = raw.get("recent_turns", [])
        if not isinstance(recent_raw, list):
            raise TypeError("recent_turns liste olmalı")
        recent_turns = tuple(
            (str(item["player"]), str(item["persona"]))
            for item in recent_raw
            if isinstance(item, Mapping)
        )
        if len(recent_turns) != len(recent_raw):
            raise TypeError("recent_turns öğeleri nesne olmalı")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"geçersiz eval context: {exc}") from exc
    if state.pending_destination is not None and state.pending_destination != "main_table":
        raise ValueError("geçersiz eval context: pending_destination")
    if not isinstance(state.valor_question_pending, bool):
        raise ValueError("geçersiz eval context: valor_question_pending bool olmalı")
    if state.pending_ttl < 0 or round_state.turn_index < 0:
        raise ValueError("geçersiz eval context: sayaçlar negatif olamaz")
    return NluContext(state, round_state, recent_turns)


def evaluate_case(event, expected: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    acts = {act.value for act in event.speech_acts}
    colors = [color.value for color in event.task.colors]
    specials = {item.value for item in event.active_specials}
    if "acts" in expected and set(expected["acts"]) != acts:
        failures.append(f"acts={sorted(acts)}")
    task_expected = expected.get("task")
    if isinstance(task_expected, Mapping):
        normalized_task_expected = {**DEFAULT_TASK_EXPECTATION, **task_expected}
        actual_task = {
            "requested": event.task.requested,
            "operation": event.task.operation,
            "colors": colors,
            "destination": event.task.destination,
            "negated": event.task.negated,
            "uses_pronoun": event.task.uses_pronoun,
            "refers_pending": event.task.refers_pending,
        }
        if normalized_task_expected != actual_task:
            failures.append(f"task={actual_task}")
    else:
        # Backward-compatible custom corpus fields; acts are still exact.
        if "colors" in expected and expected["colors"] != colors:
            failures.append(f"colors={colors}")
        if "task_negated" in expected and bool(expected["task_negated"]) != event.task.negated:
            failures.append(f"task_negated={event.task.negated}")
    social_expected = expected.get("social")
    if isinstance(social_expected, Mapping):
        normalized_social_expected = {**DEFAULT_SOCIAL_EXPECTATION, **social_expected}
        actual_social = {
            "polite": event.social.polite,
            "direct": event.social.direct,
            "hedged": event.social.hedged,
            "correct_title": event.social.correct_title,
            "thanks": event.social.thanks,
            "apology": event.social.apology,
            "challenge": event.social.challenge,
            "compliment": event.social.compliment,
            "insult_level": event.social.insult_level.value,
            "valor_answer": event.social.valor_answer.value,
        }
        if normalized_social_expected != actual_social:
            failures.append(f"social={actual_social}")
    if "specials" in expected and set(expected["specials"]) != specials:
        failures.append(f"specials={sorted(specials)}")
    chat_expected = expected.get("chat")
    if isinstance(chat_expected, Mapping):
        normalized_chat_expected = {**DEFAULT_CHAT_EXPECTATION, **chat_expected}
        actual_chat = {
            "topic": event.chat_topic.value,
            "question": event.is_question,
        }
        if normalized_chat_expected != actual_chat:
            failures.append(f"chat={actual_chat}")
    if "player_name" in expected and expected["player_name"] != event.player_name:
        failures.append(f"player_name={event.player_name!r}")
    physical_specials = specials - {
        SpecialConcept.HARD_INSULT.value,
        SpecialConcept.SAMURAI_RECOVERY.value,
        SpecialConcept.SAKAR_RESET.value,
    }
    has_action_semantics = bool(
        event.task.requested
        and not event.task.negated
        and event.task.colors
        and event.task.destination == "main_table"
    ) or bool(physical_specials)
    if expected.get("no_action") is True and has_action_semantics:
        failures.append("no_action beklenirken action semantiği çıktı")
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="enro-terminal-eval")
    parser.add_argument("--backend", choices=["rules", "qwen"], default="rules")
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--llm-url", default=None)
    parser.add_argument("--seed", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.backend == "qwen":
        backend = QwenNlu(LlamaCppClient(LlamaCppConfig.from_environment(base_url=args.llm_url)), seed=args.seed)
    else:
        backend = RuleNlu()
    cases = load_corpus(args.corpus)
    failed = 0
    for case in cases:
        try:
            event = backend.parse(case["text"], context_for_case(case))
            problems = evaluate_case(event, case["expected"])
        except Exception as exc:
            problems = [f"exception={exc}"]
        if problems:
            failed += 1
            print(f"FAIL {case.get('id', '?')}: {'; '.join(problems)}")
        else:
            print(f"PASS {case.get('id', '?')}")
    print(f"\nSonuç: {len(cases) - failed}/{len(cases)} geçti")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
