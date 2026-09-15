"""Real browser / temporary Flask household / fake provider HTTP only."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_task_publish import env as fixture
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def run(browser, provider, output):
    with tempfile.TemporaryDirectory() as temporary:
        app, client, headers, remote, _ = fixture.__wrapped__(Path(temporary), SimpleNamespace(param=provider))
        accounts = app.extensions['cloud_accounts']; engine = app.extensions['task_publish']
        # Backend unit fixtures use minimal workflow rows; the actual browser
        # loads complete journey cards, so replace only this synthetic fixture.
        with accounts.db() as con:
            con.execute("DELETE FROM entities WHERE id IN ('local-1','local-2','trip-1')")
        plan = {'title': '京都 · 合成准备流程', 'start': '2026-10-01', 'end': '2026-10-04', 'budget': 2000000,
                'international': True, 'memberIds': ['member1', 'member2'], 'destinations': [{'country': '日本', 'city': '京都'}],
                'checklist': [{'key': 'passport', 'title': '核对护照有效期', 'owner': 'member2', 'dueOffsetDays': -14, 'note': '合成测试'},
                              {'key': 'packing', 'title': '整理行李', 'owner': 'shared', 'dueOffsetDays': -2}], 'shopping': [], 'segments': []}
        p = client.post('/api/journeys/preview', json={'plan': plan}, headers=headers)
        assert p.status_code == 200, p.json
        r = client.post('/api/journeys/apply', json={'previewToken': p.json['previewToken'], 'idempotencyKey': 'browser-task-flow'}, headers=headers)
        assert r.status_code == 201, r.json
        jid, tid = r.json['id'], r.json['tripId']
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        context = browser.new_context(viewport={'width': 1365, 'height': 1000})
        external = []; errors = []
        def local_only(route):
            if urlsplit(route.request.url).hostname == '127.0.0.1': route.continue_()
            else: external.append(route.request.url); route.abort()
        context.route('**/*', local_only)
        page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
        try:
            page.goto(origin); page.locator('[name=password]').fill('testing-password-one')
            page.locator('#login-form button[type=submit]').click()
            page.wait_for_function('() => typeof TaskPublish === "object" && typeof data !== "undefined" && data !== null')
            page.evaluate('(id)=>JourneyUI.open(id)', tid)
            expect(page.locator('[data-journey=cloud-tasks]')).to_be_visible()
            page.locator('[data-journey=cloud-tasks]').click()
            expect(page.locator('#task-publish-form')).to_be_visible()
            assert page.locator('[name=sourceId] option').count() == 1
            assert page.locator('[name=entityId]').count() == 2
            assert page.locator('[name=entityId]:checked').count() == 0
            page.locator('#task-publish-form button[type=submit]').click()
            expect(page.locator('#task-publish-error')).to_contain_text('请先勾选')
            chosen = page.locator('[name=entityId]').first
            eid = chosen.get_attribute('value'); chosen.check()
            page.locator('#task-publish-form button[type=submit]').click()
            expect(page.locator('[data-tp=confirm]')).to_be_visible()
            assert not remote.calls
            with accounts.db() as con:
                assert con.execute('SELECT count(*) FROM task_publications').fetchone()[0] == 0
                original = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (eid,)).fetchone()[0])
            page.screenshot(path=str(output / ('task-publish-preview-' + provider + '.png')), full_page=True)
            with page.expect_response(lambda response: response.url.endswith('/api/task-publish/confirm')):
                page.locator('[data-tp=confirm]').click()
            expect(page.locator('#task-publish-root')).to_be_visible()
            with accounts.db() as con:
                row = dict(con.execute('SELECT * FROM task_publications').fetchone()); rid = row['id']
                assert row['entity_id'] == eid
            engine.process(rid); page.locator('[data-tp=refresh]').click()
            expect(page.locator('#task-publications')).to_contain_text('已连接 · 持续同步')
            assert remote.created == 1
            raw = next(iter(remote.records.values())); tag = '@odata.etag' if provider == 'microsoft' else 'etag'
            raw['status'] = 'completed'; raw[tag] = '"remote-done"'; engine.process(rid)
            with accounts.db() as con:
                value = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (eid,)).fetchone()[0])
                assert value['done'] and value['owner'] == original['owner'] and value['tripId'] == tid
            raw['title'] = '云端修改 · 请核对证件'; raw[tag] = '"remote-title"'; engine.process(rid)
            page.locator('[data-tp=refresh]').click()
            expect(page.locator('[data-tp=conflict-preview]')).to_be_visible()
            page.locator('[data-tp=conflict-preview]').click()
            expect(page.locator('[data-tp=resolve][data-resolution=remote]')).to_be_visible()
            expect(page.locator('.journey-detail-grid')).to_contain_text('云端修改 · 请核对证件')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(output / ('task-publish-conflict-phone-' + provider + '.png')), full_page=True)
            assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth + 1')
            page.locator('[data-tp=resolve][data-resolution=remote]').click()
            expect(page.locator('#task-publish-root')).to_be_visible()
            with accounts.db() as con:
                value = json.loads(con.execute('SELECT data FROM entities WHERE id=?', (eid,)).fetchone()[0])
                assert value['title'] == raw['title'] and value['tripId'] == tid and value['owner'] == original['owner']
            retained_title = value['title']
            raw['title'] = '第二次云端变更'; raw[tag] = '"remote-second"'; engine.process(rid)
            page.locator('[data-tp=refresh]').click(); page.locator('[data-tp=conflict-preview]').click()
            with page.expect_response(lambda response: response.url.endswith('/conflict-confirm')):
                page.locator('[data-tp=resolve][data-resolution=local]').click()
            expect(page.locator('#task-publications')).to_contain_text('等待同步'); engine.process(rid)
            page.locator('[data-tp=refresh]').click()
            expect(page.locator('#task-publications')).to_contain_text('已连接 · 持续同步')
            assert raw['title'] == retained_title and remote.patched == 1
            page.locator('[data-tp=pause]').click()
            expect(page.locator('[data-tp=resume]')).to_be_visible()
            with page.expect_response(lambda response: response.url.endswith('/resume')):
                page.locator('[data-tp=resume]').click()
            expect(page.locator('#task-publications')).to_contain_text('等待同步'); engine.process(rid)
            page.locator('[data-tp=refresh]').click()
            expect(page.locator('#task-publications')).to_contain_text('已连接 · 持续同步')
            accounts.select_sources('account-1', 'member1', [])
            accounts.select_sources('account-1', 'member1', [{'kind': 'tasks', 'remoteId': 'list-1'}])
            page.locator('[data-tp=refresh]').click()
            expect(page.locator('#task-publications')).to_contain_text('来源已断开')
            reconnect_choice = page.locator('[name=entityId][value="' + eid + '"]')
            expect(reconnect_choice).to_be_enabled(); reconnect_choice.check()
            page.locator('#task-publish-form button[type=submit]').click()
            expect(page.locator('#dialog')).to_contain_text('重新连接原清单')
            with page.expect_response(lambda response: response.url.endswith('/api/task-publish/confirm')):
                page.locator('[data-tp=confirm]').click()
            expect(page.locator('#task-publications')).to_contain_text('等待同步'); engine.process(rid)
            page.locator('[data-tp=refresh]').click()
            expect(page.locator('#task-publications')).to_contain_text('已连接 · 持续同步')
            assert remote.created == 1
            with accounts.db() as con:
                token = accounts.decrypt(con.execute("SELECT tokens FROM cloud_accounts WHERE id='account-1'").fetchone()[0]); token['scope'] = 'openid'
                con.execute("UPDATE cloud_accounts SET tokens=? WHERE id='account-1'", (accounts.encrypt(token),))
            page.locator('[data-tp=refresh]').click()
            expect(page.locator('[name=sourceId]')).to_contain_text('需重新授权')
            with accounts.db() as con:
                assert con.execute('SELECT count(*) FROM task_publications').fetchone()[0] == 1
                assert con.execute("SELECT count(*) FROM entities WHERE id LIKE 'cloud-%'").fetchone()[0] == 0
            assert not errors and not external
            page.goto(origin + '/demo'); page.wait_for_function('() => typeof TaskPublish === "object"')
            writes = []; page.on('request', lambda req: writes.append(req.url) if req.method not in {'GET', 'HEAD'} else None)
            page.evaluate('() => TaskPublish.open()')
            expect(page.locator('#dialog')).to_contain_text('演示模式')
            assert not writes
            return {'provider': provider, 'passed': True, 'realCalendarOrTaskWrites': 0, 'fakeCreated': remote.created,
                    'checks': ['journey-entry', 'owned-source-only', 'explicit-selection', 'empty-selection-error', 'preview-readonly', 'confirmed-queue',
                               'published', 'remote-completion-original-id', 'remote-title-conflict', 'adopt-remote-preserves-owner-trip',
                               'explicit-local-conflict-resolution', 'pause-resume', 'explicit-same-list-reconnection', 'missing-permission', '390px-no-overflow', 'demo-zero-writes'],
                    'jsErrors': errors, 'externalRequests': external}
        finally:
            context.close(); server.shutdown(); thread.join(timeout=5)


def main():
    output = ROOT / 'test-results'; output.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        try:
            results = [run(browser, provider, output) for provider in ['microsoft', 'google']]
            (output / 'task-publish-browser-verification.json').write_text(json.dumps({'passed': True, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(results, ensure_ascii=False))
        finally:
            browser.close()


if __name__ == '__main__': main()
