"""Persistent TV photo controls. Playback never creates or broadens media grants."""
from datetime import datetime, timezone
import secrets
import re
import time

from flask import jsonify, request
from household_media import ITEM_VIEW, MediaError, _request_object
import media_playback_progress as progress
import media_trip_playback as trips

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
        self.trip = trips.TripPlayback(self)

    iso = staticmethod(_iso)

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

    def _photos(self, con, uid, *, journey_id=None):
        # Existing grants are the ONLY source. Never accept item IDs from a
        # control request or infer permission from a journey or member identity.
        # Same projection/predicate as MediaLibrary's media-tv list: never load
        # preview BLOBs to choose a slide or count the authorized collection.
        columns = ','.join('m.'+column for column in ITEM_VIEW.split(','))
        scope = ' AND m.journey_id=? AND m.confirmed_at IS NOT NULL' if journey_id is not None else ''
        args = (uid, journey_id) if journey_id is not None else (uid,)
        rows = con.execute('SELECT '+columns+" FROM media_items m JOIN media_tv_grants t ON t.media_id=m.id "
            "WHERE t.device_id=? AND m.state='ready' AND m.visibility='shared'"+scope+" ORDER BY m.id LIMIT 2001", args).fetchall()
        if len(rows)>2000:
            raise MediaError('quota')
        return [row for row in rows if self.library._media_authority(con, row)]

    def _position(self, state, count, now):
        # A decoder's actual completion, never elapsed wall time, advances media.
        return state['cursor'] % count if count else 0

    def _dto(self, state, count, now, review=None):
        route_ready = bool(review and review['route'] and any(s['state']=='available' for s in review['route']['stops']))
        return {'deviceId':state['device_id'], 'revision':state['revision'], 'mode':state['mode'],
            'paused':bool(state['paused']), 'intervalSeconds':state['interval_seconds'],
            'position':self._position(state,count,now), 'photoCount':count, 'canStart':count>0 or route_ready,
            'scope':'journey' if review is not None else 'all', 'journeyReview':review,
            'updatedAt':_iso(state['updated_at']) if state['updated_at'] is not None else None}

    def save_state(self, con, state, revision):
        uid = state['device_id']
        if revision==0:
            con.execute('INSERT INTO media_playback VALUES(?,?,?,?,?,?,?,?)',
                tuple(state[k] for k in ('device_id','mode','paused','interval_seconds','cursor','anchor_at','revision','updated_at')))
        else:
            changed = con.execute('UPDATE media_playback SET mode=?,paused=?,interval_seconds=?,cursor=?,anchor_at=?,revision=?,updated_at=? WHERE device_id=? AND revision=?',
                tuple(state[k] for k in ('mode','paused','interval_seconds','cursor','anchor_at','revision','updated_at'))+(uid,revision))
            if changed.rowcount != 1:
                raise MediaError('conflict')

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
        with self.library._suggestion_transaction(value is not None) as con:
            owner = self.library._member(con)  # Current signed member session, not a supplied owner.
            self._device(con,uid)
            state, now = self._state(con,uid), self.clock()
            review, photos = self.trip.projection(con, uid)
            play, position = progress.resolve(self.library,con,state,photos)
            state['cursor'] = position
            if value is not None:
                if state['revision'] != revision:
                    raise MediaError('conflict')
                state['cursor'] = self._position(state,len(photos),now)
                if action=='start':
                    # Explicit ordinary start is the only expansion to all photos.
                    photos = self._photos(con, uid)
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
                self.save_state(con,state,revision)
                if action in ('start','dashboard'):
                    con.execute('DELETE FROM media_playback_journeys WHERE device_id=?',(uid,))
                    review = None
                    photos = self._photos(con,uid)
                if state['mode']=='dashboard':
                    con.execute('DELETE FROM media_playback_progress WHERE device_id=?',(uid,))
                elif photos:
                    row=photos[state['cursor'] % len(photos)]
                    if action in ('start','next','previous') or play is None:
                        play=dict(device_id=uid,item_id=row['id'],item_revision=row['revision'],play_id=secrets.token_hex(12),
                                  position_ms=0,report_seq=0,reported_at=0)
                    progress.save(con,play)
                self.library._audit(con,owner,'media_playback_control',uid)
            return self._dto(state,len(photos),now,review)

    def authorize_progress_request(self):
        with self.library.transaction() as con:
            uid=self.library._tv(con)
            progress.check_csrf(self.library,self._device(con,uid),self.clock())

    def _authorize_tv_item_metadata(self, con, uid, device):
        # Match MediaLibrary._item(device=...) without fetching preview bytes.
        # _tv_dto still checks the device; television repeats both in a fresh snapshot.
        row = con.execute('SELECT '+ITEM_VIEW+' FROM media_items WHERE id=?', (_id(uid),)).fetchone()
        if (not row or row['state']!='ready' or row['visibility']!='shared'
                or not self.library._media_authority(con,row)
                or not con.execute('SELECT 1 FROM media_tv_grants WHERE media_id=? AND device_id=?',
                                   (uid,device)).fetchone()):
            raise MediaError('not_found')

    def _tv_dto(self,con,uid):
        device=self._device(con,uid)
        state,now=self._state(con,uid),self.clock()
        review,photos=self.trip.projection(con,uid,all_photos=state['mode']=='photos')
        if state['mode']!='photos':photos=[]
        play,position=progress.resolve(self.library,con,state,photos)
        state['cursor']=position
        result=self._dto(state,len(photos),now,review)
        result.update(item=None,progress=None,protocol=2)
        if play:
            row=photos[position]
            self._authorize_tv_item_metadata(con,row['id'],uid)
            item=dict(self.library._item_dto(con,row,television=True),revision=row['revision'])
            duration=item['durationMs'] if item.get('mediaType')=='video' else state['interval_seconds']*1000
            result.update(item=item,progress=dict(playId=play['play_id'],positionMs=min(play['position_ms'],duration),
                sequence=play['report_seq'],durationMs=duration))
        result.update(serverTime=_iso(now),validUntil=_iso(min(now+LEASE_SECONDS,device['expires'])),
                      playbackCsrf=progress.csrf(self.library,device,now))
        return result

    def television(self):
        with self.library.transaction() as con:
            uid=self.library._tv(con)
            result=self._tv_dto(con,uid)
            # Release the initial SQLite snapshot before rechecking the actual
            # device and every source projection. A changed view is retried by GET.
            con.rollback()
            con.execute('BEGIN')
            if self.library._tv(con)!=uid:
                raise MediaError('forbidden')
            current=self._tv_dto(con,uid)
            fields=('serverTime','validUntil','playbackCsrf')
            if {k:v for k,v in result.items() if k not in fields}!={k:v for k,v in current.items() if k not in fields}:
                raise MediaError('unavailable')
            return current

    def report(self,value):
        keys={'revision','playId','itemId','itemRevision','sequence','positionMs','event'}
        if type(value) is not dict or set(value)!=keys:
            raise MediaError('invalid_input')
        for key in ('revision','itemRevision','sequence'):
            _integer(value[key],1,9007199254740990)
        _id(value['playId']);_id(value['itemId']);_integer(value['positionMs'],0,600250)
        if value['event'] not in ('ready','checkpoint','paused','ended'):
            raise MediaError('invalid_input')
        with self.library.transaction(True) as con:
            uid=self.library._tv(con)
            progress.check_csrf(self.library,self._device(con,uid),self.clock())
            state=self._state(con,uid)
            _,rows=self.trip.projection(con,uid)
            play,position=progress.resolve(self.library,con,state,rows)
            if (not play or state['revision']!=value['revision']
                    or (play['play_id'],play['item_id'],play['item_revision'])!=(value['playId'],value['itemId'],value['itemRevision'])
                    or value['sequence']<=play['report_seq']):
                raise MediaError('conflict')
            row=self.library._item(con,play['item_id'],device=uid)
            metadata=self.library._metadata(row)
            duration=metadata['durationMs'] if metadata.get('mediaType')=='video' else state['interval_seconds']*1000
            offset=value['positionMs'];event=value['event']
            if offset>duration or offset<min(play['position_ms'],duration):
                raise MediaError('conflict')
            if ((event in ('checkpoint','ended') and state['paused']) or (event=='paused' and not state['paused'])
                    or (event=='ready' and abs(offset-min(play['position_ms'],duration))>250)):
                raise MediaError('conflict')
            if event=='ended':
                tolerance=250 if metadata.get('mediaType')=='video' else 0
                if offset<duration-tolerance:
                    raise MediaError('conflict')
                next_index=(position+1)%len(rows);next_row=rows[next_index];now=self.clock()
                changed=con.execute('UPDATE media_playback SET cursor=?,anchor_at=?,updated_at=?,revision=revision+1 WHERE device_id=? AND revision=?',
                                    (next_index,now,now,uid,value['revision']))
                if changed.rowcount!=1:raise MediaError('conflict')
                play=dict(device_id=uid,item_id=next_row['id'],item_revision=next_row['revision'],play_id=secrets.token_hex(12),
                          position_ms=0,report_seq=0,reported_at=0)
            else:
                play.update(position_ms=offset,report_seq=value['sequence'],reported_at=self.clock())
            progress.save(con,play)
            # Operational reports never call member audit/meta, edit grants, or
            # write media. Any duplicate/unknown report is resolved by a GET.
            result=self._tv_dto(con,uid)
            if self.library._tv(con)!=uid:
                raise MediaError('forbidden')
            return result



def register_media_playback(app):
    """Root registers after household_media. No app import, background work or external I/O."""
    library = app.extensions['household_media']
    with library.sessions.db() as con:
        initialize_media_playback(con)
        progress.initialize_progress(con)
        con.execute('BEGIN IMMEDIATE')
        trips.init_schema(con)
    playback = MediaPlayback(library)
    app.extensions['media_playback'] = playback
    trips.register(app,playback)

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

    @app.post('/api/media-tv/playback/progress')
    def media_playback_progress():
        if request.args:
            raise MediaError('invalid_input')
        return jsonify(playback.report(_request_object()))

    return playback
