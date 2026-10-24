"""Grundeinstellungen, Überschreiben im Profil, Wochentage und die Migration alter Profile."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cam_profile.const import DEFAULT_PATTERN, DOMAIN, MINOR_VERSION, WEEKDAYS

from .conftest import KEY, URL, FakeRecorder, add_cameras, bare_profile, make_profile, setup_entry

pytestmark = pytest.mark.usefixtures("stream")


def _today() -> str:
    return WEEKDAYS[dt_util.now().weekday()]


def _other_day() -> str:
    return WEEKDAYS[(dt_util.now().weekday() + 3) % 7]


# ------------------------------------------------------------ Zusammenführen
async def test_profile_inherits_defaults_and_overrides_fields(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass,
        [
            bare_profile("Erbt", ["camera.a"]),
            bare_profile("Eigen", ["camera.b"], after_seconds=0, folder="Eigener/Ordner", pattern="{cam}"),
        ],
        options={"folder": "Basis", "pattern": "{cam} X", "after_seconds": 30, "max_minutes": 10},
    )
    inherits, own = entry.runtime_data.profiles["p_Erbt"], entry.runtime_data.profiles["p_Eigen"]
    assert (inherits.folder, inherits.pattern, inherits.after_s, inherits.max_min) == (["Basis"], "{cam} X", 30, 10)
    assert set(inherits.inherited) == {"folder", "pattern", "after_seconds", "max_minutes"}
    # 0 ist ein echter eigener Wert und überschreibt die Grundeinstellung
    assert (own.folder, own.pattern, own.after_s, own.max_min) == (["Eigener", "Ordner"], "{cam}", 0, 10)
    assert own.inherited == ["max_minutes"]


async def test_built_in_values_apply_without_defaults(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [bare_profile("A", ["camera.a"], folder="X")])
    profile = entry.runtime_data.profiles["p_A"]
    assert (profile.pattern, profile.after_s, profile.max_min, profile.weekdays, profile.sun) == (
        DEFAULT_PATTERN,
        0,
        0,
        [],
        "",
    )
    assert profile.manual_only


async def test_changing_defaults_reloads_and_profiles_follow(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [bare_profile("A", ["camera.a"], folder="X")], options={"after_seconds": 30})
    assert entry.runtime_data.profiles["p_A"].after_s == 30

    hass.config_entries.async_update_entry(entry, options={"after_seconds": 99})
    await hass.async_block_till_done()
    assert entry.runtime_data.profiles["p_A"].after_s == 99


async def test_profile_start_uses_default_folder_and_pattern(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    await setup_entry(
        hass, [bare_profile("A", ["camera.a"])], options={"folder": "Basis/Unter", "pattern": "{profile}-{cam}"}
    )
    await hass.services.async_call("cam_profile", "start_profile", {"profile": "A"}, blocking=True)
    _kind, path, cams, _session, _profile = FakeRecorder.calls[-1]
    assert path == ["Basis", "Unter"]
    assert cams[0]["stem"] == "A-A"


# ----------------------------------------------------------------- Wochentage
async def test_weekdays_restrict_a_profile_without_trigger(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass,
        [
            bare_profile("Heute", ["camera.a"], folder="X", weekdays=[_today()]),
            bare_profile("Anders", ["camera.b"], folder="Y", weekdays=[_other_day()]),
        ],
    )
    m = entry.runtime_data
    assert m.profile_running("p_Heute")  # nur Wochentage heißt: an diesen Tagen durchgehend
    assert not m.profile_running("p_Anders")


async def test_weekdays_restrict_a_trigger(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(
        hass, [bare_profile("A", ["camera.a"], folder="X", triggers=["binary_sensor.x"], weekdays=[_other_day()])]
    )
    assert not entry.runtime_data.profile_running("p_A")  # Auslöser an, aber heute ist nicht der Tag


async def test_all_seven_weekdays_mean_every_day(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [bare_profile("A", ["camera.a"], folder="X", weekdays=list(WEEKDAYS))])
    profile = entry.runtime_data.profiles["p_A"]
    assert not profile.weekday_limited
    assert profile.manual_only  # sieben Tage schränken nichts ein


# ------------------------------------------- Grundeinstellung „wann“ und Schalter
async def test_default_window_makes_profiles_without_trigger_automatic(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass,
        [
            bare_profile("Erbt", ["camera.a"], folder="X"),
            bare_profile("Ganztags", ["camera.b"], folder="Y", time_from="00:00:00", time_to="00:00:00"),
        ],
        options={"weekdays": [_other_day()]},
    )
    ids = er.async_get(hass)
    assert not entry.runtime_data.profiles["p_Erbt"].manual_only  # erbt die Einschränkung, läuft von allein
    assert ids.async_get_entity_id("switch", "cam_profile", f"{entry.entry_id}_p_Erbt_manual") is None
    # alle sieben Wochentage heben die geerbte Einschränkung wieder auf, dann bleibt es ein Handprofil
    sub = entry.subentries["p_Ganztags"]
    hass.config_entries.async_update_subentry(entry, sub, data={**sub.data, "weekdays": list(WEEKDAYS)})
    await hass.async_block_till_done()
    assert entry.runtime_data.profiles["p_Ganztags"].manual_only
    assert ids.async_get_entity_id("switch", "cam_profile", f"{entry.entry_id}_p_Ganztags_manual") is not None


async def test_default_sun_is_overridden_by_any(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(
        hass,
        [bare_profile("A", ["camera.a"], folder="X", sun="")],  # „egal“ im Profil überschreibt die Grundeinstellung
        options={"sun": "night"},
    )
    assert entry.runtime_data.profiles["p_A"].manual_only


# ------------------------------------------------------------------ Migration
async def test_old_profiles_are_migrated_to_inherit(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    old = make_profile(
        "Alt",
        ["camera.a"],
        pattern=DEFAULT_PATTERN,
        after_seconds=0,
        max_minutes=15,
        folder="X",
        time_from="",
        time_to="",
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"recorder_url": URL, "recorder_key": KEY},
        minor_version=1,
        subentries_data=[
            ConfigSubentryData(subentry_type="profile", title="Alt", unique_id="alt", subentry_id="p_Alt", data=old)
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == MINOR_VERSION
    assert dict(entry.subentries["p_Alt"].data) == {
        "name": "Alt",
        "cams": ["camera.a"],
        "folder": "X",
        "triggers": [],
        "max_minutes": 15,  # ein echter eigener Wert bleibt
    }
