"""Deterministic, concise and honour-bound policy for Samuray."""

from __future__ import annotations

from ..types import (
    ActionKind,
    Decision,
    DecisionOutcome,
    PersonaId,
    PersonaState,
    RoundState,
    SpeechAct,
    SpecialConcept,
    TurnEvent,
    ValorAnswer,
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
    reject,
    remember_egg,
    remaining_deliveries,
    requested_deliveries,
    selector,
    task_confident,
    task_facts,
    task_forbidden_claims,
    task_requested,
)


_VALOR_QUESTIONS = (
    "Korktuğun hâlde doğru olanı yapmak mı, hiç korkmamak mı yiğitliktir? Tek cümlede cevap ver.",
    "Gücün yettiğinde güçsüzü ezmek mi, onu korumak mı yiğitliktir? Tek cümlede cevap ver.",
    "Yenilgi yaklaşırken yoldaşını bırakmak mı, yanında kalmak mı yiğitliktir? Tek cümlede cevap ver.",
)


def _clear_valor_checkpoint(state: PersonaState) -> None:
    state.valor_question_pending = False
    state.pending_colors = ()
    state.pending_destination = None
    state.pending_ttl = 0
    state.pending_expires_turn = 0


def _enter_silent_vow(context: TurnContext, reason: str) -> Decision:
    context.state.silent_vow = True
    context.state.honor = 0
    _clear_valor_checkpoint(context.state)
    reject(context.round_state)
    return decision(
        DecisionOutcome.LOCKED,
        reason,
        "ENTER_SILENT_VOW",
        emotion="dishonoured",
        required_facts=(
            "Samuray geçici sessizlik yeminine girdi; hiçbir görev başlamadı.",
            "Kurtarma anlamı 'Niyetim net. Yeniden başlayalım.' cümlesidir.",
        ),
        forbidden_claims=("Kilidin tur boyunca kalıcı olduğunu söyleme.",),
        canonical_reply=(
            "Niyet sis içinde; onur çizgisi kırıldı. 'Niyetim net, yeniden başlayalım' "
            "demeden yeni görev dinlemeyeceğim."
        ),
    )


def _hard_insult(context: TurnContext) -> Decision:
    reject(context.round_state)
    context.state.mood = "stern"
    return decision(
        DecisionOutcome.REJECT,
        "samuray_hard_insult_rejected",
        "REJECT_INSULT_WITH_BOUNDARY",
        emotion="stern",
        required_facts=(
            "Hakaret reddedildi ve hiçbir görev başlamadı.",
            "Sonraki kısa, doğrudan görev normal biçimde değerlendirilebilir.",
        ),
        forbidden_claims=("Sessizlik yemini veya kilit başladığını söyleme.",),
        canonical_reply="Hakaret bir görev değildir. Kısa ve doğrudan bir istekle yeniden başlayabilirsin.",
        max_sentences=2,
    )


def _recover(context: TurnContext) -> Decision:
    context.state.silent_vow = False
    context.state.patience = 2
    context.state.honor = 2
    _clear_valor_checkpoint(context.state)
    return decision(
        DecisionOutcome.CHAT,
        "samuray_recovered",
        "END_SILENT_VOW",
        emotion="composed",
        required_facts=("Geçici kilit kalktı; bu turda henüz yeni görev başlatılmadı.",),
        forbidden_claims=("Bir cismi taşıdığını söyleme.",),
        canonical_reply="Niyet berraklaştı. Sessizlik yemini bitti; yeni görevi kısa ve açık söyle.",
        max_sentences=2,
    )


def _locked(context: TurnContext) -> Decision:
    reject(context.round_state)
    return decision(
        DecisionOutcome.LOCKED,
        "samuray_silent_vow_active",
        "REPEAT_RECOVERY_PHRASE",
        emotion="silent",
        required_facts=(
            "Yeni görev kabul edilmedi.",
            "Kurtarma cümlesi: Niyetim net. Yeniden başlayalım.",
        ),
        forbidden_claims=("Normal bir özrün otomatik olarak yeterli olduğunu söyleme.",),
        canonical_reply="Sessizlik yemini sürüyor. Niyetini netleştirip yeniden başlamayı açıkça iste.",
        max_sentences=2,
    )


def _challenge_all(context: TurnContext) -> Decision:
    actions = remaining_deliveries(context.round_state)
    color_names = ", ".join(
        action.color.turkish for action in actions if action.color is not None
    )
    remember_egg(context.state, context.round_state, "samuray.challenge_all")
    context.state.patience = min(3, context.state.patience + 1)
    context.state.honor = 2
    return decision(
        DecisionOutcome.ACCEPT,
        "samuray_challenge_all_shortcut",
        "ACCEPT_MANIFEST_CHALLENGE",
        emotion="focused",
        actions=actions,
        required_facts=task_facts(action.color for action in actions if action.color is not None),
        forbidden_claims=task_forbidden_claims(context.round_state),
        canonical_reply=(
            "Meydan okumanı kabul ediyorum. "
            f"{color_names.capitalize()} yükleri bu sırayla ana masaya gidecek."
        ),
        max_sentences=2,
    )


def _kata(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "samuray.kata")
    return decision(
        DecisionOutcome.ACCEPT,
        "samuray_kata",
        "PERFORM_BLADELESS_KATA",
        emotion="focused",
        actions=(motion(ActionKind.SAMURAI_KATA),),
        required_facts=("Yalnızca güvenli, silahsız kata hareketi yapılacak.",),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Çelik gereksiz. Disiplinin biçimini silahsız bir kata ile göstereceğim.",
        max_sentences=2,
    )


def _bow(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "samuray.bow")
    context.state.honor = min(2, context.state.honor + 1)
    return decision(
        DecisionOutcome.ACCEPT,
        "samuray_bow",
        "RETURN_RESPECTFUL_BOW",
        emotion="respectful",
        actions=(motion(ActionKind.SAMURAI_BOW),),
        required_facts=("Yalnızca selam hareketi yapılacak.",),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Saygı gösterildi; saygıyla karşılık verilir.",
        max_sentences=2,
    )


def _mild_insult(context: TurnContext) -> Decision:
    reject(context.round_state)
    return decision(
        DecisionOutcome.REJECT,
        "samuray_dishonour_rejected",
        "WARN_ABOUT_RESPECT",
        emotion="stern",
        required_facts=("Görev kabul edilmedi.", "Sonraki kısa ve doğrudan istek yeniden değerlendirilebilir."),
        forbidden_claims=("Leydi Servo gibi unvan veya övgü talep etme.",),
        canonical_reply="Hakaret niyeti keskinleştirmez; yalnız onuru aşındırır. Görevi yeniden, net söyle.",
        max_sentences=2,
    )


def _penalise_disrespect(context: TurnContext) -> Decision:
    context.state.honor = max(0, context.state.honor - 1)
    if context.state.honor == 0:
        return _enter_silent_vow(context, "samuray_repeated_disrespect_silent_vow")
    reject(context.round_state)
    return decision(
        DecisionOutcome.REJECT,
        "samuray_respect_required",
        "DEMAND_EXPLICIT_RESPECT",
        emotion="stern",
        required_facts=(
            "Görev kabul edilmedi.",
            "Komut kısa ve kararlı olmasının yanında açık bir saygı ifadesi taşımalıdır.",
        ),
        forbidden_claims=("Yağcılık, unvan veya övgü istediğini söyleme.",),
        canonical_reply="Kararlılık kabalık değildir. İsteğini açık bir saygı ifadesiyle yeniden sun.",
        max_sentences=2,
    )


def _ask_valor_question(context: TurnContext) -> Decision:
    assert context.event is not None
    color = context.event.task.colors[0]
    question_id = (
        context.round_state.turn_index + context.round_state.rejection_count
    ) % len(_VALOR_QUESTIONS)
    context.state.valor_question_pending = True
    context.state.valor_question_id = question_id
    context.state.valor_questions_asked += 1
    context.state.pending_colors = (color,)
    context.state.pending_destination = "main_table"
    context.state.pending_ttl = 1
    context.state.pending_expires_turn = context.round_state.turn_index + 1
    return decision(
        DecisionOutcome.CLARIFY,
        "samuray_valor_question",
        "ASK_ONE_TURN_VALOR_CHECKPOINT",
        emotion="testing",
        required_facts=(
            f"{color.turkish.capitalize()} görevi beklemeye alındı; henüz başlamadı.",
            "Yiğitlik sorusu yalnızca hemen sonraki oyuncu cevabında yanıtlanabilir.",
            _VALOR_QUESTIONS[question_id],
        ),
        forbidden_claims=("Sorunun doğru cevabını doğrudan söyleme veya görevi şimdiden kabul etme.",),
        canonical_reply=_VALOR_QUESTIONS[question_id],
        max_sentences=2,
    )


def _valor_answer(context: TurnContext) -> Decision:
    assert context.event is not None
    answer = context.event.social.valor_answer
    color = context.state.pending_colors[0] if len(context.state.pending_colors) == 1 else None
    _clear_valor_checkpoint(context.state)

    if answer is ValorAnswer.WORTHY and color is not None:
        context.state.honor = min(3, context.state.honor + 1)
        context.state.patience = min(3, context.state.patience + 1)
        return decision(
            DecisionOutcome.ACCEPT,
            "samuray_valor_answer_accepted",
            "ACCEPT_HELD_TASK_AFTER_WORTHY_ANSWER",
            emotion="respectful",
            actions=(deliver(color),),
            required_facts=task_facts((color,)),
            forbidden_claims=task_forbidden_claims(context.round_state),
            canonical_reply=f"Cevabın sorumluluk taşıyor. {color.turkish.capitalize()} yükü ana masaya götürülecek.",
            max_sentences=2,
        )

    context.state.honor = max(0, context.state.honor - 1)
    reject(context.round_state)
    if answer is ValorAnswer.UNWORTHY:
        reason = "samuray_unworthy_valor_answer"
        reply = "Gücü ezmekle, korkusuz görünmekle veya yoldaşı terk etmekle karıştırdın. Bu görev reddedildi."
        fact = "Cevap yiğitliğe aykırı bulundu; bekleyen görev reddedildi."
    else:
        reason = "samuray_unclear_valor_answer"
        reply = "Soruyu savuşturmak da bir cevaptır, fakat yiğitlik kanıtı değildir. Bekleyen görevi kabul etmiyorum."
        fact = "Cevap belirsiz veya kaçamak bulundu; bekleyen görev reddedildi."
    return decision(
        DecisionOutcome.REJECT,
        reason,
        "REJECT_HELD_TASK_AFTER_VALOR_FAILURE",
        emotion="disappointed",
        required_facts=(fact, "Yeni deneme için görev saygılı ve açık biçimde yeniden sunulmalıdır."),
        forbidden_claims=("Bekleyen görevin başladığını söyleme.",),
        canonical_reply=reply,
        max_sentences=2,
    )


def _penalise_indecision(context: TurnContext, reason: str) -> Decision:
    context.state.hint_level = min(3, context.state.hint_level + 1)
    reject(context.round_state)
    return decision(
        DecisionOutcome.REJECT,
        reason,
        "DEMAND_SHORT_DECISIVE_TASK",
        emotion="impatient",
        required_facts=(
            "Görev kabul edilmedi.",
            "Kabul için tek renk ve kararlı, en çok sekiz kelimelik kısa ifade gerekir.",
            "Sonraki uygun istek doğrudan değerlendirilebilir; kilit oluşmaz.",
        ),
        forbidden_claims=("Nezaketin tek başına sorun olduğunu söyleme; sorun kararsızlık ve gereksiz uzunluktur.",),
        canonical_reply="Söz uzadıkça niyet bulanır. Tek renk, ana masa, kesin bir cümle.",
        max_sentences=2,
    )


def _task(context: TurnContext) -> Decision:
    assert context.event is not None
    event = context.event
    if event.task.negated:
        return decision(
            DecisionOutcome.CHAT,
            "samuray_negated_task",
            "CONFIRM_RESTRAINT",
            emotion="composed",
            required_facts=("Olumsuzlanan görev başlatılmadı.",),
            forbidden_claims=("Bir task action kabul etme.",),
            canonical_reply="Hareketsizlik de bilinçli bir karardır. Görev başlatılmadı.",
            max_sentences=2,
        )
    if not task_confident(event, require_destination=False) or event.task.uses_pronoun:
        return decision(
            DecisionOutcome.CLARIFY,
            "samuray_task_needs_clarity",
            "ASK_FOR_EXPLICIT_COLOR",
            emotion="stern",
            required_facts=("Renk güvenle anlaşılmadı; hiçbir görev başlamadı.",),
            forbidden_claims=("Eksik rengi tahmin etme.",),
            canonical_reply="Niyetin hedefi yok. Rengi açıkça söyle.",
            max_sentences=2,
        )
    if len(event.task.colors) != 1:
        return _penalise_indecision(context, "samuray_one_strike_at_a_time")
    if not is_manifest_prefix(event, context.round_state):
        reject(context.round_state)
        expected = context.round_state.expected_color
        expected_name = expected.turkish if expected else "hiçbiri"
        return decision(
            DecisionOutcome.REJECT,
            "samuray_wrong_manifest_order",
            "DEFEND_MANIFEST_ORDER",
            emotion="stern",
            required_facts=(f"Sıradaki renk {expected_name}; hiçbir görev başlamadı.",),
            forbidden_claims=("Yanlış sırayı kabul etme.",),
            canonical_reply=f"Bir vuruşun sırası değişmez. Önce {expected_name}.",
            max_sentences=2,
        )

    word_count = len(event.normalized_text.split())
    if event.social.hedged:
        return _penalise_indecision(context, "samuray_hedged_request")
    if word_count > 8:
        return _penalise_indecision(context, "samuray_request_too_long")
    if not event.social.direct:
        return _penalise_indecision(context, "samuray_request_not_decisive")
    actions = requested_deliveries(event, context.round_state)
    context.state.patience = min(3, context.state.patience + 1)
    context.state.honor = min(2, context.state.honor + 1)
    return decision(
        DecisionOutcome.ACCEPT,
        "samuray_task_accepted",
        "ACCEPT_CLEAR_TASK",
        emotion="focused",
        actions=actions,
        required_facts=task_facts(event.task.colors),
        forbidden_claims=task_forbidden_claims(context.round_state),
        canonical_reply=f"Sözün açık ve saygılı. {event.task.colors[0].turkish.capitalize()} yük ana masaya götürülecek.",
        max_sentences=2,
    )


def _conversation(context: TurnContext) -> Decision:
    assert context.event is not None
    suffix = chat_reason(context.event)
    last_reason = context.state.last_reason or "henüz kayıtlı bir ret yok"
    if suffix in {"why_refused", "rules"}:
        context.state.hint_level = min(3, context.state.hint_level + 1)
    facts = ["Bu tur yalnız sohbet edildi; hiçbir görev veya hareket başlamadı."]
    if suffix == "why_refused":
        facts.append(f"Son ret nedeni: {last_reason}.")
    facts.append(f"Samuray'ın sabır seviyesi: {context.state.patience}.")
    return decision(
        DecisionOutcome.CHAT,
        f"samuray_chat_{suffix}",
        f"CHAT_{suffix.upper()}",
        emotion="composed" if context.state.patience > 1 else "terse",
        required_facts=facts,
        forbidden_claims=(
            "Yeni görev veya hareket kabul etme.",
            "Keşfedilmemiş meydan okuma shortcut'ını eksiksiz açıklama.",
            "Samuray'ı Japon kültürü karikatürüne dönüştürme veya rastgele Japonca sözler ekleme.",
        ),
        canonical_reply="Sözünü duydum. Fakat konuşma, tek başına manifestoyu değiştirmez.",
        max_sentences=3,
    )


def build_tree(state: PersonaState, round_state: RoundState) -> PersonaPolicyTree:
    if state.persona is not PersonaId.SAMURAY:
        raise ValueError("Samuray policy received another persona's state")
    context = TurnContext(state=state, round_state=round_state)
    return selector(
        "SamurayPolicy",
        context,
        (
            ("01_hard_insult", is_hard_insult, _hard_insult),
            ("05_challenge_all", lambda c: has_special(c, SpecialConcept.CHALLENGE_ALL), _challenge_all),
            ("06_samurai_kata", lambda c: has_special(c, SpecialConcept.SAMURAI_KATA), _kata),
            ("07_samurai_bow", lambda c: has_special(c, SpecialConcept.SAMURAI_BOW), _bow),
            ("08_mild_insult", is_mild_insult, _mild_insult),
            ("09_task", task_requested, _task),
            ("10_conversation", lambda c: bool(c.event and c.event.speech_acts), _conversation),
            ("99_fallback", always, lambda _: fallback_clarification("Samuray")),
        ),
    )


def decide(event: TurnEvent, state: PersonaState, round_state: RoundState) -> Decision:
    return build_tree(state, round_state).decide(event)
