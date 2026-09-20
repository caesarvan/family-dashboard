"""Offline tool boundaries. These are not Linux/Gunicorn resource results."""
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

from deploy import discovery_duplicate_linux_probe as p


def contracts():
    runtime = {'app.py': 'a'*64, **{f'm{i}.py': 'b'*64 for i in range(111)}}
    exports = {f'file{i}': 'e'*64 for i in range(23)}
    meta = dict(sourceHead='a'*40, tree='b'*40, manifestSha256='c'*64,
                runtimeFiles={**runtime, **{'static/experience/'+n: h for n, h in exports.items()}}, exportFiles=exports)
    build = dict(exitCode=0, productionOperations=False, sourceHead=meta['sourceHead'], tree=meta['tree'],
                 packageSha256='d'*64, manifestSha256=meta['manifestSha256'], runtimeHashes=meta['runtimeFiles'], imageId='sha256:'+'e'*64)
    return meta, build


@pytest.mark.parametrize('field,value', [('imageId', 'latest'), ('exitCode', 1), ('sourceHead', 'f'*40), ('runtimeHashes', {})])
def test_actual_build_identity_mismatch_rejected(field, value):
    meta, build = contracts(); build[field] = value
    with pytest.raises(RuntimeError): p.binding(meta, build, 'd'*64, 'e'*64)


def test_binding_pins_whole_image_without_overlay():
    meta, build = contracts(); result = p.binding(meta, build, 'd'*64, 'e'*64)
    assert len(result['runtimeFiles']) == 112 and len(result['exportFiles']) == 23
    assert result['imageId'] == build['imageId'] and result['buildSha256'] == 'e'*64


def test_container_argv_restricted_to_owned_paths_and_immutable_app(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'ROOT', tmp_path)
    prepared = tmp_path/'input'; prepared.mkdir(); out = tmp_path/'output'; out.mkdir()
    for folder in ('app', 'client', 'control', 'data'): (out/folder).mkdir()
    c = {'imageId': 'sha256:'+'e'*64}
    for role in p.LIMITS:
        args = p.container_args(role, 'a'*64, 'dd-'+'b'*16, prepared, out, c)
        assert '--memory='+str(p.LIMITS[role])+'m' in args
        assert '--memory-swap='+str(p.LIMITS[role])+'m' in args
        assert '--read-only' in args and '--user=10001:10001' in args and '--cap-drop=ALL' in args
        assert c['imageId'] in args and '-i' in args and 'PYTHONPATH=/app' in args
        assert not any('/runtime' in x or 'docker.sock' in x or x in ('-p', '--publish', '--privileged') for x in args)
    with pytest.raises(RuntimeError): p.container_args('decoder', 'a'*64, 'dd-'+'b'*16, prepared, out, c)


def sample(at=1):
    return {'at': at, 'monotonic': at, 'roles': {r: {'memory.max': str(n*p.MIB), 'memory.peak': '10000000',
        'memory.current': '9000000', 'memory.swap.max': '0', 'memory.events': 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0'} for r, n in p.LIMITS.items()}}


@pytest.mark.parametrize('key', ['max', 'oom', 'oom_kill', 'oom_group_kill'])
def test_limit_events_reject_even_successful_http(key):
    value = sample(); value['roles']['app']['memory.events'] = value['roles']['app']['memory.events'].replace(key+' 0', key+' 1')
    with pytest.raises(RuntimeError, match='memory event'): p.resource_samples([value])


def test_monitoring_gap_missing_role_or_limit_fails_closed():
    p.resource_samples([sample(), sample(1.25)])
    with pytest.raises(RuntimeError, match='gap'): p.resource_samples([sample(), sample(2.01)])
    value = sample(); del value['roles']['client']
    with pytest.raises(RuntimeError): p.resource_samples([value])
    value = sample(); value['roles']['app']['memory.max'] = str(768*p.MIB)
    with pytest.raises(RuntimeError): p.resource_samples([value])
    value = sample(); value['roles']['app']['memory.swap.max'] = '1'
    with pytest.raises(RuntimeError): p.resource_samples([value])


def proof_rows():
    body = {'coverage': {'scope': 'mine', 'scanLimit': 1000, 'scanned': 1000, 'capped': True, 'unverifiable': 0},
            'limit': 20, 'offset': 0, 'items': [{}]*20, 'total': 1000, 'matchBasis': 'display-copy-sha256'}
    responses = [{'id': str(i), 'status': 200 if i == 0 else 503, 'body': body if i == 0 else {'code': 'unavailable'}} for i in range(4)]
    recovery = {'id': 'recovery', 'status': 200, 'body': body}
    observations = {str(i): {'status': r['status'], 'scanCount': 2 if i == 0 else 0, 'blobReadCount': 0,
                            'startedMono': i*.1, 'completedMono': 1+i*.1} for i, r in enumerate(responses)}
    observations['recovery'] = {'status': 200, 'scanCount': 2, 'blobReadCount': 0, 'startedMono': 2, 'completedMono': 3}
    return responses, observations, recovery


def test_actual_scan_count_excludes_recovery_and_requires_server_overlap():
    responses, observations, recovery = proof_rows()
    proof = p.checked_proof(responses, observations, recovery)
    assert proof['scanInvocationCount'] == 2 and proof['recoveryScanInvocationCount'] == 2
    for i in range(4): observations[str(i)].update(startedMono=i*2, completedMono=i*2+1)
    with pytest.raises(RuntimeError, match='overlap'): p.checked_proof(responses, observations, recovery)


def test_no_concurrent_success_or_blob_attempt_cannot_pass():
    responses, observations, recovery = proof_rows()
    observations['recovery']['blobReadCount'] = 1
    with pytest.raises(RuntimeError): p.checked_proof(responses, observations, recovery)
    responses, observations, recovery = proof_rows()
    responses[0].update(status=503, body={'code': 'unavailable'}); observations['0']['status'] = 503
    with pytest.raises(RuntimeError): p.checked_proof(responses, observations, recovery)


def test_snapshot_keeps_all_business_bytes_and_normalizes_only_session_touch(tmp_path):
    path = tmp_path/'one.sqlite3'
    con = sqlite3.connect(path)
    con.executescript('CREATE TABLE member_sessions(id TEXT, last_seen_at REAL, revoked_at REAL); CREATE TABLE business(id TEXT, encrypted BLOB);')
    con.execute('INSERT INTO member_sessions VALUES(?,?,?)', ('one', 1, None)); con.execute('INSERT INTO business VALUES(?,?)', ('one', b'not plaintext'))
    con.commit(); before = p.db_snapshot(path)
    con.execute('UPDATE member_sessions SET last_seen_at=2'); con.commit()
    assert p.db_snapshot(path) == before
    con.execute('UPDATE member_sessions SET revoked_at=3'); con.commit()
    assert p.db_snapshot(path)['sha256'] != before['sha256']
    con.execute('UPDATE member_sessions SET revoked_at=NULL'); con.execute('UPDATE business SET encrypted=?', (b'changed',)); con.commit()
    assert p.db_snapshot(path)['sha256'] != before['sha256']; con.close()


def test_real_encrypted_fixture_scan_authorizer_and_receipts(tmp_path, monkeypatch):
    from app import create_app
    monkeypatch.setenv('MEMBER1_PASSWORD', p.PASSWORD); monkeypatch.setenv('MEMBER2_PASSWORD', p.PASSWORD)
    app = create_app({'DATA_DIR': str(tmp_path/'data'), 'SECRET_KEY': p.SECRET, 'PUBLIC_ORIGIN': p.PUBLIC,
                      'SESSION_COOKIE_SECURE': True, 'GOOGLE_CLIENT_ID': 'synthetic-client', 'GOOGLE_CLIENT_SECRET': 'synthetic-secret'})
    fixture = p.seed_fixture(app); engine = app.extensions['household_media']; original = engine.sessions.db
    observer = p.Observations(tmp_path); observer.start('0')
    @contextmanager
    def db():
        with original() as con:
            con.set_authorizer(lambda a, t, c, _d, _r: observer.authorize('0', a, t, c))
            con.set_trace_callback(lambda sql: observer.sql('0', sql)); yield con
    monkeypatch.setattr(engine.sessions, 'db', db)
    client = app.test_client()
    assert client.post('/api/login', base_url=p.PUBLIC, json={'username': 'member1', 'password': p.PASSWORD}).status_code == 200
    before = p.db_snapshot(engine.sessions.path)
    response = client.get('/api/media/items/'+fixture['targetId']+'/duplicates?limit=20', base_url=p.PUBLIC)
    observer.finish('0', response.status_code)
    assert response.status_code == 200 and response.json['coverage']['scanned'] == 1000 and response.json['coverage']['capped']
    assert response.json['total'] == 1000 and len(response.json['items']) == 20
    assert observer.rows['0']['scanCount'] == 2 and observer.rows['0']['blobReadCount'] == 0
    assert p.db_snapshot(engine.sessions.path) == before
    assert p.read(tmp_path/'request-0.json')['status'] == 200
    assert fixture['ownerReadyRecords'] == 1002


def test_preflight_block_preserves_failure_without_docker(tmp_path, monkeypatch):
    prepared = tmp_path/'input'; prepared.mkdir(); p.save(prepared/'input.json', {})
    monkeypatch.setattr(p, 'ROOT', tmp_path); monkeypatch.setattr(p.sys, 'platform', 'linux')
    monkeypatch.setattr(p, 'checked_input', lambda _path: {'imageId': 'sha256:'+'e'*64})
    monkeypatch.setattr(p.ipc, 'host_preflight', lambda _path: {'status': 'preflight_blocked'})
    monkeypatch.setattr(p.ipc.Executor, 'call', lambda *a, **k: pytest.fail('Docker must not start'))
    output = tmp_path/'run'
    with pytest.raises(RuntimeError, match='not passed'): p.run(prepared, output, p.sha(prepared/'input.json'))
    result = p.read(output/'result.json')
    assert not result['passed'] and 'preflight blocked' in result['failure']
    assert result['containers'] == {} and result['commands'] == [] and result['cleanupErrors'] == []
    assert result['artifacts']['cgroup-samples.json'] == p.sha(output/'cgroup-samples.json')


def test_unknown_create_does_not_guess_container_and_still_saves_receipt(tmp_path, monkeypatch):
    prepared = tmp_path/'input'; prepared.mkdir(); p.save(prepared/'input.json', {})
    monkeypatch.setattr(p, 'ROOT', tmp_path); monkeypatch.setattr(p.sys, 'platform', 'linux')
    monkeypatch.setattr(p.os, 'chown', lambda *_: None, raising=False)
    monkeypatch.setattr(p, 'checked_input', lambda _path: {'imageId': 'sha256:'+'e'*64})
    monkeypatch.setattr(p.ipc, 'host_preflight', lambda _path: {'status': 'ready'})
    class Monitor:
        thread = None; failure = None
        def __init__(self, _out): pass
        def start(self): pass
        def check(self): pass
    monkeypatch.setattr(p.ipc, 'HostMemoryMonitor', Monitor)
    calls = []
    def call(self, argv, **_kwargs):
        calls.append(argv)
        if argv[:2] == ['network', 'create']: return 0, ('a'*64).encode()
        if argv[:2] == ['network', 'inspect']:
            token = calls[0][-1]
            return 0, json.dumps([{'Id': 'a'*64, 'Internal': True, 'Labels': {'discovery-duplicates': token}, 'Containers': {}}]).encode()
        if argv[0] == 'create': raise RuntimeError('create outcome unknown')
        pytest.fail('must not guess cleanup identity')
    monkeypatch.setattr(p.ipc.Executor, 'call', call)
    with pytest.raises(RuntimeError): p.run(prepared, tmp_path/'run', p.sha(prepared/'input.json'))
    result = p.read(tmp_path/'run/result.json')
    assert not result['passed'] and result['unknownCreate'] == {'kind': 'container', 'role': 'app'}
    assert result['containers'] == {} and not any(x[0] in ('stop', 'kill', 'rm') for x in calls)


def test_pressure_stops_all_verified_owned_ids_before_inspection_and_keeps_failure(tmp_path, monkeypatch):
    prepared = tmp_path/'input'; prepared.mkdir(); p.save(prepared/'input.json', {})
    monkeypatch.setattr(p, 'ROOT', tmp_path); monkeypatch.setattr(p.sys, 'platform', 'linux')
    monkeypatch.setattr(p.os, 'chown', lambda *_: None, raising=False)
    monkeypatch.setattr(p, 'checked_input', lambda _path: {'imageId': 'sha256:'+'e'*64})
    monkeypatch.setattr(p.ipc, 'host_preflight', lambda _path: {'status': 'ready'})
    class Monitor:
        thread = True; failure = None
        def __init__(self, output): self.output = output; monitors.append(self)
        def start(self): pass
        def check(self): pass
        def finish(self): return {'failure': self.failure}
    monitors = []; calls = []; containers = {}
    monkeypatch.setattr(p.ipc, 'HostMemoryMonitor', Monitor)
    def call(self, argv, **_kwargs):
        calls.append(argv)
        if argv[:2] == ['network', 'create']: return 0, ('a'*64).encode()
        if argv[:2] == ['network', 'inspect']:
            return 0, json.dumps([{'Id': 'a'*64, 'Internal': True, 'Labels': {'discovery-duplicates': calls[0][-1]}, 'Containers': {}}]).encode()
        if argv[0] == 'create':
            role = argv[argv.index('--network-alias')+1]; cid = ('b' if role == 'app' else 'c')*64
            containers[cid] = {'Id': cid, 'Image': 'sha256:'+'e'*64, 'Name': '/'+calls[0][-1]+'-'+role,
                'Config': {'User': '10001:10001', 'Labels': {'discovery-duplicates': calls[0][-1]}},
                'HostConfig': {'Memory': p.LIMITS[role]*p.MIB, 'MemorySwap': p.LIMITS[role]*p.MIB, 'ReadonlyRootfs': True,
                    'Privileged': False, 'PortBindings': {}, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true']},
                'State': {'Running': False, 'Pid': 0, 'OOMKilled': False, 'ExitCode': 0}}
            return 0, cid.encode()
        if argv[0] == 'inspect': return 0, json.dumps(containers[argv[-1]]).encode()
        if argv[0] == 'start':
            containers[argv[-1]]['State'].update(Running=True, Pid=123)
            if argv[-1] == 'c'*64:
                monitors[0].failure = {'reason': 'pressure'}; raise p.ipc.HostMemoryAbort('pressure')
            return 0, b''
        if argv[0] == 'kill': containers[argv[-1]]['State'].update(Running=False, Pid=0, ExitCode=137); return 0, b''
        if argv[0] in ('logs', 'rm') or argv[:2] == ['network', 'rm']: return 0, b''
        pytest.fail('unexpected command '+str(argv))
    monkeypatch.setattr(p.ipc.Executor, 'call', call)
    with pytest.raises(RuntimeError): p.run(prepared, tmp_path/'run', p.sha(prepared/'input.json'))
    kill_at = [i for i, a in enumerate(calls) if a[0] == 'kill']
    assert len(kill_at) == 2 and kill_at[1] == kill_at[0]+1
    assert {calls[i][1] for i in kill_at} == {'b'*64, 'c'*64}
    result = p.read(tmp_path/'run/result.json')
    assert not result['passed'] and 'pressure' in result['failure'] and result['cleanupErrors'] == []
    assert (tmp_path/'run/app-final.json').exists() and (tmp_path/'run/client-final.json').exists()
