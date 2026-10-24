<p align="center">
  <img src="docs/banner.png" alt="Cam Profile" width="520">
</p>

# Cam Profile für Home Assistant

[![Tests](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/tests.yaml/badge.svg)](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hassfest.yaml)
[![HACS](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hacs.yaml/badge.svg)](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hacs.yaml)

**Aufnahme-Profile für die Kameras, die du schon in Home Assistant hast.** Du richtest keine Kameras neu ein: Im Profil wählst du einfach Kamera-Entities aus beliebigen Integrationen (Reolink, Ctronics, ONVIF, Generic Camera …). Eine Kamera kann in beliebig vielen Profilen stehen.

Ein Profil bestimmt, **wohin** welche Kameras aufnehmen und **wann**: durchgehend, nur nachts, an bestimmten Wochentagen, bei Bewegung oder von Hand. Aufgenommen wird der RTSP-Stream direkt in eine Datei, **ohne Neukodierung** (ffmpeg `-c copy`). Das braucht kaum CPU und keine GPU.

| Baustein | Aufgabe |
|---|---|
| Integration `cam_profile` | Profile, Auslöser, Zeiten je Wochentag, Steuerung und Sensoren |
| App `cam_profile_recorder` | schreibt die Streams auf die Platte, überwacht sie und startet bei Abbruch neu |

```
Integration (Profile)  ──HTTP──▶  App „Cam Profile Recorder“  ──ffmpeg -c copy──▶  Kamera (RTSP)
                                   pro Kamera ein ffmpeg, Neustart bei Stillstand               │
                                                                                                ▼
                                                                         /media/Aufnahmen/Überwachung/Treppe/…
```

## Aufnahme-Profile

Anlegen unter **Einstellungen → Geräte & Dienste → Cam Profile → Aufnahme-Profil hinzufügen**. Das Formular hat drei Schritte. Die ersten beiden enden mit **Weiter**, erst der letzte mit **Profil speichern**. Home Assistant bietet in Formularen keine Zurück-Taste, ein Schritt lässt sich nur durch Schließen und neu Öffnen wiederholen.

**Schritt 1: Wohin und welche Kameras**

| Feld | Bedeutung |
|---|---|
| Name | z. B. `Treppe` oder `bei Nacht` |
| Zielordner | Auswahl aus den Ordnern des Recorders, eigene Namen mit Unterordner (`Überwachung/Treppe`) werden angelegt |
| Kameras | beliebig viele `camera.*`-Entities aus allen Integrationen |
| Dateinamen-Muster | `{cam}` Name der Kamera, `{short}` Kürzel, `{profile}` Name des Profils, dazu Datum und Zeit mit `%CCYY %MM %DD %hh %mm %ss`. Standard: `{cam} %CCYY-%MM-%DD %hh-%mm-%ss` |

Der Name der Kamera ist der Name ihres Geräts, sonst der der Entity. Haben zwei Kameras eines Geräts denselben Namen (Haupt- und Substream), hängt die Integration den Entity-Namen an, damit sie nicht dieselbe Datei beschreiben. Nimm für Aufnahmen am besten den **Hauptstream** in voller Auflösung.

**Schritt 2: Wann**

| Feld | Bedeutung |
|---|---|
| Auslöser | Bewegungsmelder, Schalter oder Sensor (mehrere möglich): irgendeiner „an“ = aufnehmen |
| Nachlauf | Sekunden, die nach „aus“ weiter aufgenommen wird |
| Höchstdauer | Minuten pro Aufnahme (0 = unbegrenzt). Danach geht es erst nach „aus → an“ weiter |
| Sonne | nur bei Tag oder nur bei Nacht (`sun.sun`) |

**Schritt 3: An welchen Tagen und wann**

| Feld | Bedeutung |
|---|---|
| Montag … Sonntag aufnehmen | ein Schalter je Wochentag, standardmäßig alle an. Ein ausgeschalteter Tag nimmt nicht auf, sind **alle aus**, nimmt das Profil an keinem Tag von allein auf |
| Montag … Sonntag: Zeiten | optional, je Tag **mehrere Zeiten**, zum Beispiel `08:00-12:00, 18:00-22:00` (mehrere durch Komma). Leer heißt ganztägig |

Zeiten dürfen über Mitternacht gehen (`22:00-06:00`), das Fenster gehört dann zu dem Tag, an dem es beginnt (Freitag 22:00 bis 06:00 gilt um 03:00 nachts noch für den Freitag). `24:00` ist als Ende erlaubt.

Regeln:

- **Nur Wochentage, Zeiten oder Sonne, kein Auslöser:** nimmt in dieser Zeit durchgehend auf (z. B. „bei Nacht“ oder „samstags 08–10 Uhr“).
- **Auslöser (und Einschränkung):** nimmt auf, solange ein Auslöser „an“ ist und Wochentag, Zeiten und Sonne passen. Alles zusammen muss passen.
- **Nichts angegeben:** nur von Hand, über den Schalter **Von Hand aufnehmen** am Gerät des Profils oder über die Dienste unten. Wochentage, Zeiten und Sonne lassen sich später auf der Geräteseite überschreiben, siehe unten.
- **Eine Kamera nimmt nie in zwei Profilen gleichzeitig auf.** Wer zuerst kommt, behält sie, das andere Profil nimmt ohne sie auf und meldet sie als „busy“. Der Recorder erkennt eine Kamera an ihrer ID, bei Cam Profile ist das die Entity-ID (`camera.…`). Spricht eine andere Integration denselben Recorder mit eigenen Kamera-IDs an (zum Beispiel Cam Recorder Profile), erkennt er dieselbe Kamera dort nicht wieder und würde sie doppelt aufnehmen.
- Von Hand gestartete Profile laufen bis zum Stopp. Nach einem Neustart von Home Assistant werden laufende Profile wieder erkannt. Ein von Hand gestartetes Profil mit Auslöser folgt danach wieder seinem Auslöser.
- Wird eine Kamera-Entity umbenannt, ziehen die Profile automatisch mit.

## Anlege-Werte und Überschreiben

Was du beim Anlegen einträgst (und später über das Zahnrad des Profils änderst), sind die **Anlege-Werte** des Profils. Sie bleiben gespeichert, egal was du danach auf der Geräteseite einstellst.

Auf der Geräteseite des Profils (**Einstellungen → Geräte & Dienste → Cam Profile → Profil …**) steht im Kasten **Konfiguration**:

| Einstellung | Entity |
|---|---|
| Nachlauf nach „aus“ (Sekunden) | `number` |
| Höchstdauer pro Aufnahme (Minuten, 0 = unbegrenzt) | `number` |
| 1 Montag bis 7 Sonntag aufnehmen | sieben `switch`, alle aus heißt: an keinem Tag |
| 1 Montag Zeiten bis 7 Sonntag Zeiten (zum Beispiel `08:00-12:00, 18:00-22:00`, leer = ganztägig) | sieben `text` |
| Sonne: egal, nur bei Tag, nur bei Nacht | `select` |
| Auf Anlege-Werte zurücksetzen | `button` |

- Die Entities zeigen den **geltenden Wert**. Änderst du ihn, **überschreibst** du damit nur den Anlege-Wert, der im Profil gespeicherte Wert bleibt unverändert. Die Attribute der Entity nennen ihn (`creation_value`) und ob überschrieben wird (`overridden`).
- Überschreibungen gelten sofort, ohne Neuladen, und überleben Neustarts. Sie liegen getrennt von den Profilen, das Zahnrad des Profils ändert sie nicht. Ändert das Zahnrad einen überschriebenen Wert, gilt weiter die Überschreibung, bis du **Auf Anlege-Werte zurücksetzen** drückst.
- Alle sieben Wochentage heißen jeden Tag. Sind **alle aus**, nimmt das Profil an keinem Tag von allein auf (Pause), von Hand und über die Dienste lässt es sich weiter starten. Im Formular des Profils gilt dasselbe: ein Schalter je Tag, alle aus heißt an keinem Tag. Die Zeiten werden als Text eingetragen, unlesbare Eingaben lehnt Home Assistant mit einer Meldung ab. Das Attribut `overridden` zeigt je Tag, ob er vom Anlege-Wert abweicht.
- Zielordner, Dateinamen-Muster, Kameras und Auslöser lassen sich nur im Profil selbst ändern.
- Schränkt eine Überschreibung ein Profil **ohne Auslöser** ein (Wochentage, Zeiten oder Sonne), nimmt es von allein in dieser Zeit auf und der Schalter „Von Hand aufnehmen“ entfällt. Nach dem Zurücksetzen ist er wieder da. Dafür lädt sich die Integration kurz neu.
- Die globalen Grundeinstellungen aus Version 0.3 (Zahnrad der Integration) gibt es nicht mehr. Ihre Werte wurden beim Update in die Profile übernommen, damit sich nichts ändert. Das Zeitplan-Feld aus Version 0.5 und Von/Bis aus Version 0.6 entfallen, die Zeiten je Wochentag ersetzen sie. Eine vorhandene Von/Bis-Zeit wurde beim Update zu den Zeiten jedes Tages, der keine eigenen hatte.

## Entities und Dienste

| Entity | Wo |
|---|---|
| `binary_sensor` **Aufnahme** je Profil | am Gerät „Profil …“ (Ordner, seit wann, Kameras) |
| `switch` **Von Hand aufnehmen** | am Gerät „Profil …“, nur bei Profilen ohne Auslöser und ohne Einschränkung (Wochentage, Zeiten, Sonne). Ein: Aufnahme starten, aus: stoppen. Bei Profilen mit Auslöser oder Einschränkung gibt es ihn nicht, denn der Auslöser würde ihn sofort wieder umlegen |
| `number`, `time`, `select`, `switch`, `button` **Konfiguration** | am Gerät „Profil …“: die Einstellungen zum Überschreiben (siehe oben) |
| `binary_sensor` **Aufnahme** je Kamera | am Gerät der Kamera aus ihrer eigenen Integration, mit den Profilen, in denen sie steht |
| `binary_sensor` **Recorder erreichbar**, `sensor` **Status**, `sensor` **freier Speicher** | am Gerät „Cam Profile“ |

| Dienst | Zweck |
|---|---|
| `cam_profile.start_profile` | Profil von Hand starten (läuft bis zum Stopp). Antwort: gestartete und übersprungene Kameras |
| `cam_profile.stop_profile` | Profil beenden |

Beendet der Recorder ein Profil unerwartet (Absturz, Platte voll), erscheint unter **Einstellungen → System → Reparaturen** ein Hinweis mit dem Grund.

## Installation

### 1. App (früher „Add-on“)

1. Im App-Store oben rechts **⋮ → Repositories** wählen und `https://github.com/RedDragonNode/ha-cam-profile` hinzufügen.
2. **Cam Profile Recorder** installieren, unter *Konfiguration* einen `api_key` setzen (mindestens 12 Zeichen) und starten.
3. Auf der Seite der App unter *Info* den **Hostnamen** ablesen. Die Adresse für die Integration lautet `http://<Hostname>:8099`.

Setze `aufnahme_ordner` auf eine eingehängte Platte, sonst schreibt die App auf die Systemplatte. Alle Optionen stehen in der [App-Dokumentation](cam_profile_recorder/DOCS.md).

### 2. Integration (HACS)

1. HACS öffnen, oben rechts **Benutzerdefinierte Repositories** wählen.
2. `https://github.com/RedDragonNode/ha-cam-profile` als Typ **Integration** hinzufügen.
3. **Cam Profile** herunterladen und Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste** die Integration hinzufügen, Adresse und Schlüssel der App eintragen.

Die Verbindung lässt sich später unter *Verbindung ändern* anpassen. Lehnt die App den Schlüssel ab, fragt Home Assistant nach einem neuen.

## Fehlersuche

- **„Die App ist nicht erreichbar“.** Läuft die App, und stimmt der Hostname von der Seite der App? Der Port ist immer `8099`.
- **Eine Kamera wird übersprungen.** Die Antwort von `start_profile` nennt den Grund: `busy` (nimmt schon in einem anderen Profil auf), `missing` (die Entity gibt es nicht mehr) oder `no_stream` (die Kamera liefert keine Stream-Adresse, z. B. ohne RTSP).
- **Es entsteht keine Datei.** Prüfe das Protokoll der App. Mit `ffmpeg_loglevel: info` zeigt es die genaue ffmpeg-Ausgabe.

## Entwicklung

```bash
pip install -r requirements_test.txt
pytest
```

Icon und Banner erzeugt `python tools/make_brand.py` (nur Pillow). Der Aufnahme-Kern der App stammt aus der Vorgängerversion *Cam Recorder Profile* und hat dieselbe HTTP-Schnittstelle.

---

# Cam Profile for Home Assistant (English)

**Recording profiles for the cameras you already have in Home Assistant.** You do not add cameras again: in a profile you pick camera entities from any integration, and one camera can be part of any number of profiles.

A profile decides **where** which cameras record and **when**: continuously, at night only, on motion or by hand. The RTSP stream is written straight to a file **without re-encoding** (ffmpeg `-c copy`), so it needs hardly any CPU and no GPU.

- **Integration `cam_profile`:** profiles, triggers, time windows, control and sensors.
- **App `cam_profile_recorder`:** writes the streams to disk, supervises them and restarts on stalls.

**Profile settings:** target folder, cameras, file name pattern (`{cam}`, `{short}`, `{profile}`, `%CCYY %MM %DD %hh %mm %ss`), triggers (any "on" records), run-on time, maximum length, time window and day/night. Without triggers and window a profile only starts by hand. A camera never records in two profiles at once, the first profile to start keeps it.

**Weekdays and times:** the form has a switch per weekday (all on by default, all off means no day, same as on the device page) and optional times per day, for example `08:00-12:00, 18:00-22:00` (several separated by commas, also across midnight). A day without times records all day. The form has three steps, the first two end with Next, only the last one saves (Save profile).

**Creation values and overrides:** what you enter when you create a profile (or change later with the profile's gear) are its creation values. On the profile's device page, under *Configuration*, you can override run-on, maximum length, time window, weekdays (seven switches, all off means no day), the times per weekday (seven text fields) and sun. The page shows the value in effect, changing it only overrides the creation value, which stays stored unchanged. A button resets everything to the creation values. Overrides apply at once and survive restarts. An override that restricts a profile without triggers makes it record on its own and removes its manual switch until you reset it.

**Services:** `cam_profile.start_profile` and `cam_profile.stop_profile` (response lists started and skipped cameras). Profiles without triggers and without a restriction (weekdays, times, sun) also get a **Record manually** switch on the profile's device. Renamed camera entities are followed automatically, and a profile the recorder ends unexpectedly raises a repair issue.

**Install:** add `https://github.com/RedDragonNode/ha-cam-profile` as an app repository (App Store → ⋮ → Repositories) and install *Cam Profile Recorder* with an `api_key` of at least 12 characters. Then add the same URL as a custom *Integration* repository in HACS, download *Cam Profile*, restart Home Assistant and add the integration with the app's address (`http://<hostname>:8099`, hostname from the app's Info page) and key.

## Lizenz / License

[MIT](LICENSE)
