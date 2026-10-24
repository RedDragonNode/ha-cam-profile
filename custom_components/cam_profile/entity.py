"""Basisklassen und Geräte der Entities."""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
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


class ProfileEntity(CamProfileEntity):
    """Entity am Gerät eines Profils.

    Das Profil wird bei jedem Zugriff nachgeschlagen, denn eine Überschreibung ersetzt sein Objekt im Manager.
    """

    def __init__(self, manager: ProfileManager, profile: ProfileCfg, key: str) -> None:
        super().__init__(manager)
        self.sid = profile.subentry_id
        self._attr_unique_id = f"{manager.entry.entry_id}_{self.sid}_{key}"
        self._attr_device_info = profile_device(manager, profile)

    @property
    def profile(self) -> ProfileCfg:
        return self.manager.profiles[self.sid]


class ProfileSettingEntity(ProfileEntity):
    """Einstellung auf der Geräteseite eines Profils.

    Der angezeigte Wert ist der geltende. Ändert man ihn, überschreibt das nur den Anlege-Wert, der im Profil
    gespeichert bleibt. Der Knopf „Auf Anlege-Werte zurücksetzen“ nimmt alle Überschreibungen wieder weg.
    """

    _attr_entity_category = EntityCategory.CONFIG
    fields: tuple[str, ...] = ()  # Felder des Profils, die diese Entity überschreibt

    def _value_of(self, cfg: ProfileCfg) -> Any:
        raise NotImplementedError

    @property
    def is_overridden(self) -> bool:
        return any(field in self.profile.overridden for field in self.fields)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        creation = self._value_of(self.manager.base[self.sid])
        return {
            "overridden": self.is_overridden,
            "creation_value": creation,
        }


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
