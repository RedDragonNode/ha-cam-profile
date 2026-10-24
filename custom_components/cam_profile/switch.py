"""Schalter: Profile von Hand aufnehmen lassen und Wochentage des Profils."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .const import CONF_WEEKDAYS, WEEKDAYS
from .entity import ProfileEntity, ProfileSettingEntity
from .manager import ProfileCfg, ProfileManager


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    for sid, profile in m.profiles.items():
        entities: list[SwitchEntity] = [ProfileWeekdaySwitch(m, profile, day) for day in WEEKDAYS]
        if profile.manual_only:
            entities.append(ProfileManualSwitch(m, profile))
        async_add_entities(entities, config_subentry_id=sid)


class ProfileManualSwitch(ProfileEntity, SwitchEntity):
    """Startet und beendet die Aufnahme des Profils. Bei Profilen mit Auslöser oder Einschränkung gibt es ihn nicht,
    denn dort würde der Auslöser den Schalter sofort wieder umlegen."""

    _attr_translation_key = "profile_manual"

    def __init__(self, m: ProfileManager, profile: ProfileCfg) -> None:
        super().__init__(m, profile, "manual")

    @property
    def is_on(self) -> bool:
        return self.manager.profile_running(self.sid)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_profile_start(self.sid)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_profile_stop(self.sid)


class ProfileWeekdaySwitch(ProfileSettingEntity, SwitchEntity):
    """Nimmt das Profil an diesem Wochentag auf? Alle sieben an heißt jeden Tag, alle aus an keinem Tag."""

    fields = (CONF_WEEKDAYS,)

    def __init__(self, m: ProfileManager, profile: ProfileCfg, day: str) -> None:
        super().__init__(m, profile, f"weekday_{day}")
        self.day = day
        self._attr_translation_key = f"profile_weekday_{day}"

    def _value_of(self, cfg: ProfileCfg) -> bool:
        return self.day in cfg.weekdays

    @property
    def is_on(self) -> bool:
        return self._value_of(self.profile)

    @property
    def is_overridden(self) -> bool:
        # die Tage werden zusammen gespeichert, überschrieben ist nur der Tag, der vom Anlege-Wert abweicht
        return CONF_WEEKDAYS in self.profile.overridden and self.is_on != self._value_of(self.manager.base[self.sid])

    async def _set_day(self, on: bool) -> None:
        days = set(self.profile.weekdays)
        days = days | {self.day} if on else days - {self.day}
        await self.manager.async_override(self.sid, {CONF_WEEKDAYS: [day for day in WEEKDAYS if day in days]})

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_day(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_day(False)
