"""77/9 source-update routing and stopped preservation; no Docker or production."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from deploy import build_assistant_journey_status_release as package
from deploy import prepare_assistant_journey_status_activation as prepare
from deploy import activate_assistant_journey_status_release as entry
from deploy import membership_release_package as policy
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import ReleaseError, read, sha
import test_local_photo_release as previous

ROOT = Path(__file__).resolve().parents[1]


def test_closed_profile_keeps_five_services_and_has_no_migration():
    assert policy.baseline_values(package.BASELINE) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    assert prepare.shared._profile(prepare.MODE) is prepare
    assert package.SCHEMA_BEFORE == package.SCHEMA_AFTER == (77, 9)
    assert policy.fixed_files(package.BASELINE)['Dockerfile'] == package.DOCKER_AFTER
    with pytest.raises(ReleaseError):
        prepare.shared._profile('assistant-journey-status-source-update-other')
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
        plan['schemaBefore'] = plan['schemaAfter'] = [77, 9]
        digest = previous.old.write(candidate/'plan.json', plan)
        kwargs['runner'].plan_sha = digest
        return entry.Controller(candidate, digest, **kwargs)
    monkeypatch.setattr(previous, 'entry', SimpleNamespace(Controller=factory))
    return previous.rig.__wrapped__(tmp_path, monkeypatch)


def test_recorded_five_service_source_update_stops_before_77_check_and_never_migrates(rig):
    c, r = rig
    staged = c.stage()
    assert staged['schemaBefore'] == staged['schemaAfter'] == [77, 9] and not staged['productionWrites']
    assert len(staged['services']) == 5
    result = c.activate()
    assert result['completed'] and result['schema'] == [77, 9] and 'migration' not in result
    assert r.data == ['backup', 'check'] and 'migrate' not in c.data_actions
    assert 'tv_trip_release_data' in c.data_prefix
    assert 'activate_assistant_journey_status_release' in c.data_actions['verify-rollback']
    assert r.started == ['app', 'app', 'decoder', 'sync', 'media', 'web']
    assert r.timer and c.release.name.startswith('assistant-journey-status-77-')
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


def test_plan_rejects_prior_schema_and_wrong_parent(rig):
    c, _ = rig
    for field in ('schemaBefore', 'schemaAfter'):
        for schema in ([73, 9], [75, 9]):
            value = deepcopy(c.plan); value[field] = schema
            with pytest.raises(ReleaseError): prepare.check_plan(value)
    for field in ('parentSource', 'parentManifest'):
        value = deepcopy(c.plan); value[field] = '0'*len(value[field])
        with pytest.raises(ReleaseError): prepare.check_plan(value)


def test_fixed_parent_manifest_closes_114_runtime_and_113_preserved():
    from deploy.git_blobs import read_git_blobs
    names = package.RUNTIME_ADDITIONS | {'requirements.txt'}
    names |= {n for n in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only',
              package.INSTALLED_SOURCE, 'static'], cwd=ROOT).decode().splitlines()
              if not n.startswith(policy.PREFIX)}
    blobs = read_git_blobs(ROOT, package.INSTALLED_SOURCE, names)
    old = {n: sha(raw) for n, raw in blobs.items()}
    assert len(old) == 114 and sha(policy.encoded(old)) == package.PARENT_RUNTIME_SHA256
    assert {n:old[n] for n in package.PARENT_MODULES} == package.PARENT_MODULES
    kept = {n:h for n,h in old.items() if n not in package.CHANGED_RUNTIME_FILES}
    assert len(kept) == 113 and sha(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    assert policy.fixed_files(package.BASELINE)['Dockerfile'] == sha(
        read_git_blobs(ROOT, package.INSTALLED_SOURCE, ['Dockerfile'])['Dockerfile'])
    assert 'media_video_service.py' not in policy.runtime_files(
        {**old, 'media_video_service.py':'0'*64}, baseline=package.BASELINE)


def test_selection_requires_fixed_nodes_modules_and_no_skips(monkeypatch):
    # Small synthetic input tests the gate, not a claim of candidate test execution.
    modules = {'tests/example.py':'1'*64}
    nodes = ['tests/example.py::test_case[fixed]']
    monkeypatch.setattr(prepare, 'TEST_MODULES', modules)
    monkeypatch.setattr(prepare, 'FIXTURE_MODULES', {})
    monkeypatch.setattr(prepare, 'REQUIRED_NODEIDS_SHA256', sha(policy.encoded(nodes)))
    metadata = {'sourceFiles':modules}
    selection = {'modules':list(modules), 'nodeids':nodes, 'allowedSkips':{}}
    prepare.verify_selection(selection, metadata)
    for bad in ({**selection, 'nodeids':nodes+['tests/example.py::test_extra']},
                {**selection, 'modules':[]}, {**selection, 'allowedSkips':{nodes[0]:'reason'}}):
        with pytest.raises(ReleaseError): prepare.verify_selection(bad, metadata)
    with pytest.raises(ReleaseError): prepare.verify_selection(selection, {'sourceFiles':{}})
    monkeypatch.setattr(prepare, 'TEST_MODULES', {})
    with pytest.raises(ReleaseError): prepare.verify_selection(selection, metadata)


def test_old_tv_and_assistant_list_modes_keep_their_schema():
    from deploy import build_tv_trip_release as tv
    from deploy import prepare_tv_trip_activation as tp
    from deploy import prepare_assistant_list_activation as ap
    for cfg, before, after in ((tp,[75,9],[77,9]), (ap,[75,9],[75,9])):
        plan = {'kind':cfg.KIND, 'parentSource':cfg.PARENT_SOURCE,
            'parentManifest':cfg.PARENT_MANIFEST, 'schemaBefore':before, 'schemaAfter':after,
            'images':{'app':'sha256:'+'1'*64,'decoder':cfg.package.DECODER_IMAGE},
            'sourceHead':'a'*40,'tree':'b'*40,'productionWritesDuringPreparation':False}
        cfg.check_plan(plan)
        assert prepare.shared._profile(cfg.MODE) is cfg
    assert policy.baseline_values(tv.BASELINE) == (tv.KIND,tv.PARENT_IMAGE,tv.OLD_MANIFEST)
    assert policy.baseline_values() == ('membership-release-package',policy.PARENT_IMAGE,policy.OLD_MANIFEST)


def test_actual_nonempty77_startup_full_group_restore_and_drift_rejection(tmp_path, monkeypatch):
    from deploy import tv_trip_release_data as data
    from deploy import membership_release_data as core
    import test_tv_trip_migration as tv
    from test_membership_migration import materialize, startup, clone_databases
    from test_task_reminders_migration import documented_restore
    # Direct creation by the already deployed 77 app: no 75-to-77 migration runs.
    source = tmp_path/'source'
    hashes = materialize(source, package.INSTALLED_SOURCE)
    assert startup(source, tmp_path/'seed', 'seed')['households'] == 2
    root = tmp_path/'live'; clone_databases(tmp_path/'seed', root)
    for path in root.rglob('household.sqlite3'):
        tv.execute(path, """
          PRAGMA foreign_keys=ON;
          INSERT INTO entities(id,kind,data,updated_at) VALUES('trip','trips','{"journeyId":"journey","paid":7}','now');
          INSERT INTO journey_workflows VALUES('journey','trip','{}',1,'member1','now','now');
          INSERT INTO devices(id,secret_hash,name,approved,expires,created_at) VALUES('tv','synthetic','TV',1,9999999999,'now');
          INSERT INTO media_playback VALUES('tv','photos',0,10,0,1,1,1);
        """)
    tv.populate(root)  # Nonempty selections, missing journey/device receipts and two owners.
    (root/core.ROOT_ATTEMPT).write_bytes(b'{"syntheticSuccessfulAttempt":true}\n')
    marker = data.marker_digest(root)
    monkeypatch.setattr(data, 'MEMBERSHIP_MARKER_SHA256', marker)
    identity = {'head':package.INSTALLED_SOURCE, 'tree':package.INSTALLED_TREE,
                'imageId':package.PARENT_IMAGE,'sourceHashes':hashes,'runtimeHashes':hashes}
    kwargs = {'source_identity':identity,'plan_sha256':'a'*64,'marker_sha256':marker}
    proof = tmp_path/'proof'; proof.mkdir()
    before = data.snapshot_current(root); data.SPEC.profile(before)
    backup = data.begin(root, proof, **kwargs)
    assert startup(source, root, 'restart')['households'] == 2
    checked = data.check_stopped(root, proof, **kwargs)
    assert checked['logicalSha256'] == backup['logicalSha256'] == core._digest(core._logical(before))
    assert checked['databases'] == 3
    receipt = json.loads((proof/'backup.json').read_bytes())
    marker_bytes = (root/core.ROOT_ATTEMPT).read_bytes()
    retained = tmp_path/'retained'
    assert root.resolve().is_relative_to(tmp_path.resolve()) and not retained.exists()
    root.rename(retained)
    documented_restore(proof/'backup-group', receipt['manifest'], root, marker_bytes, monkeypatch)
    args = {k:v for k,v in kwargs.items() if k != 'marker_sha256'}
    assert entry.verify_restored_group(root, proof, **args)['completeGroupRestored']
    with pytest.raises(FileExistsError): data.begin(root, proof, **kwargs)
    with pytest.raises(tv.ERRORS):
        entry.verify_restored_group(root, proof, **{**args,'plan_sha256':'b'*64})
    for path in root.rglob('household.sqlite3'):
        rows = core.migration._read(path)['rows']
        assert len(rows['media_playback_journeys']) == 2
        assert len(rows['media_playback_operations']) == 3
    # Changed nonempty new data is rejected, as are mutations to any old table.
    tv.edit(tv.child(root), 'DELETE FROM media_playback_operations')
    with pytest.raises(tv.ERRORS): entry.verify_restored_group(root, proof, **args)


def test_frozen_api_runtime_and_exact_real_selection():
    from deploy.git_blobs import read_git_blobs
    author = 'bc3619d05553b62cdf3a83893e92b54bcc279467'
    names = package.RUNTIME_ADDITIONS | {'requirements.txt'}
    names |= {n for n in subprocess.check_output(['git','ls-tree','-r','--name-only',
              package.INSTALLED_SOURCE,'static'],cwd=ROOT).decode().splitlines()
              if not n.startswith(policy.PREFIX)}
    old = {n:sha(b) for n,b in read_git_blobs(ROOT,package.INSTALLED_SOURCE,names).items()}
    current = {n:sha(b) for n,b in read_git_blobs(ROOT,author,names).items()}
    prepare.runtime_boundary(old,current)
    wrong = dict(current);wrong['media_trip_playback.py']='0'*64
    with pytest.raises(ReleaseError): prepare.runtime_boundary(old,wrong)
    wrong = dict(current);wrong['journey_workflows.py']=old['journey_workflows.py']
    with pytest.raises(ReleaseError): prepare.runtime_boundary(old,wrong)
    modules = {**prepare.TEST_MODULES, **prepare.FIXTURE_MODULES}
    assert {n:sha(b) for n,b in read_git_blobs(ROOT,author,set(modules)).items()} == modules


@pytest.fixture(scope='module')
def profile_maps():
    # Map-only synthetic exports, not a build or package execution. Fixed Git
    # supplies real source bytes; the sole runtime change uses the reviewed API.
    from deploy.git_blobs import read_git_blobs
    tracked = set(subprocess.check_output(['git','ls-tree','-r','--name-only',
                  package.INSTALLED_SOURCE],cwd=ROOT).decode().splitlines())
    names = policy.selected_sources(tracked,(ROOT/'deploy/prepare_release.py').read_bytes(),
                                    baseline=package.parent.BASELINE)
    source = {n:sha(b) for n,b in read_git_blobs(ROOT,package.INSTALLED_SOURCE,names).items()}
    source.update(package.CHANGED_MODULES)
    exports = {n:sha(b'synthetic-export') for n in
        ['index.html','metadata.json','_expo/static/js/web/entry-test.js']+
        ['assets/%02d.png'%i for i in range(20)]}
    inputs = {n:source[n] for n in policy.required_build_inputs(source)}
    evidence = dict(schemaVersion=1,kind='membership-expo-build',buildExit=0,bundleMarkers=True,
        head='a'*40,tree='b'*40,inputFiles=inputs,files=exports,
        supplementalTestInputs={n:source[n] for n in package.SUPPLEMENTAL_INPUTS},
        additionalTestInputs={})
    files = {**source,**{policy.PREFIX+n:h for n,h in exports.items()}}
    metadata = dict(kind=package.KIND,parentImage=package.PARENT_IMAGE,
        oldManifestSha256=package.OLD_MANIFEST,sourceFiles=source,exportFiles=exports,
        runtimeFiles=policy.runtime_files(files,baseline=package.BASELINE),
        fixedFiles=policy.fixed_files(package.BASELINE),inputFiles=inputs,
        buildSourceHead=evidence['head'],buildSourceTree=evidence['tree'],sourceHead='c'*40,tree='d'*40)
    return metadata,{'files':files},evidence


def test_complete_map_validation_and_single_runtime_boundary(profile_maps):
    policy.validate_maps(*profile_maps,baseline=package.BASELINE)
    for name in ('journey_workflows.py','media_trip_playback.py'):
        metadata,manifest,evidence=deepcopy(profile_maps)
        metadata['sourceFiles'][name]=manifest['files'][name]=metadata['runtimeFiles'][name]='0'*64
        with pytest.raises(ValueError,match='preservation boundary'):
            policy.validate_maps(metadata,manifest,evidence,baseline=package.BASELINE)


@pytest.mark.parametrize('shape',['missing','null','list','nonempty'])
def test_additional_inputs_requires_explicit_empty_dict(profile_maps,shape):
    metadata,manifest,evidence=deepcopy(profile_maps)
    if shape=='missing':del evidence['additionalTestInputs']
    else:evidence['additionalTestInputs']={'null':None,'list':[],'nonempty':{'tests/extra.py':'0'*64}}[shape]
    with pytest.raises(ValueError,match='explicit empty assistant journey status build inputs'):
        policy.validate_maps(metadata,manifest,evidence,baseline=package.BASELINE)


def test_source_allowlist_requires_exact_new_ui_and_browser():
    tracked=set(subprocess.check_output(['git','ls-tree','-r','--name-only',package.INSTALLED_SOURCE],cwd=ROOT).decode().splitlines())
    extra={'frontend/tests/assistantJourneyStatus.test.mjs','tests/browser_assistant_journey_status_check.py'}
    raw=(ROOT/'deploy/prepare_release.py').read_bytes()
    selected=policy.selected_sources(tracked|extra,raw,baseline=package.BASELINE)
    assert extra <= selected
    with pytest.raises(ValueError):policy.selected_sources(tracked,raw,baseline=package.BASELINE)
    with pytest.raises(ValueError,match='new frontend input needs an explicit packaging policy'):
        policy.selected_sources(tracked|extra|{'frontend/tests/unreviewed.test.mjs'},raw,baseline=package.BASELINE)
