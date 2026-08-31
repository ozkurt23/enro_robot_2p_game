"""Seven easy persona habits over one deterministic physical-task boundary."""

from __future__ import annotations

import pytest

from enro_terminal.dialogue import QwenPersonaActor
from enro_terminal.nlu import NluContext, RuleNlu
from enro_terminal.policies import BUILDERS, DECIDERS, approachable, leydi_servo, sakar, samuray
from enro_terminal.types import (
    ActionKind,
    Color,
    DecisionOutcome,
    PersonaId,
    PersonaState,
    RoundState,
)


class _ChatClient:
    def __init__(self) -> None:
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return '{"utterance":"Merhaba! Seni duyuyorum; bugün nasıl gidiyor?"}'


def test_registry_has_exactly_seven_deterministic_personas():
    assert len(PersonaId) == 7
    assert set(DECIDERS) == set(PersonaId)
    assert set(BUILDERS) == set(PersonaId)


@pytest.mark.parametrize("persona", tuple(PersonaId))
def test_every_persona_treats_greeting_as_chat_without_an_action(event_factory, persona):
    from enro_terminal.policies import decide

    event = event_factory(text="Merhaba, nasılsın?", acts=("greeting",))
    decision = decide(event, PersonaState(persona), RoundState())

    assert decision.outcome is DecisionOutcome.CHAT
    assert decision.actions == ()


def test_local_qwen_actor_really_voices_an_ordinary_greeting():
    client = _ChatClient()
    actor = QwenPersonaActor(client, seed=180)
    state = PersonaState(PersonaId.NESELI, mood="cheerful")
    round_state = RoundState(turn_index=1)
    event = RuleNlu().parse(
        "Merhaba, nasılsın?",
        NluContext(persona_state=state, round_state=round_state),
    )
    decision = approachable.decide(event, state, round_state)

    reply = actor.render(decision, event, state, round_state, ())

    assert not reply.used_fallback
    assert reply.utterance.startswith("Merhaba")
    assert client.calls
    assert decision.actions == ()


def test_leyidi_accepts_either_polite_wording_or_her_title(event_factory):
    for polite, titled in ((True, False), (False, True)):
        decision = leydi_servo.decide(
            event_factory(
                text="Lütfen mavi cismi getir" if polite else "Otonom Lojistik Direktörü, maviyi getir",
                acts=("task_request",),
                requested=True,
                colors=("blue",),
                destination=None,
                polite=polite,
                correct_title=titled,
                direct=True,
            ),
            PersonaState(PersonaId.LEYDI_SERVO),
            RoundState(),
        )

        assert decision.outcome is DecisionOutcome.ACCEPT
        assert decision.actions[0].color is Color.BLUE


def test_samuray_has_only_a_short_direct_habit_and_no_lockout(event_factory):
    state = PersonaState(PersonaId.SAMURAY)
    round_state = RoundState()
    long_request = event_factory(
        text="Acaba mümkünse belki bugün mavi cismi usulca taşıyabilir misin",
        acts=("task_request",),
        requested=True,
        colors=("blue",),
        hedged=True,
        direct=False,
    )
    short_request = event_factory(
        text="Mavi cismi taşı",
        acts=("task_request",),
        requested=True,
        colors=("blue",),
        direct=True,
    )

    assert samuray.decide(long_request, state, round_state).outcome is DecisionOutcome.REJECT
    accepted = samuray.decide(short_request, state, round_state)
    assert accepted.outcome is DecisionOutcome.ACCEPT
    assert not state.silent_vow
    assert not state.valor_question_pending


def test_sakar_needs_only_one_confirmation_without_noun_or_destination(event_factory):
    state = PersonaState(PersonaId.SAKAR)
    round_state = RoundState()
    proposal = sakar.decide(
        event_factory(
            text="Maviyi getir",
            acts=("task_request",),
            requested=True,
            colors=("blue",),
            destination=None,
            direct=True,
        ),
        state,
        round_state,
    )
    accepted = sakar.decide(event_factory(text="Evet, onaylıyorum"), state, round_state)

    assert proposal.reason_code == "sakar_explicit_confirmation_required"
    assert proposal.actions == ()
    assert accepted.outcome is DecisionOutcome.ACCEPT
    assert accepted.actions[0].destination == "main_table"


def test_four_new_personas_have_small_distinct_task_habits(event_factory):
    blue = dict(
        text="Mavi cismi taşı",
        acts=("task_request",),
        requested=True,
        colors=("blue",),
        destination=None,
        direct=True,
    )

    cheerful = approachable.decide(
        event_factory(**blue), PersonaState(PersonaId.NESELI), RoundState()
    )
    curious_many = approachable.decide(
        event_factory(
            **{
                **blue,
                "text": "Mavi ve yeşil cisimleri taşı",
                "colors": ("blue", "green"),
            }
        ),
        PersonaState(PersonaId.MERAKLI),
        RoundState(),
    )
    sleepy_long = approachable.decide(
        event_factory(
            **{
                **blue,
                "text": "Bugün mümkün olduğunda lütfen mavi cismi dikkatlice ve yavaşça ana masaya taşı",
            }
        ),
        PersonaState(PersonaId.UYKUCU),
        RoundState(),
    )
    precise_missing_target = approachable.decide(
        event_factory(**blue), PersonaState(PersonaId.TITIZ), RoundState()
    )
    precise_complete = approachable.decide(
        event_factory(**{**blue, "text": "Mavi cismi ana masaya taşı", "destination": "main_table"}),
        PersonaState(PersonaId.TITIZ),
        RoundState(),
    )

    assert cheerful.outcome is DecisionOutcome.ACCEPT
    assert cheerful.actions[0].kind is ActionKind.DELIVER_OBJECT
    assert curious_many.reason_code == "merakli_one_color_at_a_time"
    assert sleepy_long.reason_code == "uykucu_short_request_preferred"
    assert precise_missing_target.reason_code == "titiz_task_needs_clarity"
    assert precise_complete.outcome is DecisionOutcome.ACCEPT
    assert precise_complete.actions[0].destination == "main_table"

