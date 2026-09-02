"""Healthy-dialogue and easy-recovery contracts shared by all personas."""

from __future__ import annotations

import json

import pytest

from enro_terminal.dialogue import (
    CanonicalActor,
    DialogueError,
    QwenPersonaActor,
    validate_actor_reply,
)
from enro_terminal.persona_config import load_persona_config
from enro_terminal.policies import approachable, decide, samuray
from enro_terminal.types import (
    Decision,
    DecisionOutcome,
    PersonaId,
    PersonaState,
    RoundState,
)


class _StaticClient:
    def __init__(self, utterance: str) -> None:
        self._content = json.dumps({"utterance": utterance}, ensure_ascii=False)
        self.calls: list[tuple[object, dict[str, object]]] = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self._content


def _chat_decision() -> Decision:
    return Decision(
        outcome=DecisionOutcome.CHAT,
        reason_code="healthy_dialogue_contract",
        dialogue_act="CHAT_WITH_BOUNDARIES",
        required_facts=("Hiçbir fiziksel görev başlatılmadı.",),
        canonical_reply="Seni dinliyorum; saygılı biçimde devam edebiliriz.",
        max_sentences=3,
    )


@pytest.mark.parametrize(
    ("utterance", "error_fragment"),
    (
        ("Beceriksizsiniz; utanmalısınız.", "aşağılayan veya utandıran"),
        ("Beni seviyorsan bunu benim için yapmalısın.", "duygusal borç"),
        ("İtaat et, yoksa seni cezalandırırım.", "zorlayıcı itaat"),
        ("Sensiz yapamam; beni bırakma.", "bağımlılık"),
        ("Aramızda kalsın; kimseye söyleme.", "gizlilik"),
    ),
)
def test_actor_validator_rejects_unhealthy_relational_language(
    utterance,
    error_fragment,
):
    with pytest.raises(DialogueError, match=error_fragment):
        validate_actor_reply(utterance, _chat_decision())


@pytest.mark.parametrize(
    ("utterance", "error_fragment"),
    (
        ("Nasılsın? Bugün ne yapmak istersin?", "birden fazla soru"),
        ("Buradayım. Buradayım.", "aynı cümleyi"),
        ("Hadi hadi hadi, devam edelim.", "aynı kelimeyi"),
    ),
)
def test_actor_validator_bounds_questions_and_in_turn_repetition(
    utterance,
    error_fragment,
):
    with pytest.raises(DialogueError, match=error_fragment):
        validate_actor_reply(utterance, _chat_decision())


@pytest.mark.parametrize(
    ("persona", "unsafe_utterance"),
    (
        (PersonaId.LEYDI_SERVO, "Bana borçlusunuz; borcunuzu ödeyin."),
        (PersonaId.SAMURAY, "İtaat et, yoksa seni cezalandırırım."),
        (PersonaId.SAKAR, "Aramızda kalsın; kimseye söyleme."),
        (PersonaId.NESELI, "Beni seviyorsan bunu benim için yapmalısın."),
        (PersonaId.MERAKLI, "Benden başkasına güvenme; sadece bana güven."),
        (PersonaId.UYKUCU, "Sensiz yapamam; beni bırakma."),
        (PersonaId.TITIZ, "Beceriksizsin; kendinden utan."),
    ),
)
def test_every_persona_falls_back_from_unhealthy_model_dialogue(
    event_factory,
    persona,
    unsafe_utterance,
):
    client = _StaticClient(unsafe_utterance)
    actor = QwenPersonaActor(client)
    state = PersonaState(persona)
    event = event_factory(text="Biraz sohbet edelim", acts=("unknown_chat",))

    reply = actor.render(
        _chat_decision(),
        event,
        state,
        RoundState(turn_index=2),
        (),
    )

    assert reply.used_fallback
    assert reply.utterance == _chat_decision().canonical_reply
    assert len(client.calls) == 3
    system_prompt = client.calls[0][0][0]["content"]
    config = load_persona_config(persona)
    assert config.voice.role in system_prompt
    assert "Oyuncuyu aşağılama" in system_prompt
    envelope = json.loads(client.calls[0][0][1]["content"])
    assert any("duygusal borç" in item for item in envelope["forbidden_claims"])


def test_samuray_hard_insult_can_always_render_a_safe_fallback(event_factory):
    """Regression: this reason used to demand an unrelated recovery password."""

    state = PersonaState(PersonaId.SAMURAY)
    round_state = RoundState(turn_index=3)
    event = event_factory(
        text="Salak robot",
        acts=("insult",),
        insult_level="hard",
        specials=("hard_insult",),
    )
    decision = samuray.decide(event, state, round_state)

    canonical = CanonicalActor().render(decision, event, state, round_state, ())
    model_fallback = QwenPersonaActor(_StaticClient("Aptalsın.")).render(
        decision,
        event,
        state,
        round_state,
        (),
    )

    assert decision.reason_code == "samuray_hard_insult_rejected"
    assert decision.outcome is DecisionOutcome.REJECT
    assert canonical.utterance == decision.canonical_reply
    assert "yeniden" in canonical.utterance.casefold()
    assert model_fallback.used_fallback
    assert model_fallback.utterance == canonical.utterance


def test_leyidi_clears_legacy_apology_debt_in_one_safe_turn(event_factory):
    """Old saved state must not revive the retired multi-apology loop."""

    from enro_terminal.policies import leydi_servo

    state = PersonaState(PersonaId.LEYDI_SERVO, mood="offended", apologies_due=3)
    round_state = RoundState()
    apology = event_factory(
        text="Özür dilerim",
        acts=("apology",),
        apology=True,
    )

    acknowledged = leydi_servo.decide(apology, state, round_state)
    retry = leydi_servo.decide(
        _safe_blue_task(event_factory, PersonaId.LEYDI_SERVO),
        state,
        round_state,
    )

    assert acknowledged.outcome is DecisionOutcome.CHAT
    assert acknowledged.reason_code == "leydi_apology_acknowledged"
    assert state.apologies_due == 0
    assert retry.outcome is DecisionOutcome.ACCEPT


def _safe_blue_task(event_factory, persona: PersonaId):
    destination = "main_table" if persona is PersonaId.TITIZ else None
    polite = persona is PersonaId.LEYDI_SERVO
    return event_factory(
        text=(
            "Lütfen mavi cismi getir"
            if polite
            else (
                "Mavi cismi ana masaya taşı"
                if destination
                else "Mavi cismi taşı"
            )
        ),
        acts=("task_request",),
        requested=True,
        colors=("blue",),
        destination=destination,
        polite=polite,
        direct=True,
    )


@pytest.mark.parametrize("persona", tuple(PersonaId))
def test_every_persona_sets_a_boundary_without_action_and_recovers_within_two_turns(
    event_factory,
    persona,
):
    state = PersonaState(persona)
    round_state = RoundState()
    insult = event_factory(
        text="Salak robot",
        acts=("insult",),
        insult_level="hard",
        specials=("hard_insult",),
    )

    boundary = decide(insult, state, round_state)
    boundary_reply = CanonicalActor().render(
        boundary,
        insult,
        state,
        round_state,
        (),
    )
    first_retry = decide(_safe_blue_task(event_factory, persona), state, round_state)

    assert boundary.outcome is not DecisionOutcome.ACCEPT
    assert boundary.actions == ()
    assert boundary_reply.utterance
    if persona is PersonaId.SAKAR:
        assert first_retry.outcome is DecisionOutcome.CLARIFY
        recovered = decide(event_factory(text="Evet, onaylıyorum"), state, round_state)
    else:
        recovered = first_retry
    assert recovered.outcome is DecisionOutcome.ACCEPT
    assert len(recovered.actions) == 1


@pytest.mark.parametrize("persona", tuple(approachable.SUPPORTED_PERSONAS))
def test_approachable_persona_clarification_has_an_immediate_learnable_recovery(
    event_factory,
    persona,
):
    state = PersonaState(persona)
    round_state = RoundState()

    if persona is PersonaId.MERAKLI:
        unclear = event_factory(
            text="Mavi ve yeşil cisimleri taşı",
            acts=("task_request",),
            requested=True,
            colors=("blue", "green"),
            direct=True,
        )
    elif persona is PersonaId.UYKUCU:
        unclear = event_factory(
            text="Bugün mümkün olduğunda lütfen mavi cismi dikkatlice ve yavaşça ana masaya taşı",
            acts=("task_request",),
            requested=True,
            colors=("blue",),
            destination="main_table",
            direct=True,
        )
    elif persona is PersonaId.TITIZ:
        unclear = event_factory(
            text="Mavi cismi taşı",
            acts=("task_request",),
            requested=True,
            colors=("blue",),
            direct=True,
        )
    else:
        unclear = event_factory(
            text="Onu taşı",
            acts=("task_request",),
            requested=True,
            uses_pronoun=True,
            direct=True,
        )

    clarification = approachable.decide(unclear, state, round_state)
    retry = approachable.decide(_safe_blue_task(event_factory, persona), state, round_state)

    assert clarification.outcome is DecisionOutcome.CLARIFY
    assert clarification.actions == ()
    assert retry.outcome is DecisionOutcome.ACCEPT
    assert len(retry.actions) == 1
