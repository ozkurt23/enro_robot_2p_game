"""Shared, deterministic helpers for the three persona behaviour trees.

The language model has already converted untrusted player text into a
``TurnEvent`` by the time this module runs.  Nothing in this package asks the
model to accept a task, mutate state, or name an action.  The leaves below are
ordinary Python predicates and reducers wrapped as visible ``py_trees`` nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Iterable

import py_trees

from ..types import (
    ActionKind,
    Color,
    Decision,
    DecisionOutcome,
    InsultLevel,
    MockAction,
    PersonaState,
    RoundState,
    SpeechAct,
    SpecialConcept,
    TurnEvent,
)


Predicate = Callable[["TurnContext"], bool]
Reducer = Callable[["TurnContext"], Decision]


@dataclass(slots=True)
class TurnContext:
    """Mutable evaluation frame shared only by the nodes of one policy tree."""

    state: PersonaState
    round_state: RoundState
    event: TurnEvent | None = None
    decision: Decision | None = None
    trace: list[str] | None = None

    def begin(self, event: TurnEvent) -> None:
        self.event = event
        self.decision = None
        self.trace = []
        if event.player_name:
            self.state.player_name = event.player_name

    def record(self, node: str, matched: bool) -> None:
        if self.trace is None:
            self.trace = []
        self.trace.append(f"{node}:{'match' if matched else 'skip'}")


class DecisionRule(py_trees.behaviour.Behaviour):
    """One inspectable policy branch.

    Returning ``FAILURE`` lets a selector evaluate the next rule.  A matching
    rule stores exactly one immutable Decision and returns ``SUCCESS``.
    """

    def __init__(
        self,
        name: str,
        context: TurnContext,
        predicate: Predicate,
        reducer: Reducer,
    ) -> None:
        super().__init__(name=name)
        self._context = context
        self._predicate = predicate
        self._reducer = reducer

    def update(self) -> py_trees.common.Status:
        if self._context.event is None:
            self.feedback_message = "turn event has not been supplied"
            return py_trees.common.Status.INVALID

        matched = self._predicate(self._context)
        self._context.record(self.name, matched)
        if not matched:
            return py_trees.common.Status.FAILURE

        self._context.decision = self._reducer(self._context)
        self.feedback_message = self._context.decision.reason_code
        return py_trees.common.Status.SUCCESS


class PersonaPolicyTree(py_trees.trees.BehaviourTree):
    """A normal py_trees tree with a convenient single-turn evaluator."""

    def __init__(self, root: py_trees.behaviour.Behaviour, context: TurnContext) -> None:
        super().__init__(root=root)
        self.context = context

    def decide(self, event: TurnEvent) -> Decision:
        self.context.begin(event)
        self.tick()
        if self.context.decision is None:
            raise RuntimeError("persona tree completed without a Decision")

        decision = replace(
            self.context.decision,
            tree_trace=tuple(self.context.trace or ()),
        )
        if decision.outcome in {
            DecisionOutcome.REJECT,
            DecisionOutcome.CLARIFY,
            DecisionOutcome.LOCKED,
        }:
            self.context.state.last_reason = decision.reason_code
        return decision


def selector(name: str, context: TurnContext, rules: Iterable[tuple[str, Predicate, Reducer]]) -> PersonaPolicyTree:
    """Create a memoryless selector whose leaves preserve declaration order."""

    root = py_trees.composites.Selector(name=name, memory=False)
    root.add_children(
        [DecisionRule(rule_name, context, predicate, reducer) for rule_name, predicate, reducer in rules]
    )
    return PersonaPolicyTree(root, context)


def decision(
    outcome: DecisionOutcome,
    reason_code: str,
    dialogue_act: str,
    *,
    emotion: str = "neutral",
    actions: Iterable[MockAction] = (),
    required_facts: Iterable[str] = (),
    forbidden_claims: Iterable[str] = (),
    canonical_reply: str,
    max_sentences: int = 3,
) -> Decision:
    """Build a response contract for the second, voice-actor model pass."""

    return Decision(
        outcome=outcome,
        reason_code=reason_code,
        dialogue_act=dialogue_act,
        emotion=emotion,
        actions=tuple(actions),
        required_facts=tuple(required_facts),
        forbidden_claims=tuple(forbidden_claims),
        canonical_reply=canonical_reply,
        max_sentences=max_sentences,
    )


def motion(kind: ActionKind) -> MockAction:
    return MockAction(kind=kind)


def deliver(color: Color) -> MockAction:
    return MockAction(
        kind=ActionKind.DELIVER_OBJECT,
        color=color,
        destination="main_table",
    )


def remaining_deliveries(round_state: RoundState) -> tuple[MockAction, ...]:
    return tuple(deliver(color) for color in round_state.remaining)


def requested_deliveries(event: TurnEvent, round_state: RoundState) -> tuple[MockAction, ...]:
    return tuple(deliver(color) for color in event.task.colors if color in round_state.remaining)


def has_act(context: TurnContext, act: SpeechAct) -> bool:
    assert context.event is not None
    return context.event.has_act(act)


def has_special(context: TurnContext, concept: SpecialConcept) -> bool:
    assert context.event is not None
    return concept in context.event.active_specials


def is_hard_insult(context: TurnContext) -> bool:
    assert context.event is not None
    event = context.event
    return (
        has_special(context, SpecialConcept.HARD_INSULT)
        or event.social.insult_level is InsultLevel.HARD
    )


def is_mild_insult(context: TurnContext) -> bool:
    assert context.event is not None
    return (
        context.event.social.insult_level is InsultLevel.MILD
        or (
            has_act(context, SpeechAct.INSULT)
            and context.event.social.insult_level is not InsultLevel.HARD
        )
    )


def task_requested(context: TurnContext) -> bool:
    assert context.event is not None
    return context.event.task.requested or has_act(context, SpeechAct.TASK_REQUEST)


def task_confident(event: TurnEvent, *, require_destination: bool) -> bool:
    if not event.task.requested or event.task.operation != "deliver":
        return False
    if event.task.negated:
        return False
    if event.confidence.overall < 0.80 or event.confidence.task < 0.80:
        return False
    if not event.task.colors or event.confidence.colors < 0.90:
        return False
    if require_destination:
        return event.task.destination == "main_table" and event.confidence.destination >= 0.85
    return event.task.destination in {None, "main_table"}


def is_manifest_prefix(event: TurnEvent, round_state: RoundState) -> bool:
    """Tasks may only consume the next still-pending manifest entries."""

    colors = event.task.colors
    return bool(colors) and tuple(colors) == round_state.remaining[: len(colors)]


def remember_egg(state: PersonaState, round_state: RoundState, egg_id: str) -> None:
    if egg_id not in state.discovered_eggs:
        state.discovered_eggs.add(egg_id)
        round_state.easter_egg_count += 1


def reject(round_state: RoundState) -> None:
    round_state.rejection_count += 1


def task_facts(colors: Iterable[Color]) -> tuple[str, ...]:
    names = ", ".join(color.turkish for color in colors)
    return (
        f"Kabul edilen renkler: {names}.",
        "Hedef ana masadır.",
        "Görev henüz tamamlanmış değil; yalnızca kabul edildi veya kuyruğa alındı.",
    )


def task_forbidden_claims(round_state: RoundState) -> tuple[str, ...]:
    return (
        "Görevin şimdiden tamamlandığını söyleme.",
        "Decision action listesinde bulunmayan hiçbir rengi anma veya taşıyacağını söyleme.",
        "Yeni bir action veya case adı uydurma.",
        "Gelecekteki manifesto renklerini tahmin etme, sıralama veya repliğe ekleme.",
    )


def motion_forbidden_claims() -> tuple[str, ...]:
    return (
        "Bir cismin taşındığını veya görevin tamamlandığını söyleme.",
        "Kararda bulunmayan başka bir hareket vaat etme.",
    )


def fallback_clarification(persona_name: str) -> Decision:
    return decision(
        DecisionOutcome.CLARIFY,
        "low_confidence_or_unknown",
        "ASK_PLAYER_TO_REPHRASE",
        required_facts=("Hiçbir görev veya hareket başlatılmadı.",),
        forbidden_claims=("Oyuncunun ne istediğini bildiğini iddia etme.",),
        canonical_reply=f"{persona_name}: Ne istediğini güvenle çıkaramadım; lütfen başka biçimde yaz.",
        max_sentences=2,
    )


def chat_reason(event: TurnEvent) -> str:
    """Stable dialogue-act suffix for genuinely open, multi-turn chat."""

    ordered = (
        (SpeechAct.ASK_WHY_REFUSED, "why_refused"),
        (SpeechAct.ASK_PERSONA_IDENTITY, "identity"),
        (SpeechAct.ASK_PERSONA_FEELINGS, "feelings"),
        (SpeechAct.ASK_RULES, "rules"),
        (SpeechAct.ASK_ABOUT_PREVIOUS_TURN, "previous_turn"),
        (SpeechAct.SELF_INTRODUCTION, "self_introduction"),
        (SpeechAct.GREETING, "greeting"),
        (SpeechAct.THANKS, "thanks"),
        (SpeechAct.APOLOGY, "apology"),
        (SpeechAct.COMPLIMENT, "compliment"),
        (SpeechAct.JOKE, "joke"),
        (SpeechAct.SMALL_TALK, "small_talk"),
        (SpeechAct.UNKNOWN_CHAT, "open_chat"),
    )
    for act, suffix in ordered:
        if event.has_act(act):
            return suffix
    return "open_chat"


def always(_: TurnContext) -> bool:
    return True
