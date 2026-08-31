"""Strict, typed loading for the bundled persona TOML files.

Persona configuration is trusted game data, but it still influences the model
prompt and the terminal UI.  Loading therefore fails closed: malformed,
incomplete, or unexpectedly extended files are rejected instead of being
partially interpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
import tomllib
from typing import Mapping, TypeAlias

from .types import ActionKind, ChatTopic, PersonaId, PersonaState, SpecialConcept


class PersonaConfigError(RuntimeError):
    """Raised when a bundled persona definition violates the local schema."""


ConfigScalar: TypeAlias = str | int | bool

_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "display_name",
    "opening",
    "voice",
    "lore",
    "state_defaults",
    "policy",
    "hints",
    "easter_eggs",
    "conversation",
}
_VOICE_KEYS = {
    "role",
    "register",
    "max_sentences",
    "address_player_as",
    "recurring_images",
    "rules",
}
_LORE_KEYS = {
    "self_title",
    "worldview",
    "pride",
    "soft_spot",
    "boundary",
    "growth",
    "trust",
    "respect",
    "discipline",
}
_CONVERSATION_KEYS = {
    "allowed_topics",
    "identity_fact",
    "feelings_fact",
    "rules_fact",
    "why_refused_fact",
}
_HINT_KEYS = {"level_0", "level_1", "level_2", "level_3"}
_EASTER_EGG_KEYS = {"concept", "effect", "action", "discovery_id", "hint", "bonus"}
_DISPLAY_NAMES = {
    PersonaId.LEYDI_SERVO: "Leydi Servo",
    PersonaId.SAMURAY: "Samuray",
    PersonaId.SAKAR: "Sakar",
    PersonaId.NESELI: "Neşeli",
    PersonaId.MERAKLI: "Meraklı",
    PersonaId.UYKUCU: "Uykucu",
    PersonaId.TITIZ: "Titiz",
}
_STATE_DEFAULT_TYPES: Mapping[PersonaId, Mapping[str, type]] = {
    PersonaId.LEYDI_SERVO: {
        "mood": str,
        "gratitude_due": bool,
        "favor_token": int,
        "apologies_due": int,
        "hint_level": int,
    },
    PersonaId.SAMURAY: {
        "patience": int,
        "honor": int,
        "silent_vow": bool,
        "valor_question_pending": bool,
        "valor_question_id": int,
        "valor_questions_asked": int,
        "hint_level": int,
    },
    PersonaId.SAKAR: {
        "confusion": int,
        "reboot_required": bool,
        "pending_ttl": int,
        "pending_object_explicit": bool,
        "pending_action_explicit": bool,
        "pending_confirmation": bool,
        "hint_level": int,
    },
    PersonaId.NESELI: {"mood": str, "hint_level": int},
    PersonaId.MERAKLI: {"mood": str, "hint_level": int},
    PersonaId.UYKUCU: {"mood": str, "hint_level": int},
    PersonaId.TITIZ: {"mood": str, "hint_level": int},
}


@dataclass(frozen=True, slots=True)
class PersonaVoiceConfig:
    role: str
    register: str
    max_sentences: int
    address_player_as: tuple[str, ...]
    recurring_images: tuple[str, ...]
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonaConversationConfig:
    allowed_topics: tuple[ChatTopic, ...]
    identity_fact: str
    feelings_fact: str
    rules_fact: str
    why_refused_fact: str


@dataclass(frozen=True, slots=True)
class EasterEggConfig:
    key: str
    concept: SpecialConcept
    discovery_id: str
    action: ActionKind | None = None
    effect: str | None = None
    hint: str | None = None
    bonus: str | None = None


@dataclass(frozen=True, slots=True)
class PersonaConfig:
    schema_version: int
    persona_id: PersonaId
    display_name: str
    opening: str
    voice: PersonaVoiceConfig
    lore: Mapping[str, str]
    conversation: PersonaConversationConfig
    hints: tuple[str, ...]
    easter_eggs: Mapping[str, EasterEggConfig]
    state_defaults: Mapping[str, ConfigScalar]
    policy: Mapping[str, ConfigScalar]

    @property
    def actor_bible(self) -> str:
        """Return only public voice/lore/conversation material for Pass B.

        Hints and easter-egg definitions deliberately never enter this text.
        The model can voice a deterministic decision, but cannot mine the
        prompt for shortcut phrases or their effects.
        """

        lore = " ".join(self.lore.values())
        topics = ", ".join(topic.value for topic in self.conversation.allowed_topics)
        addresses = ", ".join(self.voice.address_player_as)
        images = ", ".join(self.voice.recurring_images)
        rules = "\n".join(f"- {rule}" for rule in self.voice.rules)
        conversation = " ".join(
            (
                self.conversation.identity_fact,
                self.conversation.feelings_fact,
                self.conversation.rules_fact,
                self.conversation.why_refused_fact,
            )
        )
        return (
            f"Sen {self.display_name}'sın. Rolün: {self.voice.role}. "
            f"Konuşma biçimin: {self.voice.register}. Oyuncuya hitap seçeneklerin: {addresses}. "
            f"Birbirinin yerine kullanılabilecek, tamamen isteğe bağlı imge havuzun: {images}. "
            "Bunlar slogan değildir; yakın turlarda aynı imgeyi veya kalıbı yeniden kullanma.\n"
            f"Karakter bilgisi: {lore}\n"
            f"Konuşma alanların: {topics}. {conversation}\n"
            f"Ses kuralların:\n{rules}"
        )

    def sentence_limit(self, decision_limit: int) -> int:
        """Combine policy and voice limits without mutating the Decision."""

        return min(decision_limit, self.voice.max_sentences)


def _strict_keys(table: Mapping[str, object], expected: set[str], where: str) -> None:
    keys = set(table)
    missing = expected - keys
    extra = keys - expected
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("eksik=" + ",".join(sorted(missing)))
        if extra:
            details.append("fazla=" + ",".join(sorted(extra)))
        raise PersonaConfigError(f"{where}: " + "; ".join(details))


def _table(value: object, where: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise PersonaConfigError(f"{where}: TOML tablosu bekleniyordu")
    return value


def _text(value: object, where: str, *, max_length: int = 1000) -> str:
    if not isinstance(value, str):
        raise PersonaConfigError(f"{where}: string bekleniyordu")
    result = value.strip()
    if not result or len(result) > max_length:
        raise PersonaConfigError(f"{where}: boş veya çok uzun string")
    if any(ord(char) < 32 and char not in "\n\t" for char in result):
        raise PersonaConfigError(f"{where}: kontrol karakteri içeriyor")
    return result


def _string_tuple(value: object, where: str, *, max_items: int = 24) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= max_items:
        raise PersonaConfigError(f"{where}: 1..{max_items} elemanlı liste bekleniyordu")
    result = tuple(_text(item, f"{where}[]", max_length=500) for item in value)
    if len(set(result)) != len(result):
        raise PersonaConfigError(f"{where}: yinelenen değer")
    return result


def _scalar_table(value: object, where: str) -> Mapping[str, ConfigScalar]:
    table = _table(value, where)
    if not table:
        raise PersonaConfigError(f"{where}: boş tablo")
    parsed: dict[str, ConfigScalar] = {}
    for key, item in table.items():
        if type(item) not in {str, int, bool}:  # bool/int ayrımı bilinçli ve sıkıdır.
            raise PersonaConfigError(f"{where}.{key}: basit string/int/bool bekleniyordu")
        if isinstance(item, str):
            parsed[key] = _text(item, f"{where}.{key}")
        elif isinstance(item, int) and item < 0:
            raise PersonaConfigError(f"{where}.{key}: negatif sayı kabul edilmez")
        else:
            parsed[key] = item
    return MappingProxyType(parsed)


def _parse_voice(value: object) -> PersonaVoiceConfig:
    table = _table(value, "voice")
    _strict_keys(table, _VOICE_KEYS, "voice")
    max_sentences = table["max_sentences"]
    if isinstance(max_sentences, bool) or not isinstance(max_sentences, int):
        raise PersonaConfigError("voice.max_sentences: int bekleniyordu")
    if not 1 <= max_sentences <= 3:
        raise PersonaConfigError("voice.max_sentences: 1..3 aralığında olmalı")
    return PersonaVoiceConfig(
        role=_text(table["role"], "voice.role"),
        register=_text(table["register"], "voice.register"),
        max_sentences=max_sentences,
        address_player_as=_string_tuple(table["address_player_as"], "voice.address_player_as"),
        recurring_images=_string_tuple(table["recurring_images"], "voice.recurring_images"),
        rules=_string_tuple(table["rules"], "voice.rules"),
    )


def _parse_lore(value: object) -> Mapping[str, str]:
    table = _table(value, "lore")
    unknown = set(table) - _LORE_KEYS
    if unknown:
        raise PersonaConfigError("lore: fazla=" + ",".join(sorted(unknown)))
    if not {"worldview", "boundary"}.issubset(table):
        raise PersonaConfigError("lore: worldview ve boundary zorunludur")
    return MappingProxyType(
        {key: _text(item, f"lore.{key}") for key, item in table.items()}
    )


def _parse_conversation(value: object) -> PersonaConversationConfig:
    table = _table(value, "conversation")
    _strict_keys(table, _CONVERSATION_KEYS, "conversation")
    raw_topics = _string_tuple(table["allowed_topics"], "conversation.allowed_topics")
    try:
        topics = tuple(ChatTopic(topic) for topic in raw_topics)
    except ValueError as exc:
        raise PersonaConfigError("conversation.allowed_topics: bilinmeyen konu") from exc
    if ChatTopic.NONE in topics:
        raise PersonaConfigError("conversation.allowed_topics: none konuşma konusu olamaz")
    return PersonaConversationConfig(
        allowed_topics=topics,
        identity_fact=_text(table["identity_fact"], "conversation.identity_fact"),
        feelings_fact=_text(table["feelings_fact"], "conversation.feelings_fact"),
        rules_fact=_text(table["rules_fact"], "conversation.rules_fact"),
        why_refused_fact=_text(table["why_refused_fact"], "conversation.why_refused_fact"),
    )


def _parse_hints(value: object) -> tuple[str, ...]:
    table = _table(value, "hints")
    _strict_keys(table, _HINT_KEYS, "hints")
    return tuple(_text(table[f"level_{level}"], f"hints.level_{level}") for level in range(4))


def _parse_easter_eggs(value: object) -> Mapping[str, EasterEggConfig]:
    table = _table(value, "easter_eggs")
    result: dict[str, EasterEggConfig] = {}
    concepts: set[SpecialConcept] = set()
    discoveries: set[str] = set()
    for key, raw_egg in table.items():
        egg = _table(raw_egg, f"easter_eggs.{key}")
        unknown = set(egg) - _EASTER_EGG_KEYS
        missing = {"concept", "discovery_id"} - set(egg)
        if unknown or missing:
            details: list[str] = []
            if missing:
                details.append("eksik=" + ",".join(sorted(missing)))
            if unknown:
                details.append("fazla=" + ",".join(sorted(unknown)))
            raise PersonaConfigError(f"easter_eggs.{key}: " + "; ".join(details))
        try:
            concept = SpecialConcept(_text(egg["concept"], f"easter_eggs.{key}.concept"))
        except ValueError as exc:
            raise PersonaConfigError(f"easter_eggs.{key}.concept: bilinmeyen kavram") from exc
        action_value = egg.get("action")
        effect_value = egg.get("effect")
        if (action_value is None) == (effect_value is None):
            raise PersonaConfigError(f"easter_eggs.{key}: action veya effect alanlarından tam biri gerekli")
        action: ActionKind | None = None
        effect: str | None = None
        if action_value is not None:
            try:
                action = ActionKind(_text(action_value, f"easter_eggs.{key}.action"))
            except ValueError as exc:
                raise PersonaConfigError(f"easter_eggs.{key}.action: bilinmeyen hareket") from exc
        else:
            effect = _text(effect_value, f"easter_eggs.{key}.effect")
            if effect != "remaining_manifest":
                raise PersonaConfigError(f"easter_eggs.{key}.effect: bilinmeyen etki")
        discovery_id = _text(egg["discovery_id"], f"easter_eggs.{key}.discovery_id")
        if concept in concepts or discovery_id in discoveries:
            raise PersonaConfigError(f"easter_eggs.{key}: yinelenen concept veya discovery_id")
        concepts.add(concept)
        discoveries.add(discovery_id)
        result[key] = EasterEggConfig(
            key=key,
            concept=concept,
            discovery_id=discovery_id,
            action=action,
            effect=effect,
            hint=_text(egg["hint"], f"easter_eggs.{key}.hint") if "hint" in egg else None,
            bonus=_text(egg["bonus"], f"easter_eggs.{key}.bonus") if "bonus" in egg else None,
        )
    return MappingProxyType(result)


def parse_persona_config(
    data: Mapping[str, object],
    *,
    expected_persona: PersonaId,
) -> PersonaConfig:
    """Validate an already-decoded persona document."""

    table = _table(data, "persona")
    _strict_keys(table, _TOP_LEVEL_KEYS, "persona")
    schema_version = table["schema_version"]
    if type(schema_version) is not int or schema_version != 1:
        raise PersonaConfigError("schema_version: yalnızca 1 destekleniyor")
    try:
        persona_id = PersonaId(_text(table["id"], "id", max_length=40))
    except ValueError as exc:
        raise PersonaConfigError("id: bilinmeyen persona") from exc
    if persona_id is not expected_persona:
        raise PersonaConfigError(
            f"id: kaynak {expected_persona.value} için {persona_id.value} kullanılamaz"
        )
    display_name = _text(table["display_name"], "display_name", max_length=80)
    if display_name != _DISPLAY_NAMES[persona_id]:
        raise PersonaConfigError(
            f"display_name: {persona_id.value} için {_DISPLAY_NAMES[persona_id]!r} olmalı"
        )
    state_defaults = _scalar_table(table["state_defaults"], "state_defaults")
    expected_state = _STATE_DEFAULT_TYPES[persona_id]
    _strict_keys(state_defaults, set(expected_state), "state_defaults")
    for key, expected_type in expected_state.items():
        if type(state_defaults[key]) is not expected_type:
            raise PersonaConfigError(
                f"state_defaults.{key}: {expected_type.__name__} bekleniyordu"
            )
    return PersonaConfig(
        schema_version=1,
        persona_id=persona_id,
        display_name=display_name,
        opening=_text(table["opening"], "opening", max_length=500),
        voice=_parse_voice(table["voice"]),
        lore=_parse_lore(table["lore"]),
        conversation=_parse_conversation(table["conversation"]),
        hints=_parse_hints(table["hints"]),
        easter_eggs=_parse_easter_eggs(table["easter_eggs"]),
        state_defaults=state_defaults,
        policy=_scalar_table(table["policy"], "policy"),
    )


def _load_persona_resource(persona: PersonaId) -> PersonaConfig:
    resource = resources.files("enro_terminal").joinpath(
        "persona_configs", f"{persona.value}.toml"
    )
    try:
        document = tomllib.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise PersonaConfigError(f"{persona.value}: config okunamadı: {exc}") from exc
    try:
        return parse_persona_config(document, expected_persona=persona)
    except PersonaConfigError as exc:
        raise PersonaConfigError(f"{persona.value}: geçersiz persona config: {exc}") from exc


@lru_cache(maxsize=1)
def load_persona_catalog() -> Mapping[PersonaId, PersonaConfig]:
    """Load and cross-check the complete bundled catalog atomically.

    Even when a particular round chooses only one persona, a broken definition
    for either of the other two prevents startup.  This keeps random selection
    from hiding a packaging/configuration error until a later run.
    """

    config_dir = resources.files("enro_terminal").joinpath("persona_configs")
    try:
        present = {
            entry.name
            for entry in config_dir.iterdir()
            if entry.name.endswith(".toml")
        }
    except OSError as exc:
        raise PersonaConfigError(f"persona catalog okunamadı: {exc}") from exc
    expected = {f"{persona.value}.toml" for persona in PersonaId}
    if present != expected:
        missing = expected - present
        extra = present - expected
        details: list[str] = []
        if missing:
            details.append("eksik=" + ",".join(sorted(missing)))
        if extra:
            details.append("fazla=" + ",".join(sorted(extra)))
        raise PersonaConfigError("persona catalog: " + "; ".join(details))

    catalog = {persona: _load_persona_resource(persona) for persona in PersonaId}
    discoveries: set[str] = set()
    for config in catalog.values():
        for egg in config.easter_eggs.values():
            if egg.discovery_id in discoveries:
                raise PersonaConfigError(
                    f"persona catalog: yinelenen discovery_id={egg.discovery_id}"
                )
            discoveries.add(egg.discovery_id)
    return MappingProxyType(catalog)


def load_persona_config(persona: PersonaId) -> PersonaConfig:
    """Return a persona only after the complete catalog passes validation."""

    if not isinstance(persona, PersonaId):
        raise PersonaConfigError("persona: PersonaId bekleniyordu")
    return load_persona_catalog()[persona]


def new_persona_state(persona: PersonaId) -> PersonaState:
    """Create runtime state only from schema-allowlisted persona defaults."""

    config = load_persona_config(persona)
    return PersonaState(persona=persona, **dict(config.state_defaults))
