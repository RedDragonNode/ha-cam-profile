"""Basisklassen und Geräte der Entities."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import ProfileCfg, ProfileManager


class CamProfileEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: ProfileManager) -> None:
        self.manager = manager

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self.manager.signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()


def hub_device(manager: ProfileManager) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, manager.entry.entry_id)},
        name="Cam Profile",
        manufacturer="RedDragonNode",
        model="Cam Profile Recorder",
        entry_type=DeviceEntryType.SERVICE,
    )


def profile_device(manager: ProfileManager, profile: ProfileCfg) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{manager.entry.entry_id}_{profile.subentry_id}")},
        translation_key="profile",
        translation_placeholders={"name": profile.name},
        manufacturer="RedDragonNode",
        model="Cam Profile",
        via_device_id=manager.hub_device_id,
    )


def cam_device(manager: ProfileManager, entity_id: str) -> DeviceInfo:
    """Eigenes Gerät für eine Kamera, die selbst zu keinem Gerät gehört."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{manager.entry.entry_id}_cam_{entity_id}")},
        name=manager.cam_name(entity_id),
        manufacturer="RedDragonNode",
        model="Kamera",
        via_device_id=manager.hub_device_id,
    )
