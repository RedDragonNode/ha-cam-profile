"""Diagnose-Download (ohne Schlüssel und ohne Stream-Adressen)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import CamProfileConfigEntry
from .const import CONF_RECORDER_KEY

TO_REDACT = {CONF_RECORDER_KEY}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: CamProfileConfigEntry) -> dict[str, Any]:
    m = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "recorder": {
            "online": m.rec_online,
            "version": m.rec_status.get("version"),
            "storage": m.rec_status.get("speicher"),
            "running_profiles": sorted(m.rec_status.get("profile") or {}),
        },
        "status": m.status,
        "message": m.message,
        "profiles": [asdict(p) for p in m.profiles.values()],  # geltende Werte (mit Überschreibungen)
        "creation_values": [asdict(p) for p in m.base.values()],  # Anlege-Werte, wie im Profil gespeichert
        "overrides": m.overrides,
        "running": {pid: {k: v for k, v in st.items() if k != "off_since"} for pid, st in m.profile_state.items()},
    }
