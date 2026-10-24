"""Reine Logik: Namen, Dateimuster, Zeitfenster."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.cam_profile import logic


def test_norm_resolves_umlauts_and_symbols() -> None:
    assert logic.norm("Fuchs-Revier Ü!") == "fuchsrevierue"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Fuchsrevier", "FUC"), ("Fuchs Revier", "FR"), ("Ab", "AB"), ("!!!", "CAM"), ("Über Garten Tor Links", "UGTL")],
)
def test_short_code(name: str, expected: str) -> None:
    assert logic.short_code(name) == expected


def test_split_path_drops_empty_and_parent_parts() -> None:
    assert logic.split_path("Der_Fuchsbau/bei Nacht") == ["Der_Fuchsbau", "bei Nacht"]
    assert logic.split_path("../a//b\\c/.") == ["a", "b", "c"]
    assert logic.split_path("") == []


def test_render_pattern_supports_both_languages_and_date_tokens() -> None:
    when = datetime(2026, 10, 24, 7, 5, 9)
    text = logic.render_pattern(
        "{cam} {short} {kuerzel} {profile} {profil} %CCYY-%MM-%DD %hh-%mm-%ss",
        when,
        cam="Flur",
        short="FLU",
        profile="Treppe",
    )
    assert text == "Flur FLU FLU Treppe Treppe 2026-10-24 07-05-09"


def test_unique_names_only_touches_duplicates() -> None:
    assert logic.unique_names(["A", "B", "A"], ["x", "y", "z"]) == ["A x", "B", "A z"]


@pytest.mark.parametrize(
    ("hour", "start", "end", "expected"),
    [
        (12, "08:00:00", "18:00:00", True),
        (19, "08:00:00", "18:00:00", False),
        (23, "22:00:00", "06:00:00", True),  # über Mitternacht
        (3, "22:00:00", "06:00:00", True),
        (12, "22:00:00", "06:00:00", False),
        (12, "08:00", "18:00", True),  # ohne Sekunden
        (12, "", "", True),
        (12, "10:00:00", "10:00:00", True),  # gleiche Zeit = ganztägig
    ],
)
def test_in_time_window(hour: int, start: str, end: str, expected: bool) -> None:
    assert logic.in_time_window(datetime(2026, 1, 1, hour, 0, 0), start, end) is expected


def test_equal_start_and_end_is_not_a_window() -> None:
    assert logic.has_time_window("22:00:00", "06:00:00")
    assert logic.has_time_window("08:00", "18:00")
    assert not logic.has_time_window("00:00:00", "00:00:00")
    assert not logic.has_time_window("08:00", "08:00:00")
    assert not logic.has_time_window("", "")
    assert not logic.has_time_window(None, "06:00:00")


@pytest.mark.parametrize(
    ("when", "start", "end", "expected"),
    [
        (datetime(2026, 10, 23, 23, 0), "22:00:00", "06:00:00", 4),  # Freitag 23:00: Freitag
        (datetime(2026, 10, 24, 3, 0), "22:00:00", "06:00:00", 4),  # Samstag 03:00: gehört noch zum Freitag
        (datetime(2026, 10, 24, 7, 0), "22:00:00", "06:00:00", 5),  # Samstag 07:00 liegt außerhalb, zählt als Samstag
        (datetime(2026, 10, 24, 3, 0), "08:00:00", "18:00:00", 5),  # Fenster ohne Mitternacht: der Tag selbst
        (datetime(2026, 10, 24, 3, 0), None, None, 5),
        (datetime(2026, 10, 26, 0, 30), "22:00:00", "06:00:00", 6),  # Montag 00:30: Sonntag
    ],
)
def test_effective_weekday(when: datetime, start: str | None, end: str | None, expected: int) -> None:
    assert logic.effective_weekday(when, start, end) == expected


def test_describe_overrides_in_both_languages() -> None:
    fields = ["time_from", "time_to", "weekdays", "after_seconds"]
    assert logic.describe_overrides(fields, "de") == "Zeitfenster, Wochentage, Nachlauf"
    assert logic.describe_overrides(fields, "en-GB") == "time window, weekdays, run-on"
    assert logic.describe_overrides([], "de") == "–"
