"""Synthetic source files and temporary databases only; never refresh real reports."""
from copy import deepcopy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from flask import Flask, g, jsonify, request
import pytest

from finance_baseline import register_finance_baseline, shared_baselines
from finance_source_bridge import (normalize_candidate, register_finance_source_bridge,
                                   REPORT_PATHS, SourceError)


def synthetic_candidate(as_of='2026-09-14', amount_cents=12000):
    """Stable public synthetic candidate, reusable by browser checks."""
    generated = as_of + 'T10:00:00+08:00'
    paths = sorted(REPORT_PATHS | {'04_Banking/accounts.csv', '03_Loans/loans.csv', '01_Income/income-history.csv'})
    q = {'knownGapsCount': 1, 'unreadableStatementsCount': 1, 'channelOnlyAdded': True, 'orderOnlyAdded': True}
    def item(identifier, source, amount, category, include=True):
        return {'id': identifier, 'label': 'SYNTHETIC_PRIVATE_' + identifier, 'category': category,
                'amountCents': amount, 'currency': 'CNY', 'asOf': '2026-08-31',
                'status': 'dated_record', 'source': source, 'includedInRecordedSubtotal': include,
                'exclusionReason': '' if include else 'historical_income_not_asset', 'dateBasis': 'synthetic_record_date'}
    return {'schemaVersion': 1, 'converterVersion': 'finance-source-v1', 'asOf': as_of,
            'sourceManifest': {'version': 1, 'configDigest': 'a'*64,
                'files': [{'path': p, 'sha256': 'b'*64, 'bytes': 123} for p in paths],
                'run': {'sha256': 'c'*64, 'generatedAt': generated, 'status': 'success', 'exitCode': 0, 'loginActionRequired': False},
                'coverage': {'requestedStart': '2025-09-14', 'requestedEnd': as_of, **q}},
            'assets': [item('bank-one', '04_Banking/accounts.csv', amount_cents, 'cash')],
            'liabilities': [item('loan-one', '03_Loans/loans.csv', 4500, 'liability')],
            'income': [item('income-one', '01_Income/income-history.csv', 9800, 'historical_income', False)],
            'spending': {'generatedAt': generated, 'requestedStart': '2025-09-14', 'requestedEnd': as_of,
                         'monthly': [{'period': '2026-08', 'currency': 'CNY', 'grossSpendCents': 1200,
                                      'refundCents': 200, 'netSpendCents': 1000, 'transactionCount': 3}], 'quality': q}}


class Problem(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def make_app(path, household='default'):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='synthetic-source-bridge-secret', HOUSEHOLD_INFO={'id': household})
    def db():
        if not hasattr(g, 'conn'):
            g.conn = sqlite3.connect(path, isolation_level=None)
            g.conn.execute('PRAGMA foreign_keys=ON')
        return g.conn
    @app.teardown_appcontext
    def close(_):
        conn = g.pop('conn', None)
        if conn:
            conn.close()
    with app.app_context():
        db().executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY);
            INSERT OR IGNORE INTO users VALUES('member1'),('member2');
            CREATE TABLE IF NOT EXISTS settings(id TEXT PRIMARY KEY,data TEXT,revision INTEGER);
            INSERT OR IGNORE INTO settings VALUES('meta','{}',1),('finance','{"wallet":17}',1);
            CREATE TABLE IF NOT EXISTS private_finance(owner TEXT PRIMARY KEY,data TEXT);
            INSERT OR IGNORE INTO private_finance VALUES('member1','{"income":29}');
            CREATE TABLE IF NOT EXISTS hub_transactions(id TEXT PRIMARY KEY,data TEXT);
            CREATE TABLE IF NOT EXISTS hub_investments(id TEXT PRIMARY KEY,data TEXT);
            INSERT OR IGNORE INTO hub_investments VALUES('existing','{"untouched":true}');
            CREATE TABLE IF NOT EXISTS audit(action TEXT,target TEXT);''')
    @app.before_request
    def actor():
        who = request.headers.get('X-Synthetic-Actor')
        g.actor = {'id': who, 'role': 'tv' if who == 'screen' else 'member'} if who else None
        if request.method == 'POST' and request.headers.get('X-CSRF-Token') != 'synthetic-csrf':
            raise Problem('CSRF', 403)
    @app.errorhandler(Problem)
    def error(exc):
        return jsonify(error=exc.message), exc.status
    def require_member():
        if not g.actor:
            raise Problem('login', 401)
        if g.actor['role'] != 'member':
            raise Problem('member', 403)
    def body():
        return request.get_json()
    def audit(action, target):
        db().execute('INSERT INTO audit VALUES(?,?)', (action, target))
    register_finance_baseline(app, db, require_member)
    register_finance_source_bridge(app, db, Problem, body, require_member, audit)
    return app


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / 'household.sqlite3'
    app = make_app(path)
    return app, app.test_client(), path


H = {'X-Synthetic-Actor': 'member1', 'X-CSRF-Token': 'synthetic-csrf'}
BASE = '/api/finance-baseline/imports/'


def stored_private(path, owner='member1'):
    """Import persistence only; real private HTTP/session scope has separate tests."""
    from spending_observations import decorate_private_spending
    with closing(sqlite3.connect(path)) as con:
        row = con.execute('SELECT private_data,revision FROM finance_baselines WHERE owner=?', (owner,)).fetchone()
        return decorate_private_spending(con, owner, {**json.loads(row[0]), 'revision': row[1]}) if row else None


def preview(client, candidate=None, headers=None):
    headers = headers or H
    state = client.get(BASE + 'status', headers=headers).json['current']
    return client.post(BASE + 'preview', headers=headers, json={
        'candidate': candidate or synthetic_candidate(), 'expectedRevision': state['revision'] if state else 0,
        'expectedSourceDigest': state['sourceDigest'] if state else None})


def confirm(client, planned, candidate=None, headers=None):
    return client.post(BASE + 'confirm', headers=headers or H,
                       json={'candidate': candidate or synthetic_candidate(), 'previewToken': planned.json['previewToken']})


def test_preview_has_no_write_recomputes_shared_then_confirm_is_persistent(setup):
    app, client, path = setup
    p = preview(client)
    assert p.status_code == 200, p.json
    assert p.json['changes'] == {'added': 3, 'updated': 0, 'preserved': 0}
    assert p.json['shared']['recordedAssetCents'] == 12000
    assert p.json['shared']['recordedLiabilityCents'] == 4500
    assert p.json['shared']['netCents'] is None
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(p.json['shared'])
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM finance_baselines').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM finance_source_receipts').fetchone()[0] == 0
    done = confirm(client, p)
    assert done.status_code == 200, done.json
    assert done.json['status'] == 'imported' and done.json['revision'] == 1
    restarted = make_app(path).test_client()
    state = restarted.get(BASE + 'status', headers=H).json
    assert state['lastReceipt']['receiptId'] == done.json['receiptId']
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(state)
    assert stored_private(path)['assets'][0]['amountCents'] == 12000
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM hub_transactions').fetchone()[0] == 0
        assert conn.execute('SELECT data FROM hub_investments').fetchone()[0] == '{"untouched":true}'
        assert conn.execute("SELECT data FROM settings WHERE id='finance'").fetchone()[0] == '{"wallet":17}'
        assert conn.execute('SELECT data FROM private_finance').fetchone()[0] == '{"income":29}'


def test_replay_and_repreview_identical_candidate_do_not_bump_baseline(setup):
    _, c, path = setup
    p = preview(c); first = confirm(c, p)
    replay = confirm(c, p)
    assert replay.json['replayed'] is True and replay.json['receiptId'] == first.json['receiptId']
    assert confirm(c, preview(c)).json['status'] == 'unchanged'
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT revision FROM finance_baselines').fetchone()[0] == 1
        assert 'previewToken' not in ' '.join(x[1] for x in conn.execute('PRAGMA table_info(finance_source_receipts)'))


def test_two_previews_use_atomic_compare_and_swap(setup):
    _, c, path = setup
    a, b = synthetic_candidate(amount_cents=12000), synthetic_candidate(amount_cents=12100)
    pa, pb = preview(c, a), preview(c, b)
    assert confirm(c, pa, a).status_code == 200
    assert confirm(c, pb, b).status_code == 409
    assert confirm(c, preview(c, b), b).json['revision'] == 2
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM finance_source_receipts').fetchone()[0] == 2


@pytest.mark.parametrize('path', ['status', 'preview', 'confirm'])
def test_tv_and_anonymous_cannot_access_bridge(setup, path):
    _, c, _ = setup
    for actor, expected in [(None, 401), ('screen', 403)]:
        h = {'X-CSRF-Token': 'synthetic-csrf'}
        if actor:
            h['X-Synthetic-Actor'] = actor
        r = c.get(BASE + path, headers=h) if path == 'status' else c.post(BASE + path, headers=h, json={})
        assert r.status_code == expected


def test_csrf_owner_and_household_binding(setup, tmp_path):
    _, c, path = setup
    p = preview(c)
    other_headers = {**H, 'X-Synthetic-Actor': 'member2'}
    assert confirm(c, p, headers=other_headers).status_code == 403
    other = make_app(tmp_path / 'other.sqlite3', 'different-household').test_client()
    assert confirm(other, p).status_code == 403
    assert c.post(BASE + 'preview', headers={'X-Synthetic-Actor': 'member1'}, json={}).status_code == 403
    assert confirm(c, p).status_code == 200
    assert c.get(BASE + 'status?owner=member1', headers=other_headers).json['current'] is None


@pytest.mark.parametrize('mutation', ['owner', 'shared', 'unknown_manifest', 'duplicate_id', 'foreign_include', 'null_include',
    'float_amount', 'income_include', 'false_success', 'failed_run', 'missing_report', 'empty_file', 'bad_digest',
    'future_record', 'bad_month_math', 'duplicate_month', 'unexplained_exclusion', 'missing_date'])
def test_rejects_bad_candidates_without_mutation(setup, mutation):
    _, c, path = setup
    x = synthetic_candidate()
    if mutation == 'owner': x['owner'] = 'member2'
    elif mutation == 'shared': x['shared'] = {'recordedAssetCents': 1}
    elif mutation == 'unknown_manifest': x['sourceManifest']['privatePath'] = 'SYNTHETIC_PRIVATE'
    elif mutation == 'duplicate_id': x['liabilities'][0]['id'] = x['assets'][0]['id']
    elif mutation == 'foreign_include': x['assets'][0]['currency'] = 'USD'
    elif mutation == 'null_include': x['assets'][0]['amountCents'] = None
    elif mutation == 'float_amount': x['assets'][0]['amountCents'] = 1.5
    elif mutation == 'income_include': x['income'][0].update(includedInRecordedSubtotal=True, exclusionReason='')
    elif mutation == 'false_success': x['sourceManifest']['run']['exitCode'] = False
    elif mutation == 'failed_run': x['sourceManifest']['run']['status'] = 'partial'
    elif mutation == 'missing_report': x['sourceManifest']['files'] = x['sourceManifest']['files'][:-1]
    elif mutation == 'empty_file': x['sourceManifest']['files'][0]['bytes'] = 0
    elif mutation == 'bad_digest': x['sourceManifest']['files'][0]['sha256'] = 'invalid'
    elif mutation == 'future_record': x['assets'][0]['asOf'] = '2099-01-01'
    elif mutation == 'bad_month_math': x['spending']['monthly'][0]['netSpendCents'] = 10
    elif mutation == 'duplicate_month': x['spending']['monthly'].append(deepcopy(x['spending']['monthly'][0]))
    elif mutation == 'unexplained_exclusion': x['assets'][0]['includedInRecordedSubtotal'] = False
    elif mutation == 'missing_date': x['assets'][0]['asOf'] = ''
    assert preview(c, x).status_code == 400
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM finance_baselines').fetchone()[0] == 0


@pytest.mark.parametrize('mutation', ['older_source', 'older_record', 'lost_amount', 'lost_record', 'lost_coverage', 'lost_source'])
def test_missing_or_regressed_sources_preserve_old_snapshot(setup, mutation):
    _, c, path = setup
    assert confirm(c, preview(c)).status_code == 200
    x = synthetic_candidate()
    if mutation == 'older_source': x = synthetic_candidate(as_of='2026-09-13')
    elif mutation == 'older_record': x['assets'][0]['asOf'] = '2026-08-30'
    elif mutation == 'lost_amount': x['assets'][0].update(amountCents=None, includedInRecordedSubtotal=False, exclusionReason='missing')
    elif mutation == 'lost_record': x['income'] = []
    elif mutation == 'lost_coverage':
        x['sourceManifest']['coverage']['requestedStart'] = x['spending']['requestedStart'] = '2026-01-01'
    elif mutation == 'lost_source':
        x['income'] = []
        x['sourceManifest']['files'] = [p for p in x['sourceManifest']['files'] if p['path'] != '01_Income/income-history.csv']
    assert preview(c, x).status_code == 409
    assert stored_private(path)['revision'] == 1


def test_legacy_mapping_preserves_identity_and_foreign_values_do_not_sum(setup):
    _, c, path = setup
    assert confirm(c, preview(c)).status_code == 200
    x = synthetic_candidate()
    x['assets'][0].update(id='bank-stable-new', legacyId='bank-one', currency='USD', includedInRecordedSubtotal=False, exclusionReason='no_exchange_rate')
    p = preview(c, x)
    assert p.status_code == 200, p.json
    assert p.json['shared']['recordedAssetCents'] == 0
    assert p.json['shared']['excluded']['foreignCurrencyConversion'] is True
    assert confirm(c, p, x).status_code == 200
    with sqlite3.connect(path) as conn:
        assert 'SYNTHETIC_PRIVATE' not in json.dumps(shared_baselines(conn))


def test_tampered_candidate_and_failed_database_write_keep_receipt_and_data_atomic(setup):
    _, c, path = setup
    p = preview(c)
    x = synthetic_candidate(amount_cents=12001)
    assert confirm(c, p, x).status_code == 403
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER deny_receipt BEFORE INSERT ON finance_source_receipts BEGIN SELECT RAISE(FAIL,'synthetic failure'); END")
    with pytest.raises(sqlite3.DatabaseError):
        confirm(c, p)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM finance_baselines').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM audit').fetchone()[0] == 0


def load_prepare():
    path = Path(__file__).resolve().parents[1] / 'deploy/prepare-finance-source.py'
    spec = importlib.util.spec_from_file_location('synthetic_prepare_finance', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def source_files(tmp_path):
    root = tmp_path / 'synthetic-source'; root.mkdir()
    files = {
        '04_Banking/accounts.csv': '统计日期,机构,账户类型,尾号,币种,余额,用途,数据来源\n2026-08-31,SYNTHETIC_BANK,cash,FAKE,CNY,120.00,test,test\n',
        '03_Loans/loans.csv': '贷款名称,当前余额,数据来源\nSYNTHETIC_LOAN,45.00,test\n',
        '05_Investments/holdings-template.csv': '统计日期,平台,标的,币种,当前市值\n2026-08-31,SYNTHETIC_BROKER,SYNTHETIC_STOCK,USD,12.00\n',
        '05_Investments/property-valuation.csv': '统计日期,房产地址,当前估值\n2026-08-31,SYNTHETIC_PROPERTY,\n',
        '01_Income/income-history.csv': '年度或月份,雇主,收入类型,税前金额\n2026-08,SYNTHETIC_EMPLOYER,historical,98.00\n',
        '08_Budgets/all-email-spend-transactions-12m.json': '[]',
        '08_Budgets/statement-attachment-inventory-12m.json': '[]',
    }
    generated = '2026-09-14T10:00:00+08:00'
    files['08_Budgets/all-email-spend-report-12m.json'] = json.dumps({
        'quality': {'generated_at': generated, 'encrypted_unreadable_statements': ['SYNTHETIC'], 'channel_only_spend_added': 1, 'order_only_spend_added': 1},
        'coverage': {'requested_start': '2025-09-14', 'requested_end': '2026-09-14', 'known_gaps': ['SYNTHETIC']},
        'monthly': [{'period': '2026-08', 'currency': 'CNY', 'gross_spend': '12.00', 'refunds': '2.00', 'net_spend': '10.00', 'transaction_count': 3}]})
    for p, text in files.items():
        f = root / p; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text, encoding='utf-8')
    run_path = tmp_path / 'run-2026-09-14.json'
    def write_run():
        run_path.write_text(json.dumps({'status': 'success', 'exit_code': 0, 'login_action_required': False, 'generated_at': generated,
            'files': [{'path': str(root/p), 'bytes': (root/p).stat().st_size,
                       'modified_at': datetime.fromtimestamp((root/p).stat().st_mtime, timezone.utc).isoformat()} for p in sorted(REPORT_PATHS)]}), encoding='utf-8')
    write_run()
    def mapping(identifier, match, include=True, **extra):
        return {'id': identifier, 'match': match, 'label': 'SYNTHETIC_PRIVATE_' + identifier, 'include': include,
                'exclusionReason': '' if include else 'excluded_synthetic', **extra}
    sources = [
        {'kind': 'banking', 'path': '04_Banking/accounts.csv', 'records': [mapping('bank-one', {'尾号': 'FAKE'})]},
        {'kind': 'loans', 'path': '03_Loans/loans.csv', 'records': [mapping('loan-one', {'贷款名称': 'SYNTHETIC_LOAN'}, date='2026-08-31', dateBasis='manual_synthetic_reconciliation')]},
        {'kind': 'holdings', 'path': '05_Investments/holdings-template.csv', 'records': [mapping('investment-one', {'标的': 'SYNTHETIC_STOCK'}, False)]},
        {'kind': 'property', 'path': '05_Investments/property-valuation.csv', 'records': [mapping('property-one', {'房产地址': 'SYNTHETIC_PROPERTY'}, False)]},
        {'kind': 'income', 'path': '01_Income/income-history.csv', 'records': [mapping('income-one', {'年度或月份': '2026-08'}, False)]},
    ]
    config_path = tmp_path / 'private-config.json'
    config = {'schemaVersion': 1, 'sourceRoot': str(root), 'runFile': str(run_path), 'sources': sources}
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
    return root, run_path, config_path, config, write_run


def test_all_local_adapters_freeze_hashes_and_repeated_prepare_is_stable(tmp_path):
    root, run, config_path, _, _ = source_files(tmp_path)
    output = tmp_path / 'private-output/finance-source-candidate.json'
    module = load_prepare()
    first = module.prepare(config_path, output)
    before = output.read_bytes()
    assert module.prepare(config_path, output) == first
    assert output.read_bytes() == before
    candidate = json.loads(before)
    _, private, shared, _ = normalize_candidate(candidate, 'member1')
    assert private['totals']['recordedAssetCents'] == 12000
    assert private['totals']['recordedLiabilityCents'] == 4500
    assert len(private['assets']) == 3
    assert private['income'][0]['dateBasis'] == 'income_period_end_not_receipt_date'
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(first)
    assert str(root) not in output.read_text('utf-8')
    assert 'match' not in output.read_text('utf-8')


@pytest.mark.parametrize('mutation', ['failed_run', 'missing_source', 'wrong_bytes', 'wrong_mtime', 'wrong_generated',
    'unmapped', 'duplicate_mapping', 'missing_date', 'invalid_money', 'subcent_money', 'path_escape', 'unknown_column'])
def test_bad_local_source_preserves_previous_candidate(tmp_path, mutation):
    root, run_path, config_path, config, write_run = source_files(tmp_path)
    module = load_prepare(); output = tmp_path / 'candidate.json'; module.prepare(config_path, output)
    before = output.read_bytes()
    run = json.loads(run_path.read_text('utf-8'))
    if mutation == 'failed_run': run['exit_code'] = 1
    elif mutation == 'missing_source': (root/'04_Banking/accounts.csv').unlink()
    elif mutation == 'wrong_bytes': run['files'][0]['bytes'] += 1
    elif mutation == 'wrong_mtime': run['files'][0]['modified_at'] = '2020-01-01T00:00:00+00:00'
    elif mutation == 'wrong_generated': run['generated_at'] = '2026-09-14T11:00:00+08:00'
    elif mutation == 'unmapped':
        with (root/'04_Banking/accounts.csv').open('a', encoding='utf-8') as f: f.write('2026-08-31,SYNTHETIC,cash,NEW,CNY,1.00,test,test\n')
    elif mutation == 'duplicate_mapping': config['sources'][0]['records'].append(deepcopy(config['sources'][0]['records'][0]))
    elif mutation == 'missing_date': config['sources'][1]['records'][0].pop('date')
    elif mutation in ('invalid_money', 'subcent_money'):
        path = root/'04_Banking/accounts.csv'; path.write_text(path.read_text('utf-8').replace('120.00', 'unclear' if mutation == 'invalid_money' else '1.001'), encoding='utf-8')
    elif mutation == 'path_escape': config['sources'][0]['path'] = '../outside.csv'
    elif mutation == 'unknown_column': config['sources'][0]['records'][0]['match'] = {'missing-column': 'SYNTHETIC'}
    run_path.write_text(json.dumps(run), encoding='utf-8')
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
    with pytest.raises((ValueError, OSError)):
        module.prepare(config_path, output)
    assert output.read_bytes() == before


def test_input_changes_during_freeze_are_rejected(tmp_path, monkeypatch):
    root, _, config_path, _, _ = source_files(tmp_path)
    module = load_prepare(); output = tmp_path/'candidate.json'; module.prepare(config_path, output)
    before = output.read_bytes(); original = module.normalize_candidate
    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        p = root/'04_Banking/accounts.csv'; p.write_text(p.read_text('utf-8')+'\n', encoding='utf-8')
        return result
    monkeypatch.setattr(module, 'normalize_candidate', changing)
    with pytest.raises(module.PrepareError):
        module.prepare(config_path, output)
    assert output.read_bytes() == before


def test_cli_outputs_no_private_values_and_does_not_write_database(tmp_path):
    root, _, config, _, _ = source_files(tmp_path)
    script = Path(__file__).resolve().parents[1]/'deploy/prepare-finance-source.py'
    output = tmp_path/'finance-source-candidate.json'
    result = subprocess.run([sys.executable, str(script), '--config', str(config), '--output', str(output)], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert b'SYNTHETIC_PRIVATE' not in result.stdout + result.stderr
    assert str(root).encode() not in result.stdout + result.stderr
    assert json.loads(result.stdout)['status'] == 'prepared'
    assert not list(tmp_path.rglob('*.sqlite3'))


def test_private_configuration_or_output_in_source_repository_is_rejected(tmp_path):
    _, _, config, _, _ = source_files(tmp_path)
    module = load_prepare()
    with pytest.raises(module.PrepareError):
        module.prepare(config, module.ROOT/'must-not-create-candidate.json')
    assert not (module.ROOT/'must-not-create-candidate.json').exists()


@pytest.mark.parametrize('target', ['source', 'config', 'run'])
def test_output_cannot_replace_source_configuration_or_run(tmp_path, target):
    root, run, config, _, _ = source_files(tmp_path)
    output = {'source': root/'04_Banking/accounts.csv', 'config': config, 'run': run}[target]
    original = output.read_bytes()
    module = load_prepare()
    with pytest.raises(module.PrepareError):
        module.prepare(config, output)
    assert output.read_bytes() == original


def test_unvested_or_unconfirmed_record_is_never_counted_as_confirmed_asset(setup):
    _, c, _ = setup
    x = synthetic_candidate()
    x['assets'][0]['status'] = 'unvested_compensation'
    assert preview(c, x).status_code == 400
    x['assets'][0].update(includedInRecordedSubtotal=False, exclusionReason='not_vested')
    p = preview(c, x)
    assert p.status_code == 200
    assert p.json['shared']['recordedAssetCents'] == 0
    assert p.json['shared']['excluded']['unvestedCompensation'] is True


def test_concurrent_confirm_only_one_candidate_wins(setup):
    app, c, path = setup
    first, second = synthetic_candidate(), synthetic_candidate(amount_cents=12100)
    p1, p2 = preview(c, first), preview(c, second)
    def send(pair):
        p, candidate = pair
        return confirm(app.test_client(), p, candidate).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, [(p1, first), (p2, second)]))
    assert sorted(results) == [200, 409]
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT revision FROM finance_baselines').fetchone()[0] == 1


def test_source_local_date_is_not_confused_with_utc_today():
    instant = datetime.now(timezone(timedelta(hours=14))) - timedelta(seconds=1)
    x = synthetic_candidate(as_of=instant.date().isoformat())
    x['sourceManifest']['run']['generatedAt'] = x['spending']['generatedAt'] = instant.isoformat()
    normalize_candidate(x, 'member1')


def test_real_application_guards_and_household_router(tmp_path, monkeypatch):
    from app import create_app
    monkeypatch.setenv('MEMBER1_PASSWORD', 'synthetic-member-one-password')
    monkeypatch.setenv('MEMBER2_PASSWORD', 'synthetic-member-two-password')
    app = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path/'runtime'), 'SECRET_KEY': 'synthetic-runtime-source-secret',
                      'MEMBER1_PASSWORD': 'synthetic-member-one-password', 'MEMBER2_PASSWORD': 'synthetic-member-two-password'})
    if 'finance_source_bridge' not in app.extensions:
        pytest.fail('finance source bridge registration missing')
    c = app.test_client()
    assert c.get(BASE+'status').status_code == 401
    assert c.post('/api/login', json={'username':'member1','password':'synthetic-member-one-password'}).status_code == 200
    csrf = c.get('/api/me').json['csrf']
    assert c.post(BASE+'preview', json={}).status_code == 403
    data = {'candidate': synthetic_candidate(), 'expectedRevision':0, 'expectedSourceDigest':None}
    p = c.post(BASE+'preview', json=data, headers={'X-CSRF-Token':csrf})
    assert p.status_code == 200, p.json
    assert c.get(BASE+'status', headers={'X-Display-Mode':'tv'}).status_code in (401,403)


def _write_config(path, config):
    path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')


def _write_csv(path, fields, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(fields)
    writer.writerows(rows)
    path.write_bytes(stream.getvalue().encode('utf-8'))


def _bank_balance(root, value):
    path = root/'04_Banking/accounts.csv'
    reader = csv.DictReader(io.StringIO(path.read_text('utf-8-sig')))
    rows = list(reader)
    rows[0]['余额'] = value
    _write_csv(path, reader.fieldnames, [[row[key] for key in reader.fieldnames] for row in rows])


def test_mixed_bank_types_through_cli_preview_and_confirm_do_not_touch_other_finance(tmp_path, setup):
    root, _, config_path, config, _ = source_files(tmp_path)
    source = config['sources'][0]
    fields = ['统计日期','机构','账户类型','尾号','币种','余额','用途','数据来源']
    rows = [['2026-08-31','SYNTHETIC_BANK','asset','FAKE','CNY','120.00','test','test']]
    for identifier, value, sign, currency, include in [
        ('debt-positive','30.00','positive','CNY',True),
        ('debt-negative','-40.00','negative','CNY',True),
        ('debt-foreign','-5.00','negative','USD',False),
    ]:
        rows.append(['2026-08-31','SYNTHETIC_BANK','source-label-is-not-classification',identifier,currency,value,'test','test'])
        source['records'].append({'id': identifier, 'label':'SYNTHETIC_PRIVATE_'+identifier, 'match':{'尾号':identifier},
                                  'include':include, 'exclusionReason':'' if include else 'foreign_currency_no_conversion',
                                  'recordType':'liability', 'liabilitySign':sign})
    _write_csv(root/source['path'], fields, rows)
    _write_config(config_path, config)
    output = tmp_path/'mixed-candidate.json'
    script = Path(__file__).resolve().parents[1]/'deploy/prepare-finance-source.py'
    process = subprocess.run([sys.executable, str(script), '--config', str(config_path), '--output', str(output)], capture_output=True)
    assert process.returncode == 0, process.stderr
    assert b'SYNTHETIC_PRIVATE' not in process.stdout + process.stderr
    assert str(root).encode() not in process.stdout + process.stderr
    candidate = json.loads(output.read_bytes())
    debts = {x['id']: x for x in candidate['liabilities']}
    assert debts['debt-positive']['amountCents'] == 3000
    assert debts['debt-negative']['amountCents'] == 4000
    assert debts['debt-foreign']['amountCents'] == 500 and debts['debt-foreign']['currency'] == 'USD'
    assert all(debts[key]['category'] == 'liability' for key in ('debt-positive','debt-negative','debt-foreign'))
    assert next(x for x in candidate['assets'] if x['id']=='bank-one')['amountCents'] == 12000
    assert 'recordType' not in output.read_text('utf-8') and 'match' not in output.read_text('utf-8')
    _, client, database = setup
    planned = preview(client, candidate)
    assert planned.status_code == 200, planned.json
    assert planned.json['shared']['recordedAssetCents'] == 12000
    assert planned.json['shared']['recordedLiabilityCents'] == 11500
    assert planned.json['shared']['netCents'] is None
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(planned.json['shared'])
    with sqlite3.connect(database) as con:
        assert con.execute('SELECT count(*) FROM finance_baselines').fetchone()[0] == 0
    accepted = confirm(client, planned, candidate)
    assert accepted.status_code == 200, accepted.json
    assert confirm(client, planned, candidate).json['replayed'] is True
    with sqlite3.connect(database) as con:
        assert con.execute('SELECT count(*) FROM hub_transactions').fetchone()[0] == 0
        assert con.execute('SELECT data FROM hub_investments').fetchone()[0] == '{"untouched":true}'
        assert con.execute("SELECT data FROM settings WHERE id='finance'").fetchone()[0] == '{"wallet":17}'
        assert con.execute('SELECT data FROM private_finance').fetchone()[0] == '{"income":29}'
    assert stored_private(database, 'member2') is None
    assert client.post(BASE+'preview', json={'candidate':candidate,'expectedRevision':1,'expectedSourceDigest':accepted.json['sourceDigest']},
                       headers={'X-Synthetic-Actor':'screen','X-CSRF-Token':'synthetic-csrf'}).status_code == 403


@pytest.mark.parametrize('value,sign,expected', [('37.25','positive',3725),('-37.25','negative',3725),
    ('0','positive',0),('-0','negative',0),('','negative',None)])
def test_explicit_bank_liability_sign_zero_and_missing_balance(tmp_path, value, sign, expected):
    root, _, config_path, config, _ = source_files(tmp_path)
    mapping = config['sources'][0]['records'][0]
    mapping.update(recordType='liability', liabilitySign=sign)
    if expected is None:
        mapping.update(include=False, exclusionReason='missing_balance_not_zero')
    _bank_balance(root, value)
    _write_config(config_path, config)
    output = tmp_path/'candidate.json'
    load_prepare().prepare(config_path, output)
    candidate = json.loads(output.read_bytes())
    bank = next(x for x in candidate['liabilities'] if x['id']=='bank-one')
    assert bank['amountCents'] == expected and bank['category'] == 'liability'
    assert not any(x['id']=='bank-one' for x in candidate['assets'])
    if expected is None:
        assert bank['status'] == 'missing_valuation' and bank['includedInRecordedSubtotal'] is False


@pytest.mark.parametrize('patch,value', [
    ({'recordType':'liability'},'12.00'),
    ({'recordType':'liability','liabilitySign':'unknown'},'12.00'),
    ({'recordType':'liability','liabilitySign':True},'12.00'),
    ({'recordType':'unknown'},'12.00'),
    ({'recordType':None},'12.00'),
    ({'recordType':'asset','liabilitySign':'positive'},'12.00'),
    ({'liabilitySign':'negative'},'12.00'),
    ({},'-12.00'),
    ({'recordType':'liability','liabilitySign':'positive'},'-12.00'),
    ({'recordType':'liability','liabilitySign':'negative'},'12.00'),
    ({'recordType':'liability','liabilitySign':'negative'},'-1.001'),
    ({'recordType':'liability','liabilitySign':'negative'},''),
])
def test_invalid_bank_declarations_preserve_previous_candidate(tmp_path, patch, value):
    root, _, config_path, config, _ = source_files(tmp_path)
    module = load_prepare(); output = tmp_path/'candidate.json'
    module.prepare(config_path, output); before = output.read_bytes()
    config['sources'][0]['records'][0].update(patch)
    _bank_balance(root, value)
    _write_config(config_path, config)
    with pytest.raises(ValueError):
        module.prepare(config_path, output)
    assert output.read_bytes() == before


@pytest.mark.parametrize('source_index', [1,2,3,4])
def test_bank_classification_configuration_is_rejected_for_other_adapters(tmp_path, source_index):
    _, _, config_path, config, _ = source_files(tmp_path)
    module = load_prepare(); output = tmp_path/'candidate.json'
    module.prepare(config_path, output); before = output.read_bytes()
    config['sources'][source_index]['records'][0].update(recordType='liability', liabilitySign='positive')
    _write_config(config_path, config)
    with pytest.raises(ValueError): module.prepare(config_path, output)
    assert output.read_bytes() == before


def test_foreign_bank_liability_cannot_be_included_as_cny(tmp_path):
    root, _, config_path, config, _ = source_files(tmp_path)
    config['sources'][0]['records'][0].update(recordType='liability', liabilitySign='positive')
    path = root/'04_Banking/accounts.csv'
    path.write_text(path.read_text('utf-8').replace(',CNY,',',USD,'), encoding='utf-8')
    _write_config(config_path, config)
    output = tmp_path/'candidate.json'
    with pytest.raises(ValueError): load_prepare().prepare(config_path, output)
    assert not output.exists()


def test_existing_bank_liability_legacy_id_updates_within_same_collection(tmp_path, setup):
    root, _, config_path, config, _ = source_files(tmp_path)
    mapping = config['sources'][0]['records'][0]
    mapping.update(recordType='liability', liabilitySign='negative')
    _bank_balance(root, '-120.00'); _write_config(config_path, config)
    module = load_prepare(); output = tmp_path/'candidate.json'; module.prepare(config_path, output)
    original = json.loads(output.read_bytes()); _, client, database = setup
    assert confirm(client, preview(client, original), original).status_code == 200
    mapping.update(id='stable-bank-liability', legacyId='bank-one')
    _bank_balance(root, '-121.00'); _write_config(config_path, config)
    module.prepare(config_path, output); updated = json.loads(output.read_bytes())
    planned = preview(client, updated)
    assert planned.status_code == 200, planned.json
    assert planned.json['changes']['added'] == 0
    assert confirm(client, planned, updated).json['revision'] == 2
    saved = stored_private(database)
    assert next(x for x in saved['liabilities'] if x['id']=='stable-bank-liability')['amountCents'] == 12100
    assert not any(x['id']=='bank-one' for x in saved['assets']+saved['liabilities'])


@pytest.mark.parametrize('rename_with_legacy', [False,True])
def test_cross_collection_asset_to_liability_still_rejects_and_preserves_baseline(tmp_path, setup, rename_with_legacy):
    _, _, config_path, config, _ = source_files(tmp_path)
    module = load_prepare(); output = tmp_path/'candidate.json'; module.prepare(config_path, output)
    original = json.loads(output.read_bytes()); _, client, database = setup
    assert confirm(client, preview(client, original), original).status_code == 200
    before = stored_private(database)
    mapping = config['sources'][0]['records'][0]
    mapping.update(recordType='liability', liabilitySign='positive')
    if rename_with_legacy: mapping.update(id='changed-bucket', legacyId='bank-one')
    _write_config(config_path, config); module.prepare(config_path, output)
    assert preview(client, json.loads(output.read_bytes())).status_code == 409
    assert stored_private(database) == before
    with sqlite3.connect(database) as con:
        assert con.execute('SELECT count(*) FROM finance_source_receipts').fetchone()[0] == 1


def _notes_source(root, config, kind='holdings', *, short=True, notes=''):
    source = next(x for x in config['sources'] if x['kind']==kind)
    path = root/source['path']
    reader = csv.DictReader(io.StringIO(path.read_text('utf-8-sig')))
    rows = list(reader); fields = reader.fieldnames+['备注']
    values = [[row[key] for key in reader.fieldnames] + ([] if short else [notes]) for row in rows]
    _write_csv(path, fields, values)
    return source, path


def _review_notes(source, path):
    source.update(allowMissingTrailingNotes=True, reviewedTrailingNotesFileSha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize('kind', ['holdings','property','income'])
def test_reviewed_known_trailing_notes_omission_is_stable_and_hash_bound(tmp_path, kind):
    root, _, config_path, config, _ = source_files(tmp_path)
    source, path = _notes_source(root, config, kind)
    _review_notes(source, path); _write_config(config_path, config)
    module = load_prepare(); output = tmp_path/'candidate.json'
    first = module.prepare(config_path, output); before = output.read_bytes()
    assert module.prepare(config_path, output) == first and output.read_bytes() == before
    candidate = json.loads(before)
    assert next(x for x in candidate['sourceManifest']['files'] if x['path']==source['path'])['sha256'] == source['reviewedTrailingNotesFileSha256']
    assert 'reviewedTrailingNotesFileSha256' not in output.read_text('utf-8')
    # Even a harmless byte change requires the owner to review and bind the new file.
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError): module.prepare(config_path, output)
    assert output.read_bytes() == before
    _review_notes(source, path); _write_config(config_path, config)
    module.prepare(config_path, output); renewed = json.loads(output.read_bytes())
    assert renewed['sourceManifest']['configDigest'] != candidate['sourceManifest']['configDigest']
    for key in ('assets','liabilities','income'): assert renewed[key] == candidate[key]


@pytest.mark.parametrize('note', ['', 'quoted, note\nsecond line'])
def test_full_optional_notes_column_needs_no_compatibility_policy(tmp_path, note):
    root, _, config_path, config, _ = source_files(tmp_path)
    _notes_source(root, config, short=False, notes=note)
    output = tmp_path/'candidate.json'
    load_prepare().prepare(config_path, output)
    assert json.loads(output.read_bytes())['assets'][1]['amountCents'] == 1200


@pytest.mark.parametrize('mutation', ['no_policy','missing_hash','wrong_hash','invalid_hash','policy_false_with_hash','policy_not_bool',
    'missing_two_columns','extra_column','notes_not_last','missing_amount_header','missing_date_header','empty_header','duplicate_header','unclosed_quote'])
def test_unsupported_notes_or_required_structure_preserves_old_candidate(tmp_path, mutation):
    root, _, config_path, config, _ = source_files(tmp_path)
    module = load_prepare(); output = tmp_path/'candidate.json'; module.prepare(config_path, output); before = output.read_bytes()
    source, path = _notes_source(root, config)
    content = path.read_text('utf-8')
    if mutation == 'missing_two_columns':
        lines = content.splitlines(); lines[1] = lines[1].rsplit(',',1)[0]; content = '\n'.join(lines)+'\n'
    elif mutation == 'extra_column': content = content.rstrip('\n')+',extra,extra\n'
    elif mutation == 'notes_not_last': content = content.replace('当前市值,备注','备注,当前市值')
    elif mutation == 'missing_amount_header': content = content.replace('当前市值','unknown_amount')
    elif mutation == 'missing_date_header': content = content.replace('统计日期','unknown_date')
    elif mutation == 'empty_header': content = content.replace('平台,',',',1)
    elif mutation == 'duplicate_header': content = content.replace('平台,','标的,',1)
    elif mutation == 'unclosed_quote': content = content.replace(',12.00',',"12.00')
    path.write_text(content, encoding='utf-8')
    _review_notes(source, path)
    if mutation == 'no_policy':
        source.pop('allowMissingTrailingNotes'); source.pop('reviewedTrailingNotesFileSha256')
    elif mutation == 'missing_hash': source.pop('reviewedTrailingNotesFileSha256')
    elif mutation == 'wrong_hash': source['reviewedTrailingNotesFileSha256'] = '0'*64
    elif mutation == 'invalid_hash': source['reviewedTrailingNotesFileSha256'] = True
    elif mutation == 'policy_false_with_hash': source['allowMissingTrailingNotes'] = False
    elif mutation == 'policy_not_bool': source['allowMissingTrailingNotes'] = 'true'
    _write_config(config_path, config)
    with pytest.raises((ValueError,csv.Error)): module.prepare(config_path, output)
    assert output.read_bytes() == before


@pytest.mark.parametrize('kind', ['banking','loans'])
def test_trailing_notes_policy_does_not_expand_known_source_allowlist(tmp_path, kind):
    root, _, config_path, config, _ = source_files(tmp_path)
    source, path = _notes_source(root, config, kind)
    _review_notes(source, path); _write_config(config_path, config)
    output = tmp_path/'candidate.json'
    with pytest.raises(ValueError): load_prepare().prepare(config_path, output)
    assert not output.exists()


def test_reviewed_tail_policy_is_not_proof_against_ambiguous_middle_delimiter_loss(tmp_path):
    root, _, config_path, config, _ = source_files(tmp_path)
    source = config['sources'][2]; path = root/source['path']
    # Valid interpretation: value 1234 and empty quantity, omitted trailing note.
    # Indistinguishable alternative: a middle delimiter between 12 and 34 was lost.
    # The default rejects this short row. Opt-in only attests the reviewed format;
    # it must never be described as automatically verifying the financial value.
    path.write_text('统计日期,平台,标的,币种,当前市值,数量,备注\n2026-08-31,SYNTHETIC_BROKER,SYNTHETIC_STOCK,USD,1234,\n', encoding='utf-8')
    module = load_prepare(); output = tmp_path/'candidate.json'
    with pytest.raises(ValueError): module.prepare(config_path, output)
    assert not output.exists()
    _review_notes(source, path); _write_config(config_path, config)
    module.prepare(config_path, output)
    assert next(x for x in json.loads(output.read_bytes())['assets'] if x['id']=='investment-one')['amountCents'] == 123400


def test_explicit_configuration_choices_change_digest_without_changing_source_bytes(tmp_path):
    root, _, config_path, config, _ = source_files(tmp_path)
    source, path = _notes_source(root, config, short=False)
    module = load_prepare(); output = tmp_path/'candidate.json'; module.prepare(config_path, output)
    implicit = json.loads(output.read_bytes()); original_bytes = path.read_bytes()
    config['sources'][0]['records'][0]['recordType'] = 'asset'
    _review_notes(source, path); _write_config(config_path, config)
    module.prepare(config_path, output); explicit = json.loads(output.read_bytes())
    assert path.read_bytes() == original_bytes
    assert implicit['sourceManifest']['files'] == explicit['sourceManifest']['files']
    assert implicit['sourceManifest']['configDigest'] != explicit['sourceManifest']['configDigest']
    for key in ('assets','liabilities','income'): assert implicit[key] == explicit[key]


def test_cli_income_period_date_cannot_bypass_legacy_snapshot_date_guard(tmp_path, setup):
    _, _, config_path, _, _ = source_files(tmp_path)
    output = tmp_path/'candidate.json'; load_prepare().prepare(config_path, output)
    candidate = json.loads(output.read_bytes())
    legacy = deepcopy(candidate)
    legacy['income'][0].update(asOf='2026-09-09', dateBasis='synthetic_legacy_fixed_snapshot_date')
    _, client, database = setup
    assert confirm(client, preview(client, legacy), legacy).status_code == 200
    before = stored_private(database)
    result = preview(client, candidate)
    assert result.status_code == 409 and '日期倒退' in result.json['error']
    assert stored_private(database) == before
