"""Binärsensoren: Recorder erreichbar, Aufnahme je Profil und je Kamera."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CamProfileConfigEntry
from .entity import CamProfileEntity, ProfileEntity, cam_device, hub_device
from .manager import ProfileCfg, ProfileManager


async def async_setup_entry(
    hass: HomeAssistant, entry: CamProfileConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    m = entry.runtime_data
    async_add_entities([RecorderOnlineSensor(m)])
    async_add_entities([CamRecordingSensor(hass, m, eid) for eid in m.cam_ids])
    for sid, profile in m.profiles.items():
        async_add_entities([ProfileRecordingSensor(m, profile)], config_subentry_id=sid)


class RecorderOnlineSensor(CamProfileEntity, BinarySensorEntity):
    _attr_translation_key = "recorder_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, m: ProfileManager) -> None:
        super().__init__(m)
        self._attr_unique_id = f"{m.entry.entry_id}_recorder_online"
        self._attr_device_info = hub_device(m)

    @property
    def is_on(self) -> bool:
        return bool(self.manager.rec_online)

    @property
    def extra_state_attributes(self) -> dict:
        return {"version": self.manager.rec_status.get("version")}


class CamRecordingSensor(CamProfileEntity, BinarySensorEntity):
    """Nimmt diese Kamera gerade auf (egal in welchem Profil)? Hängt am Gerät der Quell-Integration."""

    _attr_translation_key = "cam_recording"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, hass: HomeAssistant, m: ProfileManager, entity_id: str) -> None:
        super().__init__(m)
        self.camera = entity_id
        self._attr_unique_id = f"{m.entry.entry_id}_cam_{entity_id}_recording"
        if device := async_entity_id_to_device(hass, entity_id):
            self.device_entry = device  # hängt sich an das Gerät der Quell-Integration
        else:
            self._attr_device_info = cam_device(m, entity_id)

    def _info(self) -> dict:
        return (self.manager.rec_status.get("kameras") or {}).get(self.camera) or {}

    @property
    def is_on(self) -> bool:
        return self._info().get("status") == "nimmt auf"

    @property
    def extra_state_attributes(self) -> dict:
        info = self._info()
        return {
            "camera": self.camera,
            "file": info.get("datei"),
            "part": info.get("teil"),
            "restarts": info.get("neustarts"),
            "size_mb": round((info.get("bytes") or 0) / 1e6, 1),
            "last_error": info.get("letzter_fehler") or None,
            "profiles": sorted(p.name for p in self.manager.profiles.values() if self.camera in p.cams),
        }


class ProfileRecordingSensor(ProfileEntity, BinarySensorEntity):
    _attr_translation_key = "profile_recording"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, m: ProfileManager, profile: ProfileCfg) -> None:
        super().__init__(m, profile, "recording")

    @property
    def is_on(self) -> bool:
        return self.manager.profile_running(self.sid)

    @property
    def extra_state_attributes(self) -> dict:
        run = self.manager.profile_state.get(self.sid) or {}
        return {
            "folder": "/".join(self.profile.folder),
            "since": run.get("start"),
            "manual": run.get("manual"),
            "cams": run.get("cams") or self.profile.cams,
            "weekdays": self.profile.weekdays,
            "schedule": self.profile.schedule or None,
            "overridden": self.profile.overridden,
        }
