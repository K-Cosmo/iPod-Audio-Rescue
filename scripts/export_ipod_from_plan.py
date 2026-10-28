#!/usr/bin/env python3
"""Copy a reviewed iTunesDB/metadata plan without touching the source.

Default: dry-run only. --execute copies byte-for-byte, no overwrites, SHA-256
verification for every file, export manifest. Only statuses ready, optional
podcast_ready/video_ready, are ever accepted. All review statuses are excluded.
"""
from __future__ import annotations
import argparse, csv, hashlib, os
from collections import Counter
from pathlib import Path

ALLOWED={'ready'}

def contained(child,root):
    try:child.relative_to(root);return True
    except ValueError:return False

def relative_path(s,label):
    p=Path(s)
    if not s or p.is_absolute() or any(part in ('','.', '..') for part in s.split('/')) or '\\' in s:
        raise ValueError(f'Unsafe {label} path: {s!r}')
    return p

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def copy_and_verify(src,dst):
    # Copy to a file created exclusively and never replace an existing file.
    dst.parent.mkdir(parents=True,exist_ok=True)
    h=hashlib.sha256(); created=False
    try:
        with src.open('rb') as fin, dst.open('xb') as fout:
            created=True
            for buf in iter(lambda:fin.read(1024*1024),b''):
                h.update(buf);fout.write(buf)
            fout.flush();os.fsync(fout.fileno())
        if src.stat().st_size!=dst.stat().st_size or digest(dst)!=h.hexdigest():
            raise OSError(f'SHA-256 verification failed: {src}')
        return (src.stat().st_size,h.hexdigest())
    except Exception:
        if created and dst.exists():dst.unlink()
        raise

def main():
    pa=argparse.ArgumentParser(description='Safe export using reviewed iTunesDB plan. Default: no file copies.')
    pa.add_argument('--source',required=True,type=Path,help='RAW backup root containing iTunes_Control')
    pa.add_argument('--plan',required=True,type=Path,help='Reconciled iTunesDB CSV')
    pa.add_argument('--output',required=True,type=Path,help='NEW empty output directory, not source')
    pa.add_argument('--include-podcasts',action='store_true')
    pa.add_argument('--include-videos',action='store_true')
    pa.add_argument('--execute',action='store_true')
    a=pa.parse_args()
    srcroot=a.source.expanduser().resolve(strict=True)
    plan=a.plan.expanduser().resolve(strict=True)
    output=a.output.expanduser().resolve(strict=False)
    if not srcroot.is_dir() or srcroot==Path('/') or not (srcroot/'iTunes_Control').is_dir():pa.error('Source is not a valid raw iPod backup')
    if contained(output,srcroot) or contained(srcroot,output):pa.error('Output and raw source cannot contain each other')
    if contained(plan,output) or contained(plan,srcroot):pa.error('Plan CSV must be outside raw source and destination')
    allow=set(ALLOWED)
    if a.include_podcasts:allow.add('podcast_ready')
    if a.include_videos:allow.add('video_ready')
    with plan.open('r',encoding='utf-8-sig',newline='') as fh:allrows=list(csv.DictReader(fh,delimiter=';'))
    wanted=[r for r in allrows if r.get('status','') in allow]
    blocked=Counter(r.get('status','') for r in allrows if r.get('status','') not in allow)
    if not wanted:pa.error('No eligible entries')
    targets=set();entries=[]
    for r in wanted:
        relsrc=relative_path(r['source'],'source')
        reldst=relative_path(r['target'],'target')
        if str(relsrc.parts[0])!='iTunes_Control':pa.error(f'Unexpected source path: {relsrc}')
        k=reldst.as_posix().casefold()
        if k in targets:pa.error(f'Duplicate destination (Windows casefold): {reldst}')
        targets.add(k)
        real_source=(srcroot/relsrc).resolve(strict=True)
        if not contained(real_source,srcroot):pa.error(f'Source symlink escapes raw backup: {relsrc}')
        if not real_source.is_file():pa.error(f'Not a source file: {relsrc}')
        entries.append((r,real_source,reldst))
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        pa.error('Output must be new or empty (never overwrite a prior export)')
    total=sum(s.stat().st_size for _,s,_ in entries)
    print('Export plan:',plan,'\nSource:',srcroot,'\nOutput:',output)
    print('Ready files:',len(entries),'Total bytes:',total, 'Blocked/unselected:',dict(blocked))
    if not a.execute:
        print('DRY RUN ONLY. No files copied. Use --execute after reviewing the CSV and destination.')
        return
    output.mkdir(parents=True,exist_ok=True)
    with (output/'_verification_manifest.csv').open('x',newline='',encoding='utf-8-sig') as manifest:
        writer=csv.writer(manifest,delimiter=';')
        writer.writerow(['source','target','bytes','sha256'])
        for i,(r,source,target) in enumerate(entries,1):
            final=output/target
            if not contained(final.resolve(strict=False),output):
                raise ValueError(f'Destination escapes output (symlink?): {target}')
            size,sha=copy_and_verify(source,final)
            writer.writerow([r['source'],target.as_posix(),size,sha]);manifest.flush()
            if i%100==0 or i==len(entries):print(f'Verified {i}/{len(entries)}')
    print('SUCCESS: all selected copies SHA-256 verified; no source files modified.')
if __name__=='__main__':main()
