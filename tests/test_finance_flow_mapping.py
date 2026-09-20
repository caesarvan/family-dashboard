"""Optional flow mapping uses real Flask imports and synthetic CSV/XLSX only."""
from contextlib import closing
import json
import sqlite3

import pytest

from finance_hub import FinanceHubError, parse_import
from test_app import app, member
from test_device_sessions import database
from test_finance_column_mapping import MAPPING, confirm, post, state
from test_financial_files import file_payload, workbook
from test_household_spaces import create_space


MAP2 = {**MAPPING, 'version': 2, 'flow': 4}
ROWS = [['date', 'amount', 'title', 'currency', '交易方向', '另方向'],
        ['2026-09-02', '10.50', '合成支出', 'CNY', '支出', '收入'],
        ['2026-09-03', '30', '合成收入', 'CNY', '收入', '支出']]


def payload(rows=ROWS, format='csv', mapping=MAP2):
    raw = workbook(rows) if format == 'xlsx' else ('\n'.join(','.join(row) for row in rows) + '\n').encode()
    return {'source': 'generic', 'kind': 'payments', 'file': file_payload(raw, 'synthetic.' + format),
            'mapping': dict(mapping)}


def transactions(app):
    with closing(sqlite3.connect(database(app))) as con:
        return con.execute('SELECT id,data,revision FROM hub_transactions ORDER BY id').fetchall()


@pytest.mark.parametrize('format', ['csv', 'xlsx'])
def test_flow_file_preview_confirm_receipt_replay_and_private_totals(app, format):
    client, headers = member(app)
    value = payload(format=format)
    before = state(app)
    preview = post(client, headers, 'preview', value)
    assert state(app) == before
    assert preview['columnSelection']['mapping'] == MAP2
    assert [row['flow'] for row in preview['rows']] == ['expense', 'income']
    assert all(row['visibility'] == 'private' for row in preview['rows'])
    request = {**value, 'previewToken': preview['previewToken'], 'requestId': 'a' * 32}
    result = post(client, headers, 'confirm', request)
    assert result['imported'] == 2 and result['duplicates'] == result['conflicts'] == 0
    frozen = state(app)
    replay = post(client, headers, 'confirm', request)
    assert replay['replayed'] and replay['receiptId'] == result['receiptId']
    assert client.get('/api/finance-hub/imports/results/' + 'a' * 32).json['receiptId'] == result['receiptId']
    assert state(app) == frozen
    overview = client.get('/api/finance-hub/overview?month=2026-09').json
    totals = next(t for t in overview['totals'] if t['currency'] == 'CNY')
    assert totals['expenseCents'] == 1050 and totals['incomeCents'] == 3000
    assert client.get('/api/finance-hub/shared?month=2026-09').json['totals'] == []


@pytest.mark.parametrize('format', ['csv', 'xlsx'])
@pytest.mark.parametrize('first_version', [1, 2])
def test_same_file_v1_v2_both_directions_keep_original_record(app, format, first_version):
    client, headers = member(app)
    first = payload(format=format, mapping=MAPPING if first_version == 1 else MAP2)
    confirm(client, headers, first)
    saved = transactions(app)
    second = payload(format=format, mapping=MAP2 if first_version == 1 else MAPPING)
    preview = post(client, headers, 'preview', second)
    assert preview['newCount'] == 0 and preview['duplicateCount'] == preview['conflictCount'] == 2
    assert all(row['duplicate'] and row['conflict'] for row in preview['rows'])
    result, _ = confirm(client, headers, second, 'b' * 32)
    assert result['imported'] == 0 and result['duplicates'] == result['conflicts'] == 2
    assert transactions(app) == saved


@pytest.mark.parametrize('mapping', [MAPPING, MAP2])
def test_manually_corrected_flow_is_not_overwritten_on_reimport(app, mapping):
    client, headers = member(app)
    value = payload(rows=ROWS[:2])
    confirm(client, headers, value)
    rid, raw, revision = transactions(app)[0]
    corrected = client.patch('/api/finance-hub/transactions/' + rid,
                             json={'revision': revision, 'flow': 'transfer'}, headers=headers)
    assert corrected.status_code == 200
    saved = transactions(app)
    value['mapping'] = dict(mapping)
    result, _ = confirm(client, headers, value, 'b' * 32)
    assert result['duplicates'] == result['conflicts'] == 1 and result['imported'] == 0
    assert transactions(app) == saved
    assert json.loads(saved[0][1])['provenance'] == json.loads(raw)['provenance']


@pytest.mark.parametrize('with_id', [False, True])
def test_historical_automatic_fingerprint_without_row_key_deduplicates(app, with_id):
    rows = [row + (['id'] if n == 0 else ['synthetic-id']) if with_id else row
            for n, row in enumerate(ROWS[:2])]
    client, headers = member(app)
    old = payload(rows); old.pop('mapping')
    confirm(client, headers, old)
    with closing(sqlite3.connect(database(app))) as con:
        rid, raw = con.execute('SELECT id,data FROM hub_transactions').fetchone()
        value = json.loads(raw); value.pop('sourceRowKey')
        con.execute('UPDATE hub_transactions SET data=? WHERE id=?', (json.dumps(value), rid)); con.commit()
    saved = transactions(app)
    result, _ = confirm(client, headers, payload(rows), 'b' * 32)
    assert result['duplicates'] == result['conflicts'] == 1 and result['imported'] == 0
    assert transactions(app) == saved


def test_flow_mapping_change_needs_preview_and_cannot_reuse_original_intent(app):
    client, headers = member(app)
    value = payload(rows=ROWS[:2]); preview = post(client, headers, 'preview', value)
    changed = {**value, 'mapping': {**MAP2, 'flow': 5}, 'previewToken': preview['previewToken']}
    before = state(app)
    assert client.post('/api/finance-hub/imports/confirm', json=changed, headers=headers).status_code == 400
    assert state(app) == before
    original = {**value, 'previewToken': preview['previewToken'], 'requestId': 'a' * 32}
    post(client, headers, 'confirm', original); saved = state(app)
    changed['requestId'] = 'a' * 32
    refusal = client.post('/api/finance-hub/imports/confirm', json=changed, headers=headers)
    assert refusal.status_code == 409 and refusal.json['code'] == 'import_request_conflict'
    assert state(app) == saved
    changed.pop('previewToken'); changed.pop('requestId')
    fresh = post(client, headers, 'preview', changed)
    assert fresh['previewToken'] and fresh['rows'][0]['flow'] == 'income' and fresh['conflictCount'] == 1
    assert state(app) == saved


def test_null_mapping_preserves_v1_auto_direction_and_unknown_values():
    rows = [['date', 'amount', 'title', 'currency', 'flow'],
            ['2026-09-02', '0', '合成', 'CNY', 'income']]
    a = parse_import(payload(rows, mapping=MAPPING))
    b = parse_import(payload(rows, mapping={**MAP2, 'flow': None}))
    assert a['rows'] == b['rows'] and b['rows'][0]['flow'] == 'income'
    assert b['columnSelection']['mapping'] == {**MAP2, 'flow': None}
    for raw, expected in [('', 'unknown'), ('借贷未定', 'unknown'), ('其他', 'unknown'),
                          ('支出', 'expense'), ('收入', 'income'), ('退款', 'refund'), ('不计收支', 'transfer')]:
        rows[1][4] = raw
        parsed = parse_import(payload(rows))
        assert parsed['rows'][0]['flow'] == expected
        if expected == 'unknown': assert any('待核对' in x for x in parsed['warnings'])
    # Keep the original conservative refund/failed/transfer precedence.
    for category, status, flow in [('退款', '成功', 'unknown'), ('普通', '交易失败', 'excluded'), ('转账', '成功', 'transfer')]:
        rows[0] = ['date', 'amount', 'title', 'currency', '交易方向', 'category', 'status']
        rows[1] = ['2026-09-02', '1', '合成', 'CNY', '支出', category, status]
        assert parse_import(payload(rows))['rows'][0]['flow'] == flow


@pytest.mark.parametrize('flow', [True, -1, 80, 6, 0, 3, '4', 4.0])
def test_invalid_flow_column_rejected(flow):
    with pytest.raises(FinanceHubError):
        parse_import(payload(mapping={**MAP2, 'flow': flow}))


@pytest.mark.parametrize('patch', [
    {'mapping': {**MAPPING, 'version': 2}}, {'mapping': {**MAPPING, 'flow': None}},
    {'mapping': {**MAP2, 'extra': 1}}, {'source': 'wechat'}, {'kind': 'orders'}])
def test_flow_mapping_version_scope_and_shape_rejected(patch):
    with pytest.raises(FinanceHubError): parse_import({**payload(), **patch})


def test_flow_mapping_private_receipt_member_household_and_tv_boundaries(app):
    client, headers = member(app)
    result, _ = confirm(client, headers, payload())
    partner, partner_headers = member(app, 2)
    assert partner.get('/api/finance-hub/imports/results/' + 'a' * 32).status_code == 404
    assert post(partner, partner_headers, 'preview', payload())['newCount'] == 2
    other, _, invitation = create_space(app)
    assert other.get(invitation['entry']).status_code == 303
    assert other.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    other_headers = {'X-CSRF-Token': other.get('/api/me').json['csrf']}
    assert other.get('/api/finance-hub/imports/results/' + 'a' * 32).status_code == 404
    accepted, _ = confirm(other, other_headers, payload())
    assert accepted['imported'] == 2 and accepted['receiptId'] != result['receiptId']
    anonymous = app.test_client()
    assert anonymous.post('/api/finance-hub/imports/preview', json=payload()).status_code == 401
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert client.post('/api/pair/approve', json={'code': pair['code'], 'name': 'synthetic-tv', 'focus': 'member1'}, headers=headers).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    assert tv.post('/api/finance-hub/imports/preview', json=payload(), headers=headers).status_code == 403
