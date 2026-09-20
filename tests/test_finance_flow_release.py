"""New static policy, real Git packages, and recorded lifecycle; no Docker daemon."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
from deploy import build_finance_flow_release as package
from deploy import prepare_finance_flow_activation as prepare
from deploy import activate_finance_flow_release as entry
from deploy import membership_release_package as policy
from deploy import prepare_local_photo_activation as shared
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import ReleaseError, sha
import test_local_photo_release as previous

ROOT = Path(__file__).resolve().parents[1]
NEW = {'deploy/build_finance_flow_release.py', 'deploy/prepare_finance_flow_activation.py',
       'deploy/activate_finance_flow_release.py', 'tests/test_finance_flow_release.py',
       'docs/FINANCE-FLOW-RELEASE.md'}


def blob(head, name):
    return subprocess.check_output(['git', 'show', head+':'+name], cwd=ROOT)


def test_fixed_parent_and_runtime_boundary_from_actual_git():
    names = package.RUNTIME_ADDITIONS | {'requirements.txt'}
    names |= {n for n in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only',
              package.INSTALLED_SOURCE, 'static'], cwd=ROOT).decode().splitlines()
              if not n.startswith(policy.PREFIX)}
    original = {n: sha(blob(package.INSTALLED_SOURCE, n)) for n in names}
    current = {n: sha((ROOT/n).read_bytes()) for n in names}
    assert len(original) == 112
    assert sha(policy.encoded(original)) == package.PARENT_RUNTIME_SHA256
    assert {n for n in current if current[n] != original[n]} == {'finance_hub.py'}
    kept = {n: h for n, h in current.items() if n != 'finance_hub.py'}
    assert len(kept) == 111 and sha(policy.encoded(kept)) == package.PRESERVED_RUNTIME_SHA256
    assert prepare.unchanged_finance_ast(blob(package.INSTALLED_SOURCE, 'finance_hub.py'),
                                      (ROOT/'finance_hub.py').read_bytes())['changedOnlyInside'] == [
                                          '_import_conflict', '_column_controls', 'parse_import']


def test_new_profile_is_static_and_old_modes_stay_fixed():
    assert policy.baseline_values()[0] == 'membership-release-package'
    assert policy.baseline_values(package.BASELINE) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    assert policy.baseline_values(package.parent.BASELINE)[1] == package.parent.PARENT_IMAGE
    assert shared._profile() is shared
    assert shared._profile('discovery-source-update') is prepare.discovery
    with pytest.raises(ReleaseError, match='unsupported_source_update_profile'): shared._profile('arbitrary-module')
    with pytest.raises(ValueError): policy.baseline_values('arbitrary')
    with pytest.raises(ReleaseError): services.Lifecycle(None, package.PARENT_IMAGE, package.DECODER_IMAGE, mode=prepare.MODE)
    with pytest.raises(ReleaseError): services.Lifecycle(None, 'sha256:'+'1'*64, 'sha256:'+'2'*64, mode=prepare.MODE)


def test_even_repinning_finance_cannot_hide_module_initialization_changes(monkeypatch):
    before = blob(package.INSTALLED_SOURCE, 'finance_hub.py')
    after = (ROOT/'finance_hub.py').read_bytes()+b'\nchanged_global = True\n'
    monkeypatch.setitem(package.CHANGED_MODULES, 'finance_hub.py', sha(after))
    with pytest.raises(ReleaseError, match='finance_resource_behavior_changed'):
        prepare.unchanged_finance_ast(before, after)


@pytest.fixture(scope='module')
def packaged(tmp_path_factory):
    root = tmp_path_factory.mktemp('finance-flow-package'); repo = root/'repo'; repo.mkdir()
    names = set(subprocess.check_output(['git', 'ls-files'], cwd=ROOT).decode().splitlines()) | NEW
    selected = policy.selected_sources(names, (ROOT/'deploy/prepare_release.py').read_bytes(), baseline=package.BASELINE)
    for name in selected: previous.old.write(repo/name, (ROOT/name).read_bytes())
    def git(*args): return subprocess.check_output(['git', *args], cwd=repo).decode().strip()
    git('init', '-q'); git('config', 'user.name', 'Synthetic release'); git('config', 'user.email', 'test@example.invalid')
    git('config', 'core.autocrlf', 'false'); git('add', '.'); git('commit', '-qm', 'Synthetic fixed finance source')
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


def test_real_git_package_and_docs_only_build_reuse(packaged):
    value, evidence, root, git, ehash = packaged
    assert len(value['metadata']['runtimeFiles']) == 135
    assert value['metadata']['parentImage'] == package.PARENT_IMAGE
    assert value['metadata']['fixedFiles']['deploy/nginx.conf'] == package.NGINX_AFTER
    previous.old.write(root/'repo/docs/FINANCE-FLOW-RELEASE.md', b'Synthetic documentation-only revision\n')
    git('add', 'docs/FINANCE-FLOW-RELEASE.md'); git('commit', '-qm', 'Synthetic documentation only')
    new_head = git('rev-parse', 'HEAD')
    result = package.prepare(repo=root/'repo', commit=new_head, export_dir=root/'web',
        build_evidence=root/'evidence.json', evidence_sha256=ehash, output_dir=root/'reused')
    reused = package.verify_package(root/'reused', result['packageSha256'])
    assert reused['metadata']['buildSourceHead'] == evidence['head'] != new_head
    path = root/'repo/frontend/src/lib/financeImport.ts'; path.write_bytes(path.read_bytes()+b'\n// changed input\n')
    git('add', 'frontend/src/lib/financeImport.ts'); git('commit', '-qm', 'Synthetic input changed')
    with pytest.raises(ValueError, match='build source bytes differ'):
        package.prepare(repo=root/'repo', commit=git('rev-parse', 'HEAD'), export_dir=root/'web',
            build_evidence=root/'evidence.json', evidence_sha256=ehash, output_dir=root/'rejected')
    assert not (root/'rejected').exists()


@pytest.mark.parametrize('name', ['finance_hub.py', 'household_media.py', 'media_images.py',
                                  'requirements.txt', 'Dockerfile', 'compose.yaml', 'deploy/nginx.conf'])
def test_maps_reject_wrong_finance_other_runtime_or_fixed_config(packaged, name):
    value, evidence, *_ = packaged; value = deepcopy(value)
    meta, manifest = value['metadata'], value['manifest']
    meta['sourceFiles'][name] = manifest['files'][name] = '0'*64
    if name in meta['runtimeFiles']: meta['runtimeFiles'][name] = '0'*64
    with pytest.raises(ValueError): policy.validate_maps(meta, manifest, evidence, baseline=package.BASELINE)


@pytest.mark.parametrize('field', ['supplementalTestInputs', 'additionalTestInputs'])
def test_supplemental_build_inputs_cannot_silently_drift(packaged, field):
    value, evidence, *_ = packaged; evidence = deepcopy(evidence)
    evidence[field][next(iter(evidence[field]))] = '0'*64
    with pytest.raises(ValueError, match='supplemental build inputs differ'):
        policy.validate_maps(value['metadata'], value['manifest'], evidence, baseline=package.BASELINE)


def test_missing_retained_resources_is_rejected_before_any_image_admission():
    with pytest.raises(ReleaseError, match='release_inputs_incomplete'): prepare.verify_evidence({})


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(previous, 'package', package)
    monkeypatch.setattr(previous, 'prepare', prepare)
    monkeypatch.setattr(previous, 'entry', entry)
    return previous.rig.__wrapped__(tmp_path, monkeypatch)


def test_new_controller_records_five_services_preservation_and_single_use(rig):
    c, r = rig; staged = c.stage()
    assert len(staged['services']) == 5 and not staged['productionWrites']
    result = c.activate()
    assert result['completed'] and r.data == ['backup', 'check'] and 'migrate' not in c.data_actions
    assert r.started == ['app', 'app', 'decoder', 'sync', 'media', 'web']
    assert r.timer and c.release.name.startswith('finance-flow-73-')
    assert 'verify_restored_group' in c.data_actions['verify-rollback']
    with pytest.raises(ReleaseError, match='plan_consumed'): c.activate()


@pytest.mark.parametrize('fault', ['check', 'health'])
def test_failed_finance_update_retains_data_and_never_automatically_restores(rig, fault):
    c, r = rig; c.stage(); r.fault = fault
    with pytest.raises(ReleaseError): c.activate()
    failure = json.loads((c.candidate/'failure.json').read_bytes())
    assert failure['automaticRestore'] is False and failure['candidateStop']['complete']
    assert (c.candidate/'activation-started.json').exists()
    assert not any('restore' in str(argv) for argv, _ in r.calls)
    assert not any(v['State']['Running'] for v in r.values.values())


# Exact original author JUnit selection; no body execution in this module.
NODES = ['tests/test_finance_column_mapping.py::test_canonical_mapping_signing_and_changed_payload_cannot_replay',
 'tests/test_finance_column_mapping.py::test_file_preview_and_confirm_exact_cents_with_original_receipt[synthetic.csv-utf-8-,]',
 'tests/test_finance_column_mapping.py::test_file_preview_and_confirm_exact_cents_with_original_receipt[synthetic.txt-gb18030-\\t]',
 'tests/test_finance_column_mapping.py::test_inspect_preserves_empty_duplicate_labels_without_row_samples',
 'tests/test_finance_column_mapping.py::test_old_automatic_signed_digest_remains_identical',
 'tests/test_finance_flow_mapping.py::test_flow_file_preview_confirm_receipt_replay_and_private_totals[csv]',
 'tests/test_finance_flow_mapping.py::test_flow_file_preview_confirm_receipt_replay_and_private_totals[xlsx]',
 'tests/test_finance_flow_mapping.py::test_flow_mapping_change_needs_preview_and_cannot_reuse_original_intent',
 'tests/test_finance_flow_mapping.py::test_flow_mapping_private_receipt_member_household_and_tv_boundaries',
 'tests/test_finance_flow_mapping.py::test_flow_mapping_version_scope_and_shape_rejected[patch0]',
 'tests/test_finance_flow_mapping.py::test_flow_mapping_version_scope_and_shape_rejected[patch1]',
 'tests/test_finance_flow_mapping.py::test_flow_mapping_version_scope_and_shape_rejected[patch2]',
 'tests/test_finance_flow_mapping.py::test_flow_mapping_version_scope_and_shape_rejected[patch3]',
 'tests/test_finance_flow_mapping.py::test_flow_mapping_version_scope_and_shape_rejected[patch4]',
 'tests/test_finance_flow_mapping.py::test_historical_automatic_fingerprint_without_row_key_deduplicates[False]',
 'tests/test_finance_flow_mapping.py::test_historical_automatic_fingerprint_without_row_key_deduplicates[True]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[-1]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[0]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[3]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[4.0]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[4]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[6]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[80]',
 'tests/test_finance_flow_mapping.py::test_invalid_flow_column_rejected[True]',
 'tests/test_finance_flow_mapping.py::test_manually_corrected_flow_is_not_overwritten_on_reimport[mapping0]',
 'tests/test_finance_flow_mapping.py::test_manually_corrected_flow_is_not_overwritten_on_reimport[mapping1]',
 'tests/test_finance_flow_mapping.py::test_null_mapping_preserves_v1_auto_direction_and_unknown_values',
 'tests/test_finance_flow_mapping.py::test_same_file_v1_v2_both_directions_keep_original_record[1-csv]',
 'tests/test_finance_flow_mapping.py::test_same_file_v1_v2_both_directions_keep_original_record[1-xlsx]',
 'tests/test_finance_flow_mapping.py::test_same_file_v1_v2_both_directions_keep_original_record[2-csv]',
 'tests/test_finance_flow_mapping.py::test_same_file_v1_v2_both_directions_keep_original_record[2-xlsx]',
 'tests/test_finance_hub.py::test_chinese_header_preamble_and_aliases',
 'tests/test_finance_hub.py::test_conservative_refunds_transfers_orders_and_currency']


@pytest.mark.parametrize('fault', [None, 'missing', 'extra', 'skip', 'module-bytes'])
def test_exact33_original_nodes_and_modules_required(packaged, fault):
    value, *_ = packaged
    selection = {'nodeids': list(NODES), 'allowedSkips': {}, 'modules': sorted(prepare.TEST_MODULES)}
    meta = deepcopy(value['metadata'])
    if fault == 'missing': selection['nodeids'].pop()
    if fault == 'extra': selection['nodeids'].append('tests/test_finance_flow_mapping.py::unreviewed')
    if fault == 'skip': selection['allowedSkips'][NODES[0]] = 'not approved'
    if fault == 'module-bytes': meta['sourceFiles']['tests/test_finance_flow_mapping.py'] = '0'*64
    if fault:
        with pytest.raises(ReleaseError): prepare.verify_selection(selection, meta)
    else: prepare.verify_selection(selection, meta)


@pytest.mark.parametrize('fault', ['package', 'build', 'plan'])
def test_retained_package_build_and_plan_identities_cannot_be_replaced(tmp_path, fault):
    spec = {'package': {'root': str(tmp_path), 'sha256': package.OLD_PACKAGE},
            'build': {'root': str(tmp_path), 'sha256': prepare.PARENT_BUILD_SHA256},
            'plan': {'path': str(tmp_path/'plan.json'), 'sha256': prepare.PARENT_PLAN_SHA256}}
    spec[fault]['sha256'] = '0'*64
    with pytest.raises(ReleaseError, match='retained_discovery_identity_changed'):
        prepare.retained_parent({'retainedDiscovery': spec}, {})


@pytest.mark.parametrize('fault', [None, 'old-finance', 'new-finance', 'media', 'added-module'])
def test_retained_workload_requires_exact111_and_original_finance(packaged, fault):
    value, *_ = packaged; current = dict(value['metadata']['runtimeFiles'])
    original = {**current, **package.PARENT_MODULES}
    if fault == 'old-finance': original['finance_hub.py'] = current['finance_hub.py']
    if fault == 'new-finance': current['finance_hub.py'] = package.PARENT_MODULES['finance_hub.py']
    if fault == 'media': current['media_images.py'] = '0'*64
    if fault == 'added-module': current['another.py'] = '0'*64
    if fault:
        with pytest.raises(ReleaseError, match='retained_runtime_boundary_changed'):
            prepare.runtime_boundary(original, current)
    else: prepare.runtime_boundary(original, current)


@pytest.mark.parametrize('profile', ['image_overlap', 'nginx_raw', 'duplicates'])
def test_resource_receipts_must_be_the_consumed_parent_plan_originals(profile):
    inputs = {p: {'input': {'sha256': '1'*64}, 'run': {'sha256': '2'*64}}
              for p in ('image_overlap', 'nginx_raw', 'duplicates')}
    plan = {'inputs': deepcopy(inputs)}
    prepare.resource_descriptors(inputs, plan)
    inputs[profile]['run']['sha256'] = '3'*64
    with pytest.raises(ReleaseError, match='retained_resource_receipt_changed'):
        prepare.resource_descriptors(inputs, plan)
