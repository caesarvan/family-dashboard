"""Dated synthetic reports only; real Flask/session/SQLite and no network."""
from copy import deepcopy
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

from test_app import app, member
from test_finance_source_bridge import synthetic_candidate, normalize_candidate, source_files, load_prepare
from test_data_portability import unpack
from finance_baseline import import_baseline
from spending_observations import MODE, VERSION, REPORT_PATHS, normalize_spending_candidate

BASE='/api/finance-baseline/imports/'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_a,**_k):
        raise AssertionError('No external financial calls are allowed')
    monkeypatch.setattr(socket.socket,'connect',denied)


@contextmanager
def database(app):
    with closing(sqlite3.connect(Path(app.config['DATA_DIR'])/'household.sqlite3',timeout=20)) as con:
        with con:
            yield con


def observation(end='2026-09-15',net=1100):
    start=(date.fromisoformat(end)-timedelta(days=365)).isoformat()
    generated=end+'T08:00:00+08:00'
    q={'knownGapsCount':0,'unreadableStatementsCount':2,'channelOnlyAdded':True,'orderOnlyAdded':True}
    return {'schemaVersion':1,'kind':MODE,'converterVersion':VERSION,
            'sourceManifest':{'version':1,'files':[{'path':p,'sha256':'a'*64,'bytes':123} for p in sorted(REPORT_PATHS)],
                              'run':{'sha256':'b'*64,'generatedAt':generated,'status':'success','exitCode':0,'loginActionRequired':False},
                              'coverage':{'requestedStart':start,'requestedEnd':end,**q}},
            'spending':{'generatedAt':generated,'requestedStart':start,'requestedEnd':end,
                        'monthly':[{'period':end[:7],'currency':'CNY','grossSpendCents':net+200,'refundCents':200,'netSpendCents':net,'transactionCount':3}],
                        'quality':q}}


def seed(app,owner='member1',unknown=False):
    _,private,shared,_=normalize_candidate(synthetic_candidate(),'member1')
    private['owner']=shared['owner']=owner
    # Standard source's previous month remains in every fresh report in this test fixture.
    private['spending']=observation('2026-09-14',1000)['spending']
    if unknown:
        private['spending']={'monthly':[{'period':'2026-09','currency':'CNY','netSpendCents':1000,'transactionCount':3}],'note':'SYNTHETIC_LEGACY'}
    with database(app) as con:
        import_baseline(con,private,shared)
    return private


def protected(app):
    tables=['finance_baselines','private_finance','hub_transactions','hub_reconciliations','hub_investments','entities','hub_budgets','hub_shopping_settlements']
    with database(app) as con:
        values={t:con.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}
        values['finance']=con.execute("SELECT * FROM settings WHERE id='finance'").fetchall()
        return values


def preview(c,h,x=None,ack=False,expected=None):
    s=c.get(BASE+'status?mode='+MODE)
    assert s.status_code==200,s.json
    return c.post(BASE+'preview',headers=h,json={'mode':MODE,'candidate':x or observation(),
                  **(s.json['expected'] if expected is None else expected),'acknowledgeUnknownPreviousCoverage':ack})


def confirm(c,h,p,x=None):
    assert p.status_code==200,p.json
    return c.post(BASE+'confirm',headers=h,json={'mode':MODE,'candidate':x or observation(),'previewToken':p.json['previewToken']})


def test_roundtrip_preserves_baseline_entire_row_and_all_finance(app):
    seed(app);c,h=member(app);before=protected(app)
    p=preview(c,h);assert p.status_code==200,p.json
    assert protected(app)==before
    with database(app) as con:assert con.execute('SELECT count(*) FROM finance_spending_receipts').fetchone()[0]==0
    done=confirm(c,h,p);assert done.status_code==200,done.json
    assert done.json['revision']==1 and done.json['assetBaselineUnchanged']
    assert protected(app)==before
    view=c.get('/api/finance-baseline/private').json
    assert view['spending']['monthly'][0]['netSpendCents']==1100
    assert view['spending']['generatedAt']=='2026-09-15T08:00:00+08:00'
    assert view['balanceAsOfEnd']=='2026-08-31' and view['revision']==1
    assert 'spendingObservation' not in json.dumps(c.get('/api/state').json)


def test_replay_and_same_candidate_repreview_do_not_mutate_observation(app):
    seed(app);c,h=member(app);p=preview(c,h);first=confirm(c,h,p)
    assert first.status_code==200
    with database(app) as con:before=con.execute('SELECT * FROM finance_spending_observations').fetchall()
    same=confirm(c,h,p);assert same.json['replayed'] and same.json['receiptId']==first.json['receiptId']
    second=confirm(c,h,preview(c,h));assert second.json['status']=='unchanged' and second.json['revision']==1
    with database(app) as con:assert con.execute('SELECT * FROM finance_spending_observations').fetchall()==before
    newer=observation('2026-09-16',1200);assert confirm(c,h,preview(c,h,newer),newer).status_code==200
    assert confirm(c,h,p).json['revision']==1
    assert c.get('/api/finance-baseline/private').json['spending']['generatedAt'].startswith('2026-09-16')


@pytest.mark.parametrize('change',['baseline','observation'])
def test_two_lane_cas_rejects_concurrent_change(app,change):
    seed(app);c,h=member(app);p=preview(c,h);before=protected(app)
    if change=='baseline':
        with database(app) as con:con.execute('UPDATE finance_baselines SET revision=revision+1')
    else:
        other=observation(net=1200);assert confirm(c,h,preview(c,h,other),other).status_code==200
    assert confirm(c,h,p).status_code==409
    if change=='observation':assert protected(app)==before


def test_concurrent_confirm_one_transaction_wins(app):
    seed(app);c,h=member(app);x,y=observation(net=1100),observation(net=1200)
    p,q=preview(c,h,x),preview(c,h,y)
    cookie=c.get_cookie(app.config['SESSION_COOKIE_NAME']).value
    def apply(pair):
        target=app.test_client();target.set_cookie(app.config['SESSION_COOKIE_NAME'],cookie)
        return confirm(target,h,*pair).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(apply,[(p,x),(q,y)]))
    assert sorted(codes)==[200,409]


def test_rolling_window_is_allowed_and_removed_months_explicit(app):
    seed(app);c,h=member(app)
    x=observation('2026-09-30');x['spending']['monthly'].insert(0,{'period':'2025-09','currency':'USD','grossSpendCents':10,'refundCents':0,'netSpendCents':10,'transactionCount':1})
    assert confirm(c,h,preview(c,h,x),x).status_code==200
    y=observation('2026-10-01');y['spending']['monthly'].append(deepcopy(x['spending']['monthly'][1]))
    p=preview(c,h,y);assert p.status_code==200,p.json
    assert p.json['changes']['removedMonths']==[{'period':'2025-09','currency':'USD'}]
    assert confirm(c,h,p,y).status_code==200


def test_missing_month_inside_window_rejected(app):
    seed(app);c,h=member(app);x=observation();x['spending']['monthly'].append({'period':'2026-08','currency':'USD','grossSpendCents':10,'refundCents':0,'netSpendCents':10,'transactionCount':1})
    assert confirm(c,h,preview(c,h,x),x).status_code==200
    assert preview(c,h,observation('2026-09-16')).status_code==409


def test_partial_first_month_exit_via_real_cli_then_api_has_no_invented_zero(app,tmp_path):
    seed(app);c,h=member(app);before=protected(app)
    prepared=[]
    for offset,end in enumerate(['2026-09-15','2026-09-16']):
        folder=tmp_path/str(offset);folder.mkdir();root,_,config_path,config,_=source_files(folder)
        config.pop('sources');run=folder/('run-'+end+'.json');config['runFile']=str(run)
        report=root/'08_Budgets/all-email-spend-report-12m.json';value=json.loads(report.read_text(encoding='utf-8'))
        value['quality']['generated_at']=end+'T08:00:00+08:00'
        value['coverage'].update(requested_start=(date.fromisoformat(end)-timedelta(days=365)).isoformat(),requested_end=end)
        value['monthly'][0]['period']='2026-09'
        if offset==0:value['monthly'].append({'period':'2025-09','currency':'USD','gross_spend':'1.00','refunds':'0.00','net_spend':'1.00','transaction_count':1})
        report.write_text(json.dumps(value),encoding='utf-8')
        run.write_text(json.dumps({'status':'success','exit_code':0,'login_action_required':False,'generated_at':value['quality']['generated_at'],
                       'files':[{'path':str(root/p),'bytes':(root/p).stat().st_size,'modified_at':datetime.fromtimestamp((root/p).stat().st_mtime,timezone.utc).isoformat()} for p in sorted(REPORT_PATHS)]}),encoding='utf-8')
        config_path.write_text(json.dumps(config),encoding='utf-8');output=folder/'candidate.json'
        module=load_prepare();module.prepare(config_path,output,MODE);candidate=json.loads(output.read_bytes());prepared.append(candidate)
        p=preview(c,h,candidate);assert p.status_code==200,p.json
        if offset:
            assert p.json['changes']['removedMonths']==[{'period':'2025-09','currency':'USD'}]
            assert any('可能随窗口滚出' in w and '没有补零' in w for w in p.json['warnings'])
            assert not any(r['period']=='2025-09' for r in p.json['spending']['monthly'])
        assert confirm(c,h,p,candidate).status_code==200
    assert len(prepared[0]['spending']['monthly'])==2 and len(prepared[1]['spending']['monthly'])==1
    assert protected(app)==before


def test_first_full_month_disappearance_is_not_partial_boundary_exit(app):
    seed(app);c,h=member(app);old=observation('2026-09-30')
    old['spending']['monthly'].append({'period':'2025-10','currency':'USD','grossSpendCents':100,'refundCents':0,'netSpendCents':100,'transactionCount':1})
    assert confirm(c,h,preview(c,h,old),old).status_code==200
    new=observation('2026-10-01');new['spending']['monthly'].append(deepcopy(old['spending']['monthly'][0]))
    assert preview(c,h,new).status_code==409


@pytest.mark.parametrize('end',['2026-09-14','2026-09-13'])
def test_date_rollback_rejected(app,end):
    seed(app);c,h=member(app);assert confirm(c,h,preview(c,h)).status_code==200
    assert preview(c,h,observation(end)).status_code==409


def test_unknown_legacy_coverage_requires_explicit_acknowledgement(app):
    seed(app,unknown=True);c,h=member(app);before=protected(app)
    assert c.get(BASE+'status?mode='+MODE).json['requiresUnknownCoverageAcknowledgement']
    assert preview(c,h).status_code==409
    p=preview(c,h,ack=True);assert p.status_code==200
    assert any('没有补造' in w for w in p.json['warnings'])
    assert confirm(c,h,p).status_code==200
    assert protected(app)==before


@pytest.mark.parametrize('baseline_end,expected_origin',[('2026-09-16','baseline'),('2026-09-14',MODE)])
def test_full_baseline_later_never_adds_or_regresses_observations(app,baseline_end,expected_origin):
    seed(app);c,h=member(app);assert confirm(c,h,preview(c,h)).status_code==200
    with database(app) as con:
        row=con.execute('SELECT private_data FROM finance_baselines').fetchone();base=json.loads(row[0]);base['spending']=observation(baseline_end,1300)['spending']
        con.execute('UPDATE finance_baselines SET private_data=?,revision=revision+1',(json.dumps(base),))
    result=c.get('/api/finance-baseline/private').json
    assert result['spendingObservation']['origin']==expected_origin
    assert result['spending']['monthly'][0]['netSpendCents']==(1300 if expected_origin=='baseline' else 1100)


def test_missing_baseline_is_not_rebuilt(app):
    c,h=member(app);assert preview(c,h).status_code==409
    with database(app) as con:assert con.execute('SELECT count(*) FROM finance_baselines').fetchone()[0]==0


def test_receipt_replay_does_not_recreate_deleted_baseline_or_observation(app):
    seed(app);c,h=member(app);p=preview(c,h);first=confirm(c,h,p)
    with database(app) as con:
        con.execute('DELETE FROM finance_baselines');con.execute('DELETE FROM finance_spending_observations')
    replay=confirm(c,h,p)
    assert replay.status_code==200 and replay.json['receiptId']==first.json['receiptId'] and replay.json['replayed']
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM finance_baselines').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM finance_spending_observations').fetchone()[0]==0


def test_candidate_and_manifest_order_do_not_change_digest():
    x=observation();first=normalize_spending_candidate(x)
    x['sourceManifest']['files'].reverse()
    assert normalize_spending_candidate(x)==first


@pytest.mark.parametrize('identity',['member2','logout','relogin','csrf','household'])
def test_session_and_owner_bound_receipts(app,identity):
    seed(app);seed(app,'member2');c,h=member(app);p=preview(c,h)
    if identity=='member2':target,headers=member(app,2)
    elif identity=='csrf':target,headers=c,{'X-CSRF-Token':'invalid'}
    elif identity=='household':
        app.config['HOUSEHOLD_INFO']={**app.config.get('HOUSEHOLD_INFO',{}),'id':'synthetic-other'};target,headers=c,h
    else:
        assert c.post('/api/logout',headers=h,json={}).status_code==200
        if identity=='relogin':
            assert c.post('/api/login',json={'username':'member1','password':'testing-password-one'}).status_code==200
            h={'X-CSRF-Token':c.get('/api/me').json['csrf']}
        target,headers=c,h
    assert confirm(target,headers,p).status_code in (401,403)
    with database(app) as con:assert con.execute('SELECT count(*) FROM finance_spending_observations').fetchone()[0]==0


def test_tv_and_anonymous_cannot_read_or_export_and_member_zip_is_private(app):
    seed(app);seed(app,'member2');c,h=member(app);p=preview(c,h);assert confirm(c,h,p).status_code==200
    other,oh=member(app,2);own,entries=unpack(c.post('/api/portability/export',json={'includeShared':True},headers=h))
    exported=own['personal']['spendingObservations']
    assert exported['current']['revision']==1 and len(exported['receipts'])==1
    assert p.json['previewToken'].encode() not in b''.join(entries.values())
    assert 'spendingObservations' not in json.dumps(own['shared'])
    other_zip,_=unpack(other.post('/api/portability/export',json={},headers=oh))
    assert other_zip['personal']['spendingObservations']=={'current':None,'receipts':[]}
    tv=app.test_client();pair=tv.post('/api/pair/start',json={}).json
    assert c.post('/api/pair/approve',json={'code':pair['code'],'name':'SYNTHETIC TV'},headers=h).status_code==200
    assert tv.post('/api/pair/poll',json={'secret':pair['secret']}).json['approved']
    assert tv.get(BASE+'status?mode='+MODE).status_code==403
    assert tv.get('/api/finance-baseline/private').status_code==403
    assert tv.post('/api/portability/export',json={},headers=h).status_code==403
    assert app.test_client().get(BASE+'status?mode='+MODE).status_code==401


@pytest.mark.parametrize('mutation',['bool_version','file_missing','file_duplicate','file_escape','file_bytes','bad_hash','run_failed','run_login','run_bool_exit','run_mismatch','window_short','window_long','month_duplicate','month_outside','bad_currency','float_amount','negative_gross','bad_net','subcent','bool_count','extra_private','quality_missing'])
def test_bad_source_has_no_preview_token_and_no_financial_write(app,mutation):
    seed(app);c,h=member(app);x=observation();m=x['sourceManifest'];s=x['spending'];r=s['monthly'][0]
    if mutation=='bool_version':x['schemaVersion']=True
    elif mutation=='file_missing':m['files'].pop()
    elif mutation=='file_duplicate':m['files'][0]=deepcopy(m['files'][1])
    elif mutation=='file_escape':m['files'][0]['path']='../private.json'
    elif mutation=='file_bytes':m['files'][0]['bytes']=True
    elif mutation=='bad_hash':m['files'][0]['sha256']='bad'
    elif mutation=='run_failed':m['run']['status']='failed'
    elif mutation=='run_login':m['run']['loginActionRequired']=True
    elif mutation=='run_bool_exit':m['run']['exitCode']=False
    elif mutation=='run_mismatch':m['run']['generatedAt']='2026-09-15T09:00:00+08:00'
    elif mutation in ('window_short','window_long'):s['requestedStart']=m['coverage']['requestedStart']='2025-09-'+('16' if mutation=='window_short' else '14')
    elif mutation=='month_duplicate':s['monthly'].append(deepcopy(r))
    elif mutation=='month_outside':r['period']='2024-01'
    elif mutation=='bad_currency':r['currency']='usd'
    elif mutation=='float_amount':r['netSpendCents']=1100.0
    elif mutation=='negative_gross':r['grossSpendCents']=-10
    elif mutation=='bad_net':r['netSpendCents']=10
    elif mutation=='subcent':r['netSpendCents']='0.1'
    elif mutation=='bool_count':r['transactionCount']=True
    elif mutation=='extra_private':x['assets']=[{'label':'SYNTHETIC_PRIVATE'}]
    elif mutation=='quality_missing':s['quality'].pop('unreadableStatementsCount')
    before=protected(app);result=preview(c,h,x)
    assert result.status_code==400,result.json
    assert 'previewToken' not in result.json and protected(app)==before


def test_reports_only_cli_needs_no_asset_maps_and_produces_stable_private_candidate(tmp_path):
    root,run,config_path,config,_=source_files(tmp_path)
    config.pop('sources');config_path.write_text(json.dumps(config),encoding='utf-8')
    # Bad loan/holdings content does not enter this explicit reports-only mode.
    (root/'03_Loans/loans.csv').write_text('SYNTHETIC_INVALID_NO_BALANCE_DATE',encoding='utf-8')
    output=tmp_path/'private-output/observation.json';module=load_prepare()
    first=module.prepare(config_path,output,MODE);before=output.read_bytes()
    assert module.prepare(config_path,output,MODE)==first and output.read_bytes()==before
    normalized,_,_=normalize_spending_candidate(json.loads(before))
    assert {r['path'] for r in normalized['sourceManifest']['files']}==REPORT_PATHS
    result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve().parents[1]/'deploy/prepare-finance-source.py'),'--mode',MODE,'--config',str(config_path),'--output',str(output)],capture_output=True)
    assert result.returncode==0,result.stderr
    assert str(root).encode() not in result.stdout+result.stderr and b'SYNTHETIC' not in result.stdout+result.stderr
    assert not list(tmp_path.rglob('*.sqlite3'))


@pytest.mark.parametrize('mutation',['missing_report','changed_report','failed_run','missing_mtime','short_window','extra_sources','output_source','output_config'])
def test_cli_rejects_incomplete_or_unstable_sources_and_preserves_output(tmp_path,mutation):
    root,run,config_path,config,write_run=source_files(tmp_path);config.pop('sources');config_path.write_text(json.dumps(config),encoding='utf-8')
    output=tmp_path/'observation.json';module=load_prepare();module.prepare(config_path,output,MODE);before=output.read_bytes()
    report=root/'08_Budgets/all-email-spend-report-12m.json'
    if mutation=='missing_report':report.unlink()
    elif mutation=='changed_report':report.write_text(report.read_text()+' ',encoding='utf-8')
    elif mutation=='failed_run':r=json.loads(run.read_text());r['status']='failed';run.write_text(json.dumps(r))
    elif mutation=='missing_mtime':r=json.loads(run.read_text());r['files'][0].pop('modified_at');run.write_text(json.dumps(r))
    elif mutation=='short_window':r=json.loads(report.read_text());r['coverage']['requested_start']='2025-09-15';report.write_text(json.dumps(r));write_run()
    elif mutation=='extra_sources':config['sources']=[];config_path.write_text(json.dumps(config))
    target={'output_source':report,'output_config':config_path}.get(mutation,output)
    protected_bytes=target.read_bytes() if target.exists() else None
    with pytest.raises((ValueError,OSError)):
        module.prepare(config_path,target,MODE)
    assert output.read_bytes()==before
    if target!=output:assert target.read_bytes()==protected_bytes
