"""Schalter „Von Hand aufnehmen“ für Profile ohne Auslöser und Zeitfenster."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import FakeRecorder, add_cameras, make_profile, setup_entry

pytestmark = pytest.mark.usefixtures("stream")


def _switch_id(hass: HomeAssistant, entry_id: str, profile_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("switch", "cam_profile", f"{entry_id}_{profile_id}_manual")


async def test_switch_only_for_profiles_without_trigger_and_window(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b", "c", "d")
    entry = await setup_entry(
        hass,
        [
            make_profile("Hand", ["camera.a"]),
            make_profile("Ausloeser", ["camera.b"], triggers=["binary_sensor.x"]),
            make_profile("Nacht", ["camera.c"], sun="night"),
            make_profile("Fenster", ["camera.d"], times={"mon": ["22:00-06:00"]}),
        ],
    )
    assert _switch_id(hass, entry.entry_id, "p_Hand") is not None
    for name in ("Ausloeser", "Nacht", "Fenster"):
        assert _switch_id(hass, entry.entry_id, f"p_{name}") is None


async def test_switch_starts_and_stops_the_profile(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Hand", ["camera.a"])])
    switch = _switch_id(hass, entry.entry_id, "p_Hand")
    assert hass.states.get(switch).state == "off"

    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert hass.states.get(switch).state == "on"
    assert entry.runtime_data.profile_running("p_Hand")
    kind, path, cams, _session, profile = FakeRecorder.calls[-1]
    assert (kind, profile, path) == ("start", "p_Hand", ["Ueberwachung", "Hand"])
    assert [c["id"] for c in cams] == ["camera.a"]

    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    assert hass.states.get(switch).state == "off"
    assert FakeRecorder.calls[-1] == ("stop", "p_Hand")


async def test_switch_follows_service_and_recorder(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Hand", ["camera.a"])])
    switch = _switch_id(hass, entry.entry_id, "p_Hand")

    await hass.services.async_call("cam_profile", "start_profile", {"profile": "Hand"}, blocking=True)
    assert hass.states.get(switch).state == "on"

    entry.runtime_data._sync_profiles({"profile": {"p_Hand": {"aufnahme": False, "stop_grund": "speicher_voll"}}})
    entry.runtime_data.notify()
    await hass.async_block_till_done()
    assert hass.states.get(switch).state == "off"  # der Recorder hat das Profil beendet


async def test_switch_reports_when_no_camera_is_free(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass, [make_profile("Hand", ["camera.gone"])])
    switch = _switch_id(hass, entry.entry_id, "p_Hand")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert err.value.translation_key == "no_cam_available"
    assert hass.states.get(switch).state == "off"


async def test_switch_disappears_when_a_trigger_is_added(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Hand", ["camera.a"])])
    assert _switch_id(hass, entry.entry_id, "p_Hand") is not None

    sub = entry.subentries["p_Hand"]
    hass.config_entries.async_update_subentry(entry, sub, data={**sub.data, "triggers": ["binary_sensor.x"]})
    await hass.async_block_till_done()

    assert _switch_id(hass, entry.entry_id, "p_Hand") is None
