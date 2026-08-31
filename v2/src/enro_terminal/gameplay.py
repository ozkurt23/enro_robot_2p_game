"""Strict, data-driven gameplay profiles independent from persona voice."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
import tomllib
from typing import Any, Mapping

from .types import Color


class GameplayConfigError(ValueError):
    """Raised before model/ROS startup when a gameplay profile is invalid."""


@dataclass(frozen=True, slots=True)
class GameplayConfig:
    schema_version: int
    gameplay_id: str
    display_name: str
    manifest: tuple[Color, ...]
    destination: str
    ordering: str
    timeout_seconds: float


def _strict_keys(document: Mapping[str, Any], required: set[str]) -> None:
    keys = set(document)
    missing = required - keys
    extra = keys - required
    details: list[str] = []
    if missing:
        details.append("eksik=" + ",".join(sorted(missing)))
    if extra:
        details.append("fazla=" + ",".join(sorted(extra)))
    if details:
        raise GameplayConfigError("gameplay: " + "; ".join(details))


def parse_gameplay_config(
    document: Mapping[str, Any],
    *,
    expected_id: str,
) -> GameplayConfig:
    required = {
        "schema_version",
        "gameplay_id",
        "display_name",
        "manifest",
        "destination",
        "ordering",
        "timeout_seconds",
    }
    _strict_keys(document, required)

    version = document["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise GameplayConfigError("gameplay.schema_version yalnız 1 olabilir")

    gameplay_id = document["gameplay_id"]
    if gameplay_id != expected_id:
        raise GameplayConfigError(
            f"gameplay kaynak {expected_id}, içerik kimliği {gameplay_id!r}"
        )

    display_name = document["display_name"]
    if not isinstance(display_name, str) or not display_name.strip():
        raise GameplayConfigError("gameplay.display_name boş olmayan string olmalı")

    raw_manifest = document["manifest"]
    if not isinstance(raw_manifest, list) or not raw_manifest:
        raise GameplayConfigError("gameplay.manifest boş olmayan renk listesi olmalı")
    try:
        manifest = tuple(Color(value) for value in raw_manifest)
    except (TypeError, ValueError) as exc:
        raise GameplayConfigError("gameplay.manifest bilinmeyen renk içeriyor") from exc
    if len(set(manifest)) != len(manifest):
        raise GameplayConfigError("gameplay.manifest yinelenen renk içeremez")

    destination = document["destination"]
    if destination != "main_table":
        raise GameplayConfigError("şimdilik yalnız main_table hedefi destekleniyor")

    ordering = document["ordering"]
    if ordering != "sequential":
        raise GameplayConfigError("şimdilik yalnız sequential sıralama destekleniyor")

    timeout = document["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise GameplayConfigError("gameplay.timeout_seconds sayı olmalı")
    timeout_seconds = float(timeout)
    if not 30.0 <= timeout_seconds <= 900.0:
        raise GameplayConfigError("gameplay.timeout_seconds 30..900 aralığında olmalı")

    return GameplayConfig(
        schema_version=version,
        gameplay_id=gameplay_id,
        display_name=display_name.strip(),
        manifest=manifest,
        destination=destination,
        ordering=ordering,
        timeout_seconds=timeout_seconds,
    )


@lru_cache(maxsize=1)
def load_gameplay_catalog() -> Mapping[str, GameplayConfig]:
    root = resources.files("enro_terminal").joinpath("gameplay_configs")
    catalog: dict[str, GameplayConfig] = {}
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".toml"):
            continue
        gameplay_id = resource.name.removesuffix(".toml")
        try:
            document = tomllib.loads(resource.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise GameplayConfigError(
                f"{resource.name} okunamadı: {exc}"
            ) from exc
        catalog[gameplay_id] = parse_gameplay_config(
            document,
            expected_id=gameplay_id,
        )
    if not catalog:
        raise GameplayConfigError("pakette gameplay profili bulunamadı")
    return MappingProxyType(catalog)


def load_gameplay_config(gameplay_id: str) -> GameplayConfig:
    try:
        return load_gameplay_catalog()[gameplay_id]
    except KeyError as exc:
        raise GameplayConfigError(f"bilinmeyen gameplay: {gameplay_id}") from exc


def gameplay_ids() -> tuple[str, ...]:
    return tuple(load_gameplay_catalog())
