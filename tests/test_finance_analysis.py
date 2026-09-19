"""Real temporary households/sessions/SQLite; synthetic amounts, no public I/O."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
import json
import socket
import sqlite3
from threading import Barrier, Event
import time
from types import SimpleNamespace

from flask import g
import pytest

import app as server
import finance_analysis as analysis
import finance_fx as fx
import member_sessions
from test_app import app, member
from test_device_sessions import install_connection, invalidate
from test_household_spaces import create_space
from test_member_sessions import clone


URL = '/api/finance-analysis'
ACCOUNTS = '/api/finance-accounts'
START, END = '2026-09-01', '2026-09-18'
MID = '2026-09-10'
STAMP = '2026-09-19T01:00:00.000000+00:00'


@pytest.fixture(autouse=True)
def registration(monkeypatch):
    original_accounts = server.register_finance_accounts
    original_analysis = analysis.register_finance_analysis
    def register(module_app, db, Problem, body, require_member, audit, *, initialize=True):
        if 'finance_analysis_report' in module_app.view_functions:
            return
        def checked_audit(action, target=''):
            audit(action, target)
            if module_app.config.get('ANALYSIS_AUDIT_FAILURE'):
                raise RuntimeError('Synthetic analysis audit failure')
        original_analysis(module_app, db, Problem, body, require_member, checked_audit, initialize=initialize)
    def accounts(module_app, db, Problem, body, require_member, audit, *, initialize=True):
        original_accounts(module_app, db, Problem, body, require_member, audit, initialize=initialize)
        register(module_app, db, Problem, body, require_member, audit, initialize=initialize)
    monkeypatch.setattr(server, 'register_finance_accounts', accounts)
    monkeypatch.setattr(server, 'register_finance_analysis', register, raising=False)
    def deny(*_args, **_kwargs):
        raise AssertionError('No network in account analysis tests')
    monkeypatch.setattr(socket.socket, 'connect', deny)


@contextmanager
def database(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR']) / 'household.sqlite3', timeout=5)) as con:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        with con:
            yield con


def key(number):
    return f'{number:032x}'


def create(client, headers, number=1, opening=10000, closing=16000, **changes):
    payload = {'requestId': key(number), 'revision': 0, 'name': 'SYNTHETIC_PRIVATE_ANALYSIS', 'institution': '',
               'kind': 'asset', 'currency': 'CNY', 'note': '',
               'valuation': {'asOf': START, 'amountCents': opening}, **changes}
    response = client.post(ACCOUNTS, json=payload, headers=headers)
    assert response.status_code == 201, response.json
    rid = response.json['accountId']
    if closing is not ...:
        assert value(client, headers, rid, closing, number=number+100).status_code == 200
    return rid


def value(client, headers, rid, amount, revision=1, number=101, at=END):
    return client.put(ACCOUNTS + '/' + rid + '/valuations/' + at,
                      json={'requestId': key(number), 'revision': revision, 'amountCents': amount}, headers=headers)


def report(client, **changes):
    response = client.get(URL + '/report', query_string={'start': START, 'end': END, 'baseCurrency': 'CNY',
                                                       'step': 'month', 'accountIds': 'all', **changes})
    assert response.status_code == 200, response.json
    return response.json


def flow_payload(number=1, **changes):
    return {'requestId': key(number), 'revision': 0, 'date': MID, 'direction': 'in', 'amountCents': 3000,
            'note': 'SYNTHETIC_PRIVATE_FLOW', **changes}


def flow(client, headers, rid, number=1, **changes):
    result = client.post(URL + '/accounts/' + rid + '/cashflows', json=flow_payload(number, **changes), headers=headers)
    assert result.status_code == 200, result.json
    return result.json


def confirm(client, headers, rid, number=50, review=None):
    review = review or report(client, accountIds=rid)['accounts'][0]['review']
    return client.put(URL + '/accounts/' + rid + '/reviews/' + START + '/' + END,
                      json={'requestId': key(number), 'revision': review['revision'],
                            'contextDigest': review['contextDigest'], 'confirmed': True}, headers=headers)


def operation(client, number):
    result = client.get(URL + '/operations/' + key(number))
    assert result.status_code == 200, result.json
    return result.json


def snapshot(app):
    with database(app) as con:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        excluded = {'users', 'member_sessions', 'member_session_browsers', 'attempts'}
        return {name: [tuple(row) for row in con.execute('SELECT * FROM "' + name + '" ORDER BY rowid')]
                for name in names if name not in excluded}


def batch(start='2026-08-25', end=END, rates=None, stamp=STAMP):
    return {'provider': 'ECB', 'sourceUrl': fx.ecb_url(start, end), 'retrievedAt': stamp,
            'bodySha256': 'a'*64, 'requestedStart': start, 'requestedEnd': end,
            'rates': rates or [dict(date=at, currency=currency, unitsPerEur=rate)
                               for at, usd, cny in [(START, '2', '8'), (MID, '2', '9'), (END, '2', '10')]
                               for currency, rate in [('USD', usd), ('CNY', cny)]]}


def save_rates(app, data=None):
    with database(app) as con:
        con.execute('BEGIN IMMEDIATE')
        return fx.save_fx_batch(con, data or batch())


def denied(response, status):
    assert response.status_code == status, response.json
    assert set(response.json) == {'error', 'code'}
    assert 'SYNTHETIC_PRIVATE' not in response.get_data(as_text=True)


def test_only_four_tables_transactional_foreign_keys_and_idempotent():
    with closing(sqlite3.connect(':memory:')) as con:
        con.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        con.execute('CREATE TABLE finance_accounts(owner TEXT,id TEXT,UNIQUE(owner,id))')
        con.commit()
        con.execute('BEGIN')
        analysis.init_schema(con)
        assert con.in_transaction
        con.rollback()
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 2
        analysis.init_schema(con)
        analysis.init_schema(con)
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == {'users', 'finance_accounts', 'finance_account_profiles', 'finance_account_cashflows',
                         'finance_account_reviews', 'finance_analysis_operations'}
        con.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):
            con.execute('INSERT INTO finance_account_cashflows VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('x', 'stranger', 'foreign', START, 'in', 1, '', 1, 't', 't'))


def test_unknown_flow_completeness_is_never_zero_or_return(app):
    client, headers = member(app)
    rid = create(client, headers)
    view = report(client)
    item = view['accounts'][0]
    assert item['account']['visibility'] == 'private' and set(item['account']) == {
        'id','owner','name','institution','kind','currency','note','archived','revision','createdAt','updatedAt','visibility'}
    assert item['profile'] == {'accountId': rid, 'assetClass': 'unknown', 'liquidity': 'unknown', 'revision': 0, 'updatedAt': None}
    assert item['review']['status'] == 'unreviewed' and item['review']['canConfirm']
    assert item['change']['originalChangeCents'] == '6000'
    assert item['change']['recordedNetFlowCents'] == '0'
    assert item['change']['valuationResidualCents'] is None
    assert item['change']['convertedNetFlowCents'] is None and not view['change']['complete']
    assert item['opening']['fx']['method'] == 'identity' and item['opening']['fx']['observations'] == []
    assert confirm(client, headers, rid).status_code == 200
    confirmed = report(client)['accounts'][0]
    assert confirmed['change']['valuationResidualCents'] == '6000'
    assert confirmed['change']['convertedNetFlowCents'] == '0'
    assert confirmed['change']['status'] == 'complete'


def test_exact_fx_decomposition_signed_flows_and_liability_net(app):
    client, headers = member(app)
    asset = create(client, headers, currency='USD')
    debt = create(client, headers, number=2, opening=8000, closing=7000, kind='liability', currency='USD')
    flow(client, headers, asset, 1, amountCents=4000)
    flow(client, headers, asset, 2, amountCents=1000, direction='out')
    flow(client, headers, debt, 3, amountCents=1000, direction='out')
    save_rates(app)
    assert confirm(client, headers, asset, 51).status_code == 200
    assert confirm(client, headers, debt, 52).status_code == 200
    view = report(client)
    by_id = {item['account']['id']: item for item in view['accounts']}
    assert by_id[asset]['change'] == {
        'originalChangeCents': '6000', 'recordedNetFlowCents': '3000', 'valuationResidualCents': '3000',
        'convertedChangeCents': '40000', 'convertedNetFlowCents': '13500',
        'convertedValuationResidualCents': '15000', 'fxEffectCents': '11500', 'roundingCents': '0', 'status': 'complete'}
    assert by_id[debt]['change']['convertedChangeCents'] == '3000'
    assert view['change'] == {'convertedChangeCents': '37000', 'convertedNetFlowCents': '18000',
                              'convertedValuationResidualCents': '15000', 'fxEffectCents': '4000',
                              'roundingCents': '0', 'complete': True, 'reviewedCount': 2}
    assert view['summary']['knownAssetCents'] == '80000' and view['summary']['knownLiabilityCents'] == '35000'
    assert view['summary']['knownNetCents'] == '45000'
    assert sum(int(bucket['knownCents']) for bucket in view['allocation']) == 80000
    quote = by_id[asset]['closing']['fx']
    assert quote['rateDate'] == END and len(quote['observations']) == 2
    assert all(len(o['version']) == 64 and o['bodySha256'] == 'a'*64 for o in quote['observations'])


def test_rounding_components_are_explicit_and_close_exact_change(app):
    client, headers = member(app)
    rid = create(client, headers, opening=1, closing=3, currency='USD')
    event = flow(client, headers, rid, amountCents=1)['result']
    data = batch(rates=[dict(date=at, currency='USD', unitsPerEur=usd) for at, usd in [(START, '2'), (MID, '3'), (END, '2')]])
    save_rates(app, data)
    review = report(client, baseCurrency='EUR')['accounts'][0]['review']
    assert confirm(client, headers, rid, review=review).status_code == 200
    change = report(client, baseCurrency='EUR')['accounts'][0]['change']
    assert change['convertedChangeCents'] == '1'
    assert change['convertedNetFlowCents'] == '0'
    assert change['convertedValuationResidualCents'] == '1'
    assert change['fxEffectCents'] == '0' and change['roundingCents'] == '0'
    # A separate case proves nonzero reconciliation of endpoint/component rounding.
    assert value(client, headers, rid, 2, revision=2, number=102).status_code == 200
    assert client.patch(URL+'/accounts/'+rid+'/cashflows/'+event['id'],
                        json=flow_payload(2,revision=1,amountCents=0),headers=headers).status_code == 200
    assert confirm(client, headers, rid, number=51).status_code == 200
    change = report(client, baseCurrency='EUR')['accounts'][0]['change']
    assert change['convertedChangeCents'] == '0'
    assert change['roundingCents'] == '-1'
    assert sum(int(change[f]) for f in ('convertedNetFlowCents','convertedValuationResidualCents','fxEffectCents','roundingCents')) == 0
    assert analysis.rounded(Fraction(-1, 2)) == -1


def test_missing_unknown_old_valuation_and_missing_fx_coverage(app):
    client, headers = member(app)
    known = create(client, headers)
    create(client, headers, number=2, closing=None)
    create(client, headers, number=3, closing=...)
    create(client, headers, number=4, currency='USD')
    create(client, headers, number=5, valuation={'asOf': '2026-09-19', 'amountCents': 0}, closing=...)
    view = report(client)
    assert view['summary']['coverage'] == {'selectedCount': 5, 'knownValuationCount': 3, 'convertedCount': 2,
        'missingValuationCount': 1, 'unknownValuationCount': 1, 'olderValuationCount': 1, 'missingFxCount': 1}
    assert not view['summary']['complete']
    unknown = next(i for i in view['accounts'] if i['closing']['valuation'] and i['closing']['valuation']['amountCents'] is None)
    assert unknown['closing']['convertedCents'] is None and not unknown['review']['canConfirm']
    assert confirm(client, headers, unknown['account']['id']).json['code'] == 'missing_valuations'
    assert report(client, accountIds=known)['summary']['complete']


def test_no_same_day_fx_or_flow_fx_does_not_invent_attribution(app):
    client, headers = member(app)
    rid = create(client, headers, currency='USD')
    flow(client, headers, rid)
    save_rates(app, batch(rates=[dict(date=at, currency=c, unitsPerEur=r)
                               for at in [START, END] for c, r in [('USD','2'),('CNY','10')]]))
    assert confirm(client, headers, rid).status_code == 200
    view = report(client)['accounts'][0]
    assert view['change']['originalChangeCents'] == '6000' and view['change']['valuationResidualCents'] == '3000'
    assert view['change']['convertedChangeCents'] == '30000'
    assert view['change']['convertedNetFlowCents'] is None and view['change']['status'] == 'missing_fx'
    assert not report(client)['change']['complete']
    # The newer USD observation cannot be combined with an older CNY observation.
    save_rates(app, batch(rates=[dict(date='2026-09-17',currency='USD',unitsPerEur='1')], stamp='2026-09-19T02:00:00+00:00'))
    assert report(client)['accounts'][0]['closing']['fx']['rateDate'] == END


def test_profile_is_separate_revision_allocation_excludes_debt_and_archives_keep_history(app):
    client, headers = member(app)
    rid = create(client, headers)
    debt = create(client, headers, number=2, kind='liability', closing=20000)
    before = report(client, accountIds=rid)['accounts'][0]['account']
    payload = {'requestId': key(1), 'revision': 0, 'assetClass': 'cash', 'liquidity': 'immediate'}
    first = client.put(URL + '/accounts/' + rid + '/profile', json=payload, headers=headers)
    assert first.status_code == 200 and first.json['result']['revision'] == 1
    current = report(client, accountIds=rid)['accounts'][0]
    assert current['account'] == before and current['profile']['assetClass'] == 'cash'
    assert client.patch(ACCOUNTS + '/' + rid, json={'requestId': key(201), 'revision': 2,
                                                 'changes': {'archived': True}}, headers=headers).status_code == 200
    view = report(client)
    assert set(view['accountIds']) == {rid, debt} and view['summary']['knownNetCents'] == '-4000'
    assert [b for b in view['allocation'] if b['key'] == 'cash'] == [{'key': 'cash', 'knownCents': '16000', 'count': 1}]
    denied(client.post(URL + '/accounts/' + rid + '/cashflows', json=flow_payload(2), headers=headers), 409)
    assert client.put(URL + '/accounts/' + rid + '/profile', json=payload, headers=headers).json['replayed']


@pytest.mark.parametrize('mutation', ['amount','flow_create','flow_update','flow_delete','account_revision'])
def test_review_digest_rejects_race_and_becomes_stale_after_source_revision(app, mutation):
    client, headers = member(app)
    rid = create(client, headers)
    event = flow(client, headers, rid)['result']
    old = report(client)['accounts'][0]['review']
    assert confirm(client, headers, rid).status_code == 200
    if mutation == 'amount':
        assert value(client, headers, rid, 17000, revision=2, number=202).status_code == 200
    elif mutation == 'flow_create':
        flow(client, headers, rid, 2, amountCents=0)
    elif mutation == 'flow_update':
        result = client.patch(URL + '/accounts/' + rid + '/cashflows/' + event['id'],
                              json=flow_payload(2, revision=1, amountCents=3500), headers=headers)
        assert result.status_code == 200
    elif mutation == 'flow_delete':
        assert client.delete(URL + '/accounts/' + rid + '/cashflows/' + event['id'],
                             json={'requestId':key(2),'revision':1}, headers=headers).status_code == 200
    else:
        assert client.patch(ACCOUNTS + '/' + rid, json={'requestId':key(202),'revision':2,'changes':{'note':'changed'}}, headers=headers).status_code == 200
    item = report(client)['accounts'][0]
    assert item['review']['status'] == 'stale' and item['review']['contextDigest'] != old['contextDigest']
    assert item['change']['valuationResidualCents'] is None and item['change']['status'] == 'stale'
    denied(confirm(client, headers, rid, 51, {**old, 'revision':1}), 409)
    assert not operation(client, 51)['found']
    assert confirm(client, headers, rid, 52).status_code == 200
    # Original successful receipt is recoverable, but never replaces current review.
    assert confirm(client, headers, rid, 50, old).json['replayed']
    assert report(client)['accounts'][0]['review']['revision'] == 2


def test_cashflows_start_exclusive_pagination_crud_conflicts_and_historical_receipt(app):
    client, headers = member(app)
    rid = create(client, headers)
    flow(client, headers, rid, 1, date=START)
    first = flow(client, headers, rid, 2)
    flow(client, headers, rid, 3, date=END, direction='out')
    path = URL + '/accounts/' + rid + '/cashflows'
    pages = [client.get(path, query_string={'start':START,'end':END,'page':p,'pageSize':1}).json for p in [1,2,3]]
    assert [p['total'] for p in pages] == [2,2,2] and len(pages[2]['items']) == 0
    event_path = path + '/' + first['result']['id']
    assert client.patch(event_path,json=flow_payload(4, revision=1, amountCents=2000),headers=headers).json['result']['revision'] == 2
    denied(client.delete(event_path,json={'requestId':key(5),'revision':1},headers=headers),409)
    assert client.delete(event_path,json={'requestId':key(5),'revision':2},headers=headers).json['result']['deleted']
    before = snapshot(app)
    assert client.post(path,json=flow_payload(2),headers=headers).json == {**first,'replayed':True}
    assert snapshot(app) == before
    assert operation(client, 2)['receipt']['result']['id'] == first['result']['id']
    denied(client.post(path,json=flow_payload(2, amountCents=0),headers=headers),409)
    denied(client.patch(event_path,json=flow_payload(6,revision=2),headers=headers),404)


def test_cashflow_add_delete_or_move_back_never_reactivates_prior_review(app):
    client, headers = member(app)
    rid = create(client, headers)
    assert confirm(client, headers, rid).status_code == 200
    original = report(client)['accounts'][0]['review']
    outside = flow(client, headers, rid, 1, date=START)['result']
    assert report(client)['accounts'][0]['review']['status'] == 'current'
    event = flow(client, headers, rid, 2)['result']
    assert report(client)['accounts'][0]['review']['status'] == 'stale'
    assert client.delete(URL+'/accounts/'+rid+'/cashflows/'+event['id'],
                         json={'requestId':key(3),'revision':1},headers=headers).status_code == 200
    after = report(client)['accounts'][0]['review']
    assert after['cashflowCount'] == 0 and after['status'] == 'stale'
    assert after['contextDigest'] != original['contextDigest']
    assert confirm(client, headers, rid, 51).status_code == 200
    for number, at, rev in [(4,MID,1),(5,START,2)]:
        assert client.patch(URL+'/accounts/'+rid+'/cashflows/'+outside['id'],
                            json=flow_payload(number,revision=rev,date=at),headers=headers).status_code == 200
    assert report(client)['accounts'][0]['review']['status'] == 'stale'


def test_old_account_receipts_namespace_export_and_unrelated_tables_unchanged(app):
    client, headers = member(app)
    rid = create(client, headers)
    old_receipt = client.get(ACCOUNTS + '/operations/' + key(1)).json
    before = snapshot(app)
    flow(client, headers, rid, 1)
    assert confirm(client, headers, rid).status_code == 200
    assert client.get(ACCOUNTS + '/operations/' + key(1)).json == old_receipt
    after = snapshot(app)
    changed = {'finance_account_cashflows','finance_account_reviews','finance_analysis_operations','audit','settings','sqlite_sequence'}
    assert {t:r for t,r in before.items() if t not in changed} == {t:r for t,r in after.items() if t not in changed}
    with database(app) as con:
        exported = analysis.export_owned_analysis(con,'member1')
        assert set(exported) == {'profiles','cashflows','reviews','operations'}
        assert len(exported['cashflows']) == len(exported['reviews']) == 1
        assert len(exported['operations']) == 2
        assert analysis.export_owned_analysis(con,'member2') == dict(profiles=[],cashflows=[],reviews=[],operations=[])
    encoded = json.dumps(exported)
    assert all(secret not in encoded for secret in ['payload_hash','credential_hash','session','requestId'])
    assert 'SYNTHETIC_PRIVATE' not in client.get('/api/state').get_data(as_text=True)


def test_timeline_month_end_same_selected_set_and_exact_large_sums(app):
    client, headers = member(app)
    with database(app) as con:
        for n in range(100):
            rid = f'{n:024x}'
            con.execute('INSERT INTO finance_accounts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (rid,'member1','BIG','','asset','CNY','',int(n==0),1,'t','t'))
            for at in ['2026-01-15','2026-03-04']:
                con.execute('INSERT INTO finance_account_valuations VALUES(?,?,?,?,?)',('member1',rid,at,10**14,'t'))
    view = report(client,start='2026-01-15',end='2026-03-04')
    assert [p['date'] for p in view['series']] == ['2026-01-15','2026-01-31','2026-02-28','2026-03-04']
    assert all(p['summary']['knownNetCents'] == '10000000000000000' for p in view['series'])
    assert all(p['summary']['coverage']['selectedCount'] == 100 for p in view['series'])
    assert view['series'][1]['summary']['coverage']['olderValuationCount'] == 100
    assert not view['series'][1]['summary']['complete'] and view['summary']['complete']


def test_anonymous_partner_tv_csrf_and_cross_household(app):
    client, headers = member(app)
    rid = create(client, headers)
    flow(client, headers, rid)
    paths = [URL+'/report?start='+START+'&end='+END, URL+'/operations/'+key(1),
             URL+'/accounts/'+rid+'/cashflows?start='+START+'&end='+END]
    for path in paths:
        denied(app.test_client().get(path),401)
    denied(client.post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(2)),403)
    denied(client.post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(2),headers={**headers,'Origin':'https://evil.example'}),403)
    partner, ph = member(app,2)
    assert report(partner)['accounts'] == [] and not operation(partner,1)['found']
    denied(partner.get(paths[0]+'&accountIds='+rid),404)
    denied(partner.get(paths[2]),404)
    denied(partner.post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(2),headers=ph),404)
    tv = app.test_client()
    pair = tv.post('/api/pair/start',json={}).json
    assert client.post('/api/pair/approve',json={'code':pair['code'],'name':'Synthetic TV'},headers=headers).status_code == 200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    for path in paths:
        denied(tv.get(path),403)
    other, _, space = create_space(app)
    assert other.get(space['entry']).status_code == 303
    assert other.post('/api/login',json={'username':'member1','password':'second-home-password-one'}).status_code == 200
    assert report(other)['accounts'] == [] and not operation(other,1)['found']
    denied(other.get(paths[0]+'&accountIds='+rid),404)


@pytest.mark.parametrize('field,bad', [('requestId',True),('requestId','A'*32),('revision',True),('revision',1),
    ('date','1999-01-03'),('date','2026-02-30'),('date','2026-2-3'),('direction',[]),('direction','income'),
    ('amountCents',True),('amountCents',None),('amountCents',1.0),('amountCents',-1),('amountCents',10**14+1),
    ('note','x'*1001),('note','bad\x00'),('note','\ud800'),('owner','member2'),('extra',0)])
def test_strict_flow_rejection_keeps_database_and_receipt(app, field, bad):
    client, headers = member(app)
    rid = create(client, headers)
    before = snapshot(app)
    denied(client.post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(**{field:bad}),headers=headers),400)
    assert not operation(client,1)['found'] and snapshot(app) == before


@pytest.mark.parametrize('query', [{'start':'2026-09-18'},{'start':'2025-09-17'}, {'start':'1999-01-03'},
    {'step':'year'}, {'baseCurrency':'cny'}, {'accountIds':''}, {'accountIds':'x'*24}, {'extra':'1'},
    {'accountIds': ','.join(['a'*24]*301)}, {'accountIds': 'a'*24+','+'a'*24}])
def test_strict_report_query(app, query):
    client, _ = member(app)
    result = client.get(URL+'/report',query_string={'start':START,'end':END,**query})
    denied(result,400)


def test_duplicate_json_queries_and_oversize(app):
    client, headers = member(app)
    rid = create(client, headers)
    path = URL+'/accounts/'+rid+'/cashflows'
    before = snapshot(app)
    for raw in ['[]','{"requestId":"a","requestId":"b"}','{"nested":{"a":1,"a":2}}','{"n":NaN}','{bad']:
        denied(client.post(path,data=raw,content_type='application/json',headers=headers),400)
    denied(client.post(path,data=' '*17000,content_type='application/json',headers=headers),413)
    denied(client.get(URL+'/report?start='+START+'&end='+END+'&end='+END),400)
    denied(client.get(path+'?start='+START+'&end='+END+'&pageSize=101'),400)
    denied(client.get(URL+'/operations/'+key(1)+'?owner=member2'),400)
    assert snapshot(app) == before


@pytest.mark.parametrize('limit', ['flows','operations','bytes'])
def test_capacity_preserves_state_and_allows_old_receipts(app,monkeypatch,limit):
    client, headers = member(app)
    rid = create(client,headers)
    original = flow(client,headers,rid)
    monkeypatch.setattr(analysis,{'flows':'MAX_CASHFLOWS','operations':'MAX_OPERATIONS','bytes':'MAX_OPERATION_BYTES'}[limit],1)
    before = snapshot(app)
    denied(client.post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(2),headers=headers),409)
    assert snapshot(app) == before
    assert client.post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(),headers=headers).json == {**original,'replayed':True}


def test_receipt_byte_limit_after_apply_rolls_back_new_event(app,monkeypatch):
    client,headers=member(app)
    rid=create(client,headers)
    flow(client,headers,rid)
    with database(app) as con:
        used=con.execute('SELECT sum(length(CAST(result AS BLOB))) FROM finance_analysis_operations').fetchone()[0]
    monkeypatch.setattr(analysis,'MAX_OPERATION_BYTES',used+1)
    before=snapshot(app)
    denied(client.post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(2),headers=headers),409)
    assert snapshot(app) == before and not operation(client,2)['found']


def test_revoked_session_overrides_owner_not_found_error(app):
    client,_=member(app)
    calls=[]
    def after(sql):
        if 'FROM finance_accounts WHERE' in sql and not calls:
            with database(app) as con:
                invalidate(con)
            calls.append(True)
    install_connection(app,URL+'/report','GET',after=after)
    denied(client.get(URL+'/report',query_string={'start':START,'end':END,'accountIds':'f'*24}),401)
    assert calls == [True]


@pytest.mark.parametrize('route', ['report','cashflows','receipt','missing_receipt'])
@pytest.mark.parametrize('kind', ['session','expired','auth_version'])
def test_read_and_error_response_recheck_after_snapshot_release(app,route,kind):
    client, headers = member(app)
    rid = create(client,headers)
    flow(client,headers,rid)
    path = {'report':URL+'/report','cashflows':URL+'/accounts/'+rid+'/cashflows',
            'receipt':URL+'/operations/'+key(1),'missing_receipt':URL+'/operations/'+key(2)}[route]
    calls=[]
    def after(sql):
        trigger = 'FROM finance_analysis_operations WHERE' if 'receipt' in route else 'FROM finance_accounts WHERE'
        if trigger in sql and not calls:
            with database(app) as con:
                invalidate(con,kind)
            calls.append(True)
    install_connection(app,path,'GET',after=after)
    denied(client.get(path,query_string={'start':START,'end':END} if route in ('report','cashflows') else None),401)
    assert calls == [True]


@pytest.mark.parametrize('kind', ['session','expired','auth_version'])
@pytest.mark.parametrize('replay', [False,True])
def test_writes_revalidate_actual_session_after_database_lock_wait(app,kind,replay):
    client, headers = member(app)
    rid = create(client,headers)
    if replay:
        flow(client,headers,rid)
    path = URL+'/accounts/'+rid+'/cashflows'
    before, entered = snapshot(app),Event()
    with closing(sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3',timeout=5,check_same_thread=False)) as writer:
        def hold(sql):
            if sql == 'BEGIN IMMEDIATE':
                writer.execute('BEGIN IMMEDIATE')
                invalidate(writer,kind)
                entered.set()
        install_connection(app,path,'POST',before=hold)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(client.post,path,json=flow_payload(),headers=headers)
            try:
                assert entered.wait(10) and not future.done()
            finally:
                writer.commit()
            denied(future.result(timeout=10),401)
    assert snapshot(app) == before


@pytest.mark.parametrize('failure',['audit','expiry'])
def test_cashflow_and_receipt_rollback_together_on_audit_or_commit_expiry(app,monkeypatch,failure):
    client,headers=member(app)
    rid=create(client,headers)
    before=snapshot(app)
    path=URL+'/accounts/'+rid+'/cashflows'
    if failure == 'audit':
        app.config['ANALYSIS_AUDIT_FAILURE']=True
        with pytest.raises(RuntimeError,match='Synthetic analysis audit failure'):
            client.post(path,json=flow_payload(),headers=headers)
    else:
        with database(app) as con:
            expires=con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
        clock=[time.time()]
        monkeypatch.setattr(member_sessions,'time',SimpleNamespace(time=lambda:clock[0]))
        def after(sql):
            if sql.startswith('UPDATE settings SET revision'):
                clock[0]=expires+1
        install_connection(app,path,'POST',after=after)
        denied(client.post(path,json=flow_payload(),headers=headers),401)
        assert clock[0] == expires+1
    assert snapshot(app) == before


@pytest.mark.parametrize('conflict',[False,True])
def test_real_concurrent_cashflows_have_one_effect_per_key(app,conflict):
    client,headers=member(app)
    rid=create(client,headers)
    clients=[client,clone(app,client)]
    barrier=Barrier(2)
    def send(n):
        barrier.wait(timeout=10)
        return clients[n].post(URL+'/accounts/'+rid+'/cashflows',json=flow_payload(amountCents=1+n if conflict else 1),headers=headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(send,[0,1]))
    assert sorted(r.status_code for r in results) == ([200,409] if conflict else [200,200])
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM finance_account_cashflows').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM finance_analysis_operations').fetchone()[0] == 1


def test_refresh_network_outside_transaction_atomic_cache_receipt_and_replay_no_network(app,monkeypatch):
    client,headers=member(app)
    calls=[]
    def fetch(start,end):
        assert not g.db.in_transaction
        with database(app) as con:
            con.execute('BEGIN IMMEDIATE')
            assert con.execute('SELECT count(*) FROM finance_analysis_operations').fetchone()[0] == 0
        calls.append((start,end))
        return batch(start,end)
    monkeypatch.setattr(fx,'fetch_ecb_rates',fetch)
    payload={'requestId':key(1),'start':START,'end':END}
    first=client.post(URL+'/rates/refresh',json=payload,headers=headers)
    assert first.status_code == 200 and first.json['accountId'] is None
    assert first.json['result']['inserted'] == 6 and first.json['result']['rateCount'] == 6
    assert calls == [('2026-08-25',END)]
    assert operation(client,1)['receipt'] == {**first.json,'replayed':True}
    def fail_network(*_):
        raise fx.FxError('Synthetic unavailable','fx_unavailable')
    monkeypatch.setattr(fx,'fetch_ecb_rates',fail_network)
    before=snapshot(app)
    assert client.post(URL+'/rates/refresh',json=payload,headers=headers).json == {**first.json,'replayed':True}
    denied(client.post(URL+'/rates/refresh',json={**payload,'requestId':key(2)},headers=headers),502)
    assert snapshot(app) == before and not operation(client,2)['found']


@pytest.mark.parametrize('failure',['revoked_network','audit','expiry'])
def test_refresh_failure_never_leaves_cache_without_receipt(app,monkeypatch,failure):
    client,headers=member(app)
    before=snapshot(app)
    def fetch(start,end):
        assert not g.db.in_transaction
        if failure == 'revoked_network':
            with database(app) as con:
                invalidate(con)
        return batch(start,end)
    monkeypatch.setattr(fx,'fetch_ecb_rates',fetch)
    payload={'requestId':key(1),'start':START,'end':END}
    if failure == 'audit':
        app.config['ANALYSIS_AUDIT_FAILURE']=True
        with pytest.raises(RuntimeError,match='Synthetic analysis audit failure'):
            client.post(URL+'/rates/refresh',json=payload,headers=headers)
    else:
        if failure == 'expiry':
            with database(app) as con:
                expires=con.execute("SELECT max(expires_at) FROM member_sessions WHERE owner='member1'").fetchone()[0]
            clock=[time.time()]
            monkeypatch.setattr(member_sessions,'time',SimpleNamespace(time=lambda:clock[0]))
            def after(sql):
                if sql.startswith('UPDATE settings SET revision'):
                    clock[0]=expires+1
            install_connection(app,URL+'/rates/refresh','POST',after=after)
        denied(client.post(URL+'/rates/refresh',json=payload,headers=headers),401)
    assert snapshot(app) == before


def test_refresh_key_conflict_never_calls_public_fetch_and_cache_error_is_safe(app,monkeypatch):
    client,headers=member(app)
    rid=create(client,headers)
    flow(client,headers,rid)
    calls=[]
    def fetch(start,end):
        calls.append(True)
        return batch(start,end)
    monkeypatch.setattr(fx,'fetch_ecb_rates',fetch)
    denied(client.post(URL+'/rates/refresh',json={'requestId':key(1),'start':START,'end':END},headers=headers),409)
    assert not calls
    def invalid_save(con,data):
        con.execute('INSERT INTO finance_fx_rates VALUES(?,?,?,?,?,?,?,?)',('b'*64,START,'USD','2',data['sourceUrl'],'a'*64,STAMP,STAMP))
        raise fx.FxError('Synthetic cache cannot be validated')
    monkeypatch.setattr(fx,'save_fx_batch',invalid_save)
    before=snapshot(app)
    denied(client.post(URL+'/rates/refresh',json={'requestId':key(2),'start':START,'end':END},headers=headers),503)
    assert snapshot(app) == before and not operation(client,2)['found']


def freeze_utc(monkeypatch, instant):
    clock = [datetime.fromisoformat(instant)]
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz is not None else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(analysis, 'datetime', FrozenDateTime)
    return clock


@pytest.mark.parametrize('instant,selected_end,observed_end', [
    ('2026-09-18T15:59:59+00:00', '2026-09-18', '2026-09-18'),
    ('2026-09-18T16:00:00+00:00', '2026-09-19', '2026-09-18'),
    ('2026-09-18T23:59:59+00:00', '2026-09-19', '2026-09-18'),
    ('2026-09-19T00:00:00+00:00', '2026-09-19', '2026-09-19'),
])
def test_refresh_shanghai_midnight_clips_only_network_date_and_preserves_replay(app, monkeypatch, instant, selected_end, observed_end):
    client, headers = member(app)
    create(client, headers, currency='USD')
    clock = freeze_utc(monkeypatch, instant)
    calls = []
    def fetch(start, end):
        assert not g.db.in_transaction
        assert end <= clock[0].date().isoformat()
        calls.append((start, end))
        return batch(start, end)
    monkeypatch.setattr(fx, 'fetch_ecb_rates', fetch)
    payload = {'requestId': key(1), 'start': START, 'end': selected_end}
    first = client.post(URL+'/rates/refresh', json=payload, headers=headers)
    assert first.status_code == 200, first.json
    assert calls == [('2026-08-25', observed_end)]
    view = report(client, end=selected_end)
    assert view['end'] == view['series'][-1]['date'] == selected_end
    closing = view['accounts'][0]['closing']
    assert closing['date'] == selected_end and closing['valuation']['asOf'] == END
    assert closing['fx']['rateDate'] == END
    assert all(o['date'] <= observed_end for o in closing['fx']['observations'])
    # A clock rollback must not prevent historical success recovery or modify
    # the original payload identity, even if a new request would now be future.
    clock[0] = datetime(2026, 9, 17, tzinfo=timezone.utc)
    replay = client.post(URL+'/rates/refresh', json=payload, headers=headers)
    assert replay.json == {**first.json, 'replayed': True}
    assert operation(client, 1)['receipt'] == replay.json and len(calls) == 1
    denied(client.post(URL+'/rates/refresh', json={**payload, 'requestId': key(2)}, headers=headers), 400)
    assert len(calls) == 1 and not operation(client, 2)['found']


@pytest.mark.parametrize('instant,future_end', [
    ('2026-09-18T15:59:59+00:00', '2026-09-19'),
    ('2026-09-18T16:00:00+00:00', '2026-09-20'),
    ('2026-09-19T00:00:00+00:00', '2026-09-20'),
])
def test_refresh_rejects_dates_after_shanghai_today_without_network(app, monkeypatch, instant, future_end):
    client, headers = member(app)
    freeze_utc(monkeypatch, instant)
    def no_fetch(*_):
        raise AssertionError('Future dates must be rejected before network access')
    monkeypatch.setattr(fx, 'fetch_ecb_rates', no_fetch)
    before = snapshot(app)
    response = client.post(URL+'/rates/refresh', json={'requestId':key(1),'start':START,'end':future_end}, headers=headers)
    denied(response, 400)
    assert response.json['code'] == 'invalid_request' and '北京时间今天' in response.json['error']
    assert snapshot(app) == before and not operation(client, 1)['found']


def test_refresh_public_date_parameter_error_is_400_not_network_failure(app, monkeypatch):
    client, headers = member(app)
    freeze_utc(monkeypatch, '2026-09-19T00:00:00+00:00')
    def invalid_range(*_):
        raise fx.FxError('Synthetic date range rejection', 'fx_invalid_range')
    monkeypatch.setattr(fx, 'fetch_ecb_rates', invalid_range)
    before = snapshot(app)
    response = client.post(URL+'/rates/refresh', json={'requestId':key(1),'start':START,'end':END}, headers=headers)
    denied(response, 400)
    assert response.json['code'] == 'invalid_request' and '日期' in response.json['error']
    assert snapshot(app) == before and not operation(client, 1)['found']
