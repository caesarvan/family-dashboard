"""Synthetic OOXML and encoding fixtures, not coverage claims for bank exports."""
import base64
from datetime import datetime
import io
import json
from pathlib import Path
import sqlite3
import struct
import zipfile
from xml.sax.saxutils import escape

import pytest

from financial_files import FinancialFileError, FILE_PARSE_SLOT, MAX_FILE_BYTES, read_financial_file
from finance_hub import parse_import
from test_app import app, member


NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
DR = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def inline_cell(address, text):
    return f'<c r="{address}" t="inlineStr"><is><t>{escape(str(text))}</t></is></c>'


def sheet_xml(rows):
    return f'<worksheet xmlns="{NS}"><sheetData>' + ''.join(f'<row r="{index}">' + ''.join(inline_cell(chr(65 + col) + str(index), value) for col, value in enumerate(row)) + '</row>' for index, row in enumerate(rows, 1)) + '</sheetData></worksheet>'


def workbook(rows=None, *, extra_parts=None, sheet_override=None, second_sheet=False, date1904=False, relationships_extra=''):
    rows = rows or [['微信支付账单（合成样例）'], ['交易时间', '商品', '金额(元)', '收/支', '交易单号'], ['2026-09-14 12:00:00', '合成咖啡', '10.50', '支出', 'payment-001']]
    content_types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>'
    parts = {'[Content_Types].xml': content_types,
             'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="{DR}"><workbookPr date1904="{int(date1904)}"/><sheets><sheet name="支付账单" sheetId="1" r:id="rId1"/>' + ('<sheet name="订单" sheetId="2" r:id="rId2"/>' if second_sheet else '') + '</sheets></workbook>',
             'xl/_rels/workbook.xml.rels': f'<Relationships xmlns="{REL}"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="{DR}/worksheet"/>' + (f'<Relationship Id="rId2" Target="worksheets/sheet2.xml" Type="{DR}/worksheet"/>' if second_sheet else '') + relationships_extra + '</Relationships>',
             'xl/worksheets/sheet1.xml': sheet_override or sheet_xml(rows)}
    if second_sheet:
        parts['xl/worksheets/sheet2.xml'] = sheet_xml([['交易时间', '商品', '金额(元)', '收/支', '交易单号'], ['2026-09-15', '第二工作表', '21.80', '支出', 'payment-002']])
    parts.update(extra_parts or {})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return stream.getvalue()


def file_payload(raw, name='export.xlsx', **extras):
    return {'name': name, 'contentBase64': base64.b64encode(raw).decode(), **extras}


def import_payload(raw=None, **file_args):
    return {'source': 'wechat', 'kind': 'payments', 'file': file_payload(raw or workbook(), **file_args)}


def test_xlsx_chinese_header_values_and_preview_metadata():
    payload = import_payload()
    value = parse_import(payload)
    assert value['fileInfo']['format'] == 'xlsx'
    assert value['fileInfo']['sheet'] == '支付账单'
    assert value['fileInfo']['sheets'] == ['支付账单']
    assert value['rows'][0]['date'] == '2026-09-14'
    assert value['rows'][0]['title'] == '合成咖啡'
    assert value['rows'][0]['amountCents'] == 1050
    assert value['rows'][0]['externalId'] == 'payment-001'
    assert value['errorCount'] == 0


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'gb18030'])
def test_csv_strict_auto_encoding_and_source_preserved(encoding):
    content = '交易创建时间,商品名称,金额（元）,收支,交易号\n2026-09-14,合成茶饮,18.50,支出,alipay001\n'
    value = parse_import({'source': 'alipay', 'kind': 'payments', 'file': file_payload(content.encode(encoding), 'alipay.csv', encoding='auto')})
    assert value['rows'][0]['title'] == '合成茶饮'
    assert value['rows'][0]['source'] == 'alipay'
    assert value['rows'][0]['amountCents'] == 1850
    assert value['fileInfo']['encoding'] == ('UTF-8' if encoding == 'utf-8-sig' else 'GB18030')
    assert value['rows'][0]['flow'] == 'expense'


def test_explicit_encoding_mismatch_is_rejected():
    with pytest.raises(FinancialFileError, match='编码'):
        read_financial_file(file_payload('中文内容'.encode('gb18030'), 'alipay.csv', encoding='utf-8'))
    with pytest.raises(FinancialFileError, match='编码'):
        read_financial_file(file_payload(b'\xff', 'alipay.csv'))


def test_sheet_selection_is_explicit_and_does_not_merge_unrelated_tables():
    raw = workbook(second_sheet=True)
    first = parse_import(import_payload(raw))
    second = parse_import(import_payload(raw, sheet='订单'))
    assert len(first['rows']) == len(second['rows']) == 1
    assert first['rows'][0]['title'] == '合成咖啡'
    assert second['rows'][0]['title'] == '第二工作表'
    assert len(second['fileInfo']['sheets']) == 2
    with pytest.raises(FinancialFileError, match='工作表'):
        read_financial_file(file_payload(raw, sheet='不存在'))


@pytest.mark.parametrize('date1904', [False, True])
def test_shared_strings_rich_text_and_numeric_date_styles(date1904):
    strings = f'<sst xmlns="{NS}"><si><t>交易时间</t></si><si><t>商品</t></si><si><t>金额(元)</t></si><si><t>收/支</t></si><si><r><t>合成</t></r><r><t>酒店</t></r><rPh><t>ignored phonetic</t></rPh></si><si><t>支出</t></si></sst>'
    styles = f'<styleSheet xmlns="{NS}"><numFmts count="1"><numFmt numFmtId="165" formatCode="yyyy-mm-dd hh:mm:ss"/></numFmts><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="165"/></cellXfs></styleSheet>'
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    serial = (datetime(2026, 9, 14, 12) - base).total_seconds() / 86400
    cells = '<row r="1">' + ''.join(f'<c r="{col}1" t="s"><v>{i}</v></c>' for i, col in enumerate('ABCD')) + '</row>'
    cells += f'<row r="2"><c r="A2" s="1"><v>{serial}</v></c><c r="B2" t="s"><v>4</v></c><c r="C2"><v>650.50</v></c><c r="D2" t="s"><v>5</v></c></row>'
    raw = workbook(sheet_override=f'<worksheet xmlns="{NS}"><sheetData>{cells}</sheetData></worksheet>',
                   extra_parts={'xl/sharedStrings.xml': strings, 'xl/styles.xml': styles}, date1904=date1904)
    result = parse_import(import_payload(raw))
    assert result['rows'][0]['date'] == '2026-09-14'
    assert result['rows'][0]['title'] == '合成酒店'
    assert result['rows'][0]['amountCents'] == 65050


@pytest.mark.parametrize('xml', [
    '<!DOCTYPE worksheet [<!ENTITY secret SYSTEM "file:///etc/passwd">]><worksheet/>',
    '<!DOCTYPE worksheet [<!ENTITY a "12345">]><worksheet>&a;</worksheet>',
    ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE worksheet [<!ENTITY a "unsafe">]><worksheet/>').encode('utf-16'),
    f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f>WEBSERVICE("https://example.invalid")</f><v>123</v></c></row></sheetData></worksheet>',
    f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="e"><v>#VALUE!</v></c></row></sheetData></worksheet>',
])
def test_dtd_entities_utf16_formula_cached_value_and_errors_are_rejected(xml):
    with pytest.raises(FinancialFileError):
        read_financial_file(file_payload(workbook(sheet_override=xml)))


@pytest.mark.parametrize('extra', [
    {'../outside.xml': '<x/>'}, {'/outside.xml': '<x/>'}, {'xl\\outside.xml': '<x/>'},
    {'xl/vbaProject.bin': b'macro'}, {'xl/externalLinks/externalLink1.xml': '<x/>'},
    {'xl/activeX/control.xml': '<x/>'}, {'xl/embeddings/document.xml': '<x/>'},
    {'xl/worksheets/_rels/sheet1.xml.rels': f'<Relationships xmlns="{REL}"><Relationship Id="evil" Target="https://example.invalid" TargetMode="External"/></Relationships>'},
    {'[Content_Types].xml': '<Types><Override ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/></Types>'},
])
def test_unsafe_paths_macros_embeddings_and_external_relationships_rejected(extra):
    raw = workbook(extra_parts=extra)
    # ZipInfo's Windows writer normalizes slashes; craft the actual wire name.
    if 'xl\\outside.xml' in extra:
        raw = raw.replace(b'xl/outside.xml', b'xl\\outside.xml')
    with pytest.raises(FinancialFileError):
        read_financial_file(file_payload(raw))


CONTENT_TYPES_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
BINARY_MACRO_MIME = 'application/vnd.ms-excel.sheet.binary.macroEnabled.main'
UNUSED_BINARY_DEFAULT = f'<Default Extension="bin" ContentType="{BINARY_MACRO_MIME}"/>'


def content_types_with_binary_default(declaration=UNUSED_BINARY_DEFAULT, extra=''):
    return (f'<Types xmlns="{CONTENT_TYPES_NS}">{declaration}'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f'{extra}</Types>')


def test_unused_binary_default_preserves_values_and_explicit_sheet_discovery():
    raw = workbook(second_sheet=True, extra_parts={
        '[Content_Types].xml': content_types_with_binary_default()})
    payload = import_payload(raw)
    discovery = parse_import({**payload, 'inspectSheets': True})
    assert discovery['requiresSheetSelection'] is True
    assert discovery['fileInfo']['sheets'] == ['支付账单', '订单']
    assert discovery['rows'] == []
    parsed = parse_import(import_payload(raw, sheet='订单'))
    assert parsed['errorCount'] == 0 and len(parsed['rows']) == 1
    assert parsed['rows'][0]['title'] == '第二工作表'
    assert parsed['rows'][0]['date'] == '2026-09-15'
    assert parsed['rows'][0]['amountCents'] == 2180


def test_unused_binary_default_real_order_preview_confirm_and_dedup(app):
    client, headers = member(app)
    payload = {'source': 'taobao', 'kind': 'orders', 'file': file_payload(workbook(
        rows=[['订单提交时间', '商品名称', '实付金额', '订单号', '币种', '订单状态'],
              ['2026-09-14', '合成订单', '12.34', 'synthetic-order-1', 'CNY', '交易成功']],
        extra_parts={'[Content_Types].xml': content_types_with_binary_default()}))}
    discovery = client.post('/api/finance-hub/imports/preview',
                            json={**payload, 'inspectSheets': True}, headers=headers)
    assert discovery.status_code == 200 and discovery.json['previewToken'] is None
    payload['file']['sheet'] = discovery.json['fileInfo']['sheets'][0]
    shown = client.post('/api/finance-hub/imports/preview', json=payload, headers=headers)
    assert shown.status_code == 200 and shown.json['errorCount'] == 0
    assert shown.json['rows'][0]['flow'] == 'unknown'
    assert shown.json['totals'][0]['netSpendCents'] == 0
    assert client.get('/api/finance-hub/overview').json['totalRecordCount'] == 0
    confirmation = {**payload, 'previewToken': shown.json['previewToken']}
    saved = client.post('/api/finance-hub/imports/confirm', json=confirmation, headers=headers)
    assert saved.status_code == 200 and saved.json['imported'] == 1
    replay = client.post('/api/finance-hub/imports/confirm', json=confirmation, headers=headers)
    assert replay.json['imported'] == 0 and replay.json['duplicates'] == 1
    current = client.get('/api/finance-hub/overview?month=2026-09').json
    assert current['transactionCount'] == 1 and current['totals'][0]['netSpendCents'] == 0


@pytest.mark.parametrize('declaration', [
    f'<Override PartName="/xl/unused.xml" ContentType="{BINARY_MACRO_MIME}"/>',
    f'<Default Extension="xml" ContentType="{BINARY_MACRO_MIME}"/>',
    '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>',
    '<Default Extension="bin" ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/>',
    '<Default Extension="bin" ContentType="application/vnd.ms-excel.macrosheet+xml"/>',
    f'<Default Extension="BIN" ContentType="{BINARY_MACRO_MIME}"/>',
    f'<Default Extension="bin " ContentType="{BINARY_MACRO_MIME}"/>',
    f'<Default xmlns="urn:unexpected" Extension="bin" ContentType="{BINARY_MACRO_MIME}"/>',
    f'<Default Extension="bin" ContentType="{BINARY_MACRO_MIME}" PartName="/xl/unused.bin"/>',
    f'<Default Extension="bin" ContentType="{BINARY_MACRO_MIME}"><Override/></Default>',
    f'<Default Extension="bin" ContentType="{BINARY_MACRO_MIME}">unexpected</Default>',
])
def test_binary_macro_declaration_exception_is_exact_and_not_other_macros(declaration):
    raw = workbook(extra_parts={'[Content_Types].xml': content_types_with_binary_default(declaration)})
    for inspect in (False, True):
        with pytest.raises(FinancialFileError, match='宏'):
            read_financial_file(file_payload(raw), inspect_sheets=inspect)


@pytest.mark.parametrize('case', ['binary', 'uppercase_binary', 'macro_payload', 'macro_override',
                                 'external', 'embedded', 'formula', 'malicious_xml'])
def test_unused_binary_default_does_not_bypass_other_rejections(case):
    extra = {'[Content_Types].xml': content_types_with_binary_default()}
    sheet = None
    if case in {'binary', 'uppercase_binary', 'macro_payload'}:
        name = {'binary':'xl/unused.bin', 'uppercase_binary':'xl/unused.BIN',
                'macro_payload':'xl/vbaProject.bin'}[case]
        extra[name] = b''  # Even an empty real binary part is still refused.
    elif case == 'macro_override':
        extra['[Content_Types].xml'] = content_types_with_binary_default(extra=
            f'<Override PartName="/xl/unused.xml" ContentType="{BINARY_MACRO_MIME}"/>')
    elif case == 'external':
        extra['xl/worksheets/_rels/sheet1.xml.rels'] = (
            f'<Relationships xmlns="{REL}"><Relationship Id="external" '
            'Target="https://example.invalid/never-requested" TargetMode="External"/></Relationships>')
    elif case == 'embedded':
        extra['xl/embeddings/document.xml'] = '<x/>'
    elif case == 'formula':
        sheet = f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'
    else:
        sheet = '<!DOCTYPE worksheet [<!ENTITY a "unsafe">]><worksheet>&a;</worksheet>'
    raw = workbook(extra_parts=extra, sheet_override=sheet)
    with pytest.raises(FinancialFileError):
        read_financial_file(file_payload(raw))
    # Discovery never evaluates cells; its existing formula handling is unchanged.
    if case != 'formula':
        with pytest.raises(FinancialFileError):
            read_financial_file(file_payload(raw), inspect_sheets=True)


def test_expansion_limit_rejected_before_xml_parsing_and_slot_released():
    raw = workbook(extra_parts={'huge.xml': 'x' * (8 * 1024 * 1024 + 1)})
    assert len(raw) < MAX_FILE_BYTES
    with pytest.raises(FinancialFileError, match='8 MB'):
        read_financial_file(file_payload(raw))
    assert read_financial_file(file_payload(workbook()))[1]['format'] == 'xlsx'


@pytest.mark.parametrize('sheet', [
    f'<worksheet xmlns="{NS}"><sheetData><row r="5001">{inline_cell("A5001", "value")}</row></sheetData></worksheet>',
    f'<worksheet xmlns="{NS}"><sheetData><row r="1">{inline_cell("CC1", "value")}</row></sheetData></worksheet>',
    f'<worksheet xmlns="{NS}"><sheetData><row r="1">{inline_cell("A1", "a")}{inline_cell("A1", "b")}</row></sheetData></worksheet>',
    '<worksheet>' + '<x>' * 49 + '</x>' * 49 + '</worksheet>',
])
def test_row_column_duplicate_coordinates_and_xml_depth_limits(sheet):
    with pytest.raises(FinancialFileError):
        read_financial_file(file_payload(workbook(sheet_override=sheet)))


def test_encrypted_zip_flag_and_legacy_files_rejected():
    raw = bytearray(workbook())
    for signature, offset in [(b'PK\x03\x04', 6), (b'PK\x01\x02', 8)]:
        index = raw.find(signature)
        struct.pack_into('<H', raw, index + offset, struct.unpack_from('<H', raw, index + offset)[0] | 1)
    with pytest.raises(FinancialFileError, match='加密'):
        read_financial_file(file_payload(bytes(raw)))
    for name in ('export.xls', 'export.xlsm', 'export.xlsb'):
        with pytest.raises(FinancialFileError):
            read_financial_file(file_payload(b'unsupported', name))
    with pytest.raises(FinancialFileError, match='加密'):
        read_financial_file(file_payload(bytes.fromhex('D0CF11E0A1B11AE1') + b'compound'))


def test_busy_parser_returns_429_and_does_not_release_someone_elses_slot(app):
    client, headers = member(app)
    assert FILE_PARSE_SLOT.acquire(False)
    try:
        response = client.post('/api/finance-hub/imports/preview', json=import_payload(), headers=headers)
        assert response.status_code == 429
        assert not FILE_PARSE_SLOT.acquire(False)
    finally:
        FILE_PARSE_SLOT.release()
    assert client.post('/api/finance-hub/imports/preview', json=import_payload(), headers=headers).status_code == 200


def test_xlsx_real_preview_confirm_digest_and_private_boundary(app):
    client, headers = member(app)
    partner, partner_headers = member(app, 2)
    payload = import_payload(workbook(second_sheet=True))
    result = client.post('/api/finance-hub/imports/preview', json=payload, headers=headers)
    assert result.status_code == 200, result.json
    token = result.json['previewToken']
    assert client.get('/api/finance-hub/overview?month=2026-09').json['totalRecordCount'] == 0
    changed = {**payload, 'file': {**payload['file'], 'sheet': '订单'}, 'previewToken': token}
    assert client.post('/api/finance-hub/imports/confirm', json=changed, headers=headers).status_code == 400
    assert partner.post('/api/finance-hub/imports/confirm', json={**payload, 'previewToken': token}, headers=partner_headers).status_code == 400
    response = client.post('/api/finance-hub/imports/confirm', json={**payload, 'previewToken': token}, headers=headers)
    assert response.status_code == 200 and response.json['imported'] == 1
    assert partner.get('/api/finance-hub/overview?month=2026-09').json['transactions'] == []
    assert client.post('/api/finance-hub/imports/confirm', json={**payload, 'previewToken': token}, headers=headers).json['duplicates'] == 1
    assert client.get('/api/state').json['finance']['livingSpent'] == 0
    with sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3') as con:
        stored = ' '.join(row[0] for row in con.execute('SELECT data FROM hub_transactions'))
        assert 'contentBase64' not in stored and 'PK' not in stored


def test_bad_file_and_oversized_text_never_mutate_finance(app):
    client, headers = member(app)
    bads = [import_payload(b'not a workbook'), import_payload(b'a' * (MAX_FILE_BYTES + 1)),
            {'source': 'wechat', 'kind': 'payments', 'csv': 'a' * (MAX_FILE_BYTES + 1)},
            {'source': 'wechat', 'kind': 'payments', 'file': {'name': 'x.xlsx', 'contentBase64': '%%%'}},
            {**import_payload(), 'csv': 'also csv'}]
    for payload in bads:
        response = client.post('/api/finance-hub/imports/preview', json=payload, headers=headers)
        assert response.status_code in (400, 413), response.json
    assert client.get('/api/finance-hub/overview').json['totalRecordCount'] == 0
    assert client.get('/api/state').json['finance']['livingSpent'] == 0
