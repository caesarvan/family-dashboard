"""Rehearsal safety/identity/failure checks; no app, Docker, network or database."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest

from deploy import task_reminders_linux_rehearsal as rehearsal

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:' + '1' * 64
PACKAGE = '2' * 64


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('No actual process/network allowed in these safety tests')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


@pytest.fixture
def inputs(tmp_path):
    candidate = tmp_path / 'candidate'; source = candidate / 'source'
    source.mkdir(parents=True)
    (candidate / 'package').mkdir()
    names = [rehearsal.SELF, 'deploy/build_task_reminders_release.py',
             'deploy/membership_release_package.py', 'deploy/membership_release_build.py',
             'deploy/steady_linux_rehearsal.py', 'deploy/journey_routes_linux_rehearsal.py', 'deploy/rehearse_restore.py',
             'deploy/membership_release_controller.py', 'docs/DEPLOYMENT.md', 'docs/MEMBER-SESSIONS.md']
    blobs = {n: (ROOT / n).read_bytes() for n in names}
    for name, raw in blobs.items():
        target = source / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    manifest_raw = b'{"synthetic":true}\n'
    (source / 'RELEASE-MANIFEST.json').write_bytes(manifest_raw)
    verified = {'blobs': blobs, 'manifest': {'files': {n: rehearsal.sha(v) for n, v in blobs.items()}},
                'metadata': {'manifestSha256': rehearsal.sha(manifest_raw), 'sourceHead': '3' * 40,
                             'tree': '4' * 40, 'parentImage': rehearsal.profile.PARENT_IMAGE,
                             'oldManifestSha256': rehearsal.profile.OLD_MANIFEST,
                             'runtimeFiles': {'app.py': '5' * 64}}}
    return candidate, source, verified


def test_generated_programs_bind_real_migration_and_documented_restore(inputs):
    _, source, verified = inputs
    original = rehearsal.restore.documented_programs(source)[0]
    code, binding = rehearsal.programs(verified['blobs'], original)
    assert set(code) == {'RUNTIME', 'SEED', 'BEGIN', 'MIGRATE', 'STARTUP', 'CHECK', 'RESTORE_OLD',
                         'POPULATE', 'RESTART', 'POPULATED_CHECK', 'POPULATED_BACKUP', 'RESTORE_CURRENT'}
    for name, program in code.items():
        compile(program, '<' + name + '>', 'exec')
    assert 'len(tables)==69' in code['SEED'] and 'len(tables)==61' not in code['SEED']
    assert all('INSERT INTO ' + name in code['SEED'] for name in rehearsal.FINANCE_TABLES)
    assert all('INSERT INTO ' + name in code['SEED'] for name in rehearsal.ROUTE_COUNTS)
    assert 'CREATE TABLE' not in code['SEED'] and 'CREATE TABLE' not in code['MIGRATE']
    assert 'git ' not in code['SEED'] and 'subprocess' not in code['SEED']
    for name, call in [('BEGIN', 'begin'), ('MIGRATE', 'migrate'), ('CHECK', 'check_stopped')]:
        assert 'from deploy import check_task_reminders_migration as current' in code[name]
        assert 'current.' + call + '(root,proof,source_identity=identity' in code[name]
    prefix = rehearsal.previous.literal(verified['blobs']['deploy/membership_release_controller.py'], 'DATA_PREFIX')
    assert code['STARTUP'] == prefix + rehearsal.previous.STARTUP_PROGRAM
    assert code['RESTART'] == prefix + rehearsal.previous.STARTUP_PROGRAM.replace('app-startup.json', 'app-restart-populated.json')
    assert binding['originalSha256'] == rehearsal.sha(original.encode())
    for name in ('restored-old', 'restored-current'):
        changed = original.replace("root = Path('/data').resolve(strict=True)",
                                   "root = Path('/proof/" + name + "').resolve(strict=True)", 1)
        assert binding['executedSha256'][name] == rehearsal.sha(changed.encode())
        target = 'RESTORE_OLD' if name == 'restored-old' else 'RESTORE_CURRENT'
        strings = [n.value for n in ast.walk(ast.parse(code[target])) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert changed in strings
        assert 'UPDATE member_session_browsers' not in code[target]
        assert 'app.create_app' not in code[target]
    assert 'exist_ok=False' in code['RESTORE_OLD'] and "target.open('xb')" in code['RESTORE_OLD']


@pytest.mark.parametrize('old', ['len(tables)==61', "'householdTables':61", 'app-startup.json'])
def test_program_source_anchor_drift_is_rejected(inputs, monkeypatch, old):
    _, source, verified = inputs
    attribute = 'STARTUP_PROGRAM' if old == 'app-startup.json' else 'SEED_PROGRAM'
    monkeypatch.setattr(rehearsal.previous, attribute, getattr(rehearsal.previous, attribute).replace(old, 'CHANGED_ANCHOR'))
    with pytest.raises(ValueError):
        rehearsal.programs(verified['blobs'], rehearsal.restore.documented_programs(source)[0])


def test_restore_root_anchor_must_be_unique(inputs):
    _, source, verified = inputs
    original = rehearsal.restore.documented_programs(source)[0]
    for changed in (original.replace("Path('/data')", "Path('/other')"), original + '\n' + original):
        with pytest.raises(ValueError):
            rehearsal.programs(verified['blobs'], changed)


@pytest.mark.parametrize('drift', [None, 'runner', 'routes-helper', 'tree', 'parent', 'old_manifest'])
def test_candidate_requires_fixed_helpers_source_and_baseline(inputs, monkeypatch, drift):
    candidate, source, verified = inputs
    changed = deepcopy(verified)
    if drift == 'runner': changed['blobs'][rehearsal.SELF] += b'\n# unreviewed\n'
    if drift == 'routes-helper': changed['blobs']['deploy/journey_routes_linux_rehearsal.py'] += b'\n# drift\n'
    if drift == 'tree': (source / 'unreviewed.py').write_text('# no\n')
    if drift == 'parent': changed['metadata']['parentImage'] = IMAGE
    if drift == 'old_manifest': changed['metadata']['oldManifestSha256'] = '0' * 64
    monkeypatch.setattr(rehearsal.profile, 'verify_package', lambda *_args: changed)
    if drift is None:
        actual_candidate, actual_source, actual_verified = rehearsal.candidate_input(candidate, PACKAGE)
        assert actual_candidate.samefile(candidate) and actual_source.samefile(source)
        assert actual_verified == verified
    else:
        with pytest.raises(ValueError): rehearsal.candidate_input(candidate, PACKAGE)


@pytest.mark.parametrize('write,seed', [(False, False), (True, False), (True, True)])
def test_actual_phase_constructor_has_only_synthetic_mounts_and_bounded_resources(tmp_path, write, seed):
    calls = []
    def recorded(args, **kwargs):
        calls.append((args, kwargs))
        output = b'a' * 64 if args[0] == 'create' else b'{"ok":true}' if args[0] == 'start' else b''
        return subprocess.CompletedProcess(args, 0, output, b'')
    source, output = tmp_path / 'source', tmp_path / 'output'
    assert rehearsal.previous.phase(recorded, IMAGE, 'print(1)', source, output, write=write, seed=seed) == {'ok': True}
    args = calls[0][0]
    for flag, value in [('--network', 'none'), ('--user', '10001:10001'), ('--memory', '1024m'),
                        ('--pids-limit', '256'), ('--security-opt', 'no-new-privileges:true'), ('--cap-drop', 'ALL')]:
        assert args[args.index(flag) + 1] == value
    assert '--read-only' in args and '/tmp:rw,size=805306368,mode=1777' in args
    mounts = [args[i + 1] for i, value in enumerate(args) if value == '--mount']
    assert mounts == [f'type=bind,src={output / "data"},dst=/data' + ('' if write else ',readonly'),
                      f'type=bind,src={output / "proof"},dst=/proof'] + ([] if seed else [f'type=bind,src={source},dst=/release,readonly'])
    assert args[-4:] == [IMAGE, '-B', '-c', 'print(1)']
    assert calls[-1][0] == ['rm', '--force', 'a' * 64]
    assert calls[1][1]['timeout'] == 360


def install_recorded_run(inputs, monkeypatch, failure=None):
    candidate, source, verified = inputs
    monkeypatch.setattr(rehearsal.sys, 'platform', 'linux')
    monkeypatch.setattr(rehearsal.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(rehearsal.os, 'chown', lambda *_args: None, raising=False)
    for name in list(os.environ):
        if name.upper().startswith(('DOCKER_', 'COMPOSE_')): monkeypatch.delenv(name)
    monkeypatch.setattr(rehearsal, 'candidate_input', lambda *_args: (candidate, source, verified))
    monkeypatch.setattr(rehearsal.build, 'inspect_image', lambda _run, image: {
        'RootFS': {'Layers': ['old'] if image == rehearsal.profile.PARENT_IMAGE else ['old', 'cleanup', 'copy']},
        'Config': {'User': '10001:10001'}})
    code = rehearsal.programs(verified['blobs'], rehearsal.restore.documented_programs(source)[0])[0]
    calls = []
    def phase(_docker, image, program, _source, _output, **options):
        name = next(n for n, value in code.items() if value == program)
        calls.append((name, image, options))
        if name == failure: raise RuntimeError('synthetic failure at ' + name)
        if name == 'RUNTIME': return verified['metadata']['runtimeFiles']
        if name == 'SEED': return dict(seeded=True, households=2, databases=3, householdTables=69, platformTables=9)
        if name in ('STARTUP', 'RESTART'): return dict(initialized=True, households=2)
        if name == 'POPULATE': return dict(populated=True, households=2, statesPerHousehold=2, receiptsPerHousehold=2, workerStarted=False)
        if name == 'POPULATED_BACKUP': return dict(databases=3)
        return dict(verified=True, completeGroupRestored=True, databases=3, logicalSha256='6' * 64)
    monkeypatch.setattr(rehearsal.previous, 'phase', phase)
    monkeypatch.setattr(rehearsal, 'check_group', lambda _proof: {'verified': True})
    return calls


@pytest.mark.parametrize('failure', [None, 'MIGRATE', 'STARTUP', 'RESTORE_OLD', 'POPULATED_CHECK', 'RESTORE_CURRENT'])
def test_recorded_lifecycle_preserves_failure_and_never_replays(inputs, monkeypatch, tmp_path, failure):
    calls = install_recorded_run(inputs, monkeypatch, failure)
    output = tmp_path / 'attempt'
    result = rehearsal.rehearse(inputs[0], PACKAGE, IMAGE, output)
    order = ['RUNTIME', 'SEED', 'BEGIN', 'MIGRATE', 'STARTUP', 'CHECK', 'RESTORE_OLD',
             'POPULATE', 'RESTART', 'POPULATED_CHECK', 'POPULATED_BACKUP', 'RESTORE_CURRENT']
    expected = order if failure is None else order[:order.index(failure) + 1]
    assert [n for n, _, _ in calls] == expected
    assert result['passed'] is (failure is None)
    assert (output / 'result.json').is_file() and (output / 'proof/rehearsal-contract.json').is_file()
    for name, image, options in calls:
        assert image == (rehearsal.profile.PARENT_IMAGE if name == 'SEED' else IMAGE)
        assert options.get('write', False) == (name in {'SEED', 'BEGIN', 'MIGRATE', 'STARTUP', 'POPULATE', 'RESTART', 'POPULATED_BACKUP'})
    original = (output / 'result.json').read_bytes()
    with pytest.raises(ValueError): rehearsal.rehearse(inputs[0], PACKAGE, IMAGE, output)
    assert (output / 'result.json').read_bytes() == original and len(calls) == len(expected)
    assert json.loads(original)['restoreProgram']['originalSha256']


@pytest.mark.parametrize('selector', ['DOCKER_HOST', 'compose_file'])
def test_ambient_daemon_selectors_rejected_before_candidate_read(inputs, monkeypatch, tmp_path, selector):
    calls = install_recorded_run(inputs, monkeypatch)
    monkeypatch.setenv(selector, 'forbidden-synthetic-selector')
    with pytest.raises(ValueError, match='ambient Docker selector'):
        rehearsal.rehearse(inputs[0], PACKAGE, IMAGE, tmp_path / 'never-created')
    assert not (tmp_path / 'never-created').exists() and calls == []


def test_populated_program_calls_real_task_and_reminder_apis_without_sql_state_inserts(inputs):
    _, source, verified = inputs
    code, _ = rehearsal.programs(verified['blobs'], rehearsal.restore.documented_programs(source)[0])
    program = code['POPULATE']
    strings = [n.value for n in ast.walk(ast.parse(program)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert '/api/login' in strings and '/api/me' in strings and '/api/items/tasks' in strings
    assert '/api/task-reminders?filter=all&page=0' in strings
    assert '/api/task-reminders/operations/' in strings and '/actions' in strings
    assert 'response.status_code==200' in program and 'replay.json==response.json' in program
    assert 'recovered.json==response.json' in program
    assert 'clock=' not in program and '.tick(' not in program
    assert 'INSERT INTO task_reminders' not in program and 'INSERT INTO task_reminder_operations' not in program
    assert 'current.snapshot_current(root)' in program and "proof/'populated-api-receipts.json'" in program
    assert "value['tables'][table]==before['databases'][relative]['tables'][table]" in program
    assert set(rehearsal.FINANCE_TABLES) | set(rehearsal.ROUTE_COUNTS) | {'settings'} <= set(strings)


def test_route_sentinel_anchor_drift_is_rejected(inputs, monkeypatch):
    _, source, verified = inputs
    monkeypatch.setattr(rehearsal.routes, 'POPULATE_ROUTES', 'pass')
    with pytest.raises(ValueError, match='route sentinel layout changed'):
        rehearsal.programs(verified['blobs'], rehearsal.restore.documented_programs(source)[0])


@pytest.mark.parametrize('fault', [None, 'finance', 'routes', 'new-not-empty', 'tables', 'group', 'marker'])
def test_summary_refuses_missing_sentinels_or_initial_rows(tmp_path, fault):
    old_tables = {n: {'count': 1} for n in rehearsal.FINANCE_TABLES}
    old_tables.update({n: {'count': total} for n, total in rehearsal.ROUTE_COUNTS.items()})
    old_tables.update({f'original_{i}': {'count': 0} for i in range(69-len(old_tables))})
    old = {'tables': old_tables}
    new = deepcopy(old)
    new['tables'].update(task_reminders={'count': 0}, task_reminder_operations={'count': 0})
    platform = {'tables': {f'registry_{i}': {'count': 0} for i in range(9)}}
    before = {'households': 2, 'databases': {'platform.sqlite3': platform,
        'household.sqlite3': old, 'spaces/'+'a'*24+'/household.sqlite3': deepcopy(old)}}
    after = {'households': 2, 'databases': {'platform.sqlite3': deepcopy(platform),
        'household.sqlite3': new, 'spaces/'+'a'*24+'/household.sqlite3': deepcopy(new)}}
    result = {'verified': True, 'markerSha256': rehearsal.sha(rehearsal.previous.SYNTHETIC_MARKER),
              'logicalSha256': 'a'*64}
    if fault == 'finance': after['databases']['household.sqlite3']['tables'][rehearsal.FINANCE_TABLES[0]]['count'] = 0
    if fault == 'routes': after['databases']['household.sqlite3']['tables']['journey_route_operations']['count'] = 1
    if fault == 'new-not-empty': after['databases']['household.sqlite3']['tables']['task_reminders']['count'] = 1
    if fault == 'tables': after['databases']['household.sqlite3']['tables']['unexpected'] = {'count': 0}
    if fault == 'group': after['households'] = 1
    if fault == 'marker': result['markerSha256'] = 'b'*64
    for name, value in [('before.json', before), ('migrated.json', after), ('after.json', after), ('result.json', result)]:
        (tmp_path/name).write_text(json.dumps(value))
    if fault is None:
        actual = rehearsal.check_group(tmp_path)
        assert actual['householdTables'] == [69, 71] and actual['platformTables'] == [9, 9]
        assert actual['newReminderTablesEmpty'] is True and actual['preservedRouteRowsPerHousehold'] == rehearsal.ROUTE_COUNTS
    else:
        with pytest.raises(ValueError): rehearsal.check_group(tmp_path)
