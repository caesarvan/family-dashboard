"""Role-aware no-DDL guards; optional private CLI uses only temporary generated files."""
from __future__ import annotations

import ast
import copy
import difflib
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
from unittest.mock import patch

import pytest

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy.finance_column_mapping_release import prepare as adapter
from deploy.git_blobs import read_git_blobs
from tests import test_expo_trip_recap_release as shared
from tests import test_household_members_release as members


def test_scope_and_reviewed_sources_are_exact(monkeypatch):
    monkeypatch.setattr(adapter, 'FINANCE_SOURCE_SHA256', 'a'*64)
    assert len(adapter.REQUIRED_TESTS) == 15
    assert set(adapter.UNCHANGED) == (set(adapter.previous.UNCHANGED) - {'finance_hub.py'}) | {
        'app.py', 'household_members.py', 'Dockerfile', 'deploy/prepare_release.py',
        'deploy/check_household_members_migration.py'}
    assert set(adapter.BACKEND_UNCHANGED) == (set(adapter.previous.BACKEND_UNCHANGED) - {'finance_hub.py'}) | {'app.py', 'household_members.py'}
    assert adapter.LOCAL_BUILD_SOURCES == adapter.previous.LOCAL_BUILD_SOURCES
    assert not (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) & set(adapter.UNCHANGED)
    assert not adapter.REQUIRED_CHANGED & adapter.REQUIRED_ADDED
    assert 'financial_files.py' in adapter.UNCHANGED
    assert len(adapter.PINNED) == len(set(adapter.PINNED.values())) == 9
    guard = compile(adapter.source_guard().replace('    need(', 'need('), '<source pins>', 'exec')
    pins = adapter.reviewed_sources()
    exec(guard, {'manifest': pins, 'need': adapter.need})
    for path in pins:
        for replacement in (None, '0'*64):
            with pytest.raises(RuntimeError):
                exec(guard, {'manifest': {**pins, path: replacement}, 'need': adapter.need})


@pytest.mark.parametrize('pin', [None, '', '0'*63, 'A'*64, True])
def test_missing_or_malformed_review_pin_creates_no_output(tmp_path, monkeypatch, pin):
    monkeypatch.setattr(adapter, 'FINANCE_SOURCE_SHA256', pin)
    output = tmp_path/'finance-column-mapping-tools-synthetic'
    with pytest.raises(RuntimeError, match='reviewed finance source pin'):
        adapter.prepare(tmp_path, output)
    assert not output.exists()


def test_docker_bytes_cannot_change():
    scope = {'need': adapter.need}; exec(adapter.DOCKER_CONTRACT, scope)
    old = b'FROM installed\nUSER dashboard\n'
    scope['verify_docker_delta'](old, old)
    for wrong in (b'', old.replace(b'\n', b'\r\n'), old+b'COPY extra ./\n', old.replace(b'dashboard', b'root')):
        with pytest.raises(RuntimeError): scope['verify_docker_delta'](old, wrong)


def test_original_bytes_paths_and_size_are_strict(tmp_path, monkeypatch):
    with patch.object(members, 'adapter', adapter):
        members.test_pinned_original_bytes_paths_and_size_are_strict(tmp_path, monkeypatch)


def test_generation_is_exclusive_confined_unbound_and_rechecks_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, 'FINANCE_SOURCE_SHA256', 'a'*64)
    raw = b'# original\n'; path = tmp_path/'source.py'; path.write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    monkeypatch.setattr(adapter, 'adapt', lambda *_: {'operators/build.py': b'raise RuntimeError("unbound")\n'})
    output = tmp_path/'finance-column-mapping-tools-synthetic'
    report = adapter.prepare(tmp_path, output)
    assert not report['bound'] and not report['schemaChange'] and not report['productionOperations']
    assert report['profile'] == 'household_members58' and report['expectedTestCount'] is None
    assert report['householdTablesBefore'] == report['householdTablesAfter'] == 58
    assert not (output/'operator-bindings.json').exists()
    for wrong in (output, tmp_path.parent/output.name, tmp_path/'household-members-tools-replay'):
        with pytest.raises(RuntimeError): adapter.prepare(tmp_path, wrong)
    def drift(*_):
        path.write_bytes(b'# changed\n'); return {}
    monkeypatch.setattr(adapter, 'adapt', drift)
    raced = tmp_path/'finance-column-mapping-tools-race'
    with pytest.raises(RuntimeError, match='checksum'): adapter.prepare(tmp_path, raced)
    assert not raced.exists()


@pytest.mark.parametrize('damage', ['outside', 'large', 'duplicate'])
def test_bad_freeze_rejected_before_code_evaluation(tmp_path, damage):
    root = tmp_path/'access'; root.mkdir()
    path = (tmp_path if damage == 'outside' else root)/'freeze.json'
    path.write_bytes(b'x'*2_000_001 if damage == 'large' else b'{"main":1,"main":2}')
    with pytest.raises(RuntimeError):
        adapter.previous.schema_release.freeze_config(path, root, {'prepare-package.py': b'raise AssertionError("not evaluated")'})


@pytest.mark.parametrize('code', ["migrate(Path('/data'),before,backup,schema)", 'verify_baseline(before)',
    'verify_addition(before,after,schema)', 'init_schema(con)', 'initialize_database(a,b)',
    'create_app(config)', "program='con.executescript(sql)'", "program=\"con.execute('ALTER TABLE users ADD x')\""])
def test_no_phase_can_replay_migration_or_mutate_sql(code):
    for phase in ('operators/activate.py', 'operators/post_readback.py'):
        with pytest.raises(RuntimeError): adapter.verify_generated(code, phase)


def test_populated_role_aware_snapshot_backup_and_app_restart(tmp_path, monkeypatch):
    from contextlib import closing
    import sqlite3
    import app
    from deploy import check_household_members_migration as checker
    from deploy.backup import backup_all
    def deny(*_a, **_k): raise AssertionError('No network in synthetic preservation')
    monkeypatch.setattr(socket.socket, 'connect', deny); monkeypatch.setattr(socket, 'create_connection', deny)
    root = tmp_path/'data'
    config = {'TESTING': True, 'DATA_DIR': str(root), 'SECRET_KEY': 'synthetic-mapping-preservation',
        'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
        'MEMBER1_PASSWORD': 'synthetic-only', 'MEMBER2_PASSWORD': 'synthetic-only',
        'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'MICROSOFT_CLIENT_ID': '',
        'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local', 'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''}
    application = app.create_app(config); client = application.test_client()
    assert client.post('/api/login', json={'username': 'member1', 'password': 'synthetic-only'}).status_code == 200
    headers = {'X-CSRF-Token': client.get('/api/me').json['csrf'], 'Origin': 'http://localhost'}
    created = client.post('/api/finance-accounts', json={'requestId': '1'*32, 'revision': 0,
        'name': '虚构账户', 'institution': '合成机构', 'kind': 'asset', 'currency': 'USD',
        'note': '不含真实财务', 'valuation': {'asOf': '2026-09-17', 'amountCents': 0}}, headers=headers)
    assert created.status_code == 201, created.json
    unknown = client.put('/api/finance-accounts/'+created.json['accountId']+'/valuations/2026-09-16',
        json={'requestId': '2'*32, 'revision': 1, 'amountCents': None}, headers=headers)
    assert unknown.status_code == 200, unknown.json
    path = checker.media.checked_path(root, checker.media.relative_database('default'))
    with closing(sqlite3.connect(path)) as con:
        con.execute("UPDATE users SET household_role='member' WHERE id='member2'"); con.commit()
    before = checker.snapshot(root); schema = checker.schema_definition()
    assert checker.verify_current(before, schema)['profile'] == 'household_members58'
    assert before['usersProjection']['default']['roleCounts'] == {'admin': 1, 'member': 1}
    assert before['households']['default']['tables']['finance_account_operations']['count'] == 2
    scope = {'verify_current': checker.verify_current}; exec(adapter.PRESERVATION_FUNCTION, scope)
    verify = scope['verify_preserved']
    assert verify(before, checker.snapshot(root), schema) == dict(originalTablesPreserved=58,
        newTables=0, households=1, allRowsSchemaAndSequencesPreserved=True, registryPreserved=True)
    backup = backup_all(root)
    assert checker.validate_backup(root, before, backup)['databases'] == 2
    app.create_app(config)
    assert checker.snapshot(root) == before  # Existing ordinary role must not be promoted on startup.
    with closing(sqlite3.connect(':memory:')) as original:
        with closing(sqlite3.connect(path)) as con: con.backup(original)
        for sql in ("UPDATE users SET household_role='admin' WHERE id='member2'",
                    "UPDATE finance_accounts SET note='changed'", 'UPDATE finance_account_valuations SET amount_cents=42',
                    'DELETE FROM finance_account_operations', "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'",
                    'CREATE INDEX changed_schema ON finance_accounts(name)'):
            with closing(sqlite3.connect(path)) as con: con.execute(sql); con.commit()
            with pytest.raises(RuntimeError): verify(before, checker.snapshot(root), schema)
            with closing(sqlite3.connect(path)) as con: original.backup(con)
            assert checker.snapshot(root) == before
    changed = copy.deepcopy(before); next(iter(changed['registry']['tables'].values()))['rowsSha256'] = '0'*64
    with pytest.raises(RuntimeError): verify(before, changed, schema)
    changed = copy.deepcopy(before); changed['usersProjection']['default']['rolesSha256'] = '0'*64
    with pytest.raises(RuntimeError): verify(before, changed, schema)


def function_source(code, name):
    node = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(code.decode() if isinstance(code, bytes) else code, node)


def check_pinned_local_operators(source_root, git_repo, git_revision, evidence_dir):
    """Private originals + fixed Git only; generated programs cannot launch process/network."""
    inputs = adapter.read_sources(source_root)
    archive = adapter.safe_path(source_root/adapter.BASE/'package/release.tar.gz').read_bytes()
    assert adapter.sha(archive) == adapter.OLD_ARCHIVE
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as packed:
        raw = packed.extractfile('RELEASE-MANIFEST.json').read()
        assert adapter.sha(raw) == adapter.OLD_MANIFEST
        old = json.loads(raw)['files']; old_docker = packed.extractfile('Dockerfile').read()
    assert re.fullmatch('[a-f0-9]{40}', git_revision)
    names = set(subprocess.check_output(['git', '--no-replace-objects', '-C', str(git_repo), 'ls-tree', '-rz', '--name-only', git_revision]).decode().rstrip('\0').split('\0'))
    pins = adapter.reviewed_sources()
    blobs = read_git_blobs(git_repo, git_revision, sorted({*adapter.UNCHANGED, *pins, 'deploy/prepare_release.py'}))
    for path in adapter.UNCHANGED: assert adapter.sha(blobs[path]) == old[path], path
    for path, digest in pins.items(): assert adapter.sha(blobs[path]) == digest, path
    def deny(*_a, **_k): raise AssertionError('No process or network in generated checks')
    with tempfile.TemporaryDirectory(prefix='mapping-release-') as folder, \
         patch('subprocess.run', deny), patch('subprocess.Popen', deny), patch('subprocess.check_output', deny), \
         patch('socket.create_connection', deny), patch.object(socket.socket, 'connect', deny):
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            target = access/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((source_root/name).read_bytes())
        output = access/'finance-column-mapping-tools-synthetic'
        report = adapter.prepare(access, output)
        generated = {name: (output/name).read_bytes() for name in report['generatedHashes']}
        delta = ''
        for name, raw in generated.items():
            assert adapter.sha(raw) == report['generatedHashes'][name]; adapter.verify_generated(raw, name)
            original = inputs[adapter.BASE+name]
            delta += ''.join(difflib.unified_diff(original.decode().splitlines(True), raw.decode().splitlines(True), fromfile='parent/'+name, tofile='generated/'+name))
        assert generated['operators/validate.py'] == inputs[adapter.BASE+'operators/validate.py']
        for name in ('inspect_backup_group', 'readonly_backup_args', 'backup_names'):
            assert function_source(generated['operators/post_readback.py'], name) == function_source(inputs[adapter.BASE+'operators/post_readback.py'], name)
        shared.check_activation_evidence(generated['operators/post_readback.py'])
        anonymous = members.anonymous_checks(generated['operators/post_readback.py'])
        assert len(set(anonymous)) == 38
        contract = shared.load_module('mapping_contract', output/'operators/expo_contract.py')
        contract.verify_docker_delta(old_docker, blobs['Dockerfile'])
        package = shared.load_module('mapping_package', output/'prepare-package.py')
        selected = package.selected_sources(names, blobs['deploy/prepare_release.py'])
        unsafe = {'.env', 'frontend/.env.local', 'frontend/node_modules/unsafe.js', 'data/private.sqlite3', 'frontend/dist/unsafe.js'}
        assert not package.selected_sources(names | unsafe, blobs['deploy/prepare_release.py']) & unsafe
        required_inputs = contract.required_inputs(names, blobs['Dockerfile'])
        assert required_inputs <= selected and set(adapter.LOCAL_BUILD_SOURCES) <= selected
        missing = (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) - selected
        assert missing <= {'deploy/finance_column_mapping_release/prepare.py', 'tests/test_finance_column_mapping_release.py'}
        rejected = []
        for name, function in (('operators/ops_common.py', 'source_state'), ('prepare-package.py', 'inspect_inputs')):
            tree = ast.parse(generated[name]); body = next(n.body for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            loop = next(n for n in body if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple) and all(isinstance(v, ast.Constant) for v in n.iter.elts))
            assert ast.literal_eval(loop.iter) == adapter.UNCHANGED
            guards = [n for n in body if isinstance(n, ast.Expr) and 'Reviewed column mapping source changed:' in ast.unparse(n)]
            assert len(guards) == len(pins)
            program = compile(ast.fix_missing_locations(ast.Module(body=[loop, *guards], type_ignores=[])), name, 'exec')
            manifest = {**old, **{path: adapter.sha(raw) for path, raw in blobs.items()}}
            scope = {'need': adapter.need, 'old': old, 'manifest': manifest}; exec(program, scope)
            for path in set(adapter.UNCHANGED) | set(pins):
                scope['manifest'] = {**manifest, path: '0'*64}
                with pytest.raises(RuntimeError): exec(program, scope)
                rejected.append(name+':'+path)
        with patch.object(shared, 'adapter', adapter): config = shared.synthetic_config(access)
        assert package.validate_config(config) == config
        bad_configs = []
        for field, bad in [('oldManifestSha256', adapter.previous.OLD_MANIFEST), ('oldArchiveSha256', adapter.previous.OLD_ARCHIVE),
                           ('parentImage', adapter.previous.PARENT_IMAGE), ('expectedTestCount', True)]:
            changed = copy.deepcopy(config); changed[field] = bad; bad_configs.append(changed)
        for field, required in [('validationTests', adapter.REQUIRED_TESTS), ('changedFiles', adapter.REQUIRED_CHANGED), ('addedFiles', adapter.REQUIRED_ADDED)]:
            for item in required:
                changed = copy.deepcopy(config); changed[field].remove(item); bad_configs.append(changed)
        for changed in bad_configs:
            with pytest.raises(RuntimeError): package.validate_config(changed)
        freeze = access/'freeze.json'; freeze.write_text(json.dumps(config))
        frozen = access/'finance-column-mapping-tools-frozen'; frozen_report = adapter.prepare(access, frozen, freeze)
        assert frozen_report['expectedTestCount'] == 9991  # Only synthetic config; never a collected count.
        invalid = access/'invalid-freeze.json'; invalid.write_text('{}')
        with patch.object(sys, 'argv', [str(output/'prepare-package.py'), '--freeze', str(invalid)]), pytest.raises(RuntimeError):
            package.main()
        assert not (output/'package').exists()
        binder = shared.load_module('mapping_binder', output/'bind-release.py')
        with patch.object(sys, 'argv', [str(output/'bind-release.py'), '--operator-review', str(access/'absent.json'), '--operator-review-sha256', 'invalid']), pytest.raises(RuntimeError, match='checksum'):
            binder.main()
        assert not (output/'package/operator-bindings.json').exists()
        saved = {name: sys.modules.get(name) for name in ('expo_contract', 'ops_common')}; checked = ['prepare-package.py', 'bind-release.py']
        try:
            ops = frozen/'operators'
            sys.modules['expo_contract'] = shared.load_module('mapping_frozen_contract', ops/'expo_contract.py')
            common = shared.load_module('mapping_frozen_common', ops/'ops_common.py'); sys.modules['ops_common'] = common
            common.CANDIDATE = ops; common.BINDING_PATH = ops/'operator-bindings.json'; common.host_guard = lambda: None
            for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                phase = shared.load_module('mapping_'+name[:-3], ops/name)
                argv = [str(ops/name)]
                if name == 'post_readback.py': argv += ['--reviewed-sha256', adapter.sha((ops/name).read_bytes())]
                with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError, match='unbound'): phase.main()
                checked.append(name)
        finally:
            for name, value in saved.items():
                if value is None: sys.modules.pop(name, None)
                else: sys.modules[name] = value
        with (evidence_dir/'generated-delta.patch').open('x', encoding='utf-8', newline='\n') as stream: stream.write(delta)
        return dict(sourceHashes=adapter.PINNED, reviewedSourceHashes=pins, generatedHashes=report['generatedHashes'],
            gitRevision=git_revision, pendingReleaseFiles=sorted(missing), requiredBuildInputs=len(required_inputs),
            sourceMutationRejections=len(rejected), badFreezeRejections=len(bad_configs),
            anonymous401Paths=list(dict.fromkeys(anonymous)), anonymousCheckRequests=len(anonymous),
            unboundEntrypointsRejected=checked, syntheticFreezeCount=9991, schemaChange=False,
            profile='household_members58', productionOperations=False, networkOrGeneratedProcessCalls=False,
            generatedDeltaSha256=adapter.sha((evidence_dir/'generated-delta.patch').read_bytes()))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--git-repo', type=Path, required=True); parser.add_argument('--git-revision', required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    args = parser.parse_args(); assert sys.dont_write_bytecode and not sys.flags.optimize
    assert args.evidence_dir.is_dir() and not any(args.evidence_dir.iterdir())
    print(json.dumps(check_pinned_local_operators(args.source_root, args.git_repo, args.git_revision, args.evidence_dir), indent=2))
