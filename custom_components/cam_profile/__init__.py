"""Cam Profile: Aufnahme-Profile für beliebige Home-Assistant-Kameras, aufgenommen vom Add-on „Cam Profile Recorder“."""

from __future__ import annotations

from collections.abc import Mapping
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

from .const import (
    ATTR_PROFILE,
    CONF_AFTER,
    CONF_MAX_MINUTES,
    CONF_PATTERN,
    CONF_SUN,
    CONF_TIME_FROM,
    CONF_TIME_TO,
    DEFAULT_PATTERN,
    DOMAIN,
    MINOR_VERSION,
    SERVICE_START,
    SERVICE_STOP,
    SUBENTRY_PROFILE,
)
from .manager import ProfileManager

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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


def _without_old_defaults(data: Mapping[str, Any]) -> dict[str, Any]:
    """Version 0.2 speicherte jedes Feld im Profil. Werte, die nur der alte Standard waren, werden wieder „geerbt“."""
    cleaned = dict(data)
    for key, old_default in ((CONF_AFTER, 0), (CONF_MAX_MINUTES, 0), (CONF_SUN, ""), (CONF_PATTERN, DEFAULT_PATTERN)):
        if cleaned.get(key) == old_default:
            del cleaned[key]
    if not cleaned.get(CONF_TIME_FROM) and not cleaned.get(CONF_TIME_TO):
        cleaned.pop(CONF_TIME_FROM, None)
        cleaned.pop(CONF_TIME_TO, None)
    return cleaned


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.1 -> 1.2: Profile speichern nur noch, was sie selbst überschreiben, damit Grundeinstellungen greifen."""
    if entry.version == 1 and entry.minor_version < MINOR_VERSION:
        for sub in list(entry.subentries.values()):
            if sub.subentry_type == SUBENTRY_PROFILE and (data := _without_old_defaults(sub.data)) != dict(sub.data):
                hass.config_entries.async_update_subentry(entry, sub, data=data)
        hass.config_entries.async_update_entry(entry, minor_version=MINOR_VERSION)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CamProfileConfigEntry) -> bool:
    manager = ProfileManager(hass, entry)
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
    """Kameras ohne Profil verlieren ihren Aufnahme-Sensor, Profile mit Auslöser oder Zeitfenster ihren Schalter."""
    registry = er.async_get(hass)
    cams = {f"{entry.entry_id}_cam_{eid}_recording" for eid in manager.cam_ids}
    switches = {f"{entry.entry_id}_{sid}_manual" for sid, p in manager.profiles.items() if p.manual_only}
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        stale_cam = ent.unique_id.startswith(f"{entry.entry_id}_cam_") and ent.unique_id not in cams
        stale_switch = ent.domain == Platform.SWITCH and ent.unique_id not in switches
        if stale_cam or stale_switch:
            registry.async_remove(ent.entity_id)


async def _reload_on_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Profile oder Verbindung wurden geändert -> neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: CamProfileConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unloaded
