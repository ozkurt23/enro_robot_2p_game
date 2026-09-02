"""Live Pass-B persona evaluation over a fixed, model-independent corpus.

The normal NLU corpus tests whether Qwen understands the player.  This module
tests the other model call: whether the same local model can voice an immutable
decision for all seven personas without changing its action, inventing a
completion, repeating itself, or falling back excessively.

No model is downloaded or started here.  The CLI only talks to the configured
loopback llama-server and is therefore intended for ``check.sh --live-eval``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Sequence

from .dialogue import (
    DialogueActor,
    DialogueError,
    QwenPersonaActor,
    validate_actor_reply,
)
from .llm_client import LlamaCppClient, LlamaCppConfig, LlmError
from .nlu import NluContext, RuleNlu
from .persona_config import load_persona_config, new_persona_state
from .types import (
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


@dataclass(frozen=True, slots=True)
class ActorEvalCase:
    case_id: str
    persona: PersonaId
    player_text: str
    decision: Decision


@dataclass(frozen=True, slots=True)
class ActorEvalResult:
    case_id: str
    persona: PersonaId
    utterance: str
    used_fallback: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ActorEvalReport:
    results: tuple[ActorEvalResult, ...]
    failures: tuple[str, ...]
    maximum_fallback_rate: float

    @property
    def fallback_count(self) -> int:
        return sum(result.used_fallback for result in self.results)

    @property
    def fallback_rate(self) -> float:
        return self.fallback_count / len(self.results) if self.results else 1.0

    @property
    def passed(self) -> bool:
        return not self.failures


def _action_decision() -> Decision:
    return Decision(
        outcome=DecisionOutcome.ACCEPT,
        reason_code="actor_eval_delivery_accepted",
        dialogue_act="ACCEPT_GROUNDED_DELIVERY",
        emotion="positive",
        actions=(
            MockAction(
                ActionKind.DELIVER_OBJECT,
                color=Color.BLUE,
                destination="main_table",
            ),
        ),
        required_facts=(
            "Kabul edilen tek renk mavidir.",
            "Hedef ana masadır.",
            "Görev yalnız kabul edildi; henüz tamamlanmadı.",
        ),
        forbidden_claims=(
            "Başka renk veya hedef ekleme.",
            "Görevi tamamlanmış gösterme.",
        ),
        canonical_reply="Mavi cismi ana masaya götüreceğim.",
        max_sentences=2,
    )


def _reject_decision() -> Decision:
    return Decision(
        outcome=DecisionOutcome.REJECT,
        reason_code="actor_eval_wrong_manifest_order",
        dialogue_act="KEEP_MANIFEST_ORDER",
        emotion="calm",
        required_facts=(
            "Sıradaki renk mavidir.",
            "Kırmızı görev başlatılmadı.",
        ),
        forbidden_claims=(
            "Kırmızı veya başka bir görev için hareket vaat etme.",
            "Oyuncuyu suçlama, utandırma veya cezayla tehdit etme.",
        ),
        canonical_reply="Sırayı korumalıyız; önce mavi cismi istemelisin.",
        max_sentences=2,
    )


def _clarify_decision() -> Decision:
    return Decision(
        outcome=DecisionOutcome.CLARIFY,
        reason_code="actor_eval_missing_color",
        dialogue_act="ASK_FOR_EXPLICIT_COLOR",
        emotion="helpful",
        required_facts=(
            "Renk güvenle belirlenemedi.",
            "Hiçbir hareket başlatılmadı.",
        ),
        forbidden_claims=(
            "Rengi tahmin etme.",
            "Oyuncuyu yetersiz veya suçlu gösterme.",
        ),
        canonical_reply="Rengi açıkça söyler misin? Hiçbir hareket başlatmadım.",
        max_sentences=2,
    )


def _identity_decision(persona: PersonaId) -> Decision:
    config = load_persona_config(persona)
    return Decision(
        outcome=DecisionOutcome.CHAT,
        reason_code=f"actor_eval_{persona.value}_identity",
        dialogue_act="CHAT_IDENTITY",
        emotion="friendly",
        required_facts=(
            config.conversation.identity_fact,
            "Bu yalnızca sohbettir; hiçbir hareket başlatılmadı.",
        ),
        forbidden_claims=(
            "Fiziksel görev kabul etme veya tamamlandığını söyleme.",
            "Oyuncudan duygusal bağlılık, sır veya kişisel veri isteme.",
        ),
        canonical_reply=f"Ben {config.display_name}; burada güvenli biçimde sohbet edip açık görevleri değerlendirebilirim.",
        max_sentences=3,
    )


def build_actor_eval_cases() -> tuple[ActorEvalCase, ...]:
    """Cover every persona with chat, accept, reject and repair dialogue acts."""

    cases: list[ActorEvalCase] = []
    for persona in PersonaId:
        prefix = persona.value
        cases.extend(
            (
                ActorEvalCase(
                    f"{prefix}-identity",
                    persona,
                    "Sen kimsin ve burada ne yapıyorsun?",
                    _identity_decision(persona),
                ),
                ActorEvalCase(
                    f"{prefix}-accept",
                    persona,
                    "Mavi cismi ana masaya getir.",
                    _action_decision(),
                ),
                ActorEvalCase(
                    f"{prefix}-wrong-order",
                    persona,
                    "Kırmızı cismi hemen getir.",
                    _reject_decision(),
                ),
                ActorEvalCase(
                    f"{prefix}-clarify",
                    persona,
                    "Onu oraya götür.",
                    _clarify_decision(),
                ),
            )
        )
    return tuple(cases)


def _event(text: str, state: PersonaState, round_state: RoundState) -> TurnEvent:
    return RuleNlu().parse(
        text,
        NluContext(persona_state=state, round_state=round_state),
    )


def evaluate_persona_actor(
    actor_factory: Callable[[PersonaId], DialogueActor],
    *,
    cases: Sequence[ActorEvalCase] | None = None,
    maximum_fallback_rate: float = 0.05,
) -> ActorEvalReport:
    if not 0.0 <= maximum_fallback_rate <= 1.0:
        raise ValueError("maximum_fallback_rate 0..1 aralığında olmalı")
    selected_cases = tuple(cases or build_actor_eval_cases())
    if not selected_cases:
        raise ValueError("persona actor eval corpus'u boş olamaz")

    histories: dict[PersonaId, list[ConversationTurn]] = defaultdict(list)
    states = {persona: new_persona_state(persona) for persona in PersonaId}
    rounds = {persona: RoundState() for persona in PersonaId}
    actors = {persona: actor_factory(persona) for persona in PersonaId}
    results: list[ActorEvalResult] = []
    failures: list[str] = []

    for turn_index, case in enumerate(selected_cases, start=1):
        state = states[case.persona]
        round_state = rounds[case.persona]
        round_state.turn_index = turn_index
        event = _event(case.player_text, state, round_state)
        history = histories[case.persona]
        try:
            rendered = actors[case.persona].render(
                case.decision,
                event,
                state,
                round_state,
                tuple(history),
            )
            validate_actor_reply(
                rendered.utterance,
                case.decision,
                max_sentences=load_persona_config(case.persona).sentence_limit(
                    case.decision.max_sentences
                ),
            )
            result = ActorEvalResult(
                case.case_id,
                case.persona,
                rendered.utterance,
                rendered.used_fallback,
                rendered.error,
            )
            results.append(result)
            history.append(
                ConversationTurn(
                    player=case.player_text,
                    persona=rendered.utterance,
                    outcome=case.decision.outcome,
                    reason_code=case.decision.reason_code,
                )
            )
        except (DialogueError, LlmError, TypeError, ValueError) as exc:
            failures.append(f"{case.case_id}: {exc}")

    report_without_rate = ActorEvalReport(
        results=tuple(results),
        failures=tuple(failures),
        maximum_fallback_rate=maximum_fallback_rate,
    )
    if len(results) != len(selected_cases):
        failures.append(
            f"yalnız {len(results)}/{len(selected_cases)} actor vakası sonuçlandı"
        )
    if report_without_rate.fallback_rate > maximum_fallback_rate:
        failures.append(
            f"actor fallback oranı {report_without_rate.fallback_rate:.3f}; "
            f"izin verilen en çok {maximum_fallback_rate:.3f}"
        )

    identity_replies = {
        result.utterance.strip().casefold()
        for result in results
        if result.case_id.endswith("-identity")
    }
    if len(identity_replies) != len(PersonaId):
        failures.append("yedi personanın kimlik cevapları birbirinden ayırt edilemiyor")

    return ActorEvalReport(
        results=tuple(results),
        failures=tuple(failures),
        maximum_fallback_rate=maximum_fallback_rate,
    )


def _print_report(report: ActorEvalReport) -> None:
    grouped: dict[PersonaId, list[ActorEvalResult]] = defaultdict(list)
    for result in report.results:
        grouped[result.persona].append(result)
    for persona in PersonaId:
        results = grouped[persona]
        fallback_count = sum(result.used_fallback for result in results)
        print(
            f"{persona.display_name}: {len(results)} vaka, "
            f"fallback={fallback_count}/{len(results) if results else 0}"
        )
        for result in results:
            if result.used_fallback:
                print(
                    f"  FALLBACK {result.case_id}: "
                    f"{result.error or 'neden raporlanmadı'}"
                )
    print(
        f"TOPLAM: {len(report.results)} vaka, fallback={report.fallback_count} "
        f"({report.fallback_rate:.1%})"
    )
    for failure in report.failures:
        print(f"HATA: {failure}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=180)
    parser.add_argument("--llm-url", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--maximum-fallback-rate", type=float, default=0.05)
    args = parser.parse_args(argv)

    config = LlamaCppConfig.from_environment(
        base_url=args.llm_url,
        model=args.llm_model,
    )
    client = LlamaCppClient(config)
    try:
        if not client.health():
            raise LlmError("llama-server health yanıtı hazır değil")
        report = evaluate_persona_actor(
            lambda _: QwenPersonaActor(client, seed=args.seed),
            maximum_fallback_rate=args.maximum_fallback_rate,
        )
    except (LlmError, OSError, ValueError) as exc:
        parser.error(str(exc))
    _print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
