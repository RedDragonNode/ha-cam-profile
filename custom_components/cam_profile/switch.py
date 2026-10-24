"""Schalter: Profile ohne Auslöser und ohne Zeitfenster von Hand ein- und ausschalten."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .entity import CamProfileEntity, profile_device
from .manager import ProfileCfg, ProfileManager


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    for sid, profile in m.profiles.items():
        if profile.manual_only:
            async_add_entities([ProfileManualSwitch(m, profile)], config_subentry_id=sid)


class ProfileManualSwitch(CamProfileEntity, SwitchEntity):
    """Startet und beendet die Aufnahme des Profils. Bei Profilen mit Auslöser oder Zeitfenster gibt es ihn nicht,
    denn dort würde der Auslöser den Schalter sofort wieder umlegen."""

    _attr_translation_key = "profile_manual"

    def __init__(self, m: ProfileManager, profile: ProfileCfg) -> None:
        super().__init__(m)
        self.profile = profile
        self._attr_unique_id = f"{m.entry.entry_id}_{profile.subentry_id}_manual"
        self._attr_device_info = profile_device(m, profile)

    @property
    def is_on(self) -> bool:
        return self.manager.profile_running(self.profile.subentry_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_profile_start(self.profile.subentry_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_profile_stop(self.profile.subentry_id)
