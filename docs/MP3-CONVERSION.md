# Schritt 5 — Audiodateien als MP3-Kompatibilitätskopie erzeugen

[← Projektübersicht](../README.md) · [Vorher: iPod auslesen und Audiodateien rekonstruieren](END-TO-END-RECOVERY.md)

Nach dem **bytegenau überprüften strukturierten Audioexport** können die AAC/M4A-Dateien in eine separate, vollständig benannte MP3-Bibliothek umgewandelt werden. Bereits vorhandene MP3-Dateien werden **bitidentisch kopiert**. Das Originalarchiv bleibt unangetastet.

## 0. Welche MP3-Bitrate und warum?

- `M4A`/`MP4` sind **Container**, keine Bitratenklasse. Der eigentliche Codec kann AAC, ALAC oder ein anderer sein; das Skript prüft ihn mit `ffprobe`.
- AAC 128 kbit/s wird häufig in einer ungefähren Qualitätsklasse von MP3 160–192 kbit/s eingeordnet; das ist **kein** fester Umrechnungsfaktor.
- **AAC→MP3 ist verlustbehaftete Transkodierung**. Sie kann verlorene Informationen nicht wiederherstellen. Deshalb Original-AAC-Dateien **dauerhaft behalten**.
- Wir verwenden **LAME VBR V0** (`-c:a libmp3lame -q:a 0`). Die MP3-Bitrate wird **nach Audiomaterial**, nicht aus der AAC-Quellbitrate abgeleitet. Sie liegt häufig etwa um 220–260 kbit/s, variiert aber.
- Wer die alten AAC-Dateien ohnehin abspielen kann, braucht **keine** MP3-Konvertierung. Diese Kopie dient der Kompatibilität.

## 1. Voraussetzungen und Zielordner

Die ursprünglichen Audiodateien liegen bereits **offline in der rekonstruierten Ordnerstruktur** vor und hat die unabhängige Prüfung bestanden:

```bash
cd "$HOME/iPod-Audio-Rescue"
git pull --ff-only
sudo apt-get install -y ffmpeg

AUDIO="$HOME/Audiodateien-Rekonstruiert"  # verifizierter strukturierter Export
MP3="$HOME/Audiodateien-MP3"               # völlig separates Ziel

test -f "$AUDIO/_verification_manifest.csv" \
  || { echo "ABBRUCH: Quellmanifest fehlt" >&2; exit 1; }

# Der Wiederaufnahme-Konverter benötigt ein existierendes Zielverzeichnis:
mkdir -p "$MP3"
```

**Platz beachten:** MP3 V0 kann deutlich **größer** werden als AAC mit 128 kbit/s. Die Originalbibliothek weder überschreiben noch aus Platzgründen löschen. `AUDIO` darf auch unter `/mnt/d/...` liegen; Pfade sind Beispiele.

`scripts/convert_audio_to_mp3.py` ist der einzige Konvertierungseinstieg: Trockenlauf, strenge LAME-V0-Konvertierung, automatischer Rettungsversuch und Wiederaufnahme per Checkpoint. Die Quelldateien bleiben unverändert.

## 2. Vorab prüfen – Trockenlauf

```bash
python3 scripts/convert_audio_to_mp3.py \
  --source "$AUDIO" \
  --output "$MP3"
```

Das Programm liest mit `ffprobe` alle Audio-Dateien, erkennt den echten Codec, prüft auf doppelte MP3-Zielnamen und zeigt die geplante Anzahl. **Es verändert im Trockenlauf keine Datei.**

Wenn eine M4A bereits nicht mit `ffprobe` geöffnet werden kann (beispielsweise `moov atom not found`), **bricht diese Vorprüfung absichtlich ab**. Den betroffenen Titel zunächst untersuchen, statt die ganze Sammlung ungeprüft zu verändern. Eine **ausdrücklich bestätigte, ausschließlich unlesbare** Quelldatei lässt sich über ihren exakten quellrelativen Pfad ausnehmen:

```bash
python3 scripts/convert_audio_to_mp3.py \
  --source "$AUDIO" --output "$MP3" \
  --exclude-unreadable "Album/01 - Defekter Titel.m4a"
```

Der angegebene Pfad ist **nur ein Beispiel**. Nur vorhandene, von `ffprobe` tatsächlich nicht lesbare Dateien werden so freigegeben und im Ausnahmemanifest mit Größe und SHA-256 dokumentiert. **Löschung ist nicht erforderlich.**

## 3. Konvertieren – automatisch reparieren, protokollieren, fortsetzen

**Nach erfolgreichem Trockenlauf** (ohne Ausnahmeparameter, wenn keine Ausnahme nötig ist):

```bash
python3 scripts/convert_audio_to_mp3.py \
  --source "$AUDIO" \
  --output "$MP3" \
  --execute
```

Je neuer Audio-Datei geschieht Folgendes:

1. Bereits vorhandene `.mp3` wird bitidentisch kopiert und mit SHA-256 verglichen.
2. Bei AAC/M4A wird erst **streng mit FFmpeg `-xerror` und LAME V0** kodiert; Format, Laufzeit (maximal **1 Sekunde Differenz**) und Ausgabedatei-Hash werden geprüft.
3. Falls das scheitert, erfolgt **ein einziger toleranter Versuch ohne `-xerror`**. Er wird nur akzeptiert, wenn die MP3 dekodierbar ist und ihre Laufzeit maximal **2 Sekunden** von der Quell-Containerdauer abweicht.
4. Eine gerettete Datei wird in der CSV explizit als `recovered_aac_to_mp3` markiert. **Fehlerhafte AAC-Abschnitte werden dadurch nicht wirklich repariert.** Diese MP3s später gezielt anhören.
5. Wenn auch der Rettungsversuch unbrauchbar ist, wird der Titel mit Grund/Quellhash protokolliert und die **nächste Datei** bearbeitet. Solange ungeklärte Fehler verbleiben, darf das Endergebnis **nicht als `PASS`** gelten.

**Wichtige Protokolle im MP3-Zielordner:**

| Datei | Bedeutung |
| --- | --- |
| `_mp3_conversion_progress.csv` | **Checkpoint** nach jeder fertig geprüften Datei; Restart ohne erneutes Kodieren |
| `_mp3_conversion_manifest.csv` | **Erst bei komplettem Erfolg**: alle Quellen/Ziele, Größen, Hashes, Laufzeiten, Methode |
| `_mp3_conversion_recoveries.csv` | Automatisch oder gezielt gerettete Titel, Quell-/Ziel-Hash, Zeitabweichung, Grund |
| `_mp3_conversion_failures.csv` | Fehlgeschlagene Versuche; **können historische, später erfolgreich gerettete Fälle enthalten** |
| `_mp3_conversion_exclusions.csv` | Ausdrücklich ausgenommene unlesbare/fehlerhafte Dateien, falls verwendet |

### Wiederaufnahme nach Stromausfall oder Decoderfehler

**Denselben Befehl erneut ausführen.** Bereits vorhandene MP3s werden niemals überschrieben:

- Beim **ersten Start nach einem älteren, abgebrochenen Export ohne Checkpoints** prüft das Werkzeug vorhandene MP3s einmalig (Codec, Laufzeit, SHA-256) und übernimmt sie in den Fortschrittsplan – **ohne vollständige Neucodierung**.
- Bei späteren Wiederaufnahmen reichen standardmäßig **Pfad, Aktion und Dateigröße** für die schnelle Checkpoint-Kontrolle. Bereits aufgenommene Titel werden **nicht neu kodiert oder bei jedem Neustart erneut komplett gehasht**.
- Das ist ein bewusstes **Home-Rescue-Performanceprofil**. Für die wiederholte vollständige SHA-256-Prüfung zusätzlich `--audit-existing` angeben; auch damit wird kein AAC neu kodiert.
- Bei unaufgelösten Fehlern ist der Lauf `UNVOLLSTAENDIG` und Exit-Code ungleich 0. Fehler anhand des Protokolls untersuchen, die Originale nicht verändern. Ein bereits nachgewiesener Konvertierungsfehler kann mit `--exclude-failed "exakter/relativer/Dateiname.m4a"` bewusst und dokumentiert ausgenommen werden.

### Eine manuell kontrollierte Rettungs-MP3 verwenden (optional)

In Einzelfällen kann ein manuell mit FFmpeg ohne `-xerror` erzeugter Versuch besser klingen. Nach der **Hörkontrolle** erlaubt der Konverter, genau **eine** solche MP3 mit Quellpfad und Dateipfad explizit einzubinden:

```bash
python3 scripts/convert_audio_to_mp3.py \
  --source "$AUDIO" --output "$MP3" \
  --recovery-source "Album/03 - Interpret - Titel.m4a" \
  --recovery-mp3 "$HOME/Testdatei.mp3" \
  --execute
```

Das ist optional und **nicht** der Standardweg. Das Skript prüft Herkunft, MP3-Dekodierbarkeit, Hash und maximal zwei Sekunden Laufzeitdifferenz. Es ersetzt keine schon vorhandene Zieldatei.

## 4. Unabhängig prüfen und archivieren

Das Exportmanifest ist nur ein Protokoll. **Eine unabhängige erneute Prüfung muss die tatsächlichen MP3-Dateien lesen**. Dafür gibt es ein gesondertes, **read-only** Skript:

```bash
# SHA-256 jeder MP3 gegen das neue Konvertierungsmanifest
python3 scripts/verify_mp3_conversion.py \
  --mp3-root "$MP3" \
  --strict

# Umfassender: alle MP3s und ihre Audio-Quelldateien erneut hashen
python3 scripts/verify_mp3_conversion.py \
  --mp3-root "$MP3" \
  --source "$AUDIO" \
  --strict
```

Bei Erfolg erscheint `PASS: <Anzahl> MP3 files, <Bytes> bytes; SHA-256 verified ...`. Außerdem wird das separate Rettungsprotokoll auf passende Quell-/Zielhashes zu den `recovered_aac_to_mp3`-Einträgen kontrolliert. **`PASS` bestätigt Datenintegrität, nicht störungsfreie Wiedergabe.**

**Noch einmal anhören:** Stichprobe von Anfang/Mitte/Ende, insbesondere **alle** in `_mp3_conversion_recoveries.csv` aufgeführten Titel. Vollständige Audioqualität kann keine Hashfunktion bescheinigen. Apple-spezifische Cover/Tags können sich bei MP3-Transkodierung ändern; ebenfalls stichprobenweise prüfen.

**Langzeitaufbewahrung:** (1) Rohbackup **inklusive iTunesDB** und SHA-256, (2) unabhängig geprüfte strukturierte Bibliothek mit Original-AAC/MP3, (3) MP3-Zweitbibliothek mit Manifesten. Im Fehlerfall auf das Rohbackup zurückkommen können.

## 5. Nachgewiesener Abschluss

Die hier dokumentierte MP3-Konvertierung wurde erfolgreich durchgeführt und das Endergebnis **nachträglich unabhängig mit `scripts/verify_mp3_conversion.py` geprüft**. Dabei wurden sowohl die tatsächlich vorhandenen MP3-Zieldateien als auch ihre jeweiligen Audio-Quelldateien per **SHA-256** mit dem Abschlussmanifest verglichen; Ergebnis: **`PASS`**. Auch die gesondert dokumentierte automatische Rettung ist mit dem Abschlussmanifest abgeglichen.

Nachmachen lässt sich das Ergebnis mit dem Befehl in **Abschnitt 4**. Wenn einzelne Quell-AACs beschädigt waren, die protokollierten Rettungsfassungen zusätzlich anhören.

[← Zur Übersicht](../README.md) · [Archiv und Rekonstruktion](END-TO-END-RECOVERY.md)
