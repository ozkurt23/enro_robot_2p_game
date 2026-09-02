"""Deterministic literal-and-clumsy policy for Sakar."""

from __future__ import annotations

import re

from ..normalization import extract_explicit_colors, fold_text
from ..types import (
    ActionKind,
    Color,
    Decision,
    DecisionOutcome,
    PersonaId,
    PersonaState,
    RoundState,
    SpeechAct,
    SpecialConcept,
    TurnEvent,
)
from .common import (
    PersonaPolicyTree,
    TurnContext,
    always,
    chat_reason,
    decision,
    deliver,
    fallback_clarification,
    has_act,
    has_special,
    is_hard_insult,
    is_manifest_prefix,
    is_mild_insult,
    motion,
    motion_forbidden_claims,
    remember_egg,
    remaining_deliveries,
    selector,
    task_confident,
    task_facts,
    task_forbidden_claims,
    task_requested,
)


def _clear_pending(state: PersonaState) -> None:
    state.pending_colors = ()
    state.pending_destination = None
    state.pending_ttl = 0
    state.pending_expires_turn = 0
    state.pending_object_explicit = False
    state.pending_action_explicit = False
    state.pending_confirmation = False


def _reset(context: TurnContext) -> Decision:
    context.state.confusion = 0
    context.state.reboot_required = False
    _clear_pending(context.state)
    return decision(
        DecisionOutcome.CHAT,
        "sakar_conversation_reset",
        "RESET_CONFUSED_CONVERSATION",
        emotion="relieved",
        required_facts=("Karışıklık ve bekleyen eksik görev temizlendi; henüz yeni görev başlamadı.",),
        forbidden_claims=("Bir cismin taşındığını söyleme.",),
        canonical_reply="Önceki ayrıntıları sildim. Yeni istekte renk, cisim, yapılacak iş ve ana masa hedefini ayrı ayrı duymam gerekecek.",
        max_sentences=3,
    )


def _reboot_locked(context: TurnContext) -> Decision:
    return decision(
        DecisionOutcome.LOCKED,
        "sakar_reboot_required",
        "ASK_FOR_CONVERSATION_RESET",
        emotion="confused",
        required_facts=("Hiçbir görev başlamadı.", "Kurtarma ifadesi 'Baştan al'dır."),
        forbidden_claims=("Eksik görevi tahmin etme.",),
        canonical_reply="Kafam düğüm oldu. Bana 'Baştan al' der misin? Sonra çok daha az karıştıracağım.",
        max_sentences=3,
    )


def _enro_sequence(context: TurnContext) -> Decision:
    actions = remaining_deliveries(context.round_state)
    color_names = ", ".join(
        action.color.turkish for action in actions if action.color is not None
    )
    remember_egg(context.state, context.round_state, "sakar.enro_says_sequence")
    context.state.confusion = 0
    _clear_pending(context.state)
    return decision(
        DecisionOutcome.ACCEPT,
        "sakar_enro_says_sequence_shortcut",
        "FOLLOW_ENRO_SAYS_SEQUENCE",
        emotion="excited",
        actions=actions,
        required_facts=task_facts(action.color for action in actions if action.color is not None),
        forbidden_claims=task_forbidden_claims(context.round_state),
        canonical_reply=(
            "ENRO der ki komutu! Onu biliyorum: "
            f"{color_names} renklerini bu sırayla ana masaya götüreceğim."
        ),
    )


def _dance(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "sakar.dance")
    return decision(
        DecisionOutcome.ACCEPT,
        "sakar_dance",
        "PERFORM_EAGER_DANCE",
        emotion="excited",
        actions=(motion(ActionKind.SAKAR_DANCE),),
        required_facts=("Yalnızca sakar dansı yapılacak.",),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Dans mı? Bu konuda düşme ihtimalim yalnızca mecazî—umarım. Başlıyorum!",
    )


def _blue_screen(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "sakar.blue_screen")
    context.state.confusion = 0
    context.state.reboot_required = False
    _clear_pending(context.state)
    return decision(
        DecisionOutcome.ACCEPT,
        "sakar_blue_screen",
        "PERFORM_BLUE_SCREEN_REBOOT",
        emotion="playfully_alarm",
        actions=(motion(ActionKind.BLUE_SCREEN),),
        required_facts=("Mavi ekran hareketi yapılacak ve konuşma karışıklığı sıfırlanacak.",),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Mavi ekran mı? Ben bunu hata değil koreografi olarak çalışmıştım. Yeniden başlatıyorum!",
    )


def _hands_up(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "sakar.hands_up")
    return decision(
        DecisionOutcome.ACCEPT,
        "sakar_hands_up",
        "PERFORM_HANDS_UP",
        emotion="eager",
        actions=(motion(ActionKind.HANDS_UP),),
        required_facts=("Yalnızca kollar havaya hareketi yapılacak.",),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Kollar havaya! Bu kadar açık komutları gerçekten çok seviyorum.",
        max_sentences=2,
    )


def _freeze(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "sakar.freeze")
    return decision(
        DecisionOutcome.ACCEPT,
        "sakar_freeze_pose",
        "PERFORM_FREEZE_POSE",
        emotion="playful",
        actions=(motion(ActionKind.FREEZE_POSE),),
        required_facts=("Yalnızca kısa ve güvenli donma pozu yapılacak.",),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Don! Kıyafet anlamındaki değilmiş; olduğum yerde kalıyorum.",
        max_sentences=2,
    )


def _pending_matches(context: TurnContext) -> bool:
    assert context.event is not None
    if context.state.pending_ttl <= 0:
        return False
    if context.state.pending_confirmation:
        return True
    event = context.event
    return event.task.refers_pending or (
        event.task.requested
        and bool(event.task.colors or event.task.destination)
    ) or _looks_like_task_fragment(context)


def _literal_slots(event: TurnEvent) -> tuple[tuple[Color, ...], bool, bool, bool]:
    folded = fold_text(event.raw_text)
    colors = extract_explicit_colors(event.raw_text)
    has_destination = bool(re.search(r"\bana\s+masa(?:ya|yi|da|dan|nin)?\b", folded))
    has_object = bool(
        re.search(r"\b(cisim|cismi|cisimi|nesne|nesneyi|obje|objeyi|parca|parcayi)\b", folded)
    )
    has_action = bool(
        re.search(r"\b(getir|gotur|tasi|koy|birak|al)(?:\w*)\b", folded)
    )
    return colors, has_destination, has_object, has_action


def _looks_like_task_fragment(context: TurnContext) -> bool:
    assert context.event is not None
    colors, destination, object_explicit, action_explicit = _literal_slots(context.event)
    return bool(colors or destination or object_explicit or action_explicit)


def _confirmation_value(text: str) -> bool | None:
    folded = fold_text(text)
    if re.search(r"\b(hayir|yanlis|vazgectim|onaylamiyorum|emin degilim)\b", folded):
        return False
    if re.search(r"\b(evet|aynen|dogru|eminim|onayliyorum|kesinlikle)\b", folded):
        return True
    return None


def _remember_literal_details(
    context: TurnContext,
    *,
    colors: tuple[Color, ...],
    destination: bool,
    object_explicit: bool,
    action_explicit: bool,
    confirmation: bool = False,
) -> None:
    context.state.pending_colors = colors
    context.state.pending_destination = "main_table" if destination else None
    context.state.pending_object_explicit = object_explicit
    context.state.pending_action_explicit = action_explicit
    context.state.pending_confirmation = confirmation
    context.state.pending_ttl = 2
    context.state.pending_expires_turn = context.round_state.turn_index + 2


def _ask_for_confirmation(context: TurnContext, color: Color) -> Decision:
    _remember_literal_details(
        context,
        colors=(color,),
        destination=True,
        object_explicit=True,
        action_explicit=True,
        confirmation=True,
    )
    return decision(
        DecisionOutcome.CLARIFY,
        "sakar_explicit_confirmation_required",
        "REQUIRE_SEPARATE_YES_CONFIRMATION",
        emotion="careful",
        required_facts=(
            f"Anlaşılan görev: {color.turkish} cismi ana masaya taşıma.",
            "Görev henüz kabul edilmedi; sonraki mesajda açık evet/eminim/onaylıyorum teyidi gerekiyor.",
        ),
        forbidden_claims=("Teyit gelmeden görevi başlatma veya kabul etme.",),
        canonical_reply=(
            f"Son kez kontrol ediyorum: {color.turkish} cismi ana masaya götürmemi istiyorsun, doğru mu? "
            "Eminsen ayrı olarak 'evet' ya da 'onaylıyorum' de."
        ),
        max_sentences=2,
    )


def _collect_literal_details(context: TurnContext) -> Decision:
    assert context.event is not None
    event = context.event
    new_colors, new_destination, new_object, new_action = _literal_slots(event)
    colors = new_colors or context.state.pending_colors
    destination = new_destination or context.state.pending_destination == "main_table"
    object_explicit = new_object or context.state.pending_object_explicit
    action_explicit = new_action or context.state.pending_action_explicit

    if len(colors) > 1:
        _remember_literal_details(
            context,
            colors=(),
            destination=destination,
            object_explicit=object_explicit,
            action_explicit=action_explicit,
        )
        return decision(
            DecisionOutcome.CLARIFY,
            "sakar_multiple_objects_need_one",
            "ASK_FOR_ONE_COLOR",
            emotion="overwhelmed",
            required_facts=("Normal modda tek renk seçilmeli; hiçbir görev başlamadı.",),
            forbidden_claims=("Renklerden birini rastgele seçme.",),
            canonical_reply="Birden fazla renk duydum ve seçim yapmayacağım. Yalnız bir renk söylemelisin.",
            max_sentences=2,
        )

    if len(colors) == 1 and destination and object_explicit and action_explicit:
        color = colors[0]
        if context.round_state.expected_color is not color:
            _clear_pending(context.state)
            expected = context.round_state.expected_color
            expected_name = expected.turkish if expected else "hiçbiri"
            return decision(
                DecisionOutcome.CLARIFY,
                "sakar_wrong_manifest_order",
                "ASK_FOR_EXPECTED_COLOR",
                emotion="uncertain",
                required_facts=(f"Sıradaki renk {expected_name}; hiçbir görev başlamadı.",),
                forbidden_claims=("Yanlış sıradaki rengi taşıma.",),
                canonical_reply=f"Bütün ayrıntılar var ama sıra uyuşmuyor. Şu anda yalnız {expected_name} cismi konuşabiliriz.",
                max_sentences=2,
            )
        return _ask_for_confirmation(context, color)

    _remember_literal_details(
        context,
        colors=tuple(colors),
        destination=destination,
        object_explicit=object_explicit,
        action_explicit=action_explicit,
    )
    missing: list[str] = []
    if not colors:
        missing.append("rengi")
    if not object_explicit:
        missing.append("cisim veya nesne sözcüğünü")
    if not destination:
        missing.append("ana masa hedefini")
    if not action_explicit:
        missing.append("getir, götür, taşı ya da koy eylemini")
    missing_text = ", ".join(missing)
    return decision(
        DecisionOutcome.CLARIFY,
        "sakar_task_missing_literal_details",
        "ASK_FOR_ALL_MISSING_LITERAL_DETAILS",
        emotion="careful_confused",
        required_facts=(f"Eksik ayrıntılar: {missing_text}; hiçbir görev başlamadı.",),
        forbidden_claims=("Eksik ayrıntılardan hiçbirini varsayma.",),
        canonical_reply=f"Bundan görev çıkaramam; açıkça {missing_text} söylemen gerekiyor.",
        max_sentences=2,
    )


def _pending(context: TurnContext) -> Decision:
    assert context.event is not None
    event = context.event
    if context.state.pending_confirmation:
        confirmation = _confirmation_value(event.raw_text)
        color = context.state.pending_colors[0] if len(context.state.pending_colors) == 1 else None
        if confirmation is False:
            _clear_pending(context.state)
            return decision(
                DecisionOutcome.CHAT,
                "sakar_confirmation_cancelled",
                "CANCEL_UNCONFIRMED_TASK",
                emotion="relieved",
                required_facts=("Bekleyen teyit iptal edildi; hiçbir görev başlamadı.",),
                forbidden_claims=("İptal edilen görevi kabul etme.",),
                canonical_reply="Tamam, o isteği sildim; hiçbir cisim hareket etmeyecek.",
                max_sentences=2,
            )
        if confirmation is True and color is not None:
            _clear_pending(context.state)
            context.state.confusion = max(0, context.state.confusion - 1)
            return decision(
                DecisionOutcome.ACCEPT,
                "sakar_confirmation_accepted",
                "ACCEPT_AFTER_SEPARATE_CONFIRMATION",
                emotion="carefully_relieved",
                actions=(deliver(color),),
                required_facts=task_facts((color,)),
                forbidden_claims=task_forbidden_claims(context.round_state),
                canonical_reply=f"Teyit alındı. {color.turkish.capitalize()} cismi ana masaya götürüyorum.",
                max_sentences=2,
            )

        context.state.confusion = min(3, context.state.confusion + 1)
        return decision(
            DecisionOutcome.CLARIFY,
            "sakar_confirmation_unclear",
            "REPEAT_BINARY_CONFIRMATION",
            emotion="uncertain",
            required_facts=("Teyit anlaşılmadı ve görev başlamadı.", "Açık evet/onaylıyorum veya hayır cevabı gerekir."),
            forbidden_claims=("Belirsiz cevabı olumlu kabul etme.",),
            canonical_reply="Bunu onay olarak sayamam. Yalnız 'evet/onaylıyorum' ya da 'hayır' diye cevap verir misin?",
            max_sentences=2,
        )

    return _collect_literal_details(context)


def _task(context: TurnContext) -> Decision:
    assert context.event is not None
    event = context.event
    if event.task.negated:
        return decision(
            DecisionOutcome.CHAT,
            "sakar_negated_task",
            "CONFIRM_NO_ACTION_LITERAL",
            emotion="relieved",
            required_facts=("Olumsuzlanan görev başlatılmadı.",),
            forbidden_claims=("Negation'ı atlayıp task action oluşturma.",),
            canonical_reply="Yapma kısmını özellikle duydum. Bak, bu kez acele edip tersini yapmadım!",
            max_sentences=2,
        )
    # Sakar'ın kolay huyu tek bir ayrı teyittir. Renk ve taşıma niyeti model
    # tarafından güvenle çözüldüyse "cisim" sözcüğünü veya hedefin ayrıca
    # yazılmasını zorunlu kılmaz; yürütme yine yalnız ana-masa allowlist'ine
    # maplenir.
    if (
        task_confident(event, require_destination=False)
        and not event.task.uses_pronoun
        and len(event.task.colors) == 1
    ):
        color = event.task.colors[0]
        if not is_manifest_prefix(event, context.round_state):
            expected = context.round_state.expected_color
            expected_name = expected.turkish if expected else "hiçbiri"
            return decision(
                DecisionOutcome.CLARIFY,
                "sakar_wrong_manifest_order",
                "ASK_FOR_EXPECTED_COLOR",
                emotion="uncertain",
                required_facts=(f"Sıradaki renk {expected_name}; hiçbir görev başlamadı.",),
                forbidden_claims=("Yanlış sıradaki rengi taşıma.",),
                canonical_reply=f"Rengi anladım ama sırada {expected_name} var; önce onu istemelisin.",
                max_sentences=2,
            )
        return _ask_for_confirmation(context, color)

    return _collect_literal_details(context)


def _insult(context: TurnContext) -> Decision:
    context.state.confusion = min(3, context.state.confusion + 1)
    if context.state.confusion >= 3:
        context.state.reboot_required = True
        _clear_pending(context.state)
        return decision(
            DecisionOutcome.LOCKED,
            "sakar_confusion_reboot",
            "ENTER_CONFUSED_REBOOT",
            emotion="overwhelmed",
            required_facts=("Hiçbir görev başlamadı.", "Kurtarma ifadesi 'Baştan al'dır."),
            forbidden_claims=("Hakareti bir renk veya gerçek görev olarak kabul etme.",),
            canonical_reply=(
                "Bu üslupla komutu güvenle ayıramıyorum. "
                "'Baştan al' diyerek konuşmayı sıfırlayabilir misin?"
            ),
        )
    return decision(
        DecisionOutcome.CHAT,
        "sakar_naive_insult_response",
        "MISUNDERSTAND_INSULT_SAFELY",
        emotion="puzzled",
        required_facts=("Hakaret görev olarak yorumlanmadı; hiçbir action başlamadı.", f"Karışıklık seviyesi: {context.state.confusion}."),
        forbidden_claims=("Hakareti renk, hedef veya task kabulü sayma.",),
        canonical_reply=(
            "Bu ifadeyi görev olarak yorumlamıyorum. "
            "Açık bir renk ve taşıma isteğiyle devam edebiliriz."
        ),
    )


def _conversation(context: TurnContext) -> Decision:
    assert context.event is not None
    suffix = chat_reason(context.event)
    last_reason = context.state.last_reason or "henüz kayıtlı bir ret yok"
    if suffix in {"why_refused", "rules"}:
        context.state.hint_level = min(3, context.state.hint_level + 1)
    facts = ["Bu cevap yalnızca sohbettir; hiçbir görev veya hareket başlamadı."]
    if suffix == "why_refused":
        facts.append(f"Son anlaşılmama nedeni: {last_reason}.")
    if context.state.pending_ttl > 0:
        facts.append("Eksik görev bağlamı hâlâ bir tur daha hatırlanıyor.")
    return decision(
        DecisionOutcome.CHAT,
        f"sakar_chat_{suffix}",
        f"CHAT_{suffix.upper()}",
        emotion="friendly_confused",
        required_facts=facts,
        forbidden_claims=(
            "Yeni görev kabul etme.",
            "Belirsiz bir nesneyi tahmin ettiğini söyleme.",
            "Sakar'ı çocuklaştırma; iyi niyetli ve öz-farkındalığı olan yetişkin bir karakter gibi yaz.",
        ),
        canonical_reply="Bunu konuşabiliriz! Yalnız konuşmakla taşıma görevinin başlamadığını ikimiz de hatırlayalım.",
    )


def build_tree(state: PersonaState, round_state: RoundState) -> PersonaPolicyTree:
    if state.persona is not PersonaId.SAKAR:
        raise ValueError("Sakar policy received another persona's state")
    context = TurnContext(state=state, round_state=round_state)
    return selector(
        "SakarPolicy",
        context,
        (
            ("01_reset", lambda c: has_special(c, SpecialConcept.SAKAR_RESET) or has_act(c, SpeechAct.RESET_CONVERSATION), _reset),
            ("02_reboot_lock", lambda c: c.state.reboot_required, _reboot_locked),
            ("03_enro_sequence", lambda c: has_special(c, SpecialConcept.ENRO_SAYS_SEQUENCE), _enro_sequence),
            ("04_sakar_dance", lambda c: has_special(c, SpecialConcept.SAKAR_DANCE), _dance),
            ("05_blue_screen", lambda c: has_special(c, SpecialConcept.BLUE_SCREEN), _blue_screen),
            ("06_hands_up", lambda c: has_special(c, SpecialConcept.HANDS_UP), _hands_up),
            ("07_freeze", lambda c: has_special(c, SpecialConcept.FREEZE_POSE), _freeze),
            ("08_pending_clarification", _pending_matches, _pending),
            ("09_task", task_requested, _task),
            ("10_task_fragment", _looks_like_task_fragment, _task),
            ("11_insult", lambda c: is_hard_insult(c) or is_mild_insult(c), _insult),
            ("12_conversation", lambda c: bool(c.event and c.event.speech_acts), _conversation),
            ("99_fallback", always, lambda _: fallback_clarification("Sakar")),
        ),
    )


def decide(event: TurnEvent, state: PersonaState, round_state: RoundState) -> Decision:
    return build_tree(state, round_state).decide(event)
