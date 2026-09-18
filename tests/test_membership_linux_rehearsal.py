"""Local contract checks only; never claim these execute Docker or migrations."""
import ast
import copy
import json
from pathlib import Path
import sys

import pytest

from deploy import membership_linux_rehearsal as rehearsal
from deploy import membership_release_controller as controller
from deploy import membership_migration as migration

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:' + 'a' * 64


def test_exact_controller_programs_and_same_restart_callback():
    programs = rehearsal.controller_programs((ROOT / 'deploy/membership_release_controller.py').read_bytes())
    for name in ('DATA_PREFIX', 'BACKUP_PROGRAM', 'WARM_PROGRAM', 'RUNTIME_PROGRAM'):
        assert programs[name] == getattr(controller, name)
    warm = next(n for n in ast.parse(controller.WARM_PROGRAM).body if isinstance(n, ast.FunctionDef))
    actual = next(n for n in ast.parse(programs['RESTART_PROGRAM']).body if isinstance(n, ast.FunctionDef))
    assert ast.dump(warm) == ast.dump(actual)
    assert "data.check_current_after(proof/'attempt',root)" in programs['CHECK_PROGRAM']
    ast.parse(rehearsal.SEED_PROGRAM)


@pytest.mark.parametrize('change', [
    lambda raw: raw.replace(b'DATA_PREFIX =', b'DIFFERENT_PREFIX =', 1),
    lambda raw: raw + b'\nDATA_PREFIX="different"\n',
    lambda raw: raw.replace(b'def warm():', b'def other_name():', 1),
])
def test_incomplete_or_ambiguous_controller_contract_rejected(change):
    with pytest.raises(ValueError):
        rehearsal.controller_programs(change((ROOT / 'deploy/membership_release_controller.py').read_bytes()))


def test_only_exclusive_output_and_readonly_source_mounts(tmp_path):
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    output = rehearsal.new_output(tmp_path / 'attempt', candidate)
    for action, data_write, include_source in [('seed', True, False), ('warm', True, True), ('check', False, True)]:
        params = rehearsal.container_parameters(IMAGE, action, candidate / 'source', output,
                                                data_write=data_write, include_source=include_source)
        mounts = {target: (host, readonly) for host, target, readonly in params['mounts']}
        assert mounts['/data'] == (output / 'data', not data_write)
        assert mounts['/proof'] == (output / 'proof', False)
        assert set(mounts) == ({'/data', '/proof', '/release'} if include_source else {'/data', '/proof'})
        if include_source:
            assert mounts['/release'] == (candidate / 'source', True)
        env = dict(params['env'])
        assert env['SECRET_KEY'] == 'membership-linux-rehearsal-synthetic-only'
        assert env['OPENAI_API_KEY'] == env['NVIDIA_API_KEY'] == ''
        assert env['DATA_DIR'] == '/data' and params['writable'] is True
    with pytest.raises(ValueError, match='new output'):
        rehearsal.new_output(output, candidate)
    with pytest.raises(ValueError, match='overlaps'):
        rehearsal.new_output(candidate / 'nested', candidate)


@pytest.mark.parametrize('image', ['family-dashboard-app:latest', '09f583', 'sha256:' + 'z' * 64])
def test_tags_and_nonimmutable_images_refused(image):
    with pytest.raises(ValueError, match='immutable'):
        rehearsal.image_id(image)


def synthetic_proof():
    names = ['platform.sqlite3', 'household.sqlite3', 'spaces/' + '1' * 24 + '/household.sqlite3']
    before, after = {}, {}
    for name in names:
        platform = name == 'platform.sqlite3'
        old = migration.BASE_PLATFORM_TABLES if platform else migration.BASE_HOUSEHOLD_TABLES
        added = migration.NEW_PLATFORM_TABLES if platform else migration.NEW_HOUSEHOLD_TABLES
        before[name] = {'membershipPhase': 'before', 'tables': {n: {} for n in old}}
        after[name] = {'membershipPhase': 'after', 'tables': {n: {} for n in old | added}}
    return {'seed.json': {'synthetic': True, 'households': 2, 'databases': 3, 'platformTables': 2,
                'householdTables': {n: 58 for n in names[1:]}, 'roleCounts': {n: {'admin': 1, 'member': 1} for n in names[1:]}},
            'before.json': {'households': 2, 'databases': before},
            'attempt/after.json': {'households': 2, 'databases': after},
            'attempt/result.json': {'state': 'completed', 'households': 2, 'databases': 3,
                                   'comparisons': {n: {'verified': True} for n in names}, 'afterLogicalSha256': 'a' * 64},
            'after-restart.json': {'verified': True, 'households': 2, 'databases': 3, 'logicalSha256': 'a' * 64}}


def save_proof(folder, values):
    for name, value in values.items():
        path = folder / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')


def test_summary_requires_full_three_database_chain(tmp_path):
    save_proof(tmp_path, synthetic_proof())
    result = rehearsal.proof_summary(tmp_path)
    assert result['households'] == 2 and result['databases'] == result['preservationCompared'] == 3
    assert result['householdTables'] == [58, 61] and result['platformTables'] == [2, 9]


@pytest.mark.parametrize('change', [
    lambda p: p['seed.json'].update(synthetic=False),
    lambda p: p['seed.json']['roleCounts'].update({'household.sqlite3': {'admin': 2}}),
    lambda p: p['attempt/after.json']['databases'].pop('household.sqlite3'),
    lambda p: p['attempt/after.json']['databases']['household.sqlite3']['tables'].pop('membership_operations'),
    lambda p: p['attempt/result.json'].update(state='started'),
    lambda p: p['attempt/result.json']['comparisons']['household.sqlite3'].update(verified=False),
    lambda p: p['after-restart.json'].update(logicalSha256='b' * 64),
    lambda p: p.update({'attempt/failed.json': {'state': 'failed'}}),
])
def test_partial_or_failed_proof_never_accepted(tmp_path, change):
    values = copy.deepcopy(synthetic_proof()); change(values); save_proof(tmp_path, values)
    with pytest.raises(ValueError):
        rehearsal.proof_summary(tmp_path)


def test_nonlinux_entry_rejects_before_any_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(rehearsal.build, 'Executor', lambda *_: pytest.fail('Docker must not be created'))
    with pytest.raises(ValueError, match='Linux root'):
        rehearsal.rehearse(tmp_path, 'a' * 64, IMAGE, tmp_path / 'attempt')
    assert not (tmp_path / 'attempt').exists()
