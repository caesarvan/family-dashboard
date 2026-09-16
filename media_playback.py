"""Persistent TV photo controls. Playback never creates or broadens media grants."""
from datetime import datetime, timezone
import math
import re
import time

from flask import jsonify, request
from household_media import ITEM_VIEW, MediaError, _request_object

LEASE_SECONDS = 15
SCHEMA_SQL = '''
CREATE TABLE media_playback(
 device_id TEXT PRIMARY KEY NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 mode TEXT NOT NULL DEFAULT 'dashboard' CHECK(mode IN ('dashboard','photos')),
 paused INTEGER NOT NULL DEFAULT 0 CHECK(typeof(paused)='integer' AND paused IN (0,1)),
 interval_seconds INTEGER NOT NULL DEFAULT 10 CHECK(typeof(interval_seconds)='integer' AND interval_seconds BETWEEN 5 AND 120),
 cursor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(cursor)='integer' AND cursor BETWEEN 0 AND 1000000),
 anchor_at REAL NOT NULL CHECK(anchor_at>=0),
 revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 9007199254740991),
 updated_at REAL NOT NULL CHECK(updated_at>=0));
'''


def initialize_media_playback(con):
    """Explicit initialization; migrations may instead execute SCHEMA_SQL in their transaction."""
    if con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Playback initialization requires an idle foreign-key connection')
    existing = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='media_playback'").fetchone()
    if existing:
        # Accept only this module's exact DDL, not a partial or historical table.
        if existing[0].strip().rstrip(';') != SCHEMA_SQL.strip().rstrip(';'):
            raise RuntimeError('Playback schema mismatch')
        return
    con.executescript('BEGIN IMMEDIATE;\n'+SCHEMA_SQL+'\nCOMMIT;')


def _id(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{24}', value):
        raise MediaError('invalid_input')
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise MediaError('invalid_input')
    return value


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class MediaPlayback:
    """Depends on the frozen MediaLibrary transaction/member/TV/item authorization protocol."""
    def __init__(self, library, *, clock=time.time):
        self.library, self.clock = library, clock

    def _device(self, con, uid):
        row = con.execute('SELECT id,expires FROM devices WHERE id=? AND approved=1 AND expires>?',
                          (_id(uid), self.clock())).fetchone()
        if not row:
            raise MediaError('not_found')
        return row

    def _state(self, con, uid):
        row = con.execute('SELECT * FROM media_playback WHERE device_id=?', (uid,)).fetchone()
        return dict(row) if row else dict(device_id=uid, mode='dashboard', paused=0,
            interval_seconds=10, cursor=0, anchor_at=self.clock(), revision=0, updated_at=None)

    def _photos(self, con, uid):
        # Existing grants are the ONLY source. Never accept item IDs from a
        # control request or infer permission from a journey or member identity.
        # Same projection/predicate as MediaLibrary's media-tv list: never load
        # preview BLOBs to choose a slide or count the authorized collection.
        columns = ','.join('m.'+column for column in ITEM_VIEW.split(','))
        rows = con.execute('SELECT '+columns+" FROM media_items m JOIN media_tv_grants t ON t.media_id=m.id "
            "WHERE t.device_id=? AND m.state='ready' AND m.visibility='shared' ORDER BY m.id LIMIT 2001", (uid,)).fetchall()
        if len(rows)>2000:
            raise MediaError('quota')
        allowed = {}
        for row in rows:
            key = (row['account_id'],row['owner'])
            if key not in allowed:
                allowed[key] = self.library._authority(con,*key)
        return [row for row in rows if allowed[(row['account_id'],row['owner'])]]

    def _position(self, state, count, now):
        steps = (max(0, math.floor((now-state['anchor_at'])/state['interval_seconds']))
                 if state['mode']=='photos' and not state['paused'] else 0)
        return (state['cursor']+steps) % count if count else 0

    def _dto(self, state, count, now):
        return {'deviceId':state['device_id'], 'revision':state['revision'], 'mode':state['mode'],
            'paused':bool(state['paused']), 'intervalSeconds':state['interval_seconds'],
            'position':self._position(state,count,now), 'photoCount':count, 'canStart':count>0,
            'updatedAt':_iso(state['updated_at']) if state['updated_at'] is not None else None}

    def control(self, uid, value=None):
        uid = _id(uid)
        if value is not None:
            if (type(value) is not dict or set(value)-{'revision','action','intervalSeconds'}
                    or not {'revision','action'} <= set(value)):
                raise MediaError('invalid_input')
            revision = _integer(value['revision'],0,9007199254740990)
            action = value['action']
            if type(action) is not str or action not in ('start','dashboard','pause','resume','next','previous','interval'):
                raise MediaError('invalid_input')
            if ('intervalSeconds' in value) != (action=='interval'):
                raise MediaError('invalid_input')
            if action=='interval':
                _integer(value['intervalSeconds'],5,120)
        with self.library.transaction(value is not None) as con:
            owner = self.library._member(con)  # Current signed member session, not a supplied owner.
            self._device(con,uid)
            state, photos, now = self._state(con,uid), self._photos(con,uid), self.clock()
            if value is not None:
                if state['revision'] != revision:
                    raise MediaError('conflict')
                state['cursor'] = self._position(state,len(photos),now)
                if action=='start':
                    if not photos:
                        raise MediaError('not_selected')
                    state.update(mode='photos',paused=0,cursor=0)
                elif action=='dashboard':
                    state.update(mode='dashboard',paused=0,cursor=0)
                elif action=='interval':
                    state['interval_seconds'] = value['intervalSeconds']
                else:
                    if state['mode'] != 'photos':
                        raise MediaError('conflict')
                    if action in ('pause','resume'):
                        state['paused'] = int(action=='pause')
                    else:
                        if not photos:
                            raise MediaError('not_selected')
                        state['cursor'] = (state['cursor']+(1 if action=='next' else -1)) % len(photos)
                state.update(anchor_at=now,updated_at=now,revision=revision+1)
                if revision==0:
                    con.execute('INSERT INTO media_playback VALUES(?,?,?,?,?,?,?,?)',
                        tuple(state[k] for k in ('device_id','mode','paused','interval_seconds','cursor','anchor_at','revision','updated_at')))
                else:
                    changed = con.execute('UPDATE media_playback SET mode=?,paused=?,interval_seconds=?,cursor=?,anchor_at=?,revision=?,updated_at=? WHERE device_id=? AND revision=?',
                        tuple(state[k] for k in ('mode','paused','interval_seconds','cursor','anchor_at','revision','updated_at'))+(uid,revision))
                    if changed.rowcount != 1:
                        raise MediaError('conflict')
                self.library._audit(con,owner,'media_playback_control',uid)
            return self._dto(state,len(photos),now)

    def television(self):
        with self.library.transaction() as con:
            uid = self.library._tv(con)  # Real TV credential even if a member cookie also exists.
            device = self._device(con,uid)
            state, now = self._state(con,uid), self.clock()
            photos = self._photos(con,uid) if state['mode']=='photos' else []
            result = self._dto(state,len(photos),now)
            result['item'] = None
            if photos:
                row = photos[result['position']]
                self.library._item(con,row['id'],device=uid)
                result['item'] = dict(self.library._item_dto(con,row,television=True),revision=row['revision'])
            result.update(serverTime=_iso(now),validUntil=_iso(min(now+LEASE_SECONDS,device['expires'])))
            return result


def register_media_playback(app):
    """Root registers after household_media. No app import, background work or external I/O."""
    library = app.extensions['household_media']
    with library.sessions.db() as con:
        initialize_media_playback(con)
    playback = MediaPlayback(library)
    app.extensions['media_playback'] = playback

    @app.route('/api/media-playback/devices/<uid>',methods=['GET','PUT'])
    def media_playback_control(uid):
        if request.args:
            raise MediaError('invalid_input')
        return jsonify(playback.control(uid,_request_object() if request.method=='PUT' else None))

    @app.get('/api/media-tv/playback')
    def media_playback_tv():
        if request.args:
            raise MediaError('invalid_input')
        return jsonify(playback.television())

    return playback
