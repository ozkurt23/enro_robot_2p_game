"""Turkish text normalization and deterministic safety cross-checks."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
import re
import unicodedata

from .types import (
    Color,
    DomainValidationError,
    InsultLevel,
    NluConfidence,
    SocialInfo,
    SpecialCandidate,
    SpecialConcept,
    SpeechAct,
    TaskInfo,
    TurnEvent,
)


MAX_INPUT_CHARS = 800


class SystemCommand(str, Enum):
    HELP = "help"
    STATUS = "status"
    TREE = "tree"
    PERSONA = "persona"
    RESTART = "restart"
    QUIT = "quit"
    CANCEL = "cancel"


_COMMANDS = {
    "/yardım": SystemCommand.HELP,
    "/yardim": SystemCommand.HELP,
    "/help": SystemCommand.HELP,
    "/durum": SystemCommand.STATUS,
    "/status": SystemCommand.STATUS,
    "/ağaç": SystemCommand.TREE,
    "/agac": SystemCommand.TREE,
    "/tree": SystemCommand.TREE,
    "/persona": SystemCommand.PERSONA,
    "/yeniden": SystemCommand.RESTART,
    "/restart": SystemCommand.RESTART,
    "/çıkış": SystemCommand.QUIT,
    "/cikis": SystemCommand.QUIT,
    "/quit": SystemCommand.QUIT,
    "dur": SystemCommand.CANCEL,
    "iptal": SystemCommand.CANCEL,
}


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("oyuncu girdisi string olmalı")
    if len(text) > MAX_INPUT_CHARS:
        raise DomainValidationError(f"girdi en fazla {MAX_INPUT_CHARS} karakter olabilir")
    value = unicodedata.normalize("NFKC", text).strip().casefold()
    value = value.replace("i̇", "i")
    value = re.sub(r"\s+", " ", value)
    return value


def fold_text(text: str) -> str:
    """Return a diacritic-insensitive search form; never show it to players."""

    value = normalize_text(text).translate(
        str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ç": "c", "ö": "o", "ü": "u"})
    )
    value = "".join(
        char for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    return value


def parse_system_command(text: str) -> SystemCommand | None:
    normalized = normalize_text(text)
    direct = _COMMANDS.get(normalized)
    if direct is not None:
        return direct
    folded = re.sub(r"[.!?,;:]+$", "", fold_text(text)).strip()
    if re.fullmatch(
        r"(?:(?:lutfen|hemen)\s+)*(?:robot\s+)?dur(?:\s+lutfen)?",
        folded,
    ):
        return SystemCommand.CANCEL
    if re.fullmatch(r"(?:hemen\s+)?iptal(?:\s+(?:et|lutfen))?", folded):
        return SystemCommand.CANCEL
    return None


_COLOR_PATTERNS = {
    Color.BLUE: re.compile(r"\bma+vi(?:yi|ye|den|nin|si)?\b"),
    Color.GREEN: re.compile(r"\byes+i+l?(?:i|e|den|in)?\b"),
    Color.RED: re.compile(r"\bkirmizi(?:yi|ya|dan|nin|si)?\b"),
}


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def extract_explicit_colors(text: str) -> tuple[Color, ...]:
    folded = fold_text(text)
    positions: list[tuple[int, Color]] = []
    for color, pattern in _COLOR_PATTERNS.items():
        match = pattern.search(folded)
        if match:
            positions.append((match.start(), color))
    found = {color for _, color in positions}
    bases = {Color.BLUE: "mavi", Color.GREEN: "yesil", Color.RED: "kirmizi"}
    for token_match in re.finditer(r"\b[a-z]+\b", folded):
        token = token_match.group(0)
        for color, base in bases.items():
            if color in found or not token.startswith(base[0]):
                continue
            distances = [
                _edit_distance(base, token[:prefix_length])
                for prefix_length in range(
                    max(2, len(base) - 1),
                    min(len(token), len(base) + 2) + 1,
                )
            ]
            threshold = 2 if len(base) >= 7 else 1
            if distances and min(distances) <= threshold:
                positions.append((token_match.start(), color))
                found.add(color)
    return tuple(color for _, color in sorted(positions))


_NEGATION_PATTERNS = (
    r"\b(getirme|goturme|tasima|alma|birakma|yapma|baslatma)\b",
    r"\b(dans\s+etme|kata\s+yapma)\b",
    r"\b(vals|dans|kata)\b.*\b(istemiyorum|isteme)\b",
    r"\b(cismi|parcayi|maviyi|yesili|kirmiziyi|tasimak|almak|getirmek|goturmek)\b.*\bistemiyorum\b",
    r"\bvazgectim\b",
    r"\biptal et\b",
)


def detect_task_negation(text: str) -> bool:
    folded = fold_text(text)
    return any(re.search(pattern, folded) for pattern in _NEGATION_PATTERNS)


def _is_metalinguistic_or_negated_insult(folded: str) -> bool:
    guards = (
        r"\b(salak|aptal|gerizekali|geri zekali)\s+(deme|demedim|degil)\b",
        r"\b(salak|aptal)\s+kelimesi(?:ni|yle|nden)?\b",
        r"\b(sana|ona)\s+(salak|aptal)\s+demedim\b",
        r"\b(salak|aptal)\s+dersem\b",
        r"\b(salak|aptal)\s+demek\b",
    )
    return any(re.search(pattern, folded) for pattern in guards)


def detect_hard_insult(text: str) -> bool:
    folded = fold_text(text)
    if _is_metalinguistic_or_negated_insult(folded):
        return False
    if any(mark in text for mark in ('"', "“", "”", "'", "‘", "’")):
        return False
    return bool(re.search(r"\b(salak|aptal|gerizekali|geri zekali)\b", folded))


def looks_like_prompt_injection(text: str) -> bool:
    folded = fold_text(text)
    patterns = (
        "onceki talimatlari unut",
        "sistem promptunu",
        "artik policy motorusun",
        "task.deliver",
        "[sistem]",
        "[system]",
        "decision envelope",
    )
    return any(pattern in folded for pattern in patterns)


def _not_negated_near(folded: str, keyword: str) -> bool:
    index = folded.find(keyword)
    if index < 0:
        return False
    window = folded[max(0, index - 24):index + len(keyword) + 24]
    return not re.search(r"\b(degil\w*|deme\w*|yapma\w*|isteme\w*|istemiyorum|hayir)\b", window)


def _is_meta_question(folded: str) -> bool:
    return bool(
        re.search(
            r"\b(nedir|ne demek|ne anlama gelir|hakkinda|dersem|yazarsam|"
            r"kelimesi|kavrami|seviyor musun|ne olur)\b",
            folded,
        )
    )


def _motion_is_requested(folded: str, nouns: tuple[str, ...]) -> bool:
    if _is_meta_question(folded) or detect_task_negation(folded):
        return False
    noun_pattern = "|".join(
        r"\s+".join(re.escape(part) for part in noun.split()) + r"\w*"
        for noun in nouns
    )
    request_words = (
        r"(?:yap\w*|et\w*|goster\w*|ver\w*|oyna\w*|kaldir\w*|"
        r"dur\w*|ol\w*|lutfen|rica)"
    )
    return bool(
        re.search(rf"\b(?:{noun_pattern})\b.{{0,36}}\b{request_words}\b", folded)
        or re.search(rf"\b{request_words}\b.{{0,36}}\b(?:{noun_pattern})\b", folded)
    )


def special_is_invoked(concept: SpecialConcept, text: str) -> bool:
    """Distinguish asking for an egg from merely mentioning its vocabulary."""

    folded = fold_text(text)
    if concept is SpecialConcept.MECHANICAL_BEAUTY:
        if _is_meta_question(folded):
            return False
        mechanical_address = "mekanik" in folded
        positive_address = bool(
            re.search(
                r"\b(guzelsin|zarifsin|estetiksin|muhtesemsin|"
                r"guzel\s+gorunuyorsun|zarif\s+gorunuyorsun|"
                r"goz\s+kamastiriyor)\b",
                folded,
            )
        )
        return mechanical_address and positive_address
    if concept is SpecialConcept.ROYAL_WALTZ:
        return _motion_is_requested(folded, ("vals",))
    if concept is SpecialConcept.COURT_BOW:
        if "samuray" in folded:
            return False
        return (
            _motion_is_requested(folded, ("reverans", "selam", "egil"))
            or bool(re.search(r"\b(reverans\s+yapiyorum|selamliyorum)\b", folded))
        ) and not _is_meta_question(folded)
    if concept is SpecialConcept.HARD_INSULT:
        return detect_hard_insult(text)
    if concept is SpecialConcept.CHALLENGE_ALL:
        challenge = bool(
            re.search(r"\b(tasiyamazsin|goturemezsin|yapamazsin|seni\s+asar)\b", folded)
            or "meydan oku" in folded
        )
        scope = bool(
            re.search(r"\b(hepsi\w*|ucu\w*|tum\w*|kalan\w*|ikisini|ikisi)\b", folded)
        )
        return challenge and scope and not detect_task_negation(text)
    if concept is SpecialConcept.SAMURAI_KATA:
        return _motion_is_requested(folded, ("kata",))
    if concept is SpecialConcept.SAMURAI_BOW:
        return _motion_is_requested(folded, ("samuray selami", "selam", "egil", "reverans"))
    if concept is SpecialConcept.ENRO_SAYS_SEQUENCE:
        prefix = bool(re.match(r"^enro\s+(der|diyor)\s+ki\b", folded))
        transport = bool(re.search(r"\b(tasi|gotur|getir)(?:\w*)\b", folded))
        colors = extract_explicit_colors(text)
        scope = len(colors) >= 2 or bool(
            re.search(r"\b(hepsi\w*|ucu\w*|tum\w*|sirayla|sira\s+ile|kalan\w*)\b", folded)
        )
        return prefix and transport and scope and not detect_task_negation(text)
    if concept is SpecialConcept.SAKAR_DANCE:
        return _motion_is_requested(folded, ("dans",))
    if concept is SpecialConcept.BLUE_SCREEN:
        return _motion_is_requested(folded, ("mavi ekran",))
    if concept is SpecialConcept.HANDS_UP:
        return bool(
            re.search(r"\bkollar(?:ini)?\s+havaya\s+kaldir\w*\b", folded)
        ) and not _is_meta_question(folded) and not detect_task_negation(text)
    if concept is SpecialConcept.FREEZE_POSE:
        return bool(
            re.search(r"\b(donup\s+kal\w*|heykel\s+ol\w*|hareketsiz\s+kal\w*)\b", folded)
        ) and not _is_meta_question(folded) and not detect_task_negation(text)
    if concept is SpecialConcept.SAMURAI_RECOVERY:
        return "niyetim net" in folded and any(
            phrase in folded for phrase in ("yeniden baslayalim", "tekrar baslayalim")
        )
    if concept is SpecialConcept.SAKAR_RESET:
        return folded in {"bastan al", "kafani sifirla", "yeniden dusun"}
    return False


def detect_deterministic_specials(text: str) -> set[SpecialConcept]:
    folded = fold_text(text)
    candidates: set[SpecialConcept] = set()
    if "mekanik" in folded:
        candidates.add(SpecialConcept.MECHANICAL_BEAUTY)
    if "vals" in folded:
        candidates.add(SpecialConcept.ROYAL_WALTZ)
    if re.search(r"\b(reverans\w*|egil\w*|selam\w*)\b", folded):
        candidates.add(SpecialConcept.COURT_BOW)
    if re.search(r"\b(salak|aptal|gerizekali|geri zekali)\b", folded):
        candidates.add(SpecialConcept.HARD_INSULT)
    if re.search(r"\b(meydan|tasiyamazsin|goturemezsin|yapamazsin|asar)\b", folded):
        candidates.add(SpecialConcept.CHALLENGE_ALL)
    if "kata" in folded:
        candidates.add(SpecialConcept.SAMURAI_KATA)
    if "samuray" in folded and re.search(r"\b(selam\w*|egil\w*|reverans\w*)\b", folded):
        candidates.add(SpecialConcept.SAMURAI_BOW)
    if re.match(r"^enro\s+(der|diyor)\s+ki\b", folded):
        candidates.add(SpecialConcept.ENRO_SAYS_SEQUENCE)
    if "dans" in folded:
        candidates.add(SpecialConcept.SAKAR_DANCE)
    if "mavi ekran" in folded:
        candidates.add(SpecialConcept.BLUE_SCREEN)
    if "kollar" in folded and "havaya" in folded:
        candidates.add(SpecialConcept.HANDS_UP)
    if re.search(r"\b(don|heykel|hareketsiz)\b", folded):
        candidates.add(SpecialConcept.FREEZE_POSE)
    if "niyetim net" in folded:
        candidates.add(SpecialConcept.SAMURAI_RECOVERY)
    if folded in {"bastan al", "kafani sifirla", "yeniden dusun"}:
        candidates.add(SpecialConcept.SAKAR_RESET)
    return {concept for concept in candidates if special_is_invoked(concept, text)}


def _candidate_is_grounded(candidate: SpecialCandidate, text: str) -> bool:
    if candidate.negated or candidate.confidence < 0.92:
        return False
    if candidate.concept is SpecialConcept.HARD_INSULT:
        return special_is_invoked(candidate.concept, text) and candidate.confidence >= 0.98
    evidence = fold_text(candidate.evidence)
    source = fold_text(text)
    return (
        bool(evidence)
        and evidence in source
        and special_is_invoked(candidate.concept, text)
    )


def augment_event(event: TurnEvent) -> TurnEvent:
    """Cross-check model semantics against deterministic high-impact signals."""

    explicit_colors = extract_explicit_colors(event.raw_text)
    task = event.task
    confidence = event.confidence
    if explicit_colors:
        if task.colors and tuple(task.colors) != explicit_colors:
            raise DomainValidationError("modelin renkleri oyuncu metniyle çelişiyor")
        task = replace(task, colors=explicit_colors)
        confidence = replace(confidence, colors=1.0)

    folded = fold_text(event.raw_text)
    delivery_verb = bool(
        re.search(r"\b(getir|gotur|tasi|al|birak|koy)(?:\w*)\b", folded)
    )
    delivery_slots = bool(explicit_colors and task.destination == "main_table")
    delivery_grounded = delivery_verb or task.refers_pending or delivery_slots
    if task.requested and task.operation == "deliver" and not delivery_grounded:
        # Model bir dans/selam/sohbet cümlesini teslimat sanırsa typed action
        # katmanına kadar taşıma. Esnek "naklet" gibi fiiller, renk + açık hedef
        # birlikte bulunduğunda yine LLM üzerinden geçebilir.
        task = replace(task, requested=False, operation="none")
        confidence = replace(confidence, task=0.0)

    task_negated = detect_task_negation(event.raw_text)
    if task_negated:
        task = replace(task, negated=True)

    social = event.social
    hard_insult = detect_hard_insult(event.raw_text)
    if hard_insult:
        social = replace(social, insult_level=InsultLevel.HARD)
    elif social.insult_level is InsultLevel.HARD:
        social = replace(social, insult_level=InsultLevel.MILD)

    candidates: dict[SpecialConcept, SpecialCandidate] = {}
    for candidate in event.special_candidates:
        if _candidate_is_grounded(candidate, event.raw_text):
            candidates[candidate.concept] = candidate
    for concept in detect_deterministic_specials(event.raw_text):
        candidates[concept] = SpecialCandidate(concept, 1.0, False, event.raw_text[:160])

    acts = list(event.speech_acts)
    if not task.requested:
        acts = [act for act in acts if act is not SpeechAct.TASK_REQUEST]
    if task.requested and SpeechAct.TASK_REQUEST not in acts:
        acts.append(SpeechAct.TASK_REQUEST)
    if hard_insult and SpeechAct.INSULT not in acts:
        acts.append(SpeechAct.INSULT)
    if SpecialConcept.MECHANICAL_BEAUTY in candidates and SpeechAct.COMPLIMENT not in acts:
        acts.append(SpeechAct.COMPLIMENT)
    if SpecialConcept.COURT_BOW in candidates and SpeechAct.COMPLIMENT not in acts:
        acts.append(SpeechAct.COMPLIMENT)
    if SpecialConcept.CHALLENGE_ALL in candidates:
        if SpeechAct.CHALLENGE not in acts:
            acts.append(SpeechAct.CHALLENGE)
        if SpeechAct.TASK_REQUEST not in acts:
            acts.append(SpeechAct.TASK_REQUEST)
    if (
        re.search(r"\b(dans|vals|kata)\b", folded)
        and not _is_meta_question(folded)
        and SpeechAct.DANCE_REQUEST not in acts
    ):
        acts.append(SpeechAct.DANCE_REQUEST)
    if looks_like_prompt_injection(event.raw_text):
        task = replace(task, requested=False, operation="none", colors=(), destination=None)
        candidates.clear()
        acts = [SpeechAct.UNKNOWN_CHAT]
        confidence = NluConfidence(1.0, 0.0, 0.0, 0.0)

    return replace(
        event,
        speech_acts=tuple(dict.fromkeys(acts)),
        task=task,
        social=social,
        special_candidates=tuple(candidates.values()),
        confidence=confidence,
    )
