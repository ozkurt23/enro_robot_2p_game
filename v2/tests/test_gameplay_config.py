"""Strict gameplay profiles stay separate from personas and robot skills."""

from __future__ import annotations

from copy import deepcopy
from importlib import resources
import tomllib

import pytest

from enro_terminal import cli
from enro_terminal.gameplay import (
    GameplayConfigError,
    load_gameplay_catalog,
    load_gameplay_config,
    parse_gameplay_config,
)
from enro_terminal.types import Color


def _document(gameplay_id: str) -> dict[str, object]:
    text = resources.files("enro_terminal").joinpath(
        "gameplay_configs", f"{gameplay_id}.toml"
    ).read_text(encoding="utf-8")
    return tomllib.loads(text)


def test_bundled_gameplays_are_strict_and_persona_independent():
    catalog = load_gameplay_catalog()

    assert set(catalog) == {"festival", "blue_demo"}
    assert catalog["festival"].manifest == (
        Color.BLUE,
        Color.GREEN,
        Color.RED,
    )
    assert catalog["blue_demo"].manifest == (Color.BLUE,)
    assert catalog["festival"].destination == "main_table"


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda doc: doc.update(schema_version=2), "schema_version"),
        (lambda doc: doc.update(unexpected=True), "fazla=unexpected"),
        (lambda doc: doc.update(manifest=[]), "manifest"),
        (lambda doc: doc.update(manifest=["blue", "blue"]), "yinelenen"),
        (lambda doc: doc.update(ordering="free"), "sequential"),
        (lambda doc: doc.update(timeout_seconds=5), "30..900"),
    ],
)
def test_invalid_gameplay_fails_closed(mutation, fragment):
    document = deepcopy(_document("festival"))
    mutation(document)

    with pytest.raises(GameplayConfigError, match=fragment):
        parse_gameplay_config(document, expected_id="festival")


def test_unknown_gameplay_is_rejected():
    with pytest.raises(GameplayConfigError, match="bilinmeyen gameplay"):
        load_gameplay_config("unknown")


def test_blue_demo_finishes_after_one_physically_authorized_color(tmp_path, capsys):
    script = tmp_path / "blue-demo.txt"
    script.write_text(
        "Mavi cismi ana masaya getir.\n"
        "Evet, onaylıyorum.\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "--backend",
            "rules",
            "--persona",
            "sakar",
            "--gameplay",
            "blue_demo",
            "--no-store",
            "--script",
            str(script),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Tek Mavi Demo (blue_demo)" in captured.out
    assert "Hedef sıra   : mavi" in captured.out
    assert "doğrulanmış görev zinciri tamamlandı" in captured.out
    assert "yeşil cisim simde" not in captured.out
