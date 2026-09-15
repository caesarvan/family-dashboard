"""Explicit merged order geometry with synthetic inputs only; no real source files."""
import csv
import io
import json
from pathlib import Path
import socket
import sqlite3

import pytest

from finance_hub import FinanceHubError, TAOBAO_ORDER_HEADERS, parse_import
from financial_files import FinancialFileError, read_financial_file
from test_app import app, member
from test_financial_files import (NS, REL, workbook, sheet_xml, file_payload,
                                 content_types_with_binary_default)
from test_data_portability import unpack

PREFIX = '/api/finance-hub/'
ORDER_COLUMNS = 'ABCDJK'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Network forbidden in synthetic order-group tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


def table(groups=(('ORDER_A', 2), ('ORDER_B', 3), ('ORDER_C', 1)), *, status='交易成功'):
    rows = [TAOBAO_ORDER_HEADERS.copy()]
    refs = []
    for external_id, count in groups:
        first = len(rows) + 1
        for n in range(count):
            values = [external_id, '2026-09-14 12:00:00', status, 'SYNTHETIC_SHOP',
                      f'PRIVATE_ITEM_{external_id}_{n}', 'https://example.invalid/never-fetch',
                      'SYNTHETIC_VARIANT', '2', '999.99', '100.00', '5.00']
            if n:
                for col in (0, 1, 2, 3, 9, 10):
                    values[col] = ''
            rows.append(values)
        last = len(rows)
        refs += [f'{col}{first}:{col}{last}' if count > 1 else f'{col}{first}' for col in ORDER_COLUMNS]
    return rows, refs


def payload(groups=(('ORDER_A', 2), ('ORDER_B', 3), ('ORDER_C', 1)), *, status='交易成功', mutate=None, extra=None):
    rows, refs = table(groups, status=status)
    if mutate:
        mutate(rows, refs)
    xml = sheet_xml(rows)
    merges = '<mergeCells>' + ''.join(f'<mergeCell ref="{ref}"/>' for ref in refs) + '</mergeCells>'
    xml = xml.replace('</worksheet>', merges + '</worksheet>')
    raw = workbook(rows=rows, sheet_override=xml, extra_parts={
        '[Content_Types].xml': content_types_with_binary_default(), **(extra or {})})
    return {'source':'taobao', 'kind':'orders', 'file':file_payload(raw, sheet='支付账单')}


def preview(client, headers, value):
    result = client.post(PREFIX+'imports/preview', json=value, headers=headers)
    assert result.status_code == 200, result.json
    return result.json


def save(client, headers, value):
    shown = preview(client, headers, value)
    assert shown['errorCount'] == 0 and shown['previewToken']
    result = client.post(PREFIX+'imports/confirm', json={**value,'previewToken':shown['previewToken']}, headers=headers)
    assert result.status_code == 200, result.json
    return shown, result.json


def overview(client):
    return client.get(PREFIX+'overview?month=2026-09').json


@pytest.mark.parametrize('count', [2, 3])
def test_explicit_group_keeps_all_items_and_counts_only_anchor_paid_amount(count):
    parsed = parse_import(payload((('ORDER_A', count),)))
    assert parsed['errorCount'] == 0 and len(parsed['rows']) == 1
    row = parsed['rows'][0]
    assert row['amountCents'] == 10000 and row['flow'] == 'unknown'
    assert row['title'].endswith(f'等 {count} 项商品')
    assert row['orderGroup'] == {'format':'taobao-merged-v1','itemCount':count,
                                 'sourceRows':list(range(2,count+2)),'shippingAmountText':'5.00'}
    assert len(row['orderItems']) == count
    for n,item in enumerate(row['orderItems']):
        assert item == {'title':f'PRIVATE_ITEM_ORDER_A_{n}','variant':'SYNTHETIC_VARIANT',
                        'quantityText':'2','listedAmountText':'999.99',
                        'productUrl':'https://example.invalid/never-fetch','sourceLine':n+2}
    assert any('CNY' in warning for warning in parsed['warnings'])
    assert '_worksheetStructure' not in parsed['fileInfo']


def test_mixed_single_groups_newlines_and_long_item_title_keep_source_coordinates():
    def modify(rows, refs):
        rows[1][4] = '完整商品名称' * 50 + '\n第二行'
        rows[1][6] = ''
    parsed = parse_import(payload(mutate=modify))
    assert len(parsed['rows']) == 3 and parsed['errorCount'] == 0
    assert sum(len(r['orderItems']) for r in parsed['rows']) == 6
    assert parsed['rows'][0]['orderItems'][0]['title'] == '完整商品名称' * 50 + '\n第二行'
    assert len(parsed['rows'][0]['title']) == 200
    assert [r['line'] for r in parsed['rows']] == [2,4,7]
    assert parsed['rows'][-1]['orderGroup']['sourceRows'] == [7]
    assert parsed['rows'][-1]['title'] == 'PRIVATE_ITEM_ORDER_C_0'


def test_item_strings_are_not_parsed_as_prices_quantities_or_fetchable_urls():
    def modify(rows, refs):
        rows[1][4] = '<b>synthetic item</b>'
        rows[1][5] = 'javascript:synthetic-never-execute'
        rows[1][7] = '02 件'
        rows[1][8] = '￥999.00（原价）'
        rows[2][8] = '88.00 / 套'
    parsed = parse_import(payload((('ORDER_A', 2),), mutate=modify))
    row = parsed['rows'][0]
    assert parsed['errorCount'] == 0 and row['amountCents'] == 10000
    assert parsed['amountSelection']['selectedIndex'] == 9
    assert not parsed['requiresAmountSelection']
    assert row['orderItems'][0]['title'] == '<b>synthetic item</b>'
    assert row['orderItems'][0]['productUrl'] == 'javascript:synthetic-never-execute'
    assert row['orderItems'][0]['quantityText'] == '02 件'
    assert [item['listedAmountText'] for item in row['orderItems']] == ['￥999.00（原价）', '88.00 / 套']


def test_reader_structure_is_internal_opt_in_and_not_a_client_file_parameter():
    file = payload()['file']
    _, standard = read_financial_file(file)
    assert '_worksheetStructure' not in standard
    _, structured = read_financial_file(file, include_structure=True)
    assert structured['_worksheetStructure']['rows'][1] == TAOBAO_ORDER_HEADERS
    _, discovery = read_financial_file(file, include_structure=True, inspect_sheets=True)
    assert '_worksheetStructure' not in discovery
    with pytest.raises(FinancialFileError):
        read_financial_file({**file,'include_structure':True})
    with pytest.raises(FinancialFileError):
        read_financial_file(file, include_structure='true')


@pytest.mark.parametrize('source,kind', [('generic','orders'),('pinduoduo','orders'),('alipay','payments'),
                                        ('wechat','payments'),('taobao','payments')])
def test_other_sources_and_kinds_never_fill_order_continuations(source,kind):
    value = payload()
    value.update(source=source,kind=kind)
    with pytest.raises(FinanceHubError):
        parse_import(value)  # The source-specific date alias is not generalised.


def test_csv_and_unrecognised_xlsx_headers_do_not_get_merge_semantics():
    rows,_ = table()
    output=io.StringIO(); csv.writer(output).writerows(rows)
    value={'source':'taobao','kind':'orders','csv':output.getvalue()}
    parsed=parse_import(value)
    assert parsed['errorCount']==3 and all('orderItems' not in r for r in parsed['rows'])
    def header(rows,refs): rows[0][0]='订单编号'
    parsed=parse_import(payload(mutate=header))
    assert parsed['errorCount']==3 and all('orderItems' not in r for r in parsed['rows'])


@pytest.mark.parametrize('case', ['mismatched_span','overlap','out_of_bounds','horizontal','missing_column_merge',
                                 'reversed','invalid_coordinate','merge_header','missing_anchor_id','missing_anchor_date',
                                 'missing_anchor_paid','missing_anchor_shipping','conflicting_child_id','conflicting_child_paid',
                                 'empty_product','missing_product_title','orphan_blank_date','merged_product_column'])
def test_invalid_geometry_or_missing_anchor_or_conflicting_continuation_has_no_token(app,case):
    def mutate(rows,refs):
        if case=='mismatched_span': refs[1]='B2'
        elif case=='overlap': refs.append('A3:A4')
        elif case=='out_of_bounds': refs[0]='A2:A5001'
        elif case=='horizontal': refs[0]='A2:B3'
        elif case=='missing_column_merge': refs.pop(1)
        elif case=='reversed': refs[0]='A3:A2'
        elif case=='invalid_coordinate': refs[0]='not-a-range'
        elif case=='merge_header': refs[0]='A1:A3'
        elif case.startswith('missing_anchor_'):
            rows[1][{'missing_anchor_id':0,'missing_anchor_date':1,'missing_anchor_paid':9,'missing_anchor_shipping':10}[case]]=''
        elif case=='conflicting_child_id': rows[2][0]='DIFFERENT_ORDER'
        elif case=='conflicting_child_paid': rows[2][9]='123.00'
        elif case=='empty_product': rows[2]=['']*11
        elif case=='missing_product_title': rows[2][4]=''
        elif case=='orphan_blank_date':
            rows[-1][1]=''; refs[:]=[r for r in refs if not r.endswith('7')]
        elif case=='merged_product_column': refs.append('E2:E3')
    client,headers=member(app)
    value=payload(mutate=mutate)
    result=client.post(PREFIX+'imports/preview',json=value,headers=headers)
    assert result.status_code==400 or (result.status_code==200 and result.json['errorCount']>0 and not result.json['previewToken'])
    assert overview(client)['totalRecordCount']==0


@pytest.mark.parametrize('case',['macro','external','formula','malicious_xml'])
def test_grouped_orders_retain_original_workbook_security_rejections(case):
    extra={}
    if case=='macro': extra['xl/vbaProject.bin']=b'synthetic'
    elif case=='external': extra['xl/worksheets/_rels/sheet1.xml.rels']=f'<Relationships xmlns="{REL}"><Relationship Id="x" Target="https://example.invalid" TargetMode="External"/></Relationships>'
    elif case=='formula': extra['xl/worksheets/sheet1.xml']=f'<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'
    else: extra['xl/worksheets/sheet1.xml']='<!DOCTYPE worksheet [<!ENTITY x "unsafe">]><worksheet>&x;</worksheet>'
    with pytest.raises(FinancialFileError):
        parse_import(payload(extra=extra))


def test_preview_confirm_replay_and_shifted_source_rows_do_not_duplicate_or_conflict(app):
    client,headers=member(app)
    value=payload((('ORDER_A',2),))
    shown=preview(client,headers,value)
    assert shown['newCount']==1 and shown['conflictCount']==0
    assert shown['totals'][0]['orderCents']==10000 and shown['totals'][0]['netSpendCents']==0
    original_token=shown['previewToken']
    first=client.post(PREFIX+'imports/confirm',json={**value,'previewToken':original_token},headers=headers)
    assert first.json['imported']==1
    original=overview(client)['transactions'][0]
    again=client.post(PREFIX+'imports/confirm',json={**value,'previewToken':original_token},headers=headers)
    assert again.json['imported']==0 and again.json['duplicates']==1 and again.json['conflicts']==0
    shifted=payload((('NEW_ORDER',1),('ORDER_A',2)))
    shifted['file']['name']='different-file.xlsx'
    shown,result=save(client,headers,shifted)
    assert shown['newCount']==1 and shown['duplicateCount']==1 and shown['conflictCount']==0
    assert result['imported']==1 and result['conflicts']==0
    kept=next(r for r in overview(client)['transactions'] if r['externalId']=='ORDER_A')
    assert kept==original
    assert shown['rows'][1]['orderGroup']['sourceRows']==[3,4]
    assert kept['orderGroup']['sourceRows']==[2,3]


@pytest.mark.parametrize('field',['title','variant','quantityText','listedAmountText','productUrl','shipping','order'])
def test_changed_item_metadata_is_visible_conflict_and_never_overwrites(app,field):
    client,headers=member(app)
    save(client,headers,payload((('ORDER_A',2),)))
    original=overview(client)['transactions'][0]
    def mutate(rows,refs):
        if field=='shipping': rows[1][10]='999'
        elif field=='order':
            rows[1][4:9],rows[2][4:9]=rows[2][4:9],rows[1][4:9]
        else: rows[2][{'title':4,'variant':6,'quantityText':7,'listedAmountText':8,'productUrl':5}[field]]='CHANGED'
    shown,result=save(client,headers,payload((('ORDER_A',2),),mutate=mutate))
    assert shown['conflictCount']==1 and shown['rows'][0]['conflict'] is True
    assert result['imported']==0 and result['conflicts']==1
    assert overview(client)['transactions']==[original]


def test_legacy_order_without_items_is_not_silently_enriched(app):
    client,headers=member(app)
    rows,_=table((('ORDER_A',1),)); out=io.StringIO(); csv.writer(out).writerows(rows)
    save(client,headers,{'source':'taobao','kind':'orders','csv':out.getvalue()})
    original=overview(client)['transactions'][0]
    assert 'orderItems' not in original
    shown,result=save(client,headers,payload((('ORDER_A',1),)))
    assert shown['conflictCount']==result['conflicts']==1 and result['imported']==0
    assert overview(client)['transactions']==[original]


@pytest.mark.parametrize('status',['交易关闭','待收货'])
def test_status_change_of_same_grouped_order_cannot_create_second_order(app,status):
    client,headers=member(app)
    save(client,headers,payload((('ORDER_A',2),)))
    original=overview(client)['transactions'][0]
    shown,result=save(client,headers,payload((('ORDER_A',2),),status=status))
    assert shown['duplicateCount']==shown['conflictCount']==1
    assert result['imported']==0 and result['conflicts']==1
    assert overview(client)['transactions']==[original]


def test_same_file_status_change_is_one_order_and_other_owner_is_independent(app):
    client,headers=member(app); other,oh=member(app,2)
    def mutate(rows,refs): rows[3][2]='交易关闭'
    value=payload((('ORDER_A',2),('ORDER_A',2)),mutate=mutate)
    shown,result=save(client,headers,value)
    assert (shown['newCount'],shown['duplicateCount'],shown['conflictCount'])==(1,1,1)
    assert (result['imported'],result['duplicates'],result['conflicts'])==(1,1,1)
    assert result['resultMonths']==[{'month':'2026-09','recordCount':1}]
    assert overview(client)['totals'][0]['orderCents']==10000
    again,replayed=save(client,headers,value)
    assert again['duplicateCount']==2 and replayed['imported']==0
    assert replayed['conflicts']==1 and replayed['resultMonths']==result['resultMonths']
    independent,other_result=save(other,oh,payload((('ORDER_A',2),),status='交易关闭'))
    assert independent['newCount']==1 and independent['conflictCount']==0
    assert other_result['imported']==1
    assert overview(other)['transactions'][0]['flow']=='excluded'
    assert overview(client)['transactions'][0]['flow']=='unknown'


def test_historical_multiple_records_with_same_order_id_are_kept_without_another_insert(app):
    client,headers=member(app)
    for status in ['交易成功','交易关闭']:
        rows,_=table((('ORDER_A',1),),status=status)
        output=io.StringIO(); csv.writer(output).writerows(rows)
        save(client,headers,{'source':'taobao','kind':'orders','csv':output.getvalue()})
    original=overview(client)['transactions']
    assert len(original)==2  # Existing ordinary CSV identity remains unchanged.
    value=payload((('ORDER_A',2),))
    shown,result=save(client,headers,value)
    assert shown['duplicateCount']==shown['conflictCount']==1
    assert result['imported']==0 and result['conflicts']==1
    assert result['resultMonths']==[{'month':'2026-09','recordCount':2}]
    assert overview(client)['transactions']==original
    assert save(client,headers,value)[1]['imported']==0


def test_token_tampering_members_tv_and_export_preserve_private_item_details(app):
    client,headers=member(app); other,oh=member(app,2)
    value=payload((('ORDER_A',2),))
    shown=preview(client,headers,value)
    changed=payload((('ORDER_A',3),))
    assert client.post(PREFIX+'imports/confirm',json={**changed,'previewToken':shown['previewToken']},headers=headers).status_code==400
    assert other.post(PREFIX+'imports/confirm',json={**value,'previewToken':shown['previewToken']},headers=oh).status_code==400
    save(client,headers,value)
    row=overview(client)['transactions'][0]
    exported,files=unpack(client.post('/api/portability/export',json={'includeShared':True},headers=headers))
    assert exported['personal']['transactions'][0]['orderItems']==row['orderItems']
    assert exported['personal']['transactions'][0]['orderGroup']==row['orderGroup']
    assert '_worksheetStructure' not in json.dumps(exported)
    other_export,other_files=unpack(other.post('/api/portability/export',json={'includeShared':True},headers=oh))
    assert other_export['personal']['transactions']==[]
    assert b'PRIVATE_ITEM_ORDER_A' not in b''.join(other_files.values())
    assert overview(other)['transactions']==[]
    assert client.get(PREFIX+'shared?month=2026-09').json['totals']==[]
    tv=app.test_client(); pair=tv.post('/api/pair/start',json={}).json
    assert client.post('/api/pair/approve',json={'code':pair['code'],'name':'SYNTHETIC_TV','focus':'member1'},headers=headers).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    assert tv.get(PREFIX+'overview').status_code==403
    assert tv.post(PREFIX+'imports/preview',json=value,headers=headers).status_code==403
    for viewer in [client,other,tv]:
        assert 'PRIVATE_ITEM_ORDER_A' not in viewer.get('/api/state').get_data(as_text=True)


def test_order_payment_and_shopping_settlement_use_paid_once_not_item_list_prices(app):
    from test_shopping_settlement import record, shopping, reconcile, settle
    client,headers=member(app)
    save(client,headers,payload((('ORDER_A',3),)))
    order=overview(client)['transactions'][0]
    payment=record(client,headers,amount='100.00')
    reconcile(client,headers,'order_payment',order,payment,'100.00')
    current=overview(client)
    assert current['totals'][0]['orderCents']==10000
    assert current['totals'][0]['netSpendCents']==10000
    linked=next(r for r in current['transactions'] if r['id']==order['id'])
    assert len(linked['orderItems'])==3
    item=shopping(client,headers)
    settle(client,headers,payment,item,amount=10000)
    shared=client.get('/api/state').json
    assert next(r for r in shared['shopping'] if r['id']==item['id'])['actual']==10000
    assert 'PRIVATE_ITEM_ORDER_A' not in json.dumps(shared)
