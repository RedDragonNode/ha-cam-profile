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
CONF_WEEKDAYS = "weekdays"  # Tage mit Aufnahme (Liste aus WEEKDAYS), fehlt = jeden Tag, leer = an keinem
CONF_SCHEDULE = "schedule"  # optional: Entity eines HA-Zeitplans (schedule.*), aufgenommen wird bei "on"

SUN_ANY = ""
SUN_DAY = "day"
SUN_NIGHT = "night"

DEFAULT_PATTERN = "{cam} %CCYY-%MM-%DD %hh-%mm-%ss"

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Felder, die auf der Geräteseite des Profils überschrieben werden können. Die Anlege-Werte im Profil bleiben dabei
# unverändert, die Überschreibungen liegen getrennt im Speicher der Integration.
OVERRIDABLE = (
    CONF_AFTER,
    CONF_MAX_MINUTES,
    CONF_TIME_FROM,
    CONF_TIME_TO,
    CONF_WEEKDAYS,
    CONF_SUN,
)

# Felder, die Version 0.3 als globale Grundeinstellung in config_entry.options kannte (nur für die Migration)
LEGACY_DEFAULTS = (CONF_FOLDER, CONF_PATTERN, *OVERRIDABLE)

# Version 1.3: keine globalen Grundeinstellungen mehr, Profile speichern wieder ihre Anlege-Werte selbst
# Version 1.4: leere Wochentage heißen an keinem Tag (vorher jeden Tag), Profile speichern alle sieben
MINOR_VERSION = 4

STORAGE_VERSION = 1

SERVICE_START = "start_profile"
SERVICE_STOP = "stop_profile"
ATTR_PROFILE = "profile"

# Abstand, in dem der Zustand des Add-ons abgefragt wird
POLL_SECONDS = 15
# Abstand, in dem Profile gegen ihre Auslöser abgeglichen werden (zusätzlich zu jeder Zustandsänderung)
TICK_SECONDS = 20
