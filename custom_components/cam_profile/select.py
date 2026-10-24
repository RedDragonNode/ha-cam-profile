"""Auswahl auf der Geräteseite des Profils: Sonne überschreibt den Anlege-Wert."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .const import CONF_SUN, SUN_ANY, SUN_DAY, SUN_NIGHT
from .entity import ProfileSettingEntity
from .manager import ProfileCfg, ProfileManager

_ANY = "any"  # „egal“ wird im Profil als leerer Text gespeichert


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    for sid, profile in m.profiles.items():
        async_add_entities([ProfileSunSelect(m, profile)], config_subentry_id=sid)


class ProfileSunSelect(ProfileSettingEntity, SelectEntity):
    """Nur bei Tag, nur bei Nacht oder egal (Sonne über oder unter dem Horizont)."""

    _attr_translation_key = "profile_sun"
    fields = (CONF_SUN,)

    def __init__(self, m: ProfileManager, profile: ProfileCfg) -> None:
        super().__init__(m, profile, CONF_SUN)
        self._attr_options = [_ANY, SUN_DAY, SUN_NIGHT]

    def _value_of(self, cfg: ProfileCfg) -> str:
        return cfg.sun or _ANY

    @property
    def current_option(self) -> str:
        return self._value_of(self.profile)

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_override(self.sid, {CONF_SUN: SUN_ANY if option == _ANY else option})
