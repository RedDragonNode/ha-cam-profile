"""Sensoren: Status und freier Speicher."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .entity import CamProfileEntity, hub_device
from .manager import STATUS_ERROR, STATUS_IDLE, STATUS_RECORDING, ProfileManager


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    async_add_entities([StatusSensor(m), RecorderSpaceSensor(m)])


class StatusSensor(CamProfileEntity, SensorEntity):
    """idle, recording oder error. Die letzte Meldung steht im Attribut `message`."""

    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_IDLE, STATUS_RECORDING, STATUS_ERROR]  # noqa: RUF012
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, m: ProfileManager) -> None:
        super().__init__(m)
        self._attr_unique_id = f"{m.entry.entry_id}_status"
        self._attr_device_info = hub_device(m)

    @property
    def native_value(self) -> str:
        return self.manager.status

    @property
    def extra_state_attributes(self) -> dict:
        names = {
            pid: self.manager.profiles[pid].name for pid in self.manager.profile_state if pid in self.manager.profiles
        }
        return {
            "message": self.manager.message,
            "time": self.manager.message_time,
            "running_profiles": sorted(names.values()),
        }


class RecorderSpaceSensor(CamProfileEntity, SensorEntity):
    """Freier Speicher am Aufnahme-Ort des Add-ons."""

    _attr_translation_key = "recorder_free_space"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, m: ProfileManager) -> None:
        super().__init__(m)
        self._attr_unique_id = f"{m.entry.entry_id}_recorder_free_space"
        self._attr_device_info = hub_device(m)

    @property
    def available(self) -> bool:
        return bool(self.manager.rec_online)

    @property
    def native_value(self) -> float | None:
        return (self.manager.rec_status.get("speicher") or {}).get("frei_gb")

    @property
    def extra_state_attributes(self) -> dict:
        storage = self.manager.rec_status.get("speicher") or {}
        return {"total_gb": storage.get("gesamt_gb"), "folder": self.manager.rec_status.get("wurzel")}
