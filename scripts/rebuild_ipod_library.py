#!/usr/bin/env python3
"""Read-only metadata-based audio file export from an offline iPod media backup.

No write operations on the original iPod filesystem or raw media backup.
Requires: python3 -m pip install mutagen (or apt install python3-mutagen).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

try:
    from mutagen import File as MutagenFile
    from mutagen.mp4 import MP4
except ImportError:
    raise SystemExit("Fehlt: mutagen. Installiere mit: sudo apt install python3-mutagen")

AUDIO = {".mp3", ".m4a", ".m4p", ".aac", ".wav", ".aif", ".aiff", ".flac"}
VIDEO = {".m4v", ".mp4", ".mov", ".avi", ".mpg", ".mpeg"}
VARIOUS = {"various artists", "various", "v.a.", "v.a", "va", "verschiedene interpreten", "diverse interpreten"}
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
FIELDS = ["status", "source", "target", "artist", "album_artist", "album", "title", "track", "disc", "compilation", "reason"]


def tidy(value: object) -> str:
    if value is None:
        return ""
    value = str(value)
    return " ".join(value.strip().split())


def safe_name(text: str, limit: int = 105) -> str:
    text = unicodedata.normalize("NFC", tidy(text))
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " - ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        return "_Leer_"
    if text.split(".", 1)[0].upper() in RESERVED:
        text = "_" + text
    if len(text) > limit:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        text = text[:limit - 11].rstrip(" .") + "-" + digest
    return text


def first(tags, key: str) -> str:
    try:
        value = tags.get(key)
        if value is None:
            return ""
        if hasattr(value, "text"):
            value = value.text
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return tidy(value)
    except (KeyError, TypeError, ValueError, IndexError):
        return ""


def number(text: str) -> int:
    try:
        value = int(str(text).split("/", 1)[0].strip())
        return value if 1 <= value <= 999 else 0
    except (TypeError, ValueError):
        return 0


def mp4_number(tags, key: str) -> int:
    try:
        pair = tags.get(key, [(0, 0)])[0]
        return number(pair[0])
    except (KeyError, TypeError, ValueError, IndexError):
        return 0


def mp4_compilation(tags) -> bool:
    values = tags.get("cpil", [])
    if isinstance(values, (list, tuple)):
        return bool(values and values[0])
    return bool(values)


def id3_compilation(tags) -> bool:
    return first(tags, "TCMP").lower() in {"1", "true", "yes"}


def metadata(path: Path) -> dict[str, object]:
    audio = MutagenFile(path, easy=False)
    if audio is None or audio.tags is None:
        raise ValueError("Keine lesbaren Audio-Tags")
    tags = audio.tags
    if isinstance(audio, MP4):
        return dict(
            artist=first(tags, "\xa9ART"), album_artist=first(tags, "aART"),
            album=first(tags, "\xa9alb"), title=first(tags, "\xa9nam"),
            track=mp4_number(tags, "trkn"), disc=mp4_number(tags, "disk"),
            compilation=mp4_compilation(tags),
        )
    return dict(
        artist=first(tags, "TPE1"), album_artist=first(tags, "TPE2"),
        album=first(tags, "TALB"), title=first(tags, "TIT2"),
        track=number(first(tags, "TRCK")), disc=number(first(tags, "TPOS")),
        compilation=id3_compilation(tags),
    )


def is_contained(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def stream_copy_verified(src: Path, dst: Path) -> None:
    """Create destination exclusively; compare SHA-256 from source stream and final file."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    origin = hashlib.sha256()
    created = False
    try:
        with src.open("rb") as fin, dst.open("xb") as fout:
            created = True
            while True:
                data = fin.read(1024 * 1024)
                if not data:
                    break
                origin.update(data)
                fout.write(data)
            fout.flush()
            os.fsync(fout.fileno())
        copied = hashlib.sha256()
        with dst.open("rb") as fin:
            while True:
                chunk = fin.read(1024 * 1024)
                if not chunk:
                    break
                copied.update(chunk)
        if origin.digest() != copied.digest() or src.stat().st_size != dst.stat().st_size:
            raise OSError(f"Integritaetsfehler: {src}")
    except Exception:
        # Remove only the file this call created; do not remove preexisting targets.
        if created and dst.exists():
            dst.unlink()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="iPod-Audiodateien aus unveraendertem Rohbackup wiederherstellen")
    parser.add_argument("--source", type=Path, required=True, help="Ordner mit iTunes_Control")
    parser.add_argument("--output", type=Path, required=True, help="Neuer leerer Ordner fuer die Audiodateien")
    parser.add_argument("--report", type=Path, required=True, help="CSV ausserhalb des Quell- und Zielordners")
    parser.add_argument("--execute", action="store_true", help="Nach Planpruefung tatsaechlich kopieren")
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    report = args.report.expanduser().resolve(strict=False)
    if not source.is_dir() or source == Path("/"):
        parser.error("Ungueltiger Quellordner")
    if is_contained(output, source) or is_contained(source, output):
        parser.error("Quell- und Zielordner duerfen nicht ineinander liegen")
    if is_contained(report, source) or is_contained(report, output):
        parser.error("CSV muss ausserhalb von Quelle und Ziel liegen")
    if report.exists():
        parser.error("CSV-Zieldatei existiert bereits; neuen Dateinamen waehlen")
    if output.exists() and any(output.iterdir()):
        parser.error("Ausgabeverzeichnis muss neu oder leer sein; kein Ueberschreiben")
    roots = [source / "iTunes_Control" / "Music", source / "iPod_Control" / "Music"]
    music = next((p for p in roots if p.is_dir()), None)
    if music is None:
        parser.error("Kein iTunes_Control/Music oder iPod_Control/Music gefunden")

    rows: list[dict[str, str]] = []
    names: set[str] = set()
    for path in sorted(music.rglob("*"), key=lambda p: str(p).casefold()):
        if path.is_symlink():
            rows.append(dict.fromkeys(FIELDS, "") | {"status": "review", "source": str(path.relative_to(source)), "reason": "Symbolischer Link"})
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        row = dict.fromkeys(FIELDS, "") | {"source": str(rel)}
        ext = path.suffix.lower()
        if ext in VIDEO:
            row.update(status="video_separate", reason="Video-Datei; eigene Wiederherstellung")
        elif ext not in AUDIO:
            row.update(status="non_audio", reason="Dateityp nicht in Audio-Whitelist")
        else:
            try:
                tags = metadata(path)
                row.update({k: str(v) for k, v in tags.items()})
                row["compilation"] = "1" if tags["compilation"] else "0"
                missing = [key for key in ("artist", "album", "title") if not tags[key]]
                if not tags["track"]:
                    missing.append("track")
                if missing:
                    row.update(status="review", reason="Metadaten fehlen: " + ", ".join(missing))
                else:
                    is_va = str(tags["album_artist"]).casefold().strip() in VARIOUS
                    compilation = bool(tags["compilation"] or is_va)
                    folder = safe_name(tags["album"] if compilation else f"{tags['album_artist'] or tags['artist']} - {tags['album']}")
                    track_name = f"{tags['track']:02d} - {tags['artist']} - {tags['title']}"
                    # Track numbers are per disc: add disc only when tagged as disc > 1 to avoid overwrites.
                    if tags["disc"] and tags["disc"] > 1:
                        track_name = f"CD{tags['disc']:02d} - {track_name}"
                    base = safe_name(track_name, limit=140)
                    target = Path(folder) / (base + ext)
                    if target.as_posix().casefold() in names:
                        short = hashlib.sha256(str(rel).encode("utf-8")).hexdigest()[:10]
                        target = Path(folder) / (base + " [" + short + "]" + ext)
                    if target.as_posix().casefold() in names:
                        raise ValueError("Ziel-Dateiname trotz Kollision doppelt")
                    names.add(target.as_posix().casefold())
                    row.update(status="ready", target=str(target), compilation="1" if compilation else "0")
            except Exception as exc:
                row.update(status="review", reason=f"Tagfehler: {type(exc).__name__}: {exc}")
        rows.append(row)

    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(row["status"] for row in rows)
    print("CSV-Bericht:", report)
    for key in ("ready", "review", "video_separate", "non_audio"):
        print(f"{key}: {counts[key]}")
    print("ACHTUNG: Keine iTunesDB-Analyse. Bei fehlenden Tags zuerst den Bericht pruefen.")
    if not args.execute:
        print("DRY RUN: Keine Mediendateien kopiert. Mit --execute starten, neuer --report-Dateiname erforderlich.")
        return 0
    if counts["ready"] == 0:
        print("ABBRUCH: Keine sicher zuordenbaren Titel", file=sys.stderr)
        return 2
    done = 0
    for row in rows:
        if row["status"] != "ready":
            continue
        src = source / row["source"]
        dst = output / row["target"]
        try:
            stream_copy_verified(src, dst)
        except Exception as exc:
            print(f"ABBRUCH nach {done} Dateien: {exc}", file=sys.stderr)
            return 3
        done += 1
        if done % 100 == 0:
            print(f"SHA-256-verifiziert kopiert: {done}/{counts['ready']}")
    print(f"Erfolg: {done} Audiodateien nach Kopie per SHA-256 geprueft.")
    print("WICHTIG: 'review', Videos und andere Dateien sind nicht Teil dieser Ausgabe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())