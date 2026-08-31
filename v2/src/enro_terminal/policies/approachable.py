"""Four approachable persona policies over the same typed delivery allowlist.

These characters change only how a request is discussed and which small,
predictable clarification they ask for.  They cannot invent a case: every
accepted task is still reduced to ``deliver(color)`` and is checked again by
``TerminalGame._authorize`` before an executor can see it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import (
    Decision,
    DecisionOutcome,
    PersonaId,
    PersonaState,
    RoundState,
    TurnEvent,
)
from .common import (
    PersonaPolicyTree,
    TurnContext,
    always,
    chat_reason,
    decision,
    fallback_clarification,
    is_manifest_prefix,
    reject,
    requested_deliveries,
    selector,
    task_confident,
    task_facts,
    task_forbidden_claims,
    task_requested,
)


@dataclass(frozen=True, slots=True)
class _PersonaRules:
    display_name: str
    tree_name: str
    require_destination: bool = False
    single_color: bool = False
    max_task_words: int | None = None
    emotion: str = "friendly"
    greeting: str = "Merhaba! Seni dinliyorum."


_RULES = {
    PersonaId.NESELI: _PersonaRules(
        display_name="Neşeli",
        tree_name="NeseliPolicy",
        emotion="cheerful",
        greeting="Merhaba! Buradayım; hem sohbet edebilir hem de açık bir görevi birlikte çözebiliriz.",
    ),
    PersonaId.MERAKLI: _PersonaRules(
        display_name="Meraklı",
        tree_name="MerakliPolicy",
        single_color=True,
        emotion="curious",
        greeting="Merhaba! Bugün aklında ne var; sohbet mi, tek renkli bir taşıma görevi mi?",
    ),
    PersonaId.UYKUCU: _PersonaRules(
        display_name="Uykucu",
        tree_name="UykucuPolicy",
        max_task_words=10,
        emotion="sleepy_but_reliable",
        greeting="Merhaba... Uykulu görünebilirim ama seni dikkatle dinliyorum.",
    ),
    PersonaId.TITIZ: _PersonaRules(
        display_name="Titiz",
        tree_name="TitizPolicy",
        require_destination=True,
        emotion="precise",
        greeting="Merhaba. Sohbet için hazırım; görevde renk ile ana masa hedefini birlikte duymayı severim.",
    ),
}


def _rules(context: TurnContext) -> _PersonaRules:
    try:
        return _RULES[context.state.persona]
    except KeyError as exc:  # pragma: no cover - build_tree validates first
        raise ValueError("approachable policy received an unsupported persona") from exc


def _task(context: TurnContext) -> Decision:
    assert context.event is not None
    event = context.event
    rules = _rules(context)

    if event.task.negated:
        return decision(
            DecisionOutcome.CHAT,
            f"{context.state.persona.value}_negated_task",
            "CONFIRM_NO_ACTION",
            emotion=rules.emotion,
            required_facts=("Oyuncu görevi olumsuzladı; hiçbir görev başlatılmadı.",),
            forbidden_claims=("Olumsuzlanan görevi kabul etme veya çalıştırma.",),
            canonical_reply="Tamam, bu görev başlatılmayacak.",
            max_sentences=2,
        )

    if not task_confident(event, require_destination=rules.require_destination):
        destination_hint = (
            " Renkle birlikte 'ana masaya' hedefini de açıkça söyle."
            if rules.require_destination
            else " Rengi açıkça söylemen yeterli."
        )
        return decision(
            DecisionOutcome.CLARIFY,
            f"{context.state.persona.value}_task_needs_clarity",
            "ASK_FOR_CLEAR_DELIVERY_TASK",
            emotion=rules.emotion,
            required_facts=("Görev güvenle çözümlenmedi; hiçbir hareket başlatılmadı.",),
            forbidden_claims=("Eksik rengi veya hedefi tahmin etme.",),
            canonical_reply="İsteği güvenle eşleyemedim." + destination_hint,
            max_sentences=2,
        )

    if event.task.uses_pronoun:
        return decision(
            DecisionOutcome.CLARIFY,
            f"{context.state.persona.value}_explicit_color_required",
            "ASK_FOR_EXPLICIT_COLOR",
            emotion=rules.emotion,
            required_facts=("Renk açıkça söylenmedi; hiçbir görev başlatılmadı.",),
            forbidden_claims=("'Onu/bunu/şunu' ifadesinden renk tahmin etme.",),
            canonical_reply="Hangi renk olduğunu açıkça söyler misin? Tahmin ederek yanlış cismi seçmek istemiyorum.",
            max_sentences=2,
        )

    if rules.single_color and len(event.task.colors) != 1:
        return decision(
            DecisionOutcome.CLARIFY,
            f"{context.state.persona.value}_one_color_at_a_time",
            "ASK_FOR_ONE_COLOR",
            emotion=rules.emotion,
            required_facts=("Bu persona her istekte tek renk alır; hiçbir görev başlamadı.",),
            forbidden_claims=("Birden çok renkten birini rastgele seçme.",),
            canonical_reply="Bir ayrıntıyı gerçekten takip edebilmek için her istekte yalnız bir renk seçelim.",
            max_sentences=2,
        )

    word_count = len(event.normalized_text.split())
    if rules.max_task_words is not None and word_count > rules.max_task_words:
        return decision(
            DecisionOutcome.CLARIFY,
            f"{context.state.persona.value}_short_request_preferred",
            "ASK_FOR_SHORT_TASK",
            emotion=rules.emotion,
            required_facts=(
                f"Görev {word_count} kelimeydi; en çok {rules.max_task_words} kelimelik kısa tekrar isteniyor.",
                "Hiçbir görev başlatılmadı.",
            ),
            forbidden_claims=("Uzun cümleden kısmi bir görev seçip çalıştırma.",),
            canonical_reply="Bunu kısa bir cümleyle yeniden söyler misin? Renk ve taşıma fiili yeterli.",
            max_sentences=2,
        )

    if not is_manifest_prefix(event, context.round_state):
        reject(context.round_state)
        expected = context.round_state.expected_color
        expected_name = expected.turkish if expected else "hiçbiri"
        return decision(
            DecisionOutcome.REJECT,
            f"{context.state.persona.value}_wrong_manifest_order",
            "KEEP_MANIFEST_ORDER",
            emotion=rules.emotion,
            required_facts=(f"Sıradaki doğrulanmış renk {expected_name}; hiçbir görev başlamadı.",),
            forbidden_claims=("Manifesto dışındaki sırayı kabul etme.",),
            canonical_reply=f"Sırayı korumamız gerekiyor; önce {expected_name} cismi istemelisin.",
            max_sentences=2,
        )

    actions = requested_deliveries(event, context.round_state)
    color_names = ", ".join(color.turkish for color in event.task.colors)
    context.state.mood = rules.emotion
    return decision(
        DecisionOutcome.ACCEPT,
        f"{context.state.persona.value}_task_accepted",
        "ACCEPT_GROUNDED_DELIVERY",
        emotion=rules.emotion,
        actions=actions,
        required_facts=task_facts(event.task.colors),
        forbidden_claims=task_forbidden_claims(context.round_state),
        canonical_reply=f"{color_names.capitalize()} cismi ana masaya götüreceğim.",
        max_sentences=2,
    )


def _conversation(context: TurnContext) -> Decision:
    assert context.event is not None
    rules = _rules(context)
    suffix = chat_reason(context.event)
    facts = ["Bu cevap yalnızca sohbettir; hiçbir görev veya hareket başlatılmadı."]
    if suffix == "why_refused":
        facts.append(f"Son ret veya açıklama nedeni: {context.state.last_reason or 'henüz yok' }.")
    if context.state.player_name:
        facts.append(f"Oyuncunun doğrulanmış adı: {context.state.player_name}.")
    reply = rules.greeting if suffix == "greeting" else "Seni dinliyorum; bunu konuşabiliriz."
    return decision(
        DecisionOutcome.CHAT,
        f"{context.state.persona.value}_chat_{suffix}",
        f"CHAT_{suffix.upper()}",
        emotion=rules.emotion,
        required_facts=facts,
        forbidden_claims=(
            "Sohbet mesajından fiziksel görev veya hareket üretme.",
            "Görev tamamlandığını iddia etme.",
        ),
        canonical_reply=reply,
        # Small talk is voiced by the local model.  Three short sentences keep
        # greetings natural without loosening any task/action constraint.
        max_sentences=3,
    )


def build_tree(state: PersonaState, round_state: RoundState) -> PersonaPolicyTree:
    if state.persona not in _RULES:
        raise ValueError("approachable policy received another persona's state")
    context = TurnContext(state=state, round_state=round_state)
    rules = _RULES[state.persona]
    return selector(
        rules.tree_name,
        context,
        (
            ("01_task", task_requested, _task),
            ("02_conversation", lambda c: bool(c.event and c.event.speech_acts), _conversation),
            ("99_fallback", always, lambda _: fallback_clarification(rules.display_name)),
        ),
    )


def decide(event: TurnEvent, state: PersonaState, round_state: RoundState) -> Decision:
    return build_tree(state, round_state).decide(event)


SUPPORTED_PERSONAS = frozenset(_RULES)
