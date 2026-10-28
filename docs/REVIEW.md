# Review: Vollständigkeit, Nachvollziehbarkeit und Plausibilität

[← Projektübersicht](../README.md)

**Reviewstand:** 28. Oktober 2026, nach dem Abschluss der realen Rettung und der Überarbeitung als Open-Source-How-to.

## 1. Dokumentation und roter Faden

| Bereich | Prüfung | Ergebnis |
| --- | --- | --- |
| Ausgangslage / Schutzziele | iPod-Typ und Firmware, Gerätezugriff, Originalschutz, Grenzen erklärt | Erfüllt |
| Windows-/WSL-Vorbereitung | WSL2, Ubuntu 24.04, USB-Passthrough, erforderliche Pakete | Erfüllt |
| Altes SSLv3 | GnuTLS-/libimobiledevice-Quellcode, Patch, isolierte Laufzeit, Handshake-Nachweis | Erfüllt **nur für getestete Firmware** |
| Datenextraktion | Read-only-Mount, vollständiger rsync, iTunesDB, SHA-256, physisch unabhängige Kopie | Erfüllt als reproduzierbare Anleitung |
| Rekonstruktion | Tags, iTunesDB-Abgleich, manuelle CSV-Freigabe, Kollisionsprüfung, SHA-256-Export | Erfüllt; unbekannte Metadaten benötigen Handarbeit |
| Konvertierung | LAME V0, MP3-Direktkopie, Checkpoints, automatischer strenger/toleranter Versuch, Fehlerprotokolle | Erfüllt als dokumentierter Prozess |
| Abschlussprüfung | Zusätzlicher unabhängiger MP3-SHA-256-Verifier samt Wiederholbarkeitsanleitung | Ergänzt |
| Öffentlichkeit/Datenschutz | Keine Original-Medien, privaten Dateilisten, iTunesDB, Schlüssel oder UDIDs im Repository | Beim Review keine derartigen Artefakte im Repo-Baum festgestellt |
| Nicht verwendetes PowerShell-Exportverfahren | Entfernt, alle Dokumente auf tatsächlich ausgeführten Linux-/WSL-Weg vereinheitlicht | Erfüllt |

## 2. Sachliche Konsistenz und erfolgreiche Dateiprüfung

Die privaten Abschluss-CSV-Dateien wurden zur Bestätigung des Konvertierungsprozesses ausgewertet, aber **nicht** im öffentlichen Repository abgelegt. Der Abschluss ist in mehreren Stufen nachvollziehbar:

| Nachweis | Ergebnis |
| --- | --- |
| Audio-Exportmanifest gegen Rohbackup | Unabhängiger SHA-256-Vergleich erfolgreich (`PASS`) |
| MP3-Konvertierungsmanifest und Checkpoints | Untereinander konsistente Quelldatei-/Zieldatei-Zuordnung |
| Rettungsprotokoll | Mit dem zugehörigen Konvertierungsmanifest abgeglichen |
| **MP3-Abschlussprüfung gegen echte Dateien** | **Erfolgreich (`PASS`)**: MP3-Zieldateien **und** die zugehörigen Audio-Quelldateien erneut per SHA-256 verglichen |
| Umgang mit Decoderfehlern | Automatischer zweiter Versuch wird gekennzeichnet; akustische Hörkontrolle bleibt erforderlich |

**Datenschutz:** Individuelle Datei- und Titelanzahlen, Bibliotheksgrößen, Namen und die privaten Ergebnis-CSV-Dateien sind für den allgemeinen Leitfaden nicht erforderlich und werden daher **nicht veröffentlicht**. Ein unabhängiger Nachweis auf einem eigenen Rechner ist mit folgendem Aufruf reproduzierbar:

```bash
cd "$HOME/iPod-Audio-Rescue"
python3 scripts/verify_mp3_conversion.py \
  --mp3-root "$HOME/Audiodateien-MP3" \
  --source "$HOME/Audiodateien-Rekonstruiert" \
  --strict
```

Die Pfade sind Beispiele und müssen für die jeweilige Bibliothek angepasst werden. Die SHA-256-Prüfung belegt Dateiintegrität, nicht Klangqualität. Die ursprüngliche strukturierte Bibliothek wurde nach ihrer damaligen vollständigen Verifikation einmal gezielt um eine unlesbare Datei bereinigt; dieser spätere Zustand ist vom damaligen Verifikationsstand zu unterscheiden.

## 3. Code-Review und verbleibende Grenzen

- **Originalschutz:** Rohbackup und rekonstruiertes Audioarchiv bleiben getrennte Quellen, MP3-Ausgaben werden nur unter neuem Ziel erzeugt. Keine Aufrufe von Restore/Sync/Erase.
- **Datei-/Pfadsicherheit:** Die Export-/Verifikationsskripte prüfen relative Pfade, Zielkollisionen (Windows case-insensitive), Symlinks und vermeiden Überschreiben.
- **Metadaten:** Der iTunesDB-Parser ist ein begrenzter Legacy-Parser, kein Formatdetektor für alle Generationen. Albumgruppierungen sind heuristisch und müssen vor der CSV-Freigabe geprüft werden. Fallbezogene, hartcodierte Album-/Videonamen wurden aus dem allgemeinen Reconciler entfernt.
- **Rettungskonvertierung:** Der zweite FFmpeg-Versuch toleriert beschädigte AAC-Daten, repariert sie aber nicht. Der maximal zulässige Zeitunterschied beträgt 2 Sekunden. Die fertige MP3 kann hörbare Störungen enthalten; jede `recovered_aac_to_mp3`-Datei sollte angehört werden.
- **Checkpoint-Performance:** Bei Wiederaufnahme werden bereits protokollierte MP3s nicht erneut kodiert. Standardmäßig erfolgt eine schnelle Pfad-/Größenprüfung statt einer vollständigen erneuten Hashprüfung. Für stärkere Prüfung gibt es `--audit-existing` und den unabhängigen Abschluss-Verifier.
- **Keine Qualitätsgarantie:** SHA-256 kann keine Beschädigung im Quellmaterial, fehlerhafte Tags, DRM oder fehlende Audioaufnahmen erkennen.
- **Plattformbindung:** Die beschriebene Verbindung wurde nur auf dem konkreten iPhone OS 1.1.5/WSL2-Setup erprobt; weder andere OS-Versionen noch andere Geräte gelten als automatisch kompatibel.
- **Buildsicherheit:** SSLv3 bleibt isoliert auf eine dedizierte lokale USB-Rettungsumgebung. Für GnuTLS-Download muss ein Signaturschlüssel unabhängig authentifiziert werden.
- **Tests:** Eine GitHub-Actions-Konfiguration unter `.github/workflows/validate-python.yml` umfasst Syntaxprüfung, synthetische FFmpeg-/AAC-/MP3-Wiederaufnahme und die unabhängige MP3-Manifestprüfung. **Zum Reviewzeitpunkt war kein erfolgreicher Actions-Lauf nachgewiesen**; die Konfiguration ist deshalb noch keine bestätigte CI-Testabdeckung.

## 4. Empfohlene letzte lokale Kontrolle

```bash
cd "$HOME/iPod-Audio-Rescue"
git pull --ff-only
python3 -m py_compile scripts/*.py
bash -n scripts/install-requirements.sh

# Die realen MP3-Dateien noch einmal direkt von der Platte lesen:
python3 scripts/verify_mp3_conversion.py \
  --mp3-root "/PFAD/ZUR/MP3-BIBLIOTHEK" \
  --source "/PFAD/ZUR/REKONSTRUIERTEN-AUDIODATEIEN" \
  --strict
```

**Wichtig:** `/PFAD/ZUR/...` ausdrücklich durch die **vorhandenen Verzeichnisse** ersetzen. Die Kommandos sind read-only hinsichtlich Audio-/Originaldaten.

Ergänzend ein paar Stücke am Anfang, in der Mitte und am Ende abspielen sowie alle Rettungsfassungen aus `_mp3_conversion_recoveries.csv` anhören. Danach die Original-Sicherung und das strukturierte Archiv auf physisch getrennten Datenträgern aufbewahren.

## Fazit des Reviews

**Als öffentlich nachvollziehbarer, sicherheitsbewusster „Mach es nach“-Leitfaden ist das Projekt vollständig beschrieben.** Der **unabhängige MP3-Datei-Verifier wurde am realen Datenbestand erfolgreich ausgeführt**. Das ändert nichts an den eng definierten Geräte-/Firmwaregrenzen. Ein erfolgreicher GitHub-Actions-Lauf war zum Reviewzeitpunkt noch **nicht** nachgewiesen; die CI-Konfiguration sollte deshalb weiterhin separat bestätigt werden.
