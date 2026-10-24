"""Cam Profile: Aufnahme-Profile für beliebige Home-Assistant-Kameras, aufgenommen vom Add-on „Cam Profile Recorder“."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from . import logic
from .const import (
    ATTR_PROFILE,
    CONF_TIME_FROM,
    CONF_TIME_TO,
    CONF_TIMES,
    CONF_WEEKDAYS,
    DOMAIN,
    LEGACY_DEFAULTS,
    MINOR_VERSION,
    SERVICE_START,
    SERVICE_STOP,
    SUBENTRY_PROFILE,
    WEEKDAYS,
)
from .manager import ProfileManager, overrides_store

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.TEXT,
    Platform.SELECT,
    Platform.BUTTON,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_OLD_SCHEDULE = "schedule"  # Profilfeld aus Version 0.5, wird bei der Migration entfernt

type CamProfileConfigEntry = ConfigEntry[ProfileManager]


def _manager(hass: HomeAssistant) -> ProfileManager:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def start_profile(call: ServiceCall) -> dict:
        return await _manager(hass).async_profile_start(call.data[ATTR_PROFILE])

    async def stop_profile(call: ServiceCall) -> dict:
        return await _manager(hass).async_profile_stop(call.data[ATTR_PROFILE])

    schema = vol.Schema({vol.Required(ATTR_PROFILE): cv.string})
    for name, handler in ((SERVICE_START, start_profile), (SERVICE_STOP, stop_profile)):
        hass.services.async_register(DOMAIN, name, handler, schema, supports_response=SupportsResponse.OPTIONAL)
    return True


def _window_into_day_times(data: dict[str, Any]) -> None:
    """Von/Bis (Version 0.6 und älter) wird zu den Zeiten jedes Tages, der keine eigenen hat."""
    start, end = data.pop(CONF_TIME_FROM, "") or "", data.pop(CONF_TIME_TO, "") or ""
    if not (start and end):
        return
    try:
        (window,) = logic.parse_times(f"{start}-{end}")
    except ValueError:
        return
    first, last = window.split("-", 1)
    if logic.split_range(window)[0] == logic.split_range(window)[1]:
        return  # von = bis hieß ganztägig
    times = {day: list(windows) for day, windows in (data.get(CONF_TIMES) or {}).items() if windows}
    for day in WEEKDAYS:
        times.setdefault(day, [f"{first}-{last}"])
    data[CONF_TIMES] = times


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.x -> 1.6, ohne dass sich das Verhalten der Profile ändert.

    1.3: Die globalen Grundeinstellungen aus Version 0.3 fallen weg, was ein Profil von dort geerbt hat,
    wird in das Profil geschrieben. 1.4: Leere Wochentage hießen jeden Tag und heißen jetzt an keinem Tag,
    deshalb speichern Profile alle sieben Tage ausdrücklich. 1.5: Das Zeitplan-Feld aus 0.5 entfällt.
    1.6: Von/Bis entfällt, es wird zu den Zeiten jedes Tages, der keine eigenen hat.
    """
    if entry.version == 1 and entry.minor_version < MINOR_VERSION:
        defaults = (
            {key: value for key, value in entry.options.items() if key in LEGACY_DEFAULTS}
            if entry.minor_version < 3
            else {}
        )
        for sub in list(entry.subentries.values()):
            if sub.subentry_type != SUBENTRY_PROFILE:
                continue
            data = {**defaults, **sub.data}
            had_schedule = bool(data.pop(_OLD_SCHEDULE, None))
            if (entry.minor_version < 4 or had_schedule) and not data.get(CONF_WEEKDAYS):
                data[CONF_WEEKDAYS] = list(WEEKDAYS)  # mit Zeitplan waren die Wochentage oft aus, weil er sie ersetzte
            _window_into_day_times(data)
            if data != dict(sub.data):
                hass.config_entries.async_update_subentry(entry, sub, data=data)
        hass.config_entries.async_update_entry(entry, options={}, minor_version=MINOR_VERSION)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CamProfileConfigEntry) -> bool:
    manager = ProfileManager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager
    manager.hub_device_id = (
        dr.async_get(hass)
        .async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.entry_id)},
            name="Cam Profile",
            manufacturer="RedDragonNode",
            model="Cam Profile Recorder",
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        .id
    )
    _remove_unused_entities(hass, entry, manager)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_reload_on_change))
    return True


def _remove_unused_entities(hass: HomeAssistant, entry: ConfigEntry, manager: ProfileManager) -> None:
    """Kameras ohne Profil verlieren ihren Aufnahme-Sensor, Profile mit Auslöser oder Einschränkung ihren Schalter."""
    registry = er.async_get(hass)
    cams = {f"{entry.entry_id}_cam_{eid}_recording" for eid in manager.cam_ids}
    switches = {f"{entry.entry_id}_{sid}_manual" for sid, p in manager.profiles.items() if p.manual_only}
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        stale_cam = ent.unique_id.startswith(f"{entry.entry_id}_cam_") and ent.unique_id not in cams
        stale_switch = (
            ent.domain == Platform.SWITCH and ent.unique_id.endswith("_manual") and ent.unique_id not in switches
        )
        stale_time = ent.domain == Platform.TIME  # Von/Bis gibt es seit 0.7 nicht mehr
        if stale_cam or stale_switch or stale_time:
            registry.async_remove(ent.entity_id)


async def _reload_on_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Profile oder Verbindung wurden geändert -> neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CamProfileConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Beim Löschen der Integration auch die gespeicherten Überschreibungen entfernen."""
    await overrides_store(hass, entry.entry_id).async_remove()
