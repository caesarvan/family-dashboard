"""Synthetic bulk fixture and four actual WSGI reads; no cloud import/throughput claim."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys
from threading import Barrier, Lock
import time

from test_household_media import device
from test_journey_documents import clone, create_journey
from test_journey_places import create as create_place
from test_journey_routes import create as create_route
from test_media_playback import env, granted, offline, path
from test_media_trip_playback import link, preview, start


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=lambda x:
        {'blobSha256': hashlib.sha256(bytes(x)).hexdigest()}, separators=(',', ':')).encode()).hexdigest()


def database_digest(database):
    with closing(sqlite3.connect(database)) as con:
        con.execute('BEGIN')
        result = {}
        for name, in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [r[1] for r in con.execute('PRAGMA table_info('+quoted+')')]
            rows = []
            for values in con.execute('SELECT * FROM '+quoted):
                row = dict(zip(columns, values))
                if name == 'member_sessions': row['last_seen_at'] = 0
                rows.append(digest(row))
            result[name] = digest(sorted(rows))
        return result


def cgroup():
    if sys.platform != 'linux': return None
    root = Path('/sys/fs/cgroup')
    return {name: (root/name).read_text().strip() for name in
            ('memory.max', 'memory.swap.max', 'memory.peak', 'memory.events')}


def test_four_wsgi_reads_2000_media_100_stops_no_large_blob(env, monkeypatch, tmp_path):
    app, library = env[:2]
    output = (Path('/proof') if sys.platform == 'linux' and Path('/proof').is_dir() else tmp_path) / 'tv-trip-capacity.json'
    proof = {'kind': 'tv-trip-capacity-v1', 'passed': False, 'linux': sys.platform == 'linux',
             'scope': 'four-real-Flask-WSGI-reads; not-Gunicorn-Nginx-throughput-or-media-decode',
             'fixture': {'media': 2000, 'sharedStops': 100, 'televisions': 2,
                         'creation': 'one-real-photo-confirmation-then-synthetic-encrypted-storage-fill'},
             'bookkeepingNormalization': ['member_sessions.last_seen_at'], 'requests': [],
             'deniedBlobReads': [], 'scanCount': 0, 'failure': None}
    try:
        c, h, uid, tv, _, items = granted(env, 1)
        uid2, tv2, _ = device(env)
        journey = create_journey(c, h)
        item = link(c, h, items[0], journey['id'])
        points = [create_place(c, h, name='SYNTHETIC-STOP-'+str(i), journeyId=journey['id'],
                  expectedJourneyRevision=1, visibility='shared', coordinateDisclosure='coarse',
                  coordinates={'latitude': 20+i/100, 'longitude': 110+i/100})[0] for i in range(100)]
        route, _ = create_route(c, h, journey, points, title='SYNTHETIC-CAPACITY-ROUTE', visibility='shared')
        with library.transaction(True) as con:
            row = dict(con.execute('SELECT * FROM media_items WHERE id=?', (item['id'],)).fetchone())
            metadata = library._metadata(row)
            con.execute('INSERT INTO media_tv_grants VALUES(?,?,?,?)', (row['id'], uid2, row['owner'], library.clock()))
            for _ in range(1999):
                copy = {**row, 'id': secrets.token_hex(12), 'source_key': secrets.token_hex(32)}
                copy['metadata_cipher'] = library._seal('media-metadata', copy,
                    {**metadata, 'sourceKey': copy['source_key']})
                # Small synthetic JPEG cache copied only for legal ready-row storage;
                # no byte endpoint is exercised. The authorizer below forbids reading it.
                con.execute('INSERT INTO media_items('+','.join(copy)+') VALUES('+','.join('?' for _ in copy)+')', tuple(copy.values()))
                con.executemany('INSERT INTO media_tv_grants VALUES(?,?,?,?)',
                    [(copy['id'], d, row['owner'], library.clock()) for d in (uid, uid2)])
        for d in (uid, uid2): start(c, h, d, preview(c, h, d, journey['id'], route['current']['route']['id']))
        database = library.sessions.path
        proof['databaseBefore'] = database_digest(database)
        proof['cgroupBefore'] = cgroup()
        barrier, lock = Barrier(4), Lock()
        original_connect = sqlite3.connect
        def connect(*args, **kwargs):
            con = original_connect(*args, **kwargs)
            def authorize(action, table, column, _database, _trigger):
                if action == sqlite3.SQLITE_READ and ((table == 'media_items' and column == 'preview_cipher')
                        or (table == 'media_video_cache' and column == 'cipher')):
                    with lock: proof['deniedBlobReads'].append([table, column])
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            def trace(sql):
                if sql.startswith('SELECT ') and 'JOIN media_tv_grants' in sql:
                    with lock: proof['scanCount'] += 1
            con.set_authorizer(authorize); con.set_trace_callback(trace)
            return con
        requests = [(tv, 'GET', '/api/media-tv/playback', None, {'X-Display-Mode': 'tv'}),
                    (tv2, 'GET', '/api/media-tv/playback', None, {'X-Display-Mode': 'tv'}),
                    (clone(app,c), 'GET', path(uid), None, {}),
                    (clone(app,c), 'POST', path(uid2)+'/journey-preview',
                     {'revision': 1, 'journeyId': journey['id'], 'routeId': route['current']['route']['id']}, h)]
        def invoke(spec):
            client, method, url, payload, headers = spec
            barrier.wait(timeout=15)
            begin = time.monotonic()
            response = client.open(url, method=method, json=payload, headers=headers)
            finish = time.monotonic(); body = response.get_json()
            record = {'method':method, 'path':url, 'started':begin, 'finished':finish,
                      'status':response.status_code, 'bytes':len(response.data), 'bodySha256':digest(body), 'body':body}
            with lock: proof['requests'].append(record)
            assert response.status_code == 200, body
            assert len(response.data) <= 512*1024
            assert body.get('photoCount', body.get('mediaCount')) == 2000
            view = body['route'] if 'route' in body else body['journeyReview']['route']
            assert len(view['stops']) == 100 and all(s['state']=='available' for s in view['stops'])
        with monkeypatch.context() as measured:
            measured.setattr(sqlite3, 'connect', connect)
            with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(invoke, requests))
        proof['databaseAfter'] = database_digest(database)
        proof['cgroupAfter'] = cgroup()
        intervals = proof['requests']
        proof['fourRequestOverlapSeconds'] = min(r['finished'] for r in intervals)-max(r['started'] for r in intervals)
        assert len(intervals)==4 and proof['fourRequestOverlapSeconds']>0
        assert proof['scanCount']>=4 and proof['deniedBlobReads']==[]
        assert proof['databaseBefore']==proof['databaseAfter']
        if sys.platform == 'linux':
            import resource
            proof['processPeakRssBytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
            for observed in (proof['cgroupBefore'], proof['cgroupAfter']):
                assert int(observed['memory.max'])==384*1024**2 and int(observed['memory.swap.max'])==0
                events = dict(line.split() for line in observed['memory.events'].splitlines())
                assert all(int(events.get(k, '-1'))==0 for k in ('max','oom','oom_kill'))
                assert 0<int(observed['memory.peak'])<=384*1024**2
        else:
            proof['processPeakRssBytes'] = None
        proof['loaded'] = {name: {'path': str(sys.modules[name].__file__),
                          'sha256': hashlib.sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()}
                           for name in ('media_trip_playback','media_playback','household_media','journey_routes','journey_places')}
        proof['passed'] = True
    except BaseException as error:
        proof['failure'] = {'type':type(error).__name__, 'message':str(error)}
        raise
    finally:
        final_error = None
        try:
            proof['cgroupFinal'] = cgroup()
        except Exception as error:
            final_error = error
            proof['passed'] = False
            proof['cgroupFinal'] = None
            proof['cgroupReadError'] = {'type': type(error).__name__, 'message': str(error)}
        with output.open('x', encoding='utf-8') as stream:
            json.dump(proof, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write('\n')
        if final_error is not None and proof['failure'] is None:
            raise final_error
