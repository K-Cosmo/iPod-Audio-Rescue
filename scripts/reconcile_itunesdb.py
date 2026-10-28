#!/usr/bin/env python3
"""Merge the iPod's original iTunesDB with an existing tag-based rebuild-plan CSV.

Read-only; does not need media files, does not communicate with the iPod.
Requires parse_itunesdb.py in same directory. No third-party packages.
"""
from __future__ import annotations
import argparse
import csv
import re
from collections import Counter,defaultdict
from pathlib import Path
from parse_itunesdb import parse
from rebuild_ipod_library import safe_name  # same naming semantics as original planner

COLS = ['status','source','target','suggested_target','artist','album_artist','album','title',
        'track','disc','compilation','itunesdb_compilation','itunesdb_media_type','itunesdb_track_id',
        'itunesdb_file_size','itunesdb_duration_ms','db_match','original_status','reason','original_target',
        'metadata_changes','review_detail']

def keypath(s):
    return s.lstrip(':').replace(':','/').casefold()

def suggestion(folder, r):
    # Only suggest a name, never assert an unknown track number.
    prefix = f"{int(r['track']):02d}" if r['track'].isdigit() and int(r['track'])>0 else '00'
    if r['disc'].isdigit() and int(r['disc'])>1:
        prefix=f"CD{int(r['disc']):02d} - {prefix}"
    name=safe_name(f"{prefix} - {r['artist']} - {r['title']}",limit=140)
    return f"{safe_name(folder)}/{name}{Path(r['source']).suffix.lower()}"

def main():
    p=argparse.ArgumentParser(description='iTunesDB metadata reconciliation; never alters raw files')
    p.add_argument('--itunesdb',type=Path,required=True)
    p.add_argument('--old-plan',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    db,sections=parse(a.itunesdb)
    bypath={keypath(r['path']):r for r in db}
    if len(bypath)!=len(db):raise SystemExit('ABBRUCH: Duplicate file paths in iTunesDB')
    with a.old_plan.open(encoding='utf-8-sig',newline='') as f:
        old=list(csv.DictReader(f,delimiter=';'))
    oldkeys=[keypath(r['source']) for r in old]
    if len(oldkeys)!=len(set(oldkeys)): raise SystemExit('ABBRUCH: Multiple plan rows for one source')
    if a.out.exists():raise SystemExit('ABBRUCH: Output file exists (no overwrite)')
    if a.out.resolve() in {a.itunesdb.resolve(),a.old_plan.resolve()}:raise SystemExit('ABBRUCH: Output equals input')
    output=[]
    for r in old:
        key=keypath(r['source']);d=bypath.get(key)
        item={k:'' for k in COLS}
        for k in ('source','artist','album_artist','album','title','track','disc','compilation','target','reason'):
            item[k]=r.get(k,'')
        item['original_status']=r['status']; item['original_target']=r['target']
        item['db_match']='yes' if d else 'no'
        changes=[]
        if not d:
            item['status']='review_unindexed_audio' if Path(r['source']).suffix.lower() not in {'.m4v','.mp4','.mov','.avi','.mpeg','.mpg'} else 'review_unindexed_video'
            item['target']=''
            item['reason']='Kein iTunesDB-Eintrag; Datei gesondert pruefen, nicht verwerfen'
            item['review_detail']='Nicht als Bibliothekseintrag auf dem iPod nachgewiesen'
        else:
            item.update(itunesdb_compilation=d['compilation'],itunesdb_media_type=str(d['mediatype']),
                        itunesdb_track_id=str(d['track_id']),itunesdb_file_size=str(d['file_size_db']),
                        itunesdb_duration_ms=str(d['duration_ms']))
            for f in ('artist','album_artist','album','title'):
                value=d.get(f,'').strip()
                if not item[f].strip() and value:
                    item[f]=value;changes.append(f'{f}: aus iTunesDB ergaenzt')
            # Use database's nonzero track number only if the tags lack one; never infer numbers.
            for f in ('track','disc'):
                if (not item[f].strip() or item[f]=='0') and int(d.get(f,0))>0:
                    item[f]=str(d[f]);changes.append(f'{f}: aus iTunesDB ergaenzt')
            if not item['compilation']:
                item['compilation']=str(int(d['compilation']));changes.append('compilation: iTunesDB')
            mt=d['mediatype']
            if mt in (2,6) or Path(r['source']).suffix.lower() in {'.m4v','.mp4','.mov','.avi','.mpeg','.mpg'}:
                item['status']='video_ready'
                item['target']='Videos/'+safe_name(d.get('album') or 'Unsortiert')+'/'+safe_name(d['title'] or Path(r['source']).stem)+Path(r['source']).suffix.lower()
                item['reason']='Video; aus iTunesDB zugeordnet; nicht als Audiodatei im Audioexport ausgeben'
                item['review_detail']=''
            elif mt==4:
                item['status']='podcast_ready'
                item['target']='Podcasts/'+safe_name(item['album'] or 'Podcasts')+'/'+safe_name('00 - '+item['artist']+' - '+item['title'],140)+Path(r['source']).suffix.lower()
                item['reason']='Podcast; Tracknummer 0, 00 ist ein Platzhalter (keine belegte Reihenfolge)'
                item['review_detail']=''
            elif mt==1:
                missing=[f for f in ('artist','album','title') if not item[f].strip()]
                if not item['track'] or not item['track'].isdigit() or int(item['track'])==0:missing.append('track')
                if missing:
                    item['status']='review_metadata'
                    item['target']=''
                    item['reason']='Auch iTunesDB unvollstaendig: '+', '.join(missing)
                    item['review_detail']='Nur Vorschlag; keine erfundene Titelnummer' if missing==['track'] else 'Manuelle Zuordnung erforderlich'
                    if all(item[f] for f in ('artist','album','title')):
                        folder=(item['album'] if item['compilation']=='1' else f"{item['album_artist'] or item['artist']} - {item['album']}")
                        item['suggested_target']=suggestion(folder,item)
                else:
                    item['status']='ready'
                    item['reason']=''
                    # Preserve existing checked target to avoid unrelated renames.
                    if not item['target']:
                        folder=item['album'] if item['compilation']=='1' else f"{item['album_artist'] or item['artist']} - {item['album']}"
                        item['target']=suggestion(folder,item)
            else:
                item['status']='review_unknown_media'
                item['target']=''
                item['reason']=f'Unbekannter iTunesDB Medientyp {mt}'
            # Metadata comparison: informational only, not silent replacement.
            for f in ('artist','album','title'):
                tv=(r.get(f,'') or '').strip()
                dv=(d.get(f,'') or '').strip()
                if tv and dv and tv!=dv:
                    changes.append(f'{f}: Tags / iTunesDB unterschiedlich')
        item['metadata_changes']=' | '.join(changes)
        output.append(item)
    # Consistent-artist albums: on this old library a compilation bit is often
    # erroneously set for EVERY track of an ordinary artist album. The explicit
    # album artist or an overwhelming dominant primary artist is better evidence.
    # This changes ONLY planned destination names, never source tags/bytes.
    # This heuristic requires manual approval of the CSV before exporting.
    albums=defaultdict(list)
    for item in output:
        if item['itunesdb_media_type']=='1' and item['album']:
            albums[item['album'].casefold()].append(item)
    featuring=re.compile(r'\s+(?:feat\.?|featuring|ft\.?|mit)\s+',flags=re.I)
    automatic=[]
    for album, members in albums.items():
        if len(members)<5 or not any(x['compilation']=='1' for x in members):
            continue
        bases=[]
        for item in members:
            base=featuring.split(item['artist'])[0].strip()
            if base:bases.append(base)
        major=Counter(x.casefold() for x in bases).most_common(1)
        if not major or len(bases)!=len(members):
            continue
        main,n=major[0]
        if n/len(members)<0.85 or main in ('various artists','various','diverse interpreten'):
            continue
        artist=next(x for x in bases if x.casefold()==main)
        automatic.append((album,artist,len(members)))
        for item in members:
            folder=f"{artist} - {item['album']}"
            proposed=suggestion(folder,item)
            message=f"Kuenstleralbum-Korrektur: {artist}, {len(members)} zugeordnete Albumtitel; Compilation-Flag fuer Zielordner ignoriert"
            item['metadata_changes']=(item['metadata_changes']+' | '+message).strip(' |')
            if item['status'] in ('ready','review_compilation'):
                item['status']='ready'
                item['target']=proposed
                item['reason']=''
                item['review_detail']=message
                item['suggested_target']=''
            elif item['status']=='review_metadata':
                item['suggested_target']=proposed
                item['review_detail']=message+'; andere Metadaten fehlen weiterhin'
    # No duplicates even under Windows' case-insensitive filesystem.
    targets=defaultdict(list)
    for item in output:
        if item['target']:
            targets[item['target'].casefold()].append(item)
    coll={k:v for k,v in targets.items() if len(v)>1}
    for rows in coll.values():
        for r in rows:
            r['status']='review_collision';r['suggested_target']=r['target'];r['target']=''
            r['reason']='Mehrere Quelldateien mit gleichem Zielnamen; manuell aufloesen'
    a.out.parent.mkdir(parents=True,exist_ok=True)
    with a.out.open('x',encoding='utf-8-sig',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=COLS,delimiter=';');w.writeheader();w.writerows(output)
    print('iTunesDB entries',len(db),'old plan entries',len(old),'matched',sum(x['db_match']=='yes' for x in output))
    print('Status',dict(Counter(x['status'] for x in output)))
    print('Automatically reconciled album groups',automatic)
    print('Target collisions',len(coll))
    print('Wrote',a.out)
if __name__=='__main__':main()
