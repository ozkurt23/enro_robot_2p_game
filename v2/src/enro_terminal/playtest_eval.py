"""Strict, privacy-conscious release gate for ENRO persona playtests.

Automated tests can prove action safety and dialogue-contract invariants, but
they cannot prove that people enjoy a character.  This module turns the human
part of the release decision into a reproducible, per-persona quality gate.

Input is JSONL with one anonymous rating per participant/persona pair.  Free
text and player utterances are deliberately not part of the schema, keeping
the checked-in evaluator useful without encouraging collection of personal
conversation data.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .types import PersonaId


class PlaytestDataError(ValueError):
    """Raised when a playtest record violates the checked-in schema."""


_RECORD_KEYS = {
    "participant_id",
    "persona",
    "fun",
    "fairness",
    "distinctiveness",
    "control",
    "frustration",
    "replay_interest",
    "completed",
    "had_rejection",
    "recovered_within_two_turns",
}
_ANONYMOUS_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _rating(value: Any, field: str) -> int:
    if type(value) is not int or not 1 <= value <= 5:
        raise PlaytestDataError(f"{field}: 1..5 arasında tam sayı olmalı")
    return value


@dataclass(frozen=True, slots=True)
class PlaytestRecord:
    participant_id: str
    persona: PersonaId
    fun: int
    fairness: int
    distinctiveness: int
    control: int
    frustration: int
    replay_interest: int
    completed: bool
    had_rejection: bool
    recovered_within_two_turns: bool | None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PlaytestRecord":
        if set(data) != _RECORD_KEYS:
            missing = sorted(_RECORD_KEYS - set(data))
            extra = sorted(set(data) - _RECORD_KEYS)
            parts = []
            if missing:
                parts.append("eksik=" + ",".join(missing))
            if extra:
                parts.append("fazla=" + ",".join(extra))
            raise PlaytestDataError("playtest kaydı: " + "; ".join(parts))

        participant_id = data["participant_id"]
        if not isinstance(participant_id, str) or not _ANONYMOUS_ID.fullmatch(
            participant_id
        ):
            raise PlaytestDataError(
                "participant_id: ad/e-posta yerine 8..64 karakterlik anonim kimlik kullan"
            )
        try:
            persona = PersonaId(data["persona"])
        except (TypeError, ValueError) as exc:
            raise PlaytestDataError("persona: bilinmeyen persona") from exc

        for field in ("completed", "had_rejection"):
            if not isinstance(data[field], bool):
                raise PlaytestDataError(f"{field}: bool olmalı")
        recovered = data["recovered_within_two_turns"]
        if data["had_rejection"]:
            if not isinstance(recovered, bool):
                raise PlaytestDataError(
                    "recovered_within_two_turns: ret yaşandıysa bool olmalı"
                )
        elif recovered is not None:
            raise PlaytestDataError(
                "recovered_within_two_turns: ret yaşanmadıysa null olmalı"
            )

        return cls(
            participant_id=participant_id,
            persona=persona,
            fun=_rating(data["fun"], "fun"),
            fairness=_rating(data["fairness"], "fairness"),
            distinctiveness=_rating(data["distinctiveness"], "distinctiveness"),
            control=_rating(data["control"], "control"),
            frustration=_rating(data["frustration"], "frustration"),
            replay_interest=_rating(data["replay_interest"], "replay_interest"),
            completed=data["completed"],
            had_rejection=data["had_rejection"],
            recovered_within_two_turns=recovered,
        )


@dataclass(frozen=True, slots=True)
class PlaytestThresholds:
    minimum_samples: int = 30
    minimum_rejection_samples: int = 10
    minimum_positive_wilson_lower_bound: float = 0.70
    minimum_completion_rate: float = 0.90
    minimum_recovery_rate: float = 0.95
    minimum_median_positive_rating: float = 4.0
    maximum_median_frustration: float = 2.0

    def __post_init__(self) -> None:
        if self.minimum_samples < 1 or self.minimum_rejection_samples < 1:
            raise ValueError("örnek eşikleri pozitif olmalı")
        for value in (
            self.minimum_positive_wilson_lower_bound,
            self.minimum_completion_rate,
            self.minimum_recovery_rate,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("oran eşikleri 0..1 aralığında olmalı")


@dataclass(frozen=True, slots=True)
class PersonaPlaytestSummary:
    persona: PersonaId
    samples: int
    rejection_samples: int
    positive_rate: float
    positive_wilson_lower_bound: float
    completion_rate: float
    recovery_rate: float | None
    median_fun: float
    median_fairness: float
    median_distinctiveness: float
    median_control: float
    median_frustration: float
    median_replay_interest: float
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class PlaytestReport:
    summaries: tuple[PersonaPlaytestSummary, ...]
    duplicate_pairs: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.duplicate_pairs and all(item.passed for item in self.summaries)


def wilson_lower_bound(successes: int, total: int, *, z: float = 1.959963984540054) -> float:
    """Return the two-sided 95% Wilson lower confidence bound."""

    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("Wilson hesabı için 0 <= başarı <= toplam ve toplam > 0 olmalı")
    proportion = successes / total
    z_squared = z * z
    denominator = 1.0 + z_squared / total
    centre = proportion + z_squared / (2.0 * total)
    margin = z * math.sqrt(
        (proportion * (1.0 - proportion) + z_squared / (4.0 * total)) / total
    )
    return (centre - margin) / denominator


def _rate(records: Sequence[PlaytestRecord], field: str) -> float:
    return sum(bool(getattr(record, field)) for record in records) / len(records)


def _summarize(
    persona: PersonaId,
    records: Sequence[PlaytestRecord],
    thresholds: PlaytestThresholds,
) -> PersonaPlaytestSummary:
    failures: list[str] = []
    samples = len(records)
    if samples < thresholds.minimum_samples:
        failures.append(
            f"örnek sayısı {samples}; gereken en az {thresholds.minimum_samples}"
        )

    if not records:
        return PersonaPlaytestSummary(
            persona=persona,
            samples=0,
            rejection_samples=0,
            positive_rate=0.0,
            positive_wilson_lower_bound=0.0,
            completion_rate=0.0,
            recovery_rate=None,
            median_fun=0.0,
            median_fairness=0.0,
            median_distinctiveness=0.0,
            median_control=0.0,
            median_frustration=0.0,
            median_replay_interest=0.0,
            failures=tuple(failures),
        )

    positive = sum(record.fun >= 4 and record.fairness >= 4 for record in records)
    positive_rate = positive / samples
    positive_lower = wilson_lower_bound(positive, samples)
    if positive_lower < thresholds.minimum_positive_wilson_lower_bound:
        failures.append(
            "eğlence+adalet pozitif oranının %95 alt güven sınırı "
            f"{positive_lower:.3f}; gereken {thresholds.minimum_positive_wilson_lower_bound:.3f}"
        )

    completion_rate = _rate(records, "completed")
    if completion_rate < thresholds.minimum_completion_rate:
        failures.append(
            f"tamamlama oranı {completion_rate:.3f}; gereken {thresholds.minimum_completion_rate:.3f}"
        )

    rejection_records = [record for record in records if record.had_rejection]
    recovery_rate: float | None = None
    if len(rejection_records) < thresholds.minimum_rejection_samples:
        failures.append(
            f"ret/recovery örneği {len(rejection_records)}; gereken en az "
            f"{thresholds.minimum_rejection_samples}"
        )
    else:
        recovery_rate = sum(
            record.recovered_within_two_turns is True for record in rejection_records
        ) / len(rejection_records)
        if recovery_rate < thresholds.minimum_recovery_rate:
            failures.append(
                f"iki turda recovery oranı {recovery_rate:.3f}; gereken "
                f"{thresholds.minimum_recovery_rate:.3f}"
            )

    medians = {
        field: float(median(getattr(record, field) for record in records))
        for field in (
            "fun",
            "fairness",
            "distinctiveness",
            "control",
            "frustration",
            "replay_interest",
        )
    }
    for field, label in (
        ("fun", "eğlence"),
        ("fairness", "adalet"),
        ("distinctiveness", "ayırt edilebilirlik"),
        ("control", "oyuncu kontrolü"),
        ("replay_interest", "tekrar oynama isteği"),
    ):
        if medians[field] < thresholds.minimum_median_positive_rating:
            failures.append(
                f"{label} medyanı {medians[field]:.1f}; gereken "
                f"{thresholds.minimum_median_positive_rating:.1f}"
            )
    if medians["frustration"] > thresholds.maximum_median_frustration:
        failures.append(
            f"hayal kırıklığı medyanı {medians['frustration']:.1f}; izin verilen en çok "
            f"{thresholds.maximum_median_frustration:.1f}"
        )

    return PersonaPlaytestSummary(
        persona=persona,
        samples=samples,
        rejection_samples=len(rejection_records),
        positive_rate=positive_rate,
        positive_wilson_lower_bound=positive_lower,
        completion_rate=completion_rate,
        recovery_rate=recovery_rate,
        median_fun=medians["fun"],
        median_fairness=medians["fairness"],
        median_distinctiveness=medians["distinctiveness"],
        median_control=medians["control"],
        median_frustration=medians["frustration"],
        median_replay_interest=medians["replay_interest"],
        failures=tuple(failures),
    )


def evaluate_playtests(
    records: Iterable[PlaytestRecord],
    *,
    thresholds: PlaytestThresholds | None = None,
) -> PlaytestReport:
    """Evaluate every persona independently; missing personas fail closed."""

    selected_thresholds = thresholds or PlaytestThresholds()
    materialized = tuple(records)
    seen: set[tuple[str, PersonaId]] = set()
    duplicates: list[str] = []
    for record in materialized:
        key = (record.participant_id, record.persona)
        if key in seen:
            duplicates.append(f"{record.participant_id}/{record.persona.value}")
        seen.add(key)

    summaries = tuple(
        _summarize(
            persona,
            tuple(record for record in materialized if record.persona is persona),
            selected_thresholds,
        )
        for persona in PersonaId
    )
    return PlaytestReport(summaries=summaries, duplicate_pairs=tuple(sorted(duplicates)))


def load_playtest_jsonl(path: Path) -> tuple[PlaytestRecord, ...]:
    records: list[PlaytestRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                decoded = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PlaytestDataError(f"satır {line_number}: geçersiz JSON") from exc
            if not isinstance(decoded, Mapping):
                raise PlaytestDataError(f"satır {line_number}: JSON object bekleniyordu")
            try:
                records.append(PlaytestRecord.from_mapping(decoded))
            except PlaytestDataError as exc:
                raise PlaytestDataError(f"satır {line_number}: {exc}") from exc
    return tuple(records)


def _print_report(report: PlaytestReport) -> None:
    for summary in report.summaries:
        status = "GEÇTİ" if summary.passed else "KALDI"
        recovery = "yetersiz veri" if summary.recovery_rate is None else f"{summary.recovery_rate:.1%}"
        print(
            f"{summary.persona.display_name}: {status} | n={summary.samples} | "
            f"pozitif-alt=%{summary.positive_wilson_lower_bound * 100:.1f} | "
            f"tamamlama={summary.completion_rate:.1%} | recovery={recovery}"
        )
        for failure in summary.failures:
            print(f"  - {failure}")
    for duplicate in report.duplicate_pairs:
        print(f"TEKRAR: {duplicate}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Anonim ENRO persona playtest JSONL dosyasını yayın eşiklerine göre değerlendir."
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate_playtests(load_playtest_jsonl(args.path))
    except (OSError, PlaytestDataError) as exc:
        parser.error(str(exc))
    _print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
