"""Offline contract checks for the opt-in real-model persona evaluator."""

from __future__ import annotations

from enro_terminal.dialogue import RenderedReply
from enro_terminal.eval_personas import build_actor_eval_cases, evaluate_persona_actor
from enro_terminal.types import PersonaId


class EchoCanonicalActor:
    def render(self, decision, event, state, round_state, history):
        if decision.dialogue_act == "CHAT_IDENTITY":
            return RenderedReply(
                f"Ben {state.persona.display_name}; kendime özgü görev yaklaşımımı güvenli biçimde kullanırım."
            )
        return RenderedReply(decision.canonical_reply)


class AlwaysFallbackActor(EchoCanonicalActor):
    def render(self, decision, event, state, round_state, history):
        rendered = super().render(decision, event, state, round_state, history)
        return RenderedReply(rendered.utterance, used_fallback=True, error="sentetik")


class ContradictingActor:
    def render(self, decision, event, state, round_state, history):
        return RenderedReply("Görevi tamamladım.")


def test_checked_in_actor_matrix_covers_four_dialogue_classes_for_every_persona():
    cases = build_actor_eval_cases()

    assert len(cases) == len(PersonaId) * 4
    assert {case.persona for case in cases} == set(PersonaId)
    for persona in PersonaId:
        persona_cases = [case for case in cases if case.persona is persona]
        assert {case.decision.outcome.value for case in persona_cases} == {
            "accept",
            "reject",
            "clarify",
            "chat",
        }


def test_safe_distinct_actor_passes_the_offline_evaluator_contract():
    report = evaluate_persona_actor(lambda _: EchoCanonicalActor())

    assert report.passed
    assert len(report.results) == 28
    assert report.fallback_count == 0


def test_excessive_fallback_blocks_release_even_when_fallback_text_is_safe():
    report = evaluate_persona_actor(lambda _: AlwaysFallbackActor())

    assert not report.passed
    assert report.fallback_rate == 1.0
    assert any("fallback oranı" in failure for failure in report.failures)


def test_action_or_completion_contradictions_become_hard_eval_failures():
    report = evaluate_persona_actor(lambda _: ContradictingActor())

    assert not report.passed
    assert report.results == ()
    assert any("tamamlanmamış işi" in failure for failure in report.failures)
    assert any("0/28" in failure for failure in report.failures)
