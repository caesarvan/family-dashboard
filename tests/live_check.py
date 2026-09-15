"""Explicit deployment smoke check; creates and removes its own task and TV device."""
import json
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
secrets = dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
out = root/'test-results'
out.mkdir(exist_ok=True)
base = 'https://96.44.160.28'
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True,args=['--no-proxy-server'])
    a=browser.new_context(viewport={'width':1440,'height':1000})
    b=browser.new_context()
    tv=browser.new_context(viewport={'width':1920,'height':1080})
    page=a.new_page()
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(base,wait_until='networkidle')
    page.locator('input[type=password]').fill(secrets['MEMBER1_PASSWORD'])
    page.locator('button[type=submit]').click()
    page.wait_for_selector('.board')
    assert a.request.get(base+'/healthz').json()['status']=='ok'
    assert b.request.get(base+'/api/state').status==401
    assert b.request.post(base+'/api/login',data={'username':'member2','password':secrets['MEMBER2_PASSWORD']}).ok
    ah={'X-CSRF-Token':a.request.get(base+'/api/me').json()['csrf'],'Origin':base}
    bh={'X-CSRF-Token':b.request.get(base+'/api/me').json()['csrf'],'Origin':base}
    created=a.request.post(base+'/api/items/tasks',data={'title':'部署验收临时任务','owner':'shared'},headers=ah).json()
    path=base+'/api/items/tasks/'+created['id']
    assert any(x['id']==created['id'] for x in b.request.get(base+'/api/state').json()['tasks'])
    assert b.request.patch(path,data={'revision':1,'done':True},headers=bh).ok
    subprocess.run(['ssh','-o','BatchMode=yes','racknerd','cd /opt/family-dashboard && docker compose restart app'],check=True,capture_output=True)
    # A bounded readiness wait after restart, never disabling TLS verification.
    import time
    for _ in range(15):
        r=a.request.get(base+'/healthz')
        if r.ok: break
        time.sleep(1)
    state=a.request.get(base+'/api/state').json()
    assert next(x for x in state['tasks'] if x['id']==created['id'])['done'] is True
    assert a.request.delete(path,data={'revision':2},headers=ah).ok
    tvpage=tv.new_page()
    tvpage.goto(base+'/tv')
    tvpage.wait_for_selector('.pair-code')
    code=tvpage.locator('.pair-code').inner_text().replace(' ','')
    assert a.request.post(base+'/api/pair/approve',data={'code':code,'name':'部署验收临时电视','focus':'member2'},headers=ah).ok
    tvpage.wait_for_selector('.board',timeout=20000)
    assert tv.request.get(base+'/api/me').json()['user']['role']=='tv'
    assert tv.request.get(base+'/api/private-finance').status==403
    assert tv.request.post(base+'/api/items/tasks',data={'title':'拒绝修改'},headers=ah).status==403
    device=next(x for x in a.request.get(base+'/api/devices').json() if x['name']=='部署验收临时电视')
    assert a.request.delete(base+'/api/devices/'+device['id'],data={},headers=ah).ok
    assert tv.request.get(base+'/api/state').status==401
    page.reload(wait_until='networkidle')
    page.screenshot(path=str(out/'production-empty.png'),full_page=True)
    demo=browser.new_page(viewport={'width':1920,'height':1080})
    demo.goto(base+'/demo?tv=1',wait_until='networkidle')
    demo.wait_for_selector('.board')
    demo.screenshot(path=str(out/'production-demo.png'),full_page=True)
    assert not errors, errors
    result={'httpsVerified':True,'browserLogin':True,'crossMemberEdit':True,'restartPersistence':True,'tvPairAndReadOnly':True,'tvRevocation':True,'temporaryDataRemoved':True,'pageErrors':errors}
    (out/'live-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    browser.close()
