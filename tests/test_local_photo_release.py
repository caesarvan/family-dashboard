"""Fixed policy + recorded Docker lifecycle + real populated73 SQLite; no daemon."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from deploy import build_local_photo_release as package
from deploy import membership_release_package as policy
from deploy import prepare_local_photo_activation as prepare
from deploy import activate_local_photo_release as entry
from deploy import media_video_release_controller as control
from deploy import media_video_service_lifecycle as service
from deploy import media_video_release_data as data
from deploy import membership_release_data as core
from deploy.membership_release_controller import ReleaseError, encoded, sha
import test_media_video_release_controller as old
import test_media_video_migration as sqlite_fixture
from test_media_video_migration import baseline71, identity, offline
from test_membership_migration import startup, clone_databases
from test_task_reminders_migration import documented_restore

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_FILES = {'deploy/build_local_photo_release.py', 'deploy/prepare_local_photo_activation.py',
    'deploy/activate_local_photo_release.py', 'deploy/membership_release_package.py',
    'deploy/media_video_release_controller.py', 'deploy/media_video_service_lifecycle.py',
    'tests/test_local_photo_release.py', 'docs/LOCAL-PHOTO-RELEASE.md'}


def test_closed_modes_reject_arbitrary_profiles_and_decoder_changes(tmp_path):
    with pytest.raises(ReleaseError, match='unsupported_lifecycle_mode'):
        service.Lifecycle(None, 'sha256:'+'1'*64, package.DECODER_IMAGE, mode='arbitrary')
    with pytest.raises(ReleaseError, match='local_photo_images_changed'):
        service.Lifecycle(None, 'sha256:'+'1'*64, 'sha256:'+'2'*64, mode='local-photo-source-update')
    with pytest.raises(ValueError, match='unsupported release baseline'):
        policy.baseline_values('unregistered-profile')
    assert policy.baseline_values()[0] == 'membership-release-package'
    assert policy.baseline_values(package.BASELINE) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)


@pytest.fixture(scope='module')
def packaged(tmp_path_factory):
    root = tmp_path_factory.mktemp('local-photo-package'); repo = root/'repo'; repo.mkdir()
    names = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT).decode().splitlines()) | ADAPTER_FILES
    selected = policy.selected_sources(names, (ROOT/'deploy/prepare_release.py').read_bytes(), baseline=package.BASELINE)
    for name in selected: old.write(repo/name, (ROOT/name).read_bytes())
    def git(*args): return subprocess.check_output(['git', *args], cwd=repo).decode().strip()
    git('init', '-q'); git('config', 'user.name', 'Synthetic release test'); git('config', 'user.email', 'test@example.invalid')
    git('config', 'core.autocrlf', 'false'); git('add', '.'); git('commit', '-qm', 'Synthetic immutable source')
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    export = root/'web'; export.mkdir()
    # Synthetic 23-file export, explicitly not the actual Expo build.
    files = {'index.html': b'<!doctype html>', 'metadata.json': b'{}', '_expo/static/js/web/entry-test.js': b'// synthetic'}
    files.update({'assets/%02d.png' % n: b'synthetic' for n in range(20)})
    for name, raw in files.items(): old.write(export/name, raw)
    inputs = policy.required_build_inputs(selected)
    evidence = {'schemaVersion': 1, 'kind': 'membership-expo-build', 'head': head, 'tree': tree,
        'buildExit': 0, 'bundleMarkers': True, 'inputFiles': {n: sha((repo/n).read_bytes()) for n in inputs},
        'files': {n: sha(raw) for n, raw in files.items()}}
    ehash = old.write(root/'evidence.json', evidence)
    result = package.prepare(repo=repo, commit=head, export_dir=export, build_evidence=root/'evidence.json',
        evidence_sha256=ehash, output_dir=root/'package')
    checked = package.verify_package(root/'package', result['packageSha256'])
    return checked, evidence


def test_real_git_package_roundtrip_preserves105_runtime_files(packaged):
    value, evidence = packaged; meta = value['metadata']
    assert len(meta['runtimeFiles']) == 135 and len(meta['exportFiles']) == 23
    nonexpo = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX)}
    kept = {n: h for n, h in nonexpo.items() if n not in package.CHANGED_RUNTIME_FILES}
    assert len(nonexpo) == 112 and len(kept) == 105
    assert sha(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    assert set(n for n in meta['sourceFiles'] if n.startswith('scripts/')) == package.BROWSER_SCRIPTS
    assert meta['fixedFiles']['compose.yaml'] == package.COMPOSE_SHA256
    assert meta['fixedFiles']['deploy/nginx.conf'] == package.NGINX_AFTER


@pytest.mark.parametrize('name', ['media_video_storage.py', 'media_playback_progress.py', 'sync_worker.py', 'compose.yaml'])
def test_policy_rejects_unapproved_runtime_or_configuration(packaged, name):
    value, evidence = deepcopy(packaged); meta, manifest = value['metadata'], value['manifest']
    meta['sourceFiles'][name] = manifest['files'][name] = '0'*64
    if name in meta['runtimeFiles']: meta['runtimeFiles'][name] = '0'*64
    with pytest.raises(ValueError): policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


class Runner(old.Runner):
    def __init__(self, root):
        super().__init__(root)
        self.values = {n: old.model.container(n, 'candidate') for n in service.NEW_SERVICES}
        for name, value in self.values.items():
            value['Id'] = sha(('local-parent-'+name).encode())
            if name in ('app', 'sync', 'media'): value['Image'] = package.PARENT_IMAGE
        self.controller = None

    def __call__(self, argv, *, cwd, timeout):
        result = super().__call__(argv, cwd=cwd, timeout=timeout)
        if argv[3:5] == ['start', '--attach'] and argv[-1] in self.helpers:
            value = json.loads(result)
            value['markerSha256'] = '6'*64
            identity = json.loads((self.controller.release/'proof/identity.json').read_bytes())
            value['sourceIdentitySha256'] = core._digest(identity)
            result = json.dumps(value).encode()
        return result


@pytest.fixture
def rig(tmp_path, monkeypatch):
    images = {'app': 'sha256:'+'e'*64, 'decoder': package.DECODER_IMAGE}
    monkeypatch.setattr(old.model, 'APP', images['app']); monkeypatch.setattr(old.model, 'DECODER', images['decoder'])
    monkeypatch.setattr(old.prepare, 'IMAGES', images)  # Recording transport only; no production config patch.
    if os.name == 'nt':
        original = control.stat.S_IMODE
        monkeypatch.setattr(control.stat, 'S_IMODE', lambda m: 0o600 if original(m) == 0o666 else original(m))
    root = tmp_path/'installed'; root.mkdir(); releases = tmp_path/'releases'; releases.mkdir()
    old_nginx = subprocess.check_output(['git', 'show', package.INSTALLED_SOURCE+':deploy/nginx.conf'], cwd=ROOT)
    old_blobs = {'compose.yaml': (ROOT/'compose.yaml').read_bytes(), 'deploy/nginx.conf': old_nginx,
                 'app.py': b'old application\n', 'static/experience/old.js': b'old export\n'}
    old_manifest = {'sourceHead': prepare.PARENT_SOURCE, 'tree': '1'*40,
                    'files': {n: old.write(root/n, raw) for n, raw in old_blobs.items()}}
    parent_sha = old.write(root/'RELEASE-MANIFEST.json', old_manifest)
    monkeypatch.setattr(prepare, 'PARENT_MANIFEST', parent_sha)
    env_sha = old.write(root/'.env', b'SYNTHETIC_ENV=only-for-test\n'); (root/'.env').chmod(0o600)
    candidate = tmp_path/'candidate'; candidate.mkdir()
    blobs = {**old_blobs, 'deploy/nginx.conf': (ROOT/'deploy/nginx.conf').read_bytes(),
             'app.py': b'new application\n', 'static/experience/new.js': b'new export\n'}
    blobs.pop('static/experience/old.js')
    files = {n: old.write(candidate/'source'/n, raw) for n, raw in blobs.items()}
    manifest = {'sourceHead': 'a'*40, 'tree': 'b'*40, 'files': files}
    mhash = old.write(candidate/'source/RELEASE-MANIFEST.json', manifest)
    ops = {n: old.write(candidate/'operator'/n, (ROOT/n).read_bytes()) for n in prepare.OPERATORS}
    ohash = old.write(candidate/'operator.json', {'head': 'a'*40, 'tree': 'b'*40, 'files': ops})
    r = Runner(root)
    meta = {'sourceHead': 'a'*40, 'tree': 'b'*40, 'manifestSha256': mhash, 'runtimeFiles': policy.runtime_files(files)}
    built = {'imageId': images['app'], 'parentConfig': r.app_config}
    plan = {'kind': prepare.KIND, 'parentSource': prepare.PARENT_SOURCE, 'parentManifest': parent_sha,
            'sourceHead': 'a'*40, 'tree': 'b'*40, 'images': images, 'envSha256': env_sha,
            'inputs': {}, 'verifiedEvidence': {'test': 'external receipts replaced'}, 'operatorSha256': ohash,
            'schemaBefore': [73, 9], 'schemaAfter': [73, 9], 'productionWritesDuringPreparation': False}
    digest = old.write(candidate/'plan.json', plan); r.plan_sha = digest
    monkeypatch.setattr(prepare, 'verify_evidence', lambda inputs: (
        {'metadata': meta, 'manifest': manifest, 'blobs': blobs}, built, plan['verifiedEvidence']))
    c = entry.Controller(candidate, digest, runner=r, root=root, releases=releases); r.controller = c
    return c, r


def test_five_to_five_stage_and_update_uses_no_migration(rig):
    c, r = rig; staged = c.stage()
    assert staged['schemaBefore'] == staged['schemaAfter'] == [73, 9]
    assert len(staged['services']) == 5 and not staged['productionWrites']
    assert not any(any(v in argv for v in ('create', 'up', 'stop', 'tag', 'exec')) for argv, _ in r.calls)
    result = c.activate()
    assert result['completed'] and 'migration' not in result
    assert r.data == ['backup', 'check'] and 'migrate' not in c.data_actions
    assert r.started == ['app', 'app', 'decoder', 'sync', 'media', 'web']
    assert r.timer and len(result['services']) == 5 and r.values['decoder']['Image'] == package.DECODER_IMAGE
    stopped = [a[-1] for a, _ in r.calls if 'compose' in a and 'stop' in a]
    assert stopped[:5] == ['web', 'sync', 'media', 'decoder', 'app']
    with pytest.raises(ReleaseError, match='plan_consumed'): c.activate()


@pytest.mark.parametrize('fault', ['backup', 'check', 'logical-drift', 'health'])
def test_source_update_failure_retains_consumed_plan_and_stops_only_candidates(rig, fault):
    c, r = rig; c.stage(); r.fault = fault
    with pytest.raises(ReleaseError): c.activate()
    record = json.loads((c.candidate/'failure.json').read_bytes())
    assert record['automaticRestore'] is False and record['candidateStop']['complete'] and not r.timer
    assert not any(v['State']['Running'] for v in r.values.values())
    assert (c.release/'source-before/RELEASE-MANIFEST.json').exists()
    assert 'migrate' not in r.data and 'verify-rollback' not in r.data
    if fault != 'health': assert 'decoder' not in r.started
    with pytest.raises(ReleaseError, match='plan_consumed'): c.activate()


@pytest.mark.parametrize('fault', ['decoder', 'media-socket', 'fifth-service'])
def test_current_parent_must_really_have_fixed_five_service_contract(rig, fault):
    c, r = rig
    if fault == 'decoder': r.values['decoder']['Image'] = 'sha256:'+'f'*64
    elif fault == 'media-socket': r.values['media']['Mounts'] = r.values['media']['Mounts'][:1]
    else: r.values.pop('decoder')
    with pytest.raises(ReleaseError): c.stage()
    assert not (c.candidate/'activation-started.json').exists()


@pytest.fixture(scope='module')
def populated73(baseline71, tmp_path_factory):
    root = tmp_path_factory.mktemp('photo-parent73')/'data'; clone_databases(baseline71, root)
    for name in core.enumerate_databases(root):
        if name != 'platform.sqlite3': sqlite_fixture.data.initialize_database(root/name, sqlite_fixture.data.schema_definition())
    sqlite_fixture.populate(root)
    (root/core.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    return root


@pytest.fixture
def group73(populated73, tmp_path, identity, monkeypatch):
    root = tmp_path/'live'; clone_databases(populated73, root)
    (root/core.ROOT_ATTEMPT).write_bytes((populated73/core.ROOT_ATTEMPT).read_bytes())
    marker = data.marker_digest(root)
    monkeypatch.setattr(data, 'MEMBERSHIP_MARKER_SHA256', marker)
    proof = tmp_path/'proof'; proof.mkdir()
    return root, proof, {'source_identity': identity, 'plan_sha256': 'a'*64, 'marker_sha256': marker}


def test_populated73_real_app_only_preservation_and_full_restore(group73, tmp_path, monkeypatch):
    root, proof, kwargs = group73
    before = data.snapshot_current(root); receipt = data.begin(root, proof, **kwargs)
    # Real current create_app/all-household startup, no worker or controller migration.
    assert startup(ROOT, root, 'upgrade')['households'] == 2
    stopped = data.check_stopped(root, proof, **kwargs)
    assert stopped['logicalSha256'] == receipt['logicalSha256'] and stopped['databases'] == 3
    record = json.loads((proof/'backup.json').read_bytes()); restored = tmp_path/'restored'
    documented_restore(proof/'backup-group', record['manifest'], restored,
                       (root/core.ROOT_ATTEMPT).read_bytes(), monkeypatch)
    args = {k: v for k, v in kwargs.items() if k != 'marker_sha256'}
    # Production restores at the original /data root, whose identity remains
    # pinned. The documented program first creates these restored database files.
    with pytest.raises(core.ReleaseDataError, match='snapshot_root_binding'):
        entry.verify_restored_group(restored, proof, **args)
    sqlite_fixture.edit(root/'household.sqlite3', 'DELETE FROM media_video_cache')
    for relative in before['databases']:
        shutil.copyfile(restored/relative, root/relative)
    assert entry.verify_restored_group(root, proof, **args)['completeGroupRestored']
    assert data.snapshot_current(restored)['households'] == 2
    with pytest.raises(FileExistsError): data.begin(root, proof, **kwargs)
    assert all(len([n for n in v['tables'] if not n.startswith('sqlite_')]) == (9 if n == 'platform.sqlite3' else 73)
               for n, v in before['databases'].items())


@pytest.mark.parametrize('sql', ['DELETE FROM media_video_cache',
    'UPDATE media_playback_progress SET position_ms=position_ms+1',
    "UPDATE settings SET revision=revision+1 WHERE id='task-reminders-worker'",
    "DELETE FROM task_reminder_operations WHERE request_id='retained-read'"])
def test_no_populated73_preservation_exemptions(group73, sql):
    root, proof, kwargs = group73; data.begin(root, proof, **kwargs)
    sqlite_fixture.edit(sqlite_fixture.child(root), sql)
    with pytest.raises(sqlite_fixture.ERRORS): data.check_stopped(root, proof, **kwargs)
    args = {k: v for k, v in kwargs.items() if k != 'marker_sha256'}
    with pytest.raises(sqlite_fixture.ERRORS): entry.verify_restored_group(root, proof, **args)


@pytest.mark.parametrize('profile', ['image_overlap', 'nginx_raw'])
def test_failed_or_missing_actual_resource_evidence_is_not_admission(tmp_path, profile):
    with pytest.raises((ReleaseError, KeyError)): prepare.resources({}, profile, {})
    # An offline PASS review alone is never a resource run.
    with pytest.raises((ReleaseError, KeyError)): prepare.verify_evidence({'reviews': {'resources': {'verdict': 'PASS'}}})


@pytest.fixture
def resource_record(tmp_path):
    """Shape-faithful synthetic receipts; tests the verifier, not Linux execution."""
    prepared, run = tmp_path/'input', tmp_path/'run'; prepared.mkdir(); run.mkdir()
    expected = {n: sha(n.encode()) for n in ('app.py', 'media_images.py', 'media_local_upload.py')}
    source = {'deploy/local_photo_linux_probe.py': sha(b'probe'), 'deploy/media_video_ipc_resource_probe.py': sha(b'ipc')}
    files = {'runtime/'+n: old.write(prepared/'runtime'/n, n.encode()) for n in expected}
    files.update({'tools/probe.py': old.write(prepared/'tools/probe.py', b'probe'),
                  'tools/ipc.py': old.write(prepared/'tools/ipc.py', b'ipc'),
                  'nginx.original.conf': old.write(prepared/'nginx.original.conf', (ROOT/'deploy/nginx.conf').read_bytes())})
    contract = {'kind': 'local-photo-linux-input-v1', 'runtime': expected,
        'images': {'app': package.PARENT_IMAGE, 'web': prepare.WEB_IMAGE},
        'limitsMiB': prepare.LIMITS, 'hostBudget': prepare.HOST_BUDGET, 'files': files}
    ihash = old.write(prepared/'input.json', contract)
    images = [{'input': {'pixels': 20_000_000, 'contentType': mime}} for mime in ('image/jpeg','image/png','image/webp')]
    proof = {'passed': True, 'failure': None, 'checks': images,
        'overlap': {'bytes': 64*1024**2, 'busyAfterEachImage': True}}
    artifacts = {'client/result.json': old.write(run/'client/result.json', proof)}
    artifacts['client/finished.json'] = old.write(run/'client/finished.json', {'passed': True, 'resultSha256': artifacts['client/result.json']})
    loaded = {'modules': {n[:-3]: {'path': '/runtime/'+n, 'sha256': h} for n, h in expected.items()}}
    for name in ('app/ready.json', 'app/gunicorn-worker.json'):
        artifacts[name] = old.write(run/name, {'loaded': loaded})
    roles = {'app': 'a'*64, 'client': 'b'*64}; states = {}
    for role, cid in roles.items():
        limit = prepare.LIMITS[role]*1024**2
        artifacts[role+'-final.json'] = old.write(run/(role+'-final.json'), {'Id': cid, 'Image': package.PARENT_IMAGE,
            'State': {'Running': False, 'Pid': 0, 'OOMKilled': False, 'ExitCode': 0},
            'HostConfig': {'Memory': limit, 'MemorySwap': limit}})
        states[role] = {'memory.max': str(limit), 'memory.events': 'max 0\noom 0\noom_kill 0\n'}
    artifacts['cgroup-samples.json'] = old.write(run/'cgroup-samples.json', [{'roles': states}])
    memory = {'policy': prepare.HOST_BUDGET, 'failure': None, 'threadStarted': True, 'threadStopped': True,
              'sampleCount': 2, 'minimumAvailableKiB': 700000}
    artifacts['host-memory.json'] = old.write(run/'host-memory.json', memory)
    result = {'passed': True, 'profile': 'image_overlap', 'inputSha256': ihash, 'failure': None,
        'cleanupErrors': [], 'unknownCreate': None, 'hostMemory': memory, 'commands': [{'exitCode': 0}],
        'proof': proof, 'containers': roles, 'artifacts': artifacts, 'database': [{'synthetic': True}]}
    spec = {'input': {'root': str(prepared), 'sha256': ihash},
            'run': {'root': str(run), 'sha256': old.write(run/'result.json', result)}}
    return spec, {'runtimeFiles': expected, 'sourceFiles': source}, result


def test_resource_verifier_accepts_only_bound_full_shape(resource_record):
    spec, meta, _ = resource_record
    value = prepare.resources(spec, 'image_overlap', meta)
    assert value['input']['input.json'] == spec['input']['sha256']
    assert value['run']['result.json'] == spec['run']['sha256']


@pytest.mark.parametrize('fault', ['failed', 'oom', 'runtime', 'host-thread', 'cleanup', 'missing-webp'])
def test_resource_verifier_rejects_new_failures_and_old_runtime(resource_record, fault):
    spec, meta, result = resource_record; root = Path(spec['run']['root'])
    if fault == 'failed': result['passed'] = False
    elif fault == 'runtime': meta['runtimeFiles']['media_images.py'] = 'f'*64
    elif fault == 'cleanup': result['cleanupErrors'] = [{'role': 'app', 'error': 'still running'}]
    elif fault == 'host-thread':
        result['hostMemory']['threadStopped'] = False
        result['artifacts']['host-memory.json'] = old.write(root/'host-memory.json', result['hostMemory'])
    elif fault == 'missing-webp':
        result['proof']['checks'].pop()
        result['artifacts']['client/result.json'] = old.write(root/'client/result.json', result['proof'])
        result['artifacts']['client/finished.json'] = old.write(root/'client/finished.json',
            {'passed': True, 'resultSha256': result['artifacts']['client/result.json']})
    else:
        final = json.loads((root/'app-final.json').read_bytes()); final['State']['OOMKilled'] = True
        result['artifacts']['app-final.json'] = old.write(root/'app-final.json', final)
    spec['run']['sha256'] = old.write(root/'result.json', result)
    with pytest.raises(ReleaseError): prepare.resources(spec, 'image_overlap', meta)


@pytest.mark.parametrize('temporary_event', [False, True])
def test_nginx_proof_requires_two_households_and_no_temporary_activity(resource_record, temporary_event):
    spec, meta, result = resource_record; root = Path(spec['run']['root'])
    result['profile'] = 'nginx_raw'; result['containers']['web'] = 'c'*64
    result['proof']['checks'] = [{k: True for k in ('twoSignedHouseholds', 'sameRawRoute', 'crossHouseholdIDsDenied',
        'exact8MiBAccepted', 'oversize413', 'otherRaw415', 'csrfAndOrigin403')}]
    result['artifacts']['client/result.json'] = old.write(root/'client/result.json', result['proof'])
    result['artifacts']['client/finished.json'] = old.write(root/'client/finished.json',
        {'passed': True, 'resultSha256': result['artifacts']['client/result.json']})
    web = deepcopy(json.loads((root/'app-final.json').read_bytes()))
    web.update(Id='c'*64, Image=prepare.WEB_IMAGE)
    web['HostConfig'] = {'Memory': 96*1024**2, 'MemorySwap': 96*1024**2}
    result['artifacts']['web-final.json'] = old.write(root/'web-final.json', web)
    samples = json.loads((root/'cgroup-samples.json').read_bytes())
    samples[0]['roles']['web'] = {'memory.max': str(96*1024**2), 'memory.events': 'max 0\noom 0\noom_kill 0\n'}
    result['artifacts']['cgroup-samples.json'] = old.write(root/'cgroup-samples.json', samples)
    result['temporaryEvents'] = [{'created': 'synthetic-body'}] if temporary_event else []
    spec['run']['sha256'] = old.write(root/'result.json', result)
    if temporary_event:
        with pytest.raises(ReleaseError, match='nginx_raw_incomplete'): prepare.resources(spec, 'nginx_raw', meta)
    else: assert prepare.resources(spec, 'nginx_raw', meta)['run']['result.json'] == spec['run']['sha256']
