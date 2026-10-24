"""Einstellungen auf der Geräteseite überschreiben die Anlege-Werte, ohne sie zu ändern."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cam_profile.const import DOMAIN, MINOR_VERSION, WEEKDAYS

from .conftest import KEY, URL, add_cameras, bare_profile, make_profile, profile_entity, setup_entry

pytestmark = pytest.mark.usefixtures("stream")


def _today() -> str:
    return WEEKDAYS[dt_util.now().weekday()]


def _other_day() -> str:
    return WEEKDAYS[(dt_util.now().weekday() + 3) % 7]


def _manual_switch(hass: HomeAssistant, entry: MockConfigEntry, sid: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_{sid}_manual")


async def _call(hass: HomeAssistant, domain: str, service: str, **data: object) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)
    await hass.async_block_till_done()  # ein geändertes Profil lädt die Integration womöglich neu


# ------------------------------------------------------------- Zahlen
async def test_number_overrides_but_keeps_the_creation_value(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], after_seconds=10)])
    after = profile_entity(hass, entry, "p_A", "number", "after_seconds")
    state = hass.states.get(after)
    assert state.state == "10"
    assert (state.attributes["overridden"], state.attributes["creation_value"]) == (False, 10)

    await _call(hass, "number", "set_value", entity_id=after, value=45)
    state = hass.states.get(after)
    assert state.state == "45"
    assert (state.attributes["overridden"], state.attributes["creation_value"]) == (True, 10)

    manager = entry.runtime_data
    assert manager.profiles["p_A"].after_s == 45
    assert manager.profiles["p_A"].overridden == ["after_seconds"]
    assert manager.base["p_A"].after_s == 10
    assert entry.subentries["p_A"].data["after_seconds"] == 10  # der Anlege-Wert im Profil bleibt unverändert


async def test_zero_is_an_override_too(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], max_minutes=15)])
    await _call(
        hass, "number", "set_value", entity_id=profile_entity(hass, entry, "p_A", "number", "max_minutes"), value=0
    )
    assert entry.runtime_data.profiles["p_A"].max_min == 0
    assert entry.runtime_data.profiles["p_A"].overridden == ["max_minutes"]


async def test_reset_button_restores_the_creation_values(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], after_seconds=10, max_minutes=5)])
    after = profile_entity(hass, entry, "p_A", "number", "after_seconds")
    await _call(hass, "number", "set_value", entity_id=after, value=45)
    await _call(
        hass, "number", "set_value", entity_id=profile_entity(hass, entry, "p_A", "number", "max_minutes"), value=60
    )
    assert entry.runtime_data.profiles["p_A"].overridden == ["after_seconds", "max_minutes"]

    await _call(hass, "button", "press", entity_id=profile_entity(hass, entry, "p_A", "button", "reset"))
    profile = entry.runtime_data.profiles["p_A"]
    assert (profile.after_s, profile.max_min, profile.overridden) == (10, 5, [])
    assert hass.states.get(after).state == "10"
    assert hass.states.get(after).attributes["overridden"] is False


async def test_overrides_survive_a_reload_and_a_changed_creation_value(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], after_seconds=10, max_minutes=5)])
    await _call(
        hass,
        "number",
        "set_value",
        entity_id=profile_entity(hass, entry, "p_A", "number", "after_seconds"),
        value=45,
    )

    sub = entry.subentries["p_A"]
    hass.config_entries.async_update_subentry(entry, sub, data={**sub.data, "after_seconds": 20, "max_minutes": 8})
    await hass.async_block_till_done()  # Update-Listener lädt neu

    profile = entry.runtime_data.profiles["p_A"]
    assert profile.after_s == 45  # die Überschreibung gilt weiter
    assert profile.max_min == 8  # was nicht überschrieben ist, folgt dem neuen Anlege-Wert
    assert entry.runtime_data.base["p_A"].after_s == 20


async def test_overrides_of_deleted_profiles_are_dropped(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"]), make_profile("B", ["camera.b"])])
    await _call(
        hass, "number", "set_value", entity_id=profile_entity(hass, entry, "p_A", "number", "after_seconds"), value=45
    )
    await _call(
        hass, "number", "set_value", entity_id=profile_entity(hass, entry, "p_B", "number", "after_seconds"), value=7
    )
    assert set(entry.runtime_data.overrides) == {"p_A", "p_B"}

    hass.config_entries.async_remove_subentry(entry, "p_A")
    await hass.async_block_till_done()
    assert set(entry.runtime_data.overrides) == {"p_B"}


async def test_removing_the_integration_removes_the_stored_overrides(hass: HomeAssistant, hass_storage: dict) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"])])
    await _call(
        hass, "number", "set_value", entity_id=profile_entity(hass, entry, "p_A", "number", "after_seconds"), value=45
    )
    key = f"{DOMAIN}.{entry.entry_id}"
    assert hass_storage[key]["data"]["overrides"] == {"p_A": {"after_seconds": 45}}

    await hass.config_entries.async_remove(entry.entry_id)
    assert key not in hass_storage


# ----------------------------------------------------- Zeitfenster und Sonne
async def test_time_override_sets_both_ends_and_equal_means_all_day(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(
        hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"], time_from="22:00:00", time_to="06:00:00")]
    )
    start = profile_entity(hass, entry, "p_A", "time", "time_from")
    end = profile_entity(hass, entry, "p_A", "time", "time_to")
    assert (hass.states.get(start).state, hass.states.get(end).state) == ("22:00:00", "06:00:00")

    await _call(hass, "time", "set_value", entity_id=end, time="23:30:00")
    profile = entry.runtime_data.profiles["p_A"]
    assert (profile.time_from, profile.time_to) == ("22:00:00", "23:30:00")
    assert profile.overridden == ["time_from", "time_to"]  # beide Enden zusammen
    assert hass.states.get(end).attributes["creation_value"] == "06:00:00"

    await _call(hass, "time", "set_value", entity_id=start, time="23:30:00")  # von = bis: ganztägig
    assert not entry.runtime_data.profiles["p_A"].has_time_window


async def test_time_entities_show_midnight_without_a_window(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"])])
    for key in ("time_from", "time_to"):
        assert hass.states.get(profile_entity(hass, entry, "p_A", "time", key)).state == "00:00:00"


async def test_sun_override(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"], sun="night")])
    sun = profile_entity(hass, entry, "p_A", "select", "sun")
    assert hass.states.get(sun).state == "night"

    await _call(hass, "select", "select_option", entity_id=sun, option="any")
    assert entry.runtime_data.profiles["p_A"].sun == ""
    assert hass.states.get(sun).state == "any"
    assert hass.states.get(sun).attributes["creation_value"] == "night"


# ------------------------------------------------------------------ Wochentage
async def test_weekday_switches_follow_the_profile(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass,
        [
            make_profile("Alle", ["camera.a"], triggers=["binary_sensor.x"]),
            make_profile("Werktags", ["camera.b"], triggers=["binary_sensor.x"], weekdays=["mon", "tue", "wed"]),
        ],
    )
    states = {
        sid: [hass.states.get(profile_entity(hass, entry, sid, "switch", f"weekday_{day}")).state for day in WEEKDAYS]
        for sid in ("p_Alle", "p_Werktags")
    }
    assert states["p_Alle"] == ["on"] * 7  # keine Auswahl heißt jeden Tag
    assert states["p_Werktags"] == ["on", "on", "on", "off", "off", "off", "off"]


async def test_weekday_switches_override_and_all_off_means_no_day(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"])])
    day = {name: profile_entity(hass, entry, "p_A", "switch", f"weekday_{name}") for name in WEEKDAYS}
    assert entry.runtime_data.profile_running("p_A")

    for name in ("sat", "sun"):
        await _call(hass, "switch", "turn_off", entity_id=day[name])
    profile = entry.runtime_data.profiles["p_A"]
    assert profile.weekdays == ["mon", "tue", "wed", "thu", "fri"]
    assert profile.overridden == ["weekdays"]
    assert hass.states.get(day["sat"]).state == "off"
    assert entry.subentries["p_A"].data["weekdays"] == list(WEEKDAYS)  # der Anlege-Wert bleibt

    for name in ("mon", "tue", "wed", "thu", "fri"):
        await _call(hass, "switch", "turn_off", entity_id=day[name])
    assert entry.runtime_data.profiles["p_A"].weekdays == []  # kein Fehler: alle aus ist erlaubt
    assert {hass.states.get(day[name]).state for name in WEEKDAYS} == {"off"}
    assert not entry.runtime_data.profile_running("p_A")  # der Auslöser ist an, aber kein Tag ist aktiv

    await _call(hass, "switch", "turn_on", entity_id=day["wed"])
    assert entry.runtime_data.profiles["p_A"].weekdays == ["wed"]

    for name in WEEKDAYS:
        await _call(hass, "switch", "turn_on", entity_id=day[name])
    assert not entry.runtime_data.profiles["p_A"].weekday_limited  # alle sieben: jeder Tag


async def test_no_active_weekday_leaves_a_profile_without_trigger_hand_only(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Hand", ["camera.a"], sun="night")])
    assert _manual_switch(hass, entry, "p_Hand") is None  # Sonne schränkt ein: läuft von allein

    await entry.runtime_data.async_override("p_Hand", {"weekdays": []})
    await hass.async_block_till_done()
    profile = entry.runtime_data.profiles["p_Hand"]
    assert profile.weekdays == []
    assert profile.manual_only  # an keinem Tag von allein, also nur von Hand
    assert _manual_switch(hass, entry, "p_Hand") is not None
    assert not entry.runtime_data.profile_running("p_Hand")

    await _call(hass, "button", "press", entity_id=profile_entity(hass, entry, "p_Hand", "button", "reset"))
    assert entry.runtime_data.profiles["p_Hand"].weekdays == list(WEEKDAYS)
    assert _manual_switch(hass, entry, "p_Hand") is None


async def test_weekday_override_stops_a_running_trigger_profile_at_once(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"])])
    assert entry.runtime_data.profile_running("p_A")

    await entry.runtime_data.async_override("p_A", {"weekdays": [_other_day()]})
    await hass.async_block_till_done()
    assert not entry.runtime_data.profile_running("p_A")

    await entry.runtime_data.async_override("p_A", {"weekdays": [_today()]})
    await hass.async_block_till_done()
    assert entry.runtime_data.profile_running("p_A")


# --------------------------------------------- Schalter „Von Hand aufnehmen“
async def test_override_with_a_restriction_removes_the_manual_switch_until_reset(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Hand", ["camera.a"])])
    assert _manual_switch(hass, entry, "p_Hand") is not None

    await _call(
        hass,
        "select",
        "select_option",
        entity_id=profile_entity(hass, entry, "p_Hand", "select", "sun"),
        option="night",
    )
    assert not entry.runtime_data.profiles["p_Hand"].manual_only
    assert _manual_switch(hass, entry, "p_Hand") is None  # läuft jetzt von allein, ein Schalter würde nur stören
    assert entry.runtime_data.profiles["p_Hand"].sun == "night"  # die Überschreibung überlebt das Neuladen

    await _call(hass, "button", "press", entity_id=profile_entity(hass, entry, "p_Hand", "button", "reset"))
    assert entry.runtime_data.profiles["p_Hand"].manual_only
    assert _manual_switch(hass, entry, "p_Hand") is not None


async def test_weekday_restriction_makes_a_profile_without_trigger_run_on_those_days(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass,
        [
            make_profile("Heute", ["camera.a"], weekdays=[_today()]),
            make_profile("Anders", ["camera.b"], weekdays=[_other_day()]),
        ],
    )
    manager = entry.runtime_data
    assert manager.profile_running("p_Heute")  # nur Wochentage heißt: an diesen Tagen durchgehend
    assert not manager.profile_running("p_Anders")


# --------------------------------------------------------- Fehlende Felder
async def test_built_in_values_apply_to_fields_a_profile_does_not_have(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [bare_profile("A", ["camera.a"], folder="X")])
    profile = entry.runtime_data.profiles["p_A"]
    assert (profile.after_s, profile.max_min, profile.weekdays, profile.sun) == (0, 0, list(WEEKDAYS), "")
    assert profile.pattern == "{cam} %CCYY-%MM-%DD %hh-%mm-%ss"
    assert profile.manual_only


# ------------------------------------------------------------------ Migration
def _legacy_entry(minor: int, options: dict, profiles: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={"recorder_url": URL, "recorder_key": KEY},
        options=options,
        minor_version=minor,
        subentries_data=[
            ConfigSubentryData(
                subentry_type="profile",
                title=p["name"],
                unique_id=p["name"].lower(),
                subentry_id=f"p_{p['name']}",
                data=p,
            )
            for p in profiles
        ],
    )


async def test_migration_bakes_the_old_global_defaults_into_the_profiles(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = _legacy_entry(
        2,
        {"folder": "Basis", "after_seconds": 30, "weekdays": ["sat", "sun"], "sun": "night"},
        [bare_profile("Erbt", ["camera.a"]), bare_profile("Eigen", ["camera.b"], folder="X", after_seconds=0)],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == MINOR_VERSION
    assert entry.options == {}
    assert dict(entry.subentries["p_Erbt"].data) == {
        "name": "Erbt",
        "cams": ["camera.a"],
        "triggers": [],
        "folder": "Basis",
        "after_seconds": 30,
        "weekdays": ["sat", "sun"],
        "sun": "night",
    }
    own = entry.runtime_data.profiles["p_Eigen"]
    assert (own.folder, own.after_s, own.sun) == (["X"], 0, "night")  # eigene Werte bleiben, der Rest kommt dazu


async def test_migration_without_global_defaults_only_makes_empty_weekdays_explicit(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    old = make_profile("Alt", ["camera.a"], max_minutes=15, weekdays=[])  # früher hieß leer: jeden Tag
    some = make_profile("Teil", ["camera.b"], weekdays=["mon"])
    entry = _legacy_entry(3, {}, [old, some])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == MINOR_VERSION
    assert dict(entry.subentries["p_Alt"].data) == {**old, "weekdays": list(WEEKDAYS)}
    assert dict(entry.subentries["p_Teil"].data) == some
    assert entry.runtime_data.profiles["p_Alt"].weekdays == list(WEEKDAYS)


async def test_empty_weekdays_in_a_current_profile_mean_no_day(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"], weekdays=[])])
    assert entry.runtime_data.profiles["p_A"].weekdays == []
    assert not entry.runtime_data.profile_running("p_A")
    for day in WEEKDAYS:
        assert hass.states.get(profile_entity(hass, entry, "p_A", "switch", f"weekday_{day}")).state == "off"
