<p align="center">
  <img src="docs/banner.png" alt="Cam Profile" width="520">
</p>

# Cam Profile für Home Assistant

[![Tests](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/tests.yaml/badge.svg)](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hassfest.yaml)
[![HACS](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hacs.yaml/badge.svg)](https://github.com/RedDragonNode/ha-cam-profile/actions/workflows/hacs.yaml)

**Aufnahme-Profile für die Kameras, die du schon in Home Assistant hast.** Du richtest keine Kameras neu ein: Im Profil wählst du einfach Kamera-Entities aus beliebigen Integrationen (Reolink, Ctronics, ONVIF, Generic Camera …). Eine Kamera kann in beliebig vielen Profilen stehen.

Ein Profil bestimmt, **wohin** welche Kameras aufnehmen und **wann**: durchgehend, nur nachts, bei Bewegung oder von Hand. Aufgenommen wird der RTSP-Stream direkt in eine Datei, **ohne Neukodierung** (ffmpeg `-c copy`). Das braucht kaum CPU und keine GPU.

| Baustein | Aufgabe |
|---|---|
| Integration `cam_profile` | Profile, Auslöser, Zeitfenster, Steuerung und Sensoren |
| App `cam_profile_recorder` | schreibt die Streams auf die Platte, überwacht sie und startet bei Abbruch neu |

```
Integration (Profile)  ──HTTP──▶  App „Cam Profile Recorder“  ──ffmpeg -c copy──▶  Kamera (RTSP)
                                   pro Kamera ein ffmpeg, Neustart bei Stillstand               │
                                                                                                ▼
                                                                         /media/Aufnahmen/Überwachung/Treppe/…
```

## Aufnahme-Profile

Anlegen unter **Einstellungen → Geräte & Dienste → Cam Profile → Aufnahme-Profil hinzufügen**. Das Formular hat zwei Schritte.

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
| Von / bis | Zeitfenster, auch über Mitternacht |
| Sonne | nur bei Tag oder nur bei Nacht (`sun.sun`) |

Regeln:

- **Nur Zeitfenster oder Sonne, kein Auslöser:** nimmt im Fenster durchgehend auf (z. B. „bei Nacht“).
- **Auslöser (und Fenster):** nimmt auf, solange ein Auslöser „an“ ist und das Fenster offen ist.
- **Nichts angegeben:** nur von Hand, über den Schalter **Von Hand aufnehmen** am Gerät des Profils oder über die Dienste unten.
- **Eine Kamera nimmt nie in zwei Profilen gleichzeitig auf.** Wer zuerst kommt, behält sie, das andere Profil nimmt ohne sie auf und meldet sie als „busy“. Der Recorder erkennt eine Kamera an ihrer ID, bei Cam Profile ist das die Entity-ID (`camera.…`). Spricht eine andere Integration denselben Recorder mit eigenen Kamera-IDs an (zum Beispiel Cam Recorder Profile), erkennt er dieselbe Kamera dort nicht wieder und würde sie doppelt aufnehmen.
- Von Hand gestartete Profile laufen bis zum Stopp. Nach einem Neustart von Home Assistant werden laufende Profile wieder erkannt. Ein von Hand gestartetes Profil mit Auslöser folgt danach wieder seinem Auslöser.
- Wird eine Kamera-Entity umbenannt, ziehen die Profile automatisch mit.

## Entities und Dienste

| Entity | Wo |
|---|---|
| `binary_sensor` **Aufnahme** je Profil | am Gerät „Profil …“ (Ordner, seit wann, Kameras) |
| `switch` **Von Hand aufnehmen** | am Gerät „Profil …“, nur bei Profilen ohne Auslöser und ohne Zeitfenster. Ein: Aufnahme starten, aus: stoppen. Bei Profilen mit Auslöser oder Zeitfenster gibt es ihn nicht, denn der Auslöser würde ihn sofort wieder umlegen |
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

**Services:** `cam_profile.start_profile` and `cam_profile.stop_profile` (response lists started and skipped cameras). Profiles without triggers and time window also get a **Record manually** switch on the profile's device. Renamed camera entities are followed automatically, and a profile the recorder ends unexpectedly raises a repair issue.

**Install:** add `https://github.com/RedDragonNode/ha-cam-profile` as an app repository (App Store → ⋮ → Repositories) and install *Cam Profile Recorder* with an `api_key` of at least 12 characters. Then add the same URL as a custom *Integration* repository in HACS, download *Cam Profile*, restart Home Assistant and add the integration with the app's address (`http://<hostname>:8099`, hostname from the app's Info page) and key.

## Lizenz / License

[MIT](LICENSE)
