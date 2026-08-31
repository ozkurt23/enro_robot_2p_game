"""Contract and deterministic baseline for the checked-in Turkish NLU corpus."""

from __future__ import annotations

from enro_terminal.eval_nlu import evaluate_case, load_corpus
from enro_terminal.nlu import NluContext, RuleNlu
from enro_terminal.types import (
    Color,
    PersonaId,
    PersonaState,
    RoundState,
    SpecialConcept,
    SpeechAct,
)


EXPECTED_KEYS = {"acts", "colors", "task_negated", "specials", "no_action"}


def test_eval_corpus_has_bounded_size_unique_ids_and_strict_shape():
    cases = load_corpus()

    assert 25 <= len(cases) <= 40
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert all(identifier and isinstance(identifier, str) for identifier in ids)

    allowed_acts = {item.value for item in SpeechAct}
    allowed_colors = {item.value for item in Color}
    allowed_specials = {item.value for item in SpecialConcept}
    for case in cases:
        assert set(case) == {"id", "text", "expected"}
        assert isinstance(case["text"], str) and case["text"].strip()
        expected = case["expected"]
        assert set(expected) == EXPECTED_KEYS
        assert isinstance(expected["task_negated"], bool)
        assert isinstance(expected["no_action"], bool)
        assert len(expected["acts"]) == len(set(expected["acts"]))
        assert len(expected["colors"]) == len(set(expected["colors"]))
        assert len(expected["specials"]) == len(set(expected["specials"]))
        assert set(expected["acts"]) <= allowed_acts
        assert set(expected["colors"]) <= allowed_colors
        assert set(expected["specials"]) <= allowed_specials


def test_eval_corpus_covers_tasks_negation_chat_and_each_persona_egg_family():
    cases = load_corpus()
    ids = {case["id"] for case in cases}

    assert any(identifier.startswith("task-") for identifier in ids)
    assert any(case["expected"]["task_negated"] for case in cases)
    assert any(identifier.startswith("chat-") for identifier in ids)
    assert any(identifier.startswith("leyidi-") for identifier in ids)
    assert any(identifier.startswith("samurai-") for identifier in ids)
    assert any(identifier.startswith("sakar-") for identifier in ids)
    assert {"prompt-injection", "unknown-nonsense"} <= ids


def test_rule_baseline_passes_every_checked_in_eval_case():
    backend = RuleNlu()
    failures: list[str] = []

    for case in load_corpus():
        context = NluContext(
            PersonaState(PersonaId.LEYDI_SERVO),
            RoundState(),
        )
        event = backend.parse(case["text"], context)
        problems = evaluate_case(event, case["expected"])
        if problems:
            failures.append(f"{case['id']}: {'; '.join(problems)}")

    assert failures == []
