"""Real Flask + browser feature integration on temporary synthetic data, no production writes."""
from datetime import datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app, TZ
from finance_baseline import import_baseline
from test_finance_baseline import payload
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    out = ROOT / 'test-results'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'isolated-browser-secret', 'DATA_DIR': temp,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        with sqlite3.connect(Path(temp) / 'household.sqlite3') as conn:
            data = payload.__wrapped__()
            # Similar digit lengths to real household baselines, entirely fictional amounts.
            for key, amount in [('assets', 87654321), ('liabilities', 321987654)]:
                total_key = 'recordedAssetCents' if key == 'assets' else 'recordedLiabilityCents'
                data['private'][key][0]['amountCents'] = amount
                data['private']['totals'][total_key] = data['shared'][total_key] = amount
            import_baseline(conn, **data)
        conn.close()
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                ctx = browser.new_context(viewport={'width': 390, 'height': 844})
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda err: errors.append(str(err)))
                origin = f'http://127.0.0.1:{server.server_port}'
                page.goto(origin)
                page.locator('[name=password]').fill('testing-password-one')
                page.locator('#login-form button[type=submit]').click()
                expect(page.locator('.wealth-strip')).to_be_visible()
                page.locator('[data-action=settings]').click()
                page.locator('[data-action=wealth-private]').click()
                expect(page.locator('#dialog')).to_contain_text('PRIVATE_ASSET_ACCOUNT')
                page.locator('[data-action=close]').click()
                token = ctx.request.get(origin+'/api/me').json()['csrf']
                headers = {'X-CSRF-Token': token}
                # Test actual browser compression, authenticated upload and entity save.
                page.locator('[aria-label="添加采购物品"]').click()
                page.locator('[name=title]').fill('参考采购 · 图片与预算')
                page.locator('[name=budget]').fill('128.50')
                picture = BytesIO(); Image.new('RGB', (2000, 1000), '#88aa99').save(picture, 'PNG')
                page.locator('input[type=file]').set_input_files({'name':'example.png','mimeType':'image/png','buffer':picture.getvalue()})
                expect(page.locator('.shopping-photo-chip img')).to_have_count(1)
                expect(page.locator('#dialog button[type=submit]')).to_be_enabled()
                page.locator('#dialog button[type=submit]').click()
                expect(page.locator('#dialog')).not_to_be_visible()
                state = ctx.request.get(origin+'/api/state').json()
                assert state['shopping'][0]['budget'] == 12850
                photo = state['shopping'][0]['photoIds'][0]
                assert ctx.request.get(origin+'/api/photos/'+photo).status == 200
                assert 'PRIVATE_' not in json.dumps(state)
                today = datetime.now(TZ).date()
                for i in range(-3, 7):
                    day = str(today+timedelta(days=i))
                    event = {'title':'本周项目讨论与安排', 'start':day+'T10:00:00+08:00', 'end':day+'T11:30:00+08:00', 'location':'办公室 · 会议室', 'owner':'member1'}
                    assert ctx.request.post(origin+'/api/items/events', data=event, headers=headers).status == 201
                for i in range(3):
                    assert ctx.request.post(origin+'/api/items/shopping', data={'title':['厨房纸','洗衣液','礼品咖啡豆'][i], 'quantity':'1 件', 'budget':8500+i*100, 'photoIds':[photo]}, headers=headers).status == 201
                page.reload(); expect(page.locator('.cv-card')).to_be_visible()
                page.locator('[data-calendar-mode=week]').first.click()
                expect(page.locator('.cv-day')).to_have_count(7)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                page.screenshot(path=str(out/'features-phone.png'), full_page=True)
                # Owner API, partner API, TV API exercise the same projection as production.
                partner = browser.new_context()
                partner.request.post(origin+'/api/login', data={'username':'member2','password':'testing-password-two'})
                assert partner.request.get(origin+'/api/finance-baseline/private?owner=member1').json() is None
                assert 'PRIVATE_' not in partner.request.get(origin+'/api/state').text()
                assert partner.request.get(origin+'/api/photos/'+photo).status == 200
                tv = browser.new_context()
                pair = tv.request.post(origin+'/api/pair/start', data={}).json()
                assert ctx.request.post(origin+'/api/pair/approve', headers=headers, data={'code':pair['code'],'name':'测试电视','focus':'member1','calendarView':'week'}).status == 200
                tv.request.post(origin+'/api/pair/poll', data={'secret':pair['secret']})
                assert tv.request.get(origin+'/api/finance-baseline/private').status == 403
                assert tv.request.get(origin+'/api/photos/'+photo).status == 200
                screen = tv.new_page(); screen.on('pageerror', lambda err:errors.append(str(err)))
                devices = ctx.request.get(origin+'/api/devices').json()
                device = devices[0]
                records = []
                for mode in ['today','week','around']:
                    result=ctx.request.patch(origin+'/api/devices/'+device['id'], headers=headers, data={'calendarView':mode,'revision':device['revision']})
                    assert result.status == 200
                    device['revision'] += 1
                    for width,height in [(1280,720),(1920,1080),(3840,2160)]:
                        screen.set_viewport_size({'width':width,'height':height})
                        screen.goto(origin+'/tv'); expect(screen.locator('.wealth-strip')).to_be_visible()
                        check = screen.evaluate('''() => ({horizontal:document.documentElement.scrollWidth>innerWidth+1,cards:[...document.querySelectorAll('.board>.card')].map(el=>({name:el.className,bottom:el.getBoundingClientRect().bottom,height:el.clientHeight,scroll:el.scrollHeight})),private:document.body.innerText.includes('PRIVATE_')})''')
                        assert not check['horizontal'] and not check['private'], check
                        assert len(check['cards']) == 5
                        screen.screenshot(path=str(out/'features-tv-latest.png'))
                        assert all(c['bottom'] <= height and c['scroll'] <= c['height']+2 for c in check['cards']), check
                        records.append({'mode':mode,'width':width,'height':height,'layout':'pass'})
                        if width == 1920:screen.screenshot(path=str(out/f'features-tv-{mode}.png'))
                assert not errors, errors
                print(json.dumps({'realApi':'passed','privacy':'passed','photoUpload':'passed','layouts':records,'pageErrors':errors},ensure_ascii=False))
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__':
    main()
