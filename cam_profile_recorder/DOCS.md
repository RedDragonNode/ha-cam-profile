# Cam Profile Recorder

Schreibt die RTSP-Streams der Kameras **ohne Neukodierung** (ffmpeg `-c copy`) in Dateien. Gesteuert wird die App von der
Integration **Cam Profile** (Aufnahme-Profile). Die App selbst hat keine Oberfläche.

## Einrichtung

1. Im App-Store oben rechts **⋮ → Repositories** wählen und `https://github.com/RedDragonNode/ha-cam-profile` hinzufügen.
   Danach erscheint **Cam Profile Recorder** im Store und lässt sich installieren.
   (Alternativ den Ordner `cam_profile_recorder` aus dem Repository nach `/addons/cam_profile_recorder` auf dem HA-Server kopieren,
   zum Beispiel über die Samba-Freigabe `addons`.)
2. Unter **Konfiguration** einen **api_key** setzen (mindestens 12 Zeichen, frei wählbar) und die App starten.
3. In der Integration **Cam Profile** die Adresse der App und denselben Schlüssel eintragen. Die Adresse zeigt die Seite der
   App unter **Info → Hostname**. Sie lautet `http://<Hostname>:8099`. Bei einer Installation aus `/addons` ist der Hostname
   `local-cam-profile-recorder`.

Die App ist nur im internen Home-Assistant-Netz erreichbar (kein veröffentlichter Port) und verlangt den `api_key`.

## Einstellungen

| Option | Bedeutung |
| --- | --- |
| `api_key` | Zugangsschlüssel zwischen Integration und App |
| `aufnahme_ordner` | Stammordner (voller Pfad, z. B. `/media/Aufnahmen` auf einer externen Platte). Darunter legen die Profile ihre Ordner an |
| `container` | `mp4` (fragmentiert, absturzsicher) oder `mkv` |
| `audio` | `aac` (G.711 der Kamera wird nach AAC umgewandelt, minimale Last), `copy` oder `none` |
| `stillstand_sekunden` | Wenn so lange keine Daten geschrieben werden, verbindet sich die App neu mit der Kamera (neue Datei „… Teil 2“) |
| `mindest_frei_gb` | Der Start wird verweigert und laufende Aufnahmen enden, wenn weniger Platz frei ist |
| `wallclock_zeitstempel` | Nur aktivieren, wenn eine Kamera fehlerhafte Zeitstempel liefert |
| `ffmpeg_loglevel` | `warning` (Standard). Bei Problemen `info` oder `verbose`, dann zeigt das Protokoll die genaue ffmpeg-Ausgabe |
| `video_tag` | `hvc1` setzt HEVC in MP4 so, dass Windows- und Apple-Player es abspielen. Wirkt nur bei MP4 und nur bei HEVC |

Ohne eingehängte externe Platte würde die App auf die Systemplatte schreiben. `mindest_frei_gb` schützt davor.
Richtwert: 5 Kameras ≈ 6 GB pro Stunde.

## Dateien

Pro Aufnahme entsteht neben den Videos eine `<Profil> <Datum Zeit>.json` mit Start und Ende jeder Kamera und jedes Teils (UTC).
Damit lassen sich die Kameras später zeitgenau synchronisieren.

## Schnittstelle

`POST /start` nimmt optional `profile`, `POST /stop` optional `profile` (ohne Angabe beendet es alle Profile, deshalb schickt die
Integration immer ihr Profil mit). Jedes Profil hat einen eigenen Ordner, eine eigene Sidecar-Datei und einen eigenen
Speicherwächter. Eine Kamera-ID kann nie in zwei Profilen gleichzeitig aufnehmen, der Start wird dann mit „Kamera nimmt bereits in
einem anderen Profil auf“ abgelehnt. `GET /status` liefert unter `profile` den Stand je Profil.
