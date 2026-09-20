"""Bounded package, recorded lifecycle and populated 71/9 preservation checks."""
from copy import deepcopy
import json

import pytest
from deploy import build_calendar_privacy_release as package
from deploy import activate_calendar_privacy_release as controller
from deploy import calendar_privacy_release_data as data
from deploy import build_expo_calendar_conflicts_release as previous
from deploy import build_task_reminders_release as reminders
from deploy import build_task_dependencies_release as dependencies
from deploy import membership_release_package as policy
from deploy import membership_release_controller as common
from deploy import membership_release_data as membership
from deploy import assistant_trip_change_release_controller as core
import test_expo_calendar_conflicts_release as calendar
import test_journey_routes_release as routes
import test_assistant_trip_change_release as lifecycle
import test_steady_release_package as package_tests
from test_assistant_trip_change_release import steady_simulation, old_simulation
from test_membership_release_package import ROOT, write, commit
from test_membership_migration import startup, clone_databases
from test_expo_calendar_conflicts_release import current71, edit


def parent_docker():
    raw = (ROOT / 'Dockerfile').read_bytes()
    assert policy.digest(raw) == package.DOCKER_AFTER and raw.count(package.COPY_AFTER) == 1
    parent = raw.replace(package.COPY_AFTER, package.COPY_BEFORE, 1)
    assert policy.digest(parent) == package.DOCKER_BEFORE == previous.DOCKER_AFTER
    return parent


@pytest.fixture
def package_environment(tmp_path, monkeypatch):
    # Existing closed fixture reconstructs historical COPY lines, not Git history.
    monkeypatch.setattr(routes, 'new_docker', lambda: parent_docker()
        .replace(reminders.COPY_AFTER, reminders.COPY_BEFORE, 1)
        .replace(dependencies.COPY_AFTER, dependencies.COPY_BEFORE, 1))
    env = routes.environment.__wrapped__(tmp_path, monkeypatch); repo = env['repo']
    for name in controller.SPEC.operators:
        write(repo, 'deploy/' + name, (ROOT / 'deploy' / name).read_bytes())
    write(repo, 'Dockerfile', (ROOT / 'Dockerfile').read_bytes())
    runtime = {p.name for p in repo.glob('*.py')} | package.RUNTIME_ADDITIONS | {'requirements.txt'}
    runtime |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'static').rglob('*')
                if p.is_file() and not p.relative_to(ROOT).as_posix().startswith(policy.PREFIX)}
    for name in runtime:
        write(repo, name, (ROOT / name).read_bytes())
    kept = {n: policy.digest((repo / n).read_bytes()) for n in runtime if n not in package.CHANGED_RUNTIME_FILES}
    assert len(runtime) == package.NON_EXPO_RUNTIME_COUNT == 107
    assert len(kept) == package.PRESERVED_RUNTIME_COUNT == 103
    assert policy.digest(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    for name in package.FRONTEND_TESTS:
        write(repo, name, b'// synthetic frontend test\n')
    for name in package.BROWSER_SCRIPTS:
        write(repo, name, b'# synthetic reviewed browser input\n')
    routes.refresh_evidence(env)
    return env


def test_roundtrip_exact_four_runtime_changes_and_four_browser_paths(package_environment):
    env = package_environment
    for name in package.CHANGED_RUNTIME_FILES:
        write(env['repo'], name, (env['repo'] / name).read_bytes() + b'\n# reviewed synthetic delta\n')
    write(env['repo'], 'scripts/unreviewed.py', b'# excluded\n'); routes.refresh_evidence(env)
    result = package.prepare(**env); checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta = checked['metadata']
    kept = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX) and n not in package.CHANGED_RUNTIME_FILES}
    assert len(kept) == 103 and policy.digest(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    assert package.RUNTIME_ADDITIONS - previous.RUNTIME_ADDITIONS == {'calendar_privacy.py'}
    assert package.FRONTEND_TESTS - previous.FRONTEND_TESTS == {'frontend/tests/calendarPrivacy.test.mjs'}
    assert {n for n in meta['sourceFiles'] if n.startswith('scripts/')} == package.BROWSER_SCRIPTS
    assert len(package.BROWSER_SCRIPTS) == 4
    assert meta['parentImage'] == package.PARENT_IMAGE and meta['oldManifestSha256'] == package.OLD_MANIFEST
    for baseline in (None, previous.BASELINE):
        with pytest.raises(ValueError): policy.verify_package(env['output_dir'], result['packageSha256'], baseline=baseline)
    with pytest.raises(ValueError, match='output must be new'): package.prepare(**env)


@pytest.mark.parametrize('fault', ['other-backend', 'reminder', 'legacy-static', 'add-static', 'remove-static',
    'requirements', 'missing-module', 'missing-test', 'missing-browser', 'unknown-test', 'docker', 'compose'])
def test_scope_rejected_before_output(package_environment, fault):
    env = package_environment; repo = env['repo']
    removed = {'remove-static': 'static/index.html', 'missing-module': 'calendar_privacy.py',
        'missing-test': 'frontend/tests/calendarPrivacy.test.mjs', 'missing-browser': 'scripts/check_expo_calendar_privacy_browser.py'}
    if fault in removed: (repo / removed[fault]).unlink()
    else:
        name = {'other-backend': 'cloud_accounts.py', 'reminder': 'task_reminders.py', 'legacy-static': 'static/index.html',
            'add-static': 'static/unreviewed.js', 'requirements': 'requirements.txt',
            'unknown-test': 'frontend/tests/unreviewed.test.mjs', 'docker': 'Dockerfile', 'compose': 'compose.yaml'}[fault]
        write(repo, name, (repo / name).read_bytes() + b'\n# drift\n' if (repo / name).exists() else b'drift')
    routes.refresh_evidence(env)
    with pytest.raises(ValueError): package.prepare(**env)
    assert not env['output_dir'].exists()


def test_rehashed_metadata_cannot_exempt_fifth_runtime_or_change_old_policy(package_environment):
    env = package_environment; result = package.prepare(**env)
    checked = package.verify_package(env['output_dir'], result['packageSha256'])
    meta, manifest = deepcopy(checked['metadata']), deepcopy(checked['manifest'])
    for mapping in (meta['runtimeFiles'], meta['sourceFiles'], manifest['files']): mapping['task_reminders.py'] = 'a' * 64
    meta['changedRuntimeFiles'] = list(package.CHANGED_RUNTIME_FILES | {'task_reminders.py'})
    with pytest.raises(ValueError, match='103-file preservation'):
        policy.validate_maps(meta, manifest, json.loads(env['build_evidence'].read_bytes()), baseline=package.BASELINE)
    names = set(checked['metadata']['sourceFiles'])
    with pytest.raises(ValueError, match='explicit packaging policy'):
        policy.selected_sources(names, checked['blobs']['deploy/prepare_release.py'], baseline=previous.BASELINE)
    old_names = names - (package.FRONTEND_TESTS - previous.FRONTEND_TESTS)
    selected = policy.selected_sources(old_names, checked['blobs']['deploy/prepare_release.py'], baseline=previous.BASELINE)
    assert 'calendar_privacy.py' not in selected and not (package.BROWSER_SCRIPTS - previous.BROWSER_SCRIPTS) & selected
    assert policy.baseline_values(previous.BASELINE) == (previous.KIND, previous.PARENT_IMAGE, previous.OLD_MANIFEST)
    assert policy.fixed_files(previous.BASELINE)['Dockerfile'] == package.DOCKER_BEFORE


@pytest.mark.parametrize('frontend', [False, True])
def test_export_reuse_requires_unchanged_frontend(package_environment, frontend):
    env = package_environment; name = 'frontend/src/index.ts' if frontend else 'docs/synthetic.md'
    write(env['repo'], name, b'// next reviewed revision\n'); env['commit'] = commit(env['repo'])
    if frontend:
        with pytest.raises(ValueError, match='build source bytes differ'): package.prepare(**env)
        assert not env['output_dir'].exists()
    else: assert package.prepare(**env)['packageSha256']


@pytest.fixture
def assembly(package_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(package_tests, 'steady', package)
    value = package_tests.assembly.__wrapped__(package_environment, tmp_path)
    path = value['reviews'].parent / 'parent-audit.json'; path.write_bytes(policy.encoded({'synthetic': True, 'verified': True}))
    monkeypatch.setattr(package, 'AUDIT_SHA256', policy.digest(path.read_bytes()))
    reviews = json.loads(value['reviews'].read_bytes()); reviews['parent-audit.json'] = str(path)
    value['reviews'].write_bytes(policy.encoded(reviews)); value['reviews_sha256'] = policy.digest(value['reviews'].read_bytes())
    return value


def test_plan_binds38_operators_parent_and_no_migration(assembly, monkeypatch):
    result = package.assemble(**assembly); operator = controller.Controller(assembly['candidate'], result['planSha256'])
    assert result['assembled'] and not result['productionOperations']
    assert operator.validate_evidence() == {'tests': 1, 'passed': 1, 'skipped': 0}
    assert len(controller.SPEC.operators) == len(set(controller.SPEC.operators)) == 38
    assert operator.plan['kind'] == 'calendar-privacy-release-plan' and controller.SPEC.schema_pair == (71, 9)
    assert set(operator.plan['operatorHashes']) == {'deploy/' + n for n in controller.SPEC.operators}
    monkeypatch.setattr(package, 'AUDIT_SHA256', 'f' * 64)
    with pytest.raises(common.ReleaseError, match='parent_production_audit_required'): operator.validate_evidence()


@pytest.fixture
def simulation(steady_simulation, monkeypatch):
    value = lifecycle.simulation.__wrapped__(steady_simulation); operator, calls, _, _ = value
    operator.__class__ = controller.Controller
    previous_services = operator.current_services
    monkeypatch.setattr(core.Controller, 'current_services', lambda self, image: previous_services(image))
    del operator.current_services
    original = operator.call
    def call(args, **kwargs):
        if args[:1] == ['curl'] and '--write-out' in args: calls.append(args); return b'401'
        return original(args, **kwargs)
    operator.call = call
    return value


def test_recorded_source_update_preserves71_and_orders_app_only_check(simulation):
    operator, calls, programs, _ = simulation
    assert controller.Controller._activate is core.Controller._activate and controller.Controller.stage is core.Controller.stage
    result = operator.activate()
    starts = [i for i, c in enumerate(calls) if isinstance(c, list) and c[:3] == ['docker', 'compose', 'up']]
    stopped = calls.index(['docker', 'compose', 'stop', '--timeout', '60', 'app'])
    workers = next(i for i in starts if 'sync' in calls[i])
    assert calls.index('backup') < starts[0] < stopped < calls.index('check') < workers
    assert len(programs) == 2 and all('calendar_privacy_release_data' in p for p in programs)
    assert not any('.migrate(' in p or 'warm_once' in p for p in programs)
    assert result['completed'] and (result['householdTables'], result['platformTables']) == (71, 9)
    assert result['stoppedBackup']['logicalSha256'] == result['preservation']['logicalSha256'] and 'migration' not in result


@pytest.mark.parametrize('failed', ['backup', 'check'])
def test_failed_data_phase_stops_and_cannot_replay(simulation, failed):
    lifecycle.test_failed_data_phase_stops_and_cannot_replay_activation(simulation, failed)


@pytest.fixture
def group(current71, tmp_path):
    root = tmp_path / 'live'; clone_databases(current71[0], root)
    for db in root.rglob('household.sqlite3'):
        edit(db, """INSERT INTO entities(id,kind,data,updated_at) VALUES
          ('private-calendar','events','{"title":"synthetic private","createdBy":"member1","visibility":"private"}','synthetic'),
          ('legacy-calendar','events','{"title":"synthetic old shared"}','synthetic');""")
    (root / membership.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    proof = tmp_path / 'proof'; proof.mkdir()
    return root, proof, {'source_identity': current71[2], 'plan_sha256': 'a' * 64, 'marker_sha256': data.marker_digest(root)}


def test_real_two_households_populated71_restart_and_exact_restore_verification(group, current71):
    root, proof, kwargs = group; original = data.snapshot_current(root)
    seeded = data.snapshot_current(current71[0])
    before = data.begin(root, proof, **kwargs); assert (before['households'], before['databases']) == (2, 3)
    assert startup(current71[1], root, 'restart')['households'] == 2
    after = data.check_stopped(root, proof, **kwargs); assert after['logicalSha256'] == before['logicalSha256']
    assert data.verify_restore(original, root, marker_sha256=kwargs['marker_sha256'])['verified']
    for name, fingerprint in original['databases'].items():
        if name != 'platform.sqlite3':
            assert fingerprint['tables']['task_reminders']['count'] == fingerprint['tables']['task_reminder_operations']['count'] == 1
            assert fingerprint['tables']['entities']['count'] == seeded['databases'][name]['tables']['entities']['count'] + 2
    assert len(list((proof / 'backup-group').rglob('*.sqlite3'))) == 3
    with pytest.raises(FileExistsError): data.begin(root, proof, **kwargs)


@pytest.mark.parametrize('fault', ['reminder', 'receipt', 'settings', 'private-calendar', 'platform', 'old69'])
def test_no_private_event_reminder_settings_or_registry_exemption(group, fault):
    root, proof, kwargs = group
    if fault == 'old69':
        edit(root / 'household.sqlite3', 'DROP TABLE task_reminder_operations; DROP TABLE task_reminders;')
        with pytest.raises(membership.ReleaseDataError, match='expected_71_table_profile'): data.begin(root, proof, **kwargs)
        assert not (proof / 'attempt.json').exists(); return
    data.begin(root, proof, **kwargs)
    if fault == 'platform': edit(root / 'platform.sqlite3', "UPDATE households SET name='changed' WHERE id='default';")
    else:
        child = next((root / 'spaces').rglob('household.sqlite3'))
        edit(child, {'reminder': 'UPDATE task_reminders SET revision=revision+1;',
            'receipt': "UPDATE task_reminder_operations SET result='{}';",
            'settings': "UPDATE settings SET revision=revision+1 WHERE id='meta';",
            'private-calendar': "UPDATE entities SET data='{}' WHERE id='private-calendar';"}[fault])
    with pytest.raises((membership.ReleaseDataError, membership.migration.MigrationCheckError)):
        data.check_stopped(root, proof, **kwargs)
    assert not (proof / 'result.json').exists()
    with pytest.raises(FileExistsError): data.begin(root, proof, **kwargs)
