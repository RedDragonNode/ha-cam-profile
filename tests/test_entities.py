"""Entities, Geräte, Aufräumen und Diagnose."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import KEY, add_cameras, make_profile, setup_entry


def _unique_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    return {e.unique_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}


async def test_entities_for_hub_profiles_and_cameras(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b", "unused")
    entry = await setup_entry(
        hass, [make_profile("Eins", ["camera.a"]), make_profile("Zwei", ["camera.a", "camera.b"])]
    )
    eid = entry.entry_id
    assert _unique_ids(hass, entry) == {
        f"{eid}_recorder_online",
        f"{eid}_status",
        f"{eid}_recorder_free_space",
        f"{eid}_p_Eins_recording",
        f"{eid}_p_Zwei_recording",
        f"{eid}_p_Eins_manual",  # Profile ohne Auslöser und Zeitfenster bekommen einen Schalter
        f"{eid}_p_Zwei_manual",
        f"{eid}_cam_camera.a_recording",  # eine Kamera in zwei Profilen bekommt nur einen Sensor
        f"{eid}_cam_camera.b_recording",
    }
    assert hass.states.get("sensor.cam_profile_status").state == "idle"
    assert hass.states.get("sensor.cam_profile_recorder_free_space").state == "2500.0"
    assert hass.states.get("binary_sensor.cam_profile_recorder_reachable").state == "on"


async def test_profile_sensor_follows_recording(hass: HomeAssistant, stream) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a"], folder="Ueberwachung/Eins")])
    sensor = next(
        e
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id.endswith("p_Eins_recording")
    )
    assert hass.states.get(sensor.entity_id).state == "off"

    await hass.services.async_call("cam_profile", "start_profile", {"profile": "Eins"}, blocking=True)
    state = hass.states.get(sensor.entity_id)
    assert state.state == "on"
    assert state.attributes["folder"] == "Ueberwachung/Eins"
    assert state.attributes["manual"] is True
    assert state.attributes["cams"] == ["camera.a"]
    assert hass.states.get("sensor.cam_profile_status").state == "recording"
    assert hass.states.get("sensor.cam_profile_status").attributes["running_profiles"] == ["Eins"]


async def test_camera_sensor_hangs_on_source_device(hass: HomeAssistant) -> None:
    """Der Aufnahme-Sensor erscheint am Gerät der Kamera, nicht an einem eigenen Gerät."""
    source = MockConfigEntry(domain="other")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("other", "d1")}, name="Fuchsrevier"
    )
    er.async_get(hass).async_get_or_create(
        "camera", "other", "cam1", suggested_object_id="fuchsrevier", device_id=device.id
    )
    hass.states.async_set("camera.fuchsrevier", "idle")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.fuchsrevier"])])

    sensor = er.async_get(hass).async_get_entity_id(
        "binary_sensor", "cam_profile", f"{entry.entry_id}_cam_camera.fuchsrevier_recording"
    )
    assert er.async_get(hass).async_get(sensor).device_id == device.id
    assert hass.states.get(sensor).attributes["profiles"] == ["Eins"]


async def test_camera_without_device_gets_own_device(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a"])])
    sensor = er.async_get(hass).async_get_entity_id(
        "binary_sensor", "cam_profile", f"{entry.entry_id}_cam_camera.a_recording"
    )
    device = dr.async_get(hass).async_get(er.async_get(hass).async_get(sensor).device_id)
    assert device.name == "A"


async def test_profile_gets_translated_device_via_hub(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Treppe", ["camera.a"])])
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    names = {d.name for d in devices}
    assert "Profile Treppe" in names or "Profil Treppe" in names
    hub = next(d for d in devices if d.name == "Cam Profile")
    assert all(d.via_device_id == hub.id for d in devices if d.id != hub.id and d.name.endswith("Treppe"))


async def test_unused_camera_entities_are_removed_on_reload(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a", "camera.b"])])
    assert f"{entry.entry_id}_cam_camera.b_recording" in _unique_ids(hass, entry)

    sub = entry.subentries["p_Eins"]
    hass.config_entries.async_update_subentry(entry, sub, data={**sub.data, "cams": ["camera.a"]})
    await hass.async_block_till_done()

    ids = _unique_ids(hass, entry)
    assert f"{entry.entry_id}_cam_camera.a_recording" in ids
    assert f"{entry.entry_id}_cam_camera.b_recording" not in ids


async def test_status_sensor_reports_addon_outage(hass: HomeAssistant, unreachable) -> None:
    entry = await setup_entry(hass)
    await entry.runtime_data._poll_recorder(None)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.cam_profile_recorder_reachable").state == "off"
    assert hass.states.get("sensor.cam_profile_recorder_free_space").state == "unavailable"


async def test_diagnostics_hide_the_key(hass: HomeAssistant, hass_client: ClientSessionGenerator) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a"])])
    data = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert data["entry"]["recorder_key"] == REDACTED
    assert KEY not in str(data)
    assert data["profiles"][0]["name"] == "Eins"
    assert data["recorder"]["online"] is True


async def test_unload_and_reload(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a"])])
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.cam_profile_status").state == "idle"
