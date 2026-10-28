#!/usr/bin/env python3
"""Produce a separate MP3-only library from a verified offline audio export.

Default: preflight only. --execute writes to a NEW/EMPTY destination; never changes
source files. MP3s are copied byte-identically; AAC/ALAC in audio-only M4A/MP4
are decoded and LAME V0-encoded to MP3 (lossy to lossy for AAC). DRM files and
unrecognized/multitrack media cause fail-closed preflight; actual videos skipped.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

AUDIO_EXT = {'.mp3', '.m4a', '.mp4', '.m4p', '.aac', '.wav', '.flac', '.aif', '.aiff'}
TRANSCODE = {'.m4a', '.mp4', '.aac', '.wav', '.flac', '.aif', '.aiff'}
AUDIO_CODECS = {'aac', 'alac', 'flac', 'pcm_s16le', 'pcm_s24le', 'pcm_f32le', 'pcm_s32le', 'mp3'}
MANIFEST = '_mp3_conversion_manifest.csv'
EXCLUSIONS_MANIFEST = '_mp3_conversion_exclusions.csv'


def contained(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    p = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries',
        'stream=codec_name,codec_type:stream_disposition=attached_pic:format=duration,bit_rate',
        '-of', 'json', str(path),
    ], capture_output=True, text=True)
    if p.returncode:
        raise ValueError(f'ffprobe fehlgeschlagen: {path}: {p.stderr.strip()}')
    return json.loads(p.stdout)


def duration(data: dict) -> float | None:
    try:
        return float(data.get('format', {}).get('duration'))
    except (TypeError, ValueError):
        return None


def audio_info(data: dict) -> tuple[str, bool]:
    streams = data.get('streams', [])
    audible = [s for s in streams if s.get('codec_type') == 'audio']
    is_video = any(s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic') for s in streams)
    if is_video:
        return '', True
    if len(audible) != 1:
        raise ValueError(f'Erwartet genau eine Audiospur, gefunden: {len(audible)}')
    codec = audible[0].get('codec_name', '')
    if codec not in AUDIO_CODECS:
        raise ValueError(f'Nicht freigegebener Codec: {codec}')
    return codec, False


def plan_files(source: Path, explicitly_unreadable: set[str] | None = None):
    explicitly_unreadable = explicitly_unreadable or set()
    srcs = sorted((f for f in source.rglob('*') if (f.is_file() or f.is_symlink()) and f.suffix.lower() in AUDIO_EXT), key=lambda f: f.as_posix().casefold())
    seen: dict[str, Path] = {}
    tasks, skips, errors, exclusions = [], [], [], []
    confirmed_exclusions: set[str] = set()
    for src in srcs:
        rel = src.relative_to(source)
        requested_exclusion = rel.as_posix() in explicitly_unreadable
        if src.is_symlink():
            errors.append(f'Symlink: {rel}'); continue
        if rel.name.startswith('_') and rel.suffix == '.csv':
            continue
        if src.suffix.lower() == '.m4p':
            errors.append(f'DRM-verdächtige M4P-Datei: {rel}'); continue
        try:
            data = probe(src)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            if requested_exclusion and not src.is_symlink() and src.suffix.lower() != '.m4p':
                try:
                    exclusions.append(dict(source=rel.as_posix(), bytes=src.stat().st_size,
                                           sha256=sha256(src), reason=str(e)))
                    confirmed_exclusions.add(rel.as_posix())
                except OSError as exc:
                    errors.append(f'Ausnahme nicht lesbar fuer Hashpruefung: {rel}: {exc}')
                continue
            errors.append(f'{rel}: {e}'); continue
        if requested_exclusion:
            errors.append(f'Expliziter Ausschluss nicht zulaessig: Datei ist per ffprobe lesbar: {rel}')
            continue
        try:
            codec, video = audio_info(data)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            errors.append(f'{rel}: {e}'); continue
        if video:
            skips.append(str(rel)); continue
        if src.suffix.lower() == '.mp3':
            if codec != 'mp3':
                errors.append(f'Dateiendung .mp3, aber Codec {codec}: {rel}'); continue
            action = 'copy_mp3'
        elif src.suffix.lower() in TRANSCODE:
            action = f'{codec}_to_mp3'
        else:
            errors.append(f'Nicht unterstützte Datei: {rel}'); continue
        dst = rel.with_suffix('.mp3')
        k = dst.as_posix().casefold()
        if k in seen:
            errors.append(f'Kollision {dst}: {seen[k]} <> {rel}'); continue
        seen[k] = rel
        tasks.append((src, rel, dst, action, codec, data))
    for missing in sorted(explicitly_unreadable - confirmed_exclusions):
        errors.append(f'Ausschluss nicht bestaetigt (fehlt, lesbar oder unzulaessig): {missing}')
    return tasks, skips, errors, exclusions


def copy_verified(src: Path, dst: Path):
    with src.open('rb') as fin, dst.open('xb') as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)
        fout.flush(); os.fsync(fout.fileno())
    if src.stat().st_size != dst.stat().st_size or sha256(src) != sha256(dst):
        raise ValueError('MP3-Kopierprüfung fehlgeschlagen')


def transcode_verified(src: Path, dst: Path, src_data: dict):
    with tempfile.NamedTemporaryFile(prefix='.mp3-encoding-', suffix='.tmp', dir=dst.parent, delete=False) as tmp:
        tmp_name = Path(tmp.name)
    try:
        cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
               '-i', str(src), '-map', '0:a:0', '-map_metadata', '0', '-vn',
               '-c:a', 'libmp3lame', '-q:a', '0', '-id3v2_version', '3',
               '-f', 'mp3', '-y', str(tmp_name)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode:
            raise ValueError(f'FFmpeg-Fehler: {p.stderr.strip()}')
        converted = probe(tmp_name)
        codec, is_video = audio_info(converted)
        if codec != 'mp3' or is_video or tmp_name.stat().st_size < 128:
            raise ValueError('Konvertierte Datei ist keine gültige MP3')
        d_in, d_out = duration(src_data), duration(converted)
        if d_in is not None and d_out is not None and abs(d_in - d_out) > 1.0:
            raise ValueError(f'Abweichende Laufzeit: {d_in:.2f}s -> {d_out:.2f}s')
        with tmp_name.open('rb') as fin, dst.open('xb') as fout:
            shutil.copyfileobj(fin, fout, 1024 * 1024)
            fout.flush(); os.fsync(fout.fileno())
        if sha256(tmp_name) != sha256(dst):
            raise ValueError('Transkodierte MP3 unterscheidet sich von temporärer Datei')
        return converted
    finally:
        tmp_name.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True, type=Path, help='Verified, structured offline audio directory')
    ap.add_argument('--output', required=True, type=Path, help='New/empty destination for MP3 library')
    ap.add_argument('--execute', action='store_true', help='Actually create output files (default: dry-run)')
    ap.add_argument('--exclude-unreadable', action='append', default=[], metavar='REL_PATH',
                    help='EXACT source-relative filename to exclude ONLY when ffprobe fails;'
                         ' records original size and SHA-256 in a separate manifest')
    args = ap.parse_args()
    for binary in ('ffmpeg', 'ffprobe'):
        if not shutil.which(binary):
            ap.error(f'Fehlt: {binary}; apt install ffmpeg')
    source = args.source.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    if not source.is_dir() or source == Path('/') or source == output or contained(output, source) or contained(source, output):
        ap.error('Quell-/Zielpfade unzulässig oder ineinander verschachtelt')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        ap.error('Ziel muss neu oder leer sein; bestehende Bibliothek niemals überschreiben')
    exclusion_requests: set[str] = set()
    for name in args.exclude_unreadable:
        # Avoid path aliases: exclude only the exact relative pathname.
        if (not name or '\\' in name or Path(name).is_absolute()
                or any(part in ('', '.', '..') for part in name.split('/'))):
            ap.error(f'Nicht zulaessiger Ausschlusspfad: {name!r}')
        if name in exclusion_requests:
            ap.error(f'Doppelte Ausschlussanweisung: {name!r}')
        exclusion_requests.add(name)
    tasks, skips, errors, exclusions = plan_files(source, exclusion_requests)
    summary = Counter(t[3] for t in tasks)
    print(f'Quelle: {source}\nZiel: {output}\nGeplante Dateien: {len(tasks)}; Methoden: {dict(summary)}')
    print(f'Übersprungene Video-Dateien: {len(skips)}')
    print(f'Explizit ausgeschlossene unlesbare Dateien: {len(exclusions)}')
    for item in exclusions:
        print(f"AUSNAHME (bleibt im Original): {item['source']} | {item['bytes']} Bytes | SHA256={item['sha256']}")
    for item in skips[:8]: print('VIDEO übersprungen:', item)
    if errors:
        for e in errors[:20]: print('ABBRUCH:', e, file=sys.stderr)
        if len(errors)>20:print(f'... {len(errors)-20} weitere Fehler',file=sys.stderr)
        return 2
    if not tasks:
        ap.error('Keine Audiodateien gefunden')
    if not args.execute:
        print('TROCKENLAUF OK; nichts geschrieben. Für die Erstellung --execute ergänzen.')
        return 0
    output.mkdir(parents=True, exist_ok=True)
    report = []
    for idx,(src,rel,dst_rel,action,codec,src_data) in enumerate(tasks, 1):
        dst = output / dst_rel
        if dst.is_symlink() or not contained(dst.resolve(strict=False), output):
            raise ValueError(f'Nicht zulässiges Ziel: {dst}')
        dst.parent.mkdir(parents=True,exist_ok=True)
        try:
            if action == 'copy_mp3':
                copy_verified(src, dst)
                out_data = src_data
            else:
                out_data = transcode_verified(src, dst, src_data)
            report.append(dict(source=rel.as_posix(),target=dst_rel.as_posix(),source_codec=codec,
                               source_bytes=src.stat().st_size,source_sha256=sha256(src),
                               target_bytes=dst.stat().st_size,target_sha256=sha256(dst),
                               action=action,source_duration=duration(src_data),target_duration=duration(out_data)))
            if idx % 100 == 0 or idx==len(tasks):
                print(f'Verifiziert: {idx}/{len(tasks)}')
        except Exception:
            dst.unlink(missing_ok=True)
            raise
    if exclusions:
        with (output/EXCLUSIONS_MANIFEST).open('x', newline='', encoding='utf-8-sig') as fh:
            writer = csv.DictWriter(fh, fieldnames=['source', 'bytes', 'sha256', 'reason'], delimiter=';')
            writer.writeheader(); writer.writerows(exclusions)
    with (output/MANIFEST).open('x',newline='',encoding='utf-8-sig') as fh:
        writer=csv.DictWriter(fh,fieldnames=list(report[0]),delimiter=';')
        writer.writeheader();writer.writerows(report)
    print(f'PASS: {len(report)} erzeugte MP3-Dateien; Datei-Hashes im {MANIFEST}; Rohdaten unverändert.')
    if exclusions:
        print(f'WICHTIG: {len(exclusions)} explizit ausgenommene defekte Quelldatei(en); siehe {EXCLUSIONS_MANIFEST}.')
    print('ACHTUNG: AAC/ALAC->MP3 ist eine neue verlustbehaftete Kodierung; nicht klanglich mit dem Original gleichzusetzen.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())