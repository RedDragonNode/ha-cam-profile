"""Reine Logik ohne Home-Assistant-Abhängigkeit (leicht testbar)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime

from .const import WEEKDAYS

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})

_TOKENS = (
    ("%CCYY", "%Y"),
    ("%YY", "%y"),
    ("%MM", "%m"),
    ("%DD", "%d"),
    ("%hh", "%H"),
    ("%mm", "%M"),
    ("%ss", "%S"),
)


def norm(text: str) -> str:
    """Name zum Vergleichen: klein, Umlaute aufgelöst, nur Buchstaben und Ziffern."""
    return re.sub(r"[^a-z0-9]", "", str(text).translate(_UMLAUTE).lower())


def short_code(name: str) -> str:
    """Kürzel für den Dateinamen: Anfangsbuchstaben bei mehreren Wörtern, sonst die ersten drei Zeichen.

    'Fuchs Revier' -> 'FR', 'Fuchsrevier' -> 'FUC'.
    """
    words = re.findall(r"[A-Za-z0-9ÄÖÜäöüß]+", name)
    if len(words) > 1:
        return "".join(norm(w)[:1] for w in words).upper()[:4] or "CAM"
    return norm(name).upper()[:3] or "CAM"


def render_tokens(text: str, when: datetime) -> str:
    """Datums-Platzhalter (%DD.%MM.%CCYY ...) in echte Werte umsetzen."""
    for token, fmt in _TOKENS:
        text = text.replace(token, when.strftime(fmt))
    return text


def split_path(text: str) -> list[str]:
    """'Der_Fuchsbau/bei Nacht' -> ['Der_Fuchsbau', 'bei Nacht'] (leere Teile und '..' fallen weg)."""
    return [p.strip() for p in re.split(r"[/\\]", text or "") if p.strip() and p.strip() not in (".", "..")]


def render_pattern(pattern: str, when: datetime, *, cam: str, short: str, profile: str) -> str:
    """Dateimuster eines Profils: {cam} {kuerzel} {profil} plus Datums-Platzhalter."""
    text = pattern.replace("{cam}", cam).replace("{kuerzel}", short).replace("{short}", short)
    text = text.replace("{profil}", profile).replace("{profile}", profile)
    return render_tokens(text, when)


def unique_names(names: list[str], fallbacks: list[str]) -> list[str]:
    """Macht doppelte Namen eindeutig (zwei Kameras desselben Geräts würden sonst dieselbe Datei beschreiben)."""
    result = list(names)
    for i, name in enumerate(names):
        if names.count(name) > 1:
            result[i] = f"{name} {fallbacks[i]}"
    return result


def _hms(value: str) -> str:
    return f"{value}:00" if len(value) == 5 else value


def has_time_window(start: str | None, end: str | None) -> bool:
    """Ist ein Zeitfenster gesetzt? Von = bis bedeutet ganztägig und zählt nicht als Fenster."""
    return bool(start and end and _hms(start) != _hms(end))


_END_OF_DAY = "24:00:00"
_RANGE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(?:-|–|—|bis)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", re.IGNORECASE
)


def _clock(hour: str, minute: str, second: str | None, *, end: bool) -> str:
    h, m, s = int(hour), int(minute), int(second or 0)
    if m > 59 or s > 59 or h > 24 or (h == 24 and (m or s or not end)):
        raise ValueError(f"{hour}:{minute}")
    return f"{h:02d}:{m:02d}:{s:02d}"


def _short(clock: str) -> str:
    return clock[:5] if clock.endswith(":00") else clock


def parse_times(text: str | None) -> list[str]:
    """'08:00-12:00, 18:00-22:00' -> ['08:00-12:00', '18:00-22:00'] (Komma oder Semikolon, auch über Mitternacht).

    Wirft ValueError mit dem unlesbaren Teil. 24:00 ist nur als Ende erlaubt.
    """
    windows: list[str] = []
    for part in re.split(r"[;,]", text or ""):
        if not part.strip():
            continue
        match = _RANGE.match(part)
        if match is None:
            raise ValueError(part.strip())
        h1, m1, s1, h2, m2, s2 = match.groups()
        start, end = _clock(h1, m1, s1, end=False), _clock(h2, m2, s2, end=True)
        windows.append(f"{_short(start)}-{_short(end)}")
    return windows


def format_times(windows: Iterable[str]) -> str:
    return ", ".join(windows)


def split_range(window: str) -> tuple[str, str]:
    """'08:00-12:00' -> ('08:00:00', '12:00:00')."""
    start, end = window.split("-", 1)
    return _hms(start), _hms(end)


def _hits(cur: str, start: str, end: str, today: bool) -> bool:
    if start == end:
        return today  # gleiche Zeit heißt ganztägig
    if start < end:
        return today and start <= cur < end
    return cur >= start if today else cur < end  # über Mitternacht: abends heute, morgens noch vom Vortag


def _day_windows(
    day: str, times: Mapping[str, list[str]], default_from: str | None, default_to: str | None
) -> list[tuple[str, str]]:
    if own := times.get(day):
        return [split_range(window) for window in own]
    if has_time_window(default_from, default_to):
        return [(_hms(default_from or ""), _hms(default_to or ""))]
    return [("00:00:00", _END_OF_DAY)]


def times_open(
    now: datetime,
    days: Iterable[str],
    times: Mapping[str, list[str]],
    default_from: str | None,
    default_to: str | None,
) -> bool:
    """Passt now zu den aktiven Tagen und ihren Zeiten?

    Ein Tag ohne eigene Zeiten nimmt in der Von/Bis-Zeit auf, ohne die ganztägig. Ein Fenster über Mitternacht gehört
    zu dem Tag, an dem es beginnt: Freitag 22:00 bis 06:00 gilt um 03:00 Uhr nachts noch für den Freitag.
    """
    active = set(days)
    cur = now.strftime("%H:%M:%S")
    for offset, today in ((0, True), (1, False)):
        day = WEEKDAYS[(now.weekday() - offset) % 7]
        if day in active and any(
            _hits(cur, start, end, today) for start, end in _day_windows(day, times, default_from, default_to)
        ):
            return True
    return False


_FIELD_NAMES = {
    "de": {
        "after_seconds": "Nachlauf",
        "max_minutes": "Höchstdauer",
        "time_from": "Zeitfenster",
        "time_to": "Zeitfenster",
        "weekdays": "Wochentage",
        "times": "Zeiten",
        "sun": "Sonne",
    },
    "en": {
        "after_seconds": "run-on",
        "max_minutes": "maximum length",
        "time_from": "time window",
        "time_to": "time window",
        "weekdays": "weekdays",
        "times": "times",
        "sun": "sun",
    },
}


def describe_overrides(fields: Iterable[str], language: str) -> str:
    """Namen der Einstellungen, die auf der Geräteseite überschrieben sind („–“ = keine)."""
    names = _FIELD_NAMES["de" if language.lower().startswith("de") else "en"]
    return ", ".join(dict.fromkeys(names[f] for f in fields if f in names)) or "–"
