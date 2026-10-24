"""Zeiten je Wochentag: Aufnahme nur in diesen Zeiten, Textfeld auf der Geräteseite, Migration des Zeitplan-Felds."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cam_profile.const import DOMAIN, MINOR_VERSION, WEEKDAYS

from .conftest import KEY, URL, add_cameras, make_profile, profile_entity, setup_entry

pytestmark = pytest.mark.usefixtures("stream")


@pytest.fixture(autouse=True)
def saturday_morning(freezer) -> None:
    """Samstag, 24. Oktober 2026, 09:00 Uhr Ortszeit der Test-Instanz."""
    freezer.move_to("2026-10-24 16:00:00+00:00")


async def _set(hass: HomeAssistant, entity_id: str, value: str) -> None:
    await hass.services.async_call("text", "set_value", {"entity_id": entity_id, "value": value}, blocking=True)
    await hass.async_block_till_done()


async def test_the_test_clock_is_saturday_nine(hass: HomeAssistant) -> None:
    now = dt_util.now()
    assert (WEEKDAYS[now.weekday()], now.hour) == ("sat", 9)


async def test_profile_without_trigger_records_in_the_times_of_its_day(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b", "c")
    entry = await setup_entry(
        hass,
        [
            make_profile("Drin", ["camera.a"], times={"sat": ["08:00-10:00", "18:00-22:00"]}),
            make_profile("Draussen", ["camera.b"], times={"sat": ["10:00-11:00"]}),
            make_profile("Ganztags", ["camera.c"], weekdays=["sat"]),
        ],
    )
    manager = entry.runtime_data
    assert manager.profile_running("p_Drin")
    assert not manager.profile_running("p_Draussen")
    assert manager.profile_running("p_Ganztags")  # ein Tag ohne Zeiten nimmt ganztägig auf
    assert not manager.profiles["p_Draussen"].manual_only  # Zeiten lassen es von allein laufen


async def test_other_days_times_do_not_matter_for_a_day_without_times(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], times={"mon": ["03:00-04:00"]})])
    assert entry.runtime_data.profile_running("p_A")  # Samstag hat keine Zeiten, also ganztägig


async def test_day_times_replace_the_default_window_and_trigger_must_fit(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(
        hass,
        [
            make_profile(
                "Eigen",
                ["camera.a"],
                triggers=["binary_sensor.x"],
                time_from="12:00:00",
                time_to="13:00:00",
                times={"sat": ["08:00-10:00"]},
            ),
            make_profile(
                "Standard", ["camera.b"], triggers=["binary_sensor.x"], time_from="12:00:00", time_to="13:00:00"
            ),
        ],
    )
    assert entry.runtime_data.profile_running("p_Eigen")  # die eigenen Zeiten ersetzen Von/Bis
    assert not entry.runtime_data.profile_running("p_Standard")  # Von/Bis gilt, und 09:00 liegt außerhalb


async def test_text_entity_shows_overrides_and_keeps_the_creation_value(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(
        hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"], times={"sat": ["08:00-10:00"]})]
    )
    manager = entry.runtime_data
    sat = profile_entity(hass, entry, "p_A", "text", "times_sat")
    mon = profile_entity(hass, entry, "p_A", "text", "times_mon")
    assert hass.states.get(sat).state == "08:00-10:00"
    assert hass.states.get(mon).state == ""
    assert manager.profile_running("p_A")

    await _set(hass, sat, "10:00 - 11:30; 18:00-22:00")
    state = hass.states.get(sat)
    assert state.state == "10:00-11:30, 18:00-22:00"
    assert (state.attributes["overridden"], state.attributes["creation_value"]) == (True, "08:00-10:00")
    assert hass.states.get(mon).attributes["overridden"] is False  # nur der geänderte Tag gilt als überschrieben
    assert entry.subentries["p_A"].data["times"] == {"sat": ["08:00-10:00"]}  # der Anlege-Wert bleibt
    assert not manager.profile_running("p_A")  # 09:00 liegt jetzt außerhalb, sofort beendet

    await _set(hass, sat, "")  # leer heißt ganztägig
    assert hass.states.get(sat).state == ""
    assert manager.profile_running("p_A")

    await hass.services.async_call(
        "button", "press", {"entity_id": profile_entity(hass, entry, "p_A", "button", "reset")}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(sat).state == "08:00-10:00"
    assert hass.states.get(sat).attributes["overridden"] is False


async def test_invalid_times_are_refused(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"])])
    entity = profile_entity(hass, entry, "p_A", "text", "times_sat")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("text", "set_value", {"entity_id": entity, "value": "morgens"}, blocking=True)
    assert err.value.translation_key == "invalid_times"
    assert err.value.translation_placeholders == {"value": "morgens"}
    assert entry.runtime_data.profiles["p_A"].overridden == []


async def test_times_on_the_device_page_make_a_hand_profile_run_by_itself(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Hand", ["camera.a"])])
    assert entry.runtime_data.profiles["p_Hand"].manual_only
    assert not entry.runtime_data.profile_running("p_Hand")

    await _set(hass, profile_entity(hass, entry, "p_Hand", "text", "times_sat"), "08:00-10:00")
    assert not entry.runtime_data.profiles["p_Hand"].manual_only  # Zeiten lassen es von allein laufen (Neuladen)
    assert entry.runtime_data.profile_running("p_Hand")


async def test_sensor_names_the_times(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], times={"sat": ["08:00-10:00"]})])
    state = hass.states.get(profile_entity(hass, entry, "p_A", "binary_sensor", "recording"))
    assert state.attributes["times"] == {"sat": ["08:00-10:00"]}


# ------------------------------------------------------------------ Migration
def _legacy(profiles: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={"recorder_url": URL, "recorder_key": KEY},
        minor_version=4,
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


async def test_migration_drops_the_schedule_field_and_turns_days_back_on(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b", "c")
    with_plan_off = make_profile("MitPlan", ["camera.a"], weekdays=[], schedule="schedule.nachts")
    with_plan_days = make_profile("Tage", ["camera.b"], weekdays=["mon"], schedule="schedule.nachts")
    paused = make_profile("Pause", ["camera.c"], weekdays=[])  # ohne Zeitplan heißt keine Tage ausdrücklich: Pause
    entry = _legacy([with_plan_off, with_plan_days, paused])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == MINOR_VERSION
    data = {sid: dict(sub.data) for sid, sub in entry.subentries.items()}
    assert "schedule" not in data["p_MitPlan"]
    assert data["p_MitPlan"]["weekdays"] == list(
        WEEKDAYS
    )  # der Zeitplan ersetzte sie, die Tage waren nur ausgeschaltet
    assert "schedule" not in data["p_Tage"]
    assert data["p_Tage"]["weekdays"] == ["mon"]
    assert data["p_Pause"]["weekdays"] == []
