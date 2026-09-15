"""Sheet discovery is metadata only; all fixtures and accounts are synthetic."""
import hashlib
import json
import sqlite3

import pytest
from itsdangerous import URLSafeTimedSerializer

from financial_files import FILE_PARSE_SLOT, FinancialFileError, read_financial_file
from test_finance_hub import hub, overview
from test_financial_files import NS, REL, DR, workbook, file_payload, import_payload, sheet_xml
from test_app import app, member
from test_household_spaces import create_space


def payload(raw=None, **extras):
    return {**import_payload(raw or workbook(rows=[['SYNTHETIC_COVER_ONLY']], second_sheet=True)),
            'inspectSheets': True, **extras}


def preview(client, value, actor='member1'):
    return client.post('/api/finance-hub/imports/preview', json=value, headers={'X-Test-Actor': actor})


@pytest.mark.parametrize('first', [
    sheet_xml([['SYNTHETIC_COVER_ONLY']]),
    f'<worksheet xmlns="{NS}"><sheetData/></worksheet>',
    f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>',
    f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="e"><v>#VALUE!</v></c></row></sheetData></worksheet>',
])
def test_cover_empty_formula_or_error_sheet_can_be_listed_but_not_confirmed(hub, first):
    client, target = hub
    value = payload(workbook(sheet_override=first, second_sheet=True))
    r = preview(client, value)
    assert r.status_code == 200
    assert r.json['requiresSheetSelection'] and not r.json['requiresAmountSelection']
    assert r.json['rows'] == r.json['totals'] == r.json['errors'] == []
    assert r.json['amountSelection'] is None and r.json['previewToken'] is None
    assert r.json['fileInfo']['sheet'] is None and r.json['fileInfo']['worksheetRows'] is None
    assert r.json['fileInfo']['sheets'] == ['支付账单', '订单']
    assert '尚未解析记录' in r.json['fileInfo']['note']
    assert client.post('/api/finance-hub/imports/confirm', json={**value, 'previewToken': 'synthetic-not-a-receipt'}).status_code == 400
    selected = {**value, 'file': {**value['file'], 'sheet': '支付账单'}}; selected.pop('inspectSheets')
    assert preview(client, selected).status_code == 400
    selected['file'] = {**value['file'], 'sheet': '订单'}
    good = preview(client, selected)
    assert good.status_code == 200 and good.json['previewToken']
    assert not good.json['requiresSheetSelection']
    with sqlite3.connect(target) as con:
        assert con.execute('SELECT count(*) FROM hub_transactions').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM hub_imports').fetchone()[0] == 0
    receipt = client.post('/api/finance-hub/imports/confirm', json={**selected, 'previewToken': good.json['previewToken']})
    assert receipt.json['imported'] == 1
    assert overview(client)['transactions'][0]['amountCents'] == 2180


@pytest.mark.parametrize('bad', [None, 0, 1, 'true', 'false', [], {}])
def test_discovery_type_is_strict_for_preview_and_confirm(hub, bad):
    client, _ = hub
    value = payload(inspectSheets=bad)
    assert preview(client, value).status_code == 400
    assert client.post('/api/finance-hub/imports/confirm', json={**value, 'previewToken': 'synthetic'}).status_code == 400


def test_csv_text_and_csv_file_do_not_accept_sheet_discovery(hub):
    client, _ = hub
    for value in [{'source': 'generic', 'csv': 'date,amount,currency\n2026-09-02,1,CNY\n', 'inspectSheets': True},
                  {'source': 'wechat', 'file': file_payload(b'date,amount\n2026-09-02,1\n', 'synthetic.csv'), 'inspectSheets': True},
                  payload(amountColumn=2)]:
        assert preview(client, value).status_code == 400
    assert overview(client)['totalRecordCount'] == 0


def test_old_default_first_sheet_and_explicit_false_remain_compatible(hub):
    client, _ = hub
    value = import_payload(workbook(second_sheet=True))
    for extras in [{}, {'inspectSheets': False}]:
        r = preview(client, {**value, **extras})
        assert r.status_code == 200 and r.json['previewToken']
        assert not r.json['requiresSheetSelection']
        assert r.json['fileInfo']['sheet'] == '支付账单'


@pytest.mark.parametrize('xml', [
    '<!DOCTYPE worksheet [<!ENTITY x "unsafe">]><worksheet/>',
    ('<?xml version="1.0" encoding="UTF-16"?><worksheet/>').encode('utf-16'),
    '<worksheet>',
    '<worksheet>' + '<x>' * 49 + '</x>' * 49 + '</worksheet>',
])
def test_discovery_rejects_unsafe_or_malformed_xml_even_in_other_sheet(hub, xml):
    client, _ = hub
    raw = workbook(second_sheet=True, extra_parts={'xl/worksheets/sheet2.xml': xml})
    r = preview(client, payload(raw))
    assert r.status_code == 400 and r.json.keys() == {'error'}
    assert overview(client)['totalRecordCount'] == 0


@pytest.mark.parametrize('parts', [
    {'../outside.xml': '<x/>'},
    {'xl/vbaProject.bin': 'synthetic'},
    {'xl/worksheets/_rels/sheet1.xml.rels': f'<Relationships xmlns="{REL}"><Relationship Id="bad" Target="https://example.invalid" TargetMode="External"/></Relationships>'},
    {'[Content_Types].xml': '<Types><Override ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/></Types>'},
    {'xl/sharedStrings.xml': '<!DOCTYPE sst [<!ENTITY x "unsafe">]><sst/>'},
    {'xl/styles.xml': '<styleSheet>'},
    {'xl/UNUSED.XML': '<!DOCTYPE x [<!ENTITY x "unsafe">]><x/>'},
    {'xl/worksheets/_rels/sheet1.xml.RELS': f'<Relationships xmlns="{REL}"><Relationship Id="bad" Target="https://example.invalid" TargetMode="External"/></Relationships>'},
])
def test_discovery_keeps_zip_macro_external_relationship_and_shared_xml_rejections(hub, parts):
    client, _ = hub
    r = preview(client, payload(workbook(second_sheet=True, extra_parts=parts)))
    assert r.status_code == 400 and r.json.keys() == {'error'}


def test_missing_sheet_target_is_not_advertised_as_usable(hub):
    client, _ = hub
    xml = f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Target="worksheets/missing.xml" Type="{DR}/worksheet"/></Relationships>'
    r = preview(client, payload(workbook(extra_parts={'xl/_rels/workbook.xml.rels': xml})))
    assert r.status_code == 400 and '缺少' in r.json['error']


def test_discovery_keeps_size_and_parse_slot_limits(hub):
    client, _ = hub
    raw = workbook(extra_parts={'synthetic-padding.xml': '<x>' + (' ' * (8 * 1024 * 1024)) + '</x>'})
    assert preview(client, payload(raw)).status_code == 400
    assert FILE_PARSE_SLOT.acquire(False)
    try:
        assert preview(client, payload()).status_code == 429
    finally:
        FILE_PARSE_SLOT.release()
    assert preview(client, payload()).status_code == 200


def test_discovery_cannot_confirm_even_with_a_valid_signed_request(hub):
    client, _ = hub
    value = payload()
    fields = {k: value.get(k, 'generic' if k == 'source' else 'payments' if k == 'kind' else '')
              for k in ('source', 'kind', 'csv', 'file')}
    fields['inspectSheets'] = True
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    token = URLSafeTimedSerializer('synthetic-testing-secret', salt='household-finance-preview-v1').dumps({'owner': 'member1', 'digest': digest})
    r = client.post('/api/finance-hub/imports/confirm', json={**value, 'previewToken': token})
    assert r.status_code == 400 and '工作表列表不能确认' in r.json['error']
    assert overview(client)['totalRecordCount'] == 0


def test_selection_and_file_content_remain_signed_and_private(hub):
    client, _ = hub
    value = import_payload(workbook(second_sheet=True), sheet='订单')
    token = preview(client, value).json['previewToken']
    for changed in [{**value, 'inspectSheets': True}, {**value, 'inspectSheets': False},
                    {**value, 'file': {**value['file'], 'sheet': '支付账单'}},
                    import_payload(workbook(rows=[['changed']], second_sheet=True), sheet='订单')]:
        assert client.post('/api/finance-hub/imports/confirm', json={**changed, 'previewToken': token}).status_code == 400
    assert client.post('/api/finance-hub/imports/confirm', json={**value, 'previewToken': token}, headers={'X-Test-Actor': 'member2'}).status_code == 400
    assert preview(client, payload(), 'tv').status_code == 403
    assert preview(client, payload(), 'anonymous').status_code == 401
    assert overview(client, 'member2')['totalRecordCount'] == 0


def test_actual_household_route_does_not_share_discovery_or_signed_preview(app):
    primary, h = member(app)
    value = import_payload(workbook(second_sheet=True), sheet='订单')
    token = primary.post('/api/finance-hub/imports/preview', json=value, headers=h).json['previewToken']
    child, _, space = create_space(app); assert child.get(space['entry']).status_code == 303
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    assert child.post('/api/finance-hub/imports/preview', json=payload(), headers=ch).json['requiresSheetSelection']
    assert child.post('/api/finance-hub/imports/confirm', json={**value, 'previewToken': token}, headers=ch).status_code == 400
    assert child.get('/api/finance-hub/overview?month=2026-09').json['totalRecordCount'] == 0
