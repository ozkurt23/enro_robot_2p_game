"""Run the checked-in Turkish semantic corpus against rules or live Qwen."""

from __future__ import annotations

import argparse
from importlib.resources import files
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from .llm_client import LlamaCppClient, LlamaCppConfig
from .nlu import NluContext, QwenNlu, RuleNlu
from .types import PersonaId, PersonaState, RoundState, SpecialConcept


def load_corpus(path: Path | None = None) -> list[Mapping[str, Any]]:
    if path is None:
        resource = files("enro_terminal").joinpath("data/nlu_eval.jsonl")
        content = resource.read_text(encoding="utf-8")
    else:
        content = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def evaluate_case(event, expected: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    acts = {act.value for act in event.speech_acts}
    colors = [color.value for color in event.task.colors]
    specials = {item.value for item in event.active_specials}
    if "acts" in expected and not set(expected["acts"]).issubset(acts):
        failures.append(f"acts={sorted(acts)}")
    if "colors" in expected and expected["colors"] != colors:
        failures.append(f"colors={colors}")
    if "task_negated" in expected and bool(expected["task_negated"]) != event.task.negated:
        failures.append(f"task_negated={event.task.negated}")
    if "specials" in expected and set(expected["specials"]) != specials:
        failures.append(f"specials={sorted(specials)}")
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
    context = NluContext(PersonaState(PersonaId.LEYDI_SERVO), RoundState())
    cases = load_corpus(args.corpus)
    failed = 0
    for case in cases:
        try:
            event = backend.parse(case["text"], context)
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
