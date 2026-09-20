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


NODES = ['tests/test_data_portability.py::test_export_is_owner_scoped_and_shared_is_explicit', 'tests/test_journey_finance.py::test_amount_is_strict_integer_cents[-1]', 'tests/test_journey_finance.py::test_amount_is_strict_integer_cents[0]', 'tests/test_journey_finance.py::test_amount_is_strict_integer_cents[1.5]', 'tests/test_journey_finance.py::test_amount_is_strict_integer_cents[100000000001]', 'tests/test_journey_finance.py::test_amount_is_strict_integer_cents[100]', 'tests/test_journey_finance.py::test_amount_is_strict_integer_cents[True]', 'tests/test_journey_finance.py::test_bad_source_is_reviewable_and_revocable_without_blocking_other_history[boolean_amount]', 'tests/test_journey_finance.py::test_bad_source_is_reviewable_and_revocable_without_blocking_other_history[negative_net]', 'tests/test_journey_finance.py::test_bad_source_is_reviewable_and_revocable_without_blocking_other_history[string_amount]', 'tests/test_journey_finance.py::test_broken_trip_backreference_does_not_attach_other_journey_budget', 'tests/test_journey_finance.py::test_duplicate_drift_and_deleted_target_can_be_revoked_without_recreating', 'tests/test_journey_finance.py::test_expired_saved_receipt_replays_but_unsaved_preview_rejects', 'tests/test_journey_finance.py::test_noneligible_payment_reason_and_no_write[expense-USD-unsupported_currency]', 'tests/test_journey_finance.py::test_noneligible_payment_reason_and_no_write[income-CNY-not_expense]', 'tests/test_journey_finance.py::test_noneligible_payment_reason_and_no_write[refund-CNY-not_expense]', 'tests/test_journey_finance.py::test_noneligible_payment_reason_and_no_write[transfer-CNY-not_expense]', 'tests/test_journey_finance.py::test_noneligible_payment_reason_and_no_write[unknown-CNY-not_expense]', 'tests/test_journey_finance.py::test_order_and_shopping_are_not_added_or_deducted_from_travel_net', 'tests/test_journey_finance.py::test_pagination_summary_all_pages_and_focus_not_appended', 'tests/test_journey_finance.py::test_parallel_different_journeys_cannot_overallocate_same_payment', 'tests/test_journey_finance.py::test_parallel_same_request_commits_once_and_duplicate_pair_rejects', 'tests/test_journey_finance.py::test_previews_bind_versions_source_and_reservations_but_revoke_ignores_source', 'tests/test_journey_finance.py::test_real_preview_confirmation_receipt_restart_and_no_original_mutation', 'tests/test_journey_finance.py::test_receipt_byte_capacity_keeps_reserved_revoke_space', 'tests/test_journey_finance.py::test_receipt_capacity_reserves_revoke_and_replay_survives_capacity', 'tests/test_journey_finance.py::test_refund_drift_preserves_reservation_until_explicit_update', 'tests/test_journey_finance.py::test_request_fields_and_legacy_trip_are_not_silently_accepted', 'tests/test_journey_finance.py::test_schema_exact_new_tables_and_atomic_initialization', 'tests/test_journey_finance.py::test_source_deleted_and_new_token_replay_conflict', 'tests/test_journey_finance_portability.py::test_export_allocation_and_receipt_allowlists_and_other_owner_absence[False]', 'tests/test_journey_finance_portability.py::test_export_allocation_and_receipt_allowlists_and_other_owner_absence[True]', 'tests/test_journey_finance_sessions.py::test_expiry_after_audit_rolls_back_allocation_receipt_and_audit', 'tests/test_journey_finance_sessions.py::test_owner_tv_and_other_household_cannot_read_private_history', 'tests/test_journey_finance_sessions.py::test_post_commit_revocation_returns_unknown_but_minimal_receipt_is_durable', 'tests/test_journey_finance_sessions.py::test_revoked_after_global_guard_never_reads_or_writes[confirm]', 'tests/test_journey_finance_sessions.py::test_revoked_after_global_guard_never_reads_or_writes[list]', 'tests/test_journey_finance_sessions.py::test_revoked_after_global_guard_never_reads_or_writes[payments]', 'tests/test_journey_finance_sessions.py::test_revoked_after_global_guard_never_reads_or_writes[preview]', 'tests/test_journey_finance_sessions.py::test_revoked_after_global_guard_never_reads_or_writes[receipt]', 'tests/test_journey_finance_sessions.py::test_revoked_during_snapshot_is_rechecked_after_release[list]', 'tests/test_journey_finance_sessions.py::test_revoked_during_snapshot_is_rechecked_after_release[payments]', 'tests/test_journey_finance_sessions.py::test_revoked_during_snapshot_is_rechecked_after_release[preview]', 'tests/test_journey_finance_sessions.py::test_same_owner_cookie_swap_after_guard_rejected', 'tests/test_journey_finance_sessions.py::test_write_lock_contention_is_recoverable_without_receipt_or_partial_write', 'tests/test_shopping_settlement.py::test_partial_refund_uses_only_confirmed_allocation_and_does_not_double_count_orders']


@pytest.mark.parametrize('fault', [None, 'missing', 'extra', 'skip', 'module-bytes'])
def test_exact46_api_nodes_modules_and_zero_skip(packaged, fault):
    value, *_ = packaged
    selection = {'nodeids': list(NODES), 'allowedSkips': {}, 'modules': sorted(prepare.TEST_MODULES)}
    meta = deepcopy(value['metadata'])
    if fault == 'missing': selection['nodeids'].pop()
    if fault == 'extra': selection['nodeids'].append('tests/test_journey_finance.py::unreviewed')
    if fault == 'skip': selection['allowedSkips'][NODES[0]] = 'not approved'
    if fault == 'module-bytes': meta['sourceFiles']['tests/test_journey_finance.py'] = '0'*64
    if fault:
        with pytest.raises(ReleaseError): prepare.verify_selection(selection, meta)
    else: prepare.verify_selection(selection, meta)


@pytest.fixture
def migration_record(tmp_path, packaged):
    value = deepcopy(packaged[0]); inputs_root = tmp_path/'input'; run = tmp_path/'run'
    meta = value['metadata']; tool = 'deploy/journey_finance_migration_linux_probe.py'
    sources = {n: (ROOT/n).read_bytes() for n in prepare.MIGRATION_CLOSURE}
    sources[tool] = b'# Synthetic migration-probe source for receipt validator tests only.'
    meta['sourceFiles'][tool] = sha(sources[tool])
    files = {'release/'+n: previous.old.write(inputs_root/'release'/n, raw) for n, raw in sources.items()}
    modules = {n:h for n,h in meta['runtimeFiles'].items() if '/' not in n}
    inputs = {'kind':'journey-finance-migration-linux-input-v1', 'sourceHead':'b'*40, 'tree':'c'*40,
        'runtimeSourceHead':prepare.MIGRATION_RUNTIME_SOURCE, 'historicalHead':package.INSTALLED_SOURCE,
        'productionOperations':False, 'runtimeFiles':modules, 'sourceFiles':{n:sha(raw) for n,raw in sources.items()}, 'files':files}
    ihash = previous.old.write(inputs_root/'input.json', inputs)
    group = {'verified':True,'households':2,'databases':3,'logicalSha256':'d'*64}
    stages = {n:dict(group) for n in prepare.MIGRATION_STAGES}
    stages['verify'].update(uid=10001,runtime=modules)
    for n in ('rollback73','partial','restore75'): stages[n]['completeGroupRestored']=True
    stages['partial'].update(replayRejected=True,partialTableCounts={'household.sqlite3':75,'child.sqlite3':73})
    for n in ('startup','restart'): stages[n]['initialized']=True
    stages['populate75'].update(populated=True,rowsPerNewTable=dict(prepare.POPULATED_ROWS))
    original = previous.old.write(run/'proof/synthetic-original.json', stages)
    built = {'imageId':'sha256:'+'e'*64}
    result = {'passed':True,'syntheticOnly':True,'productionAccess':False,'imageId':built['imageId'],
        'inputSha256':ihash,'stages':stages,'proofHashes':{'synthetic-original.json':original},'commands':[{'exitCode':0}]}
    rhash = previous.old.write(run/'result.json', result)
    spec = {'input':{'root':str(inputs_root),'sha256':ihash},'run':{'root':str(run),'sha256':rhash}}
    return spec,value,built,inputs,result


@pytest.mark.parametrize('fault', [None,'image','runtime','historical','source-closure','missing-stage','one-household',
    'partial','replay','incomplete-restore','empty75','logical','no-startup','command','original'])
def test_new_migration_requires_bound_actual_runtime_and_complete75_contract(migration_record, fault):
    spec,value,built,inputs,result = migration_record
    if fault == 'image': result['imageId']='sha256:'+'f'*64
    if fault == 'runtime': inputs['runtimeFiles']['journey_finance.py']='0'*64
    if fault == 'historical': inputs['historicalHead']='0'*40
    if fault == 'source-closure': inputs['sourceFiles']['deploy/check_journey_finance_migration.py']='0'*64
    if fault == 'missing-stage': del result['stages']['partial']
    if fault == 'one-household': result['stages']['seed']['households']=1
    if fault == 'partial': result['stages']['partial']['partialTableCounts']['child.sqlite3']=71
    if fault == 'replay': result['stages']['partial']['replayRejected']=False
    if fault == 'incomplete-restore': result['stages']['restore75']['completeGroupRestored']=False
    if fault == 'empty75': result['stages']['populate75']['rowsPerNewTable']['hub_journey_allocations']=0
    if fault == 'logical': result['stages']['check']['logicalSha256']='0'*64
    if fault == 'no-startup': result['stages']['restart']['initialized']=False
    if fault == 'command': result['commands'][0]['exitCode']=1
    if fault == 'original': (Path(spec['run']['root'])/'proof/synthetic-original.json').write_bytes(b'changed')
    spec['input']['sha256']=previous.old.write(Path(spec['input']['root'])/'input.json', inputs)
    result['inputSha256']=spec['input']['sha256']
    spec['run']['sha256']=previous.old.write(Path(spec['run']['root'])/'result.json', result)
    if fault:
        with pytest.raises(ReleaseError): prepare.verify_migration(spec,value,built)
    else:
        proof=prepare.verify_migration(spec,value,built)
        assert proof['operatorHead']=='b'*40 and proof['candidateSourceHead']==value['metadata']['sourceHead']
        assert proof['runtimeBytesEquivalent'] and proof['runtimeSourceHead']==prepare.MIGRATION_RUNTIME_SOURCE
