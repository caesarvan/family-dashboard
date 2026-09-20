"""Isolated four-request duplicate metadata experiment; never a production action."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time

if Path(__file__).name == 'probe.py':
    import legacy
    import ipc
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from deploy import local_photo_linux_probe as legacy
    from deploy import media_video_ipc_resource_probe as ipc

need, sha, save = legacy.need, legacy.sha, legacy.save
SELF = 'deploy/discovery_duplicate_linux_probe.py'
CLOSURE = {'tools/probe.py': SELF, 'tools/legacy.py': 'deploy/local_photo_linux_probe.py',
           'tools/ipc.py': 'deploy/media_video_ipc_resource_probe.py'}
ROOT = Path('/tmp/family-dashboard-discovery-duplicate-probe')
LIMITS = {'app': 384, 'client': 64}
BUDGET = {'preflightMiB': 640, 'preflightSamples': 3, 'preflightIntervalSeconds': 1,
          'abortBelowMiB': 256, 'sampleIntervalSeconds': .25, 'maxSampleLagSeconds': 1}
MIB = 1024 ** 2
SECRET = 'synthetic-discovery-probe-secret-not-a-credential'
PASSWORD = 'synthetic-discovery-probe-password'
PUBLIC = 'https://probe.invalid'
# Compare all tables, including encrypted BLOBs, except this one allowed session
# touch column. The duplicate request itself must leave every business byte alone.
NORMALIZED_COLUMNS = {'member_sessions': {'last_seen_at'}}


def safe(path, exists=True, remote=False):
    p = legacy.safe(path, exists=exists)
    if remote:
        need(p.is_relative_to(ROOT) and p != ROOT, 'outside dedicated temporary root')
    return p


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def binding(meta, build, package_sha, build_sha):
    runtime = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith('static/experience/')}
    need(len(runtime) == 112 and len(meta['exportFiles']) == 23, 'fixed runtime/export counts differ')
    need(build['exitCode'] == 0 and build['productionOperations'] is False
         and build['sourceHead'] == meta['sourceHead'] and build['tree'] == meta['tree']
         and build['packageSha256'] == package_sha and build['manifestSha256'] == meta['manifestSha256']
         and build['runtimeHashes'] == meta['runtimeFiles']
         and re.fullmatch('sha256:[a-f0-9]{64}', build['imageId']), 'actual build binding differs')
    return dict(sourceHead=meta['sourceHead'], tree=meta['tree'], packageSha256=package_sha,
                manifestSha256=meta['manifestSha256'], imageId=build['imageId'], buildSha256=build_sha,
                runtimeFiles=runtime, exportFiles=meta['exportFiles'])


def prepare(source, head, package, package_sha, build_path, build_sha, output):
    from deploy.git_blobs import read_git_blobs
    # Fixed reviewed discovery profile; no arbitrary module or caller profile.
    from deploy.build_discovery_release import verify_package
    source = safe(source); package = safe(package); build_path = safe(build_path)
    need(re.fullmatch('[a-f0-9]{40}', head or ''), 'full source commit required')
    def git(*args):
        p = subprocess.run(['git', '--no-replace-objects', *args], cwd=source, capture_output=True, timeout=60)
        need(p.returncode == 0, 'Git read failed'); return p.stdout.decode().strip()
    need(git('rev-parse', 'HEAD') == head and not git('status', '--porcelain', '--untracked-files=no'), 'source not fixed clean HEAD')
    value = verify_package(package, package_sha); meta = value['metadata']
    need(meta['sourceHead'] == head and meta['tree'] == git('rev-parse', head + '^{tree}'), 'package/source differs')
    need(sha(build_path) == build_sha, 'build receipt changed')
    contract = binding(meta, read(build_path), package_sha, build_sha)
    blobs = read_git_blobs(source, head, meta['sourceFiles'])
    need({n: digest(b) for n, b in blobs.items()} == meta['sourceFiles'], 'packaged Git source differs')
    need(blobs[SELF] == Path(__file__).read_bytes(), 'executed probe differs from packaged source')
    need(set(legacy.runtime_names(value['blobs'])) == set(meta['runtimeFiles']), 'Docker COPY closure differs')
    output = safe(output, exists=False); output.mkdir(parents=True)
    (output/'tools').mkdir(); (output/'records').mkdir()
    for dest, name in CLOSURE.items(): (output/dest).write_bytes(blobs[name])
    for name in ('package.json', 'release-manifest.json'): (output/'records'/name).write_bytes((package/name).read_bytes())
    (output/'records/build.json').write_bytes(build_path.read_bytes())
    contract.update(kind='discovery-duplicates-linux-input-v1', limitsMiB=LIMITS, hostBudget=BUDGET,
                    fixture={'ownerReadyRecords': 1002, 'candidateRecords': 1001, 'scanLimit': 1000,
                             'note': 'Encrypted synthetic rows; Google authorization is synthetic, no provider transport.'},
                    files={p.relative_to(output).as_posix(): sha(p) for p in output.rglob('*') if p.is_file()})
    save(output/'input.json', contract)
    checked_input(output)
    return contract


def checked_input(path):
    path = safe(path); c = read(path/'input.json')
    need(c['kind'] == 'discovery-duplicates-linux-input-v1' and c['limitsMiB'] == LIMITS
         and c['hostBudget'] == BUDGET, 'input policy differs')
    meta = read(path/'records/package.json')
    need(sha(path/'records/package.json') == c['packageSha256']
         and sha(path/'records/release-manifest.json') == c['manifestSha256']
         and sha(path/'records/build.json') == c['buildSha256'], 'receipt identity differs')
    need(all(c[k] == v for k, v in binding(meta, read(path/'records/build.json'), c['packageSha256'], c['buildSha256']).items()), 'input binding differs')
    need({p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file()} == set(c['files']) | {'input.json'}, 'input closure differs')
    need(set(c['files']) == set(CLOSURE) | {'records/package.json', 'records/release-manifest.json', 'records/build.json'}, 'unexpected input closure')
    for name, h in c['files'].items():
        need(not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name, 'unsafe input name')
        need(sha(safe(path/name)) == h, 'input bytes differ: '+name)
    need({n: c['files'][n] for n in CLOSURE} == {n: meta['sourceFiles'][v] for n, v in CLOSURE.items()}, 'unbound tool closure')
    need(sha(path/'tools/probe.py') == sha(__file__), 'executed probe changed')
    return c


def container_args(role, network, token, prepared, output, contract):
    need(role in LIMITS and re.fullmatch('dd-[a-f0-9]{16}', token), 'invalid owned role')
    need(re.fullmatch('[a-f0-9]{64}', network), 'unknown private network')
    args = ['create', '--pull=never', '--name', token+'-'+role, '--label', 'discovery-duplicates='+token,
            '--network', network, '--network-alias', role, '--read-only', '--user=10001:10001', '--cap-drop=ALL',
            '--security-opt=no-new-privileges:true', '--cpus=1', f'--memory={LIMITS[role]}m', f'--memory-swap={LIMITS[role]}m',
            '--pids-limit=64', '--ulimit=nofile=128:128', '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777']
    mounts = [(prepared, '/input', True), (output/role, '/proof', False),
              (output/'data', '/data', role == 'client'), (output/'control', '/control', True)]
    if role == 'client': mounts += [(output/'app', '/observations', True)]
    for src, dest, ro in mounts:
        safe(src, remote=True)
        args += ['--mount', f'type=bind,src={src},dst={dest}'+(',readonly' if ro else '')]
    return args + ['--entrypoint', '/usr/bin/env', contract['imageId'], '-i', 'PATH=/usr/local/bin:/usr/bin:/bin',
                   'HOME=/tmp', 'LANG=C.UTF-8', 'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUNBUFFERED=1', 'PYTHONPATH=/app',
                   'DATA_DIR=/data', 'SECRET_KEY='+SECRET, 'MEMBER1_PASSWORD='+PASSWORD, 'MEMBER2_PASSWORD='+PASSWORD,
                   'GOOGLE_CLIENT_ID=synthetic-client', 'GOOGLE_CLIENT_SECRET=synthetic-secret',
                   'PUBLIC_ORIGIN='+PUBLIC, 'TRUST_PROXY=1', 'COOKIE_SECURE=1',
                   'python', '-B', '/input/tools/probe.py', 'inside', '--role', role]


def inspect_owned(ex, cid, role, token, image):
    need(re.fullmatch('[a-f0-9]{64}', cid or ''), 'unknown CID')
    _, raw = ex.call(['inspect', '--format', '{{json .}}', cid]); info = json.loads(raw)
    need(info['Id'] == cid and info['Name'] == '/'+token+'-'+role
         and info['Config'].get('Labels', {}).get('discovery-duplicates') == token and info['Image'] == image,
         'owned container identity changed')
    h = info['HostConfig']
    need(h['Memory'] == h['MemorySwap'] == LIMITS[role]*MIB and h['ReadonlyRootfs']
         and not h['Privileged'] and not h['PortBindings'] and info['Config']['User'] == '10001:10001'
         and 'ALL' in h['CapDrop'] and 'no-new-privileges:true' in h['SecurityOpt'], 'container isolation differs')
    return info


def cgroup_state(pid):
    state = legacy.cgroup_state(pid)
    path = next(x[3:] for x in Path(f'/proc/{pid}/cgroup').read_text().splitlines() if x.startswith('0::'))
    need(path.startswith('/') and '..' not in Path(path).parts, 'unknown cgroup path')
    state['memory.swap.max'] = (Path('/sys/fs/cgroup')/path.lstrip('/')/'memory.swap.max').read_text().strip()
    return state


def resource_samples(samples):
    need(samples, 'missing cgroup observations')
    for index, sample in enumerate(samples):
        need(set(sample['roles']) == set(LIMITS), 'incomplete cgroup roles')
        if index: need(0 <= sample['monotonic']-samples[index-1]['monotonic'] <= 1, 'cgroup monitoring gap')
        for role, state in sample['roles'].items():
            events = dict(line.split() for line in state['memory.events'].splitlines())
            need(int(state['memory.max']) == LIMITS[role]*MIB and int(state['memory.swap.max']) == 0
                 and 0 < int(state['memory.peak']) <= LIMITS[role]*MIB,
                 'cgroup limit/peak differs')
            need(all(k in events and int(events[k]) == 0 for k in ('max', 'oom', 'oom_kill'))
                 and int(events.get('oom_group_kill', 0)) == 0, 'cgroup memory event')


def checked_client_database(output, proof):
    client = Path(output)/'client'
    finished = read(client/'finished.json')
    need(proof.get('passed') is True and finished == {'passed': True, 'resultSha256': sha(client/'result.json')},
         'client workload failed: '+str(proof.get('failure') or 'invalid completion receipt'))
    database = read(client/'database.json')
    before, after = (read(Path(output)/'app'/('database-'+phase+'.json')) for phase in ('before', 'after'))
    expected = {'before': before['sha256'], 'after': after['sha256'], 'beforeTables': before['tables'],
                'afterTables': after['tables'], 'normalization': before['normalization']}
    need(database == expected and after['normalization'] == before['normalization'], 'app/client database snapshots differ')
    responses = read(client/'database-http.json')
    need(len(responses) == 2 and all(r['method'] == 'GET' and r['status'] == 200
         and r['path'] == '/api/_probe/database-snapshot/'+phase and r['body'] == value
         for r, phase, value in zip(responses, ('before', 'after'), (before, after))), 'snapshot HTTP evidence differs')
    return database


def run(prepared, output, expected_input_sha256):
    need(sys.platform == 'linux' and sys.dont_write_bytecode and not sys.flags.optimize, 'Linux -B without -O required')
    prepared = safe(prepared, remote=True); c = checked_input(prepared)
    need(sha(prepared/'input.json') == expected_input_sha256, 'reviewed input changed')
    output = safe(output, exists=False, remote=True); output.mkdir(parents=True, mode=0o755)
    ipc.HOST_BUDGET = dict(BUDGET)
    ex = ipc.Executor(output); monitor = ipc.HostMemoryMonitor(output)
    token = 'dd-'+secrets.token_hex(8); owned = {}; verified = set(); network = None; unknown = None
    failure = None; errors = []; samples = []; states = {}; proof = None; database = None
    def wait_file(path, seconds):
        until = time.monotonic()+seconds
        while not path.exists():
            monitor.check(); need(time.monotonic() < until, 'bounded phase timeout: '+path.name); time.sleep(.25)
    try:
        need(ipc.host_preflight(output)['status'] == 'ready', 'preflight blocked; no automatic retry')
        monitor.start()
        for folder in ('app', 'client', 'control', 'data'):
            p = output/folder; p.mkdir(mode=0o755); os.chown(p, 10001, 10001)
        unknown = {'kind': 'network', 'name': token}
        _, raw = ex.call(['network', 'create', '--internal', '--driver=bridge', '--label', 'discovery-duplicates='+token, token], guard=monitor, interruptible=False)
        network = raw.decode().strip(); need(re.fullmatch('[a-f0-9]{64}', network), 'unknown network creation'); unknown = None
        _, raw = ex.call(['network', 'inspect', network], guard=monitor); net = json.loads(raw)[0]
        need(net['Id'] == network and net['Internal'] and net['Labels'].get('discovery-duplicates') == token and not net['Containers'], 'network isolation differs')
        for role in LIMITS:
            unknown = {'kind': 'container', 'role': role}
            _, raw = ex.call(container_args(role, network, token, prepared, output, c), guard=monitor, interruptible=False)
            cid = raw.decode().strip(); need(re.fullmatch('[a-f0-9]{64}', cid), 'unknown container creation')
            owned[role] = cid; save(output/(role+'-owned.json'), {'id': cid}); unknown = None
            inspect_owned(ex, cid, role, token, c['imageId'])
            verified.add(cid)
        for role in LIMITS:
            ex.call(['start', owned[role]], guard=monitor)
            states[role] = inspect_owned(ex, owned[role], role, token, c['imageId'])
        # Both remain alive, including after finished.json, until coordinator ACK.
        # Peak/events are lifetime counters, thus include fixture/startup cost too.
        until = time.monotonic()+180; go = False
        while True:
            monitor.check(); need(time.monotonic() < until, 'profile timeout; incomplete result')
            samples.append({'at': time.time(), 'monotonic': time.monotonic(),
                            'roles': {r: cgroup_state(s['State']['Pid']) for r, s in states.items()}})
            if not go and (output/'client/ready.json').exists():
                save(output/'control/go.json', {'start': True}); go = True
            if (output/'client/finished.json').exists(): break
            time.sleep(.25)
        resource_samples(samples)
        proof = read(output/'client/result.json')
        database = checked_client_database(output, proof)
        need(database['before'] == database['after'], 'business database changed')
        save(output/'database.json', database); save(output/'control/release.json', {'release': True})
        _, raw = ex.call(['wait', owned['client']], timeout=10, guard=monitor)
        need(raw.decode().strip() == '0', 'client process failed after receipt')
    except BaseException as error:
        failure = type(error).__name__+': '+str(error)
    finally:
        # Immutable IDs already checked immediately after creation. On pressure,
        # stop every known workload before potentially slower inspect/log reads.
        if monitor.failure:
            for cid in owned.values():
                if cid in verified:
                    try: ex.call(['kill', cid], check=False)
                    except BaseException as error: errors.append({'kill': cid, 'error': str(error)})
        for role, cid in reversed(list(owned.items())):
            try:
                info = inspect_owned(ex, cid, role, token, c['imageId'])
                if not failure and role == 'app': need(info['State']['Running'], 'app stopped unexpectedly')
                if info['State']['Running']:
                    if monitor.failure: ex.call(['kill', cid], check=False)
                    else: ex.call(['stop', '--time=5', cid], timeout=10, check=False)
                final = inspect_owned(ex, cid, role, token, c['imageId']); save(output/(role+'-final.json'), final)
                need(not final['State']['Running'] and final['State']['Pid'] == 0, 'owned container remains active')
                ex.call(['logs', cid], check=False); ex.call(['rm', cid])
                need(not final['State']['OOMKilled'], 'owned container OOM killed')
                if not failure: need(final['State']['ExitCode'] == 0, 'owned process nonzero exit')
            except BaseException as error: errors.append({'role': role, 'error': str(error)})
        if network and not errors and not unknown:
            try: ex.call(['network', 'rm', network])
            except BaseException as error: errors.append({'network': network, 'error': str(error)})
        try: memory = monitor.finish() if monitor.thread is not None else {'threadStarted': False, 'failure': 'not started'}
        except BaseException as error:
            memory = {'failure': str(error)}; errors.append({'monitor': str(error)})
        save(output/'cgroup-samples.json', samples)
        if any(r['exitCode'] != 0 or r.get('abortedBy') for r in ex.records):
            failure = failure or 'one or more recorded Docker commands failed'
        result = dict(kind='discovery-duplicates-linux-result-v1', inputSha256=expected_input_sha256,
                      passed=failure is None and not errors and not unknown and not memory.get('failure'),
                      failure=failure, cleanupErrors=errors, unknownCreate=unknown, containers=owned,
                      proof=proof, database=database, hostMemory=memory, commands=ex.records, completedAt=time.time())
        result['artifacts'] = {p.relative_to(output).as_posix(): sha(p) for p in output.rglob('*') if p.is_file() and not p.is_relative_to(output/'data')}
        save(output/'result.json', result)
    need(result['passed'], 'resource profile not passed; preserve originals, no automatic retry')


def runtime_proof(contract):
    import importlib.metadata
    expected = {**contract['runtimeFiles'], **{'static/experience/'+n: h for n, h in contract['exportFiles'].items()}}
    actual = {p.relative_to('/app').as_posix(): sha(p) for p in Path('/app').rglob('*') if p.is_file()}
    need(actual == expected and not any(p.is_symlink() for p in Path('/app').rglob('*')), 'actual complete app image runtime differs')
    loaded = {}
    for name, module in list(sys.modules.items()):
        if name+'.py' not in contract['runtimeFiles']: continue
        p = Path(module.__file__).resolve()
        need(p == Path('/app')/(name+'.py'), 'runtime import escaped immutable image')
        loaded[name] = {'path': str(p), 'sha256': sha(p)}
    need({'app', 'household_media', 'media_crypto'} <= loaded.keys(), 'required actual imports absent')
    versions = {}
    for line in Path('/app/requirements.txt').read_text().splitlines():
        package, version = line.split('=='); observed = importlib.metadata.version(package)
        need(observed == version, 'dependency changed: '+package); versions[package] = observed
    return {'modules': loaded, 'runtimeFiles': actual, 'dependencies': versions}


def forbid_outbound():
    import socket
    def denied(*_args, **_kwargs): raise RuntimeError('probe application external connection forbidden')
    socket.socket.connect = denied; socket.socket.connect_ex = denied; socket.create_connection = denied


def db_snapshot(path):
    """Exact per-table digests; only member session touch time is normalized."""
    tables = {}
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True)) as con:
        con.execute('BEGIN')
        schema = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quote = '"'+name.replace('"', '""')+'"'
            columns = [r[1] for r in con.execute('PRAGMA table_info('+quote+')')]
            kept = [i for i, c in enumerate(columns) if c not in NORMALIZED_COLUMNS.get(name, set())]
            rows = []
            for row in con.execute('SELECT * FROM '+quote):
                value = [({'blobSha256': digest(row[i]), 'bytes': len(row[i])} if isinstance(row[i], bytes) else row[i]) for i in kept]
                rows.append(json.dumps(value, sort_keys=True, separators=(',', ':')))
            tables[name] = {'columns': [columns[i] for i in kept], 'rows': len(rows), 'sha256': digest('\n'.join(sorted(rows)).encode())}
    payload = dict(schema=schema, tables=tables)
    return {'sha256': digest(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()), 'tables': tables,
            'normalization': {k: sorted(v) for k, v in NORMALIZED_COLUMNS.items()}}


def seed_fixture(app):
    """Real local upload/confirm target; synthetic encrypted Google row population."""
    from io import BytesIO
    from PIL import Image
    from cloud_accounts import GOOGLE_PHOTOS_SCOPE
    engine = app.extensions['household_media']; client = app.test_client()
    need(not app.testing and app.config['SESSION_COOKIE_SECURE'], 'secure real app required')
    need(client.post('/api/login', base_url=PUBLIC, json={'username': 'member1', 'password': PASSWORD}).status_code == 200, 'fixture login failed')
    h = {'Origin': PUBLIC, 'X-CSRF-Token': client.get('/api/me', base_url=PUBLIC).json['csrf']}
    buf = BytesIO()
    with Image.new('RGB', (20, 12), '#496654') as im: im.save(buf, 'PNG')
    raw = buf.getvalue()
    start = client.post('/api/media/local-imports', base_url=PUBLIC, headers=h, json={'requestId': secrets.token_hex(16),
        'consentVersion': 'media-v1', 'allowTemporaryProcessing': True, 'files': [{'clientFileId': secrets.token_hex(16),
        'filename': 'synthetic.png', 'contentType': 'image/png', 'bytes': len(raw), 'sha256': digest(raw)}]})
    need(start.status_code == 201, 'fixture create failed'); d = start.json; uid = d['import']['id']
    put = client.put(f"/api/media/local-imports/{uid}/files/{d['upload']['files'][0]['slotId']}", base_url=PUBLIC,
        headers={**h, 'X-Import-Revision': str(d['import']['revision'])}, content_type='image/png', data=raw)
    need(put.status_code == 200, 'fixture upload failed')
    finish = client.post(f'/api/media/local-imports/{uid}/finish', base_url=PUBLIC, headers=h,
                         json={'revision': put.json['import']['revision'], 'requestId': secrets.token_hex(16)})
    need(finish.status_code == 200, 'fixture finish failed'); d = finish.json; target = d['items'][0]['id']
    confirmed = client.post(f'/api/media/imports/{uid}/confirm', base_url=PUBLIC, headers=h,
        json={'revision': d['import']['revision'], 'confirmRequestId': secrets.token_hex(16), 'consentVersion': 'media-v1',
              'persistSelected': True, 'itemIds': [target]})
    need(confirmed.status_code == 200, 'fixture confirm failed')
    aid = '1'*32
    with engine.transaction(True) as con:
        tokens = engine.accounts.encrypt({'access_token': 'synthetic-token', 'scope': GOOGLE_PHOTOS_SCOPE, 'expires_at': time.time()+3600})
        con.execute('INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens) VALUES(?,?,?,?,?,?,?,?)',
                    (aid, 'member1', 'google', 'synthetic-client', 'synthetic-subject', 'Synthetic', 'synthetic.invalid', tokens))
        row = dict(con.execute('SELECT * FROM media_items WHERE id=?', (target,)).fetchone()); meta = engine._metadata(row)
        for index in range(1001):
            item = {**row, 'id': f'{index+1:024x}', 'account_id': aid,
                    'source_key': engine.cipher.source_key('member1', 'synthetic-google-fixture/v1', str(index)), 'preview_key': secrets.token_hex(12)}
            value = {**meta, 'source': 'google-photos', 'accountId': aid, 'sourceKey': item['source_key'], 'previewKey': item['preview_key']}
            for key in ('sourceVersion', 'uploadSha256'): value.pop(key, None)
            item['metadata_cipher'] = engine._seal('media-metadata', item, value)
            con.execute('INSERT INTO media_items('+','.join(item)+') VALUES('+','.join('?' for _ in item)+')', tuple(item.values()))
        need(con.execute("SELECT count(*) FROM media_items WHERE owner='member1' AND state='ready' AND confirmed_at IS NOT NULL").fetchone()[0] == 1002, 'fixture count differs')
    return {'targetId': target, 'ownerReadyRecords': 1002, 'candidateRecords': 1001, 'scanLimit': 1000,
            'fixtureNote': 'One real local upload; 1001 directly seeded, correctly row-bound encrypted Google metadata copies. No real Google connection or cloud import.'}


class Observations:
    """Observe real handlers and SQLite; do not replace responses or add delays."""
    def __init__(self, output):
        self.output = Path(output); self.lock = threading.Lock(); self.rows = {}
    def start(self, key):
        need(key in ('0', '1', '2', '3', 'recovery') and key not in self.rows, 'unexpected/repeated measured request')
        with self.lock: self.rows[key] = {'id': key, 'startedAt': time.time(), 'startedMono': time.monotonic(), 'scanCount': 0, 'blobReadCount': 0}
    def sql(self, key, sql):
        if ' FROM media_items WHERE owner=' in sql and ' AND id!=' in sql and 'ORDER BY id LIMIT' in sql:
            with self.lock: self.rows[key]['scanCount'] += 1
    def authorize(self, key, action, table, column):
        if action == sqlite3.SQLITE_READ and (table == 'media_video_cache' or (table == 'media_items' and column == 'preview_cipher')):
            with self.lock: self.rows[key]['blobReadCount'] += 1
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    def finish(self, key, status):
        with self.lock:
            self.rows[key].update(completedAt=time.time(), completedMono=time.monotonic(), status=status)
            save(self.output/('request-'+key+'.json'), self.rows[key])


def register_database_snapshots(app, output):
    """Fixture-only channel on the private probe network; never added to /app."""
    from flask import abort, jsonify
    engine = app.extensions['household_media']; phases = []; lock = threading.Lock()
    @app.get('/api/_probe/database-snapshot/<phase>')
    def snapshot(phase):
        if phase not in ('before', 'after'): abort(404)
        with engine.transaction() as con:
            if engine._member(con) != 'member1': abort(403)
        with lock:
            if phases != ([] if phase == 'before' else ['before']): abort(409)
            value = db_snapshot(engine.sessions.path)
            with engine.transaction() as con:
                if engine._member(con) != 'member1': abort(403)
            save(Path(output)/('database-'+phase+'.json'), value)
            phases.append(phase)
        return jsonify(value)


def measured_app():
    from flask import g, request
    from app import create_app
    forbid_outbound(); app = create_app(); engine = app.extensions['household_media']
    register_database_snapshots(app, '/proof')
    observer = Observations('/proof'); original = engine.sessions.db
    @contextmanager
    def connections():
        with original() as con:
            key = getattr(g, 'duplicate_probe', None)
            if key is not None:
                con.set_authorizer(lambda action, table, column, _db, _trigger: observer.authorize(key, action, table, column))
                con.set_trace_callback(lambda sql: observer.sql(key, sql))
            yield con
    engine.sessions.db = connections
    # Register first: observe request duration including original authentication,
    # not merely client thread launch. No response/status is substituted.
    def before():
        if request.path.endswith('/duplicates'):
            key = request.headers.get('X-Probe-Request'); observer.start(key); g.duplicate_probe = key
    app.before_request_funcs.setdefault(None, []).insert(0, before)
    @app.after_request
    def after(response):
        key = getattr(g, 'duplicate_probe', None)
        if key is not None: observer.finish(key, response.status_code)
        return response
    save('/proof/gunicorn-worker.json', {'pid': os.getpid(), 'testing': app.testing, 'loaded': runtime_proof(read('/input/input.json'))})
    return app


def app_inside():
    from app import create_app
    forbid_outbound(); app = create_app(); fixture = seed_fixture(app)
    save('/proof/ready.json', {**fixture, 'testing': app.testing, 'loaded': runtime_proof(read('/input/input.json'))})
    os.chdir('/app')
    os.execvp('gunicorn', ['gunicorn', '--pythonpath', '/input/tools,/app', '--bind', '0.0.0.0:8000',
        '--workers', '1', '--threads', '4', '--timeout', '45', '--access-logfile', '-',
        '--access-logformat', '%(m)s %(U)s %(s)s', 'probe:measured_app()'])


def checked_proof(responses, observations, recovery):
    need(len(responses) == 4 and {r['id'] for r in responses} == {'0', '1', '2', '3'}, 'four actual responses required')
    need(set(observations) == {'0', '1', '2', '3', 'recovery'}, 'server evidence incomplete')
    successful = []
    for r in [*responses, recovery]:
        need(r['status'] == observations[r['id']]['status'], 'server/client status differs')
        if r['status'] == 200:
            body = r['body']; coverage = body['coverage']
            need(coverage == {'scope': 'mine', 'scanLimit': 1000, 'scanned': 1000, 'capped': True, 'unverifiable': 0}
                 and body['limit'] == 20 and body['offset'] == 0 and len(body['items']) == 20 and body['total'] == 1000
                 and body['matchBasis'] == 'display-copy-sha256', 'actual bounded scan response differs')
            if r['id'] != 'recovery': successful.append(r)
        else: need(r['status'] == 503 and r['body'].get('code') == 'unavailable', 'unexpected HTTP failure')
    need(successful and recovery['status'] == 200, 'concurrent success/recovery absent')
    measured = [observations[str(i)] for i in range(4)]
    overlap = any(a['startedMono'] < b['completedMono'] and b['startedMono'] < a['completedMono']
                  for i, a in enumerate(measured) for b in measured[i+1:])
    scans = sum(r['scanCount'] for r in measured); blobs = sum(r['blobReadCount'] for r in observations.values())
    need(overlap and scans >= 1 and blobs == 0, 'actual overlap/scan/no-BLOB proof absent')
    return dict(concurrency=4, ownerReadyRecords=1002, candidateRecords=1001, scanLimit=1000,
                scanInvocationCount=scans, recoveryScanInvocationCount=observations['recovery']['scanCount'],
                blobReadCount=blobs, overlapObserved=overlap, responses=[{'status': r['status'], **({'code': 'unavailable'} if r['status'] == 503 else {})} for r in responses],
                recoveryStatus=200, coverageCapped=True)


def client_inside():
    from concurrent.futures import ThreadPoolExecutor
    import http.client
    from http.cookies import SimpleCookie
    cookies = {}; failure = None; proof = {}; records = []; lock = threading.Lock()
    def request(method, path, body=None, key=None):
        conn = http.client.HTTPConnection('app', 8000, timeout=60)
        headers = {'Host': 'probe.invalid', 'Origin': PUBLIC, 'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'probe.invalid'}
        if cookies: headers['Cookie'] = '; '.join(k+'='+v for k, v in cookies.items())
        if key is not None: headers['X-Probe-Request'] = key
        data = None if body is None else json.dumps(body).encode()
        if data is not None: headers['Content-Type'] = 'application/json'
        began = time.time()
        try:
            conn.request(method, path, data, headers); response = conn.getresponse()
            for k, v in response.getheaders():
                if k.lower() == 'set-cookie':
                    parsed = SimpleCookie(); parsed.load(v)
                    with lock: cookies.update({n: m.value for n, m in parsed.items()})
            raw = response.read(2*MIB+1); need(len(raw) <= 2*MIB, 'unexpected control response size')
            r = {'id': key, 'method': method, 'path': path, 'startedAt': began, 'completedAt': time.time(),
                 'status': response.status, 'body': json.loads(raw)}
            with lock: records.append(r)
            return r
        finally: conn.close()
    def wait_file(path, seconds=90):
        deadline = time.monotonic()+seconds
        while not Path(path).exists(): need(time.monotonic() < deadline, 'bounded readiness/ACK timeout'); time.sleep(.1)
    try:
        wait_file('/observations/gunicorn-worker.json')
        ready = read('/observations/ready.json')
        need(request('POST', '/api/login', {'username': 'member1', 'password': PASSWORD})['status'] == 200, 'real HTTP login failed')
        snapshot = request('GET', '/api/_probe/database-snapshot/before')
        need(snapshot['status'] == 200, 'app-side before snapshot failed')
        before = snapshot['body']; save('/proof/ready.json', {'authenticated': True})
        wait_file('/control/go.json'); barrier = threading.Barrier(4, timeout=10)
        path = '/api/media/items/'+ready['targetId']+'/duplicates?limit=20&offset=0'
        def query(i): barrier.wait(); return request('GET', path, key=str(i))
        with ThreadPoolExecutor(max_workers=4) as pool: responses = list(pool.map(query, range(4)))
        recovery = request('GET', path, key='recovery')
        observations = {str(i): read('/observations/request-'+str(i)+'.json') for i in (*range(4), 'recovery')}
        proof = checked_proof(responses, observations, recovery)
        snapshot = request('GET', '/api/_probe/database-snapshot/after')
        need(snapshot['status'] == 200, 'app-side after snapshot failed')
        after = snapshot['body']
        database = {'before': before['sha256'], 'after': after['sha256'], 'beforeTables': before['tables'],
                    'afterTables': after['tables'], 'normalization': before['normalization']}
        save('/proof/database.json', database); need(database['before'] == database['after'], 'business data changed')
    except BaseException as error: failure = type(error).__name__+': '+str(error)
    finally:
        # Login response contains CSRF/session descriptors; retain only measured
        # synthetic duplicate bodies, never signed cookies or credentials.
        save('/proof/http.json', [r for r in records if r['id'] is not None])
        save('/proof/database-http.json', [r for r in records if r['path'] in (
            '/api/_probe/database-snapshot/before', '/api/_probe/database-snapshot/after')])
        proof.update(passed=failure is None, failure=failure); save('/proof/result.json', proof)
        save('/proof/finished.json', {'passed': failure is None, 'resultSha256': sha('/proof/result.json')})
    need(failure is None, 'client workload failed; inspect originals')
    wait_file('/control/release.json')


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='action', required=True)
    a = sub.add_parser('prepare')
    for n in ('source-root', 'expected-head', 'package', 'package-sha256', 'build', 'build-sha256', 'output-dir'): a.add_argument('--'+n, required=True)
    a = sub.add_parser('run')
    for n in ('input-root', 'input-sha256', 'output-dir'): a.add_argument('--'+n, required=True)
    a = sub.add_parser('inside'); a.add_argument('--role', choices=LIMITS, required=True)
    args = p.parse_args()
    if args.action == 'prepare': prepare(args.source_root, args.expected_head, args.package, args.package_sha256, args.build, args.build_sha256, args.output_dir)
    elif args.action == 'run': run(args.input_root, args.output_dir, args.input_sha256)
    elif args.role == 'app': app_inside()
    else: client_inside()


if __name__ == '__main__': main()
