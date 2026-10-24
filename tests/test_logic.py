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


def test_parse_times_reads_several_windows_and_normalises() -> None:
    assert logic.parse_times("08:00-12:00, 18:00 - 22:00") == ["08:00-12:00", "18:00-22:00"]
    assert logic.parse_times("8:00 bis 12:30; 22:00–06:00") == ["08:00-12:30", "22:00-06:00"]
    assert logic.parse_times("00:00-24:00") == ["00:00-24:00"]
    assert logic.parse_times("08:00:30-09:15:00") == ["08:00:30-09:15"]
    assert logic.parse_times("") == []
    assert logic.parse_times(None) == []
    assert logic.parse_times(" , ; ") == []


@pytest.mark.parametrize("text", ["bis morgen", "08:00", "08:00-", "12:61-13:00", "25:00-26:00", "24:00-02:00", "8-9"])
def test_parse_times_refuses_nonsense(text: str) -> None:
    with pytest.raises(ValueError, match=r"\S"):
        logic.parse_times(text)


FRIDAY, SATURDAY, MONDAY = datetime(2026, 10, 23), datetime(2026, 10, 24), datetime(2026, 10, 26)
ALL = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@pytest.mark.parametrize(
    ("when", "days", "times", "expected"),
    [
        # ohne Zeiten: aktive Tage sind ganztägig an
        (FRIDAY.replace(hour=3), ALL, {}, True),
        (FRIDAY.replace(hour=3), ("mon",), {}, False),
        (FRIDAY.replace(hour=3), (), {}, False),  # kein Tag aktiv
        # eigene Zeiten des Tages
        (FRIDAY.replace(hour=9), ALL, {"fri": ["08:00-12:00", "18:00-22:00"]}, True),
        (FRIDAY.replace(hour=13), ALL, {"fri": ["08:00-12:00", "18:00-22:00"]}, False),
        (FRIDAY.replace(hour=19), ALL, {"fri": ["08:00-12:00", "18:00-22:00"]}, True),
        (FRIDAY.replace(hour=12), ALL, {"fri": ["08:00-12:00"]}, False),  # Ende zählt nicht mehr dazu
        # Zeiten eines anderen Tages gelten nicht, dieser Tag ist dann ganztägig
        (FRIDAY.replace(hour=13), ALL, {"mon": ["08:00-12:00"]}, True),
        # Fenster über Mitternacht gehört zum Starttag
        (FRIDAY.replace(hour=23), ("fri",), {"fri": ["22:00-06:00"]}, True),
        (SATURDAY.replace(hour=3), ("fri",), {"fri": ["22:00-06:00"]}, True),  # noch der Freitag
        (SATURDAY.replace(hour=7), ("fri",), {"fri": ["22:00-06:00"]}, False),
        (SATURDAY.replace(hour=3), ("sat",), {"fri": ["22:00-06:00"], "sat": ["10:00-11:00"]}, False),
        (MONDAY.replace(hour=0, minute=30), ("sun",), {"sun": ["22:00-06:00"]}, True),
        (
            SATURDAY.replace(hour=23),
            ("fri",),
            {"fri": ["22:00-06:00"]},
            False,
        ),  # Samstagabend ist nicht dran
        # 24:00 als Ende, gleiche Zeit heißt ganztägig
        (FRIDAY.replace(hour=23, minute=59), ALL, {"fri": ["18:00-24:00"]}, True),
        (FRIDAY.replace(hour=5), ALL, {"fri": ["10:00-10:00"]}, True),
    ],
)
def test_times_open(when: datetime, days: tuple, times: dict, expected: bool) -> None:
    assert logic.times_open(when, days, times) is expected


def test_describe_overrides_in_both_languages() -> None:
    fields = ["times", "weekdays", "after_seconds", "sun"]
    assert logic.describe_overrides(fields, "de") == "Zeiten, Wochentage, Nachlauf, Sonne"
    assert logic.describe_overrides(fields, "en-GB") == "times, weekdays, run-on, sun"
    assert logic.describe_overrides([], "de") == "–"
