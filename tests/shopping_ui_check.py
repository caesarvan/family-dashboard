"""Procurement UI browser checks with an in-memory API; never calls production."""
import base64
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jA7sAAAAASUVORK5CYII=')


def run():
    state = {
        'revision': 1,
        'people': [{'id': 'member1', 'name': '我'}, {'id': 'member2', 'name': '伴侣'}],
        'events': [], 'tasks': [], 'trips': [],
        'shopping': [
            {'id': 'a', 'title': '洗衣液', 'quantity': '1 瓶', 'owner': 'shared', 'done': False, 'budget': 5900, 'actual': None, 'photoIds': [], 'revision': 1},
            {'id': 'b', 'title': '厨房纸', 'quantity': '2 提', 'owner': 'shared', 'done': False, 'budget': None, 'actual': None, 'photoIds': [], 'revision': 1},
            {'id': 'c', 'title': '礼品咖啡豆', 'quantity': '1 袋', 'owner': 'shared', 'done': False, 'budget': 0, 'actual': None, 'photoIds': [], 'revision': 1},
            {'id': 'd', 'title': '已买日用品', 'quantity': '1 件', 'owner': 'shared', 'done': True, 'budget': 10000, 'actual': 8500, 'photoIds': [], 'revision': 1},
        ],
        'finance': {'wallet': 0, 'livingSpent': 0, 'livingBudget': 620000, 'travelSaved': 0, 'travelAnnualBudget': 10400000, 'longterm': 0, 'reserveTarget': 1000000, 'upcomingPayments': 0, 'contributionPercent': 50, 'confirmedAt': None, 'revision': 1},
        'sync': {}, 'integrations': {},
    }
    uploads = {}
    calls = []
    # Explicit wrappers keep this module test independent of integration edits.
    html = (ROOT / 'static/index.html').read_text(encoding='utf-8').replace('</head>', '<script src="/test-integration.js" defer></script></head>')
    integration = '''shoppingCard=ShoppingUI.renderCard;const originalEditForTest=editItem;editItem=(kind,...args)=>kind==='shopping'?ShoppingUI.openEditor(...args):originalEditForTest(kind,...args);const originalManageForTest=manage;manage=kind=>kind==='shopping'?ShoppingUI.openManager():originalManageForTest(kind);'''

    def route(request_route):
        req = request_route.request
        path = urlparse(req.url).path
        if path == '/':
            request_route.fulfill(body=html, content_type='text/html'); return
        if path == '/test-integration.js':
            request_route.fulfill(body=integration, content_type='text/javascript'); return
        if path.startswith('/static/'):
            file = (ROOT / path.lstrip('/')).resolve()
            assert file.is_relative_to(ROOT / 'static')
            request_route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or 'application/octet-stream'); return
        result = {}
        if path == '/api/me':
            result = {'user': {'id': 'member1', 'role': 'member'}, 'csrf': 'test-csrf'}
        elif path == '/api/state':
            result = state
        elif path == '/api/photos' and req.method == 'POST':
            payload = req.post_data_json
            assert payload['dataUrl'].startswith('data:image/jpeg;base64,')
            photo_id = 'photo-' + str(len(uploads) + 1)
            uploads[photo_id] = base64.b64decode(payload['dataUrl'].split(',', 1)[1])
            result = {'id': photo_id, 'url': '/api/photos/' + photo_id}
        elif path.startswith('/api/photos/'):
            request_route.fulfill(body=uploads[path.rsplit('/', 1)[-1]], content_type='image/jpeg'); return
        elif path.startswith('/api/items/shopping'):
            payload = req.post_data_json
            assert req.headers.get('x-csrf-token') == 'test-csrf'
            calls.append((req.method, payload))
            if req.method == 'POST':
                item = {**payload, 'id': 'new-item', 'revision': 1}
                state['shopping'].append(item)
            else:
                item = next(i for i in state['shopping'] if i['id'] == path.rsplit('/', 1)[-1])
                assert payload['revision'] == item['revision']
                item.update(payload)
                item['revision'] += 1
            state['revision'] += 1
            result = {'item': item}
        else:
            raise AssertionError('Unexpected browser request: ' + req.method + ' ' + path)
        request_route.fulfill(json=result)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.route('http://shopping.test/**', route)
        page = context.new_page()
        page.clock.install()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://shopping.test/')
        expect(page.locator('.shopping-card')).to_be_visible()
        expect(page.locator('.shopping-budget-line')).to_have_text('待买预算 ¥59 · 1 件未填')
        summary = page.evaluate('ShoppingUI.summarize(data.shopping)')
        assert summary['pendingBudget'] == 5900 and summary['pendingUnknown'] == 1
        assert summary['boughtActual'] == 8500 and summary['boughtBudget'] == 10000
        page.locator('.shopping-card [data-action=add]').click()
        page.locator('dialog input[name=title]').fill('陶瓷碗 · 图片和预算')
        page.locator('dialog input[name=quantity]').fill('2 只')
        page.locator('dialog input[name=budget]').fill('123.45')
        page.locator('dialog input[type=file]').set_input_files({'name': 'sample.png', 'mimeType': 'image/png', 'buffer': PNG})
        expect(page.locator('.shopping-photo-chip')).to_have_count(1)
        expect(page.locator('dialog button[type=submit]')).to_be_enabled()
        page.locator('dialog button[type=submit]').click()
        expect(page.locator('dialog')).not_to_be_visible()
        assert calls[-1][1]['budget'] == 12345 and calls[-1][1]['actual'] is None
        assert calls[-1][1]['photoIds'] == ['photo-1']
        page.locator('.shopping-card [data-shopping-photo=new-item]').click()
        expect(page.locator('.shopping-gallery img')).to_be_visible()
        assert page.locator('.shopping-gallery img').evaluate('(img)=>img.complete&&img.naturalWidth>0')
        page.locator('dialog [data-action=close]').click()
        page.locator('.shopping-card [data-action=edit][data-id=new-item]').click()
        page.locator('dialog input[name=title]').fill('保留输入不丢失')
        page.locator('dialog input[type=file]').set_input_files({'name': 'unsupported.heic', 'mimeType': 'image/heic', 'buffer': b'not-supported'})
        expect(page.locator('.shopping-upload-error')).to_contain_text('HEIC')
        expect(page.locator('dialog input[name=title]')).to_have_value('保留输入不丢失')
        expect(page.locator('.shopping-photo-chip')).to_have_count(1)
        page.locator('[data-photo-remove]').click()
        page.locator('dialog input[name=done]').check()
        page.locator('dialog input[name=actual]').fill('99.50')
        page.locator('dialog button[type=submit]').click()
        expect(page.locator('dialog')).not_to_be_visible()
        assert calls[-1][1]['actual'] == 9950 and calls[-1][1]['photoIds'] == []
        page.wait_for_function("data.shopping.find(item=>item.id==='new-item').done")
        page.evaluate('ShoppingUI.openManager()')
        expect(page.locator('.shopping-totals')).to_contain_text('¥184.5')
        page.locator('#shopping-show-bought').check()
        expect(page.locator('.shopping-manager .shopping-row')).to_have_count(5)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(OUT / 'shopping-phone-manager.png'), full_page=True)
        bounds = page.locator('dialog').bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
        for button in page.locator('.shopping-manager .shopping-check, .shopping-manager .shopping-edit').all():
            size = button.bounding_box()
            assert size['width'] >= 44 and size['height'] >= 44
        page.locator('dialog [data-action=close]').click()
        page.screenshot(path=str(OUT / 'shopping-phone-board.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width': 1920, 'height': 1080})
        state['shopping'][-1]['done'] = False
        state['shopping'][-1]['photoIds'] = ['photo-1']
        page.evaluate("isTV=true;data.shopping.find(item=>item.id==='new-item').done=false;data.shopping.find(item=>item.id==='new-item').photoIds=['photo-1'];renderBoard()")
        expect(page.locator('.shopping-card button')).to_have_count(0)
        expect(page.locator('.shopping-card .shopping-row')).to_have_count(3)
        expect(page.locator('.shopping-tv-pagination')).to_contain_text('1 / 2')
        tv_bounds = page.locator('.shopping-card').bounding_box()
        last_row = page.locator('.shopping-card .shopping-row').last.bounding_box()
        assert last_row['y'] + last_row['height'] <= tv_bounds['y'] + tv_bounds['height']
        page.screenshot(path=str(OUT / 'shopping-tv-board.png'), full_page=True)
        page.clock.fast_forward(21000)
        expect(page.locator('.shopping-tv-pagination')).to_contain_text('2 / 2')
        expect(page.locator('.shopping-card .shopping-row')).to_have_count(1)
        expect(page.locator('.shopping-card .shopping-row')).to_contain_text('保留输入不丢失')
        page.clock.fast_forward(20000)
        expect(page.locator('.shopping-tv-pagination')).to_contain_text('1 / 2')
        for mode in ('today', 'week', 'around'):
            page.set_viewport_size({'width': 1280, 'height': 720})
            page.evaluate('(mode)=>{data.display={calendarView:mode};renderBoard()}', mode)
            layout = page.locator('.shopping-card').evaluate('(card)=>({height:card.clientHeight,scroll:card.scrollHeight})')
            assert layout['scroll'] <= layout['height'] + 1, (mode, layout)
        assert not errors, errors
        print(json.dumps({'summaryNullAndZero': 'passed', 'photoCompressionUpload': 'passed', 'budgetAndActualWrite': 'passed', 'unsupportedPhotoPreservesDraft': 'passed', 'photoRemoval': 'passed', 'mobileTargets': 'passed', 'tvReadOnly': 'passed', 'tvCarouselAndCompactModes': 'passed', 'pageErrors': errors}, ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    run()
