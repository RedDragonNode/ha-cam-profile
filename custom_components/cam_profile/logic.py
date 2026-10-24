"""Reine Logik ohne Home-Assistant-Abhängigkeit (leicht testbar)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta

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


def in_time_window(now: datetime, start: str | None, end: str | None) -> bool:
    """Liegt now im Fenster start..end ('HH:MM[:SS]')? Fenster über Mitternacht sind erlaubt."""
    if not has_time_window(start, end):
        return True
    cur = now.strftime("%H:%M:%S")
    s, e = _hms(start or ""), _hms(end or "")
    return s <= cur < e if s < e else (cur >= s or cur < e)


def effective_weekday(now: datetime, start: str | None, end: str | None) -> int:
    """Wochentag (Montag = 0), der für die Aufnahme zählt.

    Bei einem Fenster über Mitternacht zählt der Tag, an dem es begann: Freitag 22:00 bis 06:00 gehört
    um 03:00 Uhr nachts noch zum Freitag.
    """
    if (
        has_time_window(start, end)
        and _hms(start or "") > _hms(end or "")
        and now.strftime("%H:%M:%S") < _hms(end or "")
    ):
        return (now - timedelta(days=1)).weekday()
    return now.weekday()


_FIELD_NAMES = {
    "de": {
        "after_seconds": "Nachlauf",
        "max_minutes": "Höchstdauer",
        "time_from": "Zeitfenster",
        "time_to": "Zeitfenster",
        "weekdays": "Wochentage",
        "sun": "Sonne",
    },
    "en": {
        "after_seconds": "run-on",
        "max_minutes": "maximum length",
        "time_from": "time window",
        "time_to": "time window",
        "weekdays": "weekdays",
        "sun": "sun",
    },
}


def describe_overrides(fields: Iterable[str], language: str) -> str:
    """Namen der Einstellungen, die auf der Geräteseite überschrieben sind („–“ = keine)."""
    names = _FIELD_NAMES["de" if language.lower().startswith("de") else "en"]
    return ", ".join(dict.fromkeys(names[f] for f in fields if f in names)) or "–"
