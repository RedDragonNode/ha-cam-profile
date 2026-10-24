"""Uhrzeiten auf der Geräteseite des Profils: Zeitfenster überschreiben. Von = bis heißt ganztägig."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .const import CONF_TIME_FROM, CONF_TIME_TO
from .entity import ProfileSettingEntity
from .manager import ProfileCfg, ProfileManager

_MIDNIGHT = "00:00:00"


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    for sid, profile in m.profiles.items():
        async_add_entities(
            [ProfileTime(m, profile, CONF_TIME_FROM), ProfileTime(m, profile, CONF_TIME_TO)], config_subentry_id=sid
        )


class ProfileTime(ProfileSettingEntity, TimeEntity):
    """Beginn oder Ende des Zeitfensters. Ohne Fenster zeigen beide 00:00 (= ganztägig)."""

    fields = (CONF_TIME_FROM, CONF_TIME_TO)

    def __init__(self, m: ProfileManager, profile: ProfileCfg, field: str) -> None:
        super().__init__(m, profile, field)
        self.field = field
        self._attr_translation_key = f"profile_{field}"

    def _value_of(self, cfg: ProfileCfg) -> time:
        return time.fromisoformat((cfg.time_from if self.field == CONF_TIME_FROM else cfg.time_to) or _MIDNIGHT)

    @property
    def native_value(self) -> time:
        return self._value_of(self.profile)

    async def async_set_value(self, value: time) -> None:
        start = self.profile.time_from or _MIDNIGHT
        end = self.profile.time_to or _MIDNIGHT
        chosen = value.strftime("%H:%M:%S")
        # beide Enden werden zusammen überschrieben, damit das Fenster nie nur zur Hälfte aus dem Profil stammt
        await self.manager.async_override(
            self.sid,
            {
                CONF_TIME_FROM: chosen if self.field == CONF_TIME_FROM else start,
                CONF_TIME_TO: chosen if self.field == CONF_TIME_TO else end,
            },
        )
