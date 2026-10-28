#!/usr/bin/env python3
"""Strict, read-only parser of iTunesDB track-list sections from mhbd/mhsd/mhlt/mhit/mhod.
Reference for binary field offsets: libgpod itdb_itunesdb.c (LGPL).
"""
from pathlib import Path
from collections import Counter
import argparse, csv, struct, sys
TYPES={1:'title',2:'path',3:'album',4:'artist',5:'genre',6:'filetype',8:'comment',12:'composer',13:'grouping',14:'description',18:'subtitle',19:'tvshow',20:'tvepisode',21:'tvnetwork',22:'album_artist',23:'keywords'}
def parse(p):
    b=Path(p).read_bytes(); n=len(b)
    def num(o):
        if o<0 or o+4>n:raise ValueError(f'Out-of-bounds integer at {o}')
        return struct.unpack_from('<I',b,o)[0]
    def head(o, tag, limit):
        if o+12>limit or b[o:o+4]!=tag:raise ValueError(f'Expected {tag!r} at {o}')
        hl,sz=num(o+4),num(o+8)
        if hl<12 or sz<hl or o+sz>limit:raise ValueError(f'Invalid {tag!r} sizes at {o}: header={hl}, total={sz}')
        return hl,sz
    hl,sz=head(0,b'mhbd',n)
    if sz!=n: raise ValueError(f'File length mismatch {sz} != {n}')
    section=hl
    sections=[]
    while section<n:
        h,ss=head(section,b'mhsd',n)
        sections.append((section,section+ss,num(section+12)))
        section+=ss
    if section!=n:raise ValueError('Trailing data')
    track_sections=[(start,end) for start,end,typ in sections if typ==1]
    if len(track_sections)!=1:raise ValueError(f'Expected one track section, found {len(track_sections)}')
    start,end=track_sections[0]
    slen=num(start+4); hl_off=start+slen
    if b[hl_off:hl_off+4]!=b'mhlt':raise ValueError('Missing track list header')
    total=num(hl_off+8);o=hl_off+num(hl_off+4)
    tracks=[]
    for _ in range(total):
        h,sz=head(o,b'mhit',end)
        count=num(o+12)
        record={'db_index':len(tracks)+1,'track_id':num(o+16),'compilation':b[o+30],'file_size_db':num(o+36),'duration_ms':num(o+40),'track':num(o+44),'disc':num(o+92) if h>=96 else 0,'mediatype':num(o+208) if h>=212 else 0}
        child=o+h
        for _child in range(count):
            hh,ll=head(child,b'mhod',o+sz)
            typ=num(child+12)
            if typ in TYPES:
                st=child+hh
                if st+16>child+ll:raise ValueError(f'MHOD too short {child}')
                encoding=num(st); length=num(st+4)
                if st+16+length>child+ll:raise ValueError(f'MHOD overrun {child}')
                raw=b[st+16:st+16+length]
                if encoding==2:
                    val=raw.decode('utf-8',errors='replace')
                else:
                    val=raw.decode('utf-16-le',errors='replace')
                record[TYPES[typ]]=val.rstrip('\0')
            child+=ll
        if child!=o+sz:raise ValueError(f'MHOD lengths mismatch at {o} expected end {o+sz}, actual {child}')
        tracks.append(record)
        o+=sz
    if o!=end:raise ValueError(f'Track section trailing data {end-o}')
    return tracks, sections
if __name__=='__main__':
    ar=argparse.ArgumentParser();ar.add_argument('database',type=Path);ar.add_argument('--csv',type=Path);a=ar.parse_args()
    tracks, sections=parse(a.database)
    print('sections',sections,'tracks',len(tracks),'mediatype',Counter(t['mediatype'] for t in tracks))
    print('examples',tracks[:2])
    print('missing fields',{k:sum(not t.get(k) for t in tracks) for k in ['path','artist','title','album','track']})
    if a.csv:
        fields=['db_index','track_id','path','artist','album_artist','album','title','track','disc','compilation','mediatype','file_size_db','duration_ms','genre','filetype']
        with a.csv.open('w',newline='',encoding='utf-8-sig') as fh:
            w=csv.DictWriter(fh,fieldnames=fields,delimiter=';',extrasaction='ignore');w.writeheader();w.writerows(tracks)
