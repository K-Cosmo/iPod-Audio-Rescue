#!/usr/bin/env python3
"""Independent read-only SHA-256 audit of a completed MP3 conversion.

Requires the _mp3_conversion_manifest.csv written by convert_audio_to_mp3.py.
Optionally hashes all original audio files as well.
No media is changed, decoded, renamed or deleted.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

FIELDS = ['source','target','source_codec','source_bytes','source_sha256',
          'target_bytes','target_sha256','action','source_duration','target_duration']
RECOVERY_FIELDS = ['source','target','source_sha256','target_sha256',
                   'source_duration','target_duration','note']
ACTIONS = {'copy_mp3','aac_to_mp3','alac_to_mp3','flac_to_mp3',
           'pcm_s16le_to_mp3','pcm_s24le_to_mp3','pcm_s32le_to_mp3',
           'pcm_f32le_to_mp3','mp3_to_mp3','recovered_aac_to_mp3'}
OTHER_REPORTS = {'_mp3_conversion_manifest.csv','_mp3_conversion_progress.csv',
                 '_mp3_conversion_recoveries.csv','_mp3_conversion_failures.csv',
                 '_mp3_conversion_exclusions.csv'}


def relative(value: str) -> Path:
    if not value or '\\' in value or value.startswith('/') or any(
        part in ('','.','..') for part in value.split('/')
    ):
        raise ValueError(f'Unsafe relative file path: {value!r}')
    return Path(*PurePosixPath(value).parts)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def checked_file(root: Path, name: str) -> Path:
    f = root / relative(name)
    if f.is_symlink() or not f.is_file() or not f.resolve().is_relative_to(root):
        raise ValueError(f'Missing, linked or external file: {name}')
    return f


def csv_rows(path: Path, columns: list[str]) -> list[dict[str,str]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Missing or linked CSV: {path}')
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream, delimiter=';')
        if reader.fieldnames != columns:
            raise ValueError(f'Unexpected CSV headers: {path.name}')
        rows = list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError(f'Incomplete CSV: {path.name}')
        return rows


def valid_hash(value: str) -> bool:
    return bool(re.fullmatch(r'[a-fA-F0-9]{64}',value))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mp3-root', required=True, type=Path)
    ap.add_argument('--source', type=Path, help='Verified structured audio export; hash original files too')
    ap.add_argument('--strict', action='store_true', help='Reject unknown files in the MP3 destination')
    args = ap.parse_args()
    root = args.mp3_root.expanduser().resolve(strict=True)
    source = args.source.expanduser().resolve(strict=True) if args.source else None
    if not root.is_dir() or root == Path('/') or (source and (
        not source.is_dir() or source == root or source.is_relative_to(root) or root.is_relative_to(source)
    )):
        ap.error('Invalid or overlapping directories')
    try:
        records = csv_rows(root/'_mp3_conversion_manifest.csv', FIELDS)
        if not records:
            raise ValueError('Empty MP3 conversion manifest')
        recovery_file = root/'_mp3_conversion_recoveries.csv'
        recoveries = csv_rows(recovery_file, RECOVERY_FIELDS) if recovery_file.exists() else []
        unique_recoveries = {}
        for r in recoveries:
            relative(r['source']); relative(r['target'])
            if not valid_hash(r['source_sha256']) or not valid_hash(r['target_sha256']):
                raise ValueError('Invalid recovery SHA-256')
            if r['target'].casefold() in unique_recoveries:
                raise ValueError('Duplicate recovery target')
            unique_recoveries[r['target'].casefold()] = r
        count = 0
        total = 0
        actions = Counter()
        seen_dst = set()
        seen_src = set()
        recovered_targets = set()
        for line, r in enumerate(records,2):
            try:
                src_rel = relative(r['source'])
                dst_rel = relative(r['target'])
                src_key, dst_key = src_rel.as_posix().casefold(), dst_rel.as_posix().casefold()
                if src_key in seen_src or dst_key in seen_dst:
                    raise ValueError('Duplicate source or target')
                seen_src.add(src_key); seen_dst.add(dst_key)
                if dst_rel.suffix.lower() != '.mp3' or r['action'] not in ACTIONS:
                    raise ValueError('Invalid target suffix or action')
                size_out = int(r['target_bytes'])
                size_in = int(r['source_bytes'])
                if size_out < 128 or size_in < 0 or not valid_hash(r['target_sha256']) or not valid_hash(r['source_sha256']):
                    raise ValueError('Invalid size/hash')
                out = checked_file(root,r['target'])
                if out.stat().st_size != size_out or sha256(out) != r['target_sha256'].lower():
                    raise ValueError('MP3 size or SHA-256 mismatch')
                if source:
                    inp = checked_file(source,r['source'])
                    if inp.stat().st_size != size_in or sha256(inp) != r['source_sha256'].lower():
                        raise ValueError('Original size or SHA-256 mismatch')
                if r['action'] == 'copy_mp3' and (
                    r['source_sha256'].lower() != r['target_sha256'].lower() or size_in != size_out
                ):
                    raise ValueError('Copied MP3 must be byte-identical')
                d1, d2 = float(r['source_duration']),float(r['target_duration'])
                if d1 <= 0 or d2 <= 0 or not (d1 < float('inf') and d2 < float('inf')):
                    raise ValueError('Invalid duration')
                duration_limit = 2.0 if r['action'] == 'recovered_aac_to_mp3' else 1.0
                if abs(d1-d2) > duration_limit:
                    raise ValueError('Unexpected duration difference')
                if r['action'] == 'recovered_aac_to_mp3':
                    recovery = unique_recoveries.get(dst_key)
                    if not recovery or any(
                        recovery[key] != r[key] for key in ('source','target','source_sha256','target_sha256')
                    ):
                        raise ValueError('Recovery provenance missing or mismatched')
                    recovered_targets.add(dst_key)
                total += size_out
                count += 1
                actions[r['action']] += 1
            except (ValueError, OSError, KeyError) as exc:
                raise ValueError(f'Manifest line {line}: {exc}') from exc
        if set(unique_recoveries) != recovered_targets:
            raise ValueError('Unmatched rows in recovery log')
        if args.strict:
            for item in root.rglob('*'):
                rel = item.relative_to(root).as_posix()
                if item.is_symlink():
                    raise ValueError(f'Unexpected symlink: {rel}')
                if item.is_file() and rel.casefold() not in seen_dst and rel not in OTHER_REPORTS:
                    raise ValueError(f'Unlisted output file: {rel}')
        print(f'PASS: {count} MP3 files, {total} bytes; SHA-256 verified'
              + (' against MP3 output AND original audio source' if source else ' against MP3 output'))
        print('Methods:', dict(actions))
        print(f'Recovery records: {len(recoveries)}')
        if not source:
            print('NOTE: provide --source to independently re-hash original audio files.')
        return 0
    except (ValueError, OSError, csv.Error) as exc:
        print('FAIL:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
