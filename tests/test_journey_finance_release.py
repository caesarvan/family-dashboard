"""Static policy, actual Git archives and recorded lifecycle; no Docker or production."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from deploy import build_journey_finance_release as package
from deploy import prepare_journey_finance_activation as prepare
from deploy import activate_journey_finance_release as entry
from deploy import membership_release_package as policy
from deploy import prepare_local_photo_activation as shared
from deploy import media_video_release_controller as control
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import ReleaseError, read, sha
import test_local_photo_release as previous

ROOT = Path(__file__).resolve().parents[1]
NEW = {'deploy/build_journey_finance_release.py', 'deploy/prepare_journey_finance_activation.py',
       'deploy/activate_journey_finance_release.py', 'tests/test_journey_finance_release.py',
       'docs/JOURNEY-FINANCE-RELEASE.md'}


def blob(head, name):
    return subprocess.check_output(['git', 'show', head+':'+name], cwd=ROOT)


def test_actual_parent113_runtime110_preserved_and_exact_registration_ast():
    names = package.parent.RUNTIME_ADDITIONS | {'requirements.txt'}
    names |= {n for n in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only',
              package.INSTALLED_SOURCE, 'static'], cwd=ROOT).decode().splitlines()
              if not n.startswith(policy.PREFIX)}
    original = {n: sha(blob(package.INSTALLED_SOURCE, n)) for n in names}
    current = {n: sha((ROOT/n).read_bytes()) for n in names | {'journey_finance.py'}}
    prepare.runtime_boundary(original, current)
    assert len(current) == 113
    for name in package.PARENT_MODULES:
        assert prepare.unchanged_media_ast(name, blob(package.INSTALLED_SOURCE, name),
                                           (ROOT/name).read_bytes())['unchangedOutsideExactAdditions']


@pytest.mark.parametrize('name', ['app.py', 'data_portability.py'])
def test_even_repinning_does_not_hide_unrelated_media_or_export_changes(monkeypatch, name):
    raw = (ROOT/name).read_bytes()+b'\nextra_global = True\n'
    monkeypatch.setitem(package.CHANGED_MODULES, name, sha(raw))
    with pytest.raises(ReleaseError, match='retained_media_behavior_changed'):
        prepare.unchanged_media_ast(name, blob(package.INSTALLED_SOURCE, name), raw)


def test_new_closed_profile_does_not_change_old_modes():
    assert policy.baseline_values()[0] == 'membership-release-package'
    assert policy.baseline_values(package.BASELINE) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    assert shared._profile('finance-flow-source-update') is prepare.parent
    assert shared._profile(prepare.MODE) is prepare
    assert package.SCHEMA_BEFORE == (73, 9) and package.SCHEMA_AFTER == (75, 9)
    with pytest.raises(ReleaseError): shared._profile('journey-finance-73-to-76')
    with pytest.raises(ValueError): policy.baseline_values('arbitrary-module')
    with pytest.raises(ReleaseError): services.Lifecycle(None, package.PARENT_IMAGE, package.DECODER_IMAGE, mode=prepare.MODE)
    with pytest.raises(ReleaseError): services.Lifecycle(None, 'sha256:'+'1'*64, 'sha256:'+'2'*64, mode=prepare.MODE)


@pytest.fixture(scope='module')
def packaged(tmp_path_factory):
    root = tmp_path_factory.mktemp('jf-package'); repo = root/'repo'; repo.mkdir()
    names = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT).decode().splitlines()) | NEW | package.ADDITIONAL_INPUTS
    selected = policy.selected_sources(names, (ROOT/'deploy/prepare_release.py').read_bytes(), baseline=package.BASELINE)
    for name in selected:
        # This author tree deliberately lacks the UI merge. Use its frozen, reviewed
        # test only in this synthetic Git fixture; this is not an Expo build claim.
        raw = ((ROOT/name).read_bytes() if (ROOT/name).exists() else
               blob('9ef78e358883b0cf4bfe660496d623f61b757f26', name))
        previous.old.write(repo/name, raw)
    def git(*args): return subprocess.check_output(['git', *args], cwd=repo).decode().strip()
    git('init', '-q'); git('config', 'user.name', 'Synthetic release'); git('config', 'user.email', 'test@example.invalid')
    git('config', 'core.autocrlf', 'false'); git('add', '.'); git('commit', '-qm', 'Synthetic fixed journey source')
    head, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    export = root/'web'; export.mkdir()
    files = {'index.html': b'<!doctype html>', 'metadata.json': b'{}', '_expo/static/js/web/entry-test.js': b'// synthetic'}
    files.update({'assets/%02d.png' % n: b'synthetic' for n in range(20)})
    for name, raw in files.items(): previous.old.write(export/name, raw)
    evidence = {'schemaVersion': 1, 'kind': 'membership-expo-build', 'head': head, 'tree': tree,
        'buildExit': 0, 'bundleMarkers': True,
        'inputFiles': {n: sha((repo/n).read_bytes()) for n in policy.required_build_inputs(selected)},
        'supplementalTestInputs': {n: sha((repo/n).read_bytes()) for n in package.SUPPLEMENTAL_INPUTS},
        'additionalTestInputs': {n: sha((repo/n).read_bytes()) for n in package.ADDITIONAL_INPUTS},
        'files': {n: sha(raw) for n, raw in files.items()}}
    ehash = previous.old.write(root/'evidence.json', evidence)
    result = package.prepare(repo=repo, commit=head, export_dir=export, build_evidence=root/'evidence.json',
                             evidence_sha256=ehash, output_dir=root/'package')
    return package.verify_package(root/'package', result['packageSha256']), evidence, root, git, ehash


def test_real_git_package_and_input_reuse_boundary(packaged):
    value, evidence, root, git, ehash = packaged
    assert len(value['metadata']['runtimeFiles']) == 136
    assert value['metadata']['parentImage'] == package.PARENT_IMAGE
    assert value['metadata']['fixedFiles']['Dockerfile'] == package.DOCKER_AFTER
    previous.old.write(root/'repo/docs/JOURNEY-FINANCE-RELEASE.md', b'Synthetic documentation revision\n')
    git('add', 'docs/JOURNEY-FINANCE-RELEASE.md'); git('commit', '-qm', 'Synthetic docs only')
    result = package.prepare(repo=root/'repo', commit=git('rev-parse', 'HEAD'), export_dir=root/'web',
        build_evidence=root/'evidence.json', evidence_sha256=ehash, output_dir=root/'reused')
    assert package.verify_package(root/'reused', result['packageSha256'])['metadata']['buildSourceHead'] == evidence['head']
    path = root/'repo/tests/test_expo_journey_finance.mjs'; path.write_bytes(path.read_bytes()+b'\n// changed input\n')
    git('add', 'tests/test_expo_journey_finance.mjs'); git('commit', '-qm', 'Synthetic input changed')
    with pytest.raises(ValueError):
        package.prepare(repo=root/'repo', commit=git('rev-parse', 'HEAD'), export_dir=root/'web',
            build_evidence=root/'evidence.json', evidence_sha256=ehash, output_dir=root/'rejected')
    assert not (root/'rejected').exists()


@pytest.mark.parametrize('name', ['journey_finance.py', 'app.py', 'data_portability.py', 'media_images.py',
                                  'requirements.txt', 'Dockerfile', 'compose.yaml', 'deploy/nginx.conf'])
def test_runtime_and_fixed_configuration_cannot_drift(packaged, name):
    value, evidence, *_ = packaged; value = deepcopy(value)
    meta, manifest = value['metadata'], value['manifest']
    meta['sourceFiles'][name] = manifest['files'][name] = '0'*64
    if name in meta['runtimeFiles']: meta['runtimeFiles'][name] = '0'*64
    with pytest.raises(ValueError): policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


class JourneyRunner(previous.Runner):
    def __call__(self, argv, *, cwd, timeout):
        raw = super().__call__(argv, cwd=cwd, timeout=timeout)
        if argv[3:5] == ['start', '--attach'] and argv[-1] in self.helpers:
            value = json.loads(raw)
            if self.helpers[argv[-1]]['action'] == 'migrate':
                value.update(beforeSha256='7'*64, schemaSha256='8'*64)
                if self.fault == 'migration-identity': value['planSha256'] = 'f'*64
                if self.fault == 'backup-as-migration': value.pop('schemaSha256')
            raw = json.dumps(value).encode()
        return raw


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(previous, 'package', package)
    monkeypatch.setattr(previous, 'prepare', prepare)
    monkeypatch.setattr(previous, 'Runner', JourneyRunner)
    def factory(candidate, digest, **kwargs):
        plan = read(candidate/'plan.json', digest); plan['schemaAfter'] = [75, 9]
        digest = previous.old.write(candidate/'plan.json', plan)
        kwargs['runner'].plan_sha = digest
        return entry.Controller(candidate, digest, **kwargs)
    monkeypatch.setattr(previous, 'entry', SimpleNamespace(Controller=factory))
    return previous.rig.__wrapped__(tmp_path, monkeypatch)


def test_five_service_parent_real_migration_action_then_stopped_gate_once(rig):
    c, r = rig; staged = c.stage()
    assert staged['schemaBefore'] == [73, 9] and staged['schemaAfter'] == [75, 9]
    assert len(staged['services']) == 5 and not staged['productionWrites']
    result = c.activate()
    assert result['completed'] and result['schema'] == [75, 9]
    assert r.data == ['backup', 'migrate', 'check'] and result['migration']['schemaSha256'] == '8'*64
    assert r.started == ['app', 'app', 'decoder', 'sync', 'media', 'web']
    assert 'check_journey_finance_migration' in c.data_prefix and 'verify_restored_group' not in c.data_actions['verify-rollback']
    assert r.timer and c.release.name.startswith('journey-finance-75-')
    with pytest.raises(ReleaseError, match='plan_consumed'): c.activate()


@pytest.mark.parametrize('fault', ['migrate', 'check', 'logical-drift', 'migration-identity', 'backup-as-migration', 'health'])
def test_failure_preserves_consumed_plan_and_never_restores_or_restarts_old_services(rig, fault):
    c, r = rig; c.stage(); r.fault = fault
    with pytest.raises(ReleaseError): c.activate()
    failure = read(c.candidate/'failure.json')
    assert failure['automaticRestore'] is False and failure['candidateStop']['complete'] and not r.timer
    assert (c.candidate/'activation-started.json').exists()
    assert not any(v['State']['Running'] for v in r.values.values())
    assert not any('restore' in str(argv) for argv, _ in r.calls)
    if fault != 'health': assert 'decoder' not in r.started


@pytest.mark.parametrize('mode', ['local-photo-source-update', 'discovery-source-update', 'finance-flow-source-update'])
def test_old_source_update_modes_remain_without_ddl(mode, tmp_path, monkeypatch):
    # The existing actual controller is exercised with the existing recording fixture.
    import importlib
    suffix = {'local-photo-source-update': 'local_photo', 'discovery-source-update': 'discovery',
              'finance-flow-source-update': 'finance_flow'}[mode]
    monkeypatch.setattr(previous, 'package', importlib.import_module('deploy.build_'+suffix+'_release'))
    monkeypatch.setattr(previous, 'prepare', importlib.import_module('deploy.prepare_'+suffix+'_activation'))
    monkeypatch.setattr(previous, 'entry', importlib.import_module('deploy.activate_'+suffix+'_release'))
    c, r = previous.rig.__wrapped__(tmp_path, monkeypatch)
    c.stage(); result = c.activate()
    assert result['schema'] == [73, 9] and 'migration' not in result and r.data == ['backup', 'check']


@pytest.mark.parametrize('fault', ['package', 'build', 'plan'])
def test_retained_parent_identity_is_pinned_before_reading_any_resource(tmp_path, fault):
    spec = {'package': {'root': str(tmp_path), 'sha256': package.OLD_PACKAGE},
            'build': {'root': str(tmp_path), 'sha256': prepare.PARENT_BUILD_SHA256},
            'plan': {'path': str(tmp_path/'plan.json'), 'sha256': prepare.PARENT_PLAN_SHA256}}
    spec[fault]['sha256'] = '0'*64
    with pytest.raises(ReleaseError, match='retained_finance_identity_changed'):
        prepare.retained_parent({'retainedFinance': spec}, {})


def test_missing_new_rehearsal_or_review_never_admits():
    with pytest.raises(ReleaseError, match='release_inputs_incomplete'): prepare.verify_evidence({})
    with pytest.raises(ReleaseError, match='migration_descriptor'): prepare.verify_migration({}, {}, {})
    assert 'migration' in prepare.REVIEW_ROLES

