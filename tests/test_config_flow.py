"""Config-Flow: Verbindung zum Add-on, neuer Schlüssel und Aufnahme-Profile als Untereinträge."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
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
    old_manager = entry.runtime_data
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"recorder_url": "http://neu:8099", "recorder_key": "neuerneuerneuer1"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"recorder_url": "http://neu:8099", "recorder_key": "neuerneuerneuer1"}
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old_manager  # genau ein Neuladen über den Update-Listener


async def test_reauth_replaces_key(hass: HomeAssistant, bad_key: type[FakeRecorder]) -> None:
    entry = await setup_entry(hass)
    old_manager = entry.runtime_data
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"recorder_key": "falschfalschfalsch"})
    assert result["errors"] == {"base": "invalid_auth"}

    FakeRecorder.fail = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"recorder_key": "richtigrichtig12"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["recorder_key"] == "richtigrichtig12"
    await hass.async_block_till_done()
    assert entry.runtime_data is not old_manager


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
        "cams": ["camera.treppe", "camera.flur"],
        "folder": "Ueberwachung/Treppe",
        "triggers": ["binary_sensor.treppe"],
        "after_seconds": 30,
        "max_minutes": 10,
        "sun": "night",
    }  # Muster, Zeitfenster und Wochentage blieben leer und werden nicht gespeichert (= Grundeinstellung gilt)


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


# -------------------------------------------------- Grundeinstellungen und Vererbung
async def test_options_flow_saves_only_filled_fields(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass, options={"after_seconds": 5, "sun": "day"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    suggested = {str(k): k.description["suggested_value"] for k in result["data_schema"].schema if k.description}
    assert suggested == {"after_seconds": 5}  # nur was gesetzt ist, ist vorbelegt

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"folder": "Ueberwachung/Basis", "max_minutes": 0}
    )
    assert result["step_id"] == "when"
    bad = await hass.config_entries.options.async_configure(result["flow_id"], {"time_from": "22:00:00"})
    assert bad["errors"] == {"time_to": "time_both"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"weekdays": ["tue", "mon"], "sun": "any", "time_from": "22:00:00", "time_to": "06:00:00"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {
        "folder": "Ueberwachung/Basis",
        "max_minutes": 0,  # 0 ist ein Wert, kein leeres Feld
        "time_from": "22:00:00",
        "time_to": "06:00:00",
        "weekdays": ["mon", "tue"],
        "sun": "",
    }
    assert entry.runtime_data.profiles == {}  # neu geladen, ohne Profile


async def test_profile_flow_with_defaults_needs_no_folder_and_stores_nothing_extra(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, options={"folder": "Basis", "after_seconds": 30, "weekdays": ["sat", "sun"]})

    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "profile"), context={"source": "user"})
    assert flow["description_placeholders"]["default_folder"] == "Basis"
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Erbt", "cams": ["camera.a"]}
    )
    assert result["step_id"] == "user_when"
    assert result["description_placeholders"]["default_after"] == "30 s"
    assert result["description_placeholders"]["default_weekdays"] == "Sat, Sun"  # die Test-Instanz läuft auf Englisch
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    data = next(s.data for s in entry.subentries.values() if s.subentry_type == "profile")
    assert dict(data) == {"name": "Erbt", "cams": ["camera.a"], "triggers": []}
    assert entry.options["after_seconds"] == 30  # das Profil ändert die Grundeinstellung nie


async def test_profile_flow_without_any_folder_is_refused(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "profile"), context={"source": "user"})
    bad = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "X", "cams": ["camera.a"]})
    assert bad["errors"] == {"folder": "folder_required"}


async def test_profile_flow_stores_own_overrides_including_zero(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, options={"after_seconds": 30, "sun": "night"})
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "profile"), context={"source": "user"})
    await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Eigen", "folder": "X", "cams": ["camera.a"]}
    )
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"after_seconds": 0, "weekdays": ["fri", "mon"], "sun": "any"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    data = next(s.data for s in entry.subentries.values() if s.subentry_type == "profile")
    assert (data["after_seconds"], data["weekdays"], data["sun"]) == (0, ["mon", "fri"], "")
    profile = next(iter(entry.runtime_data.profiles.values()))
    assert (profile.after_s, profile.sun, profile.weekdays) == (0, "", ["mon", "fri"])


async def test_reconfigure_prefills_only_what_the_profile_sets(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(
        hass,
        [{"name": "A", "cams": ["camera.a"], "triggers": [], "folder": "X", "after_seconds": 5, "sun": ""}],
        options={"max_minutes": 10},
    )
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "profile"), context={"source": "reconfigure", "subentry_id": "p_A"}
    )
    step1 = {str(k): k.description["suggested_value"] for k in flow["data_schema"].schema if k.description}
    assert step1 == {"name": "A", "cams": ["camera.a"], "folder": "X"}

    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "A", "folder": "X", "cams": ["camera.a"]}
    )
    step2 = {str(k): k.description["suggested_value"] for k in result["data_schema"].schema if k.description}
    assert step2 == {
        "triggers": [],
        "after_seconds": 5,
        "sun": "any",
    }  # max_minutes bleibt leer: kommt aus der Grundeinstellung
