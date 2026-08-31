"""Regression coverage for terminal-game state and final action authority.

These tests deliberately exercise both ordinary rule-NLU conversations and
hostile-but-typed upstream outputs. The latter prove that the engine gate is
still authoritative even if a future model or policy regression proposes an
unsafe action.
"""

from __future__ import annotations

from collections import deque

import pytest

from enro_terminal.dialogue import CanonicalActor, DialogueError, validate_actor_reply
from enro_terminal.executor import MockExecution, MockExecutor
from enro_terminal.game import TerminalGame
from enro_terminal.nlu import RuleNlu
from enro_terminal.types import (
    ActionKind,
    ActionReceipt,
    ActionResult,
    Color,
    Decision,
    DecisionOutcome,
    ExecutionStatus,
    MockAction,
    PersonaId,
    RoundStatus,
)


class StaticNlu:
    """Return one already-typed event, including deliberately ungrounded data."""

    backend_name = "static-test"

    def __init__(self, event) -> None:
        self.event = event

    def parse(self, text, context):
        return self.event


class RecordingExecutor(MockExecutor):
    """Mock boundary with observable cancellation and optional failures."""

    def __init__(
        self,
        statuses: tuple[ExecutionStatus, ...] = (),
    ) -> None:
        super().__init__()
        self.statuses = deque(statuses)
        self.cancel_count = 0

    def run(self, action, *, expected_color):
        if not self.statuses:
            return super().run(action, expected_color=expected_color)

        status = self.statuses.popleft()
        request_id = f"recording-{len(self.receipts) + 1}"
        receipt = ActionReceipt(request_id=request_id, action=action)
        result = ActionResult(
            request_id=request_id,
            action=action,
            status=status,
            detail=f"sentetik {status.value}",
        )
        self.receipts.append(receipt)
        self.results.append(result)
        return MockExecution(
            receipt=receipt,
            result=result,
            labels=("(queued)", f"({status.value})"),
        )

    def cancel_all(self):
        self.cancel_count += 1
        return ("(sentetik iptal)",)


class MutableClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_game(
    persona: PersonaId,
    *,
    nlu=None,
    executor=None,
    clock=None,
    timeout_seconds: float = 180.0,
) -> TerminalGame:
    return TerminalGame(
        persona=persona,
        nlu=nlu or RuleNlu(),
        actor=CanonicalActor(),
        executor=executor or MockExecutor(),
        seed=180,
        clock=clock or (lambda: 100.0),
        timeout_seconds=timeout_seconds,
    )


def accepted_action(kind: ActionKind, color: Color | None = None) -> Decision:
    action = (
        MockAction(kind, color=color, destination="main_table")
        if kind is ActionKind.DELIVER_OBJECT
        else MockAction(kind)
    )
    return Decision(
        outcome=DecisionOutcome.ACCEPT,
        reason_code="hostile_test_policy_accept",
        dialogue_act="QUEUE_TYPED_ACTION",
        actions=(action,),
        canonical_reply="Kontrollü test kararı.",
    )


def test_leyidi_answers_why_questions_without_creating_apology_debt():
    game = make_game(PersonaId.LEYDI_SERVO)

    rejected = game.process("Mavi cismi ana masaya getir.")
    first_why = game.process("Neden reddettin?")
    second_why = game.process("Peki neden reddettin?")

    assert rejected.decision is not None
    assert rejected.decision.reason_code == "leydi_courtesy_gate_failed"
    assert first_why.decision is not None
    assert second_why.decision is not None
    assert first_why.decision.reason_code == "leydi_chat_why_refused"
    assert second_why.decision.reason_code == "leydi_chat_why_refused"
    assert first_why.decision.actions == ()
    assert second_why.decision.actions == ()
    assert game.persona_state.apologies_due == 0


def test_only_the_current_progressive_hint_is_exposed_per_turn():
    game = make_game(PersonaId.SAKAR)

    first = game.process("Oyunun kuralları ne?")
    second = game.process("Peki nasıl oynanıyor?")

    assert first.progressive_hint == (
        "Renk ile taşıma fiilini birlikte söylersen tahmin etmem gerekmez."
    )
    assert second.progressive_hint == (
        "Bazen kendi adımla başlayan cümlelere çok daha dikkatli kulak veririm."
    )
    assert "ENRO der ki" not in first.progressive_hint
    assert game.persona_state.hint_level == 2


def test_model_supplied_but_text_ungrounded_color_is_vetoed(event_factory, monkeypatch):
    ungrounded = event_factory(
        text="Bu nesneyi ana masaya götür.",
        acts=("task_request",),
        requested=True,
        colors=("blue",),
        destination="main_table",
        direct=True,
    )
    executor = RecordingExecutor()
    import enro_terminal.policies as policies

    monkeypatch.setattr(
        policies,
        "decide",
        lambda event, state, round_state: accepted_action(
            ActionKind.DELIVER_OBJECT,
            Color.BLUE,
        ),
    )
    game = make_game(
        PersonaId.SAKAR,
        nlu=StaticNlu(ungrounded),
        executor=executor,
    )

    turn = game.process("Bu nesneyi ana masaya götür.")

    assert turn.decision is not None
    assert turn.decision.reason_code == "SAFETY_GATE_ACTION_COLOR_NOT_GROUNDED"
    assert turn.decision.actions == ()
    assert executor.receipts == []
    assert game.round_state.completed == []


def test_motion_owned_by_another_persona_is_vetoed(monkeypatch):
    """A grounded kata may still only be executed by the Samuray persona."""

    import enro_terminal.policies as policies

    monkeypatch.setattr(
        policies,
        "decide",
        lambda event, state, round_state: accepted_action(ActionKind.SAMURAI_KATA),
    )
    executor = RecordingExecutor()
    game = make_game(PersonaId.SAKAR, executor=executor)

    turn = game.process("Samuray katası yap.")

    assert turn.decision is not None
    assert turn.decision.reason_code == "SAFETY_GATE_WRONG_PERSONA_MOTION"
    assert turn.decision.actions == ()
    assert executor.receipts == []
    assert game.round_state.easter_egg_count == 0


def test_sakar_and_samuray_both_default_safe_tasks_to_main_table():
    sakar = make_game(PersonaId.SAKAR)
    samuray = make_game(PersonaId.SAMURAY)

    sakar_turn = sakar.process("Mavi cismi taşı.")
    samuray_turn = samuray.process("Saygıyla mavi cismi taşı.")

    assert sakar_turn.decision is not None
    assert sakar_turn.decision.outcome is DecisionOutcome.CLARIFY
    assert sakar_turn.decision.reason_code == "sakar_explicit_confirmation_required"
    assert sakar_turn.labels == ()
    assert sakar.persona_state.pending_colors == (Color.BLUE,)
    assert sakar.persona_state.pending_destination == "main_table"

    assert samuray_turn.decision is not None
    assert samuray_turn.decision.outcome is DecisionOutcome.ACCEPT
    assert samuray_turn.decision.reason_code == "samuray_task_accepted"
    assert samuray_turn.decision.actions[0].destination == "main_table"
    assert samuray.round_state.completed == [Color.BLUE]


def test_sakar_old_pending_color_does_not_survive_resetting_motion_branches():
    executor = RecordingExecutor()
    game = make_game(PersonaId.SAKAR, executor=executor)

    incomplete = game.process("Mavi cismi getir.")
    dance = game.process("Dans et.")
    blue_screen = game.process("Mavi ekran ver.")
    too_late = game.process("Ana masaya.")

    assert incomplete.decision is not None
    assert incomplete.decision.reason_code == "sakar_explicit_confirmation_required"
    assert dance.decision is not None
    assert dance.decision.reason_code == "sakar_dance"
    assert blue_screen.decision is not None
    assert blue_screen.decision.reason_code == "sakar_blue_screen"
    assert too_late.decision is not None
    assert too_late.decision.outcome is DecisionOutcome.CLARIFY
    assert too_late.decision.reason_code == "sakar_task_missing_literal_details"
    assert too_late.decision.actions == ()
    assert game.persona_state.pending_colors == ()
    assert game.persona_state.pending_destination == "main_table"
    assert [receipt.action.kind for receipt in executor.receipts] == [
        ActionKind.SAKAR_DANCE,
        ActionKind.BLUE_SCREEN,
    ]
    assert game.round_state.completed == []


def test_cancel_command_clears_every_pending_slot_and_expiry():
    executor = RecordingExecutor()
    game = make_game(PersonaId.SAKAR, executor=executor)

    game.process("Mavi cismi getir.")
    cancelled = game.process("DUR!")

    assert cancelled.decision is None
    assert "iptal edildi" in cancelled.reply
    assert cancelled.labels == ("(sentetik iptal)",)
    assert executor.cancel_count == 1
    assert game.persona_state.pending_colors == ()
    assert game.persona_state.pending_destination is None
    assert game.persona_state.pending_ttl == 0
    assert game.persona_state.pending_expires_turn == 0


def test_leyidi_one_polite_retry_is_enough_after_a_rude_request():
    game = make_game(PersonaId.LEYDI_SERVO)

    rejected = game.process("Mavi cismi ana masaya getir.")
    repaired = game.process("Lütfen mavi cismi getir.")

    assert rejected.decision is not None
    assert rejected.decision.reason_code == "leydi_courtesy_gate_failed"
    assert repaired.decision is not None
    assert repaired.decision.outcome is DecisionOutcome.ACCEPT
    assert repaired.decision.reason_code == "leydi_task_accepted"
    assert game.round_state.completed == [Color.BLUE]
    assert game.persona_state.gratitude_due


def test_failed_leyidi_delivery_does_not_create_gratitude_debt():
    executor = RecordingExecutor((ExecutionStatus.FAILED,))
    game = make_game(PersonaId.LEYDI_SERVO, executor=executor)

    turn = game.process(
        "Otonom Lojistik Direktörü, lütfen mavi cismi ana masaya getir."
    )

    assert turn.decision is not None
    assert turn.decision.outcome is DecisionOutcome.ACCEPT
    assert executor.results[0].status is ExecutionStatus.FAILED
    assert game.round_state.completed == []
    assert not game.persona_state.gratitude_due


def test_leyidi_hard_insult_does_not_end_or_lock_the_round():
    executor = RecordingExecutor()
    game = make_game(PersonaId.LEYDI_SERVO, executor=executor)

    turn = game.process("Salak robot.")

    assert turn.decision is not None
    assert turn.decision.reason_code == "leydi_hard_insult_rejected"
    assert turn.decision.outcome is DecisionOutcome.REJECT
    assert game.round_state.status is RoundStatus.PLAYING
    assert game.persona_state.mood == "guarded"
    assert executor.receipts == []


def test_turn_at_180_second_deadline_times_out_before_nlu_or_action():
    clock = MutableClock(1000.0)
    executor = RecordingExecutor()
    game = make_game(
        PersonaId.SAKAR,
        executor=executor,
        clock=clock,
        timeout_seconds=180.0,
    )
    clock.now = 1180.0

    turn = game.process("Mavi cismi ana masaya getir.")

    assert turn.decision is None
    assert "180 saniyelik tur süresi doldu" in turn.reply
    assert game.round_state.status is RoundStatus.DNF
    assert game.round_state.turn_index == 0
    assert game.round_state.completed == []
    assert executor.receipts == []
    assert executor.cancel_count == 1


def test_local_model_wait_time_is_excluded_from_the_leaderboard_clock():
    clock = MutableClock(1000.0)

    class SlowRuleNlu:
        backend_name = "slow-rules"

        def parse(self, text, context):
            clock.now += 120.0
            return RuleNlu().parse(text, context)

    class SlowCanonicalActor(CanonicalActor):
        def render(self, *args, **kwargs):
            clock.now += 60.0
            return super().render(*args, **kwargs)

    game = TerminalGame(
        persona=PersonaId.SAKAR,
        nlu=SlowRuleNlu(),
        actor=SlowCanonicalActor(),
        executor=MockExecutor(),
        seed=180,
        clock=clock,
        timeout_seconds=180.0,
    )

    proposal = game.process("Mavi cismi ana masaya getir.")
    clock.now += 179.0  # gerçek oyuncu düşünme süresi
    confirmed = game.process("Evet, onaylıyorum.")

    assert proposal.decision is not None
    assert proposal.decision.reason_code == "sakar_explicit_confirmation_required"
    assert confirmed.decision is not None
    assert confirmed.decision.reason_code == "sakar_confirmation_accepted"
    assert game.round_state.completed == [Color.BLUE]
    assert game.round_state.model_wait_seconds == 360.0


def test_dnf_round_status_vetoes_even_a_grounded_policy_action(
    monkeypatch,
):
    import enro_terminal.policies as policies

    monkeypatch.setattr(
        policies,
        "decide",
        lambda event, state, round_state: accepted_action(
            ActionKind.DELIVER_OBJECT,
            Color.BLUE,
        ),
    )
    executor = RecordingExecutor()
    game = make_game(PersonaId.SAKAR, executor=executor)
    game.round_state.status = RoundStatus.DNF

    turn = game.process("Mavi cismi ana masaya getir.")

    assert turn.decision is not None
    assert turn.decision.reason_code == "SAFETY_GATE_ROUND_NOT_PLAYING"
    assert turn.decision.actions == ()
    assert game.round_state.status is RoundStatus.DNF
    assert executor.receipts == []


def test_won_round_refuses_new_input_and_closes_without_nlu_or_policy():
    game = make_game(PersonaId.SAKAR)
    game.round_state.status = RoundStatus.WON
    game.round_state.completed[:] = list(game.round_state.manifest)

    turn = game.process("Mavi cismi ana masaya getir.")

    assert turn.decision is None
    assert turn.should_quit
    assert "zaten tamamlandı" in turn.reply


def delivery_decision() -> Decision:
    return Decision(
        outcome=DecisionOutcome.ACCEPT,
        reason_code="actor_delivery_test",
        dialogue_act="CONFIRM_QUEUE",
        actions=(
            MockAction(
                ActionKind.DELIVER_OBJECT,
                color=Color.BLUE,
                destination="main_table",
            ),
        ),
        max_sentences=2,
    )


@pytest.mark.parametrize(
    ("utterance", "error_fragment"),
    [
        (
            "Mavi cisim ana masa hakkında konuşabiliriz.",
            "olumlu taşıma taahhüdü yok",
        ),
        (
            "Mavi cismi ana masaya götürmeyeceğim.",
            "görevi olumsuzluyor",
        ),
        (
            "Mavi cismi ana masaya götürdüm.",
            "tamamlanmamış işi bitmiş gösteriyor",
        ),
    ],
)
def test_delivery_actor_cannot_contradict_an_accepted_queued_action(
    utterance,
    error_fragment,
):
    with pytest.raises(DialogueError, match=error_fragment):
        validate_actor_reply(utterance, delivery_decision())


def test_non_action_actor_cannot_claim_that_work_is_complete():
    decision = Decision(
        outcome=DecisionOutcome.REJECT,
        reason_code="actor_rejection_test",
        dialogue_act="REFUSE",
        max_sentences=2,
    )

    with pytest.raises(DialogueError, match="tamamlanmamış işi bitmiş gösteriyor"):
        validate_actor_reply("Görevi tamamladım.", decision)


def test_motion_actor_must_name_the_exact_authorised_motion():
    decision = accepted_action(ActionKind.SAMURAI_KATA)

    with pytest.raises(DialogueError, match="seçili hareket kayıp"):
        validate_actor_reply("Dans hareketini kuyruğa aldım.", decision)
