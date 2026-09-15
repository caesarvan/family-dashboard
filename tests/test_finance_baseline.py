"""Synthetic finance sources only; no household data belongs in this repository."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from flask import Flask, g, jsonify, request

from finance_baseline import BaselineError, import_baseline, register_finance_baseline, shared_baselines


@pytest.fixture
def conn(tmp_path):
    value = sqlite3.connect(tmp_path / 'baseline.sqlite3')
    value.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE users(id TEXT PRIMARY KEY);
        INSERT INTO users VALUES('member1'),('member2');
        CREATE TABLE settings(id TEXT PRIMARY KEY,data TEXT,revision INTEGER);
        INSERT INTO settings VALUES('meta','{}',1),('finance','{"wallet":17}',1);
        CREATE TABLE private_finance(owner TEXT PRIMARY KEY,data TEXT);
        INSERT INTO private_finance VALUES('member1','{"income":29}');
    """)
    yield value
    value.close()


@pytest.fixture
def payload():
    totals = {'complete': False, 'assetCents': None, 'liabilityCents': None,
              'netCents': None, 'recordedAssetCents': 12000, 'recordedLiabilityCents': 4500}
    base = {'schemaVersion': 1, 'owner': 'member1', 'asOf': '2026-09-14',
            'importedAt': '2026-09-14T12:00:00+08:00', 'currency': 'CNY',
            'balanceAsOfStart': '2026-08-01', 'balanceAsOfEnd': '2026-09-01',
            'sourceDigest': 'a' * 64}
    def item(label, amount):
        return {'label': label, 'category': 'synthetic', 'amountCents': amount,
                'currency': 'CNY', 'asOf': '2026-08-01', 'status': 'dated_record',
                'source': 'fictional.csv:2', 'includedInRecordedSubtotal': True}
    private = {**base, 'totals': deepcopy(totals),
               'assets': [item('PRIVATE_ASSET_ACCOUNT', 12000)],
               'liabilities': [item('PRIVATE_LENDER', 4500)],
               'income': [item('PRIVATE_SALARY', 9800)],
               'sources': {'fictional.csv': {'path': 'PRIVATE_SOURCE_PATH'}}}
    shared = {**base, **totals, 'coverage': 'partial_dated_records', 'excluded': {'missingValuations': True}}
    return {'private': private, 'shared': shared}


def test_import_is_idempotent_and_preserves_other_finance(conn, payload):
    assert import_baseline(conn, **payload)['imported'] is True
    assert conn.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == 2
    assert import_baseline(conn, **payload)['imported'] is False
    changed_stamp = deepcopy(payload)
    for value in changed_stamp.values():
        value['importedAt'] = '2026-09-14T13:00:00+08:00'
    assert import_baseline(conn, **changed_stamp)['imported'] is False
    assert conn.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == 2
    assert conn.execute("SELECT data FROM settings WHERE id='finance'").fetchone()[0] == '{"wallet":17}'
    assert conn.execute('SELECT data FROM private_finance').fetchone()[0] == '{"income":29}'
    update = deepcopy(payload)
    update['private']['assets'][0]['amountCents'] = 12100
    update['private']['totals']['recordedAssetCents'] = 12100
    update['shared']['recordedAssetCents'] = 12100
    assert import_baseline(conn, **update)['revision'] == 2
    assert conn.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == 3


def test_shared_allowlist_also_filters_stored_rows(conn, payload):
    payload['shared']['income'] = 'PRIVATE_SALARY'
    payload['shared']['coverageNote'] = 'PRIVATE_SOURCE_PATH'
    payload['shared']['excluded']['account'] = 'PRIVATE_ASSET_ACCOUNT'
    import_baseline(conn, **payload)
    result = shared_baselines(conn)
    assert result[0]['recordedAssetCents'] == 12000
    assert result[0]['complete'] is False
    assert 'PRIVATE_' not in json.dumps(result)
    # Reapply the whitelist at response time, even after an older writer stored extras.
    raw = json.loads(conn.execute('SELECT shared_data FROM finance_baselines').fetchone()[0])
    raw['accountDetails'] = 'PRIVATE_ASSET_ACCOUNT'
    raw['coverageNote'] = 'PRIVATE_SALARY'
    conn.execute('UPDATE finance_baselines SET shared_data=?', (json.dumps(raw),))
    assert 'PRIVATE_' not in json.dumps(shared_baselines(conn))


@pytest.mark.parametrize('field,value', [('recordedAssetCents', True), ('recordedAssetCents', 1.2),
                                        ('recordedAssetCents', '12000'), ('recordedLiabilityCents', -1)])
def test_rejects_noninteger_or_negative_amounts(conn, payload, field, value):
    payload['shared'][field] = value
    payload['private']['totals'][field] = value
    with pytest.raises(BaselineError):
        import_baseline(conn, **payload)
    assert conn.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == 1


@pytest.mark.parametrize('mutation', ['owner', 'digest', 'schema', 'totals', 'partial_net', 'included_currency', 'included_null', 'line_sum', 'date'])
def test_rejects_inconsistent_imports(conn, payload, mutation):
    if mutation == 'owner':
        payload['shared']['owner'] = 'member2'
    elif mutation == 'digest':
        payload['shared']['sourceDigest'] = 'b' * 64
    elif mutation == 'schema':
        payload['private']['schemaVersion'] = True
    elif mutation == 'totals':
        payload['shared']['recordedAssetCents'] = 3
    elif mutation == 'partial_net':
        payload['shared']['netCents'] = payload['private']['totals']['netCents'] = -1
    elif mutation == 'included_currency':
        payload['private']['assets'][0]['currency'] = 'USD'
    elif mutation == 'included_null':
        payload['private']['assets'][0]['amountCents'] = None
    elif mutation == 'line_sum':
        payload['private']['assets'][0]['amountCents'] = 11999
    elif mutation == 'date':
        payload['private']['assets'][0]['asOf'] = '2026-02-31'
    with pytest.raises(BaselineError):
        import_baseline(conn, **payload)


def test_owner_must_exist_and_complete_math_must_reconcile(conn, payload):
    conn.execute("DELETE FROM users WHERE id='member2'")
    for value in payload.values():
        value['owner'] = 'member2'
    with pytest.raises(BaselineError):
        import_baseline(conn, **payload)
    for value in payload.values():
        value['owner'] = 'member1'
    for value in (payload['shared'], payload['private']['totals']):
        value.update(complete=True, assetCents=12000, liabilityCents=4500, netCents=7500)
    assert import_baseline(conn, **payload)['imported'] is True
    for value in (payload['shared'], payload['private']['totals']):
        value['netCents'] = 7499
    with pytest.raises(BaselineError):
        import_baseline(conn, **payload)


def test_failed_write_rolls_back_payload_and_revision(conn, payload):
    import_baseline(conn, **payload)
    conn.execute("CREATE TRIGGER fail_baseline_revision BEFORE UPDATE ON settings WHEN NEW.id='meta' BEGIN SELECT RAISE(FAIL, 'synthetic'); END")
    payload['private']['income'][0]['label'] = 'PRIVATE_CHANGED'
    with pytest.raises(sqlite3.DatabaseError):
        import_baseline(conn, **payload)
    data = conn.execute('SELECT private_data,revision FROM finance_baselines').fetchone()
    assert 'PRIVATE_CHANGED' not in data[0]
    assert data[1] == 1
    assert conn.execute("SELECT revision FROM settings WHERE id='meta'").fetchone()[0] == 2


def test_private_endpoint_uses_authenticated_owner_only(conn, payload):
    app = Flask(__name__)
    @app.before_request
    def identity():
        who = request.headers.get('X-Test-Actor')
        g.actor = {'id': who, 'role': 'tv' if who == 'screen' else 'member'} if who else None
    def require_member():
        from werkzeug.exceptions import Unauthorized, Forbidden
        if not g.actor:
            raise Unauthorized()
        if g.actor['role'] != 'member':
            raise Forbidden()
    register_finance_baseline(app, lambda: conn, require_member)
    import_baseline(conn, **payload)
    client = app.test_client()
    assert client.get('/api/finance-baseline/private').status_code == 401
    assert client.get('/api/finance-baseline/private', headers={'X-Test-Actor': 'screen'}).status_code == 403
    assert client.get('/api/finance-baseline/private?owner=member1', headers={'X-Test-Actor': 'member2'}).json is None
    first = client.get('/api/finance-baseline/private?owner=member2', headers={'X-Test-Actor': 'member1'})
    assert first.json['assets'][0]['label'] == 'PRIVATE_ASSET_ACCOUNT'
    assert first.json['revision'] == 1


def test_cli_stdin_only_sanitized_output_and_no_database_creation(conn, payload, tmp_path):
    conn.commit()
    path = conn.execute('PRAGMA database_list').fetchone()[2]
    script = Path(__file__).resolve().parents[1] / 'deploy' / 'import-finance-baseline.py'
    command = [sys.executable, str(script), '--database', path]
    first = subprocess.run(command, input=json.dumps(payload).encode(), capture_output=True)
    assert first.returncode == 0
    assert json.loads(first.stdout)['status'] == 'imported'
    assert b'PRIVATE_' not in first.stdout + first.stderr
    second = subprocess.run(command, input=json.dumps(payload).encode(), capture_output=True)
    assert json.loads(second.stdout)['status'] == 'unchanged'
    missing = tmp_path / 'must-not-create.sqlite3'
    failure = subprocess.run([sys.executable, str(script), '--database', str(missing)], input=b'{}', capture_output=True)
    assert failure.returncode == 1
    assert not missing.exists()
    assert b'Traceback' not in failure.stderr
