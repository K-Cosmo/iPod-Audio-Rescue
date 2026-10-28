# Schritt 1–4 — Audiodateien vom iPod ohne iTunes sichern und rekonstruieren

[← Projektübersicht](../README.md) · [WSL und USB](WSL-SETUP.md) · [SSLv3 bei iPhone OS 1.x](IPOD1-SSLV3-RESCUE.md) · [Weiter: MP3-Konvertierung](MP3-CONVERSION.md)

**Open-Source-Leitfaden zum Nachmachen** – für einen alten iPod, dessen Bibliothek man möglichst **ohne Schreibzugriff auf das Gerät** sichern, nach Interpreten/Alben rekonstruieren und optional in ein besser nutzbares Format überführen möchte.

**Erprobt:** iPod touch 1, iPhone OS 1.1.5 (Build 4B1), Windows 11, WSL2/Ubuntu 24.04, usbipd-win, ifuse 1.1.4, rsync, Python 3 und Mutagen. Der schwierige Legacy-SSLv3-Zugang ist [separat vollständig beschrieben](IPOD1-SSLV3-RESCUE.md). Für andere iPod-Familien können Dateisystem und Protokolle anders aussehen.

## 0. Ausgangslage und Sicherheitsregeln

Alte iPods speichern Audiodateien häufig in scheinbar zufälligen Verzeichnissen und mit kryptischen Dateinamen. Die eigentlichen Metadaten wie Interpret, Sprecher, Album und Titel liegen teilweise in **Dateitags** und in der **`iTunesDB`**. Das gilt auch für selbst erstellte Aufnahmen; **Podcasts bleiben standardmäßig ein gesonderter Medientyp**. Diese Datenbank ergänzt das bloße Kopieren von Dateiordnern um wichtige Metadaten.

**Das Ziel sind drei unabhängige Ebenen:**
1. **Rohbackup:** byteidentische Sicherung des erreichbaren Medienbereichs einschließlich `iTunes_Control/iTunes/iTunesDB`; niemals nachträglich sortieren.
2. **Strukturierter Export:** geprüfte Kopien mit lesbaren Album-/Titelpfaden; Audioinhalt wird nicht verändert.
3. **Optionale MP3-Kopie:** separate, teils erneut verlustbehaftete Kodierung; kein Ersatz für 1 oder 2.

**Nicht tun:** iPod synchronisieren, wiederherstellen, aktualisieren, jailbreaken, auf dem Gerät Titel umbenennen oder eine erneute Konvertierung direkt auf das Rohbackup loslassen. Keine privaten Medien, `iTunesDB`, CSV-Listen mit Titeln, UDIDs oder Pairing-Schlüssel ins öffentliche Repository hochladen.

**Benötigt:** Platz für mehrere Bibliothekskopien sowie nach Möglichkeit einen **zweiten physischen Datenträger**. Für beschädigte Medien kann keine Software Erfolg garantieren. SHA-256 beweist die Identität kopierter Bytes, nicht die Abspielbarkeit der Originaldatei.

## 1. USB-Zugang und read-only Mount

1. [Windows 11/WSL2/Ubuntu/USB einrichten](WSL-SETUP.md).
2. Nur für den historischen iPod touch 1 / iPhone OS 1.x: [isolierten SSLv3-Build](IPOD1-SSLV3-RESCUE.md) vorbereiten. SSLv3 niemals systemweit aktivieren.
3. `ifuse -o ro` benutzen und mit `findmnt` prüfen. Erst bei bestätigtem `ro` fortfahren.

Im getesteten Setup liegen die Bibliotheken im Home-Verzeichnis:

```bash
export LIMD_LIB="$HOME/ipod-rescue-gnutls/lib"
export SSL3_LIB="$HOME/ipod-rescue-ssl3/lib"
export GNUTLS_SYSTEM_PRIORITY_FILE="$HOME/ipod-gnutls-isolated.conf"
export LD_LIBRARY_PATH="$SSL3_LIB:$LIMD_LIB"

MNT="$HOME/ipod-media"
findmnt --mountpoint "$MNT" -o TARGET,SOURCE,FSTYPE,OPTIONS
findmnt -n -o OPTIONS --mountpoint "$MNT" | grep -Eq '(^|,)ro(,|$)' \
  || { echo "ABBRUCH: Mount ist nicht read-only" >&2; exit 1; }
test -d "$MNT/iTunes_Control" || { echo "Medienpfad fehlt" >&2; exit 1; }
```

Das Terminal sollte das tatsächliche iPod-Verzeichnis zeigen. Ein ro-FUSE-Mount schützt vor Schreiboperationen über diese Schnittstelle, nicht vor jedem denkbaren Protokoll-Seiteneffekt.

## 2. Rohbackup und Pruefsummen

**Dieser Schritt ist wichtiger als alle späteren Umbenennungen.** In Ubuntu ein neues, eindeutiges Rohbackup-Verzeichnis unter `$HOME` anlegen:

```bash
RAW="$(mktemp -d "$HOME/ipod-rescue-media.XXXXXX")"
printf 'Rohbackup: %s\n' "$RAW"

rsync -a --no-owner --no-group --info=progress2 "$MNT/" "$RAW/"
echo "rsync Exit-Code: $?"
test -f "$RAW/iTunes_Control/iTunes/iTunesDB" \
  || { echo "ABBRUCH: iTunesDB nicht im Backup" >&2; exit 1; }
```

**Stopp bei Fehlern:** rsync muss Exit-Code **0** liefern. Ein `rsync`-Dateizähler ist **keine** Anzahl von Audioeinträgen. Falls `iTunesDB` bei deinem Modell unter einem anderen Pfad liegt, zuerst Dateibaum inspizieren, bevor du mit diesen Skripten weitermachst.

**Quellvergleich bei weiterhin eingehängtem iPod:**

```bash
rsync -a --no-owner --no-group --checksum --dry-run \
  --itemize-changes --stats "$MNT/" "$RAW/"
```

Die Ausgabe soll keine unerwarteten Unterschiede oder Lesefehler enthalten; `--dry-run` kann trotz angezeigter Unterschiede Exit-Code 0 liefern. Bei einer Dateiänderung auf dem Gerät zwischen Sicherung und Vergleich die Ursache prüfen.

**Rohbackup-Manifest erstellen (außerhalb des Backup-Ordners):**

```bash
(
  cd "$RAW" || exit 1
  find . -type f -print0 | sort -z | xargs -0 -r sha256sum
) > "$RAW.sha256"
```

**Zweite unabhängige Sicherung:** Das nachfolgende Beispiel nutzt `/mnt/d` **nur, wenn D: wirklich ein anderer physischer Datenträger ist**. Variable auf den tatsächlichen Datenträger anpassen:

```bash
SECOND="/mnt/d/iPod-Rescue/Originalbackup"
test ! -e "$SECOND" || { echo "ABBRUCH: Ziel existiert bereits" >&2; exit 1; }
mkdir -p "$SECOND"
rsync -r --no-perms --no-owner --no-group --info=progress2 "$RAW/" "$SECOND/"

(
  cd "$SECOND" || exit 1
  sha256sum --check "$RAW.sha256"
)
```

Die vollständige Prüfsummenliste lokal außerhalb der beiden Sicherungen aufbewahren. **Nur bei fehlerfreier Hashprüfung** kann die Zweitkopie als geprüft gelten. Quell-`RAW` und `RAW.sha256` über mehrere WSL-Sitzungen hinweg wieder explizit setzen – Shellvariablen bleiben nicht erhalten.

## 3. Werkzeugkette und lokale Arbeitsordner

Im Ubuntu-Terminal:

```bash
sudo apt-get install -y git python3-mutagen
cd "$HOME/iPod-Audio-Rescue"
git pull --ff-only

# Tatsächlichen Namen deines Rohbackup-Verzeichnisses einsetzen:
RAW="/home/DEIN-UBUNTU-BENUTZER/ipod-rescue-media.ABCDEF"
test -f "$RAW/iTunes_Control/iTunes/iTunesDB" \
  || { echo "Pfad zum Rohbackup stimmt nicht" >&2; exit 1; }

WORK="$HOME/ipod-work"
mkdir -p "$WORK"
DB="$RAW/iTunes_Control/iTunes/iTunesDB"
```

`DEIN-UBUNTU-BENUTZER` und `ABCDEF` sind **Platzhalter**. Den realen Pfad aus Schritt 2 kopieren, nicht wörtlich ausführen. Die Skripte greifen **nur auf das lokale Rohbackup** zu.

## 4. Bibliothek rekonstruieren

### 4.1 Dateitags inventarisieren — ohne Audiodateien zu kopieren

```bash
python3 scripts/rebuild_ipod_library.py \
  --source "$RAW" \
  --output "$HOME/Audiodateien-Rekonstruiert" \
  --report "$WORK/plan-tags.csv"
```

Es entsteht ein semikolongetrennter CSV-Plan; **noch keine neue Audiosammlung**. Fehlende Informationen und unbekannte Titelnummern bleiben zur Prüfung markiert. **`--execute` an dieser Stelle nicht verwenden.** Die erste Rohinventur nutzt Mutagen und benötigt keine KI.

### 4.2 iTunesDB auswerten und mit Tags abgleichen

```bash
python3 scripts/parse_itunesdb.py "$DB" \
  --csv "$WORK/itunesdb-tracks.csv"

python3 scripts/reconcile_itunesdb.py \
  --itunesdb "$DB" \
  --old-plan "$WORK/plan-tags.csv" \
  --out "$WORK/plan-itunesdb.csv"
```

Der Parser liest die historischen `mhbd/mhsd/mhlt/mhit/mhod`-Strukturen der hier getesteten iTunesDB und findet beispielsweise Künstler, Album, Titel, Titelnummer und iPod-Dateipfad. Er ist **kein Parser für alle iPod-Firmwarestände**. `reconcile_itunesdb.py` gleicht ausschließlich **exakte iPod-Pfade** ab und ersetzt widersprüchliche vorhandene Tags **nicht** stillschweigend durch Datenbankwerte.

> Die CSVs können private Audio-/Personendaten enthalten. Nur lokal öffnen; in Excel als **UTF-8, Semikolon-getrennt, Spalten möglichst als Text** importieren. Bei Formeln/CSV-Injection vorsichtig sein. Keine Tabellenformeln aus ungeprüften Daten ausführen.

### 4.3 Plan manuell überprüfen

In `$WORK/plan-itunesdb.csv` sind unter anderem diese Stati relevant:

| Status | Bedeutung |
| --- | --- |
| `ready` | Exportfähig **nach menschlicher Sichtung** |
| `review_metadata` / `review` | Name, Album, Nummer oder Zuordnung fehlen |
| `review_collision` | Mehrere Quellen würden denselben Windows-Dateinamen erhalten |
| `review_unindexed_audio` | Audiokopie ist vorhanden, aber **nicht in der iTunesDB** nachgewiesen |
| `podcast_ready` / `video_ready` | Separater Medientyp, nur auf ausdrücklichen Wunsch exportieren |
| Andere `review_*` | Nicht ungeprüft freigeben |

**Wichtig:** Dieses Repository enthält **keine** allgemeine Online-Metadatendatenbank und errät keine Tracknummern. Wo sichere Informationen fehlen, zunächst einen **separaten Sammelordner** wählen und eindeutige Namen vergeben. Die Namen im neu erzeugten CSV dürfen manuell ergänzt werden; die Quelldatei selbst bleibt unverändert.

**Empfohlenes Ausgabelayout:**

```text
Interpret - Album/
  01 - Interpret - Titel.m4a
  02 - Interpret - Zweiter Titel.mp3

Samplername/
  01 - Interpret A - Titel.m4a
  02 - Interpret B - Titel.mp3

Sammelordner - Manuell einsortieren/
  00 - Unbekannt - Unklarer Titel [eindeutige Quellkennung].m4a
```

**Freigabe:** Zunächst eine *Kopie* des geprüften CSV anlegen (zum Beispiel mit `cp "$WORK/plan-itunesdb.csv" "$WORK/plan-itunesdb-freigegeben.csv"`), die Kopie in einem CSV-Editor öffnen, nur wirklich entschiedene Zeilen auf `ready` setzen und `target` mit einem sicheren **relativen** Zielpfad ausfüllen. Keine doppelten Ziele (auch nicht mit anderer Groß-/Kleinschreibung). Bei Dubletten **Audiodaten vergleichen**; gleiche Dateinamen oder Dateigrößen allein beweisen keine Identität. Das Original-CSV behalten.

### 4.4 Strukturierter Export: erst Trockenlauf, dann Kopie

```bash
PLAN="$WORK/plan-itunesdb-freigegeben.csv"
OUT="$HOME/Audiodateien-Rekonstruiert"

# Nur nach dem manuellen Sichern/Bearbeiten der Plankopie:
test -f "$PLAN" || { echo "Freigegebener CSV-Plan fehlt" >&2; exit 1; }

python3 scripts/export_ipod_from_plan.py \
  --source "$RAW" --plan "$PLAN" --output "$OUT"

# Erst wenn Ausgabe, Anzahl und Zielpfad plausibel sind:
python3 scripts/export_ipod_from_plan.py \
  --source "$RAW" --plan "$PLAN" --output "$OUT" --execute
```

`OUT` muss **neu oder leer** sein. Das Programm exportiert standardmäßig **nur `ready`** und kopiert jede Audiodatei **ohne jede Neukodierung**; die Hashwerte werden während/nach der Kopie geprüft. Das Programm schreibt `$OUT/_verification_manifest.csv` und überschreibt keine vorhandenen Audiodateien. Podcasts/Videos sind optional, in diesem How-to bewusst nicht Teil des Audioexports.

**Achtung:** Das Exportskript ist nicht für `--execute` in einem bereits teilweise gefüllten Ordner gedacht. Bei Unterbrechungen zuerst Fehler prüfen und einen neuen leeren Ausgabeordner wählen; bestehende Ergebnisse **nicht blind löschen**.

### 4.5 Unabhängig prüfen

```bash
python3 scripts/verify_ipod_export.py \
  --export-root "$OUT" \
  --raw "$RAW" \
  --strict
```

Erst ein erfolgreiches `PASS` bestätigt, dass jede im Manifest freigegebene Datei im rekonstruierten Ordner und im **Rohbackup** mit dem dokumentierten SHA-256-Wert übereinstimmt. `--strict` meldet nicht im Manifest aufgeführte Dateien. **Abspielbarkeit und Vollständigkeit gegenüber dem ursprünglich angezeigten iPod-Titelzähler bleiben separate Prüfungen.**

## 5. Weiter zur MP3-Konvertierung

Bei vielen alten Geräten sind MP3 und AAC in `.m4a` gemischt. **Der rekonstruierte Audioexport bleibt die Archivfassung.** Für eine zusätzliche, weitgehend gerätekompatible MP3-Zweitbibliothek folgt nun [Schritt 5: AAC→MP3 mit LAME V0, automatischer Fehlerbehandlung, Checkpoints und abschließender SHA-256-Prüfung](MP3-CONVERSION.md).

## 6. Was die Werkzeuge leisten – und was nicht

| Werkzeug | Aufgabe |
| --- | --- |
| [`scripts/install-requirements.sh`](../scripts/install-requirements.sh) | Linux/WSL-Basispakete installieren |
| [`scripts/rebuild_ipod_library.py`](../scripts/rebuild_ipod_library.py) | Tags inventarisieren und ersten CSV-Plan erzeugen |
| [`scripts/parse_itunesdb.py`](../scripts/parse_itunesdb.py) | Alte binäre iTunesDB auslesen |
| [`scripts/reconcile_itunesdb.py`](../scripts/reconcile_itunesdb.py) | Datenbank und Tags über Dateipfade abgleichen |
| [`scripts/export_ipod_from_plan.py`](../scripts/export_ipod_from_plan.py) | Freigegebene Titel byteidentisch kopieren |
| [`scripts/verify_ipod_export.py`](../scripts/verify_ipod_export.py) | Original- und Export-SHA-256 unabhängig vergleichen |
| [`scripts/convert_audio_to_mp3.py`](../scripts/convert_audio_to_mp3.py) | MP3 mit Checkpoints und kontrolliertem Rettungsfallback |
| [`scripts/verify_mp3_conversion.py`](../scripts/verify_mp3_conversion.py) | MP3-Endbibliothek unabhängig erneut hashen |

**KI ist optional:** Die ursprüngliche Rettung wurde durch einen Assistenten bei Fehlersuche, Skripterstellung und Metadatenbewertung unterstützt. Der hier beschriebene Open-Source-Pfad **funktioniert offline und ohne KI**. Automatische Albumgruppierungen sind Heuristiken: Nutzer müssen im CSV kontrollieren, statt vermeintlich „richtige“ Albumtitel oder Reihenfolgen ungeprüft zu übernehmen.

**Integrität ≠ Dekodierbarkeit:** Auch eine vollständig SHA-256-geprüfte M4A kann beschädigtes Audio oder fehlende MP4-Verwaltungsdaten enthalten. Unlesbare Dateien separat protokollieren, Originale behalten; keine Audioverluste durch automatisches Schönreden verbergen.

## 7. Ergebnis und Grenzen des nachgewiesenen Verfahrens

Der hier dokumentierte Rettungsweg wurde an einem historischen iPod erfolgreich durchlaufen: **AFC-Rohbackup, iTunesDB-Abgleich, strukturierter Audioexport und separate MP3-Konvertierung**. Für den strukturierten Export wurde SHA-256 unabhängig mit dem Rohbackup verglichen; die abschließende MP3-Prüfung hat ebenfalls **`PASS` gegen die tatsächlich vorhandenen Audioquelldateien und MP3-Zieldateien** ergeben.

Im ursprünglichen Rettungsfall wurde eine nicht abspielbare Datei nach der erfolgreichen Prüfung aus dem *strukturierten* Quellordner entfernt. Eine zuvor erfolgte Verifikation bezieht sich daher auf den damaligen Ordnerzustand. Der später geprüfte MP3-Zielbestand wurde mit den tatsächlich noch vorhandenen Quelldateien abgeglichen.

**Wichtig:** Ein erfolgreiches `PASS` belegt die Dateiintegrität, nicht die Korrektheit sämtlicher Tags oder die hörbare Qualität beschädigter Originalaufnahmen. Original-Rohbackup und iTunesDB möglichst unverändert archivieren.
