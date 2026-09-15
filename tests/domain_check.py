"""Validate domain TLS and browser flow; optional DNS override never bypasses TLS verification."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

parser=argparse.ArgumentParser()
parser.add_argument('--resolve',action='store_true')
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
out=root/'test-results'
out.mkdir(exist_ok=True)
origin='https://home.caesarcharles.world'
values=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
with sync_playwright() as p:
    flags=['--no-proxy-server']
    if args.resolve: flags.append('--host-resolver-rules=MAP home.caesarcharles.world 96.44.160.28')
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True,args=flags)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(origin,wait_until='networkidle',timeout=30000)
    assert page.locator('input[type=password]').count()==1
    assert page.evaluate("fetch('/healthz').then(r=>r.json()).then(x=>x.status)")=='ok'
    assert page.evaluate("fetch('/api/state').then(r=>r.status)")==401
    result={'host':'home.caesarcharles.world','dnsOverride':args.resolve,'tlsVerified':True,'loginPage':True,'unauthorizedDataBlocked':True}
    page.locator('input[type=password]').fill(values['MEMBER1_PASSWORD'])
    with page.expect_response(lambda r:r.url==origin+'/api/login') as login_response:
        page.locator('button[type=submit]').click()
    if login_response.value.status==200:
        page.wait_for_selector('.board',timeout=20000)
        result['existingAccountLogin']=True
        page.screenshot(path=str(out/'domain-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(out/'domain-mobile.png'),full_page=True)
        result['mobileNoHorizontalOverflow']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    else:
        result['existingAccountLogin']={'status':login_response.value.status,'message':'Initial credential not accepted; no passwords changed.'}
    tv=browser.new_page(viewport={'width':1920,'height':1080})
    tv.goto(origin+'/tv',wait_until='networkidle')
    tv.wait_for_selector('.pair-code')
    result['tvPairingPage']=True
    demo=browser.new_page(viewport={'width':1920,'height':1080})
    demo.goto(origin+'/demo?tv=1',wait_until='networkidle')
    demo.wait_for_selector('.board')
    demo.screenshot(path=str(out/'domain-demo.png'),full_page=True)
    assert not errors,errors
    result['javascriptErrors']=errors
    (out/'domain-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    browser.close()
