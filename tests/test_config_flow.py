"""Config-Flow: Verbindung zum Add-on, neuer Schlüssel und Aufnahme-Profile als Untereinträge."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cam_profile.const import DEFAULT_PATTERN, DOMAIN, WEEKDAYS

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
def _step_values(result: dict) -> dict:
    return {str(k): k.description["suggested_value"] for k in result["data_schema"].schema if k.description}


async def _start(hass: HomeAssistant, entry, **context) -> dict:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, "profile"), context={"source": "user", **context}
    )


async def _add_profile(
    hass: HomeAssistant, entry, basics: dict, when: dict | None = None, days: dict | None = None
) -> dict:
    flow = await _start(hass, entry)
    assert flow["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], basics)
    if result["type"] is FlowResultType.FORM and result["step_id"] == "user":
        return result  # Fehler im ersten Schritt
    assert result["step_id"] == "user_when"
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], when or {})
    if result["type"] is FlowResultType.FORM and result["step_id"] == "user_when":
        return result  # Fehler im zweiten Schritt
    assert result["step_id"] == "user_days"
    return await hass.config_entries.subentries.async_configure(flow["flow_id"], days or {})


async def test_profile_flow_creates_subentry_from_any_camera(hass: HomeAssistant) -> None:
    add_cameras(hass, "treppe", "flur")
    entry = await setup_entry(hass)

    result = await _add_profile(
        hass,
        entry,
        {"name": " Treppe ", "folder": "Ueberwachung/Treppe", "cams": ["camera.treppe", "camera.flur"]},
        {"triggers": ["binary_sensor.treppe"], "after_seconds": 30, "max_minutes": 10, "sun": "night"},
        {"times_mon": "08:00-12:00, 18:00 - 22:00", "weekday_sun": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    sub = next(s for s in entry.subentries.values() if s.subentry_type == "profile")
    assert sub.title == "Treppe"
    assert sub.data == {
        "name": "Treppe",
        "cams": ["camera.treppe", "camera.flur"],
        "folder": "Ueberwachung/Treppe",
        "pattern": DEFAULT_PATTERN,
        "triggers": ["binary_sensor.treppe"],
        "after_seconds": 30,
        "max_minutes": 10,
        "time_from": "",
        "time_to": "",
        "sun": "night",
        "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat"],  # ein Schalter je Tag, Sonntag aus
        "times": {"mon": ["08:00-12:00", "18:00-22:00"]},  # nur Tage mit Zeiten, der Rest gilt ganztägig
    }  # das Profil speichert seine Anlege-Werte vollständig


async def test_profile_flow_offers_recorder_folders_and_validates(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass, [make_profile("Vorhanden", ["camera.a"])])
    flow = await _start(hass, entry)
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
    days = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"time_from": "22:00:00", "time_to": "06:00:00"}
    )
    assert days["step_id"] == "user_days"
    bad_times = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"times_tue": "bis morgen", "times_wed": "25:00-26:00", "times_thu": "08:00-12:00"}
    )
    assert bad_times["errors"] == {"times_tue": "times_invalid", "times_wed": "times_invalid"}
    done = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"times_thu": "08:00-12:00"})
    assert done["type"] is FlowResultType.CREATE_ENTRY


async def test_profile_flow_works_when_recorder_is_unreachable(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    from custom_components.cam_profile.recorder_client import RecorderError

    FakeRecorder.fail = RecorderError("weg")
    flow = await _start(hass, entry)
    folder = next(k for k in flow["data_schema"].schema if k == "folder")
    assert flow["data_schema"].schema[folder].config["options"] == []  # Eingabe von Hand bleibt möglich


async def test_profile_reconfigure_keeps_own_name(hass: HomeAssistant) -> None:
    add_cameras(hass, "a", "b")
    entry = await setup_entry(
        hass, [make_profile("Eins", ["camera.a"]), make_profile("Zwei", ["camera.b"], triggers=["switch.x"])]
    )
    flow = await _start(hass, entry, source="reconfigure", subentry_id="p_Zwei")
    assert flow["step_id"] == "reconfigure"

    taken = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "eins", "folder": "X", "cams": ["camera.b"]}
    )
    assert taken["errors"] == {"name": "name_taken"}

    step2 = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Zwei", "folder": "Neuer/Ordner", "cams": ["camera.a", "camera.b"]}
    )
    assert step2["step_id"] == "reconfigure_when"
    step3 = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"triggers": []})
    assert step3["step_id"] == "reconfigure_days"
    done = await hass.config_entries.subentries.async_configure(flow["flow_id"], {})
    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    data = entry.subentries["p_Zwei"].data
    assert data["folder"] == "Neuer/Ordner"
    assert data["cams"] == ["camera.a", "camera.b"]
    assert data["triggers"] == []


# ------------------------------------------------------- Anlege-Werte und Überschreibungen
async def test_options_flow_is_gone(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    assert not entry.supports_options


async def test_profile_flow_stores_all_values_including_zero_and_any_sun(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass)
    flow = await _start(hass, entry)
    assert _step_values(flow)["pattern"] == DEFAULT_PATTERN  # Muster ist beim Anlegen vorbelegt

    await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Eigen", "folder": "X", "cams": ["camera.a"], "pattern": " {cam} "}
    )
    days = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"after_seconds": 0, "sun": "any"})
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {f"weekday_{day}": day in ("fri", "mon") for day in WEEKDAYS}
    )
    assert days["step_id"] == "user_days"
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    data = next(s.data for s in entry.subentries.values() if s.subentry_type == "profile")
    assert (data["pattern"], data["after_seconds"], data["weekdays"], data["sun"]) == ("{cam}", 0, ["mon", "fri"], "")


async def test_profile_flow_empty_pattern_means_the_built_in_one(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass)
    await _add_profile(hass, entry, {"name": "A", "folder": "X", "cams": ["camera.a"], "pattern": ""})
    await hass.async_block_till_done()
    assert next(s.data for s in entry.subentries.values() if s.subentry_type == "profile")["pattern"] == DEFAULT_PATTERN


async def test_reconfigure_shows_creation_values_not_overrides_and_names_the_overrides(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], after_seconds=5, max_minutes=10)])
    await entry.runtime_data.async_override("p_A", {"after_seconds": 99, "weekdays": ["mon"]})

    flow = await _start(hass, entry, source="reconfigure", subentry_id="p_A")
    assert _step_values(flow)["folder"] == "Ueberwachung/A"
    assert flow["description_placeholders"] == {"overridden": "run-on, weekdays"}  # die Test-Instanz läuft auf Englisch

    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "A", "folder": "Ueberwachung/A", "cams": ["camera.a"]}
    )
    step2 = _step_values(result)
    assert (step2["after_seconds"], step2["max_minutes"], step2["sun"]) == (5, 10, "any")  # Anlege-Werte, nicht 99


async def test_reconfigure_keeps_the_overrides(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass, [make_profile("A", ["camera.a"], after_seconds=5)])
    await entry.runtime_data.async_override("p_A", {"after_seconds": 99})

    flow = await _start(hass, entry, source="reconfigure", subentry_id="p_A")
    await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "A", "folder": "Neu", "cams": ["camera.a"]}
    )
    await hass.config_entries.subentries.async_configure(flow["flow_id"], {"after_seconds": 7})
    done = await hass.config_entries.subentries.async_configure(flow["flow_id"], {})
    assert done["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    assert entry.subentries["p_A"].data["after_seconds"] == 7  # neuer Anlege-Wert
    profile = entry.runtime_data.profiles["p_A"]
    assert (profile.after_s, profile.folder) == (99, ["Neu"])  # die Überschreibung bleibt


async def test_profile_flow_without_folder_is_refused(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    flow = await _start(hass, entry)
    bad = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "X", "folder": "", "cams": ["camera.a"]}
    )
    assert bad["errors"] == {"folder": "folder_required"}


async def test_days_step_has_a_switch_and_times_per_weekday(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(hass)
    flow = await _start(hass, entry)
    await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "Plan", "folder": "X", "cams": ["camera.a"]}
    )
    days = await hass.config_entries.subentries.async_configure(flow["flow_id"], {})
    assert days["step_id"] == "user_days"
    fields = {str(k) for k in days["data_schema"].schema}
    assert fields == {f"weekday_{d}" for d in WEEKDAYS} | {f"times_{d}" for d in WEEKDAYS}
    suggested = _step_values(days)
    assert [suggested[f"weekday_{day}"] for day in WEEKDAYS] == [True] * 7  # neues Profil: jeder Tag an

    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {f"weekday_{day}": False for day in WEEKDAYS} | {"times_tue": "22:00-06:00"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    data = next(s.data for s in entry.subentries.values() if s.subentry_type == "profile")
    assert data["weekdays"] == []  # alle aus heißt an keinem Tag, im Formular wie auf der Geräteseite
    assert data["times"] == {"tue": ["22:00-06:00"]}


async def test_reconfigure_shows_the_saved_weekdays_and_times(hass: HomeAssistant) -> None:
    add_cameras(hass, "a")
    entry = await setup_entry(
        hass,
        [make_profile("A", ["camera.a"], weekdays=["mon", "sat"], times={"mon": ["08:00-12:00", "18:00-22:00"]})],
    )
    flow = await _start(hass, entry, source="reconfigure", subentry_id="p_A")
    await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"name": "A", "folder": "Ueberwachung/A", "cams": ["camera.a"]}
    )
    days = await hass.config_entries.subentries.async_configure(flow["flow_id"], {})
    assert days["step_id"] == "reconfigure_days"
    suggested = _step_values(days)
    assert [suggested[f"weekday_{day}"] for day in WEEKDAYS] == [True, False, False, False, False, True, False]
    assert suggested["times_mon"] == "08:00-12:00, 18:00-22:00"
    assert suggested["times_sat"] == ""
