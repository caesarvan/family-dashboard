"""New policy/receipt failures plus recorded five-service lifecycle; no Docker."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from deploy import build_tv_trip_release as package
from deploy import prepare_tv_trip_activation as prepare
from deploy import activate_tv_trip_release as entry
from deploy import membership_release_package as policy
from deploy import prepare_local_photo_activation as shared
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import ReleaseError, read, sha
import test_local_photo_release as previous
from test_journey_finance_release import JourneyRunner

ROOT = Path(__file__).resolve().parents[1]
CAPACITY = 'tests/test_tv_trip_capacity.py::test_four_wsgi_reads_2000_media_100_stops_no_large_blob'


def runtime():
    names = package.RUNTIME_ADDITIONS | {'requirements.txt'}
    names |= {n for n in subprocess.check_output(['git','ls-tree','-r','--name-only',
              package.INSTALLED_SOURCE,'static'],cwd=ROOT).decode().splitlines() if not n.startswith(policy.PREFIX)}
    return {n: sha((ROOT/n).read_bytes()) for n in sorted(names)}


@pytest.fixture
def candidate():
    return {'metadata': {'sourceHead':'a'*40, 'tree':'b'*40, 'runtimeFiles':runtime(),
        'sourceFiles':{n:sha((ROOT/n).read_bytes()) for n in prepare.MIGRATION_CLOSURE | set(prepare.TEST_MODULES) | set(prepare.FIXTURE_MODULES)}}}


def test_actual_parent113_to_candidate114_keeps112_and_rejects_native_drift():
    current = runtime()
    names = set(current)-{'media_trip_playback.py'}
    old = {n:sha(subprocess.check_output(['git','show',package.INSTALLED_SOURCE+':'+n],cwd=ROOT)) for n in names}
    prepare.runtime_boundary(old,current)
    assert len(old)==113 and len(current)==114
    current['media_images.py']='0'*64
    with pytest.raises(ReleaseError): prepare.runtime_boundary(old,current)


def test_closed_profile_preserves_old_registration_and_requires_decoder():
    assert shared._profile('assistant-list-source-update') is prepare.parent
    assert shared._profile(prepare.MODE) is prepare
    assert package.SCHEMA_BEFORE==(75,9) and package.SCHEMA_AFTER==(77,9)
    with pytest.raises(ReleaseError): shared._profile('tv-trip-75-to-78')
    with pytest.raises(ReleaseError): services.Lifecycle(None,'sha256:'+'1'*64,'sha256:'+'2'*64,mode=prepare.MODE)


@pytest.fixture
def rig(tmp_path,monkeypatch):
    monkeypatch.setattr(previous,'package',package)
    monkeypatch.setattr(previous,'prepare',prepare)
    monkeypatch.setattr(previous,'Runner',JourneyRunner)
    def factory(candidate,digest,**kwargs):
        plan=read(candidate/'plan.json',digest);plan.update(schemaBefore=[75,9],schemaAfter=[77,9])
        digest=previous.old.write(candidate/'plan.json',plan);kwargs['runner'].plan_sha=digest
        return entry.Controller(candidate,digest,**kwargs)
    monkeypatch.setattr(previous,'entry',SimpleNamespace(Controller=factory))
    return previous.rig.__wrapped__(tmp_path,monkeypatch)


def test_five_service_real_controller_orders_migration_and_consumes_once(rig):
    c,r=rig;staged=c.stage()
    assert staged['schemaBefore']==[75,9] and staged['schemaAfter']==[77,9]
    assert len(staged['services'])==5 and not staged['productionWrites']
    result=c.activate()
    assert result['completed'] and result['schema']==[77,9]
    assert r.data==['backup','migrate','check'] and result['migration']['schemaSha256']=='8'*64
    assert r.started==['app','app','decoder','sync','media','web']
    assert 'check_tv_trip_migration' in c.data_prefix and c.release.name.startswith('tv-trip-77-')
    assert r.timer and 'verify_restored_group' not in c.data_actions['verify-rollback']
    with pytest.raises(ReleaseError,match='plan_consumed'):c.activate()


@pytest.mark.parametrize('fault',['migrate','check','logical-drift','migration-identity','backup-as-migration','health'])
def test_failure_never_replays_migration_or_automatically_restores(rig,fault):
    c,r=rig;c.stage();r.fault=fault
    with pytest.raises(ReleaseError):c.activate()
    failure=read(c.candidate/'failure.json')
    assert failure['automaticRestore'] is False and failure['candidateStop']['complete'] and not r.timer
    assert (c.candidate/'activation-started.json').exists() and not any(v['State']['Running'] for v in r.values.values())
    assert not any('restore' in str(argv) for argv,_ in r.calls)
    if fault!='health':assert 'decoder' not in r.started


def test_old_assistant_source_update_still75_and_no_migration(tmp_path,monkeypatch):
    from deploy import activate_assistant_list_release as oldentry
    monkeypatch.setattr(previous,'package',package.parent);monkeypatch.setattr(previous,'prepare',prepare.parent)
    def factory(candidate,digest,**kwargs):
        plan=read(candidate/'plan.json',digest);plan.update(schemaBefore=[75,9],schemaAfter=[75,9])
        digest=previous.old.write(candidate/'plan.json',plan);kwargs['runner'].plan_sha=digest
        return oldentry.Controller(candidate,digest,**kwargs)
    monkeypatch.setattr(previous,'entry',SimpleNamespace(Controller=factory))
    c,r=previous.rig.__wrapped__(tmp_path,monkeypatch);c.stage();result=c.activate()
    assert result['schema']==[75,9] and r.data==['backup','check'] and not c.needs_migration


@pytest.mark.parametrize('fault',[None,'missing','extra','skip','module','fixture'])
def test_exact118_selection_without_ffmpeg_and_pinned_fixture_closure(candidate,fault):
    # Exact collected names; this receipt check never executes those business bodies.
    nodes=list(NODES)
    selection={'nodeids':nodes,'allowedSkips':{},'modules':sorted(prepare.TEST_MODULES)}
    if fault=='missing':selection['nodeids'].pop()
    if fault=='extra':selection['nodeids'].append('tests/test_media_trip_playback.py::unapproved')
    if fault=='skip':selection['allowedSkips'][nodes[0]]='not-approved'
    if fault=='module':candidate['metadata']['sourceFiles']['tests/test_media_playback.py']='0'*64
    if fault=='fixture':candidate['metadata']['sourceFiles']['tests/test_household_media.py']='0'*64
    if fault:
        with pytest.raises(ReleaseError):prepare.verify_selection(selection,candidate['metadata'])
    else:
        prepare.verify_selection(selection,candidate['metadata'])
        assert CAPACITY in nodes and not any('test_real_video_in_scoped_playlist' in n for n in nodes)


def test_collected_selection_is_accepted_by_real_shared_builder(candidate):
    from deploy import membership_release_build as builder
    meta = candidate['metadata']
    meta['manifestSha256'] = 'c' * 64
    selection = {'schemaVersion': 1, 'sourceHead': meta['sourceHead'],
                 'manifestSha256': meta['manifestSha256'], 'modules': sorted(prepare.TEST_MODULES),
                 'nodeids': list(NODES), 'allowedSkips': {}}
    raw = policy.encoded(selection)
    assert builder.selection_record(raw, policy.digest(raw), meta) == selection
    prepare.verify_selection(selection, meta)
    assert len(NODES) == 118 and max(map(len, NODES)) < 2000


NODES = ['tests/test_media_playback.py::test_audit_failure_rolls_back_state', 'tests/test_media_playback.py::test_auth_csrf_member_tv_mix_and_query_rejection', 'tests/test_media_playback.py::test_database_constraints[anchor_at=-1]', 'tests/test_media_playback.py::test_database_constraints[cursor=-1]', "tests/test_media_playback.py::test_database_constraints[device_id='missing']", 'tests/test_media_playback.py::test_database_constraints[interval_seconds=4]', 'tests/test_media_playback.py::test_database_constraints[interval_seconds=5.2]', "tests/test_media_playback.py::test_database_constraints[mode='video']", 'tests/test_media_playback.py::test_database_constraints[paused=2]', 'tests/test_media_playback.py::test_database_constraints[revision=0]', 'tests/test_media_playback.py::test_database_constraints[updated_at=-1]', 'tests/test_media_playback.py::test_default_no_write_and_explicit_schema', 'tests/test_media_playback.py::test_factory_schema_registration_and_reject_partial', 'tests/test_media_playback.py::test_frozen_engine_photo_flow_persists_and_advances_only_on_actual_ended', 'tests/test_media_playback.py::test_lease_bounded_by_device_expiry_and_server_clock', 'tests/test_media_playback.py::test_member_revalidated_inside_write_transaction', 'tests/test_media_playback.py::test_other_member_can_control_but_control_never_grants', 'tests/test_media_playback.py::test_parallel_controls_have_one_cas_winner_and_no_duplicate_effect', 'tests/test_media_playback.py::test_raw_json_rejected[array]', 'tests/test_media_playback.py::test_raw_json_rejected[duplicate-key]', 'tests/test_media_playback.py::test_raw_json_rejected[infinity]', 'tests/test_media_playback.py::test_raw_json_rejected[nan]', 'tests/test_media_playback.py::test_raw_json_rejected[null]', 'tests/test_media_playback.py::test_raw_json_rejected[oversize]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[account]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[delete]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[device_deleted]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[device_expired]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[grant]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[private]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[reauth]', 'tests/test_media_playback.py::test_revoke_is_checked_again_on_every_tv_read[scope]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes0]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes10]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes11]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes12]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes13]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes14]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes15]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes16]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes17]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes18]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes19]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes1]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes2]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes3]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes4]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes5]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes6]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes7]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes8]', 'tests/test_media_playback.py::test_strict_mutation_fields[changes9]', 'tests/test_media_playback.py::test_two_households_and_two_devices_are_independent', 'tests/test_media_trip_playback.py::test_atomic_schema_requires_transaction_and_rollback_keeps_original_tables', 'tests/test_media_trip_playback.py::test_audit_failure_rolls_back_selection_receipt_and_progress', 'tests/test_media_trip_playback.py::test_dashboard_tv_does_not_scan_album_and_selection_query_has_no_blobs', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[coordinates_hidden]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[journey_broken]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[journey_deleted]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[media_grant]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[media_source]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[place_deleted]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[place_private]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[route_deleted]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[route_moved]', 'tests/test_media_trip_playback.py::test_fresh_source_changes_never_broaden_scope[route_private]', 'tests/test_media_trip_playback.py::test_parallel_start_has_one_effect_and_durable_owner_receipt[False]', 'tests/test_media_trip_playback.py::test_parallel_start_has_one_effect_and_durable_owner_receipt[True]', 'tests/test_media_trip_playback.py::test_preview_start_scope_persist_receipt_and_explicit_exit', 'tests/test_media_trip_playback.py::test_receipt_owner_only_device_deleted_and_quota_replay', 'tests/test_media_trip_playback.py::test_route_only_private_route_denied_gaps_and_no_inferred_route', 'tests/test_media_trip_playback.py::test_strict_preview_input_and_tv_csrf_denial[payload0]', 'tests/test_media_trip_playback.py::test_strict_preview_input_and_tv_csrf_denial[payload1]', 'tests/test_media_trip_playback.py::test_strict_preview_input_and_tv_csrf_denial[payload2]', 'tests/test_media_trip_playback.py::test_strict_preview_input_and_tv_csrf_denial[payload3]', 'tests/test_media_trip_playback.py::test_strict_preview_input_and_tv_csrf_denial[payload4]', 'tests/test_media_trip_playback.py::test_strict_preview_input_and_tv_csrf_denial[payload5]', 'tests/test_media_trip_playback.py::test_token_session_device_revision_source_binding_and_empty_preview', 'tests/test_media_trip_playback.py::test_two_signed_households_cannot_read_or_start_original_scope', 'tests/test_media_trip_playback.py::test_unknown_old_start_and_new_preview_share_cas_in_both_orders[False]', 'tests/test_media_trip_playback.py::test_unknown_old_start_and_new_preview_share_cas_in_both_orders[True]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[auth_version-control]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[auth_version-preview]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[auth_version-receipt]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[expired-control]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[expired-preview]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[expired-receipt]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[session-control]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[session-preview]', 'tests/test_media_trip_playback_sessions.py::test_member_read_discards_response_when_actual_session_changes[session-receipt]', 'tests/test_media_trip_playback_sessions.py::test_start_session_expires_after_audit_rolls_back_all_writes', 'tests/test_media_trip_playback_sessions.py::test_tv_rechecks_fresh_snapshot_before_releasing_projection[device]', 'tests/test_media_trip_playback_sessions.py::test_tv_rechecks_fresh_snapshot_before_releasing_projection[route]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[account-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[account-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[deleted-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[deleted-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[device-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[device-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[expired-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[expired-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[grant-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[grant-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[membership-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[membership-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[private-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[private-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[reauth-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[reauth-journey]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[scope-all]', 'tests/test_tv_playback_projection.py::test_actual_revoke_between_snapshots_discards_old_item_and_stays_revoked[scope-journey]', 'tests/test_tv_playback_projection.py::test_get_metadata_uses_no_media_blob_in_either_snapshot[photo-all]', 'tests/test_tv_playback_projection.py::test_get_metadata_uses_no_media_blob_in_either_snapshot[photo-journey]', 'tests/test_tv_playback_projection.py::test_get_metadata_uses_no_media_blob_in_either_snapshot[video-all]', 'tests/test_tv_playback_projection.py::test_get_metadata_uses_no_media_blob_in_either_snapshot[video-journey]', 'tests/test_tv_playback_projection.py::test_local_source_requires_current_sealed_authority_without_blobs[all]', 'tests/test_tv_playback_projection.py::test_local_source_requires_current_sealed_authority_without_blobs[journey]', 'tests/test_tv_trip_capacity.py::test_four_wsgi_reads_2000_media_100_stops_no_large_blob']

@pytest.fixture
def migration_record(tmp_path, candidate):
    value = deepcopy(candidate); inputs_root = tmp_path/'input'; run = tmp_path/'run'
    meta = value['metadata']; tool = 'deploy/tv_trip_migration_linux_probe.py'
    sources = {n: (ROOT/n).read_bytes() for n in prepare.MIGRATION_CLOSURE}
    sources[tool] = b'# Synthetic migration-probe source for receipt validator tests only.'
    meta['sourceFiles'][tool] = sha(sources[tool])
    files = {'release/'+n: previous.old.write(inputs_root/'release'/n, raw) for n, raw in sources.items()}
    modules = {n:h for n,h in meta['runtimeFiles'].items() if '/' not in n}
    inputs = {'kind':'tv-trip-migration-linux-input-v1', 'sourceHead':'b'*40, 'tree':'c'*40,
        'runtimeSourceHead':prepare.MIGRATION_RUNTIME_SOURCE, 'historicalHead':package.INSTALLED_SOURCE,
        'productionOperations':False, 'runtimeFiles':modules, 'sourceFiles':{n:sha(raw) for n,raw in sources.items()}, 'files':files}
    ihash = previous.old.write(inputs_root/'input.json', inputs)
    group = {'verified':True,'households':2,'databases':3,'logicalSha256':'d'*64}
    stages = {n:dict(group) for n in prepare.MIGRATION_STAGES}
    stages['verify'].update(uid=10001,runtime=modules)
    for n in ('rollback75','partial','restore77'): stages[n]['completeGroupRestored']=True
    stages['partial'].update(replayRejected=True,partialTableCounts={'household.sqlite3':77,'child.sqlite3':75})
    for n in ('startup','restart'): stages[n]['initialized']=True
    stages['populate77'].update(populated=True,rowsPerNewTable=dict(prepare.POPULATED_ROWS))
    original = previous.old.write(run/'proof/synthetic-original.json', stages)
    built = {'imageId':'sha256:'+'e'*64}
    result = {'passed':True,'syntheticOnly':True,'productionAccess':False,'imageId':built['imageId'],
        'inputSha256':ihash,'stages':stages,'proofHashes':{'synthetic-original.json':original},'commands':[{'exitCode':0}]}
    rhash = previous.old.write(run/'result.json', result)
    spec = {'input':{'root':str(inputs_root),'sha256':ihash},'run':{'root':str(run),'sha256':rhash}}
    return spec,value,built,inputs,result


@pytest.mark.parametrize('fault', [None,'image','runtime','historical','source-closure','missing-stage','one-household',
    'partial','replay','incomplete-restore','empty77','logical','no-startup','command','original'])
def test_new_migration_requires_bound_actual_runtime_and_complete77_contract(migration_record, fault):
    spec,value,built,inputs,result = migration_record
    if fault == 'image': result['imageId']='sha256:'+'f'*64
    if fault == 'runtime': inputs['runtimeFiles']['media_trip_playback.py']='0'*64
    if fault == 'historical': inputs['historicalHead']='0'*40
    if fault == 'source-closure': inputs['sourceFiles']['deploy/check_journey_finance_migration.py']='0'*64
    if fault == 'missing-stage': del result['stages']['partial']
    if fault == 'one-household': result['stages']['seed']['households']=1
    if fault == 'partial': result['stages']['partial']['partialTableCounts']['child.sqlite3']=71
    if fault == 'replay': result['stages']['partial']['replayRejected']=False
    if fault == 'incomplete-restore': result['stages']['restore77']['completeGroupRestored']=False
    if fault == 'empty77': result['stages']['populate77']['rowsPerNewTable']['media_playback_journeys']=0
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


@pytest.fixture
def capacity_record(tmp_path,candidate):
    # Receipt parser fixture only, never presented as measured Linux evidence.
    root=tmp_path/'validation';built={'imageId':'sha256:'+'e'*64}
    cgroup={'memory.max':str(384*1024**2),'memory.swap.max':'0','memory.peak':'200000000',
            'memory.events':'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0'}
    route={'stops':[{'state':'available'} for _ in range(100)]}
    from test_tv_trip_capacity import digest
    requests=[]
    for number,(method,url) in enumerate([('GET','/api/media-tv/playback'),('GET','/api/media-tv/playback'),
        ('GET','/api/media-playback/devices/'+'1'*24),('POST','/api/media-playback/devices/'+'2'*24+'/journey-preview')]):
        body={'deviceId':str(number+1)*24,'photoCount':2000,'journeyReview':{'route':route}}
        requests.append({'method':method,'path':url,'status':200,'bytes':50000,'started':1.0,'finished':2.0,
                         'body':body,'bodySha256':digest(body)})
    proof={'kind':'tv-trip-capacity-v1','passed':True,'linux':True,'failure':None,
        'fixture':{'media':2000,'sharedStops':100,'televisions':2,'creation':'one-real-photo-confirmation-then-synthetic-encrypted-storage-fill'},
        'bookkeepingNormalization':['member_sessions.last_seen_at'],'deniedBlobReads':[],'scanCount':8,
        'databaseBefore':{'media_items':'a'*64},'databaseAfter':{'media_items':'a'*64},'requests':requests,
        'fourRequestOverlapSeconds':1.0,'processPeakRssBytes':190000000,
        'loaded':{n:{'path':'/app/'+n+'.py','sha256':candidate['metadata']['runtimeFiles'][n+'.py']} for n in
            ('media_trip_playback','media_playback','household_media','journey_routes','journey_places')},
        'cgroupBefore':dict(cgroup),'cgroupAfter':dict(cgroup),'cgroupFinal':dict(cgroup)}
    record={'imageId':built['imageId'],'sourceHead':candidate['metadata']['sourceHead'],'tree':candidate['metadata']['tree'],
            'allPassed':True,'containerExitCode':0,'evidence':{}}
    return root,built,proof,record,candidate


@pytest.mark.parametrize('fault',[None,'missing','image','windows','blob-read','database','overlap','same-tv','response',
                                  'max-event','oom','swap','limit','runtime','proof-bytes'])
def test_capacity_admission_requires_actual_linux_bounded_four_reads(capacity_record,fault):
    root,built,proof,record,value=capacity_record
    if fault=='image':record['imageId']='sha256:'+'f'*64
    if fault=='windows':proof['linux']=False
    if fault=='blob-read':proof['deniedBlobReads']=[['media_items','preview_cipher']]
    if fault=='database':proof['databaseAfter']['media_items']='b'*64
    if fault=='overlap':proof['requests'][0]['finished']=0.5
    if fault=='same-tv':proof['requests'][1]['body']['deviceId']=proof['requests'][0]['body']['deviceId']
    if fault=='response':proof['requests'][0]['body']['photoCount']=1999
    if fault=='max-event':proof['cgroupFinal']['memory.events']='max 1\noom 0\noom_kill 0'
    if fault=='oom':proof['cgroupFinal']['memory.events']='max 0\noom 1\noom_kill 1'
    if fault=='swap':proof['cgroupFinal']['memory.swap.max']='1'
    if fault=='limit':proof['cgroupFinal']['memory.max']=str(1024*1024**2)
    if fault=='runtime':proof['loaded']['media_playback']['sha256']='0'*64
    from test_tv_trip_capacity import digest
    for request in proof['requests']:request['bodySha256']=digest(request['body'])
    record['evidence']['proof/tv-trip-capacity.json']=previous.old.write(root/'proof/tv-trip-capacity.json',proof)
    if fault=='missing':record['evidence']={}
    if fault=='proof-bytes':(root/'proof/tv-trip-capacity.json').write_text('{}')
    spec={'root':str(root),'sha256':previous.old.write(root/'validation.json',record)}
    if fault:
        with pytest.raises(ReleaseError):prepare.verify_capacity(spec,value,built)
    else:assert prepare.verify_capacity(spec,value,built)['imageId']==built['imageId']


def test_retained_parent_requires_exact_original_identity_before_read(candidate):
    for name in ('package','build','plan'):
        spec={'package':{'sha256':package.OLD_PACKAGE},'build':{'sha256':prepare.PARENT_BUILD_SHA256},
              'plan':{'path':'/synthetic/plan.json','sha256':prepare.PARENT_PLAN_SHA256}}
        spec[name]['sha256']='0'*64
        with pytest.raises(ReleaseError,match='retained_assistant_list_identity_changed'):
            prepare.resource_evidence({'retainedAssistantList':spec},candidate,{})
