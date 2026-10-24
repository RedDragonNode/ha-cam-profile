"""Kern der Integration: Aufnahme-Profile und Abgleich mit dem Recorder-Add-on."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.camera import async_get_stream_source
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from . import logic
from .const import (
    CONF_AFTER,
    CONF_CAMS,
    CONF_FOLDER,
    CONF_MAX_MINUTES,
    CONF_PATTERN,
    CONF_RECORDER_KEY,
    CONF_RECORDER_URL,
    CONF_SUN,
    CONF_TIME_FROM,
    CONF_TIME_TO,
    CONF_TRIGGERS,
    CONF_WEEKDAYS,
    DEFAULT_PATTERN,
    DEFAULTABLE,
    DOMAIN,
    POLL_SECONDS,
    SUBENTRY_PROFILE,
    SUN_ANY,
    SUN_DAY,
    TICK_SECONDS,
    WEEKDAYS,
)
from .recorder_client import RecorderAuthError, RecorderClient, RecorderError

_LOGGER = logging.getLogger(__name__)

STATUS_IDLE = "idle"
STATUS_RECORDING = "recording"
STATUS_ERROR = "error"


@dataclass
class ProfileCfg:
    """Aufnahme-Profil mit den geltenden Werten (eigene, sonst Grundeinstellung, sonst eingebaute)."""

    subentry_id: str
    name: str
    folder: list[str]
    cams: list[str]
    pattern: str = DEFAULT_PATTERN
    triggers: list[str] = field(default_factory=list)
    after_s: int = 0
    max_min: int = 0
    time_from: str = ""
    time_to: str = ""
    weekdays: list[str] = field(default_factory=list)  # leer = jeden Tag
    sun: str = SUN_ANY
    inherited: list[str] = field(default_factory=list)  # Felder, die von den Grundeinstellungen kommen

    @property
    def has_time_window(self) -> bool:
        return logic.has_time_window(self.time_from, self.time_to)

    @property
    def weekday_limited(self) -> bool:
        return 0 < len(set(self.weekdays)) < len(WEEKDAYS)

    @property
    def has_window(self) -> bool:
        """Zeitfenster, Sonne oder Wochentage schränken ein: dann läuft das Profil auch ohne Auslöser von allein."""
        return self.has_time_window or bool(self.sun) or self.weekday_limited

    @property
    def manual_only(self) -> bool:
        """Ohne Auslöser und ohne Einschränkung startet und stoppt das Profil nur von Hand."""
        return not self.triggers and not self.has_window


class ProfileManager:
    """Hält die Profile eines Config-Entries und steuert ihre Aufnahmen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.signal = f"{DOMAIN}_update_{entry.entry_id}"
        self._unsubs: list[CALLBACK_TYPE] = []
        self.rec_status: dict[str, Any] = {}
        self.rec_online: bool | None = None
        self.message: str | None = None
        self.message_time: str | None = None
        self.failed = False
        self.profiles: dict[str, ProfileCfg] = {}
        self.profile_state: dict[str, dict[str, Any]] = {}  # laufende Profile (Laufzeit)
        self.hub_device_id: str | None = None  # Gerät „Cam Profile“, an dem die Profil-Geräte hängen
        self._prof_lock = asyncio.Lock()
        self._capped: set[str] = set()
        self._reauth_started = False
        self._read_subentries()

    # ------------------------------------------------------------------ Setup
    def _read_subentries(self) -> None:
        for sid, sub in self.entry.subentries.items():
            if sub.subentry_type != SUBENTRY_PROFILE:
                continue
            d = sub.data
            values, inherited = logic.resolve(d, self.entry.options, DEFAULTABLE)
            self.profiles[sid] = ProfileCfg(
                subentry_id=sid,
                name=d[CONF_NAME],
                folder=logic.split_path(values.get(CONF_FOLDER, "")),
                cams=list(d.get(CONF_CAMS) or []),
                pattern=values.get(CONF_PATTERN) or DEFAULT_PATTERN,
                triggers=list(d.get(CONF_TRIGGERS) or []),
                after_s=int(values.get(CONF_AFTER) or 0),
                max_min=int(values.get(CONF_MAX_MINUTES) or 0),
                time_from=values.get(CONF_TIME_FROM) or "",
                time_to=values.get(CONF_TIME_TO) or "",
                weekdays=[day for day in WEEKDAYS if day in (values.get(CONF_WEEKDAYS) or [])],
                sun=values.get(CONF_SUN) or SUN_ANY,
                inherited=inherited,
            )

    @property
    def cam_ids(self) -> list[str]:
        """Alle Kamera-Entities, die in mindestens einem Profil vorkommen."""
        seen: dict[str, None] = {}
        for p in self.profiles.values():
            for eid in p.cams:
                seen.setdefault(eid)
        return sorted(seen)

    @callback
    def async_start(self) -> None:
        watch = {e for p in self.profiles.values() for e in p.triggers}
        if any(p.sun for p in self.profiles.values()):
            watch.add("sun.sun")
        if watch:
            self._unsubs.append(async_track_state_change_event(self.hass, sorted(watch), self._profile_state_changed))
        if self.profiles:
            self._unsubs.append(
                async_track_time_interval(self.hass, self._profile_tick, timedelta(seconds=TICK_SECONDS))
            )
        self._unsubs.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._entity_registry_updated,
                event_filter=_is_rename,
            )
        )
        self._unsubs.append(async_track_time_interval(self.hass, self._poll_recorder, timedelta(seconds=POLL_SECONDS)))
        self.hass.async_create_background_task(self._first_sync(), name=f"{DOMAIN}_poll")
        self._drop_stale_issues()

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # ---------------------------------------------------------------- Helfer
    @callback
    def notify(self) -> None:
        async_dispatcher_send(self.hass, self.signal)

    @property
    def status(self) -> str:
        if self.failed:
            return STATUS_ERROR
        return STATUS_RECORDING if self.profile_state else STATUS_IDLE

    def _set_message(self, text: str, *, failed: bool = False) -> None:
        self.message, self.message_time, self.failed = text, dt_util.now().isoformat(), failed

    def _recorder(self) -> RecorderClient:
        url, key = self.entry.data.get(CONF_RECORDER_URL), self.entry.data.get(CONF_RECORDER_KEY)
        if not url or not key:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="recorder_not_configured")
        return RecorderClient(async_get_clientsession(self.hass), url, key)

    def cam_name(self, entity_id: str) -> str:
        """Anzeigename einer Kamera: Gerätename, sonst Name der Entity."""
        ent = er.async_get(self.hass).async_get(entity_id)
        if ent and ent.device_id and (dev := dr.async_get(self.hass).async_get(ent.device_id)):
            name = dev.name_by_user or dev.name
            if name:
                return name
        if (state := self.hass.states.get(entity_id)) and state.name:
            return state.name
        return (ent.name or ent.original_name) if ent and (ent.name or ent.original_name) else entity_id

    # ---------------------------------------------------- Umbenannte Entities
    @callback
    def _entity_registry_updated(self, event: Event) -> None:
        """Wird eine Kamera-Entity umbenannt, ziehen die Profile mit (sonst fände das Profil sie nicht mehr)."""
        old, new = event.data["old_entity_id"], event.data["entity_id"]
        for sid, p in self.profiles.items():
            if old not in p.cams:
                continue
            sub = self.entry.subentries[sid]
            cams = [new if c == old else c for c in sub.data[CONF_CAMS]]
            self.hass.config_entries.async_update_subentry(self.entry, sub, data={**sub.data, CONF_CAMS: cams})

    # ------------------------------------------------------------------ Recorder
    async def _poll_recorder(self, _now: datetime | None) -> None:
        """Zustand des Add-ons holen; verlorene Profil-Aufnahmen (Absturz, Platte voll) erkennen."""
        try:
            st = await self._recorder().status()
        except RecorderAuthError:
            self._start_reauth()
            return
        except (RecorderError, ServiceValidationError):
            if self.rec_online is not False:
                self.rec_online = False
                self.notify()
            return
        self.rec_status, self.rec_online = st, True
        self._sync_profiles(st)
        self.notify()

    def _start_reauth(self) -> None:
        self.rec_online = False
        self.notify()
        if not self._reauth_started:
            self._reauth_started = True
            self.entry.async_start_reauth(self.hass)

    async def _first_sync(self) -> None:
        """Beim Start erst den Add-on-Stand holen (laufende Profile erkennen), dann Auslöser auswerten."""
        await self._poll_recorder(None)
        await self._profile_tick(None)

    # ------------------------------------------------------------------ Profile
    def profile(self, ref: str) -> ProfileCfg:
        if ref in self.profiles:
            return self.profiles[ref]
        norm = logic.norm(ref)
        for p in self.profiles.values():
            if norm == logic.norm(p.name):
                return p
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="profile_not_found", translation_placeholders={"profile": ref}
        )

    def profile_running(self, pid: str) -> bool:
        return pid in self.profile_state

    def _busy_cam_ids(self, exclude: str) -> set[str]:
        """Kameras, die gerade in einem anderen Profil aufnehmen.

        Quelle der Wahrheit ist der Add-on-Stand (er kennt auch Aufnahmen, die nicht von dieser Integration stammen),
        dazu der eigene Merker für gerade gestartete Profile.
        """
        busy: set[str] = set()
        for pid, st in self.profile_state.items():
            if pid != exclude:
                busy |= set(st.get("cams") or [])
        for pid, ps in (self.rec_status.get("profile") or {}).items():
            if pid != exclude and ps.get("aufnahme"):
                busy |= {k for k, c in (ps.get("kameras") or {}).items() if c.get("status") != "beendet"}
        return busy

    def _trigger_on(self, p: ProfileCfg) -> bool:
        return any((st := self.hass.states.get(e)) is not None and st.state == STATE_ON for e in p.triggers)

    def _window_open(self, p: ProfileCfg, now: datetime) -> bool:
        if p.weekday_limited and WEEKDAYS[logic.effective_weekday(now, p.time_from, p.time_to)] not in p.weekdays:
            return False
        if p.has_time_window and not logic.in_time_window(now, p.time_from, p.time_to):
            return False
        if p.sun:
            sun = self.hass.states.get("sun.sun")
            if sun is None or sun.state not in ("above_horizon", "below_horizon"):
                return False
            if (sun.state == "above_horizon") != (p.sun == SUN_DAY):
                return False
        return True

    def _wanted(self, p: ProfileCfg, now: datetime) -> bool:
        if p.manual_only:
            return False
        if not self._window_open(p, now):
            return False
        return self._trigger_on(p) if p.triggers else True

    @callback
    def _profile_state_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self._profile_tick(None))

    async def _profile_tick(self, _now: datetime | None) -> None:
        """Gleicht jedes Profil mit seinen Auslösern ab (Start, Nachlauf, Höchstdauer, Zeitfenster)."""
        async with self._prof_lock:
            now = dt_util.now()
            for p in list(self.profiles.values()):
                try:
                    await self._reconcile(p, now)
                except HomeAssistantError as err:
                    _LOGGER.error("Profil %s: %s", p.name, err)
                    self._set_message(f"{p.name}: {err}", failed=True)
                    self.notify()

    async def _reconcile(self, p: ProfileCfg, now: datetime) -> None:
        run = self.profile_state.get(p.subentry_id)
        wanted = self._wanted(p, now)
        if not wanted:
            self._capped.discard(p.subentry_id)  # Auslöser vorbei -> nächste Runde darf wieder starten
        if run is None:
            if wanted and p.subentry_id not in self._capped:
                await self._profile_start(p, manual=False)
            return
        if run.get("manual"):
            return
        if wanted:
            run["off_since"] = None
            if (
                p.max_min
                and (dt_util.utcnow() - dt_util.parse_datetime(run["start"])).total_seconds() >= p.max_min * 60
            ):
                self._capped.add(p.subentry_id)
                await self._profile_stop(p, "max_duration")
            return
        if p.has_window and not self._window_open(p, now):
            await self._profile_stop(p, "window_closed")
            return
        off = run.get("off_since")
        if off is None:
            run["off_since"] = dt_util.utcnow().isoformat()
            off = run["off_since"]
        if (dt_util.utcnow() - dt_util.parse_datetime(off)).total_seconds() >= p.after_s:
            await self._profile_stop(p, "trigger_off")

    async def async_profile_start(self, ref: str) -> dict[str, Any]:
        p = self.profile(ref)
        async with self._prof_lock:
            if p.subentry_id in self.profile_state:
                return {"started": False, "reason": "already_recording"}
            return await self._profile_start(p, manual=True)

    async def async_profile_stop(self, ref: str) -> dict[str, Any]:
        p = self.profile(ref)
        async with self._prof_lock:
            if p.subentry_id not in self.profile_state:
                return {"stopped": False, "reason": "not_recording"}
            await self._profile_stop(p, "manual")
            return {"stopped": True}

    async def _stream_url(self, entity_id: str) -> str | None:
        try:
            return await async_get_stream_source(self.hass, entity_id)
        except HomeAssistantError as err:
            _LOGGER.warning("Stream-Quelle von %s nicht lesbar: %s", entity_id, err)
            return None

    async def _profile_start(self, p: ProfileCfg, manual: bool) -> dict[str, Any]:
        client = self._recorder()
        try:  # frischer Add-on-Stand, damit Aufnahmen anderer Profile nicht übersehen werden
            self.rec_status, self.rec_online = await client.status(), True
        except RecorderError as err:
            self.rec_online = False
            self._set_message(f"{p.name}: {err}", failed=True)
            self.notify()
            if manual:
                raise
            _LOGGER.warning("Profil %s konnte nicht starten: %s", p.name, err)
            return {"started": False, "reason": str(err)}
        busy = self._busy_cam_ids(p.subentry_id)
        now = dt_util.now()
        skipped: list[dict[str, str]] = []
        ready: list[tuple[str, str]] = []  # (entity_id, Stream-Adresse)
        for eid in p.cams:
            if self.hass.states.get(eid) is None:
                skipped.append({"cam": eid, "reason": "missing"})
            elif eid in busy:
                skipped.append({"cam": eid, "reason": "busy"})
            elif not (url := await self._stream_url(eid)):
                skipped.append({"cam": eid, "reason": "no_stream"})
            else:
                ready.append((eid, url))
        if not ready:
            if manual:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_cam_available",
                    translation_placeholders={"profile": p.name, "details": _describe(skipped)},
                )
            return {"started": False, "reason": "no_cam_available", "skipped": skipped}
        names = logic.unique_names([self.cam_name(eid) for eid, _ in ready], [eid.split(".", 1)[1] for eid, _ in ready])
        cams = [
            {
                "id": eid,
                "name": name,
                "url": url,
                "stem": logic.render_pattern(p.pattern, now, cam=name, short=logic.short_code(name), profile=p.name),
            }
            for (eid, url), name in zip(ready, names, strict=True)
        ]
        session = logic.render_pattern("{profile} %CCYY-%MM-%DD %hh-%mm-%ss", now, cam="", short="", profile=p.name)
        try:
            await client.start(p.folder, cams, session, p.subentry_id)
        except RecorderError as err:
            self.rec_online = False if "nicht erreichbar" in str(err) else self.rec_online
            self._set_message(f"{p.name}: {err}", failed=True)
            self.notify()
            if manual:
                raise
            _LOGGER.warning("Profil %s konnte nicht starten: %s", p.name, err)
            return {"started": False, "reason": str(err)}
        self.profile_state[p.subentry_id] = {
            "start": dt_util.utcnow().isoformat(),
            "manual": manual,
            "cams": [c["id"] for c in cams],
            "off_since": None,
        }
        ir.async_delete_issue(self.hass, DOMAIN, f"profile_lost_{p.subentry_id}")
        self._set_message(f"{p.name}: recording ({len(cams)} cams)")
        self.notify()
        return {"started": True, "cams": [c["name"] for c in cams], "skipped": skipped, "folder": "/".join(p.folder)}

    async def _profile_stop(self, p: ProfileCfg, reason: str) -> None:
        client = self._recorder()
        try:
            await client.stop(p.subentry_id)
        except RecorderError as err:
            self._set_message(f"{p.name}: {err}", failed=True)
            self.notify()
            raise
        self.profile_state.pop(p.subentry_id, None)
        self._set_message(f"{p.name}: stopped ({reason})")
        self.notify()

    @callback
    def _sync_profiles(self, st: dict[str, Any]) -> None:
        """Add-on-Stand übernehmen: nach HA-Neustart weiterlaufende Profile erkennen, verlorene melden."""
        if "profile" not in st:
            return
        remote = st["profile"]
        for pid, p in self.profiles.items():
            ps = remote.get(pid) or {}
            if ps.get("aufnahme") and pid not in self.profile_state:
                cams = [k for k, c in (ps.get("kameras") or {}).items() if c.get("status") != "beendet"]
                self.profile_state[pid] = {
                    "start": dt_util.utcnow().isoformat(),
                    "manual": p.manual_only,  # ein Profil ohne Auslöser läuft sonst nach dem Neuladen nicht weiter
                    "cams": cams,
                    "off_since": None,
                }
            elif not ps.get("aufnahme") and pid in self.profile_state and not self._prof_lock.locked():
                self.profile_state.pop(pid, None)
                reason = ps.get("stop_grund") or "unknown"
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"profile_lost_{pid}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="profile_lost",
                    translation_placeholders={"profile": p.name, "reason": reason},
                )
                self._set_message(f"{p.name}: stopped by the recorder ({reason})", failed=True)

    @callback
    def _drop_stale_issues(self) -> None:
        """Hinweise zu Profilen, die es nicht mehr gibt, entfernen."""
        registry = ir.async_get(self.hass)
        for domain, issue_id in list(registry.issues):
            if domain == DOMAIN and issue_id.startswith("profile_lost_") and issue_id[13:] not in self.profiles:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)


@callback
def _is_rename(data: er.EventEntityRegistryUpdatedData) -> bool:
    return data["action"] == "update" and "old_entity_id" in data


def _describe(skipped: list[dict[str, str]]) -> str:
    return ", ".join(f"{s['cam']} ({s['reason']})" for s in skipped) or "-"
