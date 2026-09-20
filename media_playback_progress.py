"""Per-TV media playhead. No grant, source capability or decoder is stored here."""
import hashlib
import hmac
import math
import re

from flask import request
from household_media import MediaError

SCHEMA_SQL = '''CREATE TABLE media_playback_progress(
 device_id TEXT PRIMARY KEY NOT NULL REFERENCES media_playback(device_id) ON DELETE CASCADE,
 item_id TEXT NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
 item_revision INTEGER NOT NULL CHECK(typeof(item_revision)='integer' AND item_revision>0),
 play_id TEXT NOT NULL CHECK(length(play_id)=24),
 position_ms INTEGER NOT NULL CHECK(typeof(position_ms)='integer' AND position_ms BETWEEN 0 AND 600250),
 report_seq INTEGER NOT NULL CHECK(typeof(report_seq)='integer' AND report_seq BETWEEN 0 AND 9007199254740990),
 reported_at REAL NOT NULL CHECK(reported_at>=0));'''


def initialize_progress(con):
    if con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Playback progress requires an idle foreign-key connection')
    found=con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='media_playback_progress'").fetchone()
    if found:
        if found[0].strip().rstrip(';') != SCHEMA_SQL.strip().rstrip(';'):
            raise RuntimeError('Playback progress schema mismatch')
        return
    try:
        con.execute('BEGIN IMMEDIATE')
        con.execute(SCHEMA_SQL)
        con.commit()
    except BaseException:
        con.rollback()
        raise


def mac(library, purpose, *values):
    secret=library.app.secret_key
    if isinstance(secret,str):secret=secret.encode('utf-8')
    message='\0'.join(('tv-playback-v1',purpose,library.household,*map(str,values))).encode('utf-8')
    return hmac.new(secret,message,hashlib.sha256).hexdigest()


def csrf(library, device, now):
    # Expiry cannot exceed the device or display lease. Integer milliseconds
    # avoid granting a fractional second beyond the actual TV deadline.
    issued=math.floor(now*1000);expires=math.floor(min(now+15,device['expires'])*1000)
    cookie=hashlib.sha256(request.cookies.get('household_tv','').encode()).hexdigest()
    return f'{issued}.{expires}.'+mac(library,'csrf',device['id'],cookie,issued,expires)


def check_csrf(library, device, now):
    origin=request.headers.get('Origin')
    if (request.method!='POST' or request.headers.get('X-Display-Mode')!='tv'
            or origin!=request.host_url.rstrip('/') or not request.is_json):
        raise MediaError('forbidden')
    token=request.headers.get('X-TV-Playback-CSRF','')
    if not re.fullmatch(r'\d{1,16}\.\d{1,16}\.[0-9a-f]{64}',token):
        raise MediaError('forbidden')
    issued,expires,signature=token.split('.');issued=int(issued);expires=int(expires)
    cookie=hashlib.sha256(request.cookies.get('household_tv','').encode()).hexdigest()
    expected=mac(library,'csrf',device['id'],cookie,issued,expires)
    if (not issued<=now*1000<expires or not 0<expires-issued<=15000
            or expires>math.floor(device['expires']*1000) or not hmac.compare_digest(signature,expected)):
        raise MediaError('forbidden')


def resolve(library, con, state, rows):
    """GET projection is read-only; stale/revoked selection gets a fresh generation."""
    if state['mode']!='photos' or not rows:return None,0
    stored=con.execute('SELECT * FROM media_playback_progress WHERE device_id=?',(state['device_id'],)).fetchone()
    if stored:
        for index,row in enumerate(rows):
            if (stored['item_id'],stored['item_revision'])==(row['id'],row['revision']):
                return dict(stored),index
    index=state['cursor']%len(rows);row=rows[index]
    generation=mac(library,'play',state['device_id'],state['revision'],row['id'],row['revision'])[:24]
    return dict(device_id=state['device_id'],item_id=row['id'],item_revision=row['revision'],play_id=generation,
                position_ms=0,report_seq=0,reported_at=0),index


def save(con, value):
    columns=('device_id','item_id','item_revision','play_id','position_ms','report_seq','reported_at')
    con.execute('INSERT INTO media_playback_progress VALUES(?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET '
                'item_id=excluded.item_id,item_revision=excluded.item_revision,play_id=excluded.play_id,'
                'position_ms=excluded.position_ms,report_seq=excluded.report_seq,reported_at=excluded.reported_at',
                tuple(value[k] for k in columns))
