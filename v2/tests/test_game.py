"""End-to-end orchestration tests for the terminal-only MVP."""

from __future__ import annotations

from collections import deque

import pytest

from enro_terminal import cli
from enro_terminal.dialogue import CanonicalActor
from enro_terminal.executor import MockExecution, MockExecutor
from enro_terminal.game import TerminalGame
from enro_terminal.nlu import NluError, RuleNlu
from enro_terminal.types import (
    ActionReceipt,
    ActionResult,
    Color,
    ExecutionStatus,
    PersonaId,
    RoundStatus,
)


class SequencedExecutor:
    """Small controllable double preserving the queued -> result contract."""

    def __init__(self, statuses: tuple[ExecutionStatus, ...]) -> None:
        self.statuses = deque(statuses)
        self.executions: list[MockExecution] = []

    def run(self, action, *, expected_color):
        status = self.statuses.popleft()
        request_id = f"scripted-{len(self.executions) + 1}"
        receipt = ActionReceipt(request_id=request_id, action=action)
        result = ActionResult(
            request_id=request_id,
            action=action,
            status=status,
            detail="scripted result",
        )
        execution = MockExecution(
            receipt=receipt,
            result=result,
            labels=(f"({receipt.status.value})", f"({status.value})"),
        )
        self.executions.append(execution)
        return execution

    def cancel_all(self):
        return ("(cancelled)",)


class FailingNlu:
    backend_name = "always-fails"

    def parse(self, text, context):
        raise NluError("sentetik NLU arızası")


class NeverExecutor:
    def run(self, action, *, expected_color):  # pragma: no cover - failure is the assertion
        raise AssertionError("NLU arızasından sonra yürütücü çağrılmamalı")

    def cancel_all(self):
        return ()


def make_sakar_game(*, nlu=None, executor=None) -> TerminalGame:
    return TerminalGame(
        persona=PersonaId.SAKAR,
        nlu=nlu or RuleNlu(),
        actor=CanonicalActor(),
        executor=executor or MockExecutor(),
        seed=180,
        clock=lambda: 100.0,
    )


def test_manifest_advances_only_after_succeeded_result():
    executor = SequencedExecutor(
        (ExecutionStatus.FAILED, ExecutionStatus.SUCCEEDED)
    )
    game = make_sakar_game(executor=executor)

    proposal = game.process("Mavi cismi ana masaya getir.")
    assert proposal.decision is not None
    assert proposal.decision.reason_code == "sakar_explicit_confirmation_required"
    assert executor.executions == []

    failed_turn = game.process("Evet, eminim.")

    assert failed_turn.decision is not None
    assert executor.executions[0].receipt.status is ExecutionStatus.QUEUED
    assert executor.executions[0].result.status is ExecutionStatus.FAILED
    assert game.round_state.completed == []
    assert game.round_state.expected_color is Color.BLUE
    assert game.round_state.status is RoundStatus.PLAYING

    game.process("Mavi cismi ana masaya getir.")
    successful_retry = game.process("Onaylıyorum.")

    assert successful_retry.decision is not None
    assert executor.executions[1].receipt.status is ExecutionStatus.QUEUED
    assert executor.executions[1].result.status is ExecutionStatus.SUCCEEDED
    assert game.round_state.completed == [Color.BLUE]
    assert game.round_state.expected_color is Color.GREEN


def test_nlu_failure_is_fail_closed_and_never_reaches_executor():
    game = make_sakar_game(nlu=FailingNlu(), executor=NeverExecutor())

    turn = game.process("Mavi cismi ana masaya getir.")

    assert turn.decision is None
    assert turn.labels == ()
    assert "hiçbir görev veya hareket" in turn.reply
    assert "sentetik NLU arızası" in turn.technical_error
    assert game.round_state.completed == []
    assert game.round_state.status is RoundStatus.PLAYING


def test_scripted_rule_game_completes_blue_green_red_in_order():
    game = make_sakar_game()

    turns = []
    for color in ("Mavi", "Yeşil", "Kırmızı"):
        turns.append(game.process(f"{color} cismi ana masaya getir."))
        turns.append(game.process("Evet, onaylıyorum."))

    assert all(turn.decision is not None for turn in turns)
    assert game.round_state.completed == [Color.BLUE, Color.GREEN, Color.RED]
    assert game.round_state.remaining == ()
    assert game.round_state.status is RoundStatus.WON
    assert any("tur süresi" in label for label in turns[-1].labels)
    assert turns[-1].should_quit
    assert turns[-1].closing_reply is not None
    assert "tebrik" in turns[-1].closing_reply.casefold()


def test_samuray_runs_three_short_direct_tasks_without_a_valor_checkpoint():
    game = TerminalGame(
        persona=PersonaId.SAMURAY,
        nlu=RuleNlu(),
        actor=CanonicalActor(),
        executor=MockExecutor(),
        seed=180,
        clock=lambda: 100.0,
    )

    blue = game.process("Saygıyla mavi cismi taşı.")
    green = game.process("Yeşil cismi taşı.")
    red = game.process("Saygıyla kırmızı cismi taşı.")

    assert blue.decision is not None and blue.decision.outcome.value == "accept"
    assert green.decision is not None
    assert green.decision.reason_code == "samuray_task_accepted"
    assert not game.persona_state.valor_question_pending
    assert red.should_quit
    assert red.closing_reply is not None
    assert "zafer" in red.closing_reply.casefold()
    assert game.round_state.status is RoundStatus.WON


@pytest.mark.parametrize(
    ("persona", "text", "closing_word"),
    [
        (PersonaId.LEYDI_SERVO, "Bugün çok mekanik ve güzelsin.", "tebrik"),
        (PersonaId.SAMURAY, "Kalan üçünü taşıyamazsın.", "zafer"),
        (PersonaId.SAKAR, "ENRO der ki kalanları sırayla taşı.", "tebrik"),
    ],
)
def test_each_personas_manifest_shortcut_also_closes_with_its_own_victory_voice(
    persona,
    text,
    closing_word,
):
    game = TerminalGame(
        persona=persona,
        nlu=RuleNlu(),
        actor=CanonicalActor(),
        executor=MockExecutor(),
        seed=180,
        clock=lambda: 100.0,
    )

    turn = game.process(text)

    assert game.round_state.status is RoundStatus.WON
    assert turn.should_quit
    assert turn.closing_reply is not None
    assert closing_word in turn.closing_reply.casefold()


def test_cli_script_rules_backend_stays_offline_and_finishes_round(
    tmp_path,
    monkeypatch,
    capsys,
):
    script = tmp_path / "round.txt"
    script.write_text(
        "# yorum satırı\n"
        "Mavi cismi ana masaya getir.\n"
        "Evet, onaylıyorum.\n"
        "Yeşil cismi ana masaya getir.\n"
        "Evet, onaylıyorum.\n"
        "Kırmızı cismi ana masaya getir.\n"
        "Evet, onaylıyorum.\n",
        encoding="utf-8",
    )

    class NetworkMustNotBeConstructed:
        def __init__(self, *args, **kwargs):
            raise AssertionError("rules backend yerel model istememeli")

    monkeypatch.setattr(cli, "LlamaCppClient", NetworkMustNotBeConstructed)

    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "sakar",
            "--seed",
            "180",
            "--no-store",
            "--script",
            str(script),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.err == ""
    assert "RULES + sabit replik" in captured.out
    assert "mavi cisim simde" in captured.out
    assert "yeşil cisim simde" in captured.out
    assert "kırmızı cisim simde" in captured.out
    assert "tur süresi" in captured.out


def test_safety_veto_rolls_back_policy_state_mutations():
    game = TerminalGame(
        persona=PersonaId.LEYDI_SERVO,
        nlu=RuleNlu(),
        actor=CanonicalActor(),
        executor=MockExecutor(),
        seed=180,
        clock=lambda: 100.0,
    )

    turn = game.process(
        "Maviyi getirme ama bugün çok mekanik ve güzelsin."
    )

    assert turn.decision is not None
    assert turn.decision.reason_code == "SAFETY_GATE_NEGATED_INPUT"
    assert turn.labels == ()
    assert game.persona_state.mood == "neutral"
    assert not game.persona_state.gratitude_due
    assert game.persona_state.discovered_eggs == set()
    assert game.round_state.easter_egg_count == 0
    assert game.round_state.completed == []
