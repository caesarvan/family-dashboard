"""Read-only public checks of the deployed release; never tries stored passwords."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
out = root / 'test-results'
out.mkdir(exist_ok=True)
origin = 'https://home.caesarcharles.world'
with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True,
        args=['--no-proxy-server', '--host-resolver-rules=MAP home.caesarcharles.world 96.44.160.28'])
    page = browser.new_page(viewport={'width':1440,'height':1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(origin, wait_until='networkidle')
    assert page.locator('input[type=password]').count() == 1
    statuses = page.evaluate("fetch('/api/auth/providers').then(r=>r.json())")
    assert statuses['origin'] == origin
    assert [p['id'] for p in statuses['providers']] == ['microsoft','google']
    assert all(not p['configured'] for p in statuses['providers'])
    assert page.evaluate("fetch('/api/state').then(r=>r.status)") == 401
    assert page.evaluate("fetch('/api/accounts').then(r=>r.status)") == 401
    page.screenshot(path=str(out/'accounts-live-login.png'), full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(out/'accounts-live-phone.png'), full_page=True)
    page.goto(origin+'/static/account-setup.html', wait_until='networkidle')
    assert page.locator('#microsoft').count() == 1 and page.locator('#google').count() == 1
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(out/'accounts-live-guide.png'), full_page=True)
    # A forged callback is rejected without attempting a provider token exchange.
    page.goto(origin+'/auth/google/callback?state=public-log-check-marker&code=public-log-check-marker', wait_until='networkidle')
    assert page.locator('input[type=password]').count() == 1
    assert 'code=' not in page.url and 'state=' not in page.url
    page.set_viewport_size({'width':1920,'height':1080})
    page.goto(origin+'/demo?tv=1', wait_until='networkidle')
    page.wait_for_selector('.board')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth&&document.documentElement.scrollHeight<=innerHeight')
    page.screenshot(path=str(out/'accounts-live-tv.png'), full_page=True)
    assert not errors, errors
    result = {'host':origin, 'dnsOverride':True, 'tlsVerification':True, 'providerConfig':statuses,
              'anonymousDataBlocked':True, 'phoneLayout':True, 'tvLayout':True, 'guideAvailable':True,
              'forgedCallbackRejected':True, 'javascriptErrors':errors,
              'realProviderAuthorization':'awaiting application registration and member consent',
              'existingMemberLogin':'not attempted; stored initial password is outdated'}
    (out/'accounts-live-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    browser.close()
