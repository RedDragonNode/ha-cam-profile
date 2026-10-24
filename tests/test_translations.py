"""Übersetzungen: gleiche Schlüssel in beiden Sprachen und keine unbekannten Platzhalter."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

TRANSLATIONS = Path(__file__).resolve().parents[1] / "custom_components" / "cam_profile" / "translations"
# Das Frontend liest jede geschweifte Klammer als Platzhalter und meldet einen Fehler, wenn der Wert fehlt.
ALLOWED_PLACEHOLDERS = {"name", "profile", "reason", "details", "overridden", "value"}


def _flatten(node: object, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        out: dict[str, str] = {}
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: str(node)}


@pytest.fixture(scope="module")
def texts() -> dict[str, dict[str, str]]:
    return {
        lang: _flatten(json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))) for lang in ("de", "en")
    }


def test_both_languages_have_the_same_keys(texts: dict[str, dict[str, str]]) -> None:
    assert set(texts["de"]) == set(texts["en"])


@pytest.mark.parametrize("lang", ["de", "en"])
def test_only_known_placeholders(texts: dict[str, dict[str, str]], lang: str) -> None:
    for key, text in texts[lang].items():
        assert set(re.findall(r"\{([^{}]*)\}", text)) <= ALLOWED_PLACEHOLDERS, f"{lang}: {key}"
        assert text.count("{") == text.count("}"), f"{lang}: {key}"


def test_placeholders_match_between_languages(texts: dict[str, dict[str, str]]) -> None:
    for key, de_text in texts["de"].items():
        assert set(re.findall(r"\{(\w+)\}", de_text)) == set(re.findall(r"\{(\w+)\}", texts["en"][key])), key


@pytest.mark.parametrize("lang", ["de", "en"])
def test_weekday_entities_sort_in_weekday_order_and_together(texts: dict[str, dict[str, str]], lang: str) -> None:
    """Die Geräteseite sortiert nach dem Namen: Die Nummer im Namen hält je Tag Schalter und Zeiten zusammen."""
    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    expected = []
    for day in days:
        expected += [
            texts[lang][f"entity.switch.profile_weekday_{day}.name"],
            texts[lang][f"entity.text.profile_times_{day}.name"],
        ]
    assert [name.split(" ")[0] for name in expected] == [str(n) for n in range(1, 8) for _ in range(2)]
    others = [
        text
        for key, text in texts[lang].items()
        if key.startswith("entity.")
        and key.endswith(".name")
        and "profile_weekday_" not in key
        and "profile_times_" not in key
    ]
    assert not any(text[:1].isdigit() for text in others)  # nur die Wochentage beginnen mit einer Ziffer
    block = sorted([*others, *expected], key=str.casefold)
    assert block[:14] == expected  # ein Block am Anfang: je Tag der Schalter, dann die Zeiten
