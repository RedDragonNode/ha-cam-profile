"""Zahlen auf der Geräteseite des Profils: Nachlauf und Höchstdauer überschreiben die Anlege-Werte."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .const import CONF_AFTER, CONF_MAX_MINUTES
from .entity import ProfileSettingEntity
from .manager import ProfileCfg, ProfileManager


@dataclass(frozen=True)
class NumberSpec:
    field: str  # Feld des Profils
    attr: str  # Attribut von ProfileCfg
    translation_key: str
    maximum: int
    unit: UnitOfTime


SPECS = (
    NumberSpec(CONF_AFTER, "after_s", "profile_after", 3600, UnitOfTime.SECONDS),
    NumberSpec(CONF_MAX_MINUTES, "max_min", "profile_max", 1440, UnitOfTime.MINUTES),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    for sid, profile in m.profiles.items():
        async_add_entities([ProfileNumber(m, profile, spec) for spec in SPECS], config_subentry_id=sid)


class ProfileNumber(ProfileSettingEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_min_value = 0
    _attr_native_step = 1

    def __init__(self, m: ProfileManager, profile: ProfileCfg, spec: NumberSpec) -> None:
        super().__init__(m, profile, spec.field)
        self.spec = spec
        self.fields = (spec.field,)
        self._attr_translation_key = spec.translation_key
        self._attr_native_max_value = spec.maximum
        self._attr_native_unit_of_measurement = spec.unit

    def _value_of(self, cfg: ProfileCfg) -> int:
        return getattr(cfg, self.spec.attr)

    @property
    def native_value(self) -> int:
        return self._value_of(self.profile)

    async def async_set_native_value(self, value: float) -> None:
        await self.manager.async_override(self.sid, {self.spec.field: int(value)})
