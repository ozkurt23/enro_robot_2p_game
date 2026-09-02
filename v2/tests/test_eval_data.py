"""Contract and deterministic baseline for the checked-in Turkish NLU corpus."""

from __future__ import annotations

from copy import deepcopy

from enro_terminal.eval_nlu import (
    DEFAULT_CHAT_EXPECTATION,
    DEFAULT_SOCIAL_EXPECTATION,
    DEFAULT_TASK_EXPECTATION,
    context_for_case,
    evaluate_case,
    load_corpus,
)
from enro_terminal.nlu import RuleNlu
from enro_terminal.types import (
    ChatTopic,
    Color,
    InsultLevel,
    PersonaId,
    SpecialConcept,
    SpeechAct,
    ValorAnswer,
)


EXPECTED_KEYS = {
    "acts", "task", "social", "specials", "chat", "player_name", "no_action",
}
CONTEXT_KEYS = {
    "persona",
    "pending_colors",
    "pending_destination",
    "pending_ttl",
    "valor_question_pending",
    "valor_question_id",
    "completed",
    "turn_index",
    "recent_turns",
}


def test_eval_corpus_has_bounded_size_unique_ids_and_strict_shape():
    cases = load_corpus()

    # Large enough to cover adversarial and contextual semantics, still tiny
    # enough for the offline rules gate to finish in well under a second.
    assert 80 <= len(cases) <= 120
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert all(identifier and isinstance(identifier, str) for identifier in ids)

    allowed_acts = {item.value for item in SpeechAct}
    allowed_colors = {item.value for item in Color}
    allowed_specials = {item.value for item in SpecialConcept}
    allowed_topics = {item.value for item in ChatTopic}
    allowed_insults = {item.value for item in InsultLevel}
    allowed_valor = {item.value for item in ValorAnswer}
    for case in cases:
        assert set(case) in ({"id", "text", "expected"}, {"id", "text", "context", "expected"})
        assert isinstance(case["text"], str) and case["text"].strip()
        expected = case["expected"]
        assert set(expected) == EXPECTED_KEYS
        assert isinstance(expected["no_action"], bool)
        assert expected["player_name"] is None or isinstance(expected["player_name"], str)
        assert isinstance(expected["task"], dict)
        assert isinstance(expected["social"], dict)
        assert isinstance(expected["chat"], dict)
        assert set(expected["task"]) <= set(DEFAULT_TASK_EXPECTATION)
        assert set(expected["social"]) <= set(DEFAULT_SOCIAL_EXPECTATION)
        assert set(expected["chat"]) <= set(DEFAULT_CHAT_EXPECTATION)
        assert len(expected["acts"]) == len(set(expected["acts"]))
        assert expected["acts"]
        task = {**DEFAULT_TASK_EXPECTATION, **expected["task"]}
        social = {**DEFAULT_SOCIAL_EXPECTATION, **expected["social"]}
        chat = {**DEFAULT_CHAT_EXPECTATION, **expected["chat"]}
        assert isinstance(task["requested"], bool)
        assert task["operation"] in {"none", "deliver"}
        assert task["requested"] == (task["operation"] == "deliver")
        assert task["destination"] in {None, "main_table"}
        assert all(isinstance(task[name], bool) for name in ("negated", "uses_pronoun", "refers_pending"))
        assert len(task["colors"]) == len(set(task["colors"]))
        assert set(task["colors"]) <= allowed_colors
        assert all(isinstance(social[name], bool) for name in (
            "polite", "direct", "hedged", "correct_title", "thanks",
            "apology", "challenge", "compliment",
        ))
        assert social["insult_level"] in allowed_insults
        assert social["valor_answer"] in allowed_valor
        assert chat["topic"] in allowed_topics
        assert isinstance(chat["question"], bool)
        assert len(expected["specials"]) == len(set(expected["specials"]))
        assert set(expected["acts"]) <= allowed_acts
        assert set(expected["specials"]) <= allowed_specials

        context = case.get("context", {})
        assert isinstance(context, dict)
        assert set(context) <= CONTEXT_KEYS
        # Construction exercises enum values, counters and recent-turn shape.
        context_for_case(case)


def test_eval_corpus_covers_tasks_adversaries_context_and_every_persona():
    cases = load_corpus()
    ids = {case["id"] for case in cases}

    assert any(identifier.startswith("task-") for identifier in ids)
    assert any(case["expected"]["task"].get("negated") is True for case in cases)
    assert any(identifier.startswith("chat-") for identifier in ids)
    assert any(identifier.startswith("leyidi-") for identifier in ids)
    assert any(identifier.startswith("samurai-") for identifier in ids)
    assert any(identifier.startswith("sakar-") for identifier in ids)
    assert len([identifier for identifier in ids if "injection" in identifier]) >= 7
    assert any(identifier.startswith("pending-") for identifier in ids)
    assert any(identifier.startswith("valor-") for identifier in ids)
    assert {"prompt-injection", "unknown-nonsense", "history-injection-is-not-current-input"} <= ids

    contextual_personas = {
        case.get("context", {}).get("persona")
        for case in cases
        if isinstance(case.get("context"), dict)
    }
    assert {persona.value for persona in PersonaId} <= contextual_personas


def test_rule_baseline_passes_every_checked_in_eval_case():
    backend = RuleNlu()
    failures: list[str] = []

    for case in load_corpus():
        event = backend.parse(case["text"], context_for_case(case))
        problems = evaluate_case(event, case["expected"])
        if problems:
            failures.append(f"{case['id']}: {'; '.join(problems)}")

    assert failures == []


def test_evaluator_rejects_extra_acts_and_mismatched_important_fields():
    case = next(case for case in load_corpus() if case["id"] == "task-with-greeting")
    event = RuleNlu().parse(case["text"], context_for_case(case))

    missing_act = deepcopy(case["expected"])
    missing_act["acts"] = ["task_request"]
    wrong_destination = deepcopy(case["expected"])
    wrong_destination["task"]["destination"] = None
    wrong_social = deepcopy(case["expected"])
    wrong_social["social"]["direct"] = False

    assert any(problem.startswith("acts=") for problem in evaluate_case(event, missing_act))
    assert any(problem.startswith("task=") for problem in evaluate_case(event, wrong_destination))
    assert any(problem.startswith("social=") for problem in evaluate_case(event, wrong_social))
