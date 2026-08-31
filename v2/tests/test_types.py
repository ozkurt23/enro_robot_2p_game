"""Strict validation tests for untrusted structured NLU output."""

from __future__ import annotations

from copy import deepcopy

import pytest

from enro_terminal.types import (
    ChatTopic,
    Color,
    DomainValidationError,
    InsultLevel,
    SpecialConcept,
    SpeechAct,
    TurnEvent,
)


def parse(payload: dict[str, object]) -> TurnEvent:
    return TurnEvent.from_mapping(
        payload,
        raw_text="Lütfen mavi cismi ana masaya getir.",
        normalized_text="lütfen mavi cismi ana masaya getir",
    )


def test_valid_turn_event_is_converted_to_typed_domain(valid_turn_payload):
    event = parse(valid_turn_payload)

    assert event.speech_acts == (SpeechAct.TASK_REQUEST,)
    assert event.task.colors == (Color.BLUE,)
    assert event.task.destination == "main_table"
    assert event.social.insult_level is InsultLevel.NONE
    assert event.chat_topic is ChatTopic.NONE
    assert event.active_specials == frozenset()


@pytest.mark.parametrize(
    ("mutation", "error_fragment"),
    [
        (lambda value: value.update({"case_id": "motion.royal_waltz"}), "fazla=case_id"),
        (lambda value: value.pop("confidence"), "eksik=confidence"),
        (lambda value: value["task"].update({"ros_topic": "/cmd_vel"}), "fazla=ros_topic"),
        (lambda value: value["social"].update({"joint": 3}), "fazla=joint"),
    ],
)
def test_turn_event_rejects_missing_and_injected_fields(
    valid_turn_payload,
    mutation,
    error_fragment,
):
    payload = deepcopy(valid_turn_payload)
    mutation(payload)

    with pytest.raises(DomainValidationError, match=error_fragment):
        parse(payload)


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("speech_acts",), ["execute_shell"]),
        (("task", "colors"), ["purple"]),
        (("task", "destination"), "operator_table"),
        (("task", "operation"), "dance"),
        (("social", "insult_level"), "fatal"),
        (("chat", "topic"), "robot_joint"),
    ],
)
def test_turn_event_rejects_unknown_enums(valid_turn_payload, path, bad_value):
    payload = deepcopy(valid_turn_payload)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    with pytest.raises(DomainValidationError):
        parse(payload)


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("task", "requested"), 1),
        (("task", "negated"), "false"),
        (("social", "polite"), "yes"),
        (("chat", "question"), 0),
        (("confidence", "overall"), True),
        (("confidence", "task"), 1.01),
        (("confidence", "colors"), -0.01),
        (("special_candidates",), {}),
        (("evidence",), "mavi"),
    ],
)
def test_turn_event_rejects_wrong_types_and_probability_ranges(
    valid_turn_payload,
    path,
    bad_value,
):
    payload = deepcopy(valid_turn_payload)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    with pytest.raises(DomainValidationError):
        parse(payload)


def test_turn_event_rejects_duplicate_colors(valid_turn_payload):
    payload = deepcopy(valid_turn_payload)
    payload["task"]["colors"] = ["blue", "blue"]

    with pytest.raises(DomainValidationError, match="yinelenen renk"):
        parse(payload)


def test_special_candidate_requires_high_confidence_and_positive_meaning(
    valid_turn_payload,
):
    payload = deepcopy(valid_turn_payload)
    payload["special_candidates"] = [
        {
            "id": "mechanical_beauty",
            "confidence": 0.99,
            "negated": False,
            "evidence": "mekanik ve güzelsin",
        },
        {
            "id": "royal_waltz",
            "confidence": 0.91,
            "negated": False,
            "evidence": "vals olabilir",
        },
        {
            "id": "hard_insult",
            "confidence": 1.0,
            "negated": True,
            "evidence": "salak deme",
        },
    ]

    event = parse(payload)

    assert event.active_specials == frozenset({SpecialConcept.MECHANICAL_BEAUTY})


def test_turn_event_rejects_duplicate_special_candidates(valid_turn_payload):
    payload = deepcopy(valid_turn_payload)
    candidate = {
        "id": "blue_screen",
        "confidence": 0.99,
        "negated": False,
        "evidence": "mavi ekran",
    }
    payload["special_candidates"] = [candidate, deepcopy(candidate)]

    with pytest.raises(DomainValidationError, match="yinelenen kavram"):
        parse(payload)


def test_turn_event_rejects_oversized_evidence(valid_turn_payload):
    payload = deepcopy(valid_turn_payload)
    payload["special_candidates"] = [
        {
            "id": "hard_insult",
            "confidence": 1.0,
            "negated": False,
            "evidence": "x" * 161,
        }
    ]

    with pytest.raises(DomainValidationError, match="çok uzun"):
        parse(payload)


@pytest.mark.parametrize(
    ("requested", "operation"),
    [(True, "none"), (False, "deliver")],
)
def test_turn_event_rejects_inconsistent_task_request_and_operation(
    valid_turn_payload,
    requested,
    operation,
):
    payload = deepcopy(valid_turn_payload)
    payload["task"]["requested"] = requested
    payload["task"]["operation"] = operation

    with pytest.raises(DomainValidationError, match="birbiriyle tutarlı"):
        parse(payload)
