"""Real Git/package checks; explicit synthetic evidence/recorded Docker, no daemon."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
from deploy import build_discovery_release as package
from deploy import prepare_discovery_activation as prepare
from deploy import activate_discovery_release as entry
from deploy import prepare_local_photo_activation as shared
from deploy import membership_release_package as policy
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import ReleaseError, sha, encoded
import test_local_photo_release as previous

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {'deploy/build_discovery_release.py', 'deploy/prepare_discovery_activation.py',
    'deploy/activate_discovery_release.py', 'tests/test_discovery_release.py', 'docs/DISCOVERY-RELEASE.md'}
FEATURES = {'home_assistant.py': 'e2a349476095c3c2d91105cf2354af4cfda4e2fe',
            'household_media.py': 'e436b6804fabfbd999eb51980336c0a2fd520f35'}


def git_blob(head, name):
    return subprocess.check_output(['git', 'show', head+':'+name], cwd=ROOT)


def test_static_profiles_keep_old_defaults_and_reject_unregistered_mode():
    assert policy.baseline_values()[0] == 'membership-release-package'
    assert policy.baseline_values(package.BASELINE) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    assert shared._profile() is shared
    with pytest.raises(ReleaseError, match='unsupported_source_update_profile'):
        shared._profile('json-module-name')
    with pytest.raises(ValueError, match='unsupported release baseline'):
        policy.baseline_values('unregistered')
    with pytest.raises(ReleaseError, match='local_photo_images_changed'):
        services.Lifecycle(None, 'sha256:'+'1'*64, 'sha256:'+'2'*64, mode=prepare.MODE)
    obj = services.Lifecycle(None, 'sha256:'+'1'*64, package.DECODER_IMAGE, mode=prepare.MODE)
    assert obj.parent_image == package.PARENT_IMAGE and obj.parent_services == services.NEW_SERVICES


@pytest.mark.parametrize('name', FEATURES)
def test_actual_pinned_git_ast_retains_old_media_paths(name):
    old, new = git_blob(package.INSTALLED_SOURCE, name), git_blob(FEATURES[name], name)
    proof = prepare.unchanged_media_ast(name, old, new)
    assert proof['unchangedOutsidePinnedDiscoveryNodes']
    with pytest.raises(ReleaseError, match='resource_module_pin_changed'):
        prepare.unchanged_media_ast(name, old, new+b'\n# unreviewed change\n')


def test_ast_rejects_media_method_change_even_if_a_pin_is_accidentally_updated(monkeypatch):
    name = 'household_media.py'; old = git_blob(package.INSTALLED_SOURCE, name)
    changed = git_blob(FEATURES[name], name).replace(b'class MediaLibrary:', b'class MediaLibrary:\n    altered = True')
    monkeypatch.setitem(package.CHANGED_MODULES, name, sha(changed))
    with pytest.raises(ReleaseError, match='resource_media_behavior_changed'):
        prepare.unchanged_media_ast(name, old, changed)


@pytest.fixture(scope='module')
def packaged(tmp_path_factory):
    root = tmp_path_factory.mktemp('discovery-package'); repo = root/'repo'; repo.mkdir()
    names = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT).decode().splitlines())
    names |= ADAPTERS | package.FRONTEND_TESTS | package.BROWSER_SCRIPTS | {'deploy/discovery_duplicate_linux_probe.py'}
    selected = policy.selected_sources(names, (ROOT/'deploy/prepare_release.py').read_bytes(), baseline=package.BASELINE)
    for name in selected:
        if name in FEATURES: raw = git_blob(FEATURES[name], name)
        elif (ROOT/name).exists(): raw = (ROOT/name).read_bytes()
        else: raw = b'# synthetic tool/test only\n' if name.endswith('.py') else b'// synthetic test only\n'
        previous.old.write(repo/name, raw)
    def git(*args): return subprocess.check_output(['git', *args], cwd=repo).decode().strip()
    git('init', '-q'); git('config', 'user.name', 'Synthetic release'); git('config', 'user.email', 'test@example.invalid')
    git('config', 'core.autocrlf', 'false'); git('add', '.'); git('commit', '-qm', 'Synthetic immutable source')
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    export = root/'web'; export.mkdir()
    files = {'index.html': b'<!doctype html>', 'metadata.json': b'{}', '_expo/static/js/web/entry-test.js': b'// synthetic'}
    files.update({'assets/%02d.png' % n: b'synthetic' for n in range(20)})
    for name, raw in files.items(): previous.old.write(export/name, raw)
    evidence = {'schemaVersion': 1, 'kind': 'membership-expo-build', 'head': head, 'tree': tree,
        'buildExit': 0, 'bundleMarkers': True,
        'inputFiles': {n: sha((repo/n).read_bytes()) for n in policy.required_build_inputs(selected)},
        'files': {n: sha(raw) for n, raw in files.items()}}
    ehash = previous.old.write(root/'evidence.json', evidence)
    result = package.prepare(repo=repo, commit=head, export_dir=export, build_evidence=root/'evidence.json',
                             evidence_sha256=ehash, output_dir=root/'package')
    checked = package.verify_package(root/'package', result['packageSha256'])
    return checked, evidence, root, result


def test_real_git_package_preserves110_and_pins_changed2(packaged):
    value, _, _, _ = packaged; meta = value['metadata']
    nonexpo = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX)}
    kept = {n: h for n, h in nonexpo.items() if n not in package.CHANGED_MODULES}
    assert len(meta['runtimeFiles']) == 135 and len(nonexpo) == 112 and len(kept) == 110
    assert sha(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    assert sha(policy.encoded({**kept, **package.PARENT_MODULES})) == package.PARENT_RUNTIME_SHA256
    assert {n: nonexpo[n] for n in package.CHANGED_MODULES} == package.CHANGED_MODULES
    assert meta['fixedFiles']['compose.yaml'] == package.COMPOSE_SHA256
    assert meta['fixedFiles']['deploy/nginx.conf'] == package.NGINX_BEFORE == package.NGINX_AFTER


@pytest.mark.parametrize('name', ['media_images.py', 'media_playback.py', 'home_assistant.py',
                                  'household_media.py', 'compose.yaml', 'requirements.txt'])
def test_new_policy_rejects_unreviewed_runtime_and_config(packaged, name):
    value, evidence, _, _ = packaged; value = deepcopy(value)
    meta, manifest = value['metadata'], value['manifest']
    meta['sourceFiles'][name] = manifest['files'][name] = '0'*64
    if name in meta['runtimeFiles']: meta['runtimeFiles'][name] = '0'*64
    with pytest.raises(ValueError): policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


def test_missing_new_resource_receipt_is_not_grandfathered():
    inputs = dict.fromkeys(('package', 'build', 'validation', 'selection', 'parentAudit', 'image_overlap', 'nginx_raw', 'reviews'), {})
    with pytest.raises(ReleaseError, match='release_inputs_incomplete'): prepare.verify_evidence(inputs)


def test_only_new_profile_requires_both_reviewed_browser_entrypoints():
    names = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT).decode().splitlines())
    names |= ADAPTERS | package.FRONTEND_TESTS | package.BROWSER_SCRIPTS
    raw = (ROOT/'deploy/prepare_release.py').read_bytes()
    selected = policy.selected_sources(names, raw, baseline=package.BASELINE)
    entries = {'scripts/check_expo_assistant_places_browser.py', 'scripts/check_expo_photo_duplicates_browser.py'}
    assert entries <= set(selected) and not entries & package.parent.BROWSER_SCRIPTS
    for entrypoint in entries:
        with pytest.raises(ValueError): policy.selected_sources(names-{entrypoint}, raw, baseline=package.BASELINE)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    # Reuse the existing narrow recorded-Docker fixture with the new static
    # profile. Real Controller/Lifecycle code executes; Docker/evidence are synthetic.
    monkeypatch.setattr(previous, 'package', package)
    monkeypatch.setattr(previous, 'prepare', prepare)
    monkeypatch.setattr(previous, 'entry', entry)
    return previous.rig.__wrapped__(tmp_path, monkeypatch)


def test_actual_controller_new_mode_keeps_five_services_and_zero_migration(rig):
    c, r = rig; staged = c.stage()
    assert len(staged['services']) == 5 and staged['schemaBefore'] == staged['schemaAfter'] == [73, 9]
    result = c.activate()
    assert result['completed'] and r.data == ['backup', 'check'] and 'migrate' not in c.data_actions
    assert r.started == ['app', 'app', 'decoder', 'sync', 'media', 'web']
    assert r.timer and len(result['services']) == 5
    assert c.parent_image == package.PARENT_IMAGE and c.release.name.startswith('discovery-73-')
    assert 'activate_local_photo_release import verify_restored_group' in c.data_actions['verify-rollback']
    with pytest.raises(ReleaseError, match='plan_consumed'): c.activate()


@pytest.mark.parametrize('fault', ['check', 'logical-drift', 'health'])
def test_new_mode_retains_failure_and_stops_owned_candidates_without_restore(rig, fault):
    c, r = rig; c.stage(); r.fault = fault
    with pytest.raises(ReleaseError): c.activate()
    failure = json.loads((c.candidate/'failure.json').read_bytes())
    assert failure['automaticRestore'] is False
    assert (c.candidate/'activation-started.json').exists()
    assert not any('restore' in str(argv) for argv, _ in r.calls)


def resource_fixture(tmp_path, packaged):
    value, _, _, packaged_result = packaged; meta = value['metadata']
    runtime = {n: h for n, h in meta['runtimeFiles'].items() if not n.startswith(policy.PREFIX)}
    image = 'sha256:'+'3'*64; built = {'imageId': image}; buildsha = '4'*64
    prepared = tmp_path/'prepared'; prepared.mkdir(); run = tmp_path/'run'; run.mkdir()
    pfiles = {'tools/probe.py': previous.old.write(prepared/'tools/probe.py', value['blobs']['deploy/discovery_duplicate_linux_probe.py'])}
    contract = {'kind': 'discovery-duplicates-linux-input-v1', 'sourceHead': meta['sourceHead'], 'tree': meta['tree'],
        'packageSha256': packaged_result['packageSha256'], 'manifestSha256': meta['manifestSha256'],
        'imageId': image, 'buildSha256': buildsha, 'runtimeFiles': runtime, 'exportFiles': meta['exportFiles'],
        'limitsMiB': prepare.DUPLICATE_LIMITS, 'hostBudget': prepare.DUPLICATE_HOST_BUDGET, 'files': pfiles}
    proof = {'passed': True, 'failure': None, 'concurrency': 4, 'ownerReadyRecords': 1002, 'candidateRecords': 1001,
        'scanLimit': 1000, 'scanInvocationCount': 8, 'blobReadCount': 0, 'overlapObserved': True,
        'responses': [{'status': 200}]*3+[{'status': 503, 'code': 'unavailable'}],
        'recoveryStatus': 200, 'coverageCapped': True}
    memory = {'policy': prepare.DUPLICATE_HOST_BUDGET, 'failure': None, 'threadStarted': True,
        'threadStopped': True, 'sampleCount': 2, 'minimumAvailableKiB': 700000}
    db = {'before': 'a'*64, 'after': 'a'*64}
    loaded = {'loaded': {'modules': {n: {'path': '/app/'+n+'.py', 'sha256': runtime[n+'.py']}
                                    for n in ('app', 'household_media', 'media_crypto')}}}
    samples = [{'roles': {r: {'memory.max': str(v*1024**2), 'memory.peak': '10000',
        'memory.events': 'max 0\noom 0\noom_kill 0\n'} for r, v in prepare.DUPLICATE_LIMITS.items()}}]
    artifacts = {'app/ready.json': loaded, 'app/gunicorn-worker.json': loaded, 'client/result.json': proof,
        'host-memory.json': memory, 'database.json': db, 'cgroup-samples.json': samples}
    containers = {'app': 'a'*64, 'client': 'b'*64}
    for role, limit in prepare.DUPLICATE_LIMITS.items():
        artifacts[role+'-final.json'] = {'Id': containers[role], 'Image': image,
            'State': {'Running': False, 'Pid': 0, 'OOMKilled': False, 'ExitCode': 0},
            'HostConfig': {'Memory': limit*1024**2, 'MemorySwap': limit*1024**2}}
    def write():
        files = {n: previous.old.write(run/n, val) for n, val in artifacts.items()}
        files['client/finished.json'] = previous.old.write(run/'client/finished.json', {
            'passed': True, 'resultSha256': files['client/result.json']})
        ih = previous.old.write(prepared/'input.json', contract)
        result = {'kind': 'discovery-duplicates-linux-result-v1', 'inputSha256': ih,
            'passed': True, 'failure': None, 'cleanupErrors': [], 'unknownCreate': None,
            'commands': [{'exitCode': 0}], 'artifacts': files, 'proof': proof,
            'hostMemory': memory, 'database': db, 'containers': containers}
        rh = previous.old.write(run/'result.json', result)
        return {'input': {'root': str(prepared), 'sha256': ih}, 'run': {'root': str(run), 'sha256': rh}}
    return value, built, packaged_result['packageSha256'], buildsha, write, artifacts, contract


@pytest.mark.parametrize('fault', [None, 'peak', 'oom', 'blob', 'concurrency', 'uncapped', 'runtime', 'image', 'db', 'missing-original'])
def test_resource_admission_reads_originals_and_rejects_false_success(tmp_path, packaged, fault):
    value, built, ph, bh, write, originals, contract = resource_fixture(tmp_path, packaged)
    if fault == 'peak': originals['cgroup-samples.json'][0]['roles']['app']['memory.peak'] = str(385*1024**2)
    if fault == 'oom': originals['cgroup-samples.json'][0]['roles']['app']['memory.events'] = 'max 1\noom 0\noom_kill 0\n'
    if fault == 'blob': originals['client/result.json']['blobReadCount'] = 1
    if fault == 'concurrency': originals['client/result.json']['overlapObserved'] = False
    if fault == 'uncapped': originals['client/result.json']['ownerReadyRecords'] = 1001
    if fault == 'runtime': contract['runtimeFiles']['media_crypto.py'] = '0'*64
    if fault == 'image': contract['imageId'] = package.PARENT_IMAGE
    if fault == 'db': originals['database.json']['after'] = 'b'*64
    if fault == 'missing-original': originals.pop('app/ready.json')
    spec = write()
    if fault:
        with pytest.raises(ReleaseError): prepare.duplicate_resources(spec, value, built, ph, bh)
    else:
        actual = prepare.duplicate_resources(spec, value, built, ph, bh)
        assert actual['scope'] == 'four-concurrent-bounded-metadata-requests-only'
        (Path(spec['run']['root'])/'client/result.json').write_text('{}')
        with pytest.raises(ReleaseError): prepare.duplicate_resources(spec, value, built, ph, bh)
