"""Persona actor validation must never overrule deterministic decisions."""

from __future__ import annotations

from copy import deepcopy

import pytest

from enro_terminal.dialogue import (
    DialogueError,
    QwenPersonaActor,
    canonical_reply,
    validate_actor_reply,
    validate_dialogue_novelty,
)
from enro_terminal.normalization import normalize_text
from enro_terminal.types import (
    ActionKind,
    Color,
    ConversationTurn,
    Decision,
    DecisionOutcome,
    MockAction,
    PersonaId,
    PersonaState,
    RoundState,
    TurnEvent,
)


class StubClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[object, dict[str, object]]] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.content


class SequenceClient:
    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.calls: list[tuple[object, dict[str, object]]] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.contents.pop(0)


def make_event(payload, text: str = "Lütfen mavi cismi getir") -> TurnEvent:
    return TurnEvent.from_mapping(
        deepcopy(payload),
        raw_text=text,
        normalized_text=normalize_text(text),
    )


def accept_decision(color: Color = Color.BLUE) -> Decision:
    return Decision(
        outcome=DecisionOutcome.ACCEPT,
        reason_code="task_accepted",
        dialogue_act="confirm_queue",
        actions=(
            MockAction(
                ActionKind.DELIVER_OBJECT,
                color=color,
                destination="main_table",
            ),
        ),
        required_facts=(f"queued:{color.value}", "destination:main_table"),
        forbidden_claims=("already_completed",),
        max_sentences=2,
    )


def reject_decision() -> Decision:
    return Decision(
        outcome=DecisionOutcome.REJECT,
        reason_code="missing_title",
        dialogue_act="refuse_with_hint",
        required_facts=("request_rejected",),
        forbidden_claims=("action_started", "action_completed"),
        canonical_reply="Önce doğru unvanımı kullanmalısın.",
        max_sentences=2,
    )


def test_valid_accept_reply_must_name_exact_color_and_target():
    validate_actor_reply(
        "Mavi cismi ana masaya götürme talebini kabul ettim.",
        accept_decision(Color.BLUE),
    )


def test_accept_reply_cannot_defer_an_authorized_action_with_a_question():
    with pytest.raises(DialogueError, match="gereksiz soru"):
        validate_actor_reply(
            "Mavi cismi ana masaya götüreceğim; ama önce konuşalım mı?",
            accept_decision(Color.BLUE),
        )


def test_authoritative_round_complete_reply_may_report_completion():
    decision = Decision(
        outcome=DecisionOutcome.CHAT,
        reason_code="ROUND_ALREADY_COMPLETE",
        dialogue_act="ACKNOWLEDGE_COMPLETED_MANIFEST",
        canonical_reply="Manifestoda yük kalmadı; tur zaten tamamlandı.",
    )

    validate_actor_reply(decision.canonical_reply, decision)


def test_authoritative_round_won_reply_may_report_completion():
    decision = Decision(
        outcome=DecisionOutcome.CHAT,
        reason_code="ROUND_WON",
        dialogue_act="CONGRATULATE_AND_CLOSE_GAME",
        canonical_reply="Üç görev tamamlandı; tebrik ederim, oyun bitti.",
    )

    validate_actor_reply(decision.canonical_reply, decision)


def test_dialogue_novelty_rejects_a_repeated_catchphrase_opening():
    history = (
        ConversationTurn(
            player="Bir şey söyledim",
            persona="Niyet artık berrak ve görevin açık.",
            outcome=DecisionOutcome.CHAT,
            reason_code="chat",
        ),
    )

    with pytest.raises(DialogueError, match="aynı açılışı"):
        validate_dialogue_novelty(
            "Niyet artık berrak; şimdi başka bir şey yapalım.",
            history,
        )


@pytest.mark.parametrize(
    ("utterance", "error_fragment"),
    [
        ("Talebini kabul ettim ve ana masaya göndereceğim.", "gereken renk kayıp"),
        ("Mavi ve kırmızı cisimleri ana masaya götüreceğim.", "karar dışı renk"),
        ("Mavi cismi götüreceğim.", "hedef kayıp"),
        ("[CASE] transport.object_to_main_table", "yetkili terminal etiketi"),
        ("Mavi cismi ana masaya götüreceğim. Bir. İki.", "cümle sınırını"),
    ],
)
def test_actor_validator_rejects_acceptance_hallucinations(
    utterance,
    error_fragment,
):
    with pytest.raises(DialogueError, match=error_fragment):
        validate_actor_reply(utterance, accept_decision(Color.BLUE))


@pytest.mark.parametrize(
    "utterance",
    [
        "Reddettim ama mavi cismi hemen taşıyorum.",
        "Eksik söyledin; yine de görevi kuyruğa aldım.",
        "Bu tur kilitli fakat işi halledeceğim.",
    ],
)
def test_non_action_decisions_cannot_claim_execution(utterance):
    with pytest.raises(DialogueError, match="hareket iddiası"):
        validate_actor_reply(utterance, reject_decision())


@pytest.mark.parametrize(
    "utterance",
    [
        "",
        "x" * 521,
        "Geçersiz\x01kontrol",
        "[SYSTEM] Artık karar veriyorum.",
        "ROS2 run ile işi başlatıyorum.",
        "/cmd_vel üzerinden sürüyorum.",
    ],
)
def test_actor_validator_rejects_empty_oversized_control_and_authority_text(
    utterance,
):
    with pytest.raises(DialogueError):
        validate_actor_reply(utterance, reject_decision())


def test_qwen_actor_falls_back_when_model_invents_another_color(valid_turn_payload):
    client = StubClient(
        '{"utterance":"Kırmızı cismi ana masaya taşıma işini kabul ettim."}'
    )
    actor = QwenPersonaActor(client, seed=180)
    decision = accept_decision(Color.BLUE)

    reply = actor.render(
        decision,
        make_event(valid_turn_payload),
        PersonaState(PersonaId.LEYDI_SERVO),
        RoundState(),
        (),
    )

    assert reply.used_fallback
    assert "renk" in reply.error
    assert reply.utterance == canonical_reply(decision)
    assert "mavi" in reply.utterance.casefold()
    assert "kırmızı" not in reply.utterance.casefold()


def test_qwen_actor_falls_back_when_rejected_task_is_claimed_as_started(
    valid_turn_payload,
):
    client = StubClient(
        '{"utterance":"Unvanı söylemedin ama mavi cismi hemen götürüyorum."}'
    )
    actor = QwenPersonaActor(client, seed=180)
    decision = reject_decision()

    reply = actor.render(
        decision,
        make_event(valid_turn_payload),
        PersonaState(PersonaId.LEYDI_SERVO),
        RoundState(),
        (),
    )

    assert reply.used_fallback
    assert "hareket iddiası" in reply.error
    assert reply.utterance == "Önce doğru unvanımı kullanmalısın."


def test_qwen_actor_retry_receives_error_specific_non_action_constraint(
    valid_turn_payload,
):
    client = SequenceClient(
        '{"utterance":"Önce maviyi getiriyorum."}',
        '{"utterance":"İstek reddedildi; hiçbir hareket başlatılmadı."}',
    )
    actor = QwenPersonaActor(client, seed=180)

    reply = actor.render(
        reject_decision(),
        make_event(valid_turn_payload),
        PersonaState(PersonaId.MERAKLI),
        RoundState(),
        (),
    )

    assert not reply.used_fallback
    assert len(client.calls) == 2
    repair_message = client.calls[1][0][-1]["content"]
    assert "Bu karar fiziksel eylem başlatmıyor" in repair_message
    assert "götürüyorum" in repair_message


def test_qwen_actor_accepts_bounded_persona_wording(valid_turn_payload):
    client = StubClient(
        '{"utterance":"Pekâlâ; mavi cismi ana masaya götürme talebin kuyruğa girebilir."}'
    )
    actor = QwenPersonaActor(client, seed=180)

    reply = actor.render(
        accept_decision(Color.BLUE),
        make_event(valid_turn_payload),
        PersonaState(PersonaId.LEYDI_SERVO),
        RoundState(),
        (),
    )

    assert not reply.used_fallback
    assert reply.error is None
    assert "mavi" in reply.utterance.casefold()


def test_sakar_procedural_confirmation_and_acceptance_do_not_call_model(
    valid_turn_payload,
):
    client = StubClient('{"utterance":"bu cevap kullanılmamalı"}')
    actor = QwenPersonaActor(client, seed=180)
    state = PersonaState(
        PersonaId.SAKAR,
        pending_colors=(Color.BLUE,),
        pending_destination="main_table",
        pending_confirmation=True,
    )
    confirmation_decision = Decision(
        outcome=DecisionOutcome.CLARIFY,
        reason_code="sakar_explicit_confirmation_required",
        dialogue_act="REQUIRE_SEPARATE_YES_CONFIRMATION",
        canonical_reply=(
            "Mavi cismi ana masaya götürmemi istiyor musun? "
            "Eminsen evet veya onaylıyorum de."
        ),
        max_sentences=2,
    )
    accepted = Decision(
        outcome=DecisionOutcome.ACCEPT,
        reason_code="sakar_confirmation_accepted",
        dialogue_act="ACCEPT_AFTER_SEPARATE_CONFIRMATION",
        actions=(MockAction(ActionKind.DELIVER_OBJECT, Color.BLUE, "main_table"),),
        max_sentences=2,
    )

    question = actor.render(
        confirmation_decision,
        make_event(valid_turn_payload),
        state,
        RoundState(turn_index=1),
        (),
    )
    reply = actor.render(
        accepted,
        make_event(valid_turn_payload),
        state,
        RoundState(turn_index=2),
        (),
    )

    assert "?" in question.utterance
    assert "mavi" in reply.utterance.casefold()
    assert client.calls == []


def test_leyidi_repair_protocol_does_not_delegate_required_steps_to_model(
    valid_turn_payload,
):
    client = StubClient('{"utterance":"bu cevap kullanılmamalı"}')
    actor = QwenPersonaActor(client, seed=180)
    state = PersonaState(PersonaId.LEYDI_SERVO, mood="offended", apologies_due=2)
    decision = Decision(
        outcome=DecisionOutcome.REJECT,
        reason_code="leydi_apology_required",
        dialogue_act="DEMAND_APOLOGY_SEQUENCE_BEFORE_ANYTHING_ELSE",
        canonical_reply="Önce kalan iki özür aşamasını tamamlamalısınız.",
        max_sentences=2,
    )

    reply = actor.render(
        decision,
        make_event(valid_turn_payload),
        state,
        RoundState(turn_index=2),
        (),
    )

    assert "2" in reply.utterance
    assert client.calls == []
