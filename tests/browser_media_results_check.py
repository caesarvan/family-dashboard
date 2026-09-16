"""Actual Edge with explicit synthetic results DTOs; no Google/backend proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading

from flask import jsonify, request
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from browser_household_media_check import Fixture as BaseFixture, IMPORT, Quiet, ROOT, photo


IDS = [f'{index:024x}' for index in range(20, 23)]
PRIVATE_MARKER = 'DO_NOT_RENDER_provider_token_filename_decoder_detail'


class Fixture(BaseFixture):
    def __init__(self):
        super().__init__()
        self.items = {}
        self.fail_once = True
        self.hold_import = False
        self.import_started = threading.Event()
        self.import_release = threading.Event()
        self.stage('staging', ['successful', 'successful', 'failed'] + ['pending'] * 7)

    def stage(self, state, statuses, errors=None, saved=None):
        now = datetime.now(timezone.utc)
        rows = []
        for position, status in enumerate(statuses, 1):
            row = dict(position=position, status=status)
            if status in ('failed', 'skipped'):
                row['error'] = dict(code=(errors or ['input_too_large'])[len([r for r in rows if 'error' in r]) % len(errors or ['input_too_large'])], message=PRIVATE_MARKER)
            rows.append(row)
        ready = sum(status in ('successful', 'duplicate') for status in statuses)
        self.imports[IMPORT] = dict(
            id=IMPORT, revision=1, state=state, createdAt=now.isoformat(),
            expiresAt=(now+timedelta(hours=24)).isoformat(), nextPollAt=(now+timedelta(minutes=1)).isoformat(),
            canConfirm=state == 'awaiting_confirmation', resultsState='known', results=rows,
            counts=dict(selected=len(rows), ready=ready, failed=statuses.count('failed'),
                        skipped=statuses.count('skipped'), pending=statuses.count('pending'),
                        saved=saved, unselected=ready-saved if saved is not None else None))
        available = [status for status in statuses if status in ('successful', 'duplicate')]
        self.candidates = [dict(id=uid, status=status, item=photo(uid)) for uid, status in zip(IDS, available)]

    def create_app(self):
        app = super().create_app()
        original = app.view_functions['api']

        def api(path):
            body = request.get_json(silent=True) or {}
            if path not in (f'media/imports/{IMPORT}', f'media/imports/{IMPORT}/confirm'):
                return original(path)
            self.records.append(dict(path=path, method=request.method, body=deepcopy(body)))
            if path.endswith('/confirm'):
                assert request.method == 'POST'
                assert body['persistSelected'] and body['consentVersion'] == 'media-v1'
                if body['confirmRequestId'] not in self.confirm_receipts:
                    assert body['revision'] == self.imports[IMPORT]['revision']
                    assert set(body['itemIds']) <= {item['id'] for item in self.candidates}
                    self.confirm_receipts[body['confirmRequestId']] = deepcopy(body)
                    for uid in body['itemIds']:
                        self.items[uid] = photo(uid)
                    self.imports[IMPORT].update(state='confirmed', revision=2, canConfirm=False)
                    counts = self.imports[IMPORT]['counts']
                    counts.update(saved=len(body['itemIds']), unselected=counts['ready']-len(body['itemIds']))
                else:
                    assert self.confirm_receipts[body['confirmRequestId']] == body
                if self.fail_once:
                    self.fail_once = False
                    return jsonify(error='合成测试：保存结果未收到。'), 503
                return jsonify({'import': self.imports[IMPORT], 'replayed': True})
            result = deepcopy({'import': self.imports[IMPORT], 'items': self.candidates if self.imports[IMPORT]['state'] == 'awaiting_confirmation' else []})
            if self.hold_import:
                self.import_started.set()
                assert self.import_release.wait(10)
            return jsonify(result)

        app.view_functions['api'] = api
        return app


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT / 'test-results' / 'media-results' / stamp
    out.mkdir(parents=True)
    files = ['static/household-media.js', 'static/household-media.css', 'tests/browser_media_results_check.py']
    hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}
    fixture = Fixture()
    server = make_server('127.0.0.1', 0, fixture.create_app(), threaded=True, request_handler=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    checks, errors, external = [], [], []
    passed = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
            context = browser.new_context(viewport=dict(width=1440, height=1000))
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: external.append(req.url) if not req.url.startswith(f'http://127.0.0.1:{server.server_port}/') else None)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            panel = page.locator('[data-hm-import]')
            expect(panel.locator('[data-hm-count=ready]')).to_contain_text('2 张')
            expect(panel.locator('[data-hm-count=failed]')).to_contain_text('1 张')
            expect(panel.locator('[data-hm-count=pending]')).to_contain_text('7 张')
            expect(panel.locator('progress')).to_have_attribute('value', '3')
            expect(panel.locator('progress')).to_have_attribute('max', '10')
            expect(panel).to_contain_text('输入图片超过 8 MiB 上限')
            checks.append('in-progress selection shows 10 total, 2 successful, 1 failed, 7 pending and actual progress')

            codes = ['too_many_pixels', 'invalid_image', 'unsupported_format', 'multiple_frames', 'output_too_large', 'result_unknown', PRIVATE_MARKER]
            fixture.stage('awaiting_confirmation', ['successful'] * 3 + ['failed'] * 7, codes)
            page.locator('[data-hm=poll]').click()
            expect(panel.locator('[data-hm-count=failed]')).to_contain_text('7 张')
            expect(panel.locator('.hm-result')).to_have_count(10)
            expect(panel.locator('.hm-result-problem')).to_have_count(7)
            expect(panel.locator('[data-hm-candidate]')).to_have_count(3)
            expect(panel).to_contain_text('图片像素超过 2000 万像素上限')
            expect(panel).to_contain_text('图片不完整或无法安全解码')
            expect(panel).to_contain_text('旧记录未保存此项的具体处理原因')
            expect(panel).not_to_contain_text(PRIVATE_MARKER)
            expect(panel).not_to_contain_text('too_many_pixels')
            expect(panel).not_to_contain_text('HEIC')
            checks.append('all seven failures remain visible with fixed safe reasons; unknown code/message never rendered')

            expect(panel.locator('[data-hm-selection-summary]')).to_contain_text('当前勾选的 0 张')
            first = panel.locator('[data-hm-candidate]').nth(0)
            first.focus()
            page.keyboard.press('Space')
            expect(first).to_be_focused()
            expect(first).to_be_checked()
            expect(panel.locator('[data-hm-selection-summary]')).to_contain_text('当前勾选的 1 张')
            expect(panel.locator('[data-hm-selection-summary]')).to_contain_text('还有 2 张未勾选')
            for checkbox in panel.locator('[data-hm-candidate]').all():
                checkbox.check()
            expect(panel.locator('[data-hm-selection-summary]')).to_contain_text('当前勾选的 3 张')
            assert not fixture.confirm_receipts
            checks.append('keyboard selection updates exact save/unchecked counts without moving focus or automatically saving')

            for width, theme in [(1440, 'light'), (390, 'light'), (360, 'dark')]:
                page.set_viewport_size(dict(width=width, height=900))
                page.evaluate("(theme)=>{document.documentElement.dataset.theme=theme;document.body.style.background=theme==='dark'?'#101a20':'#fafafa';}", theme)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(out/f'results-{width}-{theme}.png'), full_page=True)
            checks.append('desktop and 390/360px light/dark layouts fit without horizontal overflow')

            panel.locator('[data-hm-persist]').check()
            panel.locator('[data-hm=confirm]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('保存结果未收到')
            expect(panel.locator('[data-hm-candidate]').nth(0)).to_be_disabled()
            expect(panel.locator('[data-hm-selection-summary]')).to_contain_text('当前勾选的 3 张')
            panel.locator('[data-hm=confirm]').click()
            expect(panel.locator('[data-hm-count=saved]')).to_contain_text('3 张')
            expect(panel.locator('[data-hm-count=failed]')).to_contain_text('7 张')
            expect(panel.locator('.hm-result-problem')).to_have_count(7)
            expect(panel).to_contain_text('本次选择 10 张 · 已保存 3 张')
            expect(panel).not_to_contain_text('保存完成')
            expect(panel).not_to_contain_text('全部成功')
            expects = [r['body'] for r in fixture.records if r['path'].endswith('/confirm')]
            assert len(expects) == 2 and expects[0] == expects[1] and len(fixture.confirm_receipts) == 1
            expect(panel.locator('[data-hm-candidate]')).to_have_count(0)
            page.reload()
            page.locator('.hm-history summary').click()
            page.locator('[data-hm=resume]').click()
            expect(panel.locator('[data-hm-count=saved]')).to_contain_text('3 张')
            expect(panel.locator('.hm-result-problem')).to_have_count(7)
            page.screenshot(path=str(out/'confirmed-partial-360-light.png'), full_page=True)
            checks.append('10 selected / 3 saved / 7 failures persist through unknown confirmation retry and history reload')

            fixture.imports[IMPORT].update(resultsState='unknown', results=[])
            fixture.imports[IMPORT]['counts'] = dict(selected=None, ready=None, skipped=None, failed=None, pending=None, saved=3, unselected=None)
            panel.locator('[data-hm=poll]').click()
            expect(panel).to_contain_text('已保存 3 张；本次其他处理结果未记录')
            expect(panel.locator('[data-hm-count]')).to_have_count(0)
            expect(panel.locator('.hm-result')).to_have_count(0)
            expect(panel).not_to_contain_text('0 张')
            fixture.imports[IMPORT]['counts']['saved'] = None
            panel.locator('[data-hm=poll]').click()
            expect(panel).to_contain_text('本次保存数量未记录；本次其他处理结果未记录')
            expect(panel).not_to_contain_text('0 张')
            fixture.imports[IMPORT].pop('resultsState')
            fixture.imports[IMPORT].pop('counts')
            panel.locator('[data-hm=poll]').click()
            expect(panel).to_contain_text('本次保存数量未记录')
            checks.append('legacy null or absent results/counts remain explicitly unknown, never invented zero or selected total')

            fixture.stage('awaiting_confirmation', ['duplicate', 'successful', 'successful', 'skipped'], ['unsupported_type'])
            panel.locator('[data-hm=poll]').click()
            expect(panel).to_contain_text('本次仅处理照片，已跳过非照片媒体')
            expect(panel.locator('[data-hm-count=skipped]')).to_contain_text('1 张')
            panel.locator('[data-hm-candidate]').nth(0).check()
            expect(panel.locator('[data-hm-selection-summary]')).to_contain_text('还有 2 张未勾选')
            panel.locator('[data-hm-persist]').check()
            panel.locator('[data-hm=confirm]').click()
            expect(panel.locator('[data-hm-count=saved]')).to_contain_text('1 张')
            expect(panel.locator('[data-hm-count=unselected]')).to_contain_text('2 张')
            expect(panel).to_contain_text('已在相册，可复用')
            checks.append('duplicate and skipped processing stay distinct from saved and successful-but-unselected counts')

            before_writes = len([r for r in fixture.records if r['method'] != 'GET'])
            fixture.stage('failed', ['failed', 'failed'], ['input_too_large', 'invalid_image'])
            panel.locator('[data-hm=poll]').click()
            expect(panel.locator('[data-hm-count=failed]')).to_contain_text('2 张')
            expect(panel.locator('[data-hm-candidate]')).to_have_count(0)
            expect(panel.locator('.hm-result-problem')).to_have_count(2)
            assert len([r for r in fixture.records if r['method'] != 'GET']) == before_writes
            assert not any(r['path'] in ('media/imports', 'accounts/google-photos/bind') and r['method'] == 'POST' for r in fixture.records)
            checks.append('all-failed results do not automatically retry selection, save, or reauthorize')

            fixture.hold_import = True
            panel.locator('[data-hm=poll]').click()
            assert fixture.import_started.wait(3)
            fixture.actor = 'member2'
            page.evaluate('switchLocal()')
            fixture.import_release.set()
            expect(page.locator('#host')).to_contain_text('登录成员或家庭已变化')
            page.wait_for_timeout(200)
            expect(page.locator('.hm-result,.hm-candidate,.hm-card')).to_have_count(0)
            checks.append('identity switch clears results and discards late import detail')
            records_before_tv = len(fixture.records)
            page.evaluate("isTV=true;HouseholdMedia.mount(document.querySelector('#host'))")
            expect(page.locator('#host')).to_contain_text('请在手机或电脑上登录')
            assert len(fixture.records) == records_before_tv
            checks.append('TV mode makes no media API request and cannot display import results')
            assert not errors and not external, (errors, external)
            assert hashes == {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}
            passed = True
            browser.close()
    finally:
        fixture.import_release.set()
        server.shutdown()
        thread.join(timeout=3)
        report = dict(passed=passed, checks=checks, pageErrors=errors, externalRequests=external,
                      sourceHashes=hashes, coverage='Real local Edge with synthetic API DTOs. No actual Google, backend, production or physical TV validation.')
        (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=passed, checks=len(checks), report=str(out/'result.json')), ensure_ascii=False))


if __name__ == '__main__':
    main()
