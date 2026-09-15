"""Synthetic holdings only; no bank connections, prices, or private input."""
import base64
import csv
import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from investment_import import COLUMNS, PREFIX, TEXT_COLUMNS
from test_finance_hub import hub, investment, overview
from test_financial_files import workbook, sheet_xml, file_payload, FILE_PARSE_SLOT
from test_app import app, member


def holding(**changes):
    return {'holdingKey': 'synthetic-holding-1', 'name': 'SYNTHETIC_FUND', 'institution': 'SYNTHETIC_BROKER',
            'assetType': '基金', 'currency': 'USD', 'quantity': '10.25', 'cost': '100.50', 'value': '120.75',
            'asOf': '2026-01-10', 'note': 'synthetic only', 'recordId': '', **changes}


def csv_payload(rows=None, *, source='合成账户甲', headers=None, encoding='utf-8', content=None):
    headers = COLUMNS if headers is None else headers
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(headers)
    for row in ([holding()] if rows is None else rows):
        writer.writerow([row.get(k, '') for k in headers])
    raw = (out.getvalue() if content is None else content).encode(encoding)
    return {'sourceName': source, 'file': file_payload(raw, name='holdings.csv')}


def preview(client, payload=None, **kw):
    return client.post(PREFIX + '/preview', json=payload or csv_payload(), **kw)


def confirm(client, p, **kw):
    assert p.status_code == 200, p.json
    assert p.json['previewToken'], p.json
    return client.post(PREFIX + '/confirm', json={'previewToken': p.json['previewToken']}, **kw)


def saved(client, uid='member1'):
    return overview(client, uid)['investments']


def business(target):
    with sqlite3.connect(target) as con:
        return {table: con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in
                ['hub_transactions', 'hub_imports', 'hub_investments', 'hub_budgets', 'hub_reconciliations',
                 'hub_investment_sources', 'hub_investment_links', 'hub_investment_import_receipts', 'settings', 'audit']}


def test_preview_confirm_roundtrip_replay_and_no_other_finance_writes(hub):
    c, target = hub
    before = business(target)
    p = preview(c)
    assert p.json['counts'] == {'create': 1, 'update': 0, 'unchanged': 0}
    assert p.json['rows'][0]['after']['costCents'] == 10050
    assert p.json['rows'][0]['after']['valueCents'] == 12075
    assert p.json['rows'][0]['after']['valuationSource'] == 'file_import'
    assert business(target) == before
    r = confirm(c, p)
    assert r.status_code == 200 and r.json['created'] == 1 and r.json['replayed'] is False
    record = saved(c)[0]
    assert record['asOf'] == '2026-01-10' and record['visibility'] == 'private'
    after = business(target)
    r2 = confirm(c, p)
    assert r2.json == {**r.json, 'replayed': True}
    assert business(target) == after
    fresh = preview(c)
    assert fresh.json['replayed'] and fresh.json['counts']['unchanged'] == 1
    assert confirm(c, fresh).json == r2.json
    assert business(target) == after
    for table in ['hub_transactions', 'hub_imports', 'hub_budgets', 'hub_reconciliations', 'settings']:
        assert after[table] == before[table]
    with sqlite3.connect(target) as con:
        staged = con.execute('SELECT snapshot FROM hub_investment_import_previews').fetchall()
    assert all('contentBase64' not in row[0] and 'previewToken' not in row[0] for row in staged)


def test_periodic_snapshot_updates_same_id_and_retains_missing_holdings(hub):
    c, _ = hub
    rows = [holding(), holding(holdingKey='second', name='SECOND', currency='CNY', value='')]
    assert confirm(c, preview(c, csv_payload(rows))).json['created'] == 2
    first = next(i for i in saved(c) if i['name'] == 'SYNTHETIC_FUND')
    updated = holding(value='130.25', asOf='2026-02-01')
    p = preview(c, csv_payload([updated]))
    assert p.json['counts'] == {'create': 0, 'update': 1, 'unchanged': 0}
    assert p.json['preservedCount'] == 1 and p.json['warnings']
    assert confirm(c, p).json['updated'] == 1
    current = saved(c)
    new = next(i for i in current if i['id'] == first['id'])
    assert new['revision'] == 2 and new['valueCents'] == 13025
    assert len(current) == 2 and next(i for i in current if i['name'] == 'SECOND')['valueCents'] is None


@pytest.mark.parametrize('changes,message', [
    ({'asOf': '2025-12-31'}, '日期'), ({'value': ''}, '空估值'), ({'currency': 'CNY'}, '币种'),
    ({'recordId': 'missing'}, '关联'),
])
def test_updates_cannot_replace_newer_dates_known_values_currency_or_links(hub, changes, message):
    c, target = hub
    confirm(c, preview(c))
    before = business(target)
    p = preview(c, csv_payload([holding(**changes)]))
    assert p.status_code == 200 and p.json['errorCount'] == 1 and p.json['previewToken'] is None
    assert message in p.json['errors'][0]['message']
    assert business(target) == before


def test_entire_batch_rejected_if_one_row_bad(hub):
    c, target = hub
    p = preview(c, csv_payload([holding(), holding(holdingKey='bad', cost='1.001')]))
    assert p.status_code == 200 and p.json['errorCount'] == 1 and p.json['errors'][0]['line'] == 3
    assert p.json['previewToken'] is None and saved(c) == []
    assert c.post(PREFIX + '/confirm', json={'previewToken': None}).status_code == 400


@pytest.mark.parametrize('changes', [
    {'cost': '-1'}, {'cost': 'NaN'}, {'cost': 'Infinity'}, {'cost': '0.001'}, {'cost': ''},
    {'value': '-1'}, {'value': 'NaN'}, {'quantity': '-1'}, {'quantity': '1.123456789'},
    {'asOf': '2026-02-30'}, {'asOf': ''}, {'currency': ''}, {'currency': 'USDD'},
    {'holdingKey': ''}, {'holdingKey': 'a\x00b'}, {'recordId': 'bad/id'}, {'name': ''},
])
def test_invalid_cells_report_line_without_staging_or_business_changes(hub, changes):
    c, target = hub
    before = business(target)
    p = preview(c, csv_payload([holding(**changes)]))
    if changes.get('holdingKey') == 'a\x00b':
        assert p.status_code == 400  # The shared decoder rejects NUL before row parsing.
    else:
        assert p.status_code == 200 and p.json['errorCount'] == 1 and p.json['errors'][0]['line'] == 2
        assert p.json['previewToken'] is None
    assert business(target) == before


@pytest.mark.parametrize('rows', [
    [holding(), holding(value='200')],
    [holding(recordId='same'), holding(holdingKey='two', recordId='same')],
])
def test_duplicate_keys_and_explicit_ids_rejected(hub, rows):
    c, _ = hub
    p = preview(c, csv_payload(rows))
    assert p.json['errorCount'] and not p.json['previewToken'] and saved(c) == []


@pytest.mark.parametrize('content', [
    '', '"unterminated header', 'holdingKey,name\nx,y\n', ',name,name\nx,y,z\n',
    ','.join(COLUMNS) + '\nshort,row\n', ','.join(COLUMNS) + '\n"unclosed',
    ','.join(COLUMNS + ['unexpected']) + '\n', ','.join(COLUMNS) + '\n',
])
def test_bad_csv_structure_is_not_partially_imported(hub, content):
    c, _ = hub
    p = preview(c, csv_payload(content=content))
    assert p.status_code == 400 or (p.json['errorCount'] and p.json['previewToken'] is None)
    assert saved(c) == []


@pytest.mark.parametrize('mutation', ['edit', 'delete', 'new_record', 'another_import'])
def test_portfolio_cas_blocks_concurrent_changes_atomically(hub, mutation):
    c, target = hub
    confirm(c, preview(c))
    p = preview(c, csv_payload([holding(value='140')]))
    item = saved(c)[0]
    if mutation == 'edit':
        assert c.patch('/api/finance-hub/investments/' + item['id'], json=investment(revision=item['revision'])).status_code == 200
    elif mutation == 'delete':
        assert c.delete('/api/finance-hub/investments/' + item['id'], json={'revision': item['revision']}).status_code == 200
    elif mutation == 'new_record':
        assert c.post('/api/finance-hub/investments', json=investment()).status_code == 201
    else:
        confirm(c, preview(c, csv_payload([holding(value='135')])) )
    before = business(target)
    r = confirm(c, p)
    assert r.status_code == 409 and business(target) == before


def test_identical_changed_file_is_unchanged_and_preserves_revision(hub):
    c, _ = hub
    confirm(c, preview(c))
    item = saved(c)[0]
    payload = csv_payload()
    payload['file']['contentBase64'] = base64.b64encode(base64.b64decode(payload['file']['contentBase64']) + b'\n').decode()
    p = preview(c, payload)
    assert p.json['counts']['unchanged'] == 1
    assert confirm(c, p).json['unchanged'] == 1 and saved(c)[0] == item


def test_deleted_link_is_not_resurrected_by_old_file_or_changed_file(hub):
    c, _ = hub
    confirm(c, preview(c))
    item = saved(c)[0]
    c.delete('/api/finance-hub/investments/' + item['id'], json={'revision': item['revision']})
    assert confirm(c, preview(c)).json['replayed'] and saved(c) == []
    p = preview(c, csv_payload([holding(value='130')]))
    assert p.json['errorCount'] and '已删除' in p.json['errors'][0]['message'] and saved(c) == []


def test_manual_possible_duplicate_requires_explicit_record_id(hub):
    c, _ = hub
    r = c.post('/api/finance-hub/investments', json=investment(name='SYNTHETIC_FUND', institution='SYNTHETIC_BROKER', asOf='2026-01-01'))
    rid = r.json['id']
    p = preview(c)
    assert p.json['errorCount'] == 1 and 'recordId' in p.json['errors'][0]['message']
    p = preview(c, csv_payload([holding(recordId=rid)]))
    assert p.json['counts']['update'] == 1 and confirm(c, p).json['updated'] == 1
    assert len(saved(c)) == 1 and saved(c)[0]['id'] == rid
    p = preview(c, csv_payload([holding(recordId=rid)], source='另一来源'))
    assert p.json['errorCount'] == 1 and '另一来源' in p.json['errors'][0]['message']


def test_current_template_safely_roundtrips_formula_like_private_labels_and_manual_identity(hub):
    c, _ = hub
    value = investment(name='=SYNTHETIC()', institution='+SYNTHETIC', note='@SYNTHETIC\nsecond line', asOf='2026-01-01')
    r = c.post('/api/finance-hub/investments', json=value)
    original = r.json
    t = c.get(PREFIX + '/template?mode=current&sourceName=manual-account')
    assert t.status_code == 200 and t.json['rowCount'] == 1
    cells = list(csv.DictReader(io.StringIO(t.json['csv'])))[0]
    assert all(cells[k].startswith("'") for k in TEXT_COLUMNS)
    assert cells['csvTextEncoding'] == 'apostrophe-v1'
    p = preview(c, csv_payload(source='manual-account', content=t.json['csv']))
    assert p.json['counts']['unchanged'] == 1
    assert confirm(c, p).json['unchanged'] == 1
    assert saved(c) == [original]
    t2 = c.get(PREFIX + '/template?mode=current&sourceName=manual-account')
    p2 = preview(c, csv_payload(source='manual-account', content=t2.json['csv']))
    assert confirm(c, p2).json['replayed']
    other = c.get(PREFIX + '/template?mode=current&sourceName=other-account')
    assert other.json['rowCount'] == 0 and other.json['warnings']


def test_template_is_member_private_and_source_ids_do_not_guess_another_member(hub):
    c, _ = hub
    confirm(c, preview(c))
    rid = saved(c)[0]['id']
    h = {'X-Test-Actor': 'member2'}
    current = c.get(PREFIX + '/template?mode=current&sourceName=x', headers=h)
    assert current.json['rowCount'] == 0 and 'SYNTHETIC_FUND' not in current.json['csv']
    p = preview(c, csv_payload([holding(recordId=rid)]), headers=h)
    assert p.json['errorCount'] == 1 and p.json['rows'] == []
    assert confirm(c, preview(c, headers=h), headers=h).status_code == 200
    assert len(saved(c, 'member1')) == len(saved(c, 'member2')) == 1


@pytest.mark.parametrize('uid,code', [('anonymous', 401), ('tv', 403)])
def test_all_new_routes_require_member(hub, uid, code):
    c, _ = hub
    headers = {'X-Test-Actor': uid}
    assert c.get(PREFIX + '/template', headers=headers).status_code == code
    assert preview(c, headers=headers).status_code == code
    assert c.post(PREFIX + '/confirm', json={'previewToken': 'synthetic'}, headers=headers).status_code == code


def test_token_binding_owner_session_household_and_body(hub):
    c, target = hub
    p = preview(c)
    token = p.json['previewToken']
    before = business(target)
    assert confirm(c, p, headers={'X-Test-Actor': 'member2'}).status_code == 409
    assert c.post(PREFIX + '/confirm', json={'previewToken': token, 'inspectSheets': True}).status_code == 400
    assert c.post(PREFIX + '/confirm', json={'previewToken': token + 'x'}).status_code == 409
    with c.session_transaction() as s:
        s['csrf'] = 'rotated-synthetic-session'
    assert confirm(c, p).status_code == 409
    with c.session_transaction() as s:
        s.clear()
    c.application.config['HOUSEHOLD_INFO'] = {'id': 'other-synthetic-household'}
    assert confirm(c, p).status_code == 409
    assert business(target) == before


def test_expired_preview_cleanup_quota_and_confirm(hub):
    c, target = hub
    p = preview(c)
    with sqlite3.connect(target) as con:
        con.execute('UPDATE hub_investment_import_previews SET expires_at=0')
    assert confirm(c, p).status_code == 409
    for _ in range(20):
        assert preview(c).status_code == 200
    assert preview(c).status_code == 429
    with sqlite3.connect(target) as con:
        assert con.execute('SELECT count(*) FROM hub_investment_import_previews').fetchone()[0] == 20
    assert saved(c) == []


@pytest.mark.parametrize('inspect', [None, 1, 'true', [], {}])
def test_inspection_mode_is_strict_boolean(hub, inspect):
    c, _ = hub
    assert preview(c, {**csv_payload(), 'inspectSheets': inspect}).status_code == 400


def test_xlsx_discovery_selection_and_actual_confirm(hub):
    c, _ = hub
    rows = [COLUMNS, [holding()[key] for key in COLUMNS]]
    raw = workbook(rows=[['说明页：请选择订单工作表']], second_sheet=True,
                   extra_parts={'xl/worksheets/sheet2.xml': sheet_xml(rows)})
    payload = {'sourceName': 'xlsx-account', 'file': file_payload(raw), 'inspectSheets': True}
    discovery = preview(c, payload)
    assert discovery.status_code == 200 and discovery.json['requiresSheetSelection']
    assert discovery.json['fileInfo']['sheets'] == ['支付账单', '订单']
    assert discovery.json['rows'] == [] and discovery.json['previewToken'] is None and saved(c) == []
    assert c.post(PREFIX + '/confirm', json=payload).status_code == 400
    payload['file']['sheet'] = '订单'; payload['inspectSheets'] = False
    p = preview(c, payload)
    assert p.json['fileInfo']['sheet'] == '订单' and p.json['counts']['create'] == 1
    assert confirm(c, p).json['created'] == 1
    payload['file']['sheet'] = '支付账单'
    bad = preview(c, payload)
    assert bad.json['errorCount'] and bad.json['previewToken'] is None


@pytest.mark.parametrize('cover', ['explanation', 'formula'])
def test_no_sheet_automatically_discovers_without_parsing_cover_cells(hub, cover):
    c, _ = hub
    rows = [COLUMNS, [holding()[key] for key in COLUMNS]]
    first = sheet_xml([['这是合成说明页，没有持仓表头']]) if cover == 'explanation' else (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>')
    raw = workbook(second_sheet=True, sheet_override=first, extra_parts={'xl/worksheets/sheet2.xml': sheet_xml(rows)})
    value = {'sourceName': 'synthetic-xlsx', 'file': file_payload(raw), 'inspectSheets': False}
    p = preview(c, value)
    assert p.status_code == 200 and p.json['requiresSheetSelection'] and p.json['fileInfo']['sheet'] is None
    assert p.json['previewToken'] is None and p.json['rows'] == [] and saved(c) == []
    value['file']['sheet'] = '订单'
    selected = preview(c, value)
    assert confirm(c, selected).json['created'] == 1
    if cover == 'formula':
        value['file']['sheet'] = '支付账单'
        assert preview(c, value).status_code == 400  # Selecting the formula tab still rejects it.


@pytest.mark.parametrize('kind', ['formula', 'external', 'oversize', 'concurrency'])
def test_existing_file_safety_limits_remain_enforced(hub, kind):
    c, _ = hub
    payload = csv_payload()
    if kind == 'formula':
        payload['file'] = file_payload(workbook(sheet_override='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'), sheet='支付账单')
    elif kind == 'external':
        payload['file'] = file_payload(workbook(relationships_extra='<Relationship Id="evil" Target="https://invalid.example" TargetMode="External" Type="external"/>'), sheet='支付账单')
    elif kind == 'oversize':
        payload['file'] = file_payload(b'a' * (2 * 1024 * 1024 + 1), name='big.csv')
    else:
        FILE_PARSE_SLOT.acquire()
    try:
        r = preview(c, payload)
        assert r.status_code in {400, 413, 429} and saved(c) == []
    finally:
        if kind == 'concurrency': FILE_PARSE_SLOT.release()


def test_full_application_csrf_origin_and_private_fields(app):
    c, headers = member(app)
    assert preview(c).status_code == 403
    assert preview(c, headers={**headers, 'Origin': 'https://invalid.example'}).status_code == 403
    p = preview(c, headers=headers)
    assert p.status_code == 200 and confirm(c, p, headers=headers).status_code == 200
    other, h2 = member(app, 2)
    assert confirm(other, p, headers=h2).status_code == 409
    assert other.get(PREFIX + '/template?mode=current&sourceName=account').json['rowCount'] == 0
    assert 'SYNTHETIC_FUND' not in json.dumps(other.get('/api/state').json)


def test_parallel_confirm_has_one_commit_and_one_replay(hub):
    c, target = hub
    p = preview(c)
    application = c.application
    def send(_):
        with application.test_client() as isolated:
            r = confirm(isolated, p)
            return r.status_code, r.json
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert all(code == 200 for code, _ in results)
    assert sorted(value['replayed'] for _, value in results) == [False, True]
    assert len({value['receiptId'] for _, value in results}) == 1
    with sqlite3.connect(target) as con:
        assert con.execute('SELECT count(*) FROM hub_investments').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM hub_investment_import_receipts').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM audit').fetchone()[0] == 1


def test_multicurrency_zero_unknown_and_large_minor_units_remain_separate(hub):
    c, _ = hub
    records = [holding(holdingKey='large', name='LARGE', cost='999999999999.99', value='1000000000000.00'),
               holding(holdingKey='zero', name='ZERO', currency='CNY', cost='0.00', value='0', quantity='0'),
               holding(holdingKey='unknown', name='UNKNOWN', currency='EUR', cost='8.25', value='', quantity='')]
    p = preview(c, csv_payload(records))
    assert confirm(c, p).json['created'] == 3
    groups = {g['currency']: g for g in overview(c)['investmentTotals']}
    assert set(groups) == {'USD', 'CNY', 'EUR'}
    assert groups['USD']['unrealizedGainCents'] == 1
    assert groups['CNY']['valueCents'] == 0 and groups['CNY']['unvaluedCount'] == 0
    assert groups['EUR']['valueCents'] == 0 and groups['EUR']['unvaluedCount'] == 1
    unknown = next(i for i in saved(c) if i['currency'] == 'EUR')
    assert unknown['valueCents'] is None and unknown['quantity'] is None


@pytest.mark.parametrize('case', ['file_rows', 'existing_records'])
def test_holdings_quota_is_all_or_nothing(hub, case):
    c, target = hub
    if case == 'file_rows':
        rows = [holding(holdingKey=f'key-{n}', name=f'SYNTHETIC-{n}') for n in range(301)]
    else:
        value = c.post('/api/finance-hub/investments', json=investment()).json
        data = {k: v for k, v in value.items() if k not in {'id', 'revision'}}
        with sqlite3.connect(target) as con:
            for n in range(299):
                con.execute('INSERT INTO hub_investments(id,owner,data,updated_at) VALUES(?,?,?,?)',
                            (f'synthetic-{n}', 'member1', json.dumps({**data, 'name': f'SYNTHETIC-{n}'}), '2026-01-01'))
        rows = [holding()]
    before = business(target)
    p = preview(c, csv_payload(rows))
    assert p.json['errorCount'] and p.json['previewToken'] is None
    assert any('300' in e['message'] for e in p.json['errors'])
    assert business(target) == before


def test_csv_quotes_multiline_notes_and_explicit_safe_export_marker(hub):
    c, _ = hub
    row = holding(name='SYNTHETIC, QUOTED "NAME"', note='line one\nline two')
    assert confirm(c, preview(c, csv_payload([row]))).status_code == 200
    assert saved(c)[0]['name'] == row['name'] and saved(c)[0]['note'] == row['note']
    t = c.get(PREFIX + '/template?mode=current&sourceName=合成账户甲')
    broken = t.json['csv'].replace('apostrophe-v1', 'unsupported')
    p = preview(c, csv_payload(content=broken))
    assert p.json['errorCount'] and p.json['previewToken'] is None


@pytest.mark.parametrize('currency', ['USD', 'CNY', 'EUR'])
@pytest.mark.parametrize('amount', ['1,23', '1，23', '12,34.56', '1,234，567.89', '1，234,567.89'])
def test_ambiguous_decimal_or_malformed_mixed_grouping_never_gets_token(hub, currency, amount):
    c, target = hub
    before = business(target)
    p = preview(c, csv_payload([holding(currency=currency, cost=amount, value=amount)]))
    assert p.status_code == 200 and p.json['errorCount'] == 1 and p.json['previewToken'] is None
    assert p.json['errors'][0]['line'] == 2 and '千分隔符' in p.json['errors'][0]['message']
    assert business(target) == before


@pytest.mark.parametrize('currency', ['USD', 'CNY', 'EUR'])
@pytest.mark.parametrize('amount', ['1234.56', '1,234.56', '1，234.56'])
def test_explicit_decimal_and_complete_thousands_groups_roundtrip_exactly(hub, currency, amount):
    c, _ = hub
    p = preview(c, csv_payload([holding(currency=currency, cost=amount, value=amount)]))
    assert p.json['rows'][0]['after']['costCents'] == 123456
    assert p.json['rows'][0]['after']['valueCents'] == 123456
    assert confirm(c, p).status_code == 200
    assert saved(c)[0]['costCents'] == saved(c)[0]['valueCents'] == 123456
