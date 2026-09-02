"""Human persona-quality release gates are strict, per-persona and anonymous."""

from __future__ import annotations

import json

import pytest

from enro_terminal.playtest_eval import (
    PlaytestDataError,
    PlaytestRecord,
    evaluate_playtests,
    load_playtest_jsonl,
    main,
    wilson_lower_bound,
)
from enro_terminal.types import PersonaId


def record(
    persona: PersonaId,
    index: int,
    *,
    fun: int = 5,
    fairness: int = 5,
    distinctiveness: int = 5,
    control: int = 5,
    frustration: int = 1,
    replay_interest: int = 5,
    completed: bool = True,
    had_rejection: bool = True,
    recovered: bool | None = True,
) -> PlaytestRecord:
    return PlaytestRecord(
        participant_id=f"anon_{persona.value}_{index:03d}",
        persona=persona,
        fun=fun,
        fairness=fairness,
        distinctiveness=distinctiveness,
        control=control,
        frustration=frustration,
        replay_interest=replay_interest,
        completed=completed,
        had_rejection=had_rejection,
        recovered_within_two_turns=recovered,
    )


def complete_passing_cohort() -> list[PlaytestRecord]:
    return [record(persona, index) for persona in PersonaId for index in range(30)]


def test_complete_high_quality_cohort_passes_every_persona_gate():
    report = evaluate_playtests(complete_passing_cohort())

    assert report.passed
    assert len(report.summaries) == len(PersonaId)
    assert all(summary.samples == 30 for summary in report.summaries)
    assert all(summary.positive_wilson_lower_bound > 0.70 for summary in report.summaries)


def test_one_weak_persona_blocks_the_whole_release():
    records = complete_passing_cohort()
    records = [
        record(
            item.persona,
            index,
            fun=2,
            fairness=2,
            distinctiveness=2,
            control=2,
            frustration=5,
            replay_interest=2,
            completed=False,
            recovered=False,
        )
        if item.persona is PersonaId.UYKUCU
        else item
        for index, item in enumerate(records)
    ]

    report = evaluate_playtests(records)
    uykucu = next(item for item in report.summaries if item.persona is PersonaId.UYKUCU)

    assert not report.passed
    assert not uykucu.passed
    assert any("eğlence" in failure for failure in uykucu.failures)
    assert any("tamamlama" in failure for failure in uykucu.failures)
    assert all(
        summary.passed
        for summary in report.summaries
        if summary.persona is not PersonaId.UYKUCU
    )


def test_missing_persona_and_duplicate_participant_rating_fail_closed():
    records = [record(PersonaId.NESELI, index) for index in range(30)]
    records.append(records[0])

    report = evaluate_playtests(records)

    assert not report.passed
    assert report.duplicate_pairs == ("anon_neseli_000/neseli",)
    assert all(
        summary.failures
        for summary in report.summaries
        if summary.persona is not PersonaId.NESELI
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"participant_id": "Ali@example.com"},
        {"fun": 6},
        {"completed": "yes"},
        {"persona": "unknown"},
        {"had_rejection": False, "recovered_within_two_turns": True},
    ],
)
def test_invalid_or_personally_identifying_shaped_records_are_rejected(mutation):
    document = {
        "participant_id": "anon_0001",
        "persona": "neseli",
        "fun": 5,
        "fairness": 5,
        "distinctiveness": 5,
        "control": 5,
        "frustration": 1,
        "replay_interest": 5,
        "completed": True,
        "had_rejection": True,
        "recovered_within_two_turns": True,
    }
    document.update(mutation)

    with pytest.raises(PlaytestDataError):
        PlaytestRecord.from_mapping(document)


def test_jsonl_loader_reports_the_bad_line_without_accepting_extra_fields(tmp_path):
    path = tmp_path / "ratings.jsonl"
    valid = {
        "participant_id": "anon_0001",
        "persona": "neseli",
        "fun": 5,
        "fairness": 5,
        "distinctiveness": 5,
        "control": 5,
        "frustration": 1,
        "replay_interest": 5,
        "completed": True,
        "had_rejection": False,
        "recovered_within_two_turns": None,
    }
    invalid = {**valid, "participant_id": "anon_0002", "player_message": "özel metin"}
    path.write_text(
        json.dumps(valid, ensure_ascii=False) + "\n" + json.dumps(invalid, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PlaytestDataError, match="satır 2.*fazla=player_message"):
        load_playtest_jsonl(path)


def test_cli_returns_nonzero_until_all_seven_personas_have_enough_data(tmp_path, capsys):
    path = tmp_path / "ratings.jsonl"
    payloads = []
    for index in range(30):
        item = record(PersonaId.NESELI, index, had_rejection=False, recovered=None)
        payloads.append(
            {
                "participant_id": item.participant_id,
                "persona": item.persona.value,
                "fun": item.fun,
                "fairness": item.fairness,
                "distinctiveness": item.distinctiveness,
                "control": item.control,
                "frustration": item.frustration,
                "replay_interest": item.replay_interest,
                "completed": item.completed,
                "had_rejection": item.had_rejection,
                "recovered_within_two_turns": item.recovered_within_two_turns,
            }
        )
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in payloads) + "\n",
        encoding="utf-8",
    )

    assert main([str(path)]) == 1
    output = capsys.readouterr().out
    assert "Neşeli: KALDI" in output  # recovery örneği de bir yayın kapısıdır
    assert "Leydi Servo: KALDI" in output


def test_wilson_lower_bound_never_turns_a_small_perfect_sample_into_proof():
    assert wilson_lower_bound(3, 3) < 0.50
    assert wilson_lower_bound(30, 30) > 0.85
