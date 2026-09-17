"""Temporary 58-table preservation and adapter checks; explicit CLI additionally checks private pinned originals.

The CLI uses temporary files and blocks all generated process/network calls.
It does not bind, package the application, connect to servers or run production.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
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
from deploy.expo_trip_recap_release import prepare as adapter
from deploy.git_blobs import read_git_blobs


def test_populated_real_58_table_snapshot_preserves_accounts_values_and_receipts(tmp_path, monkeypatch):
    from contextlib import closing
    import sqlite3
    import app
    from deploy import check_finance_accounts_migration as checker
    def deny(*_a, **_k): raise AssertionError('No network in preservation fixture')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    root = tmp_path / 'data'
    application = app.create_app({'TESTING': True, 'DATA_DIR': str(root),
        'SECRET_KEY': 'synthetic-recap-preservation', 'SESSION_COOKIE_SECURE': False,
        'PUBLIC_ORIGIN': 'http://localhost', 'MEMBER1_PASSWORD': 'synthetic-only',
        'MEMBER2_PASSWORD': 'synthetic-only', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
        'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '', 'ASSISTANT_PROVIDER': 'local',
        'NVIDIA_API_KEY': '', 'OPENAI_API_KEY': ''})
    client = application.test_client()
    assert client.post('/api/login', json={'username': 'member1', 'password': 'synthetic-only'}).status_code == 200
    headers = {'X-CSRF-Token': client.get('/api/me').json['csrf'], 'Origin': 'http://localhost'}
    created = client.post('/api/finance-accounts', json={'requestId': '1' * 32, 'revision': 0,
        'name': '虚构非空账户', 'institution': '合成机构', 'kind': 'asset', 'currency': 'USD',
        'note': '不含真实财务', 'valuation': {'asOf': '2026-09-17', 'amountCents': 0}}, headers=headers)
    assert created.status_code == 201, created.json
    account_id = created.json['accountId']
    unknown = client.put('/api/finance-accounts/' + account_id + '/valuations/2026-09-16',
        json={'requestId': '2' * 32, 'revision': 1, 'amountCents': None}, headers=headers)
    assert unknown.status_code == 200, unknown.json
    before = checker.snapshot(root); schema = checker.schema_definition()
    assert checker.verify_current(before, schema)['newTableRows'] == {
        'finance_accounts': 1, 'finance_account_valuations': 2, 'finance_account_operations': 2}
    namespace = {'verify_current': checker.verify_current}
    exec(adapter.PRESERVATION_FUNCTION, namespace)
    verify = namespace['verify_preserved']
    result = verify(before, checker.snapshot(root), schema)
    assert result == dict(originalTablesPreserved=58, newTables=0, households=1,
        allRowsSchemaAndSequencesPreserved=True, registryPreserved=True)
    # Drift the actual populated SQLite database, roll back each injected change
    # by restoring a local in-memory backup, then confirm the full snapshot again.
    path = checker.media.checked_path(root, checker.media.relative_database('default'))
    with closing(sqlite3.connect(':memory:')) as backup:
        with closing(sqlite3.connect(path)) as con: con.backup(backup)
        for sql in ("UPDATE finance_accounts SET note='changed'",
                    'UPDATE finance_account_valuations SET amount_cents=42',
                    'DELETE FROM finance_account_operations',
                    "UPDATE audit SET target='changed'",
                    "UPDATE sqlite_sequence SET seq=seq+1 WHERE name='audit'",
                    'CREATE INDEX synthetic_changed_schema ON finance_accounts(name)'):
            with closing(sqlite3.connect(path)) as con:
                con.execute(sql); con.commit()
            with pytest.raises(RuntimeError): verify(before, checker.snapshot(root), schema)
            with closing(sqlite3.connect(path)) as con: backup.backup(con)
            assert checker.snapshot(root) == before
    changed = copy.deepcopy(before)
    table = next(iter(changed['registry']['tables'].values()))
    table['rowsSha256'] = '0' * 64
    with pytest.raises(RuntimeError): verify(before, changed, schema)
    changed = copy.deepcopy(before); changed['households']['other'] = changed['households'].pop('default')
    with pytest.raises(RuntimeError): verify(before, changed, schema)


def test_pinned_bytes_and_unsafe_paths_are_rejected(tmp_path, monkeypatch):
    raw = b'# synthetic\r\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    assert adapter.read_sources(tmp_path) == {'source.py': b'# synthetic\n'}
    (tmp_path / 'source.py').write_bytes(b'# synthetic\n')
    with pytest.raises(RuntimeError, match='checksum'): adapter.read_sources(tmp_path)
    for path in (Path('relative'), tmp_path / '..' / 'escape'):
        with pytest.raises(RuntimeError): adapter.safe_path(path, exists=False)


def test_new_output_is_confined_exclusive_and_unbound(tmp_path, monkeypatch):
    raw = b'# original\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    monkeypatch.setattr(adapter, 'adapt', lambda *_: {'operators/build.py': b'raise RuntimeError("unbound")\n'})
    output = tmp_path / 'expo-trip-recap-tools-synthetic'
    result = adapter.prepare(tmp_path, output)
    assert result['bound'] is False and result['schemaChange'] is False
    assert result['householdTablesBefore'] == 58 and result['householdTablesAfter'] == 58
    assert result['expectedTestCount'] is None and result['productionOperations'] is False
    assert not (output / 'operator-bindings.json').exists()
    with pytest.raises(RuntimeError, match='exists'): adapter.prepare(tmp_path, output)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path.parent / output.name)
    with pytest.raises(RuntimeError): adapter.prepare(tmp_path, tmp_path / 'trip-coordination-tools-replay')


def test_input_race_fails_before_any_output(tmp_path, monkeypatch):
    raw = b'# original\n'; (tmp_path / 'source.py').write_bytes(raw)
    monkeypatch.setattr(adapter, 'PINNED', {'source.py': adapter.sha(raw)})
    def drift(*_):
        (tmp_path / 'source.py').write_bytes(b'# changed\n'); return {}
    monkeypatch.setattr(adapter, 'adapt', drift)
    output = tmp_path / 'expo-trip-recap-tools-synthetic'
    with pytest.raises(RuntimeError, match='checksum'): adapter.prepare(tmp_path, output)
    assert not output.exists()


@pytest.mark.parametrize('damage', ['outside', 'large', 'duplicate'])
def test_invalid_freeze_never_evaluates_generated_code(tmp_path, damage):
    root = tmp_path / 'access'; root.mkdir()
    path = (tmp_path if damage == 'outside' else root) / 'freeze.json'
    path.write_bytes(b'x' * 2_000_001 if damage == 'large' else b'{"main":1,"main":2}')
    with pytest.raises(RuntimeError):
        adapter.freeze_config(path, root, {'prepare-package.py': b'raise AssertionError("must not execute")'})


@pytest.mark.parametrize('code', ["migrate(root)", "initialize_database(a,b)",
    "create_app(config)", "program='con.executescript(sql)'",
    "program=\"con.execute('CREATE TABLE x(y)')\""])
def test_generated_program_refuses_uncontrolled_migration_and_ddl(code):
    with pytest.raises(RuntimeError): adapter.verify_generated(code, 'operators/activate.py')


def test_scope_preserves_all_runtime_and_dependency_bytes():
    assert len(adapter.REQUIRED_TESTS) == 8
    assert {'tests/test_finance_accounts_migration.py', 'tests/test_platform_backup.py'} <= adapter.REQUIRED_TESTS
    assert 'tests/test_packager_batch_read.py' not in adapter.REQUIRED_TESTS
    assert len(adapter.BACKEND_UNCHANGED) == 38
    assert set(adapter.previous.UNCHANGED) <= set(adapter.UNCHANGED)
    assert set(adapter.BACKEND_UNCHANGED) <= set(adapter.UNCHANGED)
    assert adapter.LOCAL_BUILD_SOURCES == adapter.previous.LOCAL_BUILD_SOURCES
    assert len(adapter.LOCAL_BUILD_SOURCES) == 3
    assert not set(adapter.LOCAL_BUILD_SOURCES) & adapter.REQUIRED_ADDED
    assert not (adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED) & set(adapter.UNCHANGED)
    assert not adapter.REQUIRED_CHANGED & adapter.REQUIRED_ADDED
    assert {'Dockerfile', 'app.py', 'data_portability.py', 'finance_accounts.py',
        'frontend/package.json', 'frontend/package-lock.json', 'deploy/backup.py',
        'deploy/prepare_release.py', 'deploy/check_finance_accounts_migration.py'} <= set(adapter.UNCHANGED)
    assert len(adapter.PINNED) == len(set(adapter.PINNED.values())) == 9


@pytest.mark.parametrize('bad', [b'', b'COPY extra ./\n', b'FROM changed\n', b'FROM fixed-parent\r\n'])
def test_dockerfile_must_remain_exact_bytes(bad):
    old = b'FROM fixed-parent\n'
    ns = {'need': adapter.need}; exec(adapter.DOCKER_CONTRACT, ns)
    ns['verify_docker_delta'](old, old)
    with pytest.raises(RuntimeError): ns['verify_docker_delta'](old, bad)


def anonymous_loop(code):
    loops = [node for node in ast.walk(ast.parse(code)) if isinstance(node, ast.For)
             and isinstance(node.iter, ast.Tuple) and any(isinstance(item, ast.Constant)
             and item.value == '/api/accounts' for item in node.iter.elts)]
    assert len(loops) == 1
    return loops[0]


def anonymous_paths(code):
    return eval(compile(ast.Expression(anonymous_loop(code).iter), '<endpoint tuple>', 'eval'), {'__builtins__': {}})


def check_anonymous_loop(code, target, status):
    # Run the actual loop with controlled HTTP outcomes, never a live endpoint.
    from urllib.error import HTTPError
    calls = []
    def urlopen(url, timeout):
        assert timeout == 15
        calls.append(url)
        code = status if url.endswith(target) else 401
        raise HTTPError(url, code, 'synthetic boundary response', {}, None)
    namespace = {'urlopen': urlopen, 'HTTPError': HTTPError, 'need': adapter.need, 'denied': {}}
    module = ast.Module(body=[anonymous_loop(code)], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<anonymous endpoint check>', 'exec'), namespace)
    assert any(url.endswith(target) for url in calls)
    assert namespace['denied'][target] == 401


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def check_activation_evidence(code):
    """Execute the actual pure post guard, including its chained proof equality."""
    main = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    node = next(n for n in main.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name) and n.value.func.id == 'need'
                and 'activation_snapshot' in ast.unparse(n.value.args[0]))
    program = compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<activation proof>', 'exec')
    result = dict(originalTablesPreserved=58, newTables=0, households=2,
                  allRowsSchemaAndSequencesPreserved=True, registryPreserved=True)
    snapshot = {'synthetic': 'populated 58 tables'}
    for damage in (None, 'startup', 'rows', 'registry', 'schema', 'count', 'addition'):
        proof = {'before.json': copy.deepcopy(snapshot)}
        published = dict(preservationResult=copy.deepcopy(result),
                         households=2, householdTables=58, schemaChange=False, allExistingDataPreservedAtAppStartup=True)
        if damage == 'startup': proof['before.json']['synthetic'] = 'changed'
        elif damage == 'rows': published['preservationResult']['allRowsSchemaAndSequencesPreserved'] = False
        elif damage == 'registry': published['preservationResult']['registryPreserved'] = False
        elif damage == 'schema': published['schemaChange'] = True
        elif damage == 'count': published['householdTables'] = 55
        elif damage == 'addition': published['preservationResult']['newTables'] = 3
        scope = dict(need=adapter.need, activation_snapshot=snapshot, preservation=result, published=published,
                     proof_root=Path('synthetic'), read=lambda path: proof[path.name])
        if damage:
            with pytest.raises(RuntimeError): exec(program, scope)
        else: exec(program, scope)


@pytest.mark.parametrize('name,code', [
    ('operators/post_readback.py', "migrate(Path('/data'),before,backup,schema)"),
    ('operators/activate.py', "migrate(Path('/other'),before,backup,schema)"),
    ('operators/validate.py', 'verify_baseline(before)'),
    ('operators/build.py', 'verify_addition(before,after,schema)'),
])
def test_old_migration_calls_are_forbidden_in_every_phase(name, code):
    with pytest.raises(RuntimeError): adapter.verify_generated(code, name)


def synthetic_config(access):
    file = access / 'synthetic-input'; file.write_bytes(b'synthetic')
    return dict(schemaVersion=1, main='1' * 40, integration='2' * 40, tree='3' * 40,
        buildEvidencePath=str(file), testedBuildEvidencePath=str(file), exportDirectory=str(access),
        buildEvidenceSha256='a' * 64, testedBuildEvidenceSha256='b' * 64,
        oldArchivePath=str(file), oldArchiveSha256=adapter.OLD_ARCHIVE,
        oldManifestSha256=adapter.OLD_MANIFEST, parentImage=adapter.PARENT_IMAGE,
        oldImages={**{name: adapter.PARENT_IMAGE for name in ('app', 'sync', 'media')},
                   'web': 'sha256:1ae82dcc4a34bcd976195b3c4c5a6b7e569505527a1e2a28c2101e032159a5c7'},
        envSha256='a72d456815cf113b1ac0c1e032ac8c45b300ccf2cb499520c14b7f54d5314e07',
        migrationSqlSha256='c' * 64, validationTests=sorted(adapter.REQUIRED_TESTS), expectedTestCount=9991,
        changedFiles=sorted(adapter.REQUIRED_CHANGED), addedFiles=sorted(adapter.REQUIRED_ADDED), removedFiles=[])


def check_pinned_local_operators(source_root, git_repo, git_revision, freeze=None, build_evidence=None):
    """Inspect actual generated guards, never a replacement implementation."""
    inputs = adapter.read_sources(source_root)
    archive = adapter.safe_path(source_root / adapter.BASE / 'package/release.tar.gz')
    raw = archive.read_bytes(); assert adapter.sha(raw) == adapter.OLD_ARCHIVE
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as packed:
        manifest_raw = packed.extractfile('RELEASE-MANIFEST.json').read()
        assert adapter.sha(manifest_raw) == adapter.OLD_MANIFEST
        manifest = json.loads(manifest_raw)['files']
        old_docker = packed.extractfile('Dockerfile').read()
        assert adapter.sha(old_docker) == manifest['Dockerfile']
    assert re.fullmatch('[0-9a-f]{40}', git_revision)
    docker = subprocess.run(['git', '--no-replace-objects', '-C', str(adapter.safe_path(git_repo)), 'show', git_revision + ':Dockerfile'],
                            check=True, capture_output=True).stdout
    tracked = set(subprocess.run(['git', '--no-replace-objects', '-C', str(git_repo), 'ls-tree', '-rz', '--name-only', git_revision],
                                check=True, capture_output=True).stdout.decode().rstrip('\0').split('\0'))
    prepare_source = subprocess.run(['git', '--no-replace-objects', '-C', str(git_repo), 'show', git_revision + ':deploy/prepare_release.py'],
                                    check=True, capture_output=True).stdout
    evidence_raw = adapter.safe_path(build_evidence).read_bytes() if build_evidence else None
    actual_freeze_raw = adapter.safe_path(freeze).read_bytes() if freeze else None
    contract_ns = {'__name__': 'pure_parent_contract'}
    exec(compile(inputs[adapter.BASE + 'operators/expo_contract.py'], '<fixed contract>', 'exec'), contract_ns)
    input_names = contract_ns['required_inputs'](tracked, docker)
    blob_inputs = read_git_blobs(git_repo, git_revision, input_names)
    backend_inputs = read_git_blobs(git_repo, git_revision, adapter.BACKEND_UNCHANGED)
    assert all(adapter.sha(raw) == manifest[name] for name, raw in backend_inputs.items())
    def deny(*_args, **_kwargs): raise AssertionError('Generated operator attempted an external action')
    with tempfile.TemporaryDirectory(prefix='expo-trip-recap-guards-') as folder, \
         patch('subprocess.run', deny), patch('subprocess.Popen', deny), patch('subprocess.check_output', deny), \
         patch('socket.create_connection', deny), patch.object(socket.socket, 'connect', deny):
        access = Path(folder).resolve()
        for name in adapter.PINNED:
            target = access / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source_root / name).read_bytes())
        output = access / 'expo-trip-recap-tools-synthetic'; report = adapter.prepare(access, output)
        operator_dir = output / 'operators'
        contract = load_module('trip_contract_test', operator_dir / 'expo_contract.py')
        contract.verify_docker_delta(old_docker, docker)
        expected_paths = contract.runtime_paths(docker, tracked)
        assert {'household_routines.py', 'journey_documents.py', 'journey_reschedule.py', 'media_playback.py', 'tv_display.py'} <= expected_paths
        validation = inputs[adapter.BASE + 'operators/validate.py']
        assert b"'--memory','896m'" in validation and b'/tmp:rw,size=671088640,mode=1777' in validation
        with pytest.raises(RuntimeError): contract.verify_docker_delta(old_docker, docker + b'\n')
        generated = {name: (output / name).read_bytes() for name in report['generatedHashes']}
        validation = generated['operators/validate.py'].decode()
        assert "'--memory','896m'" in validation and '/tmp:rw,size=671088640,mode=1777' in validation
        assert "('deploy.check_finance_accounts_migration','finance_accounts')" in validation
        assert validation.count('helper.ROOT=runtime') == 1
        assert generated['operators/validate.py'] == inputs[adapter.BASE + 'operators/validate.py']
        original_post = inputs[adapter.BASE + 'operators/post_readback.py'].decode()
        expected_post = generated['operators/post_readback.py'].decode()
        old_paths, new_paths = anonymous_paths(original_post), anonymous_paths(expected_post)
        assert new_paths == old_paths and len(set(new_paths)) == 37
        for target in set(new_paths):
            check_anonymous_loop(expected_post, target, 401)
            for denied_status in (200, 403):
                with pytest.raises(RuntimeError, match='Anonymous endpoint boundary failed'):
                    check_anonymous_loop(expected_post, target, denied_status)
        post = (operator_dir / 'post_readback.py').read_text()
        assert "'/app/tv','/tv'" in post and "'/tv?classic=1'" in post
        assert "TV did not redirect to Expo display" in post
        package = load_module('trip_package_test', output / 'prepare-package.py')
        config = synthetic_config(access); assert package.validate_config(config) == config
        # Exercise the actual pinned parent selector and the generated selector,
        # using a real Git tree and its unmodified global whitelist source.
        parent_ns = {'__name__': 'parent_selector_review', '__file__': str(access / 'parent.py')}
        exec(compile(inputs[adapter.PREPARE_SOURCE], parent_ns['__file__'], 'exec'), parent_ns)
        parent_selected = parent_ns['selected_sources'](tracked, prepare_source)
        selected = package.selected_sources(tracked, prepare_source)
        assert selected == parent_selected
        assert all(name in selected for name in adapter.LOCAL_BUILD_SOURCES)
        required = adapter.REQUIRED_CHANGED | adapter.REQUIRED_ADDED
        pending_sources = sorted(required - tracked)
        assert required.intersection(tracked) <= selected
        assert not set(adapter.LOCAL_BUILD_SOURCES) & expected_paths  # Not Python runtime/Node execution.
        for missing in adapter.LOCAL_BUILD_SOURCES:
            with pytest.raises(RuntimeError, match='Explicit allowlist source is not tracked'):
                package.selected_sources(tracked - {missing}, prepare_source)
        extras = {'frontend/tests/private-finance.json', 'frontend/tests/other.test.ts',
                  'frontend/node_modules/private.js', 'frontend/dist/index.html', 'frontend/.env.local'}
        assert not extras & package.selected_sources(tracked | extras, prepare_source)
        with pytest.raises(RuntimeError, match='Generated Expo output unexpectedly tracked'):
            package.selected_sources(tracked | {'static/experience/extra.js'}, prepare_source)
        input_count = len(input_names)
        assert input_names == contract.required_inputs(tracked, docker) <= selected
        assert set(blob_inputs) == input_names
        if evidence_raw:
            evidence = contract.validate_evidence(json.loads(evidence_raw))
            assert evidence['sourceHead'] == git_revision
            assert set(evidence['inputFiles']) == input_names
            assert all(adapter.sha(blob_inputs[name]) == digest for name, digest in evidence['inputFiles'].items())
            input_count = len(evidence['inputFiles'])
        if actual_freeze_raw:
            assert not pending_sources, 'Final source must include every required path'
            actual_config = json.loads(actual_freeze_raw, object_pairs_hook=adapter.unique)
            # This pure config check never calls inspect_inputs/packaging/binding.
            assert package.validate_config(actual_config) == actual_config
        # A real final-freeze generation must retain its explicit selection/count;
        # 9991 here is deliberately synthetic, never a collected production count.
        freeze = access / 'synthetic-freeze.json'; freeze.write_text(json.dumps(config))
        frozen_output = access / 'expo-trip-recap-tools-frozen-synthetic'
        frozen = adapter.prepare(access, frozen_output, freeze)
        assert frozen['finalFreezeProvided'] and frozen['bound'] is False
        assert frozen['expectedTestCount'] == 9991 and frozen['freezeSha256'] == adapter.sha(freeze.read_bytes())
        frozen_common = ast.parse((frozen_output / 'operators/ops_common.py').read_text())
        constants = {node.targets[0].id: ast.literal_eval(node.value) for node in frozen_common.body
                     if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id in ('EXPECTED_TEST_COUNT', 'EXPECTED_TESTS')}
        assert constants == {'EXPECTED_TEST_COUNT': 9991, 'EXPECTED_TESTS': tuple(config['validationTests'])}
        frozen_dir = frozen_output / 'operators'
        imported = sys.modules.get('expo_contract')
        try:
            sys.modules['expo_contract'] = contract
            bound_guard = load_module('accounts_bound_guard', frozen_dir / 'ops_common.py')
        finally:
            if imported is None: sys.modules.pop('expo_contract', None)
            else: sys.modules['expo_contract'] = imported
        bound_guard.CANDIDATE = frozen_dir
        bound_guard.BINDING_PATH = frozen_dir / 'operator-bindings.json'
        binding = dict(bound=True, expected={'synthetic': True}, expectedTestCount=9991,
            operatorHashes={name: adapter.sha((frozen_dir / name).read_bytes()) for name in adapter.SCRIPTS},
            migration=dict(profile='finance_accounts58', sqlSha256='c' * 64, sourceSha256='d' * 64))
        # Synthetic binding lives only in the temporary fixture; no phase executes.
        bound_guard.BINDING_PATH.write_text(json.dumps(binding))
        assert bound_guard.release_binding() == binding
        for field, bad in [('bound', False), ('expectedTestCount', 184), ('expectedTestCount', True),
                           ('migration', {**binding['migration'], 'profile': 'investment_operations55'}),
                           ('operatorHashes', {**binding['operatorHashes'], 'activate.py': '0' * 64})]:
            bound_guard.BINDING_PATH.write_text(json.dumps({**binding, field: bad}))
            with pytest.raises(RuntimeError): bound_guard.release_binding()
        # Execute only the actual generated byte-preservation loop. A changed
        # backend must fail before any server phase can touch production data.
        source_state = next(node for node in frozen_common.body
                            if isinstance(node, ast.FunctionDef) and node.name == 'source_state')
        guard = next(node for node in source_state.body if isinstance(node, ast.For)
                     and isinstance(node.iter, ast.Tuple)
                     and all(isinstance(item, ast.Constant) for item in node.iter.elts))
        guard_names = ast.literal_eval(guard.iter)
        assert set(guard_names) == set(adapter.UNCHANGED)
        program = compile(ast.fix_missing_locations(ast.Module(body=[guard], type_ignores=[])),
                          '<actual backend preservation guard>', 'exec')
        namespace = {'need': adapter.need, 'old': manifest, 'manifest': dict(manifest)}
        exec(program, namespace)
        for name in adapter.BACKEND_UNCHANGED:
            namespace['manifest'] = {**manifest, name: '0' * 64}
            with pytest.raises(RuntimeError, match='Dependency, schema or deployment contract changed'):
                exec(program, namespace)
        rejected = []
        for key, bad in [('oldManifestSha256', adapter.previous.OLD_MANIFEST),
                         ('oldArchiveSha256', adapter.previous.OLD_ARCHIVE),
                         ('parentImage', adapter.previous.PARENT_IMAGE)]:
            changed = copy.deepcopy(config); changed[key] = bad
            if key == 'parentImage': changed['oldImages'].update({name: bad for name in ('app', 'sync', 'media')})
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append(key)
        for key, required in [('validationTests', adapter.REQUIRED_TESTS), ('changedFiles', adapter.REQUIRED_CHANGED),
                              ('addedFiles', adapter.REQUIRED_ADDED)]:
            for item in sorted(required):
                changed = copy.deepcopy(config); changed[key].remove(item)
                with pytest.raises(RuntimeError): package.validate_config(changed)
                rejected.append(key + ':' + item)
        for name in adapter.FORBIDDEN_TESTS:
            changed = copy.deepcopy(config); changed['validationTests'].append(name)
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append('forbiddenTest:' + name)
        for count in (0, True, 10_000):
            changed = copy.deepcopy(config); changed['expectedTestCount'] = count
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append('expectedTestCount:' + str(count))
        for field in ('validationTests', 'changedFiles', 'addedFiles'):
            changed = copy.deepcopy(config); changed[field].append(changed[field][0])
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append('duplicate:' + field)
        for field in ('unexpected', 'main', 'integration', 'tree'):
            changed = copy.deepcopy(config); changed[field] = 'bad'
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append('malformed:' + field)
        for path in ('../private.py',):
            changed = copy.deepcopy(config); changed['addedFiles'] = sorted(changed['addedFiles'] + [path])
            with pytest.raises(RuntimeError): package.validate_config(changed)
            rejected.append('unsafeAdded:' + path)
        activation = generated['operators/activate.py'].decode()
        ordered = ["'web_backup_timer_and_all_data_volume_writers_stopped'", "before=diagnostic(snapshot_program)",
            "backup_check=diagnostic(validation_program)", "preserved = json.loads",
            "need(diagnostic(current_program)==before", "os.rename(old_bundle", "'--wait-timeout','150','app'",
            "need(after==before", "'--wait-timeout','150','sync','media','web'"]
        assert [activation.index(fragment) for fragment in ordered] == sorted(activation.index(fragment) for fragment in ordered)
        assert 'schemaChange=False' in activation and "report.pop('productionWrites', None)" in activation
        assert 'verify_preserved(before,after,schema)' in activation
        for forbidden in ('migrate(', 'verify_addition(', 'verify_baseline(', 'after-migration.json', 'migration_result'):
            assert forbidden not in activation and forbidden not in expected_post
        assert "activation_snapshot==read(proof_root/'before.json')" in expected_post
        assert 'activationStartup58Verified=True' in expected_post and 'liveGroupSnapshotRechecked=False' in expected_post
        parent_function = next(n for n in ast.parse(original_post).body if isinstance(n, ast.FunctionDef) and n.name == 'inspect_backup_group')
        new_function = next(n for n in ast.parse(expected_post).body if isinstance(n, ast.FunctionDef) and n.name == 'inspect_backup_group')
        assert ast.dump(new_function) == ast.dump(parent_function)
        # Execute the preservation function extracted from the actual generated
        # activation and check it is identical to the post program's function.
        strings = [n.value for n in ast.walk(ast.parse(activation)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        fragment = next(v for v in strings if v.startswith('\ndef verify_preserved('))
        post_main = next(n for n in ast.parse(expected_post).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        post_program = next(n.value.value for n in post_main.body if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'preservation_program')
        assert fragment in post_program
        assert fragment == adapter.PRESERVATION_FUNCTION
        check_activation_evidence(expected_post)
        checked = []; previous = {name: sys.modules.get(name) for name in ('expo_contract', 'ops_common')}
        try:
            sys.modules['expo_contract'] = contract
            common = load_module('trip_common_test', operator_dir / 'ops_common.py'); sys.modules['ops_common'] = common
            common.CANDIDATE = operator_dir; common.BINDING_PATH = operator_dir / 'operator-bindings.json'
            common.host_guard = lambda: None  # Reach actual absent-binding guard past Linux location validation.
            with patch('subprocess.run', deny), patch('subprocess.Popen', deny), patch('subprocess.check_output', deny), \
                 patch('socket.create_connection', deny), patch.object(socket.socket, 'connect', deny):
                for name in ('build.py', 'validate.py', 'stage.py', 'activate.py', 'post_readback.py'):
                    value = load_module('trip_' + name.removesuffix('.py'), operator_dir / name)
                    argv = [str(operator_dir / name)]
                    if name == 'post_readback.py': argv += ['--reviewed-sha256', adapter.sha((operator_dir / name).read_bytes())]
                    with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError, match='unbound'): value.main()
                    checked.append(name)
                for name in ('prepare-package.py', 'bind-release.py'):
                    value = load_module('trip_' + name.replace('-', '_').removesuffix('.py'), output / name)
                    missing = output / 'absent.json'
                    argv = [str(output / name), '--freeze', str(missing)] if name == 'prepare-package.py' else [str(output / name), '--operator-review', str(missing), '--operator-review-sha256', 'a' * 64]
                    with patch.object(sys, 'argv', argv), pytest.raises(RuntimeError): value.main()
                    checked.append(name)
        finally:
            for name, module in previous.items():
                if module is None: sys.modules.pop(name, None)
                else: sys.modules[name] = module
        for name, digest in report['generatedHashes'].items():
            raw = (output / name).read_bytes(); assert adapter.sha(raw) == digest; adapter.verify_generated(raw, name)
        return dict(pinnedSources=adapter.PINNED, generatedHashes=report['generatedHashes'],
            unboundRejected=checked, freezeRejected=rejected, actualDockerArchiveSha256=adapter.OLD_ARCHIVE,
            actualDockerUnchanged=docker == old_docker, gitRevision=git_revision,
            exactPreservationAndStartupOrderVerified=True, recursiveGeneratedSyntaxVerified=True,
            syntheticFinalFreezeSelectionAndCountVerified=True,
            changedBindingOrOldCountRejected=True,
            exactLocalBuildSources=list(adapter.LOCAL_BUILD_SOURCES),
            trackedRequiredSourcesSelected=True, pendingIntegrationSources=pending_sources,
            missingLocalBuildSourcesRejected=3,
            extraLocalSensitiveOrGeneratedSourcesRejected=True,
            actualBuildInputCount=input_count,
            actualBackendFilesUnchanged=len(backend_inputs), backendByteChangesRejected=len(adapter.BACKEND_UNCHANGED),
            actualBuildEvidenceSha256=adapter.sha(evidence_raw) if evidence_raw else None,
            actualFreezeAccepted=actual_freeze_raw is not None,
            actualFreezeSha256=adapter.sha(actual_freeze_raw) if actual_freeze_raw else None,
            exactAnonymousEndpointsPreserved=sorted(set(new_paths)), anonymousUniquePathsPreserved=37, anonymous401Required=True,
            validationMemoryMiB=896, validationTmpfsMiB=640,
            productionOperations=False, unboundNetworkOrProcessActions=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--git-repo', type=Path, required=True)
    parser.add_argument('--git-revision', required=True)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--build-evidence', type=Path)
    args = parser.parse_args()
    assert sys.dont_write_bytecode and not sys.flags.optimize
    print(json.dumps(check_pinned_local_operators(args.source_root, args.git_repo, args.git_revision,
                                                args.freeze, args.build_evidence), indent=2))
