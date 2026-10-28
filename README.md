# iPod Audio Rescue — Audiodateien vom alten iPod retten, ordnen und optional als MP3 sichern

**Ein Open-Source-How-to zum Nachmachen:** Windows 11 → WSL2/Ubuntu → iPod schreibgeschützt auslesen → Originaldateien sichern → Audiosammlung anhand von Tags und iTunesDB rekonstruieren → bei Bedarf eine separate MP3-Bibliothek erstellen.

Der Leitfaden entstand bei der erfolgreichen Rettung eines **iPod touch der 1. Generation mit iPhone OS 1.1.5**. Die vollständige Methode kommt mit frei verfügbaren Werkzeugen aus; es sind **weder iTunes-Synchronisation noch ein Firmware-Update, Jailbreak oder ein KI-Dienst nötig**.

> [!IMPORTANT]
> **Erst sichern, dann sortieren, erst danach konvertieren.** Niemals auf dem iPod selbst umbenennen, löschen oder Audiodateien vom Gerät synchronisieren. Originaldaten und iTunesDB unverändert archivieren. Für iPhone OS 1.x benötigen wir eine isolierte, bewusst unsichere **SSLv3**-Verbindung ausschließlich zum lokalen USB-Gerät. Andere iPod-Generationen/Firmwares erfordern möglicherweise einen anderen Verbindungsweg.

## Der Weg in fünf Schritten

| Schritt | Was wir erreichen | Ausführliches How-to |
| --- | --- | --- |
| **1. Ausgangslage verstehen** | Modell/Firmware und Grenzen feststellen; Schreibzugriffe vermeiden; Platz für zwei Kopien planen | [Gesamter Leitfaden: Grundlagen und Sicherung](docs/END-TO-END-RECOVERY.md) |
| **2. Windows/WSL einrichten** | Ubuntu 24.04 in WSL2, usbipd-win, usbmuxd, ifuse; bei OS 1.x SSLv3-Kompatibilität in einer **lokalen** Build-Umgebung | [WSL und USB einrichten](docs/WSL-SETUP.md) · [Legacy-SSLv3-Build](docs/IPOD1-SSLV3-RESCUE.md) |
| **3. Originaldaten extrahieren** | Schreibgeschützter AFC-Mount, vollständiges rsync-Rohbackup **inklusive iTunesDB**, SHA-256-Prüfung und zweite Sicherung | [Extraktion und Backup](docs/END-TO-END-RECOVERY.md#2-rohbackup-und-pruefsummen) |
| **4. Audiodateien rekonstruieren** | Metadaten (z. B. Titel, Sprecher/Interpret, Album) aus Dateitags und iTunesDB zuordnen; unklare Fälle manuell prüfen; byteidentischen strukturierten Export erstellen | [iTunesDB und Rekonstruktion](docs/END-TO-END-RECOVERY.md#4-bibliothek-rekonstruieren) |
| **5. MP3-Kompatibilitätskopie erstellen** | AAC/M4A mit LAME V0 kodieren, vorhandene MP3s kopieren, bei beschädigten Titeln kontrolliert nachfassen, alles protokollieren | [Konvertierung, Fortsetzen und Prüfen](docs/MP3-CONVERSION.md) |

**Empfohlener Einstieg:** [Ausführliche Schritt-für-Schritt-Anleitung](docs/END-TO-END-RECOVERY.md). Das README dient bewusst als Wegweiser statt als zweite, leicht abweichende Befehlsammlung.

## Was brauche ich?

- Einen noch erkennbaren iPod und ein funktionierendes USB-Kabel; gegebenenfalls Zeit zum Laden.
- Einen PC mit **Windows 11, WSL2 und Ubuntu 24.04 LTS** (so wurde es erfolgreich getestet). Ein nativer Linux-Rechner ist denkbar, aber diese Anleitung wurde dafür nicht Ende-zu-Ende getestet.
- Ausreichend freien Platz für **Rohkopie**, **zweite physische Sicherung**, **rekonstruierte Audiodateien** und optional **MP3-Zweitbibliothek**.
- Open-Source-Tools: **usbipd-win, libimobiledevice, ifuse, GnuTLS, rsync, Python 3, Mutagen, FFmpeg/LAME**.
- Grundkenntnisse, um Kommandos in PowerShell und Ubuntu-Terminal auszuführen und lokale Verzeichnispfade anzupassen.

## Nachprüfbarer Abschluss

Der im Leitfaden beschriebene Ablauf wurde an einem echten Legacy-iPod erfolgreich ausgeführt: Der Rohbestand wurde gesichert, die Audiosammlung rekonstruiert und eine separate MP3-Kompatibilitätskopie erstellt. **Beide strukturierten Ausgabestufen wurden unabhängig mit SHA-256 gegen ihre jeweiligen Quelldateien geprüft.** Konkrete Bestandszahlen, Dateigrößen und private Audiotitel sind bewusst nicht Bestandteil dieser öffentlichen Dokumentation.

Die Prüfprogramme stehen allen zur Verfügung: [`verify_ipod_export.py`](scripts/verify_ipod_export.py) für den byteidentischen Audioexport und [`verify_mp3_conversion.py`](scripts/verify_mp3_conversion.py) für die fertige MP3-Bibliothek.

## Was ist bewusst nicht enthalten?

Kein iPod-Restore, keine iTunes-Synchronisation, kein Jailbreak, kein DRM-Bypass und keine zweifelhaften Web-Konverter. Die nicht verwendete PowerShell-Kopiervariante wurde aus dem Projekt entfernt; der **tatsächlich erprobte Weg** führt über WSL/Linux mit read-only ifuse und rsync.

Die Werkzeuge sind bewusst offline nutzbar. Ein KI-Assistent kann bei der Sichtung einzelner Metadaten helfen, ist aber **keine Voraussetzung** und darf unbekannte Tracknummern nicht erfinden.

## Quellcode und Dokumente

- [WSL und USB](docs/WSL-SETUP.md)
- [SSLv3 für iPhone OS 1.1.5](docs/IPOD1-SSLV3-RESCUE.md)
- [Rohbackup, Metadaten, Export, SHA-256](docs/END-TO-END-RECOVERY.md)
- [AAC/M4A → MP3, fehlertolerante Fortsetzung](docs/MP3-CONVERSION.md)
- [Alle Python- und Shell-Werkzeuge](scripts/) · [Automatische Code-Tests](.github/workflows/validate-python.yml)
- **[Abschließender Review: Vollständigkeit, Nachvollziehbarkeit, Plausibilität](docs/REVIEW.md)**

**Projektcharakter:** Eine nachvollziehbar dokumentierte, erfolgreich angewandte Einzelfallrettung – keine Garantie für alle Modelle, Firmwares, defekten Speichermedien oder Kopierschutz-Varianten. Prüfe den Code und halte deine Originale immer separat.
