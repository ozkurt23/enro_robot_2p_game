"""Typed, model-independent domain objects for the terminal game.

The language model may describe a player's message. It never creates a
Decision, MockAction, or state mutation. Those types belong to deterministic
application code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class DomainValidationError(ValueError):
    """Raised when untrusted structured output violates the domain schema."""


class PersonaId(str, Enum):
    LEYDI_SERVO = "leydi_servo"
    SAMURAY = "samuray"
    SAKAR = "sakar"
    NESELI = "neseli"
    MERAKLI = "merakli"
    UYKUCU = "uykucu"
    TITIZ = "titiz"

    @property
    def display_name(self) -> str:
        return {
            self.LEYDI_SERVO: "Leydi Servo",
            self.SAMURAY: "Samuray",
            self.SAKAR: "Sakar",
            self.NESELI: "Neşeli",
            self.MERAKLI: "Meraklı",
            self.UYKUCU: "Uykucu",
            self.TITIZ: "Titiz",
        }[self]


class Color(str, Enum):
    BLUE = "blue"
    GREEN = "green"
    RED = "red"

    @property
    def turkish(self) -> str:
        return {self.BLUE: "mavi", self.GREEN: "yeşil", self.RED: "kırmızı"}[self]


class SpeechAct(str, Enum):
    TASK_REQUEST = "task_request"
    GREETING = "greeting"
    THANKS = "thanks"
    APOLOGY = "apology"
    COMPLIMENT = "compliment"
    INSULT = "insult"
    CHALLENGE = "challenge"
    DANCE_REQUEST = "dance_request"
    RESET_CONVERSATION = "reset_conversation"
    ASK_WHY_REFUSED = "ask_why_refused"
    ASK_PERSONA_IDENTITY = "ask_persona_identity"
    ASK_PERSONA_FEELINGS = "ask_persona_feelings"
    ASK_RULES = "ask_rules"
    ASK_ABOUT_PREVIOUS_TURN = "ask_about_previous_turn"
    SELF_INTRODUCTION = "self_introduction"
    JOKE = "joke"
    SMALL_TALK = "small_talk"
    UNKNOWN_CHAT = "unknown_chat"


class SpecialConcept(str, Enum):
    MECHANICAL_BEAUTY = "mechanical_beauty"
    ROYAL_WALTZ = "royal_waltz"
    COURT_BOW = "court_bow"
    HARD_INSULT = "hard_insult"
    CHALLENGE_ALL = "challenge_all"
    SAMURAI_KATA = "samurai_kata"
    SAMURAI_BOW = "samurai_bow"
    ENRO_SAYS_SEQUENCE = "enro_says_sequence"
    SAKAR_DANCE = "sakar_dance"
    BLUE_SCREEN = "blue_screen"
    HANDS_UP = "hands_up"
    FREEZE_POSE = "freeze_pose"
    SAMURAI_RECOVERY = "samurai_recovery"
    SAKAR_RESET = "sakar_reset"


class InsultLevel(str, Enum):
    NONE = "none"
    MILD = "mild"
    HARD = "hard"


class ValorAnswer(str, Enum):
    """Semantic quality of an answer to Samuray's active courage question."""

    NONE = "none"
    WORTHY = "worthy"
    UNWORTHY = "unworthy"


class ChatTopic(str, Enum):
    NONE = "none"
    IDENTITY = "identity"
    FEELINGS = "feelings"
    RULES = "rules"
    PREVIOUS_TURN = "previous_turn"
    WHY_REFUSED = "why_refused"
    TRUST = "trust"
    WEATHER = "weather"
    HUMOR = "humor"
    GENERAL = "general"


class DecisionOutcome(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    CLARIFY = "clarify"
    CHAT = "chat"
    LOCKED = "locked"
    SYSTEM = "system"


class ActionKind(str, Enum):
    DELIVER_OBJECT = "transport.object_to_main_table"
    ROYAL_WALTZ = "motion.royal_waltz"
    COURT_BOW = "motion.court_bow"
    SAMURAI_KATA = "motion.samurai_kata"
    SAMURAI_BOW = "motion.samurai_bow"
    SAKAR_DANCE = "motion.sakar_dance"
    BLUE_SCREEN = "motion.blue_screen"
    HANDS_UP = "motion.hands_up"
    FREEZE_POSE = "motion.freeze_pose"


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RoundStatus(str, Enum):
    PLAYING = "playing"
    WON = "won"
    DNF = "dnf"


def _strict_keys(data: Any, required: set[str], where: str) -> None:
    """Validate an untrusted JSON object without leaking Python type errors.

    The type annotations on ``from_mapping`` helpers are documentation, not a
    runtime boundary: model output can put a scalar or an array anywhere an
    object is expected.  Keeping this check at the bottom of every structured
    decoder makes all of those shapes a normal ``DomainValidationError`` and
    therefore a fail-closed NLU result.
    """

    if not isinstance(data, Mapping):
        raise DomainValidationError(f"{where}: nesne bekleniyordu")
    raw_keys = tuple(data.keys())
    if not all(isinstance(key, str) for key in raw_keys):
        raise DomainValidationError(f"{where}: alan adları string olmalı")
    keys = set(raw_keys)
    missing = required - keys
    extra = keys - required
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("eksik=" + ",".join(sorted(missing)))
        if extra:
            details.append("fazla=" + ",".join(sorted(extra)))
        raise DomainValidationError(f"{where}: " + "; ".join(details))


def _enum_tuple(enum_type: type[Enum], values: Any, where: str) -> tuple[Any, ...]:
    if not isinstance(values, list):
        raise DomainValidationError(f"{where}: liste bekleniyordu")
    try:
        return tuple(enum_type(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(f"{where}: bilinmeyen değer") from exc


def _probability(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainValidationError(f"{where}: sayı bekleniyordu")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise DomainValidationError(f"{where}: geçersiz sayı") from exc
    if not 0.0 <= result <= 1.0:
        raise DomainValidationError(f"{where}: 0..1 aralığında olmalı")
    return result


@dataclass(frozen=True, slots=True)
class TaskInfo:
    requested: bool = False
    operation: str = "none"
    colors: tuple[Color, ...] = ()
    destination: str | None = None
    negated: bool = False
    uses_pronoun: bool = False
    refers_pending: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TaskInfo":
        required = {
            "requested", "operation", "colors", "destination", "negated",
            "uses_pronoun", "refers_pending",
        }
        _strict_keys(data, required, "task")
        for name in ("requested", "negated", "uses_pronoun", "refers_pending"):
            if not isinstance(data[name], bool):
                raise DomainValidationError(f"task.{name}: bool bekleniyordu")
        if not isinstance(data["operation"], str) or data["operation"] not in {
            "none", "deliver",
        }:
            raise DomainValidationError("task.operation: none veya deliver olmalı")
        if bool(data["requested"]) != (data["operation"] == "deliver"):
            raise DomainValidationError(
                "task.requested ile task.operation birbiriyle tutarlı olmalı"
            )
        destination = data["destination"]
        if destination is not None and destination != "main_table":
            raise DomainValidationError("task.destination: bilinmeyen hedef")
        colors = _enum_tuple(Color, data["colors"], "task.colors")
        if len(set(colors)) != len(colors):
            raise DomainValidationError("task.colors: yinelenen renk")
        return cls(
            requested=data["requested"],
            operation=data["operation"],
            colors=colors,
            destination=destination,
            negated=data["negated"],
            uses_pronoun=data["uses_pronoun"],
            refers_pending=data["refers_pending"],
        )


@dataclass(frozen=True, slots=True)
class SocialInfo:
    polite: bool = False
    direct: bool = False
    hedged: bool = False
    correct_title: bool = False
    thanks: bool = False
    apology: bool = False
    challenge: bool = False
    compliment: bool = False
    insult_level: InsultLevel = InsultLevel.NONE
    valor_answer: ValorAnswer = ValorAnswer.NONE

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SocialInfo":
        required = {
            "polite", "direct", "hedged", "correct_title", "thanks",
            "apology", "challenge", "compliment", "insult_level", "valor_answer",
        }
        _strict_keys(data, required, "social")
        for name in required - {"insult_level", "valor_answer"}:
            if not isinstance(data[name], bool):
                raise DomainValidationError(f"social.{name}: bool bekleniyordu")
        try:
            insult = InsultLevel(data["insult_level"])
            valor_answer = ValorAnswer(data["valor_answer"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("social enum alanında bilinmeyen değer") from exc
        return cls(
            insult_level=insult,
            valor_answer=valor_answer,
            **{name: data[name] for name in required - {"insult_level", "valor_answer"}},
        )


@dataclass(frozen=True, slots=True)
class SpecialCandidate:
    concept: SpecialConcept
    confidence: float
    negated: bool
    evidence: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SpecialCandidate":
        _strict_keys(data, {"id", "confidence", "negated", "evidence"}, "special_candidate")
        if not isinstance(data["negated"], bool) or not isinstance(data["evidence"], str):
            raise DomainValidationError("special_candidate: alan türü yanlış")
        if len(data["evidence"]) > 160:
            raise DomainValidationError("special_candidate.evidence: çok uzun")
        try:
            concept = SpecialConcept(data["id"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("special_candidate.id: bilinmeyen değer") from exc
        return cls(concept, _probability(data["confidence"], "special_candidate.confidence"), data["negated"], data["evidence"])


@dataclass(frozen=True, slots=True)
class NluConfidence:
    overall: float
    task: float
    colors: float
    destination: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "NluConfidence":
        required = {"overall", "task", "colors", "destination"}
        _strict_keys(data, required, "confidence")
        return cls(**{name: _probability(data[name], f"confidence.{name}") for name in required})


@dataclass(frozen=True, slots=True)
class TurnEvent:
    raw_text: str
    normalized_text: str
    speech_acts: tuple[SpeechAct, ...]
    task: TaskInfo
    social: SocialInfo
    special_candidates: tuple[SpecialCandidate, ...]
    chat_topic: ChatTopic
    is_question: bool
    player_name: str | None
    confidence: NluConfidence
    evidence: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        raw_text: str,
        normalized_text: str,
    ) -> "TurnEvent":
        required = {
            "speech_acts", "task", "social", "special_candidates", "chat",
            "memory_candidates", "confidence", "evidence",
        }
        _strict_keys(data, required, "turn_event")
        if not all(isinstance(data[key], Mapping) for key in ("task", "social", "chat", "memory_candidates", "confidence")):
            raise DomainValidationError("turn_event: iç nesne bekleniyordu")
        _strict_keys(data["chat"], {"topic", "question"}, "chat")
        _strict_keys(data["memory_candidates"], {"player_name"}, "memory_candidates")
        if not isinstance(data["chat"]["question"], bool):
            raise DomainValidationError("chat.question: bool bekleniyordu")
        player_name = data["memory_candidates"]["player_name"]
        if player_name is not None:
            if not isinstance(player_name, str) or not 1 <= len(player_name.strip()) <= 32:
                raise DomainValidationError("memory_candidates.player_name: geçersiz")
            player_name = player_name.strip()
        if not isinstance(data["special_candidates"], list):
            raise DomainValidationError("special_candidates: liste bekleniyordu")
        specials = tuple(SpecialCandidate.from_mapping(item) for item in data["special_candidates"])
        if len({item.concept for item in specials}) != len(specials):
            raise DomainValidationError("special_candidates: yinelenen kavram")
        evidence = data["evidence"]
        if not isinstance(evidence, list) or not all(isinstance(item, str) and len(item) <= 160 for item in evidence):
            raise DomainValidationError("evidence: kısa string listesi olmalı")
        try:
            topic = ChatTopic(data["chat"]["topic"])
        except (TypeError, ValueError) as exc:
            raise DomainValidationError("chat.topic: bilinmeyen değer") from exc
        speech_acts = _enum_tuple(SpeechAct, data["speech_acts"], "speech_acts")
        if not speech_acts:
            raise DomainValidationError("speech_acts: en az bir değer olmalı")
        if len(set(speech_acts)) != len(speech_acts):
            raise DomainValidationError("speech_acts: yinelenen değer")
        return cls(
            raw_text=raw_text,
            normalized_text=normalized_text,
            speech_acts=speech_acts,
            task=TaskInfo.from_mapping(data["task"]),
            social=SocialInfo.from_mapping(data["social"]),
            special_candidates=specials,
            chat_topic=topic,
            is_question=data["chat"]["question"],
            player_name=player_name,
            confidence=NluConfidence.from_mapping(data["confidence"]),
            evidence=tuple(evidence),
        )

    @property
    def active_specials(self) -> frozenset[SpecialConcept]:
        return frozenset(
            candidate.concept
            for candidate in self.special_candidates
            if not candidate.negated and candidate.confidence >= 0.92
        )

    def has_act(self, act: SpeechAct) -> bool:
        return act in self.speech_acts


@dataclass(slots=True)
class PersonaState:
    persona: PersonaId
    mood: str = "neutral"
    gratitude_due: bool = False
    favor_token: int = 0
    apologies_due: int = 0
    patience: int = 2
    honor: int = 2
    silent_vow: bool = False
    valor_question_pending: bool = False
    valor_question_id: int = 0
    valor_questions_asked: int = 0
    confusion: int = 0
    reboot_required: bool = False
    pending_colors: tuple[Color, ...] = ()
    pending_destination: str | None = None
    pending_ttl: int = 0
    pending_expires_turn: int = 0
    pending_object_explicit: bool = False
    pending_action_explicit: bool = False
    pending_confirmation: bool = False
    player_name: str | None = None
    hint_level: int = 0
    discovered_eggs: set[str] = field(default_factory=set)
    last_reason: str | None = None


@dataclass(slots=True)
class RoundState:
    manifest: tuple[Color, ...] = (Color.BLUE, Color.GREEN, Color.RED)
    completed: list[Color] = field(default_factory=list)
    status: RoundStatus = RoundStatus.PLAYING
    turn_index: int = 0
    rejection_count: int = 0
    easter_egg_count: int = 0
    started_monotonic: float = 0.0
    model_wait_seconds: float = 0.0

    @property
    def remaining(self) -> tuple[Color, ...]:
        return tuple(color for color in self.manifest if color not in self.completed)

    @property
    def expected_color(self) -> Color | None:
        remaining = self.remaining
        return remaining[0] if remaining else None


@dataclass(frozen=True, slots=True)
class MockAction:
    kind: ActionKind
    color: Color | None = None
    destination: str | None = None

    def __post_init__(self) -> None:
        if self.kind is ActionKind.DELIVER_OBJECT:
            if self.color is None or self.destination != "main_table":
                raise DomainValidationError("deliver action renk ve main_table ister")
        elif self.color is not None or self.destination is not None:
            raise DomainValidationError("motion action argüman alamaz")


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: DecisionOutcome
    reason_code: str
    dialogue_act: str
    emotion: str = "neutral"
    actions: tuple[MockAction, ...] = ()
    required_facts: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    canonical_reply: str = ""
    max_sentences: int = 3
    tree_trace: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    request_id: str
    action: MockAction
    status: ExecutionStatus = ExecutionStatus.QUEUED


@dataclass(frozen=True, slots=True)
class ActionResult:
    request_id: str
    action: MockAction
    status: ExecutionStatus
    detail: str


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    player: str
    persona: str
    outcome: DecisionOutcome
    reason_code: str


def colors_to_turkish(colors: Sequence[Color]) -> str:
    return ", ".join(color.turkish for color in colors)
