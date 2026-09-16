"""55-table preservation with real disposable two-household operation receipts.

Private historical operator inputs are inspected by the explicit local CLI below,
not silently skipped or replaced by mock operator success in pytest.
"""
from contextlib import closing
import ast
import copy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import app as app_module
from deploy.travel_release import prepare as adapter
from deploy import check_investment_operation_migration as schema_check
from deploy.backup import backup_all
from test_finance_receipt_migration import login, copy_backup_group_to_new_root


def preservation():
    namespace = {'verify_current': schema_check.verify_current}
    exec(adapter.PRESERVATION_FUNCTION, namespace)
    return namespace['verify_preserved']


@pytest.fixture
def populated(tmp_path, monkeypatch):
    def offline(*_args, **_kwargs):
        raise AssertionError('Synthetic preservation tests must not use the network')
    monkeypatch.setattr(socket.socket, 'connect', offline)
    monkeypatch.setattr(socket, 'create_connection', offline)
    root = tmp_path / 'data'
    config = {'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'synthetic-travel-preservation',
              'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
              'MEMBER1_PASSWORD': 'synthetic-receipt-password', 'MEMBER2_PASSWORD': 'synthetic-receipt-password',
              'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '',
              'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local', 'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''}
    application = app_module.create_app(config)
    client, headers = login(application)
    invitation = client.post('/api/spaces/invitations', json={}, headers=headers)
    assert invitation.status_code == 201
    response = client.post('/api/spaces/redeem', json={'invitation': invitation.json['invitation'],
        'name': '合成保全家庭', 'slug': 'travel-preservation-two', 'MEMBER1_PASSWORD': 'synthetic-receipt-password',
        'MEMBER2_PASSWORD': 'synthetic-receipt-password'}, headers=headers)
    assert response.status_code == 201, response.json
    platform = application.extensions['household_platform']
    receipts = {}
    for entry in platform.households():
        client, headers = login(platform.child(entry))
        payload = {'name': '已删除的合成持仓', 'institution': '合成机构', 'assetType': '基金', 'currency': 'CNY',
                   'quantity': '1.25', 'cost': '123.45', 'value': None, 'asOf': '2026-09-17', 'note': '仅测试', 'requestId': 'a' * 32}
        created = client.post('/api/finance-hub/investments', json=payload, headers=headers)
        assert created.status_code == 201, created.json
        deleted = client.delete('/api/finance-hub/investments/' + created.json['id'],
            json={'requestId': 'b' * 32, 'revision': created.json['revision']}, headers=headers)
        assert deleted.status_code == 200 and deleted.json['deleted']
        receipts[entry['id']] = client.get('/api/finance-hub/investments/operations/' + 'b' * 32).json
    before = schema_check.snapshot(root)
    assert schema_check.verify_current(before, schema_check.schema_definition())['receiptRows'] == 4
    return root, config, before, receipts


def test_nonempty_receipts_backup_and_new_factory_keep_complete_group(populated):
    root, config, before, receipts = populated
    schema = schema_check.schema_definition()
    backup = backup_all(root)
    assert schema_check.validate_backup(root, before, backup)['databases'] == 3
    assert preservation()(before, schema_check.snapshot(root), schema)['receiptRows'] == 4
    platform = app_module.create_app(config).extensions['household_platform']
    for entry in platform.households():
        platform.child(entry)
    result = preservation()(before, schema_check.snapshot(root), schema)
    assert result == {'originalTablesPreserved': 55, 'newTables': 0, 'households': 2, 'receiptRows': 4,
                      'allRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}
    # Authentication may write audit/session state, so perform receipt readback after the startup comparison.
    for entry in platform.households():
        client, _ = login(platform.child(entry))
        assert client.get('/api/finance-hub/investments/operations/' + 'b' * 32).json == receipts[entry['id']]


@pytest.mark.parametrize('damage', ['receipt', 'schema', 'sequence', 'registry', 'household'])
def test_exact_group_rejects_actual_drift(populated, damage):
    root, _, before, _ = populated
    if damage == 'household':
        after = copy.deepcopy(before); after['households'].pop(next(iter(after['households'])))
    else:
        target = root / ('platform.sqlite3' if damage == 'registry' else 'household.sqlite3')
        with closing(sqlite3.connect(target)) as con:
            if damage == 'receipt': con.execute("UPDATE hub_investment_operations SET result='{}' WHERE request_id=?", ('b' * 32,))
            elif damage == 'schema': con.execute('CREATE INDEX synthetic_unreviewed_index ON users(name)')
            elif damage == 'sequence': con.execute('UPDATE sqlite_sequence SET seq=seq+1')
            else: con.execute("UPDATE households SET name='synthetic drift' WHERE id='default'")
            con.commit()
        after = schema_check.snapshot(root)
    with pytest.raises(RuntimeError, match='changed'):
        preservation()(before, after, schema_check.schema_definition())


def test_complete_closed_backup_restores_populated_operation_rows(populated, tmp_path):
    root, _, before, _ = populated
    backup = backup_all(root)
    destination = tmp_path / 'recovered'
    copy_backup_group_to_new_root(root, backup, destination)
    from deploy.rehearse_restore import documented_programs
    restore, _ = documented_programs(Path(__file__).resolve().parents[1])
    restore = adapter.replace(restore, "root = Path('/data').resolve(strict=True)", 'root = Path(' + repr(str(destination)) + ').resolve(strict=True)')
    from unittest.mock import patch
    with patch.object(sys, 'argv', ['synthetic-restore', backup['manifest'], 'platform', 'default']):
        exec(compile(restore, '<synthetic-travel-restore>', 'exec'), {'__name__': '__main__'})
    result = schema_check.verify_restore(before, schema_check.snapshot(destination), schema_check.schema_definition())
    assert result['receiptRows'] == 4 and result['completeGroupRestored']
    assert schema_check.snapshot(root) == before


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'digest'])
def test_incomplete_or_changed_backup_is_rejected(populated, damage):
    root, _, before, _ = populated
    backup = backup_all(root)
    path = root / 'backups' / backup['manifest']
    value = json.loads(path.read_text())
    if damage == 'missing': value['snapshots'].pop()
    elif damage == 'duplicate': value['snapshots'].append(copy.deepcopy(value['snapshots'][0]))
    else: value['snapshots'][0]['sha256'] = '0' * 64
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError): schema_check.validate_backup(root, before, backup)
    assert schema_check.snapshot(root) == before


@pytest.mark.parametrize('source', ['migrate(root)', 'initialize_database(root, sql)', 'verify_addition(a,b,c)',
                                   'create_app(config)', "program='con.executescript(sql)'", "program=\"con.execute('CREATE TABLE x(y)')\""])
def test_recursive_generated_syntax_rejects_migration_or_ddl(source):
    with pytest.raises(RuntimeError): adapter.verify_generated(source, 'synthetic.py')


def test_readonly_sql_and_embedded_snapshot_checks_are_accepted():
    adapter.verify_generated("program=\"con.execute('SELECT id FROM households')\"", 'synthetic.py')
    adapter.verify_generated(adapter.PRESERVATION_FUNCTION, 'synthetic.py')


def test_docker_contract_is_exact_bytes_including_line_endings():
    namespace = {'need': adapter.need}; exec(adapter.DOCKER_CONTRACT, namespace)
    check = namespace['verify_docker_delta']; original = b'FROM synthetic\r\nCOPY app.py ./\n'
    check(original, original)
    for altered in [original.replace(b'\r\n', b'\n'), original + b'RUN echo changed\n', original.replace(b'app.py', b'extra.py')]:
        with pytest.raises(RuntimeError): check(original, altered)


def test_pinned_inputs_refuse_changed_bytes_and_paths(tmp_path, monkeypatch):
    raw = b'# synthetic pinned\r\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    assert adapter.read_sources(tmp_path) == {'source.py': b'# synthetic pinned\n'}
    (tmp_path / 'source.py').write_bytes(raw.replace(b'\r\n', b'\n'))
    with pytest.raises(RuntimeError, match='checksum'): adapter.read_sources(tmp_path)
    for path in [Path('relative'), tmp_path / '..' / 'escape']:
        with pytest.raises(RuntimeError): adapter.safe_path(path, exists=False)


def test_exclusive_confined_output_is_unbound(tmp_path, monkeypatch):
    raw = b'# source\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    monkeypatch.setattr(adapter, 'adapt', lambda *_: {'operators/build.py': b'raise RuntimeError("unbound")\n'})
    output = tmp_path / 'expo-travel-tools-synthetic'
    result = adapter.prepare(tmp_path, output)
    assert result['schemaChange'] is False and result['bound'] is False
    assert result['householdTablesBefore'] == result['householdTablesAfter'] == 55
    assert result['expectedTestCount'] is None and result['productionOperations'] is False
    with pytest.raises(RuntimeError, match='exists'): adapter.prepare(tmp_path, output)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path.parent / 'expo-travel-tools-escape')


def test_generation_rechecks_sources_before_creating_output(tmp_path, monkeypatch):
    raw = b'# source\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    def changed(*_):
        (tmp_path / 'source.py').write_bytes(b'# drift\n'); return {}
    monkeypatch.setattr(adapter, 'adapt', changed)
    output = tmp_path / 'expo-travel-tools-synthetic'
    with pytest.raises(RuntimeError, match='checksum'): adapter.prepare(tmp_path, output)
    assert not output.exists()


def test_freeze_rejects_duplicate_outside_and_oversized_input(tmp_path):
    root = tmp_path / 'access'; root.mkdir()
    outside = tmp_path / 'outside.json'; outside.write_text('{}')
    with pytest.raises(RuntimeError): adapter.freeze_config(outside, root, {})
    large = root / 'large.json'; large.write_bytes(b'x' * 2_000_001)
    with pytest.raises(RuntimeError): adapter.freeze_config(large, root, {})
    duplicate = root / 'duplicate.json'; duplicate.write_text('{"main":"a","main":"b"}')
    with pytest.raises(RuntimeError, match='Duplicate'): adapter.freeze_config(duplicate, root, {})


def check_pinned_local_operators(source_root, git_repo, git_revision):
    """Read fixed private originals, then exercise generated code only in a tempdir.

    Actual entrypoints execute with all process/network methods blocked. Their
    missing binding must fail before any such action. No production command runs.
    """
    import io
    import importlib.util
    import subprocess
    import tarfile
    import tempfile
    from unittest.mock import patch
    inputs = adapter.read_sources(source_root)
    archive = adapter.safe_path(source_root / adapter.BASE / 'package/release.tar.gz')
    raw = archive.read_bytes(); assert adapter.sha(raw) == adapter.OLD_ARCHIVE
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as packed:
        members = [row for row in packed.getmembers() if row.name == 'Dockerfile']
        assert len(members) == 1 and members[0].isfile() and members[0].size < 100_000
        old_docker = packed.extractfile(members[0]).read()
    assert re_full_sha(git_revision)
    new_docker = subprocess.run(['git', '-C', str(adapter.safe_path(git_repo)), 'show', git_revision + ':Dockerfile'], check=True, capture_output=True).stdout
    def deny(*_args, **_kwargs): raise AssertionError('Unbound operator attempted an external action')
    with tempfile.TemporaryDirectory(prefix='travel-operator-guards-') as folder:
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            target = access / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((source_root / name).read_bytes())
        output = access / 'expo-travel-tools-synthetic'; report = adapter.prepare(access, output)
        operator_dir = output / 'operators'
        def module(name, path):
            spec = importlib.util.spec_from_file_location(name, path); value = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(value); return value
        contract = module('travel_contract_test', operator_dir / 'expo_contract.py')
        contract.verify_docker_delta(old_docker, new_docker)
        source = (operator_dir / 'activate.py').read_text(encoding='utf-8')
        assert "report.pop('productionWrites', None)" in source and 'schemaChange=False' in source
        assert not any(term in source for term in ('after-migration.json', 'migrationResult', 'newTableEmpty', 'migrate('))
        assert 'householdTablesBefore=55,householdTablesAfter=55,schemaChange=False' in (operator_dir / 'stage.py').read_text()
        guards = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == 'need' and node.args
                  and isinstance(node.args[0], ast.Compare) and isinstance(node.args[0].left, ast.Name)
                  and node.args[0].left.id == 'preservation']
        assert len(guards) == 1
        guard = compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(value=guards[0])], type_ignores=[])), '<actual-preservation-guard>', 'exec')
        expected = {'originalTablesPreserved': 55, 'newTables': 0, 'households': 2, 'receiptRows': 4,
                    'allRowsSchemaAndSequencesPreserved': True, 'registryPreserved': True}
        reference = {'households': {uid: {'tables': {'hub_investment_operations': {'count': 2}}} for uid in ['default', 'second']}}
        rejected = [{'originalTablesPreserved': 54}, {'originalTablesPreserved': 56}, {'newTables': 1},
                    {'households': 1}, {'receiptRows': 0}, {'allRowsSchemaAndSequencesPreserved': False}, {'registryPreserved': False}]
        exec(guard, {'need': adapter.need, 'before': reference, 'preservation': expected})
        for altered in rejected:
            with pytest.raises(RuntimeError, match='Unexpected preservation result'):
                exec(guard, {'need': adapter.need, 'before': reference, 'preservation': {**expected, **altered}})
        checked = []
        old_modules = {name: sys.modules.get(name) for name in ('expo_contract', 'ops_common')}
        try:
            sys.modules['expo_contract'] = contract
            common = module('travel_common_test', operator_dir / 'ops_common.py'); sys.modules['ops_common'] = common
            common.CANDIDATE = operator_dir; common.BINDING_PATH = operator_dir / 'operator-bindings.json'
            common.host_guard = lambda: None  # Exercise the actual absent-binding guard beyond host/path checks.
            with patch('subprocess.run', deny), patch('subprocess.Popen', deny), patch('subprocess.check_output', deny), patch('socket.create_connection', deny), patch.object(socket.socket, 'connect', deny):
                for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                    value = module('travel_' + name.removesuffix('.py'), operator_dir / name)
                    args = [str(operator_dir / name)]
                    if name == 'post_readback.py': args += ['--reviewed-sha256', adapter.sha((operator_dir / name).read_bytes())]
                    with patch.object(sys, 'argv', args), pytest.raises(RuntimeError, match='unbound'):
                        value.main()
                    checked.append(name)
                for name in ('prepare-package.py', 'bind-release.py'):
                    value = module('travel_' + name.replace('-', '_').removesuffix('.py'), output / name)
                    missing = output / 'absent.json'
                    args = [str(output / name), '--freeze', str(missing)] if name == 'prepare-package.py' else [str(output / name), '--operator-review', str(missing), '--operator-review-sha256', 'a' * 64]
                    with patch.object(sys, 'argv', args), pytest.raises(RuntimeError): value.main()
                    checked.append(name)
        finally:
            for name, previous in old_modules.items():
                if previous is None: sys.modules.pop(name, None)
                else: sys.modules[name] = previous
        for name, digest in report['generatedHashes'].items():
            raw = (output / name).read_bytes(); assert adapter.sha(raw) == digest; adapter.verify_generated(raw, name)
        return {'pinnedSources': adapter.PINNED, 'generatedHashes': report['generatedHashes'], 'unboundRejected': checked,
                'actualDockerArchiveSha256': adapter.OLD_ARCHIVE, 'gitRevision': git_revision,
                'actualDockerIdentical': old_docker == new_docker, 'recursiveGeneratedSyntaxVerified': True,
                'generatedPreservationGuard': {'accepted': expected, 'rejectedChanges': rejected},
                'productionOperations': False, 'readOnlyGitBlobInput': True, 'unboundNetworkOrProcessActions': False}


def re_full_sha(value):
    import re
    return re.fullmatch('[0-9a-f]{40}', value)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--git-repo', type=Path, required=True)
    parser.add_argument('--git-revision', required=True)
    args = parser.parse_args()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    print(json.dumps(check_pinned_local_operators(args.source_root, args.git_repo, args.git_revision), indent=2))
