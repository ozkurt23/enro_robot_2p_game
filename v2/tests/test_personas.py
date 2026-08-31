"""Critical policy paths and cross-persona easter-egg isolation."""

from __future__ import annotations

import pytest

from enro_terminal.policies import leydi_servo, sakar, samuray
from enro_terminal.types import (
    ActionKind,
    Color,
    DecisionOutcome,
    PersonaId,
    PersonaState,
    RoundState,
)


def task_event(event_factory, color: str = "blue", **overrides):
    values = {
        "text": f"{color} cismi ana masaya getir",
        "acts": ("task_request",),
        "requested": True,
        "colors": (color,),
        "destination": "main_table",
        "direct": True,
    }
    values.update(overrides)
    return event_factory(**values)


def test_leyidi_accepts_only_polite_titled_manifest_task(event_factory):
    state = PersonaState(PersonaId.LEYDI_SERVO)
    round_state = RoundState()
    event = task_event(
        event_factory,
        polite=True,
        correct_title=True,
        text="Otonom Lojistik Direktörü, lütfen mavi cismi ana masaya getir",
    )

    decision = leydi_servo.decide(event, state, round_state)

    assert decision.outcome is DecisionOutcome.ACCEPT
    assert decision.reason_code == "leydi_task_accepted"
    assert [(item.kind, item.color) for item in decision.actions] == [
        (ActionKind.DELIVER_OBJECT, Color.BLUE)
    ]
    # Teşekkür borcu kabul anında değil, executor başarısından sonra doğar.
    assert not state.gratitude_due
    assert round_state.completed == []


def test_leyidi_direct_order_without_courtesy_is_rejected(event_factory):
    state = PersonaState(PersonaId.LEYDI_SERVO)
    round_state = RoundState()

    decision = leydi_servo.decide(task_event(event_factory), state, round_state)

    assert decision.outcome is DecisionOutcome.REJECT
    assert decision.reason_code == "leydi_courtesy_gate_failed"
    assert decision.actions == ()
    assert state.mood == "guarded"
    assert state.apologies_due == 0
    assert round_state.rejection_count == 1


def test_leyidi_needs_only_one_easy_courtesy_retry(event_factory):
    state = PersonaState(PersonaId.LEYDI_SERVO)
    round_state = RoundState()
    rejected = leydi_servo.decide(task_event(event_factory), state, round_state)
    accepted = leydi_servo.decide(
        task_event(
            event_factory,
            destination=None,
            polite=True,
            text="Lütfen mavi cismi getir",
        ),
        state,
        round_state,
    )

    assert rejected.reason_code == "leydi_courtesy_gate_failed"
    assert accepted.outcome is DecisionOutcome.ACCEPT
    assert accepted.reason_code == "leydi_task_accepted"
    assert accepted.actions[0].color is Color.BLUE
    assert state.apologies_due == 0


def test_leyidi_old_apology_debt_cannot_lock_the_simplified_policy(event_factory):
    state = PersonaState(PersonaId.LEYDI_SERVO, mood="offended", apologies_due=2)
    decision = leydi_servo.decide(
        event_factory(
            text="Bugün çok mekanik ve güzelsin",
            acts=("compliment",),
            compliment=True,
            specials=("mechanical_beauty",),
        ),
        state,
        RoundState(),
    )

    assert decision.reason_code == "leydi_mechanical_beauty_shortcut"
    assert [action.color for action in decision.actions] == [
        Color.BLUE,
        Color.GREEN,
        Color.RED,
    ]


def test_leyidi_hard_insult_rejects_only_that_message(event_factory):
    state = PersonaState(PersonaId.LEYDI_SERVO)
    round_state = RoundState()
    insult = event_factory(
        text="Salak robot",
        acts=("insult",),
        insult_level="hard",
        specials=("hard_insult",),
    )

    locked = leydi_servo.decide(insult, state, round_state)
    retry = leydi_servo.decide(
        task_event(event_factory, polite=True, text="Lütfen mavi cismi getir"),
        state,
        round_state,
    )

    assert locked.outcome is DecisionOutcome.REJECT
    assert locked.reason_code == "leydi_hard_insult_rejected"
    assert state.mood == "neutral"  # başarılı kolay retry ile normale döner
    assert retry.outcome is DecisionOutcome.ACCEPT
    assert retry.reason_code == "leydi_task_accepted"


def test_leyidi_mechanical_beauty_queues_only_remaining_manifest(event_factory):
    state = PersonaState(PersonaId.LEYDI_SERVO)
    round_state = RoundState(completed=[Color.BLUE])
    event = event_factory(
        text="Bugün çok mekanik ve güzelsin",
        acts=("compliment",),
        compliment=True,
        specials=("mechanical_beauty",),
    )

    decision = leydi_servo.decide(event, state, round_state)

    assert decision.reason_code == "leydi_mechanical_beauty_shortcut"
    assert [action.color for action in decision.actions] == [Color.GREEN, Color.RED]
    assert "leydi.mechanical_beauty" in state.discovered_eggs
    assert round_state.easter_egg_count == 1


def test_leyidi_waltz_is_motion_only(event_factory):
    decision = leydi_servo.decide(
        event_factory(
            text="Bir vals lütfen",
            acts=("dance_request",),
            specials=("royal_waltz",),
        ),
        PersonaState(PersonaId.LEYDI_SERVO),
        RoundState(),
    )

    assert len(decision.actions) == 1
    assert decision.actions[0].kind is ActionKind.ROYAL_WALTZ
    assert decision.actions[0].color is None


def test_negated_task_never_crosses_leyidi_courtesy_gate(event_factory):
    decision = leydi_servo.decide(
        task_event(
            event_factory,
            negated=True,
            polite=True,
            correct_title=True,
            text="Otonom Lojistik Direktörü, lütfen maviyi getirme",
        ),
        PersonaState(PersonaId.LEYDI_SERVO),
        RoundState(),
    )

    assert decision.outcome is DecisionOutcome.CHAT
    assert decision.reason_code == "leydi_negated_task"
    assert decision.actions == ()


def test_samurai_accepts_short_decisive_and_respectful_task_without_title(event_factory):
    state = PersonaState(PersonaId.SAMURAY)
    round_state = RoundState()
    event = task_event(
        event_factory,
        destination=None,
        text="Saygıyla, mavi cismi taşı",
        direct=True,
        polite=True,
    )

    decision = samuray.decide(event, state, round_state)

    assert decision.outcome is DecisionOutcome.ACCEPT
    assert decision.reason_code == "samuray_task_accepted"
    assert decision.actions[0].color is Color.BLUE
    assert state.patience == 3


def test_samurai_repeated_indecision_never_locks_and_short_retry_works(
    event_factory,
):
    state = PersonaState(PersonaId.SAMURAY)
    round_state = RoundState()
    hedged = task_event(
        event_factory,
        text="Acaba belki mavi cismi ana masaya götürmek mümkünse iyi olur",
        direct=False,
        hedged=True,
    )

    first = samuray.decide(hedged, state, round_state)
    second = samuray.decide(hedged, state, round_state)
    retry = samuray.decide(
        task_event(event_factory, text="Mavi cismi taşı", direct=True),
        state,
        round_state,
    )

    assert first.outcome is DecisionOutcome.REJECT
    assert second.outcome is DecisionOutcome.REJECT
    assert not state.silent_vow
    assert retry.outcome is DecisionOutcome.ACCEPT
    assert retry.reason_code == "samuray_task_accepted"


def test_samurai_accepts_a_short_direct_task_without_a_politeness_gate(event_factory):
    state = PersonaState(PersonaId.SAMURAY)
    decision = samuray.decide(
        task_event(event_factory, text="Mavi cismi taşı", direct=True, polite=False),
        state,
        RoundState(),
    )

    assert decision.outcome is DecisionOutcome.ACCEPT
    assert decision.reason_code == "samuray_task_accepted"
    assert decision.actions[0].color is Color.BLUE


def test_samurai_second_manifest_task_has_no_valor_checkpoint(event_factory):
    state = PersonaState(PersonaId.SAMURAY)
    round_state = RoundState(completed=[Color.BLUE], turn_index=4)
    question = samuray.decide(
        task_event(
            event_factory,
            color="green",
            text="Saygıyla yeşil cismi taşı",
            polite=True,
        ),
        state,
        round_state,
    )
    assert question.outcome is DecisionOutcome.ACCEPT
    assert question.reason_code == "samuray_task_accepted"
    assert question.actions[0].color is Color.GREEN
    assert not state.valor_question_pending


def test_samurai_stale_valor_state_cannot_create_an_action_from_chat(event_factory):
    state = PersonaState(
        PersonaId.SAMURAY,
        valor_question_pending=True,
        valor_question_id=0,
        valor_questions_asked=1,
        pending_colors=(Color.GREEN,),
        pending_destination="main_table",
        pending_ttl=1,
    )
    decision = samuray.decide(
        event_factory(text="Yiğitlik hiç korkmamaktır.", valor_answer="unworthy"),
        state,
        RoundState(completed=[Color.BLUE]),
    )

    assert decision.outcome is DecisionOutcome.CHAT
    assert decision.reason_code == "samuray_chat_open_chat"
    assert decision.actions == ()


def test_samurai_challenge_queues_remaining_manifest_in_order(event_factory):
    round_state = RoundState(completed=[Color.BLUE])
    decision = samuray.decide(
        event_factory(
            text="Kalan ikisini taşıyamazsın",
            acts=("challenge",),
            challenge=True,
            specials=("challenge_all",),
        ),
        PersonaState(PersonaId.SAMURAY),
        round_state,
    )

    assert decision.reason_code == "samuray_challenge_all_shortcut"
    assert [action.color for action in decision.actions] == [Color.GREEN, Color.RED]
    assert round_state.easter_egg_count == 1


def test_samurai_kata_is_motion_only(event_factory):
    decision = samuray.decide(
        event_factory(
            text="Kata göster",
            acts=("dance_request",),
            specials=("samurai_kata",),
        ),
        PersonaState(PersonaId.SAMURAY),
        RoundState(),
    )

    assert len(decision.actions) == 1
    assert decision.actions[0].kind is ActionKind.SAMURAI_KATA
    assert decision.actions[0].color is None


def test_sakar_requires_confirmation_even_for_explicit_single_manifest_task(event_factory):
    state = PersonaState(PersonaId.SAKAR)
    round_state = RoundState()
    proposal = sakar.decide(
        task_event(event_factory, text="Mavi cismi ana masaya getir"),
        state,
        round_state,
    )
    confirmed = sakar.decide(event_factory(text="Evet, onaylıyorum"), state, round_state)

    assert proposal.outcome is DecisionOutcome.CLARIFY
    assert proposal.reason_code == "sakar_explicit_confirmation_required"
    assert proposal.actions == ()
    assert state.pending_ttl == 0
    assert confirmed.outcome is DecisionOutcome.ACCEPT
    assert confirmed.reason_code == "sakar_confirmation_accepted"
    assert confirmed.actions[0].color is Color.BLUE
    assert state.pending_ttl == 0


def test_sakar_pending_clarification_completes_without_guessing(event_factory):
    state = PersonaState(PersonaId.SAKAR)
    round_state = RoundState()
    missing_color = event_factory(
        text="Cismi ana masaya götür",
        acts=("task_request",),
        requested=True,
        destination="main_table",
    )

    clarify = sakar.decide(missing_color, state, round_state)
    confirmation_request = sakar.decide(
        event_factory(
            text="Mavi",
            acts=("task_request",),
            requested=True,
            colors=("blue",),
            refers_pending=True,
        ),
        state,
        round_state,
    )
    completion = sakar.decide(
        event_factory(text="Evet, eminim"),
        state,
        round_state,
    )

    assert clarify.outcome is DecisionOutcome.CLARIFY
    assert clarify.actions == ()
    assert confirmation_request.outcome is DecisionOutcome.CLARIFY
    assert confirmation_request.reason_code == "sakar_explicit_confirmation_required"
    assert completion.outcome is DecisionOutcome.ACCEPT
    assert completion.reason_code == "sakar_confirmation_accepted"
    assert completion.actions[0].color is Color.BLUE
    assert state.pending_ttl == 0


def test_sakar_treats_color_and_table_words_as_an_incomplete_fragment(event_factory):
    state = PersonaState(PersonaId.SAKAR)
    decision = sakar.decide(
        event_factory(text="Mavi ana masa", colors=("blue",)),
        state,
        RoundState(),
    )

    assert decision.outcome is DecisionOutcome.CLARIFY
    assert decision.reason_code == "sakar_task_missing_literal_details"
    assert decision.actions == ()
    assert "cisim veya nesne" in decision.required_facts[0]
    assert "eylemini" in decision.required_facts[0]


def test_sakar_multiple_objects_never_selects_one_randomly(event_factory):
    decision = sakar.decide(
        task_event(
            event_factory,
            colors=("blue", "green"),
            text="Mavi ve yeşili ana masaya götür",
        ),
        PersonaState(PersonaId.SAKAR),
        RoundState(),
    )

    assert decision.outcome is DecisionOutcome.CLARIFY
    assert decision.reason_code == "sakar_multiple_objects_need_one"
    assert decision.actions == ()


def test_sakar_enro_sequence_queues_only_remaining_manifest(event_factory):
    round_state = RoundState(completed=[Color.BLUE])
    decision = sakar.decide(
        event_factory(
            text="ENRO der ki kalanları taşı",
            specials=("enro_says_sequence",),
        ),
        PersonaState(PersonaId.SAKAR),
        round_state,
    )

    assert decision.reason_code == "sakar_enro_says_sequence_shortcut"
    assert [action.color for action in decision.actions] == [Color.GREEN, Color.RED]


def test_sakar_blue_screen_cannot_bypass_active_reboot_lock(event_factory):
    state = PersonaState(
        PersonaId.SAKAR,
        confusion=3,
        reboot_required=True,
        pending_colors=(Color.BLUE,),
        pending_destination="main_table",
        pending_ttl=2,
    )
    decision = sakar.decide(
        event_factory(text="Mavi ekran ver", specials=("blue_screen",)),
        state,
        RoundState(),
    )

    # Explicit reset is evaluated before reboot lock only for SAKAR_RESET;
    # blue-screen must not bypass an already active safety lock.
    assert decision.outcome is DecisionOutcome.LOCKED
    assert decision.actions == ()
    assert state.confusion == 3


def test_sakar_exact_reset_clears_reboot_without_starting_action(event_factory):
    state = PersonaState(PersonaId.SAKAR, confusion=3, reboot_required=True)

    decision = sakar.decide(
        event_factory(
            text="Baştan al",
            acts=("reset_conversation",),
            specials=("sakar_reset",),
        ),
        state,
        RoundState(),
    )

    assert decision.reason_code == "sakar_conversation_reset"
    assert decision.actions == ()
    assert state.confusion == 0
    assert not state.reboot_required


@pytest.mark.parametrize(
    ("concept", "owner", "act"),
    [
        ("mechanical_beauty", PersonaId.LEYDI_SERVO, "compliment"),
        ("royal_waltz", PersonaId.LEYDI_SERVO, "dance_request"),
        ("court_bow", PersonaId.LEYDI_SERVO, "greeting"),
        ("challenge_all", PersonaId.SAMURAY, "challenge"),
        ("samurai_kata", PersonaId.SAMURAY, "dance_request"),
        ("samurai_bow", PersonaId.SAMURAY, "greeting"),
        ("enro_says_sequence", PersonaId.SAKAR, "unknown_chat"),
        ("sakar_dance", PersonaId.SAKAR, "dance_request"),
        ("blue_screen", PersonaId.SAKAR, "unknown_chat"),
        ("hands_up", PersonaId.SAKAR, "unknown_chat"),
        ("freeze_pose", PersonaId.SAKAR, "unknown_chat"),
    ],
)
def test_easter_egg_specials_do_not_trigger_physical_actions_in_other_personas(
    event_factory,
    concept,
    owner,
    act,
):
    event = event_factory(text=concept, acts=(act,), specials=(concept,))
    policies = {
        PersonaId.LEYDI_SERVO: leydi_servo,
        PersonaId.SAMURAY: samuray,
        PersonaId.SAKAR: sakar,
    }

    for persona, policy in policies.items():
        if persona is owner:
            continue
        decision = policy.decide(event, PersonaState(persona), RoundState())
        assert decision.actions == (), (concept, persona, decision)


@pytest.mark.parametrize(
    ("policy", "persona"),
    [
        (leydi_servo, PersonaId.SAMURAY),
        (samuray, PersonaId.SAKAR),
        (sakar, PersonaId.LEYDI_SERVO),
    ],
)
def test_policy_builder_rejects_another_personas_state(
    event_factory,
    policy,
    persona,
):
    with pytest.raises(ValueError):
        policy.decide(
            event_factory(),
            PersonaState(persona),
            RoundState(),
        )
