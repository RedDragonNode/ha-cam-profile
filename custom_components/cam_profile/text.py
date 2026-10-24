"""Textfelder auf der Geräteseite des Profils: Zeiten je Wochentag überschreiben die Anlege-Werte."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry, logic
from .const import CONF_TIMES, DOMAIN, WEEKDAYS
from .entity import ProfileSettingEntity
from .manager import ProfileCfg, ProfileManager


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    for sid, profile in m.profiles.items():
        async_add_entities([ProfileTimesText(m, profile, day) for day in WEEKDAYS], config_subentry_id=sid)


class ProfileTimesText(ProfileSettingEntity, TextEntity):
    """Zeiten eines Wochentags, zum Beispiel „08:00-12:00, 18:00-22:00“. Leer heißt ganztägig (oder Von/Bis)."""

    fields = (CONF_TIMES,)
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 255

    def __init__(self, m: ProfileManager, profile: ProfileCfg, day: str) -> None:
        super().__init__(m, profile, f"times_{day}")
        self.day = day
        self._attr_translation_key = f"profile_times_{day}"

    def _value_of(self, cfg: ProfileCfg) -> str:
        return logic.format_times(cfg.times.get(self.day) or [])

    @property
    def native_value(self) -> str:
        return self._value_of(self.profile)

    @property
    def is_overridden(self) -> bool:
        # die Zeiten aller Tage werden zusammen gespeichert, überschrieben ist nur der Tag, der abweicht
        return CONF_TIMES in self.profile.overridden and self.native_value != self._value_of(
            self.manager.base[self.sid]
        )

    async def async_set_value(self, value: str) -> None:
        try:
            windows = logic.parse_times(value)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_times", translation_placeholders={"value": str(err)}
            ) from err
        times = {day: list(entries) for day, entries in self.profile.times.items() if entries}
        if windows:
            times[self.day] = windows
        else:
            times.pop(self.day, None)
        await self.manager.async_override(self.sid, {CONF_TIMES: times})
