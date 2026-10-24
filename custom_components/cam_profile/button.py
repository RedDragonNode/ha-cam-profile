"""Knopf auf der Geräteseite des Profils: alle Überschreibungen verwerfen."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .entity import ProfileEntity
from .manager import ProfileCfg, ProfileManager


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    for sid, profile in m.profiles.items():
        async_add_entities([ProfileResetButton(m, profile)], config_subentry_id=sid)


class ProfileResetButton(ProfileEntity, ButtonEntity):
    """Setzt Nachlauf, Höchstdauer, Zeitfenster, Wochentage und Sonne auf die Anlege-Werte des Profils zurück."""

    _attr_translation_key = "profile_reset"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, m: ProfileManager, profile: ProfileCfg) -> None:
        super().__init__(m, profile, "reset")

    async def async_press(self) -> None:
        await self.manager.async_reset_overrides(self.sid)
