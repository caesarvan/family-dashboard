"""Synthetic local recovery checks. No Docker daemon or production inputs."""
import ast
from contextlib import closing, contextmanager
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest
from werkzeug.serving import WSGIRequestHandler, make_server

from app import create_app
from deploy.backup import backup_all
from deploy import rehearse_restore as controller
from journey_places import SCHEMA_SQL


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('places_restore_fixture', ROOT / 'tests/restore_rehearsal_fixture.py')
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
IMAGE = 'sha256:' + 'a' * 64


def minimal_snapshot(profile='journey_places44'):
    details, schema = controller.profile_definition(ROOT, profile)
    names = controller.LEGACY_TABLES | ({'journey_places'} if profile == 'journey_places44' else set())
    return {'tables': {name: {} for name in names}, 'schema': schema}, details


def test_profiles_are_explicit_and_schema_digest_is_exact():
    assert len(controller.LEGACY_TABLES) == 43
    for name, count in [('legacy43', 43), ('journey_places44', 44)]:
        value, details = minimal_snapshot(name)
        assert controller.validate_snapshot_profile(value, ROOT, name) == details
        assert details['householdTables'] == count
        assert details['schemaSha256'] == (controller.sha(SCHEMA_SQL.encode('utf-8')) if count == 44 else None)
        value['tables']['sqlite_sequence'] = {}
        assert controller.validate_snapshot_profile(value, ROOT, name) == details
    with pytest.raises(ValueError, match='Unknown restore profile'):
        controller.profile_definition(ROOT, 'auto')


@pytest.mark.parametrize('change', ['same_count_wrong_name', 'extra', 'missing', 'internal_extra', 'legacy_on_44', '44_on_legacy'])
def test_table_count_alone_never_satisfies_profile(change):
    value, _ = minimal_snapshot('legacy43' if change == '44_on_legacy' else 'journey_places44')
    if change == 'same_count_wrong_name':
        value['tables']['unknown'] = value['tables'].pop('photos')
    elif change in {'extra', 'internal_extra'}:
        value['tables']['sqlite_unapproved' if change == 'internal_extra' else 'unknown'] = {}
    elif change == 'missing':
        value['tables'].pop('users')
    with pytest.raises(ValueError, match='table set'):
        controller.validate_snapshot_profile(value, ROOT, 'legacy43' if change == 'legacy_on_44' else 'journey_places44')


@pytest.mark.parametrize('object_type', ['table', 'index', 'trigger'])
def test_places_ddl_drift_rejected(object_type):
    value, _ = minimal_snapshot()
    row = next(row for row in value['schema'] if row[0] == object_type)
    row[3] = (row[3] or '') + ' -- changed'
    with pytest.raises(ValueError, match='DDL'):
        controller.validate_snapshot_profile(value, ROOT, 'journey_places44')


def test_schema_missing_duplicate_or_nonliteral_rejected(tmp_path):
    path = tmp_path / 'journey_places.py'
    for code in ('x=1', "SCHEMA_SQL=''; SCHEMA_SQL=''", 'SCHEMA_SQL=get_schema()'):
        path.write_text(code, encoding='utf-8')
        with pytest.raises((ValueError, TypeError)):
            controller.profile_definition(tmp_path, 'journey_places44')
    # Legacy images do not need the new Python module.
    assert controller.profile_definition(tmp_path, 'legacy43')[0]['householdTables'] == 43


@pytest.mark.parametrize('profile', controller.PROFILES)
@pytest.mark.parametrize('wrong', [False, True])
def test_controller_passes_profile_and_rejects_mismatched_proof(tmp_path, monkeypatch, profile, wrong):
    obj = controller.Rehearsal(ROOT, IMAGE, tmp_path / 'report', profile=profile)
    value = {'passed': True, 'checks': [{'name': 'synthetic', 'passed': True}], 'profile': obj.profile,
             'counts': {'householdTablesEach': 0 if wrong else obj.profile['householdTables']}}
    seen = []
    monkeypatch.setattr(obj, 'require_owned', lambda *_: {})
    def fake(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(value), '')
    monkeypatch.setattr(obj, 'docker', fake)
    if wrong:
        with pytest.raises(RuntimeError, match='fixture_seed'):
            obj.fixture('owned-synthetic', 'seed')
    else:
        obj.fixture('owned-synthetic', 'seed')
    assert seen[0][-2:] == ['--profile', profile]
    assert obj.env['ASSISTANT_PROVIDER'] == 'local'
    assert obj.env['NVIDIA_API_KEY'] == obj.env['NVIDIA_MODEL'] == ''


class QuietRequests(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


@contextmanager
def local_server(config, port=0):
    server = make_server('127.0.0.1', port, create_app(config), threaded=True, request_handler=QuietRequests)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def adapted_program(program, paths, argv, monkeypatch):
    """Tests only: remap literal container roots to fresh temporary directories."""
    seen = set()
    class LocalPaths(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in paths:
                seen.add(node.value)
                return ast.copy_location(ast.Constant(str(paths[node.value])), node)
            return node
    tree = LocalPaths().visit(ast.parse(program))
    assert seen == set(paths)
    monkeypatch.setattr(sys, 'argv', ['synthetic-local-only', *argv])
    exec(compile(ast.fix_missing_locations(tree), '<documented-program-temporary-paths-only>', 'exec'), {})


def fixture_phase(phase, root, proof, base, monkeypatch, capsys):
    monkeypatch.setenv('DATA_DIR', str(root))
    code = fixture.main([phase, '--proof-dir', str(proof), '--base-url', base, '--profile', 'journey_places44'])
    output = capsys.readouterr().out.strip().splitlines()
    report = json.loads(output[-1])
    assert code == 0, report
    assert report['passed'] and report['productionInputs'] == 0
    assert not report['externalRequests'] and report['providerRequestsInitiatedByFixture'] == 0
    return report


def test_real_http_two_households_backup_documented_restore_and_permissions(tmp_path, monkeypatch, capsys):
    """Runs real app/API/SQLite; adapted local paths are NOT real Docker evidence."""
    obj = controller.Rehearsal(ROOT, IMAGE, tmp_path / 'unused', profile='journey_places44')
    for key, value in obj.env.items():
        monkeypatch.setenv(key, value)
    source, target, proof = (tmp_path / name for name in ('source', 'restored', 'proof'))
    for path in (source, target, proof):
        path.mkdir()
    config = {'TESTING': True, 'DATA_DIR': str(source), 'SESSION_COOKIE_SECURE': False}
    network = fixture.Audit('local-test-network-guard')
    with fixture.only_loopback(network):
        with local_server(config) as base:
            seeded = fixture_phase('seed', source, proof, base, monkeypatch, capsys)
            # Full real table set rejects legacy even though its 43 names are present.
            with pytest.raises(ValueError, match='table set'):
                controller.validate_snapshot_profile(fixture.snapshot(source / 'household.sqlite3'), ROOT, 'legacy43')
        before_proof = (proof / 'expected.json').read_bytes()
        expected = json.loads(before_proof)
        assert sum(len(h['places']) for h in expected['households']) == 24
        assert len(expected['schemaFingerprints']) == 2
        # No app is running while using the unmodified backup entrypoint.
        backed = backup_all(source)
        assert backed['databases'] == 3
        restore, invalidate = controller.documented_programs(ROOT)
        adapted_program(controller.COPY_SNAPSHOTS, {'/source': source, '/data': target}, [backed['manifest'], 'valid'], monkeypatch)
        adapted_program(restore, {'/data': target}, [backed['manifest'], 'platform', 'default'], monkeypatch)
        for house in fixture.registry(target):
            with closing(sqlite3.connect(fixture.database_path(target, house['id']))) as con:
                con.executescript(invalidate)
        with local_server({**config, 'DATA_DIR': str(target)}, port=int(base.rsplit(':', 1)[1])) as restored_base:
            verified = fixture_phase('verify', target, proof, restored_base, monkeypatch, capsys)
        assert (proof / 'expected.json').read_bytes() == before_proof
        assert seeded['profile'] == verified['profile'] == obj.profile
        assert seeded['schemaFingerprints'] == verified['schemaFingerprints']
        assert verified['counts']['journeyPlaces'] == 24 and verified['counts']['placeTombstones'] == 4
        assert verified['counts']['oldCookiesRejected'] == 4 and verified['counts']['oldOAuthStatesRejected'] == 4
        assert not network.external
    print(json.dumps({'kind': 'synthetic-local-http-sqlite', 'realDocker': False,
        'profile': verified['profile'], 'schemaFingerprints': verified['schemaFingerprints'],
        'seedChecks': seeded['checkCount'], 'verifyChecks': verified['checkCount'],
        'seedRequests': seeded['httpRequests'], 'verifyRequests': verified['httpRequests'],
        'counts': verified['counts'], 'productionInputs': 0, 'externalRequests': 0}))


def test_compare_restored_detects_place_data_or_receipt_loss():
    """Use a minimal shape to ensure the generic all-row comparison covers the new table."""
    baseline = {'schema': [], 'userVersion': 0, 'applicationId': 0, 'tables': {
        'journey_places': {'columns': [], 'rows': [['synthetic-receipt', 'visited', 2, 'tombstone']]}}}
    changed = copy.deepcopy(baseline)
    changed['tables']['journey_places']['rows'][0][0] = 'lost-receipt'
    with pytest.raises(fixture.FixtureFailure):
        fixture.compare_restored(baseline, changed, fixture.Audit('verify'), 'synthetic', 0)
