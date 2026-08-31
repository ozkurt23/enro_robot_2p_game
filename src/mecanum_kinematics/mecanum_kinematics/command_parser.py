"""Deterministic Turkish command parser for the supported robot cases.

The language model is deliberately not involved in these mappings.  Known
commands always resolve to the same bounded robot skill; an LLM may only be
used as a fallback for text outside this grammar.
"""

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class ParsedCommand:
    """A validated symbolic robot command."""

    action: str
    arguments: tuple[str, ...] = ()


_ENTITY_PATTERNS = (
    ("stack", re.compile(r"\b(?:ana\s+masa\w*|istif\w*|stack\w*)\b")),
    ("center", re.compile(r"\b(?:merkez\w*|center\w*)\b")),
    ("red", re.compile(r"\b(?:kirmizi\w*|red\w*)\b")),
    ("blue", re.compile(r"\b(?:mavi\w*|blue\w*)\b")),
    ("green", re.compile(r"\b(?:yesil\w*|green\w*)\b")),
)

_TRANSFER_VERBS = re.compile(
    r"\b(?:tasi\w*|gotur\w*|koy\w*|birak\w*|aktar\w*)\b"
)
_GO_VERBS = re.compile(r"\b(?:git\w*|yonel\w*|ilerle\w*)\b")
_STACK_ALL = re.compile(
    r"\b(?:tum|butun)\b.*\b(?:kup\w*|cisim\w*)\b.*\b(?:diz\w*|istifle\w*)\b"
)


def normalize_turkish(text: str) -> str:
    """Return a punctuation-free ASCII-ish representation of Turkish text."""

    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    normalized = normalized.translate(str.maketrans({
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ü": "u",
        "ö": "o",
        "ç": "c",
    }))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _ordered_entities(text: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    for entity, pattern in _ENTITY_PATTERNS:
        matches.extend((match.start(), entity) for match in pattern.finditer(text))
    matches.sort()

    return [entity for _, entity in matches]


def parse_command(text: str) -> ParsedCommand | None:
    """Parse a supported instruction without consulting a language model."""

    normalized = normalize_turkish(text)
    if not normalized:
        return None

    if normalized in {"cik", "exit", "quit", "kapat"}:
        return ParsedCommand("exit")

    if _STACK_ALL.search(normalized):
        return ParsedCommand("stack_all")

    entities = _ordered_entities(normalized)
    if _TRANSFER_VERBS.search(normalized) and len(entities) >= 2:
        source, target = entities[0], entities[1]
        if source not in {"red", "blue", "green"}:
            return None
        if target not in {"red", "blue", "green", "stack"}:
            return None
        if source == target:
            return ParsedCommand("reject_same_location", (source,))
        return ParsedCommand("transfer", (source, target))

    if _GO_VERBS.search(normalized) and entities:
        return ParsedCommand("go", (entities[0],))

    return None
