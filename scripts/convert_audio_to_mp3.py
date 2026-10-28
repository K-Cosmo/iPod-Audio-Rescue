#!/usr/bin/env python3
"""Create and resume a separate MP3 library from offline audio originals.

Default: dry-run. --execute never overwrites source or existing output media.
MP3 files are byte-exact copies; other supported audio is LAME V0 encoded.
Strict decoding uses -xerror first. Failed encodes retry tolerantly once,
are recorded in a recovery log and require listening review.
Interrupted runs use per-file checkpoints; full auditing is opt-in.
DRM and ambiguous/multitrack inputs fail closed during preflight.

Standalone: requires Python standard library and FFmpeg/ffprobe only.
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


PROGRESS = '_mp3_conversion_progress.csv'
FAILURES = '_mp3_conversion_failures.csv'
RECOVERIES = '_mp3_conversion_recoveries.csv'
RECOVERY_FIELDS = ('source', 'target', 'source_sha256', 'target_sha256', 'source_duration', 'target_duration', 'note')
RECOVERY_ACTION = 'recovered_aac_to_mp3'
RECOVERY_DURATION_TOLERANCE = 2.0  # fixed maximum duration difference for damaged AAC rescue
FIELDS = ('source', 'target', 'source_codec', 'source_bytes', 'source_sha256',
          'target_bytes', 'target_sha256', 'action', 'source_duration', 'target_duration')


def append_csv(path: Path, row: dict, fields: tuple[str, ...]) -> None:
    with path.open('a', newline='', encoding='utf-8-sig' if not path.exists() else 'utf-8') as out:
        writer = csv.DictWriter(out, fieldnames=fields, delimiter=';')
        if out.tell() == 0:
            writer.writeheader()
        writer.writerow(row)
        out.flush()
        os.fsync(out.fileno())


def load_csv(path: Path, fields: tuple[str, ...]) -> list[dict]:
    if not path.exists():
        return []
    if path.is_symlink():
        raise ValueError(f'Symlink-Protokoll verboten: {path}')
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream, delimiter=';')
        if tuple(reader.fieldnames or ()) != fields:
            raise ValueError(f'Ungueltige CSV-Spalten in {path.name}')
        rows = list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):
            raise ValueError(f'Ungueltige/unvollstaendige CSV-Zeile in {path.name}')
        return rows


def csv_report(src: Path, rel: Path, dst: Path, dst_rel: Path, action: str,
               codec: str, src_data: dict, dst_data: dict) -> dict:
    return dict(source=rel.as_posix(), target=dst_rel.as_posix(), source_codec=codec,
                source_bytes=src.stat().st_size, source_sha256=sha256(src),
                target_bytes=dst.stat().st_size, target_sha256=sha256(dst),
                action=action, source_duration=duration(src_data),
                target_duration=duration(dst_data))


def validate_row(row: dict, src: Path, rel: Path, dst: Path, dst_rel: Path,
                 action: str, codec: str, src_data: dict,
                 recovery_records: dict[str, dict], audit: bool = False) -> dict:
    if row['source'] != rel.as_posix() or row['target'] != dst_rel.as_posix():
        raise ValueError(f'Checkpoint-Pfad stimmt nicht: {rel}')
    recovered = row['action'] == RECOVERY_ACTION
    if row['source_codec'] != codec or (row['action'] != action and not (recovered and action == 'aac_to_mp3')):
        raise ValueError(f'Checkpoint-Codecs stimmen nicht: {rel}')
    if (not dst.is_file() or dst.is_symlink() or
        row['source_bytes'] != str(src.stat().st_size) or
        row['target_bytes'] != str(dst.stat().st_size)):
        raise ValueError(f'Checkpoint-Datei fehlt oder Groesse stimmt nicht: {rel}')
    # Default: trust fsynced checkpoints, checking source and target sizes.
    # --audit-existing repeats full SHA-256, codec and duration validation.
    if audit:
        if (row['source_sha256'] != sha256(src)
                or row['target_sha256'] != sha256(dst)):
            raise ValueError(f'Checkpoint-Hash stimmt nicht: {rel}')
        data = probe(dst)
        codec_out, video = audio_info(data)
        if codec_out != 'mp3' or video:
            raise ValueError(f'Checkpoint-Ziel ist keine MP3: {dst_rel}')
        d_in, d_out = duration(src_data), duration(data)
        tolerance = RECOVERY_DURATION_TOLERANCE if recovered else 1.0
        if d_in is None or d_out is None or abs(d_in-d_out) > tolerance:
            raise ValueError(f'Checkpoint-Laufzeit weicht ab: {rel}: {d_in} -> {d_out}')
    if recovered:
        provenance = recovery_records.get(dst_rel.as_posix())
        if (provenance is None or provenance['source'] != rel.as_posix()
            or provenance['source_sha256'] != row['source_sha256']
            or provenance['target_sha256'] != row['target_sha256']):
            raise ValueError(f'Rettungs-Kodierung ohne pruefbares Herkunftsprotokoll: {rel}')
    return row


def verify_preexisting(src: Path, rel: Path, dst: Path, dst_rel: Path,
                       action: str, codec: str, src_data: dict) -> dict:
    """Verify legacy output without silently trusting it or overwriting it."""
    if not dst.is_file() or dst.is_symlink():
        raise ValueError(f'Vorhandene Zieldatei ist ungueltig: {dst_rel}')
    dst_data = probe(dst)
    result_codec, is_video = audio_info(dst_data)
    if result_codec != 'mp3' or is_video:
        raise ValueError(f'Vorhandene Datei ist keine MP3: {dst_rel}')
    d_in, d_out = duration(src_data), duration(dst_data)
    if d_in is None or d_out is None or abs(d_in - d_out) > 1.0:
        raise ValueError(f'Vorhandene MP3 hat abweichende Laufzeit: {rel}: {d_in} -> {d_out}')
    if action == 'copy_mp3':
        if src.stat().st_size != dst.stat().st_size or sha256(src) != sha256(dst):
            raise ValueError(f'Kopierte MP3 weicht byteweise ab: {rel}')
    else:
        # One-time import of legacy output: codec, plausible duration and hashes
        # are checked and checkpointed. No costly duplicate re-encoding.
        if dst.stat().st_size < 128:
            raise ValueError(f'Vorhandene MP3 zu klein: {rel}')
    return csv_report(src, rel, dst, dst_rel, action, codec, src_data, dst_data)



def validate_recovery(src: Path, rel: Path, dst_rel: Path, src_data: dict,
                      candidate: Path) -> tuple[dict, dict]:
    """Require a user-reviewed, independently decodable MP3, never silently repair."""
    if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.lower() != '.mp3':
        raise ValueError('Rettungsdatei muss eine regulaere MP3-Datei ohne Symlink sein')
    candidate_data = probe(candidate)
    codec, video = audio_info(candidate_data)
    if codec != 'mp3' or video:
        raise ValueError('Rettungsdatei ist keine reine MP3')
    d_in, d_out = duration(src_data), duration(candidate_data)
    if (d_in is None or d_out is None or d_out <= 0
            or abs(d_in-d_out) > RECOVERY_DURATION_TOLERANCE):
        raise ValueError(f'Rettungsdatei hat unzulaessige Laufzeit: {d_in} -> {d_out}')
    test = subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
         '-i', str(candidate), '-map', '0:a:0', '-vn', '-f', 'null', '-'],
        capture_output=True, text=True)
    if test.returncode:
        raise ValueError(f'Rettungs-MP3 selbst nicht vollstaendig dekodierbar: {test.stderr.strip()}')
    info = dict(source=rel.as_posix(), target=dst_rel.as_posix(),
                source_sha256=sha256(src), target_sha256=sha256(candidate),
                source_duration=str(d_in), target_duration=str(d_out),
                note='Benutzergepruefte Rettungskodierung mit AAC-Decoderwarnungen; max. 2 s Zeitdifferenz')
    return candidate_data, info


def verify_recorded_recovery(src: Path, rel: Path, dst: Path, dst_rel: Path,
                             codec: str, src_data: dict, provenance: dict) -> dict:
    """Recover from a previous crash between recording recovery and checkpoint."""
    if provenance['source'] != rel.as_posix() or provenance['source_sha256'] != sha256(src):
        raise ValueError(f'Rettungsprotokoll-Quellhash stimmt nicht: {rel}')
    data = probe(dst)
    dst_codec, video = audio_info(data)
    if dst_codec != 'mp3' or video or provenance['target_sha256'] != sha256(dst):
        raise ValueError(f'Rettungsprotokoll-Zielhash oder Codec stimmt nicht: {rel}')
    d_in, d_out = duration(src_data), duration(data)
    if d_in is None or d_out is None or abs(d_in-d_out) > RECOVERY_DURATION_TOLERANCE:
        raise ValueError(f'Rettungsprotokoll-Ziellaufzeit unzulaessig: {rel}')
    return csv_report(src, rel, dst, dst_rel, RECOVERY_ACTION, codec, src_data, data)


def transcode_auto_rescue(src: Path, dst: Path, src_data: dict,
                          rel: Path, dst_rel: Path) -> tuple[dict, dict | None]:
    """Strict encode first; retry broken AAC once tolerantly and log provenance."""
    try:
        return transcode_verified(src, dst, src_data), None
    except ValueError as strict_exc:
        if dst.exists() or dst.is_symlink():
            raise ValueError(f'Strenger Versuch hat unerwartete Zieldatei hinterlassen: {dst_rel}') from strict_exc
        # The strict run might fail even on a malformed source; no original
        # file is ever modified. The tolerant encode writes a temporary MP3.
        fd, temp_path = tempfile.mkstemp(prefix='.mp3-tolerant-', suffix='.mp3', dir=dst.parent)
        os.close(fd)
        tmp = Path(temp_path)
        try:
            cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
                   '-i', str(src), '-map', '0:a:0', '-map_metadata', '0', '-vn',
                   '-c:a', 'libmp3lame', '-q:a', '0', '-id3v2_version', '3',
                   '-f', 'mp3', '-y', str(tmp)]
            run = subprocess.run(cmd, capture_output=True, text=True)
            if run.returncode or tmp.stat().st_size < 128:
                raise ValueError(f'Keine brauchbare tolerante Kodierung: {run.stderr[-700:]}')
            decoded = probe(tmp)
            out_codec, video = audio_info(decoded)
            d_in, d_out = duration(src_data), duration(decoded)
            if out_codec != 'mp3' or video or d_in is None or d_out is None or (
                    abs(d_in-d_out) > RECOVERY_DURATION_TOLERANCE):
                raise ValueError(f'Tolerante Kodierung zu kurz/lang: {d_in} -> {d_out} s')
            check = subprocess.run(
                ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
                 '-i', str(tmp), '-map', '0:a:0', '-vn', '-f', 'null', '-'],
                capture_output=True, text=True)
            if check.returncode:
                raise ValueError(f'Tolerante MP3 ist nicht fehlerfrei dekodierbar: {check.stderr[-500:]}')
            expected_hash = sha256(tmp)
            with tmp.open('rb') as fin, dst.open('xb') as fout:
                shutil.copyfileobj(fin, fout, 1024 * 1024)
                fout.flush()
                os.fsync(fout.fileno())
            if sha256(dst) != expected_hash:
                raise ValueError('Tolerante MP3 hat beim Kopieren falschen SHA-256-Wert')
            note = ('AUTO_RESCUE: strenger Versuch fehlgeschlagen: ' + str(strict_exc)[:250]
                    + '; Decoderwarnungen: ' + str(run.stderr.count('Error submitting packet'))
                    + '; tolerant_ffmpeg_exit=' + str(run.returncode))
            provenance = dict(source=rel.as_posix(), target=dst_rel.as_posix(),
                              source_sha256=sha256(src), target_sha256=expected_hash,
                              source_duration=str(d_in), target_duration=str(d_out),
                              note=note)
            return decoded, provenance
        finally:
            tmp.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--exclude-unreadable', action='append', default=[], metavar='REL_PATH')
    ap.add_argument('--exclude-failed', action='append', default=[], metavar='REL_PATH',
                    help='Only a previously recorded failed transcode with unchanged source hash')
    ap.add_argument('--execute', action='store_true', help='Validate existing output and resume; dry-run by default')
    ap.add_argument('--audit-existing', action='store_true',
                    help='Slow full hash/codec/duration audit of checkpointed MP3s')
    ap.add_argument('--recovery-source', metavar='REL_PATH', help='Exact source-relative damaged AAC to replace with an auditioned rescue MP3')
    ap.add_argument('--recovery-mp3', type=Path, help='Previously decoded, user-auditioned MP3; requires --recovery-source')
    args = ap.parse_args()
    for binary in ('ffmpeg', 'ffprobe'):
        import shutil
        if not shutil.which(binary):
            ap.error(f'Fehlt {binary}: sudo apt-get install ffmpeg')
    source = args.source.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=True)
    if not source.is_dir() or not output.is_dir() or output == source or \
       contained(output, source) or contained(source, output) or source == Path('/') or output == Path('/'):
        ap.error('Quelle oder vorhandenes Ausgabe-Verzeichnis ungueltig')
    if (output / MANIFEST).exists():
        ap.error('Konvertierungs-Manifest existiert bereits: Dieser Export ist abgeschlossen. '
                 'Fuer eine unabhaengige Nachpruefung scripts/verify_mp3_conversion.py verwenden.')
    if bool(args.recovery_source) != bool(args.recovery_mp3):
        ap.error('--recovery-source und --recovery-mp3 muessen gemeinsam angegeben werden')
    paths = list(args.exclude_unreadable) + list(args.exclude_failed)
    if args.recovery_source:
        paths.append(args.recovery_source)
    for name in paths:
        if not name or '\\' in name or Path(name).is_absolute() or any(x in ('', '.', '..') for x in name.split('/')):
            ap.error(f'Unsicherer Ausnahmepfad: {name!r}')
    if len(paths) != len(set(paths)):
        ap.error('Ausnahmepfade doppelt angegeben')
    tasks, skipped_videos, errors, exclusions = plan_files(source, set(args.exclude_unreadable))
    if errors:
        for error in errors:print('ABBRUCH:', error, file=sys.stderr)
        return 2
    failures_path = output / FAILURES
    fail_fields = ('source', 'target', 'source_sha256', 'reason')
    failures = load_csv(failures_path, fail_fields)
    by_failure = {(r['source'], r['source_sha256']): r for r in failures}
    omitted_tasks = []
    for path in args.exclude_failed:
        match = next((t for t in tasks if t[1].as_posix() == path), None)
        if match is None:
            ap.error(f'Nicht im aktiven Konvertierungsplan: {path}')
        src, rel, dst_rel, *_ = match
        failure = by_failure.get((path, sha256(src)))
        if not failure or failure['target'] != dst_rel.as_posix():
            ap.error(f'Kein bestaetigter frueherer Fehler mit identischem Quellhash: {path}')
        if (output / dst_rel).exists() or (output / dst_rel).is_symlink():
            ap.error(f'Auszunehmende Datei hat bereits ein Ziel: {dst_rel}')
        omitted_tasks.append(match)
        exclusions.append(dict(source=path, bytes=src.stat().st_size,
                               sha256=sha256(src), reason='Bestaetigter Fehlschlag: ' + failure['reason']))
    omitted_set = {x[1].as_posix() for x in omitted_tasks}
    tasks = [t for t in tasks if t[1].as_posix() not in omitted_set]
    expected_files = {t[2].as_posix().casefold() for t in tasks}
    allowed_logs = {PROGRESS, FAILURES, RECOVERIES}
    recoveries = load_csv(output / RECOVERIES, RECOVERY_FIELDS)
    recovery_records = {row['target']: row for row in recoveries}
    if len(recovery_records) != len(recoveries):
        ap.error('Doppelte Eintraege im Rettungsprotokoll')
    recovery_task = None
    recovery_candidate = None
    recovery_candidate_data = None
    recovery_info = None
    if args.recovery_source:
        recovery_task = next((task for task in tasks if task[1].as_posix() == args.recovery_source), None)
        if recovery_task is None or recovery_task[3] != 'aac_to_mp3':
            ap.error('Rettungskodierung erfordert exakt eine AAC-Quelldatei im aktiven Plan')
        recovery_candidate = args.recovery_mp3.expanduser().resolve(strict=True)
        if (contained(recovery_candidate, source) or contained(recovery_candidate, output)
                or recovery_candidate.is_symlink()):
            ap.error('Rettungs-MP3 muss ausserhalb von Quelle und MP3-Ziel liegen')
        try:
            recovery_candidate_data, recovery_info = validate_recovery(
                recovery_task[0], recovery_task[1], recovery_task[2],
                recovery_task[5], recovery_candidate)
        except (ValueError, OSError) as exc:
            ap.error(str(exc))
        previous = recovery_records.get(recovery_task[2].as_posix())
        if previous and previous != recovery_info:
            ap.error('Rettungskodierung unterscheidet sich vom vorhandenen Protokoll')
        if ((output / recovery_task[2]).exists() or (output / recovery_task[2]).is_symlink()) and not previous:
            ap.error('Rettungsziel existiert bereits ohne passendes Rettungsprotokoll')
        print(f'RETTUNGSMODUS: {recovery_task[1]} | Quelle {recovery_info["source_duration"]} s'
              f' -> MP3 {recovery_info["target_duration"]} s | {recovery_info["target_sha256"]}')

    for f in output.rglob('*'):
        if f.is_symlink():
            ap.error(f'Symlink im Ziel: {f.relative_to(output)}')
        if f.is_file() and f.relative_to(output).as_posix().casefold() not in expected_files \
                and f.relative_to(output).as_posix() not in allowed_logs:
            ap.error(f'Unbekannte Datei im Zieldirectory: {f.relative_to(output)}')
    checkpoint = output / PROGRESS
    rows = load_csv(checkpoint, FIELDS)
    plan_by_target = {t[2].as_posix():t for t in tasks}
    if len(plan_by_target) != len(tasks):
        ap.error('Doppelte Zieldateien im Plan')
    records = {}
    for row in rows:
        if row['target'] in records or row['target'] not in plan_by_target:
            ap.error(f'Unbekannter oder doppelter Checkpoint: {row["target"]}')
        records[row['target']] = row
    existing = sum((output / t[2]).is_file() for t in tasks)
    missing = [(i,t) for i,t in enumerate(tasks, 1) if not (output / t[2]).exists()]
    print(f'Quelle: {source}\nZiel: {output}')
    print(f'Geplant: {len(tasks)} MP3; vorhanden: {existing}; protokolliert: {len(records)}; '
          f'ausgenommen: {len(exclusions)}; Videos: {len(skipped_videos)}')
    if missing:
        idx, task = missing[0]
        print(f'Erste fehlende MP3: Position {idx}/{len(tasks)} | Quelle: {task[1]} | Ziel: {task[2]}')
    if not args.execute:
        print('TROCKENLAUF OK – nichts geschrieben. Alte MP3s ohne Checkpoint werden einmalig geprueft; vorhandene Checkpoints nur per Dateigroesse (SHA-256 mit --audit-existing).')
        return 0
    report = []
    reused = newly = current_errors = auto_rescued = 0
    for idx,(src,rel,dst_rel,action,codec,src_data) in enumerate(tasks,1):
        dst = output / dst_rel
        if not contained(dst.resolve(strict=False), output) or dst.is_symlink():
            raise ValueError(f'Unsicheres Ziel: {dst_rel}')
        dst.parent.mkdir(parents=True, exist_ok=True)
        was_present = dst.exists()
        try:
            if dst_rel.as_posix() in records:
                record = validate_row(records[dst_rel.as_posix()], src, rel, dst, dst_rel, action, codec, src_data,
                                      recovery_records, audit=args.audit_existing)
                reused += 1
            elif was_present:
                print(f'Pruefe bestehende Datei {idx}/{len(tasks)}: {dst_rel}', flush=True)
                provenance = recovery_records.get(dst_rel.as_posix())
                if provenance:
                    record = verify_recorded_recovery(src,rel,dst,dst_rel,codec,src_data,provenance)
                else:
                    record = verify_preexisting(src,rel,dst,dst_rel,action,codec,src_data)
                append_csv(checkpoint, record, FIELDS)
                reused += 1
            else:
                if recovery_task and rel == recovery_task[1]:
                    print(f'Uebernehme nach Benutzerfreigabe Rettungs-MP3 {idx}/{len(tasks)}: {rel}', flush=True)
                    with recovery_candidate.open('rb') as inp, dst.open('xb') as out:
                        shutil.copyfileobj(inp, out, 1024 * 1024)
                        out.flush(); os.fsync(out.fileno())
                    if sha256(dst) != recovery_info['target_sha256'] or (
                        dst.stat().st_size != recovery_candidate.stat().st_size):
                        raise ValueError(f'Rettungs-MP3 Kopie hat Hash-/Groessenfehler: {rel}')
                    append_csv(output / RECOVERIES, recovery_info, RECOVERY_FIELDS)
                    recovery_records[dst_rel.as_posix()] = recovery_info
                    data = recovery_candidate_data
                    record = csv_report(src,rel,dst,dst_rel,RECOVERY_ACTION,codec,src_data,data)
                else:
                    print(f'Konvertiere {idx}/{len(tasks)}: {rel}', flush=True)
                    if action == 'copy_mp3':
                        copy_verified(src, dst)
                        data = src_data
                    else:
                        data, auto_provenance = transcode_auto_rescue(src, dst, src_data, rel, dst_rel)
                        if auto_provenance:
                            print(f'AUTO-RETTUNG (anhoeren!): {rel} | '
                                  f'{auto_provenance["source_duration"]} -> '
                                  f'{auto_provenance["target_duration"]} Sekunden', flush=True)
                            auto_rescued += 1
                            append_csv(output / RECOVERIES, auto_provenance, RECOVERY_FIELDS)
                            recovery_records[dst_rel.as_posix()] = auto_provenance
                            action = RECOVERY_ACTION
                    record = csv_report(src,rel,dst,dst_rel,action,codec,src_data,data)
                append_csv(checkpoint, record, FIELDS)
                newly += 1
            report.append(record)
            if idx % 100 == 0:print(f'Verifiziert: {idx}/{len(tasks)} (wiederverwendet {reused}, neu {newly})',flush=True)
        except Exception as exc:
            if not was_present:
                dst.unlink(missing_ok=True)
            try:
                append_csv(failures_path, dict(source=rel.as_posix(), target=dst_rel.as_posix(),
                        source_sha256=sha256(src),reason=str(exc)), fail_fields)
            except OSError as log_err:
                print(f'WARNUNG: Fehlerprotokoll konnte nicht gespeichert werden: {log_err}', file=sys.stderr)
            print(f'FEHLER bei {idx}/{len(tasks)}: {rel}: {exc} (weiter mit naechster Datei)', file=sys.stderr)
            current_errors += 1
            continue
    # On unresolved errors retain checkpoints and error log, but never claim a
    # complete library or write a final manifest.
    if current_errors:
        print(f'UNVOLLSTAENDIG: {len(report)}/{len(tasks)} MP3s erfolgreich; '
              f'{current_errors} Fehler, siehe {FAILURES}; '
              f'Resuming ist ohne Ueberschreiben moeglich.')
        return 3
    # Do not claim success before both final manifests are written.
    if exclusions:
        excl_path = output / EXCLUSIONS_MANIFEST
        with excl_path.open('x', newline='', encoding='utf-8-sig') as fh:
            writer = csv.DictWriter(fh, fieldnames=['source','bytes','sha256','reason'], delimiter=';')
            writer.writeheader();writer.writerows(exclusions)
    with (output / MANIFEST).open('x', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter=';')
        writer.writeheader();writer.writerows(report)
    print(f'PASS: {len(report)} MP3s, wiederverwendet {reused}, neu {newly}, '
          f'automatisch gerettet {auto_rescued}. '
          f'Originale unveraendert; Ausnahmen {len(exclusions)}; Manifest: {MANIFEST}')
    if auto_rescued:
        print(f'BITTE ANHOEREN: {auto_rescued} automatische Rettungsfassung(en) in {RECOVERIES}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
