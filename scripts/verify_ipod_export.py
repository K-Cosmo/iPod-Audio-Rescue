#!/usr/bin/env python3
"""Independently check the exported files against the exporter's SHA-256 manifest.

Read-only. Optional --raw rehashes source files from an independent raw backup.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path


def safe_relative(name: str) -> Path:
    if not name or '\\' in name or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError(f'Invalid relative path: {name!r}')
    path = Path(name)
    if path.is_absolute():
        raise ValueError(f'Absolute path in manifest: {name!r}')
    return path


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--export-root', type=Path, required=True)
    ap.add_argument('--raw', type=Path, help='Optional original raw-backup root; also check each source')
    ap.add_argument('--strict', action='store_true', help='Also fail on unlisted files inside export root')
    args = ap.parse_args()
    root = args.export_root.expanduser().resolve(strict=True)
    raw = args.raw.expanduser().resolve(strict=True) if args.raw else None
    if not root.is_dir() or (raw and (not raw.is_dir() or raw == root)):
        ap.error('Invalid export/raw root')
    manifest = root / '_verification_manifest.csv'
    if not manifest.is_file() or manifest.is_symlink():
        ap.error('Export manifest missing or symbolic link')

    errors: list[str] = []
    seen_src: set[str] = set()
    seen_dst: set[str] = set()
    count = total = 0
    with manifest.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream, delimiter=';')
        if reader.fieldnames != ['source', 'target', 'bytes', 'sha256']:
            ap.error('Unexpected manifest columns')
        for line, row in enumerate(reader, 2):
            try:
                src_rel = safe_relative(row['source'])
                dst_rel = safe_relative(row['target'])
                src_key = src_rel.as_posix().casefold()
                dst_key = dst_rel.as_posix().casefold()
                if src_key in seen_src or dst_key in seen_dst:
                    raise ValueError('Duplicate source or destination')
                seen_src.add(src_key)
                seen_dst.add(dst_key)
                expected_size = int(row['bytes'])
                expected_hash = row['sha256'].lower()
                if expected_size < 0 or not re.fullmatch(r'[0-9a-f]{64}', expected_hash):
                    raise ValueError('Invalid size or SHA-256')
                dst = root / dst_rel
                if not dst.resolve().is_relative_to(root) or not dst.is_file() or dst.is_symlink():
                    raise ValueError('Missing, linked or out-of-root destination')
                if dst.stat().st_size != expected_size or checksum(dst) != expected_hash:
                    raise ValueError('Exported file size/hash mismatch')
                if raw:
                    src = raw / src_rel
                    if not src.resolve().is_relative_to(raw) or not src.is_file() or src.is_symlink():
                        raise ValueError('Missing, linked or out-of-root source')
                    if src.stat().st_size != expected_size or checksum(src) != expected_hash:
                        raise ValueError('Raw source size/hash mismatch')
                count += 1
                total += expected_size
            except (ValueError, OSError, KeyError, TypeError) as exc:
                errors.append(f'CSV line {line}: {exc}')
    if args.strict:
        for f in root.rglob('*'):
            if f.is_symlink():
                errors.append(f'Unexpected symlink: {f.relative_to(root)}')
            elif f.is_file() and f != manifest and f.relative_to(root).as_posix().casefold() not in seen_dst:
                errors.append(f'Unlisted file: {f.relative_to(root)}')
    if errors:
        for msg in errors[:25]:
            print('FAIL:', msg)
        if len(errors) > 25:
            print(f'... {len(errors)-25} additional error(s)')
        return 1
    print(f'PASS: {count} files, {total} bytes, SHA-256 verified' + (' against export and raw backup' if raw else ' in export'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
