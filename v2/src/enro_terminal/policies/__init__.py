"""Persona policy registry.

All public decisions pass through one of seven deterministic py_trees
policies.  There is deliberately no LLM-selected fallback policy.
"""

from __future__ import annotations

from collections.abc import Callable

from ..types import Decision, PersonaId, PersonaState, RoundState, TurnEvent
from . import approachable, leydi_servo, sakar, samuray
from .common import PersonaPolicyTree


PolicyDecider = Callable[[TurnEvent, PersonaState, RoundState], Decision]
PolicyBuilder = Callable[[PersonaState, RoundState], PersonaPolicyTree]


DECIDERS: dict[PersonaId, PolicyDecider] = {
    PersonaId.LEYDI_SERVO: leydi_servo.decide,
    PersonaId.SAMURAY: samuray.decide,
    PersonaId.SAKAR: sakar.decide,
    PersonaId.NESELI: approachable.decide,
    PersonaId.MERAKLI: approachable.decide,
    PersonaId.UYKUCU: approachable.decide,
    PersonaId.TITIZ: approachable.decide,
}

BUILDERS: dict[PersonaId, PolicyBuilder] = {
    PersonaId.LEYDI_SERVO: leydi_servo.build_tree,
    PersonaId.SAMURAY: samuray.build_tree,
    PersonaId.SAKAR: sakar.build_tree,
    PersonaId.NESELI: approachable.build_tree,
    PersonaId.MERAKLI: approachable.build_tree,
    PersonaId.UYKUCU: approachable.build_tree,
    PersonaId.TITIZ: approachable.build_tree,
}


def decide(event: TurnEvent, state: PersonaState, round_state: RoundState) -> Decision:
    """Route a validated turn to the state object's authoritative persona."""

    return DECIDERS[state.persona](event, state, round_state)


def build_tree(state: PersonaState, round_state: RoundState) -> PersonaPolicyTree:
    """Build the selected persona's inspectable, reusable behaviour tree."""

    return BUILDERS[state.persona](state, round_state)


# Descriptive alias for callers that prefer making the dispatch explicit.
build_tree_for_persona = build_tree


__all__ = [
    "BUILDERS",
    "DECIDERS",
    "PersonaPolicyTree",
    "build_tree",
    "build_tree_for_persona",
    "decide",
    "approachable",
    "leydi_servo",
    "sakar",
    "samuray",
]
