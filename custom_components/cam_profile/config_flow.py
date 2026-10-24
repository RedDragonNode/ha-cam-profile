"""Config-Flow (Verbindung zum Add-on) und Untereinträge (Aufnahme-Profile)."""

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
    DEFAULT_PATTERN,
    DEFAULT_RECORDER_URL,
    DOMAIN,
    SUBENTRY_PROFILE,
    SUN_ANY,
    SUN_DAY,
    SUN_NIGHT,
)
from .recorder_client import RecorderAuthError, RecorderClient, RecorderError

_TEXT = selector.TextSelector()
_SECRET = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))

_SUN_OPTIONS = {"any": SUN_ANY, SUN_DAY: SUN_DAY, SUN_NIGHT: SUN_NIGHT}

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RECORDER_URL, default=DEFAULT_RECORDER_URL): _TEXT,
        vol.Required(CONF_RECORDER_KEY): _SECRET,
    }
)


def _num(hi: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=hi, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement=unit
        )
    )


async def _check_recorder(hass: HomeAssistant, url: str, key: str) -> str | None:
    """Fehlerschlüssel der Verbindungsprüfung, None wenn das Add-on antwortet."""
    try:
        await RecorderClient(async_get_clientsession(hass), url, key).status()
    except RecorderAuthError:
        return "invalid_auth"
    except RecorderError:
        return "cannot_connect"
    return None


class CamProfileConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

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


def _folder_select(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=o, label=o) for o in options],
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class ProfileSubentryFlow(ConfigSubentryFlow):
    """Aufnahme-Profil anlegen oder bearbeiten: Schritt 1 wohin und welche Kameras, Schritt 2 wann."""

    _basics: dict[str, Any]
    _own: str | None = None

    async def _dirs(self, parts: list[str]) -> list[str]:
        """Ordner aus dem Recorder (leer, wenn er nicht erreichbar ist, die Eingabe von Hand bleibt möglich)."""
        data = self._get_entry().data
        try:
            client = RecorderClient(
                async_get_clientsession(self.hass), data[CONF_RECORDER_URL], data[CONF_RECORDER_KEY]
            )
            return await client.list_dirs(parts)
        except RecorderError:
            return []

    async def _folder_options(self) -> list[str]:
        """Alle Ordner bis zwei Ebenen ('Haupt' und 'Haupt/Unter') als eine Auswahlliste."""
        out: list[str] = []
        for main in await self._dirs([]):
            out.append(main)
            out.extend(f"{main}/{sub}" for sub in await self._dirs([main]))
        return out

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
            folder = "/".join(logic.split_path(user_input.get(CONF_FOLDER, "")))
            cams = list(user_input.get(CONF_CAMS) or [])
            if not name or logic.norm(name) in self._taken_names():
                errors[CONF_NAME] = "name_taken"
            if not folder:
                errors[CONF_FOLDER] = "folder_required"
            if not cams:
                errors[CONF_CAMS] = "cams_required"
            if not errors:
                self._basics = {
                    CONF_NAME: name,
                    CONF_FOLDER: folder,
                    CONF_CAMS: cams,
                    CONF_PATTERN: (user_input.get(CONF_PATTERN) or DEFAULT_PATTERN).strip(),
                }
                return await self._step_when(f"{step_id}_when", None, current)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): _TEXT,
                vol.Required(CONF_FOLDER): _folder_select(await self._folder_options()),
                vol.Required(CONF_CAMS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="camera", multiple=True)
                ),
                vol.Optional(CONF_PATTERN, default=DEFAULT_PATTERN): _TEXT,
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, user_input or current),
            errors=errors,
        )

    # -------------------------------------------------------------- Schritt 2
    async def _step_when(
        self, step_id: str, user_input: dict[str, Any] | None, current: Mapping[str, Any]
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            time_from, time_to = user_input.get(CONF_TIME_FROM) or "", user_input.get(CONF_TIME_TO) or ""
            if bool(time_from) != bool(time_to):
                errors[CONF_TIME_TO] = "time_both"
            else:
                sun = user_input.get(CONF_SUN) or "any"
                data = {
                    **self._basics,
                    CONF_TRIGGERS: list(user_input.get(CONF_TRIGGERS) or []),
                    CONF_AFTER: int(user_input.get(CONF_AFTER) or 0),
                    CONF_MAX_MINUTES: int(user_input.get(CONF_MAX_MINUTES) or 0),
                    CONF_TIME_FROM: time_from,
                    CONF_TIME_TO: time_to,
                    CONF_SUN: _SUN_OPTIONS.get(sun, SUN_ANY),
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
                vol.Optional(CONF_SUN, default="any"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(_SUN_OPTIONS),
                        translation_key="sun_window",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        suggested = dict(user_input or current)
        suggested[CONF_SUN] = suggested.get(CONF_SUN) or "any"
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
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
