"""75/9 source-update routing and stopped preservation; no Docker or production."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from deploy import build_media_date_release as package
from deploy import prepare_media_date_activation as prepare
from deploy import activate_media_date_release as entry
from deploy import journey_finance_release_data as data
from deploy import membership_release_data as core
from deploy import membership_release_package as policy
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import ReleaseError, read, sha
import test_local_photo_release as previous
import test_journey_finance_migration as jf
from test_journey_finance_migration import baseline73, source, group, offline

ROOT = Path(__file__).resolve().parents[1]


def test_closed_profile_keeps_five_services_and_has_no_migration():
    assert policy.baseline_values(package.BASELINE) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    assert prepare.shared._profile(prepare.MODE) is prepare
    assert package.SCHEMA_BEFORE == package.SCHEMA_AFTER == (75, 9)
    assert policy.fixed_files(package.BASELINE)['Dockerfile'] == package.DOCKER_AFTER
    with pytest.raises(ReleaseError):
        prepare.shared._profile('media-date-source-update-other')
    with pytest.raises(ReleaseError):
        services.Lifecycle(None, package.PARENT_IMAGE, package.DECODER_IMAGE, mode=prepare.MODE)
    with pytest.raises(ReleaseError):
        services.Lifecycle(None, 'sha256:'+'1'*64, 'sha256:'+'2'*64, mode=prepare.MODE)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(previous, 'package', package)
    monkeypatch.setattr(previous, 'prepare', prepare)
    def factory(candidate, digest, **kwargs):
        plan = read(candidate/'plan.json', digest)
        plan['schemaBefore'] = plan['schemaAfter'] = [75, 9]
        digest = previous.old.write(candidate/'plan.json', plan)
        kwargs['runner'].plan_sha = digest
        return entry.Controller(candidate, digest, **kwargs)
    monkeypatch.setattr(previous, 'entry', SimpleNamespace(Controller=factory))
    return previous.rig.__wrapped__(tmp_path, monkeypatch)


def test_recorded_five_service_source_update_stops_before_75_check_and_never_migrates(rig):
    c, r = rig
    staged = c.stage()
    assert staged['schemaBefore'] == staged['schemaAfter'] == [75, 9] and not staged['productionWrites']
    assert len(staged['services']) == 5
    result = c.activate()
    assert result['completed'] and result['schema'] == [75, 9] and 'migration' not in result
    assert r.data == ['backup', 'check'] and 'migrate' not in c.data_actions
    assert 'journey_finance_release_data' in c.data_prefix
    assert 'activate_media_date_release' in c.data_actions['verify-rollback']
    assert r.started == ['app', 'app', 'decoder', 'sync', 'media', 'web']
    assert r.timer and c.release.name.startswith('media-date-75-')
    with pytest.raises(ReleaseError, match='plan_consumed'): c.activate()


@pytest.mark.parametrize('fault', ['backup', 'check', 'logical-drift', 'health'])
def test_failure_retains_backup_consumes_plan_and_never_automatically_restores(rig, fault):
    c, r = rig; c.stage(); r.fault = fault
    with pytest.raises(ReleaseError): c.activate()
    failure = read(c.candidate/'failure.json')
    assert failure['automaticRestore'] is False and failure['candidateStop']['complete'] and not r.timer
    assert (c.candidate/'activation-started.json').exists()
    assert (c.release/'source-before/RELEASE-MANIFEST.json').exists()
    assert not any(v['State']['Running'] for v in r.values.values())
    assert 'migrate' not in r.data and 'verify-rollback' not in r.data
    if fault != 'health': assert 'decoder' not in r.started


def test_plan_rejects_prior_73_profile(rig):
    c, _ = rig
    for field in ('schemaBefore', 'schemaAfter'):
        value = deepcopy(c.plan); value[field] = [73, 9]
        with pytest.raises(ReleaseError): prepare.check_plan(value)


def test_actual_populated75_startup_preservation_restore_and_no_replay(group, source, tmp_path, monkeypatch):
    # The old migration is used only to create the synthetic fixture, never by
    # this source-update controller. Includes both new allocation tables populated.
    root, oldproof, kwargs = group
    jf.migrate(group); jf.data.check_stopped(root, oldproof, **kwargs); jf.populate(root)
    monkeypatch.setattr(data, 'MEMBERSHIP_MARKER_SHA256', kwargs['marker_sha256'])
    proof = tmp_path/'date-proof'; proof.mkdir()
    before = data.snapshot_current(root)
    receipt = data.begin(root, proof, **kwargs)
    assert jf.startup(source[0], root, 'restart')['households'] == 2
    stopped = data.check_stopped(root, proof, **kwargs)
    assert stopped['logicalSha256'] == receipt['logicalSha256'] == core._digest(core._logical(before))
    assert stopped['databases'] == 3
    record = json.loads((proof/'backup.json').read_bytes())
    # The controller binds restoration to the original data root. Preserve the
    # synthetic original directory and restore the complete group at that root.
    marker = (root/core.ROOT_ATTEMPT).read_bytes()
    retained = tmp_path/'retained75'
    assert root.resolve().is_relative_to(tmp_path.resolve()) and not retained.exists()
    root.rename(retained)
    restored = root
    jf.documented_restore(proof/'backup-group', record['manifest'], restored, marker, monkeypatch)
    restore_args = {k: v for k, v in kwargs.items() if k != 'marker_sha256'}
    result = entry.verify_restored_group(restored, proof, **restore_args)
    assert result['completeGroupRestored'] and result['databases'] == 3
    with pytest.raises(FileExistsError): data.begin(root, proof, **kwargs)
    jf.edit(jf.child(restored), 'DELETE FROM hub_journey_allocation_operations')
    with pytest.raises(jf.ERRORS): entry.verify_restored_group(restored, proof, **restore_args)
    with pytest.raises(jf.ERRORS):
        entry.verify_restored_group(root, proof, **{**restore_args, 'plan_sha256': 'f'*64})


def test_fixed_parent_runtime_and_media_processing_are_compared():
    names = package.RUNTIME_ADDITIONS | {'requirements.txt'}
    names |= {n for n in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only',
              package.INSTALLED_SOURCE, 'static'], cwd=ROOT).decode().splitlines()
              if not n.startswith(policy.PREFIX)}
    def blob(head, name): return subprocess.check_output(['git', 'show', head+':'+name], cwd=ROOT)
    old = {n: sha(blob(package.INSTALLED_SOURCE, n)) for n in names}
    # Runtime authorship is checked against its frozen commit; no file copying.
    author = '8a0d949caa7fa4df368339454a11ff87745a3ba4'
    current = {n: sha(blob(author, n)) for n in names}
    prepare.runtime_boundary(old, current)
    prepare.unchanged_media_processing(blob(package.INSTALLED_SOURCE, 'household_media.py'),
                                       blob(author, 'household_media.py'))
    current['media_images.py'] = '0'*64
    with pytest.raises(ReleaseError): prepare.runtime_boundary(old, current)


@pytest.fixture(scope='module')
def date_input_maps():
    # Real current source hashes; synthetic exports only exercise map validation.
    # No package/build is produced or represented as a real Expo execution.
    tracked = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT).decode().splitlines())
    selected = policy.selected_sources(tracked, (ROOT/'deploy/prepare_release.py').read_bytes(),
                                       baseline=package.BASELINE)
    sources = {name: sha((ROOT/name).read_bytes()) for name in selected}
    exports = {name: sha(b'synthetic') for name in
               ['index.html', 'metadata.json', '_expo/static/js/web/entry-test.js'] +
               ['assets/%02d.png' % index for index in range(20)]}
    inputs = {name: sources[name] for name in policy.required_build_inputs(sources)}
    evidence = dict(schemaVersion=1, kind='membership-expo-build', buildExit=0,
        bundleMarkers=True, head='a'*40, tree='b'*40, inputFiles=inputs, files=exports,
        supplementalTestInputs={name: sources[name] for name in package.SUPPLEMENTAL_INPUTS},
        additionalTestInputs={})
    files = {**sources, **{policy.PREFIX+name: digest for name, digest in exports.items()}}
    metadata = dict(kind=package.KIND, parentImage=package.PARENT_IMAGE,
        oldManifestSha256=package.OLD_MANIFEST, sourceFiles=sources, exportFiles=exports,
        runtimeFiles=policy.runtime_files(files, baseline=package.BASELINE),
        fixedFiles=policy.fixed_files(package.BASELINE), inputFiles=inputs,
        buildSourceHead=evidence['head'], buildSourceTree=evidence['tree'],
        sourceHead='c'*40, tree='d'*40)
    return metadata, {'files': files}, evidence


def test_empty_date_additional_inputs_validates_complete_maps(date_input_maps):
    policy.validate_maps(*date_input_maps, baseline=package.BASELINE)


@pytest.mark.parametrize('fault', ['missing', 'null', 'list', 'nonempty'])
def test_empty_date_additional_inputs_rejects_other_shapes(date_input_maps, fault):
    metadata, manifest, evidence = deepcopy(date_input_maps)
    if fault == 'missing':
        del evidence['additionalTestInputs']
    else:
        evidence['additionalTestInputs'] = {
            'null': None, 'list': [], 'nonempty': {'tests/extra.py': '0'*64}}[fault]
    with pytest.raises(ValueError, match='explicit empty media date build inputs required'):
        policy.validate_maps(metadata, manifest, evidence, baseline=package.BASELINE)


@pytest.mark.parametrize('fault', ['empty', 'digest'])
def test_date_required_supplements_remain_strict(date_input_maps, fault):
    metadata, manifest, evidence = deepcopy(date_input_maps)
    if fault == 'empty':
        evidence['supplementalTestInputs'] = {}
    else:
        name = next(iter(evidence['supplementalTestInputs']))
        evidence['supplementalTestInputs'][name] = '0'*64
    with pytest.raises(ValueError):
        policy.validate_maps(metadata, manifest, evidence, baseline=package.BASELINE)


def test_generic_hash_map_still_requires_nonempty():
    with pytest.raises(ValueError, match='nonempty file map required'):
        policy.hash_map({})
