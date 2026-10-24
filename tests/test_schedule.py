"""Zeitplan (Helfer „Zeitplan“): mehrere Zeiten je Wochentag, das Profil nimmt auf, solange er „an“ ist."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.cam_profile.const import DOMAIN, WEEKDAYS

from .conftest import add_cameras, make_profile, profile_entity, setup_entry

pytestmark = pytest.mark.usefixtures("stream")

PLAN = "schedule.nachts"


def _other_day() -> str:
    return WEEKDAYS[(dt_util.now().weekday() + 3) % 7]


async def test_profile_without_trigger_records_while_the_schedule_is_on(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set(PLAN, "off")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], schedule=PLAN)])
    manager = entry.runtime_data
    assert not manager.profiles["p_A"].manual_only  # der Zeitplan lässt es von allein laufen
    assert not manager.profile_running("p_A")

    hass.states.async_set(PLAN, "on")
    await hass.async_block_till_done()
    assert manager.profile_running("p_A")  # sofort bei der Zustandsänderung, ohne auf den nächsten Takt zu warten

    hass.states.async_set(PLAN, "off")
    await hass.async_block_till_done()
    assert not manager.profile_running("p_A")


async def test_trigger_and_schedule_must_both_fit(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set(PLAN, "off")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"], schedule=PLAN)])
    assert not entry.runtime_data.profile_running("p_A")  # Auslöser an, aber der Zeitplan ist aus

    hass.states.async_set(PLAN, "on")
    await hass.async_block_till_done()
    assert entry.runtime_data.profile_running("p_A")


async def test_schedule_and_weekdays_combine(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set(PLAN, "on")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], schedule=PLAN, weekdays=[_other_day()])])
    assert not entry.runtime_data.profile_running("p_A")  # der Zeitplan ist an, aber heute ist nicht der Tag


async def test_missing_schedule_means_no_recording_and_no_manual_switch(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], schedule="schedule.gibt_es_nicht")])
    assert not entry.runtime_data.profile_running("p_A")
    assert er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_p_A_manual") is None


async def test_sensor_names_the_schedule(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    hass.states.async_set(PLAN, "off")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], schedule=PLAN), make_profile("B", ["camera.b"])])
    assert (
        hass.states.get(profile_entity(hass, entry, "p_A", "binary_sensor", "recording")).attributes["schedule"] == PLAN
    )
    assert (
        hass.states.get(profile_entity(hass, entry, "p_B", "binary_sensor", "recording")).attributes["schedule"] is None
    )
