"""75/9 source-update routing and stopped preservation; no Docker or production."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from deploy import build_assistant_list_release as package
from deploy import prepare_assistant_list_activation as prepare
from deploy import activate_assistant_list_release as entry
from deploy import membership_release_package as policy
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import ReleaseError, read, sha
import test_local_photo_release as previous

ROOT = Path(__file__).resolve().parents[1]


def test_closed_profile_keeps_five_services_and_has_no_migration():
    assert policy.baseline_values(package.BASELINE) == (package.KIND, package.PARENT_IMAGE, package.OLD_MANIFEST)
    assert prepare.shared._profile(prepare.MODE) is prepare
    assert package.SCHEMA_BEFORE == package.SCHEMA_AFTER == (75, 9)
    assert policy.fixed_files(package.BASELINE)['Dockerfile'] == package.DOCKER_AFTER
    with pytest.raises(ReleaseError):
        prepare.shared._profile('assistant-list-source-update-other')
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
    assert 'activate_assistant_list_release' in c.data_actions['verify-rollback']
    assert r.started == ['app', 'app', 'decoder', 'sync', 'media', 'web']
    assert r.timer and c.release.name.startswith('assistant-list-75-')
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
