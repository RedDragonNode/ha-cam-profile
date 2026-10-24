"""Config-Flow (Verbindung) und Untereinträge (Aufnahme-Profile mit ihren Anlege-Werten)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    DEFAULT_RECORDER_URL,
    DOMAIN,
    MINOR_VERSION,
    SUBENTRY_PROFILE,
    SUN_DAY,
    SUN_NIGHT,
    WEEKDAYS,
)
from .recorder_client import RecorderAuthError, RecorderClient, RecorderError

_TEXT = selector.TextSelector()
_SECRET = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))

# Auswahl in der Oberfläche -> gespeicherter Wert ("egal" wird als leerer Text gespeichert und überschreibt dann auch)
_SUN_OPTIONS = {"any": "", SUN_DAY: SUN_DAY, SUN_NIGHT: SUN_NIGHT}
_SUN_SUGGESTION = {"": "any", SUN_DAY: SUN_DAY, SUN_NIGHT: SUN_NIGHT}

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RECORDER_URL, default=DEFAULT_RECORDER_URL): _TEXT,
        vol.Required(CONF_RECORDER_KEY): _SECRET,
    }
)


# ----------------------------------------------------------------- Bausteine
def _num(hi: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=hi, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement=unit
        )
    )


def _folder_select(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=o, label=o) for o in options],
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _weekday_select() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(WEEKDAYS),
            multiple=True,
            translation_key="weekdays",
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _sun_select() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(_SUN_OPTIONS),
            translation_key="sun_window",
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _how_data(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Zielordner und Dateinamen-Muster (ohne Muster gilt das eingebaute)."""
    return {
        CONF_FOLDER: "/".join(logic.split_path(user_input.get(CONF_FOLDER) or "")),
        CONF_PATTERN: (user_input.get(CONF_PATTERN) or "").strip() or DEFAULT_PATTERN,
    }


def _when_data(user_input: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Nachlauf, Höchstdauer, Zeitfenster, Wochentage und Sonne sowie die Fehler dazu."""
    errors: dict[str, str] = {}
    start, end = user_input.get(CONF_TIME_FROM) or "", user_input.get(CONF_TIME_TO) or ""
    if bool(start) != bool(end):
        errors[CONF_TIME_TO] = "time_both"
    data = {
        CONF_AFTER: int(user_input.get(CONF_AFTER) or 0),
        CONF_MAX_MINUTES: int(user_input.get(CONF_MAX_MINUTES) or 0),
        CONF_TIME_FROM: start if start and end else "",
        CONF_TIME_TO: end if start and end else "",
        CONF_WEEKDAYS: [day for day in WEEKDAYS if day in (user_input.get(CONF_WEEKDAYS) or [])],
        CONF_SUN: _SUN_OPTIONS.get(user_input.get(CONF_SUN) or "any", ""),
    }
    return data, errors


# Vorbelegung beim Anlegen (und für Felder, die ein älteres Profil nicht gespeichert hat)
_NEW_PROFILE = {CONF_PATTERN: DEFAULT_PATTERN, CONF_AFTER: 0, CONF_MAX_MINUTES: 0, CONF_SUN: ""}


def _suggestions(current: Mapping[str, Any]) -> dict[str, Any]:
    values = {**_NEW_PROFILE, **current}
    values[CONF_SUN] = _SUN_SUGGESTION.get(values[CONF_SUN], "any")
    return values


async def _check_recorder(hass: HomeAssistant, url: str, key: str) -> str | None:
    """Fehlerschlüssel der Verbindungsprüfung, None wenn die App antwortet."""
    try:
        await RecorderClient(async_get_clientsession(hass), url, key).status()
    except RecorderAuthError:
        return "invalid_auth"
    except RecorderError:
        return "cannot_connect"
    return None


async def _folder_options(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """Alle Ordner des Recorders bis zwei Ebenen ('Haupt' und 'Haupt/Unter') als eine Auswahlliste.

    Ist der Recorder nicht erreichbar, bleibt die Liste leer und der Name lässt sich von Hand eintippen.
    """
    try:
        client = RecorderClient(
            async_get_clientsession(hass), entry.data[CONF_RECORDER_URL], entry.data[CONF_RECORDER_KEY]
        )
        out: list[str] = []
        for main in await client.list_dirs([]):
            out.append(main)
            out.extend(f"{main}/{sub}" for sub in await client.list_dirs([main]))
    except RecorderError:
        return []
    return out


# ------------------------------------------------------------------ Verbindung
class CamProfileConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = MINOR_VERSION

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_RECORDER_URL].strip().rstrip("/")
            key = user_input[CONF_RECORDER_KEY].strip()
            if error := await _check_recorder(self.hass, url, key):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="Cam Profile", data={CONF_RECORDER_URL: url, CONF_RECORDER_KEY: key}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(CONNECTION_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_RECORDER_URL].strip().rstrip("/")
            key = user_input[CONF_RECORDER_KEY].strip()
            if error := await _check_recorder(self.hass, url, key):
                errors["base"] = error
            else:
                # neu geladen wird über den Update-Listener der Integration, ein zweites Neuladen wäre doppelt
                return self.async_update_and_abort(entry, data_updates={CONF_RECORDER_URL: url, CONF_RECORDER_KEY: key})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(CONNECTION_SCHEMA, user_input or dict(entry.data)),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_RECORDER_KEY].strip()
            if error := await _check_recorder(self.hass, entry.data[CONF_RECORDER_URL], key):
                errors["base"] = error
            else:
                return self.async_update_and_abort(entry, data_updates={CONF_RECORDER_KEY: key})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_RECORDER_KEY): _SECRET}),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_PROFILE: ProfileSubentryFlow}


# ----------------------------------------------------------------- Profile
class ProfileSubentryFlow(ConfigSubentryFlow):
    """Aufnahme-Profil anlegen oder bearbeiten: Schritt 1 wohin und welche Kameras, Schritt 2 wann.

    Was hier steht, sind die Anlege-Werte des Profils. Nachlauf, Höchstdauer, Zeitfenster, Wochentage und Sonne
    lassen sich später auf der Geräteseite des Profils überschreiben, ohne dass sich diese Werte ändern.
    """

    _basics: dict[str, Any]
    _own: str | None = None

    def _placeholders(self) -> dict[str, str]:
        manager = getattr(self._get_entry(), "runtime_data", None)
        profile = manager.profiles.get(self._own) if manager and self._own else None
        return {
            "overridden": logic.describe_overrides(profile.overridden if profile else [], self.hass.config.language)
        }

    def _taken_names(self) -> set[str]:
        return {
            logic.norm(s.data[CONF_NAME])
            for sid, s in self._get_entry().subentries.items()
            if s.subentry_type == SUBENTRY_PROFILE and sid != self._own
        }

    # -------------------------------------------------------------- Schritt 1
    async def _step_basics(
        self, step_id: str, user_input: dict[str, Any] | None, current: Mapping[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            cams = list(user_input.get(CONF_CAMS) or [])
            how = _how_data(user_input)
            if not name or logic.norm(name) in self._taken_names():
                errors[CONF_NAME] = "name_taken"
            if not how[CONF_FOLDER]:
                errors[CONF_FOLDER] = "folder_required"
            if not cams:
                errors[CONF_CAMS] = "cams_required"
            if not errors:
                self._basics = {CONF_NAME: name, CONF_CAMS: cams, **how}
                return await self._step_when(f"{step_id}_when", None, current)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): _TEXT,
                vol.Required(CONF_FOLDER): _folder_select(await _folder_options(self.hass, self._get_entry())),
                vol.Required(CONF_CAMS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="camera", multiple=True)
                ),
                vol.Optional(CONF_PATTERN): _TEXT,
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, user_input or _suggestions(current)),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    # -------------------------------------------------------------- Schritt 2
    async def _step_when(
        self, step_id: str, user_input: dict[str, Any] | None, current: Mapping[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            when, errors = _when_data(user_input)
            if not errors:
                data = {
                    **self._basics,
                    CONF_TRIGGERS: list(user_input.get(CONF_TRIGGERS) or []),
                    **when,
                }
                unique_id = logic.norm(data[CONF_NAME])
                if self._own is None:
                    return self.async_create_entry(title=data[CONF_NAME], data=data, unique_id=unique_id)
                return self.async_update_and_abort(
                    self._get_entry(),
                    self._get_reconfigure_subentry(),
                    title=data[CONF_NAME],
                    unique_id=unique_id,
                    data=data,
                )
        schema = vol.Schema(
            {
                vol.Optional(CONF_TRIGGERS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "switch", "input_boolean", "sensor"], multiple=True
                    )
                ),
                vol.Optional(CONF_AFTER): _num(3600, "s"),
                vol.Optional(CONF_MAX_MINUTES): _num(1440, "min"),
                vol.Optional(CONF_TIME_FROM): selector.TimeSelector(),
                vol.Optional(CONF_TIME_TO): selector.TimeSelector(),
                vol.Optional(CONF_WEEKDAYS): _weekday_select(),
                vol.Optional(CONF_SUN): _sun_select(),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, user_input or _suggestions(current)),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    # ------------------------------------------------------------- Einstiege
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._own = None
        return await self._step_basics("user", user_input, {})

    async def async_step_user_when(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._step_when("user_when", user_input, {})

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        self._own = sub.subentry_id
        return await self._step_basics("reconfigure", user_input, dict(sub.data))

    async def async_step_reconfigure_when(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._step_when("reconfigure_when", user_input, dict(self._get_reconfigure_subentry().data))
