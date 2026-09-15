"""Real loopback Flask/Edge: stale confirmation stays disabled during repreview.

No production data, OAuth navigation or real provider calls. Delayed replies
come from the actual Flask endpoint; only the delivery time is controlled.
"""
from copy import deepcopy
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--legacy-negative-control', action='store_true',
                        help='Serve the same JS without the one-line disable fix; must fail the pending-button assertion.')
    args = parser.parse_args()
    suffix = '-legacy' if args.legacy_negative_control else ''
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    report = {'passed': False, 'checks': [], 'pageErrors': [], 'externalRequests': [],
              'productionWrites': 0, 'realCloudWrites': 0, 'screenshots': [],
              'scope': 'Temporary Flask/SQLite and actual Edge; controlled delivery of real HTTP responses',
              'legacyNegativeControl': args.legacy_negative_control,
              'sourceHashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                               for name in ['app.py', 'static/journey-ui.js']}}
    page = None
    with tempfile.TemporaryDirectory(prefix='journey-confirm-guard-') as folder:
        application = create_app({'TESTING': True, 'DATA_DIR': folder,
            'SECRET_KEY': 'synthetic-draft-guard', 'SESSION_COOKIE_SECURE': False,
            'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
            'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
            'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'OPENAI_API_KEY': ''})
        assert application.config['SESSION_REFRESH_EACH_REQUEST'] is False
        server = make_server('127.0.0.1', 0, application, threaded=True, request_handler=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1050})
                pending, previews, applies = {}, [], []
                gate = {'path': None, 'armed': False, 'failure': False}

                def guard(route):
                    if not route.request.url.startswith(origin + '/'):
                        report['externalRequests'].append(urlsplit(route.request.url).path)
                        route.abort()
                    else:
                        route.continue_()

                def controlled(route):
                    path = urlsplit(route.request.url).path
                    if path == '/api/journeys/preview' and gate['failure']:
                        gate['failure'] = False
                        route.fulfill(status=503, content_type='application/json', body='{"error":"合成重新预览暂不可用"}')
                        return
                    response = route.fetch()
                    if path == '/api/journeys/preview' and response.status == 200:
                        previews.append(response.json()['previewToken'])
                    if gate['armed'] and path == gate['path']:
                        gate['armed'] = False
                        pending.update(route=route, response=response)
                    else:
                        route.fulfill(response=response)

                context.route('**/*', guard)
                if args.legacy_negative_control:
                    text = (ROOT / 'static/journey-ui.js').read_text(encoding='utf-8')
                    needle = "    if (form.id === 'journey-review-form') dirty();\n"
                    assert text.count(needle) == 1
                    old_js = text.replace(needle, '')
                    report['servedJourneyJsSha256'] = digest(old_js)
                    context.route('**/static/journey-ui.js*', lambda route: route.fulfill(
                        status=200, content_type='application/javascript', body=old_js))
                context.route('**/api/me', controlled)
                context.route('**/api/journeys/preview', controlled)
                assert context.request.post(origin + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                headers = {'X-CSRF-Token': context.request.get(origin + '/api/me').json()['csrf']}
                page = context.new_page()
                page.on('pageerror', lambda exc: report['pageErrors'].append(str(exc)))
                page.on('request', lambda req: applies.append(req.post_data_json)
                        if urlsplit(req.url).path == '/api/journeys/apply' else None)
                page.goto(origin)
                expect(page.locator('.ps-home-board')).to_be_visible()

                def database_state():
                    with closing(sqlite3.connect(Path(folder) / 'household.sqlite3')) as con:
                        return {'workflows': con.execute('SELECT count(*) FROM journey_workflows').fetchone()[0],
                                'actions': con.execute('SELECT count(*) FROM journey_actions').fetchone()[0],
                                'entityIds': [r[0] for r in con.execute('SELECT id FROM entities ORDER BY id')],
                                'revisions': dict(con.execute('SELECT id,revision FROM journey_workflows'))}

                def fresh_review(title):
                    page.evaluate('JourneyUI.create()')
                    for name, value in {'title': title, 'start': '2026-12-01', 'end': '2026-12-05'}.items():
                        page.locator('#journey-core-fields [name=' + name + ']').fill(value)
                    for name, value in {'country': '虚构国家', 'city': '虚构城市',
                                        'arrival': '2026-12-01', 'departure': '2026-12-05'}.items():
                        page.locator('.journey-destination [name=' + name + ']').fill(value)
                    page.locator('#journey-form [type=submit]').click()
                    expect(page.locator('#journey-apply')).to_be_enabled()
                    return previews[-1]

                def delay_and_check(action, path, before):
                    gate.update(path=path, armed=True)
                    page.locator('[data-journey=' + action + ']').click()
                    # This check happens while the real response is held, not
                    # after a timeout that could let the new token arrive.
                    expect(page.locator('#journey-apply')).to_be_disabled()
                    deadline = time.monotonic() + 5
                    while not pending and time.monotonic() < deadline:
                        page.wait_for_timeout(20)
                    assert pending, 'Expected HTTP request did not reach the gate'
                    expect(page.locator('#journey-apply')).to_be_disabled()
                    number = len(applies)
                    page.locator('#journey-apply').evaluate('(button) => button.click()')
                    # Normal implicit form submission also cannot use the old
                    # receipt when the confirmation button is disabled.
                    page.locator('#journey-checklist input[name=title]').first.press('Enter')
                    page.wait_for_timeout(80)
                    assert len(applies) == number, 'Old receipt was submitted while preview pending'
                    assert database_state() == before, 'Preview pending changed persisted workflow'

                def release_and_save(old_token, before, new_workflow, name):
                    response = pending.pop('response')
                    pending.pop('route').fulfill(response=response)
                    expect(page.locator('#journey-apply')).to_be_enabled()
                    new_token = previews[-1]
                    assert new_token != old_token
                    number = len(applies)
                    page.locator('#journey-apply').click()
                    expect(page.locator('.journey-detail-top')).to_be_visible()
                    assert len(applies) == number + 1
                    assert applies[-1]['previewToken'] == new_token
                    assert applies[-1]['previewToken'] != old_token
                    after = database_state()
                    assert after['actions'] == before['actions'] + 1
                    assert after['workflows'] == before['workflows'] + int(new_workflow)
                    if not new_workflow:
                        assert after['entityIds'] == before['entityIds']
                        changed = [uid for uid in after['revisions'] if after['revisions'][uid] != before['revisions'][uid]]
                        assert len(changed) == 1
                        assert after['revisions'][changed[0]] == before['revisions'][changed[0]] + 1
                    report['checks'].append({'name': name, 'passed': True,
                        'oldTokenSha256': digest(old_token), 'newTokenSha256': digest(new_token),
                        'confirmationRequests': 1, 'committedActions': 1})

                for target in ('/api/me', '/api/journeys/preview'):
                    old = fresh_review('虚构新建 · ' + target)
                    before = database_state()
                    delay_and_check('repreview', target, before)
                    release_and_save(old, before, True, 'new-plan repreview held at ' + target)

                journey = context.request.get(origin + '/api/journeys').json()['journeys'][0]
                for target in ('/api/me', '/api/journeys/preview'):
                    page.evaluate('(id) => JourneyUI.open(id)', journey['id'])
                    expect(page.locator('.journey-detail-top')).to_be_visible()
                    page.locator('[data-journey=edit]').click()
                    page.locator('#journey-core-fields [name=budget]').fill('12345')
                    page.locator('#journey-form [type=submit]').click()
                    expect(page.locator('#journey-apply')).to_be_enabled()
                    old = previews[-1]
                    latest = context.request.get(origin + '/api/journeys/' + journey['id']).json()
                    plan = deepcopy(latest['plan'])
                    plan['saved'] += 1000
                    fresh = context.request.post(origin + '/api/journeys/preview', headers=headers,
                        data={'journeyId': latest['id'], 'revision': latest['revision'], 'plan': plan})
                    assert fresh.status == 200
                    change = context.request.post(origin + '/api/journeys/apply', headers=headers,
                        data={'previewToken': fresh.json()['previewToken'], 'idempotencyKey': 'parallel-' + str(latest['revision'])})
                    assert change.status == 200
                    # One intentional stale apply establishes the actual 409
                    # recovery flow; no additional stale apply is allowed later.
                    page.locator('#journey-apply').click()
                    expect(page.locator('[data-journey=latest-draft]')).to_be_visible()
                    page.locator('[data-journey=latest-draft]').click()
                    expect(page.locator('[data-journey=rebase-draft]')).to_be_visible()
                    before = database_state()
                    delay_and_check('rebase-draft', target, before)
                    release_and_save(old, before, False, '409 rebase held at ' + target)

                old = fresh_review('虚构失败重试 · 保留草稿')
                before = database_state()
                gate['failure'] = True
                page.locator('[data-journey=repreview]').click()
                expect(page.locator('.journey-error')).to_contain_text('合成重新预览暂不可用')
                expect(page.locator('#journey-apply')).to_be_disabled()
                expect(page.locator('[data-journey=repreview]')).to_be_enabled()
                assert database_state() == before
                delay_and_check('repreview', '/api/journeys/preview', before)
                release_and_save(old, before, True, '503 repreview keeps old confirmation disabled then saves new token once')
                screenshot = output / 'journey-confirm-guard-final.png'
                page.screenshot(path=str(screenshot))
                report['screenshots'].append(str(screenshot))
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
                browser.close()
        except Exception as exc:
            report['failure'] = str(exc)
            if page is not None and not page.is_closed():
                try:
                    page.screenshot(path=str(output / 'journey-confirm-guard-failure.png'))
                except Exception:
                    pass
            raise
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            report_path = output / ('journey-confirm-guard' + suffix + '-verification.json')
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']),
                              'report': str(report_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
