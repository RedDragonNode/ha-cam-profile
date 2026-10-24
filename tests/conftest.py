"""Gemeinsame Fixtures: Home-Assistant-Test-Plugin, ein Fake-Recorder und Hilfen zum Einrichten."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, ClassVar
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cam_profile.const import DOMAIN, MINOR_VERSION
from custom_components.cam_profile.recorder_client import RecorderAuthError, RecorderError

URL = "http://addon:8099"
KEY = "geheimgeheim123"
STREAM = "rtsp://user:pass@192.168.1.12/stream"


class FakeRecorder:
    """Ersatz für RecorderClient: merkt sich die Aufrufe und liefert einstellbare Antworten."""

    calls: ClassVar[list[tuple]] = []
    remote_profiles: ClassVar[dict[str, Any]] = {}
    fail: Exception | None = None

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def _check(self) -> None:
        if FakeRecorder.fail:
            raise FakeRecorder.fail

    async def status(self) -> dict[str, Any]:
        self._check()
        return {
            "aufnahme": bool(FakeRecorder.remote_profiles),
            "wurzel": "/media/Aufnahmen",
            "speicher": {"frei_gb": 2500.0, "gesamt_gb": 3000.0},
            "version": "0.1.0",
            "kameras": {},
            "profile": FakeRecorder.remote_profiles,
        }

    async def list_dirs(self, path: list[str]) -> list[str]:
        self._check()
        return {"": ["Der_Fuchsbau", "Ueberwachung"], "Ueberwachung": ["Treppe"]}.get("/".join(path), [])

    async def start(self, path: list[str], cams: list[dict], session: str, profile: str | None = None) -> dict:
        self._check()
        FakeRecorder.calls.append(("start", path, cams, session, profile))
        return {}

    async def stop(self, profile: str | None = None) -> dict:
        self._check()
        FakeRecorder.calls.append(("stop", profile))
        return {}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Lässt Home Assistant die Integration aus `custom_components` laden."""


@pytest.fixture(autouse=True)
def fake_recorder() -> Generator[type[FakeRecorder]]:
    FakeRecorder.calls, FakeRecorder.remote_profiles, FakeRecorder.fail = [], {}, None
    with (
        patch("custom_components.cam_profile.manager.RecorderClient", FakeRecorder),
        patch("custom_components.cam_profile.config_flow.RecorderClient", FakeRecorder),
    ):
        yield FakeRecorder


@pytest.fixture
def stream() -> Generator[AsyncMock]:
    """Jede Kamera liefert eine Stream-Adresse."""
    with patch("custom_components.cam_profile.manager.async_get_stream_source", AsyncMock(return_value=STREAM)) as mock:
        yield mock


@pytest.fixture
def unreachable() -> type[FakeRecorder]:
    FakeRecorder.fail = RecorderError("Recorder-Add-on nicht erreichbar (test)")
    return FakeRecorder


@pytest.fixture
def bad_key() -> type[FakeRecorder]:
    FakeRecorder.fail = RecorderAuthError("Recorder: Schlüssel stimmt nicht")
    return FakeRecorder


def make_profile(name: str, cams: list[str], **overrides: Any) -> dict[str, Any]:
    """Subentry-Daten eines Profils mit Standardwerten."""
    return {
        "name": name,
        "folder": f"Ueberwachung/{name}",
        "cams": cams,
        "pattern": "{cam} %CCYY",
        "triggers": [],
        "after_seconds": 0,
        "max_minutes": 0,
        "time_from": "",
        "time_to": "",
        "sun": "",
        **overrides,
    }


def bare_profile(name: str, cams: list[str], **fields: Any) -> dict[str, Any]:
    """Subentry-Daten, wie sie ab Version 0.3 gespeichert werden: nur Pflichtfelder und was das Profil selbst setzt."""
    return {"name": name, "cams": cams, "triggers": [], **fields}


def add_cameras(hass: HomeAssistant, *names: str) -> None:
    """Legt Kamera-Zustände an (camera.<name>) ohne echte Quell-Integration."""
    for name in names:
        hass.states.async_set(f"camera.{name}", "idle", {"friendly_name": name.title()})


async def setup_entry(
    hass: HomeAssistant, profiles: list[dict[str, Any]] | None = None, options: dict[str, Any] | None = None
) -> MockConfigEntry:
    """Richtet Cam Profile mit den angegebenen Profilen und Grundeinstellungen ein (Subentry-ID = 'p_<Name>')."""
    subentries = [
        ConfigSubentryData(
            subentry_type="profile",
            title=profile["name"],
            unique_id=profile["name"].lower(),
            subentry_id=f"p_{profile['name']}",
            data=profile,
        )
        for profile in profiles or []
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Cam Profile",
        data={"recorder_url": URL, "recorder_key": KEY},
        options=options or {},
        subentries_data=subentries,
        minor_version=MINOR_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
