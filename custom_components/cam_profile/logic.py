"""Reine Logik ohne Home-Assistant-Abhängigkeit (leicht testbar)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

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


def resolve(
    profile: Mapping[str, Any], defaults: Mapping[str, Any], keys: Iterable[str]
) -> tuple[dict[str, Any], list[str]]:
    """Wert je Feld: der des Profils, sonst die Grundeinstellung.

    Auch 0 und "" zählen als Wert, nur ein fehlendes Feld erbt.
    """
    values: dict[str, Any] = {}
    inherited: list[str] = []
    for key in keys:
        if key in profile:
            values[key] = profile[key]
        elif key in defaults:
            values[key] = defaults[key]
            inherited.append(key)
    return values, inherited


_WEEKDAY_NAMES = {
    "de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
_SUN_NAMES = {"de": {"": "egal", "day": "Tag", "night": "Nacht"}, "en": {"": "any", "day": "day", "night": "night"}}


def describe_defaults(defaults: Mapping[str, Any], language: str) -> dict[str, str]:
    """Texte für die Formulare: die aktuell geltenden Grundeinstellungen („–“ = nicht gesetzt)."""
    lang = "de" if language.lower().startswith("de") else "en"
    unset = "–"
    days = [d for d in WEEKDAYS if d in (defaults.get("weekdays") or [])]
    start, end = defaults.get("time_from"), defaults.get("time_to")
    return {
        "default_folder": str(defaults.get("folder") or unset),
        "default_pattern": str(defaults.get("pattern") or unset),
        "default_after": f"{defaults['after_seconds']} s" if "after_seconds" in defaults else unset,
        "default_max": f"{defaults['max_minutes']} min" if "max_minutes" in defaults else unset,
        "default_window": f"{start[:5]}–{end[:5]}" if start and end else unset,
        "default_weekdays": ", ".join(_WEEKDAY_NAMES[lang][WEEKDAYS.index(d)] for d in days) or unset,
        "default_sun": _SUN_NAMES[lang].get(defaults["sun"], unset) if "sun" in defaults else unset,
    }
