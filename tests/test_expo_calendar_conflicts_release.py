"""UI-only package boundary, recorded lifecycle and real populated 71/9 SQLite."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest
from deploy import build_expo_calendar_conflicts_release as package
from deploy import activate_expo_calendar_conflicts_release as controller
from deploy import expo_calendar_conflicts_release_data as data
from deploy import build_task_reminders_release as previous
from deploy import membership_release_package as policy
from deploy import membership_release_controller as common
from deploy import membership_release_data as membership
from deploy import assistant_trip_change_release_controller as core
import test_task_reminders_release as reminders
import test_journey_routes_release as routes
import test_assistant_trip_change_release as lifecycle
import test_steady_release_package as package_tests
from test_assistant_trip_change_release import steady_simulation, old_simulation
from test_membership_release_package import ROOT, write, commit
from test_membership_migration import startup, clone_databases


@pytest.fixture
def package_environment(tmp_path, monkeypatch):
    env = reminders.package_environment.__wrapped__(tmp_path, monkeypatch)
    for name in controller.SPEC.operators:
        write(env['repo'], 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    for name in package.FRONTEND_TESTS - previous.FRONTEND_TESTS:
        write(env['repo'], name, b'// synthetic frontend input\n')
    for name in package.BROWSER_SCRIPTS - previous.BROWSER_SCRIPTS:
        write(env['repo'], name, b'# synthetic reviewed browser input\n')
    routes.refresh_evidence(env)
    return env


def test_roundtrip_pins_all106_runtime_and_only_named_browser(package_environment):
    env = package_environment
    write(env['repo'], 'scripts/unreviewed.py', b'# excluded\n')
    routes.refresh_evidence(env)
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    non_expo = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX)}
    assert len(non_expo) == 106 and policy.digest(policy.encoded(non_expo)) == package.NON_EXPO_RUNTIME_SHA256
    assert meta['parentImage'] == package.PARENT_IMAGE and meta['oldManifestSha256'] == package.OLD_MANIFEST
    assert meta['fixedFiles'] == {**policy.FIXED, 'Dockerfile': package.DOCKER_AFTER}
    assert {n for n in meta['sourceFiles'] if n.startswith('scripts/')} == package.BROWSER_SCRIPTS
    assert package.FRONTEND_TESTS <= meta['sourceFiles'].keys()
    for old in (None, previous.BASELINE):
        with pytest.raises(ValueError): policy.verify_package(env['output_dir'], result['packageSha256'], baseline=old)
    with pytest.raises(ValueError, match='output must be new'): package.prepare(**env)


@pytest.mark.parametrize('fault', ['backend', 'reminder', 'legacy-static', 'add-static', 'remove-static',
    'requirements', 'missing-module', 'missing-test', 'missing-old-test', 'missing-browser',
    'unknown-test', 'docker', 'compose'])
def test_scope_rejected_before_output(package_environment, fault):
    env = package_environment; repo = env['repo']
    removed = {'remove-static': 'static/index.html', 'missing-module': 'task_reminders.py',
        'missing-test': 'frontend/tests/calendarConflicts.test.mjs',
        'missing-old-test': 'frontend/tests/taskReminders.test.mjs',
        'missing-browser': 'scripts/check_expo_calendar_conflicts_browser.py'}
    if fault in removed: (repo / removed[fault]).unlink()
    else:
        name = {'backend': 'app.py', 'reminder': 'task_reminders.py', 'legacy-static': 'static/index.html',
            'add-static': 'static/unreviewed.js', 'requirements': 'requirements.txt',
            'unknown-test': 'frontend/tests/unreviewed.test.mjs', 'docker': 'Dockerfile', 'compose': 'compose.yaml'}[fault]
        write(repo, name, (repo / name).read_bytes() + b'\n# drift\n' if (repo / name).exists() else b'drift')
    routes.refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_rehashed_metadata_and_old_profile_cannot_relax_runtime(package_environment):
    env = package_environment
    result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']): mapping['task_reminders.py'] = 'a' * 64
    meta['changedRuntimeFiles'] = ['task_reminders.py']
    with pytest.raises(ValueError, match='106-file baseline'):
        policy.validate_maps(meta, manifest, json.loads(env['build_evidence'].read_bytes()), baseline=package.BASELINE)
    names = set(checked['metadata']['sourceFiles'])
    with pytest.raises(ValueError, match='explicit packaging policy'):
        policy.selected_sources(names, checked['blobs']['deploy/prepare_release.py'], baseline=previous.BASELINE)
    old_names = names - (package.FRONTEND_TESTS - previous.FRONTEND_TESTS)
    selected = policy.selected_sources(old_names, checked['blobs']['deploy/prepare_release.py'], baseline=previous.BASELINE)
    assert not (package.BROWSER_SCRIPTS - previous.BROWSER_SCRIPTS) & selected
    assert policy.baseline_values(previous.BASELINE) == (previous.KIND, previous.PARENT_IMAGE, previous.OLD_MANIFEST)
    assert policy.baseline_values(None)[0] == 'membership-release-package'
    assert policy.fixed_files(previous.BASELINE)['Dockerfile'] == previous.DOCKER_AFTER


@pytest.mark.parametrize('frontend', [False, True])
def test_export_reuse_requires_identical_input_bytes(package_environment, frontend):
    env = package_environment
    name = 'frontend/src/index.ts' if frontend else 'docs/synthetic.md'
    write(env['repo'], name, b'// next reviewed revision\n')
    env['commit'] = commit(env['repo'])  # Intentionally retain original build evidence.
    if frontend:
        with pytest.raises(ValueError, match='build source bytes differ'): package.prepare(**env)
        assert not env['output_dir'].exists()
    else:
        assert package.prepare(**env)['packageSha256']


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    value = package_tests.assembly.__wrapped__(package_environment, tmp_path)
    path = value['reviews'].parent / 'parent-audit.json'
    path.write_bytes(policy.encoded({'synthetic': True, 'verified': True}))
    monkeypatch.setattr(package, 'AUDIT_SHA256', policy.digest(path.read_bytes()))
    reviews = json.loads(value['reviews'].read_bytes()); reviews['parent-audit.json'] = str(path)
    value['reviews'].write_bytes(policy.encoded(reviews))
    value['reviews_sha256'] = policy.digest(value['reviews'].read_bytes())
    return value


def test_plan_binds35_operators_and_parent_audit(assembly, monkeypatch):
    result = package.assemble(**assembly)
    operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert result['assembled'] and not result['productionOperations']
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 35
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    assert operator.plan['kind'] == 'expo-calendar-conflicts-release-plan'
    monkeypatch.setattr(package, 'AUDIT_SHA256', 'f' * 64)
    with pytest.raises(common.ReleaseError, match='parent_production_audit_required'): operator.validate_evidence()
    with pytest.raises(common.ReleaseError, match='new_and_separate'): package.assemble(**assembly)


@pytest.fixture
def simulation(steady_simulation, monkeypatch):
    value = lifecycle.simulation.__wrapped__(steady_simulation)
    operator, calls, _, _ = value
    operator.__class__ = controller.Controller
    # Keep recording service inspection but execute this adapter's actual hook.
    previous_services = operator.current_services
    monkeypatch.setattr(core.Controller, 'current_services', lambda self, image: previous_services(image))
    del operator.current_services
    original = operator.call
    def call(args, **kwargs):
        if args[:1] == ['curl'] and '--write-out' in args:
            calls.append(args); return b'401'
        return original(args, **kwargs)
    operator.call = call
    return value


def test_inherited71_lifecycle_and_new_guards_only_after_workers(simulation):
    operator, calls, programs, _ = simulation
    assert controller.Controller._activate is core.Controller._activate
    assert controller.Controller.stage is core.Controller.stage
    before = len(calls)
    parent = operator.current_services(package.PARENT_IMAGE)
    assert len(calls) == before and set(parent) == set(common.SERVICES)
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    workers = next(i for i in starts if 'sync' in calls[i])
    stopped = calls.index(['docker', 'compose', 'stop', '--timeout', '60', 'app'])
    guards = [i for i, c in enumerate(calls) if isinstance(c, list) and '--write-out' in c]
    assert calls.index('backup') < starts[0] < stopped < calls.index('check') < workers < min(guards)
    assert len(guards) == 2 and max(guards) < calls.index(['systemctl', 'start', 'family-dashboard-backup.timer'])
    assert len(programs) == 2 and all('expo_calendar_conflicts_release_data' in p for p in programs)
    assert not any('.migrate(' in p or 'warm_once' in p for p in programs)
    assert result['completed'] and (result['householdTables'], result['platformTables']) == (71, 9)
    assert result['stoppedBackup']['logicalSha256'] == result['preservation']['logicalSha256']
    assert 'migration' not in result and '/expo-calendar-conflicts-71-' in result['releaseDirectory'].replace('\\', '/')


def test_stage71_to71_without_production_write(simulation):
    operator = simulation[0]; (operator.candidate / 'stage.json').unlink()
    result = operator.stage()
    assert result['schemaBefore'] == result['schemaAfter'] == [71, 9] and result['productionWrites'] is False


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_failed_data_phase_preserves_attempt_without_replay(simulation, failed):
    lifecycle.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)


def test_non401_guard_stops_candidate_without_restore(simulation):
    operator, calls, _, _ = simulation; original = operator.call
    def denied(args, **kwargs):
        if args[:1] == ['curl'] and '--write-out' in args:
            calls.append(args); return b'200'
        return original(args, **kwargs)
    operator.call = denied
    with pytest.raises(common.ReleaseError, match='anonymous_reminder_access_allowed'): operator.activate()
    raw = (operator.candidate / 'activation.json').read_bytes(); result = json.loads(raw)
    assert not result['completed'] and result['candidateStoppedAfterFailure']
    assert ['systemctl', 'start', 'family-dashboard-backup.timer'] not in calls
    with pytest.raises(FileExistsError): operator.activate()
    assert (operator.candidate / 'activation.json').read_bytes() == raw


def test_hook_preserves_service_dict_identity(monkeypatch):
    operator = object.__new__(controller.Controller); operator.plan = {'imageId': 'sha256:' + '1' * 64}
    services = {'app': {'environmentSha256': 'a' * 64}, 'sync': {}, 'media': {}, 'web': {}}
    monkeypatch.setattr(core.Controller, 'current_services', lambda self, image: services)
    calls = []; operator.call = lambda args: calls.append(args) or b'401'
    assert operator.current_services(package.PARENT_IMAGE) is services and calls == []
    assert operator.current_services(operator.plan['imageId']) is services and len(calls) == 2


def edit(path, sql):
    with closing(sqlite3.connect(path)) as con:
        con.executescript(sql); con.commit()


@pytest.fixture(scope='module')
def current71(tmp_path_factory):
    base = tmp_path_factory.mktemp('c71'); source = base / 'source'; source.mkdir()
    hashes = {}
    for path in ROOT.glob('*.py'):
        raw = path.read_bytes(); (source / path.name).write_bytes(raw); hashes[path.name] = policy.digest(raw)
    assert startup(source, base / 'seed', 'seed')['households'] == 2
    clone_databases(base / 'seed', base / 'closed')
    for path in (base / 'closed').rglob('household.sqlite3'):
        edit(path, """
          PRAGMA foreign_keys=ON;
          INSERT INTO task_reminders VALUES('member1','synthetic','2026-09-20','read','later',3,0,'created','updated');
          INSERT INTO task_reminder_operations VALUES('member1','synthetic-request','digest','{"retained":true}','created');
          INSERT INTO settings(id,data) VALUES('task-reminders-worker','{"syntheticHeartbeat":true}');
        """)
    identity = {'head': 'a' * 40, 'tree': 'b' * 40, 'imageId': 'sha256:' + 'c' * 64,
                'sourceHashes': hashes, 'runtimeHashes': hashes}
    return base / 'closed', source, identity


@pytest.fixture
def group(current71, tmp_path):
    root = tmp_path / 'live'; clone_databases(current71[0], root)
    (root / membership.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    proof = tmp_path / 'proof'; proof.mkdir()
    return root, proof, {'source_identity': current71[2], 'plan_sha256': 'a' * 64,
                        'marker_sha256': data.marker_digest(root)}


def test_real_populated71_backup_app_restart_and_closed_check(group, current71):
    root, proof, kwargs = group
    original = data.snapshot_current(root)
    before = data.begin(root, proof, **kwargs)
    assert before['households'] == 2 and before['databases'] == 3
    assert startup(current71[1], root, 'restart')['households'] == 2
    after = data.check_stopped(root, proof, **kwargs)
    assert after['logicalSha256'] == before['logicalSha256']
    assert data.verify_restore(original, root, marker_sha256=kwargs['marker_sha256'])['verified']
    assert len(list((proof / 'backup-group').rglob('*.sqlite3'))) == 3
    for name, fingerprint in original['databases'].items():
        if name != 'platform.sqlite3':
            assert fingerprint['tables']['task_reminders']['count'] == fingerprint['tables']['task_reminder_operations']['count'] == 1
    with pytest.raises(FileExistsError): data.begin(root, proof, **kwargs)


@pytest.mark.parametrize('fault', ['reminder', 'receipt', 'settings', 'private', 'platform', 'backup', 'old69'])
def test_full_group_has_no_reminder_or_settings_exemption(group, fault):
    root, proof, kwargs = group
    if fault == 'old69':
        edit(root / 'household.sqlite3', 'DROP TABLE task_reminder_operations; DROP TABLE task_reminders;')
        with pytest.raises(membership.ReleaseDataError, match='expected_71_table_profile'): data.begin(root, proof, **kwargs)
        assert not (proof / 'attempt.json').exists()
        return
    data.begin(root, proof, **kwargs)
    child = next((root / 'spaces').rglob('household.sqlite3'))
    if fault == 'backup': next((proof / 'backup-group').rglob('*.sqlite3')).unlink()
    elif fault == 'platform': edit(root / 'platform.sqlite3', "UPDATE households SET name='changed' WHERE id='default';")
    else:
        edit(child, {'reminder': 'UPDATE task_reminders SET revision=revision+1;',
            'receipt': "UPDATE task_reminder_operations SET result='{}';",
            'settings': "UPDATE settings SET revision=revision+1 WHERE id='meta';",
            'private': "UPDATE private_finance SET data='{}';"}[fault])
    with pytest.raises((membership.ReleaseDataError, membership.migration.MigrationCheckError)):
        data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()
    with pytest.raises(FileExistsError): data.begin(root, proof, **kwargs)
