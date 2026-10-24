"""Konstanten der Integration Cam Profile."""

from __future__ import annotations

DOMAIN = "cam_profile"

SUBENTRY_PROFILE = "profile"

# --- Verbindung zum Add-on (config_entry.data) -----------------------------------
CONF_RECORDER_URL = "recorder_url"
CONF_RECORDER_KEY = "recorder_key"
DEFAULT_RECORDER_URL = "http://local-cam-profile-recorder:8099"

# --- Aufnahme-Profil (Subentry-Daten) --------------------------------------------
CONF_FOLDER = "folder"  # "Haupt" oder "Haupt/Unter"
CONF_CAMS = "cams"  # Liste von Kamera-Entities (camera.*) aus beliebigen Integrationen
CONF_PATTERN = "pattern"
CONF_TRIGGERS = "triggers"  # Liste von Entities, "an" = aufnehmen
CONF_AFTER = "after_seconds"
CONF_MAX_MINUTES = "max_minutes"
CONF_TIME_FROM = "time_from"
CONF_TIME_TO = "time_to"
CONF_SUN = "sun"
CONF_WEEKDAYS = "weekdays"  # Liste aus WEEKDAYS, leer oder alle sieben = jeden Tag

SUN_ANY = ""
SUN_DAY = "day"
SUN_NIGHT = "night"

DEFAULT_PATTERN = "{cam} %CCYY-%MM-%DD %hh-%mm-%ss"

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Felder, die als Grundeinstellung (config_entry.options) gelten und im Profil überschrieben werden können.
# Fehlt ein Feld im Profil, gilt die Grundeinstellung, fehlt auch die, gilt der eingebaute Wert.
DEFAULTABLE = (
    CONF_FOLDER,
    CONF_PATTERN,
    CONF_AFTER,
    CONF_MAX_MINUTES,
    CONF_TIME_FROM,
    CONF_TIME_TO,
    CONF_WEEKDAYS,
    CONF_SUN,
)

# Version 1.2: Profile speichern nur noch, was sie selbst überschreiben
MINOR_VERSION = 2

SERVICE_START = "start_profile"
SERVICE_STOP = "stop_profile"
ATTR_PROFILE = "profile"

# Abstand, in dem der Zustand des Add-ons abgefragt wird
POLL_SECONDS = 15
# Abstand, in dem Profile gegen ihre Auslöser abgeglichen werden (zusätzlich zu jeder Zustandsänderung)
TICK_SECONDS = 20
