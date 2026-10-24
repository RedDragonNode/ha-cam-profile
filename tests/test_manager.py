"""Profile: Start und Stopp über Auslöser, Zeitfenster, Sonne, Dienste und belegte Kameras."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.cam_profile.const import DOMAIN, WEEKDAYS
from custom_components.cam_profile.recorder_client import RecorderAuthError, RecorderError

from .conftest import STREAM, FakeRecorder, add_cameras, make_profile, setup_entry

pytestmark = pytest.mark.usefixtures("stream")


async def test_motion_trigger_starts_and_stops_with_own_profile_id(hass: HomeAssistant) -> None:
    add_cameras(hass, "treppe")
    hass.states.async_set("binary_sensor.treppe", "off")
    await setup_entry(hass, [make_profile("Treppe", ["camera.treppe"], triggers=["binary_sensor.treppe"])])

    hass.states.async_set("binary_sensor.treppe", "on")
    await hass.async_block_till_done()

    kind, path, cams, session, profile = FakeRecorder.calls[-1]
    assert kind == "start"
    assert path == ["Ueberwachung", "Treppe"]
    assert profile == "p_Treppe"
    assert session.startswith("Treppe ")
    assert cams == [
        {"id": "camera.treppe", "name": "Treppe", "url": STREAM, "stem": f"Treppe {dt_util.now().year}"},
    ]

    hass.states.async_set("binary_sensor.treppe", "off")
    await hass.async_block_till_done()
    # nie ein Stopp ohne Profil: der würde alle Sitzungen des Add-ons beenden
    assert FakeRecorder.calls[-1] == ("stop", "p_Treppe")


async def test_run_on_delay_and_manual_services(hass: HomeAssistant) -> None:
    add_cameras(hass, "flur")
    hass.states.async_set("binary_sensor.flur", "off")
    entry = await setup_entry(
        hass, [make_profile("Flur", ["camera.flur"], triggers=["binary_sensor.flur"], after_seconds=3600)]
    )
    m = entry.runtime_data
    hass.states.async_set("binary_sensor.flur", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.flur", "off")
    await hass.async_block_till_done()
    assert m.profile_running("p_Flur")  # der Nachlauf läuft noch

    result = await hass.services.async_call(
        DOMAIN, "stop_profile", {"profile": "Flur"}, blocking=True, return_response=True
    )
    assert result == {"stopped": True}
    assert not m.profile_running("p_Flur")
    assert FakeRecorder.calls[-1] == ("stop", "p_Flur")

    await hass.services.async_call(DOMAIN, "start_profile", {"profile": "flur"}, blocking=True)  # Name ohne Groß/Klein
    assert m.profile_running("p_Flur")
    hass.states.async_set("binary_sensor.flur", "on")
    hass.states.async_set("binary_sensor.flur", "off")
    await hass.async_block_till_done()
    assert m.profile_running("p_Flur")  # von Hand gestartet: der Auslöser stoppt nicht

    again = await hass.services.async_call(
        DOMAIN, "start_profile", {"profile": "Flur"}, blocking=True, return_response=True
    )
    assert again == {"started": False, "reason": "already_recording"}


async def test_unknown_profile_and_not_loaded_raise(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "start_profile", {"profile": "gibtsnicht"}, blocking=True)
    assert err.value.translation_key == "profile_not_found"
    assert err.value.translation_placeholders == {"profile": "gibtsnicht"}

    await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "stop_profile", {"profile": "x"}, blocking=True)
    assert err.value.translation_key == "not_loaded"


async def test_camera_in_two_profiles_first_come_first_served(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass, [make_profile("Eins", ["camera.a"]), make_profile("Zwei", ["camera.a", "camera.b"])]
    )
    m = entry.runtime_data
    await hass.services.async_call(DOMAIN, "start_profile", {"profile": "Eins"}, blocking=True)
    res = await hass.services.async_call(
        DOMAIN, "start_profile", {"profile": "Zwei"}, blocking=True, return_response=True
    )
    assert res["cams"] == ["B"]
    assert res["skipped"] == [{"cam": "camera.a", "reason": "busy"}]
    assert m.profile_running("p_Eins")
    assert m.profile_running("p_Zwei")


async def test_camera_busy_in_foreign_session_is_skipped(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a", "camera.b"])])
    FakeRecorder.remote_profiles = {"default": {"aufnahme": True, "kameras": {"camera.a": {"status": "nimmt auf"}}}}
    res = await hass.services.async_call(
        DOMAIN, "start_profile", {"profile": "Eins"}, blocking=True, return_response=True
    )
    assert res["cams"] == ["B"]
    assert res["skipped"] == [{"cam": "camera.a", "reason": "busy"}]
    assert entry.runtime_data.profile_running("p_Eins")


async def test_missing_and_streamless_cameras_are_skipped(hass: HomeAssistant, stream: AsyncMock) -> None:
    add_cameras(hass, "ok", "blind")
    await setup_entry(hass, [make_profile("Eins", ["camera.ok", "camera.blind", "camera.gone"])])

    async def source(_hass: HomeAssistant, entity_id: str) -> str | None:
        return None if entity_id == "camera.blind" else STREAM

    stream.side_effect = source
    res = await hass.services.async_call(
        DOMAIN, "start_profile", {"profile": "Eins"}, blocking=True, return_response=True
    )
    assert res["cams"] == ["Ok"]
    assert res["skipped"] == [
        {"cam": "camera.blind", "reason": "no_stream"},
        {"cam": "camera.gone", "reason": "missing"},
    ]


async def test_manual_start_without_free_camera_fails_but_trigger_start_is_quiet(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.gone"])])
    m = entry.runtime_data
    with pytest.raises(ServiceValidationError) as err:
        await m.async_profile_start("Eins")
    assert err.value.translation_key == "no_cam_available"
    assert err.value.translation_placeholders["details"] == "camera.gone (missing)"
    result = await m._profile_start(m.profile("Eins"), manual=False)
    assert result["started"] is False
    assert result["reason"] == "no_cam_available"
    assert not FakeRecorder.calls


async def test_unreachable_addon_does_not_mark_running(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a"])])
    m = entry.runtime_data
    FakeRecorder.fail = RecorderError("Recorder-Add-on nicht erreichbar (test)")
    with pytest.raises(RecorderError):
        await m.async_profile_start("Eins")
    assert not m.profile_running("p_Eins")
    assert m.rec_online is False
    assert m.status == "error"


async def test_sun_window(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    hass.states.async_set("sun.sun", "above_horizon")
    entry = await setup_entry(
        hass, [make_profile("Nacht", ["camera.a"], sun="night"), make_profile("Tag", ["camera.b"], sun="day")]
    )
    m = entry.runtime_data
    assert m.profile_running("p_Tag")
    assert not m.profile_running("p_Nacht")
    hass.states.async_set("sun.sun", "below_horizon")
    await hass.async_block_till_done()
    assert m.profile_running("p_Nacht")
    assert not m.profile_running("p_Tag")  # Zeitfenster zu -> Aufnahme endet


async def test_day_times_block_trigger(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "on")
    now = dt_util.now()
    other = (now + timedelta(hours=2)).strftime("%H:%M")
    later = (now + timedelta(hours=3)).strftime("%H:%M")
    day = WEEKDAYS[now.weekday()]
    entry = await setup_entry(
        hass, [make_profile("Eins", ["camera.a"], triggers=["binary_sensor.x"], times={day: [f"{other}-{later}"]})]
    )
    assert not entry.runtime_data.profile_running("p_Eins")  # Auslöser an, aber die Zeit des Tages ist noch nicht da


async def test_max_duration_and_lost_detection(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "on")
    entry = await setup_entry(hass, [make_profile("X", ["camera.a"], triggers=["binary_sensor.x"], max_minutes=1)])
    m = entry.runtime_data
    assert m.profile_running("p_X")
    m.profile_state["p_X"]["start"] = (dt_util.utcnow() - timedelta(minutes=2)).isoformat()
    await m._profile_tick(None)
    assert not m.profile_running("p_X")
    await m._profile_tick(None)
    assert not m.profile_running("p_X")  # Auslöser noch an, aber Höchstdauer erreicht: kein Neustart
    hass.states.async_set("binary_sensor.x", "off")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.x", "on")
    await hass.async_block_till_done()
    assert m.profile_running("p_X")  # erst nach „aus → an“ wieder

    m._sync_profiles({"profile": {"p_X": {"aufnahme": False, "stop_grund": "speicher_voll"}}})
    assert not m.profile_running("p_X")
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "profile_lost_p_X")
    assert issue is not None
    assert issue.translation_placeholders == {"profile": "X", "reason": "speicher_voll"}
    assert m.status == "error"

    hass.states.async_set("binary_sensor.x", "off")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.x", "on")
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "profile_lost_p_X") is None  # neuer Start räumt den Hinweis auf


async def test_running_profile_is_readopted_after_restart(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    FakeRecorder.remote_profiles = {"p_A": {"aufnahme": True, "kameras": {"camera.a": {"status": "nimmt auf"}}}}
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"])])
    await entry.runtime_data._poll_recorder(None)  # der erste Abgleich läuft sonst als Hintergrundaufgabe
    assert entry.runtime_data.profile_running("p_A")
    assert entry.runtime_data.profile_state["p_A"]["cams"] == ["camera.a"]
    assert entry.runtime_data.status == "recording"
    await entry.runtime_data._profile_tick(None)
    assert entry.runtime_data.profile_running("p_A")  # ohne Auslöser läuft es bis zum Stopp von Hand weiter


async def test_readopted_profile_with_trigger_follows_its_trigger(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    hass.states.async_set("binary_sensor.x", "off")
    FakeRecorder.remote_profiles = {"p_A": {"aufnahme": True, "kameras": {"camera.a": {"status": "nimmt auf"}}}}
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], triggers=["binary_sensor.x"])])
    await entry.runtime_data._poll_recorder(None)
    assert entry.runtime_data.profile_running("p_A")
    await entry.runtime_data._profile_tick(None)
    assert not entry.runtime_data.profile_running("p_A")  # Auslöser ist aus -> das Profil endet wie gewohnt


async def test_cameras_of_one_device_get_distinct_file_names(hass: HomeAssistant) -> None:
    """Haupt- und Substream desselben Geräts heißen gleich und dürfen nicht dieselbe Datei beschreiben."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    source = MockConfigEntry(domain="other")
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("other", "d1")}, name="Flur"
    )
    registry = er.async_get(hass)
    for uid, object_id in (("main", "flur"), ("sub", "flur_sub")):
        registry.async_get_or_create("camera", "other", uid, suggested_object_id=object_id, device_id=device.id)
        hass.states.async_set(f"camera.{object_id}", "idle")
    await setup_entry(hass, [make_profile("Eins", ["camera.flur", "camera.flur_sub"], pattern="{cam}")])
    await hass.services.async_call(DOMAIN, "start_profile", {"profile": "Eins"}, blocking=True)
    stems = [c["stem"] for c in FakeRecorder.calls[-1][2]]
    assert stems == ["Flur flur", "Flur flur_sub"]


async def test_renamed_camera_entity_is_followed(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create("camera", "other", "uid1", suggested_object_id="flur")
    hass.states.async_set("camera.flur", "idle")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.flur", "camera.zweite"])])

    registry.async_update_entity("camera.flur", new_entity_id="camera.diele")
    await hass.async_block_till_done()

    assert entry.subentries["p_Eins"].data["cams"] == ["camera.diele", "camera.zweite"]
    assert entry.runtime_data.profiles["p_Eins"].cams == ["camera.diele", "camera.zweite"]  # nach dem Neuladen


async def test_stream_source_errors_are_swallowed(hass: HomeAssistant, stream: AsyncMock) -> None:
    from homeassistant.exceptions import HomeAssistantError

    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("Eins", ["camera.a"])])
    stream.side_effect = HomeAssistantError("kaputt")
    with pytest.raises(ServiceValidationError) as err:
        await entry.runtime_data.async_profile_start("Eins")
    assert err.value.translation_placeholders["details"] == "camera.a (no_stream)"


async def test_reauth_is_started_on_wrong_key(hass: HomeAssistant, bad_key: type[FakeRecorder]) -> None:
    bad_key.fail = None  # erst nach dem Einrichten ablehnen, sonst startet schon der erste Abgleich die Anmeldung
    entry = await setup_entry(hass)
    FakeRecorder.fail = RecorderAuthError("Schlüssel")
    with patch.object(entry, "async_start_reauth") as start_reauth:
        await entry.runtime_data._poll_recorder(None)
        await entry.runtime_data._poll_recorder(None)
    start_reauth.assert_called_once()  # nur einmal, nicht bei jeder Abfrage
