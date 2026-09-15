"""Temporary Flask/SQLite/Edge reports-only workflow. No real sources or external network."""
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from app import create_app
from test_spending_observations import observation, seed, protected, database
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self,*_args,**_kwargs):
        pass


def source_hashes():
    paths=list(ROOT.glob('*.py'))+list((ROOT/'static').rglob('*'))+list((ROOT/'deploy').rglob('*'))
    paths += [ROOT/x for x in ['Dockerfile','compose.yaml','requirements.txt','pytest.ini','tests/test_spending_observations.py','tests/browser_spending_observations_check.py']]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file() and '__pycache__' not in p.parts}


def main():
    output=ROOT/'test-results';output.mkdir(exist_ok=True)
    report=output/'spending-observations-browser-verification.json'
    before=source_hashes();checks=[];page_errors=[];external=[];provider=[];screenshots=[];failure=None;failure_traceback=None
    original_connect=socket.socket.connect
    def local_only(sock,address):
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1','localhost'):
            provider.append('blocked_non_loopback');raise AssertionError('No external network')
        return original_connect(sock,address)
    socket.socket.connect=local_only
    try:
        with tempfile.TemporaryDirectory(prefix='spending-observation-browser-') as folder:
            app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-spending-browser-secret','DATA_DIR':folder,'SESSION_COOKIE_SECURE':False,
                            'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'})
            seed(app);seed(app,'member2')
            untouched=protected(app)
            server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet)
            server.daemon_threads=False
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            candidate=Path(folder)/'synthetic-spending-observation.json';candidate.write_text(json.dumps(observation()),encoding='utf-8')
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                    context=browser.new_context(viewport={'width':390,'height':844})
                    def network(route):
                        if not route.request.url.startswith(origin+'/'):
                            external.append('blocked_external');route.abort()
                        else:route.continue_()
                    context.route('**/*',network)
                    def login(number=1):
                        assert context.request.post(origin+'/api/login',data={'username':'member'+str(number),'password':'testing-password-'+('one' if number==1 else 'two')}).status==200
                        return {'X-CSRF-Token':context.request.get(origin+'/api/me').json()['csrf']}
                    headers=login()
                    page=context.new_page();page.on('pageerror',lambda e:page_errors.append(str(e)))
                    writes=[]
                    page.on('request',lambda r:writes.append((r.url.rsplit('/',1)[-1],r.post_data_json)) if r.method=='POST' and '/finance-baseline/imports/' in r.url else None)
                    page.goto(origin);expect(page.locator('.ps-welcome')).to_be_visible()
                    def open_mode(mode='spending_observation'):
                        page.evaluate('(mode)=>FinanceSourceUI.open({mode})',mode)
                        expect(page.locator('#finance-source-form')).to_be_visible()
                    def file_preview():
                        page.locator('[name=candidateFile]').set_input_files(candidate)
                        page.locator('#finance-source-form [type=submit]').click()
                        expect(page.locator('#finance-source-ack')).to_be_visible()
                    def wait_for_request(held,label):
                        deadline=time.monotonic()+15
                        while not held and time.monotonic()<deadline:
                            page.wait_for_timeout(25)
                        assert held, 'Timed out waiting for '+label
                    open_mode('baseline')
                    page.locator('[name=sourceMode]').select_option('spending_observation')
                    expect(page.locator('#finance-source-form')).to_contain_text('仅更新消费观察')
                    assert writes==[];checks.append('One existing entry exposes explicit reports-only mode without uploading')
                    page.locator('[name=candidateFile]').set_input_files(candidate)
                    assert writes==[];checks.append('Selecting a file does not POST')
                    page.locator('#finance-source-form [type=submit]').click()
                    expect(page.locator('#finance-source-ack')).to_be_visible()
                    expect(page.locator('[data-fs=confirm]')).to_be_disabled()
                    expect(page.locator('.finance-source-dates')).to_contain_text('2026-09-15T08:00:00+08:00')
                    expect(page.locator('.finance-source-dates')).to_contain_text('2026-08-31')
                    assert protected(app)==untouched
                    with database(app) as con:assert con.execute('SELECT count(*) FROM finance_spending_observations').fetchone()[0]==0
                    con.close()
                    checks.append('Preview distinguishes report and asset dates, requires acknowledgement and writes no financial data')
                    for theme in ['forest','light','ocean']:
                        page.evaluate('(t)=>document.documentElement.dataset.theme=t',theme)
                        for width in [360,768,1440]:
                            page.set_viewport_size({'width':width,'height':900})
                            assert page.evaluate('document.querySelector("#dialog").scrollWidth<=document.querySelector("#dialog").clientWidth+1')
                            target=output/f'spending-observation-{theme}-{width}.png';page.screenshot(path=str(target),full_page=True);screenshots.append(str(target))
                            checks.append(f'{theme} theme {width}px preview has no horizontal overflow')
                    page.locator('#finance-source-ack').check()
                    page.route('**/api/finance-baseline/imports/confirm',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":"SYNTHETIC_PRIVATE_RAW_FAILURE"}'))
                    page.locator('[data-fs=confirm]').click()
                    expect(page.locator('#finance-source-error')).to_contain_text('暂时不可用')
                    expect(page.locator('#finance-source-error')).not_to_contain_text('SYNTHETIC_PRIVATE')
                    expect(page.locator('#finance-source-ack')).to_be_checked()
                    page.unroute('**/api/finance-baseline/imports/confirm')
                    page.locator('[data-fs=confirm]').click();expect(page.locator('#finance-source-success')).to_contain_text('消费观察已更新')
                    tokens=[value['previewToken'] for kind,value in writes if kind=='confirm']
                    assert len(tokens)==2 and tokens[0]==tokens[1]
                    assert protected(app)==untouched
                    checks.append('503 displays fixed text, preserves acknowledgement and retries original token')
                    page.locator('[data-fs=private]').click()
                    expect(page.locator('[data-spending-dates]')).to_contain_text('2026-09-15T08:00:00+08:00')
                    expect(page.locator('#finance-private-root')).to_contain_text('2026-08-31')
                    assert protected(app)==untouched;checks.append('Confirmed report reads through the private baseline view while the full baseline row remains identical')
                    open_mode();file_preview();page.locator('#finance-source-ack').check();page.locator('[data-fs=confirm]').click()
                    expect(page.locator('#finance-source-success')).to_contain_text('没有重复更新')
                    checks.append('Same source preview and confirmation are idempotent')
                    # A different browser update races this preview; UI must keep file for re-preview.
                    candidate.write_text(json.dumps(observation('2026-09-16',1200)),encoding='utf-8')
                    open_mode();file_preview()
                    other=observation('2026-09-16',1300)
                    status=context.request.get(origin+'/api/finance-baseline/imports/status?mode=spending_observation').json()
                    pre=context.request.post(origin+'/api/finance-baseline/imports/preview',headers=headers,data={'mode':'spending_observation','candidate':other,**status['expected'],'acknowledgeUnknownPreviousCoverage':False})
                    assert pre.status==200,pre.text()
                    assert context.request.post(origin+'/api/finance-baseline/imports/confirm',headers=headers,data={'mode':'spending_observation','candidate':other,'previewToken':pre.json()['previewToken']}).status==200
                    page.locator('#finance-source-ack').check();page.locator('[data-fs=confirm]').click()
                    expect(page.locator('#finance-source-error')).to_contain_text('文件仍保留')
                    expect(page.locator('[data-fs=confirm]')).to_be_disabled()
                    page.locator('[data-fs=preview]').click();expect(page.locator('#finance-source-ack')).to_be_enabled()
                    expect(page.locator('#finance-source-ack')).not_to_be_checked()
                    checks.append('Real concurrent CAS conflict keeps the candidate and requires a new preview and acknowledgement')
                    open_mode();pending=[]
                    page.route('**/api/finance-baseline/imports/preview',lambda route:pending.append(route))
                    page.locator('[name=candidateFile]').set_input_files(candidate)
                    page.locator('#finance-source-form [type=submit]').click()
                    wait_for_request(pending,'slow preview range-lock request')
                    expect(page.locator('[name=sourceMode]')).to_be_disabled()
                    expect(page.locator('[name=candidateFile]')).to_be_disabled()
                    expect(page.locator('[name=sourceMode]')).to_have_value('spending_observation')
                    pending[0].fulfill(status=503,content_type='application/json',body='{"error":"SYNTHETIC_PRIVATE_RAW_FAILURE"}')
                    expect(page.locator('#finance-source-error')).to_contain_text('暂时不可用')
                    expect(page.locator('[name=sourceMode]')).to_be_enabled()
                    expect(page.locator('[name=candidateFile]')).to_be_enabled()
                    expect(page.locator('[name=sourceMode]')).to_have_value('spending_observation')
                    page.unroute('**/api/finance-baseline/imports/preview')
                    checks.append('Pending preview locks source mode and file; failure restores only the original form without changing its range')
                    # Delayed successful response cannot replace a later form or dialog.
                    for target in ['new_form','closed','other_dialog','file_input']:
                        open_mode();held=[]
                        def hold(route):held.append((route,route.fetch()))
                        page.route('**/api/finance-baseline/imports/preview',hold)
                        page.locator('[name=candidateFile]').set_input_files(candidate)
                        page.locator('#finance-source-form [type=submit]').click()
                        wait_for_request(held,'delayed preview '+target)
                        if target=='new_form':open_mode('baseline')
                        elif target=='closed':page.evaluate('document.getElementById("dialog").close()')
                        elif target=='other_dialog':page.evaluate('openModal("SYNTHETIC_OTHER","<p id=synthetic-other>OTHER</p>")')
                        else:
                            alternate=Path(folder)/'changed-selection.json';alternate.write_text(candidate.read_text(encoding='utf-8'),encoding='utf-8')
                            page.locator('[name=candidateFile]').set_input_files(alternate)
                        held[0][0].fulfill(response=held[0][1]);page.unroute('**/api/finance-baseline/imports/preview');page.wait_for_timeout(150)
                        assert page.locator('#finance-source-ack').count()==0,target
                        if target=='other_dialog':expect(page.locator('#synthetic-other')).to_be_visible()
                        if target in ['new_form','file_input']:expect(page.locator('#finance-source-form')).to_be_visible()
                        checks.append('Delayed preview preserves '+target)
                    # Cookie changes while global UI still shows old actor; no private result may render.
                    open_mode();held=[];page.route('**/api/finance-baseline/imports/preview',hold)
                    page.locator('[name=candidateFile]').set_input_files(candidate);page.locator('#finance-source-form [type=submit]').click()
                    wait_for_request(held,'cookie-only member-switch preview')
                    login(2);held[0][0].fulfill(response=held[0][1]);page.unroute('**/api/finance-baseline/imports/preview')
                    expect(page.locator('#finance-source-root')).to_contain_text('登录或家庭已变化')
                    assert page.locator('#finance-source-ack').count()==0;checks.append('Cookie-only member switch suppresses old private preview before rendering')
                    page.reload();expect(page.locator('.ps-welcome')).to_be_visible();open_mode()
                    assert context.request.get(origin+'/api/finance-baseline/imports/status?mode=spending_observation').json()['current'] is None
                    checks.append('Second member cannot read the first member observation')
                    page.route('**/api/me',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":"SYNTHETIC_PRIVATE"}'))
                    open_request=page.evaluate('FinanceSourceUI.open({mode:"spending_observation"})')
                    expect(page.locator('#finance-source-root')).to_contain_text('暂时无法核对登录状态')
                    assert page.locator('#finance-source-form').count()==0
                    page.unroute('**/api/me');checks.append('Missing /me refuses private reads and displays no cached report')
                    restricted=[]
                    page.on('request',lambda r:restricted.append(r.url) if '/api/finance-baseline/' in r.url else None)
                    page.goto(origin+'/demo');expect(page.locator('.board')).to_be_visible()
                    page.evaluate('FinanceSourceUI.open()');page.wait_for_timeout(100)
                    assert not restricted and page.locator('#finance-source-root').count()==0
                    checks.append('Real demo route does not request private source APIs or render source controls')
                    tv=browser.new_context();tv.route('**/*',network)
                    pair=tv.request.post(origin+'/api/pair/start',data={}).json()
                    tv_headers={'X-CSRF-Token':context.request.get(origin+'/api/me').json()['csrf']}
                    assert context.request.post(origin+'/api/pair/approve',headers=tv_headers,data={'code':pair['code'],'name':'SYNTHETIC TV'}).status==200
                    assert tv.request.post(origin+'/api/pair/poll',data={'secret':pair['secret']}).json()['approved']
                    tvpage=tv.new_page();tvpage.on('pageerror',lambda e:page_errors.append(str(e)))
                    tvpage.on('request',lambda r:restricted.append(r.url) if '/api/finance-baseline/' in r.url else None)
                    tvpage.goto(origin+'/tv');expect(tvpage.locator('.board')).to_be_visible()
                    tvpage.evaluate('FinanceSourceUI.open()');tvpage.wait_for_timeout(100)
                    assert not restricted and tvpage.locator('#finance-source-root').count()==0
                    assert tv.request.get(origin+'/api/finance-baseline/imports/status?mode=spending_observation').status==403
                    checks.append('Actually paired TV makes no private source API request and its explicit management request is forbidden')
                    tv.close()
                    assert protected(app)==untouched;checks.append('All protected finance and baseline rows are byte-for-byte unchanged after browser workflow')
                    browser.close()
            finally:
                server.shutdown();worker.join(timeout=5);server.server_close()
                # Imported pytest fixtures release sqlite statement cycles at collection.
                gc.collect()
    except Exception as exc:
        failure=type(exc).__name__+': '+str(exc)
        failure_traceback=traceback.format_exc()
    finally:
        socket.socket.connect=original_connect
        after=source_hashes()
        result={'passed':failure is None and not page_errors and not external and not provider and before==after,'checks':checks,'failure':failure,'traceback':failure_traceback,
                'pageErrors':page_errors,'externalRequests':external,'providerCalls':provider,'sourceHashes':before,'sourceHashesAfter':after,'sourceUnchanged':before==after,
                'screenshots':screenshots,'productionWrites':0,'realFinanceInputsRead':0,'timestamp':datetime.now(timezone.utc).isoformat()}
        report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':result['passed'],'checks':len(checks),'failure':failure,'sourceUnchanged':before==after},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
