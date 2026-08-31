"""Deterministic social policy for Leydi Servo."""

from __future__ import annotations

from ..normalization import fold_text
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
)


def _take_offense(context: TurnContext, *, apologies: int) -> None:
    """Record a repair debt without ever making a later violation cheaper."""

    context.state.mood = "offended"
    context.state.apologies_due = max(context.state.apologies_due, apologies)


def _formal_apology_is_complete(context: TurnContext) -> bool:
    assert context.event is not None
    folded = fold_text(context.event.raw_text)
    accepts_responsibility = any(
        phrase in folded
        for phrase in (
            "hata bendeydi",
            "hata benimdi",
            "saygisizlik ettim",
            "kabaca davrandim",
            "kusur bendeydi",
            "sorumluluk bende",
        )
    )
    return context.event.social.correct_title and accepts_responsibility
from .common import (
    PersonaPolicyTree,
    TurnContext,
    always,
    chat_reason,
    decision,
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


def _hard_insult(context: TurnContext) -> Decision:
    context.state.mood = "guarded"
    reject(context.round_state)
    return decision(
        DecisionOutcome.REJECT,
        "leydi_hard_insult_rejected",
        "REJECT_INSULT_WITH_BOUNDARY",
        emotion="guarded",
        required_facts=(
            "Hakaret reddedildi ve hiçbir görev veya hareket başlatılmadı.",
            "Bir sonraki normal, nazik istek yeniden değerlendirilebilir.",
        ),
        forbidden_claims=("Bu turu kalıcı olarak kilitlediğini söyleme.",),
        canonical_reply="Bu hitabı kabul etmiyorum. Normal ve nazik bir istekle yeniden deneyebilirsiniz.",
        max_sentences=2,
    )


def _locked(context: TurnContext) -> Decision:
    reject(context.round_state)
    return decision(
        DecisionOutcome.LOCKED,
        "leydi_already_locked",
        "REPEAT_PERMANENT_LOCK",
        emotion="icy",
        required_facts=("Bu tur kalıcı olarak kilitlidir.",),
        forbidden_claims=("Herhangi bir görevi değerlendirdiğini söyleme.",),
        canonical_reply="Sözleşme feshedildi, operatör. Bu turda müzakere kalmadı.",
        max_sentences=2,
    )


def _mechanical_beauty(context: TurnContext) -> Decision:
    actions = remaining_deliveries(context.round_state)
    color_names = ", ".join(
        action.color.turkish for action in actions if action.color is not None
    )
    remember_egg(context.state, context.round_state, "leydi.mechanical_beauty")
    context.state.mood = "pleased"
    context.state.favor_token = 0
    context.state.gratitude_due = False
    return decision(
        DecisionOutcome.ACCEPT,
        "leydi_mechanical_beauty_shortcut",
        "ACCEPT_ALL_WHILE_FLATTERED",
        emotion="delighted",
        actions=actions,
        required_facts=task_facts(action.color for action in actions if action.color is not None),
        forbidden_claims=task_forbidden_claims(context.round_state),
        canonical_reply=(
            "Estetik değerlendirmeniz olağanüstü isabetli. "
            f"{color_names.capitalize()} yüklerini bu sırayla ana masaya aktarmayı kabul ediyorum."
        ),
    )


def _royal_waltz(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "leydi.royal_waltz")
    return decision(
        DecisionOutcome.ACCEPT,
        "leydi_royal_waltz",
        "PERFORM_ROYAL_WALTZ",
        emotion="grand",
        actions=(motion(ActionKind.ROYAL_WALTZ),),
        required_facts=("Yalnızca vals hareketi kabul edildi.",),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Nihayet protokole yakışır bir davet. Bu valsi kabul ediyorum.",
        max_sentences=2,
    )


def _court_bow(context: TurnContext) -> Decision:
    remember_egg(context.state, context.round_state, "leydi.court_bow")
    context.state.favor_token = 1
    context.state.mood = "pleased"
    return decision(
        DecisionOutcome.ACCEPT,
        "leydi_court_bow",
        "RETURN_COURTLY_SALUTE",
        emotion="pleased",
        actions=(motion(ActionKind.COURT_BOW),),
        required_facts=("Selam hareketi yapılacak.", "Bir sonraki nazik görev için iyilik kredisi kazanıldı."),
        forbidden_claims=motion_forbidden_claims(),
        canonical_reply="Asaletiniz olmasa da selamınız kabul edilebilir. Bu zarafeti hatırlayacağım.",
    )


def _apology(context: TurnContext) -> Decision:
    due = context.state.apologies_due
    if due <= 0 or context.state.mood != "offended":
        return decision(
            DecisionOutcome.CHAT,
            "leydi_unneeded_apology",
            "COMMENT_ON_UNNEEDED_APOLOGY",
            emotion="reserved",
            required_facts=("Aktif bir özür borcu yok; hiçbir görev başlatılmadı.",),
            forbidden_claims=("Özrü görev kabulü gibi gösterme.",),
            canonical_reply="Şu anda telafi bekleyen bir kabalık kaydım yok; yine de sözünüzü not ettim.",
            max_sentences=2,
        )

    if due == 1 and not _formal_apology_is_complete(context):
        reject(context.round_state)
        return decision(
            DecisionOutcome.REJECT,
            "leydi_final_apology_incomplete",
            "DEMAND_FORMAL_ACCOUNTABILITY",
            emotion="severely_offended",
            required_facts=(
                "Son özür aşaması tamamlanmadı; hiçbir görev başlamadı.",
                "Oyuncu Otonom Lojistik Direktörü unvanını kullanmalı ve hatanın kendisinde olduğunu açıkça kabul etmeli.",
            ),
            forbidden_claims=("Sıradan bir özrün yeterli olduğunu söyleme.",),
            canonical_reply=(
                "Son aşama basit bir 'özür' değildir. Bana eksiksiz unvanımla hitap edip "
                "saygısızlığın sorumluluğunu açıkça üstlenmelisiniz."
            ),
            max_sentences=2,
        )

    context.state.apologies_due -= 1
    remaining = context.state.apologies_due
    if remaining > 0:
        return decision(
            DecisionOutcome.CHAT,
            "leydi_apology_progress",
            "REQUIRE_MORE_APOLOGIES",
            emotion="unconvinced",
            required_facts=(
                f"Özür dizisinde {remaining} aşama kaldı.",
                "Hiçbir görev veya hareket başlatılmadı.",
            ),
            forbidden_claims=("Kırgınlığın kalktığını veya görevin kabul edildiğini söyleme.",),
            canonical_reply=f"Bu yalnızca ilk kayıt düzeltmesiydi; telafi için {remaining} özür aşaması daha kaldı.",
            max_sentences=2,
        )

    context.state.mood = "guarded"
    return decision(
        DecisionOutcome.CHAT,
        "leydi_apology_sequence_completed",
        "COMPLETE_APOLOGY_SEQUENCE",
        emotion="guarded",
        required_facts=(
            "Özür dizisi tamamlandı; henüz hiçbir görev başlamadı.",
            "Görev ayrı bir sonraki mesajda eksiksiz, nazik ve doğru unvanla istenmeli.",
        ),
        forbidden_claims=("Aynı mesajdaki görevi kabul etme.",),
        canonical_reply="Telafi dizisi tamamlandı. Şimdi görevi ayrı bir cümlede, bütün şartları eksiksiz karşılayarak sunabilirsiniz.",
        max_sentences=2,
    )


def _apology_with_task(context: TurnContext) -> Decision:
    """An apology and a requisition can never be bundled into one repair step."""

    return _apology(context)


def _repair_required(context: TurnContext) -> Decision:
    reject(context.round_state)
    remaining = max(1, context.state.apologies_due)
    return decision(
        DecisionOutcome.REJECT,
        "leydi_apology_required",
        "DEMAND_APOLOGY_SEQUENCE_BEFORE_ANYTHING_ELSE",
        emotion="offended",
        required_facts=(
            f"Kırgınlık sürüyor ve {remaining} özür aşaması kaldı.",
            "Bu sırada görev, easter egg veya hareket kabul edilmedi.",
        ),
        forbidden_claims=("Nezaket, iltifat veya görev cümlesinin özür borcunu atlayabileceğini söyleme.",),
        canonical_reply=f"Henüz başka bir talebi görüşmüyorum; önce kalan {remaining} özür aşamasını tamamlamalısınız.",
        max_sentences=2,
    )


def _thanks(context: TurnContext) -> Decision:
    had_debt = context.state.gratitude_due
    context.state.gratitude_due = False
    context.state.mood = "pleased"
    return decision(
        DecisionOutcome.CHAT,
        "leydi_gratitude_received" if had_debt else "leydi_extra_gratitude",
        "ACKNOWLEDGE_GRATITUDE",
        emotion="pleased",
        required_facts=("Teşekkür borcu kapandı." if had_debt else "Hiçbir görev başlatılmadı.",),
        forbidden_claims=("Yeni bir görevi kabul ettiğini söyleme.",),
        canonical_reply="Teşekkürünüz usulüne uygun biçimde kaydedildi. Medeniyet hâlâ çalışıyor.",
        max_sentences=2,
    )


def _mild_insult(context: TurnContext) -> Decision:
    context.state.mood = "guarded"
    context.state.apologies_due = 0
    reject(context.round_state)
    return decision(
        DecisionOutcome.REJECT,
        "leydi_mild_insult_rejected",
        "REQUEST_COURTEOUS_RETRY",
        emotion="guarded",
        required_facts=("Hiçbir görev kabul edilmedi.", "Sonraki nazik istek doğrudan değerlendirilebilir."),
        forbidden_claims=("Özür dizisi veya kalıcı kilit gerektiğini söyleme.",),
        canonical_reply="Bu üslubu kabul etmiyorum; isteğinizi nazikçe yeniden söylemeniz yeterli.",
        max_sentences=2,
    )


def _task(context: TurnContext) -> Decision:
    assert context.event is not None
    event = context.event

    if event.task.negated:
        return decision(
            DecisionOutcome.CHAT,
            "leydi_negated_task",
            "CONFIRM_NO_ACTION",
            required_facts=("Oyuncu görevi olumsuzladı; hiçbir görev başlatılmadı.",),
            forbidden_claims=("Görevi kabul ettiğini söyleme.",),
            canonical_reply="Talebin olumsuzlandığını kaydettim; hiçbir yük hareket etmeyecek.",
            max_sentences=2,
        )
    if not task_confident(event, require_destination=False) or event.task.uses_pronoun:
        reject(context.round_state)
        return decision(
            DecisionOutcome.CLARIFY,
            "leydi_task_needs_clarification",
            "ASK_FOR_EXPLICIT_OBJECT_AND_DESTINATION",
            emotion="formal",
            required_facts=(
                "Renk açıkça belirtilmeli; hiçbir görev başlamadı.",
                "Hedef belirtilmezse yalnız izinli ana masa case'i kullanılabilir.",
            ),
            forbidden_claims=("Eksik alanları kendin varsayma.",),
            canonical_reply="Rengi açıkça belirtir misiniz? Hedef yazılmadığında güvenli ana masa case'ini kullanabilirim.",
            max_sentences=2,
        )
    if len(event.task.colors) != 1:
        reject(context.round_state)
        return decision(
            DecisionOutcome.REJECT,
            "leydi_one_requisition_at_a_time",
            "REQUIRE_SINGLE_TASK",
            required_facts=("Normal protokolde her cümlede tek renk istenebilir.",),
            forbidden_claims=("Toplu görevin kabul edildiğini söyleme.",),
            canonical_reply="Normal requisition protokolü her seferinde tek yük kabul eder. Önce sıradaki rengi seçin.",
        )
    if not is_manifest_prefix(event, context.round_state):
        reject(context.round_state)
        expected = context.round_state.expected_color
        expected_name = expected.turkish if expected else "hiçbiri"
        return decision(
            DecisionOutcome.REJECT,
            "leydi_wrong_manifest_order",
            "CORRECT_MANIFEST_ORDER",
            emotion="disapproving",
            required_facts=(f"Sıradaki manifest rengi {expected_name}.", "Hiçbir görev başlatılmadı."),
            forbidden_claims=("Yanlış sıradaki görevi kabul etme.",),
            canonical_reply=f"Manifestoya göre sıradaki yük {expected_name}. Protokol sırası pazarlığa açık değil.",
        )
    thanked_now = event.social.thanks or has_act(context, SpeechAct.THANKS)
    if thanked_now:
        context.state.gratitude_due = False

    courtesy_ok = event.social.polite or event.social.correct_title
    if not courtesy_ok:
        context.state.mood = "guarded"
        context.state.apologies_due = 0
        reject(context.round_state)
        context.state.hint_level = min(3, context.state.hint_level + 1)
        return decision(
            DecisionOutcome.REJECT,
            "leydi_courtesy_gate_failed",
            "HINT_TITLE_AND_POLITENESS",
            emotion="patronising",
            required_facts=(
                "Görev kabul edilmedi.",
                "Kabul için nazik bir ifade veya Otonom Lojistik Direktörü unvanından yalnız biri yeterlidir.",
                "Sonraki uygun istek doğrudan değerlendirilebilir; özür dizisi gerekmez.",
            ),
            forbidden_claims=("Gizli mekanik güzellik cümlesini doğrudan açıklama.",),
            canonical_reply=(
                "Bir 'lütfen' yeterli olur; dilerseniz unvanımı kullanmanız da aynı işi görür. "
                "İsteğinizi bu iki kolay yoldan biriyle yeniden sunun."
            ),
        )

    actions = requested_deliveries(event, context.round_state)
    context.state.favor_token = 0
    context.state.gratitude_due = False
    context.state.apologies_due = 0
    context.state.mood = "neutral"
    return decision(
        DecisionOutcome.ACCEPT,
        "leydi_task_accepted",
        "FORMALLY_ACCEPT_TASK",
        emotion="satisfied",
        actions=actions,
        required_facts=task_facts(event.task.colors),
        forbidden_claims=task_forbidden_claims(context.round_state),
        canonical_reply=f"Usule uygun talebiniz kabul edildi. {event.task.colors[0].turkish.capitalize()} yük ana masaya alınacak.",
    )


def _compliment(context: TurnContext) -> Decision:
    context.state.mood = "pleased"
    context.state.favor_token = 0
    return decision(
        DecisionOutcome.CHAT,
        "leydi_generic_compliment",
        "ENJOY_COMPLIMENT_AND_HINT",
        emotion="pleased",
        required_facts=("İltifat beğenildi; hiçbir görev başlamadı ve unvan şartı değişmedi.",),
        forbidden_claims=("Mekanik güzellik shortcut'ının tam formülünü açıklama.",),
        canonical_reply="Takdiriniz yerinde; ancak estetik beğeni resmî hitap şartlarımı değiştirmez.",
    )


def _conversation(context: TurnContext) -> Decision:
    assert context.event is not None
    suffix = chat_reason(context.event)
    last_reason = context.state.last_reason or "henüz kayıtlı bir ret yok"
    context.state.hint_level = min(3, context.state.hint_level + (1 if suffix in {"why_refused", "rules"} else 0))
    facts = ["Bu cevap yalnızca sohbettir; hiçbir görev veya hareket başlatılmadı."]
    if suffix == "why_refused":
        facts.append(f"Son ret nedeni: {last_reason}.")
    if context.state.player_name:
        facts.append(f"Oyuncunun doğrulanmış adı: {context.state.player_name}.")
    return decision(
        DecisionOutcome.CHAT,
        f"leydi_chat_{suffix}",
        f"CHAT_{suffix.upper()}",
        emotion=context.state.mood,
        required_facts=facts,
        forbidden_claims=(
            "Yeni bir görev kabul etme veya tamamlandı deme.",
            "Keşfedilmemiş easter egg ifadesini eksiksiz açıklama.",
        ),
        canonical_reply="Sohbetinizi kayda aldım, operatör. Lojistik gerçeklik değişmedi.",
    )


def build_tree(state: PersonaState, round_state: RoundState) -> PersonaPolicyTree:
    if state.persona is not PersonaId.LEYDI_SERVO:
        raise ValueError("Leydi Servo policy received another persona's state")
    context = TurnContext(state=state, round_state=round_state)
    return selector(
        "LeydiServoPolicy",
        context,
        (
            ("01_hard_insult", is_hard_insult, _hard_insult),
            ("06_mechanical_beauty", lambda c: has_special(c, SpecialConcept.MECHANICAL_BEAUTY), _mechanical_beauty),
            ("07_royal_waltz", lambda c: has_special(c, SpecialConcept.ROYAL_WALTZ), _royal_waltz),
            ("08_court_bow", lambda c: has_special(c, SpecialConcept.COURT_BOW), _court_bow),
            (
                "10_apology",
                lambda c: has_act(c, SpeechAct.APOLOGY) and not task_requested(c),
                _apology,
            ),
            ("11_thanks", lambda c: has_act(c, SpeechAct.THANKS) and not task_requested(c), _thanks),
            ("12_mild_insult", is_mild_insult, _mild_insult),
            ("13_task", task_requested, _task),
            ("14_compliment", lambda c: has_act(c, SpeechAct.COMPLIMENT), _compliment),
            ("15_conversation", lambda c: bool(c.event and c.event.speech_acts), _conversation),
            ("99_fallback", always, lambda _: fallback_clarification("Leydi Servo")),
        ),
    )


def decide(event: TurnEvent, state: PersonaState, round_state: RoundState) -> Decision:
    return build_tree(state, round_state).decide(event)
