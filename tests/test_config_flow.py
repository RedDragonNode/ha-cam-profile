"""Config-Flow: Verbindung zum Add-on, neuer Schlüssel und Aufnahme-Profile als Untereinträge."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cam_profile.const import DOMAIN

from .conftest import KEY, URL, FakeRecorder, add_cameras, make_profile, setup_entry


async def _start_user_flow(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"recorder_url": f" {URL}/ ", "recorder_key": f" {KEY} "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cam Profile"
    assert result["data"] == {"recorder_url": URL, "recorder_key": KEY}  # bereinigt


async def test_user_flow_default_url_is_suggested(hass: HomeAssistant) -> None:
    result = await _start_user_flow(hass)
    url_field = next(k for k in result["data_schema"].schema if k == "recorder_url")
    assert url_field.default() == "http://local-cam-profile-recorder:8099"


async def test_user_flow_unreachable_and_wrong_key(hass: HomeAssistant, unreachable: type[FakeRecorder]) -> None:
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"recorder_url": URL, "recorder_key": KEY}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    from custom_components.cam_profile.recorder_client import RecorderAuthError

    FakeRecorder.fail = RecorderAuthError("Schlüssel")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"recorder_url": URL, "recorder_key": KEY}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    FakeRecorder.fail = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"recorder_url": URL, "recorder_key": KEY}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_second_entry_is_refused(hass: HomeAssistant) -> None:
    await setup_entry(hass)
    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reconfigure_changes_connection(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"recorder_url": "http://neu:8099", "recorder_key": "neuerneuerneuer1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"recorder_url": "http://neu:8099", "recorder_key": "neuerneuerneuer1"}


async def test_reauth_replaces_key(hass: HomeAssistant, bad_key: type[FakeRecorder]) -> None:
    entry = await setup_entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"recorder_key": "falschfalschfalsch"})
    assert result["errors"] == {"base": "invalid_auth"}

    FakeRecorder.fail = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"recorder_key": "richtigrichtig12"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["recorder_key"] == "richtigrichtig12"


# ------------------------------------------------------------------ Profile
async def _add_profile(hass: HomeAssistant, entry, basics: dict, when: dict | None = None) -> dict:
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "profile"), context={"source": "user"})
    assert flow["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], basics)
    if result["type"] is FlowResultType.FORM and result["step_id"] == "user":
        return result  # Fehler im ersten Schritt
    assert result["step_id"] == "user_when"
    return await hass.config_entries.subentries.async_configure(flow["flow_id"], when or {})


async def test_profile_flow_creates_subentry_from_any_camera(hass: HomeAssistant) -> None:
    add_cameras(hass, "treppe", "flur")
    entry = await setup_entry(hass)

    result = await _add_profile(
        hass,
        entry,
        {"name": " Treppe ", "folder": "Ueberwachung/Treppe", "cams": ["camera.treppe", "camera.flur"]},
        {"triggers": ["binary_sensor.treppe"], "after_seconds": 30, "max_minutes": 10, "sun": "night"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    sub = next(s for s in entry.subentries.values() if s.subentry_type == "profile")
    assert sub.title == "Treppe"
    assert sub.data == {
        "name": "Treppe",
        "folder": "Ueberwachung/Treppe",
        "cams": ["camera.treppe", "camera.flur"],
        "pattern": "{cam} %CCYY-%MM-%DD %hh-%mm-%ss",
        "triggers": ["binary_sensor.treppe"],
        "after_seconds": 30,
        "max_minutes": 10,
        "time_from": "",
        "time_to": "",
        "sun": "night",
    }


async def test_profile_flow_offers_recorder_folders_and_validates(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass, [make_profile("Vorhanden", ["camera.a"])])
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "profile"), context={"source": "user"})
    folder = next(k for k in flow["data_schema"].schema if k == "folder")
    options = [o["value"] for o in flow["data_schema"].schema[folder].config["options"]]
    assert options == ["Der_Fuchsbau", "Ueberwachung", "Ueberwachung/Treppe"]  # Unterordner stehen mit in der Auswahl

    bad = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "vorhanden", "folder": "../", "cams": []}
    )
    assert bad["errors"] == {"name": "name_taken", "folder": "folder_required", "cams": "cams_required"}

    ok = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Neu", "folder": "A/B", "cams": ["camera.a"]}
    )
    assert ok["step_id"] == "user_when"
    bad_time = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"time_from": "22:00:00"})
    assert bad_time["errors"] == {"time_to": "time_both"}
    done = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"time_from": "22:00:00", "time_to": "06:00:00"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY


async def test_profile_flow_works_when_recorder_is_unreachable(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    FakeRecorder.fail = Exception  # list_dirs wirft hier RecorderError, siehe unten
    from custom_components.cam_profile.recorder_client import RecorderError

    FakeRecorder.fail = RecorderError("weg")
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "profile"), context={"source": "user"})
    folder = next(k for k in flow["data_schema"].schema if k == "folder")
    assert flow["data_schema"].schema[folder].config["options"] == []  # Eingabe von Hand bleibt möglich


async def test_profile_reconfigure_keeps_own_name(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass, [make_profile("Eins", ["camera.a"]), make_profile("Zwei", ["camera.b"], triggers=["switch.x"])]
    )
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "profile"), context={"source": "reconfigure", "subentry_id": "p_Zwei"}
    )
    assert flow["step_id"] == "reconfigure"

    taken = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "eins", "folder": "X", "cams": ["camera.b"]}
    )
    assert taken["errors"] == {"name": "name_taken"}

    step2 = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Zwei", "folder": "Neuer/Ordner", "cams": ["camera.a", "camera.b"]}
    )
    assert step2["step_id"] == "reconfigure_when"
    done = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"triggers": []})
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    data = entry.subentries["p_Zwei"].data
    assert data["folder"] == "Neuer/Ordner"
    assert data["cams"] == ["camera.a", "camera.b"]
    assert data["triggers"] == []
