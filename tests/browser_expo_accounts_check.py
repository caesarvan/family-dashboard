"""Frozen Expo accounts UI against real local Flask, member sessions and SQLite.

Only the provider protocol is synthetic. OAuth account seeding uses actual
bind/callback routes. Browser interceptions delay/drop genuine HTTP responses;
they never fabricate a business response. No real cloud or production access.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-build-evidence', required=True)
    args = parser.parse_args()
    root, bundle = args.source_root.resolve(), args.bundle.resolve()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert head == args.expected_head, 'Unexpected source commit'
    evidence_path = bundle.parent / 'build-evidence.json'
    assert sha(evidence_path) == args.expected_build_evidence
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    assert evidence['sourceHead'] == head
    assert evidence['sourceTree'] == subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, text=True).strip()
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=root, text=True).strip()
    names = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    hashes = lambda: {name: sha(root / name) for name in names}
    bundle_hashes = lambda: {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert bundle_hashes() == evidence['files']
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items())
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-accounts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], blockedAuthorizationNavigations=[], httpErrors=[], screenshots=[],
        eventInjections=['document.hidden/visibilityState plus visibilitychange for background/foreground'],
        head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path), harnessSha256=sha(out / 'executed-harness.py'),
        sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(), productionWrites=0, realCloud=False, physicalTelevision=False,
        scope='Frozen Expo bundle, real Flask/SQLite/member CSRF and HTTP routes. Synthetic provider identity/discovery/snapshot protocol only.')
    page = None

    def passed(message):
        report['checks'].append(message)
        print('PASS ' + message, flush=True)

    original_connect = socket.socket.connect

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            report['externalRequests'].append('non-loopback socket')
            raise AssertionError('External network forbidden')
        return original_connect(sock, address)

    try:
        with ExitStack() as lifecycle:
            lifecycle.enter_context(patch.object(socket.socket, 'connect', local_connect))
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-accounts-')))
            sys.path[:0] = [str(root), str(root / 'tests')]
            source = importlib.import_module('app')
            fixture = importlib.import_module('test_cloud_accounts')
            provider_error = importlib.import_module('cloud_providers').ProviderError
            shutil.copytree(root / 'static', folder / 'static', ignore=shutil.ignore_patterns('experience'))
            shutil.copytree(bundle, folder / 'static' / 'experience')
            lifecycle.enter_context(patch.object(source, 'ROOT', folder))
            monkey = lifecycle.enter_context(pytest.MonkeyPatch.context())
            for name in ('OPENAI_API_KEY', 'OPENAI_MODEL', 'NVIDIA_API_KEY', 'NVIDIA_MODEL'):
                monkey.setenv(name, '')
            remote = fixture.Remote()
            control = {'discoveryError': None, 'discoveries': 0, 'snapshots': 0, 'omitSources': set()}
            original_factory = remote.factory

            def provider_factory(name, token, transport=None):
                original = original_factory(name, token, transport)

                class Provider:
                    identity = original.identity
                    write_task = original.write_task

                    def list_sources(self):
                        control['discoveries'] += 1
                        if control['discoveryError']:
                            raise control['discoveryError']
                        return [item for item in original.list_sources() + [
                            {'id': 'read-only-tasks', 'kind': 'tasks', 'name': '只读归档清单', 'writable': False}]
                            if item['id'] not in control['omitSources']]

                    def snapshot(self, selected, start, end):
                        control['snapshots'] += 1
                        return original.snapshot(selected, start, end)

                return Provider()

            cfg = {'TESTING': True, 'SECRET_KEY': 'expo-accounts-synthetic-only', 'DATA_DIR': str(folder / 'data'),
                'SESSION_COOKIE_SECURE': False, 'PUBLIC_ORIGIN': 'http://localhost',
                'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two',
                'MICROSOFT_CLIENT_ID': 'test-ms-client', 'MICROSOFT_CLIENT_SECRET': 'synthetic-ms-secret',
                'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
                'OPENAI_API_KEY': '', 'OPENAI_MODEL': '', 'NVIDIA_API_KEY': '', 'NVIDIA_MODEL': '',
                'CLOUD_PROVIDER_FACTORY': provider_factory, 'OAUTH_TRANSPORT': remote.tokens}
            application = source.create_app(cfg)
            engine = application.extensions['cloud_accounts']
            _, _, aid = fixture.bind(application, remote, 1, subject='owner-synthetic')
            _, _, partner_aid = fixture.bind(application, remote, 2, subject='partner-synthetic')
            owner_name, partner_name = '合成本人账户', '合成伴侣账户'
            with engine.db() as con:
                con.execute('UPDATE cloud_accounts SET name=?,email=? WHERE id=?', (owner_name, 'owner@example.test', aid))
                con.execute('UPDATE cloud_accounts SET name=?,email=? WHERE id=?', (partner_name, 'partner@example.test', partner_aid))
            server = make_server('127.0.0.1', 0, application, threaded=True, request_handler=Quiet, ssl_context='adhoc')
            base = 'https://127.0.0.1:' + str(server.server_port)
            application.config.update(PUBLIC_ORIGIN=base, SESSION_COOKIE_SECURE=True)
            # The ephemeral listener port was unavailable when constructing the
            # real factory. Bind the engine's configured callback origin now.
            engine.origin = base
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def stop():
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                assert not thread.is_alive()

            lifecycle.callback(stop)
            with sync_playwright() as pw, ExitStack() as browsers:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                browsers.callback(browser.close)

                def failure_capture():
                    if not report['passed'] and page is not None and not page.is_closed():
                        try:
                            page.screenshot(path=str(out / 'failure.png'), full_page=True)
                            (out / 'failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
                        except Exception:
                            pass

                browsers.callback(failure_capture)

                def context(number=None):
                    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, ignore_https_errors=True)

                    def route(handler):
                        if urlsplit(handler.request.url).hostname == '127.0.0.1':
                            handler.continue_()
                        else:
                            report['externalRequests'].append(urlsplit(handler.request.url).hostname)
                            handler.abort()

                    ctx.route('**/*', route)
                    ctx.on('page', lambda p: p.on('pageerror', lambda error: report['pageErrors'].append(str(error))))
                    ctx.on('response', lambda response: report['httpErrors'].append({'method': response.request.method,
                        'path': urlsplit(response.url).path, 'status': response.status}) if response.status >= 400 else None)
                    if number:
                        login(ctx, number)
                    return ctx

                def login(ctx, number=1):
                    response = ctx.request.post(base + '/api/login', data={'username': f'member{number}',
                        'password': 'testing-password-' + ('one' if number == 1 else 'two')})
                    assert response.status == 200, response.text()

                def get(ctx, path):
                    response = ctx.request.get(base + path)
                    assert response.status == 200, response.text()
                    return response.json()

                def write(ctx, method, path, body, status=200):
                    response = ctx.request.fetch(base + path, method=method,
                        headers={'X-CSRF-Token': get(ctx, '/api/me')['csrf'], 'Origin': base}, data=body)
                    assert response.status == status, response.text()
                    return response.json()

                def account(ctx, uid=aid):
                    return next(value for value in get(ctx, '/api/accounts')['accounts'] if value['id'] == uid)

                def saved(ctx, uid=aid):
                    return {(item['kind'], item['remoteId']): (item['owner'], item['primary']) for item in account(ctx, uid)['sources']}

                def button(p, name):
                    return p.get_by_role('button', name=re.compile(r'(?:^|\s)' + re.escape(name) + r'(?=$|[：:])'))

                def checkbox(p, name):
                    return p.get_by_role('checkbox', name=name, exact=True)

                def visibility(p, hidden):
                    p.evaluate('''hidden => {
                      if (hidden) {
                        Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});
                        Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});
                      } else { delete document.hidden; delete document.visibilityState; }
                      document.dispatchEvent(new Event('visibilitychange'));
                    }''', hidden)

                def assert_layout(p, width, name):
                    p.evaluate('() => document.fonts.ready')
                    metrics = p.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,
                      clipped:[...document.querySelectorAll('input,button,[role="button"],[role="checkbox"]')].filter(e=>{const r=e.getBoundingClientRect();
                      return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'&&r.right>innerWidth+2&&r.left<innerWidth;})
                      .map(e=>({label:e.getAttribute('aria-label')||e.innerText,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})''')
                    assert metrics['scroll'] <= width + 2 and not metrics['clipped'], metrics
                    filename = f'{name}-{width}.png'
                    p.screenshot(path=str(out / filename), full_page=True)
                    report['screenshots'].append(filename)

                owner, partner = context(1), context(2)
                page, partner_page = owner.new_page(), partner.new_page()
                requests = []
                page.on('request', lambda request: requests.append({'path': urlsplit(request.url).path,
                    'method': request.method, 'body': request.post_data_json if request.method == 'POST' and request.post_data else None}))
                source_path = '/api/accounts/' + aid + '/sources'

                def source_posts():
                    return [request for request in requests if request['path'] == source_path and request['method'] == 'POST']

                def open_accounts(p):
                    p.goto(base + '/app/connections')
                    expect(p.get_by_role('heading', name='账户与同步', exact=True)).to_be_visible(timeout=15000)
                    expect(button(p, '连接 Microsoft')).to_be_enabled()

                def open_editor(p):
                    button(p, '选择日历与清单').first.click()
                    expect(p.get_by_text('选择共享内容', exact=True)).to_be_visible()
                    expect(checkbox(p, '选择日历：私人日历')).to_be_visible()

                def consent(p):
                    value = checkbox(p, '我确认共享所选的完整日程标题、地点和任务')
                    if not value.is_checked():
                        value.focus()
                        value.press('Space')
                    expect(value).to_be_checked()

                def review_save(p):
                    consent(p)
                    button(p, '查看变更').click()
                    expect(button(p, '确认保存')).to_be_enabled()

                for status, reason, message in [
                    ('connected', '', '请核对下方账户，并选择要同步和共享的日历、清单。'),
                    ('error', 'insufficient_permissions', '缺少日历或清单权限，请重新连接并允许这些权限。'),
                    ('error', 'SYNTHETIC-UNTRUSTED-TEXT', '账户授权未完成，请稍后重试。'),
                ]:
                    page.goto(base + '/?' + urlencode({'auth': status, 'reason': reason,
                        'code': 'SYNTHETIC-PRIVATE-CODE', 'state': 'SYNTHETIC-PRIVATE-STATE'}))
                    expect(page).to_have_url(base + '/app/connections')
                    expect(page.get_by_text(message, exact=True)).to_be_visible()
                    expect(page.locator('body')).not_to_contain_text('SYNTHETIC-')
                    assert len(get(owner, '/api/accounts')['accounts']) == 1
                guest = context()
                guest_page = guest.new_page()
                guest_page.goto(base + '/?auth=error&reason=unbound_account')
                expect(guest_page).to_have_url(base + '/app/connections')
                expect(guest_page.get_by_text('这个账户尚未绑定。请先用家庭密码登录，再连接自己的账户。', exact=True)).to_be_visible()
                expect(guest_page.get_by_role('textbox', name='登录密码', exact=True)).to_be_visible()
                page.goto(base + '/?auth=photos-connected')
                expect(page).to_have_url(base + '/app/photos')
                passed('real OAuth return bridge drops code/state and unknown text; fixed result messages are consumed in Expo, anonymous login error remains actionable and Photos return remains separate')

                open_accounts(page)
                expect(page.get_by_text(owner_name, exact=True)).to_be_visible()
                expect(page.locator('body')).not_to_contain_text(partner_name)
                expect(button(page, '连接 Google')).to_be_disabled()
                assert control['discoveries'] == 0, 'Opening accounts must not implicitly enumerate remote sources'
                assert get(partner, '/api/accounts')['accounts'][0]['id'] == partner_aid
                assert partner.request.get(base + source_path).status == 404
                passed('configured/unconfigured providers are truthful; account cards are owner-only and opening does not discover cloud sources')

                # The real bind API generates the URL and state. Abort the provider
                # document request before any external network, recording no URL
                # query or OAuth state. No account connection is inferred from it.
                def abort_authorization(handler):
                    target = urlsplit(handler.request.url)
                    params = parse_qs(target.query)
                    expected = '/common/oauth2/v2.0/authorize' if target.hostname == 'login.microsoftonline.com' else '/o/oauth2/v2/auth'
                    provider = 'microsoft' if target.hostname == 'login.microsoftonline.com' else 'google'
                    assert target.scheme == 'https' and target.path == expected
                    assert params['redirect_uri'] == [base + '/auth/' + provider + '/callback']
                    assert params['response_type'] == ['code'] and params['code_challenge_method'] == ['S256']
                    assert len(params['state'][0]) >= 32 and len(params['code_challenge'][0]) == 43
                    report['blockedAuthorizationNavigations'].append({'host': target.hostname, 'path': target.path, 'externalNetwork': False})
                    handler.abort('blockedbyclient')

                for provider, host in [('Microsoft', 'login.microsoftonline.com'), ('Google', 'accounts.google.com')]:
                    if provider == 'Google':
                        application.config.update(GOOGLE_CLIENT_ID='synthetic-google-client', GOOGLE_CLIENT_SECRET='synthetic-google-secret')
                        open_accounts(page)
                    page.route('https://' + host + '/**', abort_authorization)
                    # request alone fires before its route callback is handled.
                    # Wait for the actual abort and a loaded local document before
                    # unregistering, so no in-flight handler is displaced.
                    with page.expect_event('requestfailed', predicate=lambda request: urlsplit(request.url).hostname == host):
                        button(page, '连接 ' + provider).click()
                    open_accounts(page)
                    page.unroute('https://' + host + '/**', abort_authorization)
                    assert len(get(owner, '/api/accounts')['accounts']) == 1
                application.config.update(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='')
                open_accounts(page)
                passed('real Microsoft and Google bind buttons generate current-app PKCE authorization URLs; provider navigation blocked before network, no binding or sync success fabricated')

                write(owner, 'POST', '/api/items/tasks', {'title': '合成本地待办保留', 'sourceId': ''}, 201)
                open_editor(page)
                checkbox(page, '选择日历：私人日历').focus()
                checkbox(page, '选择日历：私人日历').press('Space')
                button(page, '日历 私人日历 归属：共同').click()
                checkbox(page, '选择清单：共同待办').click()
                expect(checkbox(page, '选择清单：只读归档清单')).to_be_disabled()
                button(page, '设为主清单：共同待办').click()
                assert not source_posts() and saved(owner) == {}
                review_save(page)
                assert not source_posts()
                button(page, '确认保存').click()
                expect(button(page, '选择日历与清单').first).to_be_enabled()
                assert saved(owner) == {('calendar', 'cal-1'): ('shared', False), ('tasks', 'list-1'): ('shared', True)}
                assert len(source_posts()) == 1 and source_posts()[0]['body']['selectionVersion']
                assert not any(item['lastSuccess'] for item in account(owner)['sources'])
                passed('keyboard selection, explicit sharing consent and review persist chosen calendar/task/primary only; read-only task cannot be selected')

                remote.records[('microsoft', 'list-1')] = {'t': {'id': 't', 'version': 'v1', 'data':
                    {'title': '合成云清单事项', 'done': False, 'note': '', 'due': '', 'tripId': ''}}}
                remote.records[('microsoft', 'cal-1')] = {'e': {'id': 'e', 'version': 'v1', 'data':
                    {'title': '合成完整日程标题', 'start': '2026-10-01T10:00:00+08:00', 'end': '2026-10-01T11:00:00+08:00',
                     'allDay': False, 'location': '合成公开会合地点'}}}
                snapshots_before = control['snapshots']
                button(page, '检查更新').first.click()
                expect(page.get_by_text('已安排后台检查。请查看各来源的最近成功时间，排队不代表同步完成。', exact=True)).to_be_visible()
                assert control['snapshots'] == snapshots_before
                assert not any(item['lastSuccess'] for item in account(owner)['sources'])
                engine.tick()
                assert all(item['lastSuccess'] and not item['error'] for item in account(owner)['sources'])
                state = get(owner, '/api/state')
                assert any(item['title'] == '合成云清单事项' for item in state['tasks'])
                assert state['events'][0]['location'] == '合成公开会合地点'
                partner_state = get(partner, '/api/state')
                assert any(item['title'] == '合成云清单事项' for item in partner_state['tasks'])
                assert partner_state['events'][0]['title'] == '合成完整日程标题'
                assert partner_state['events'][0]['location'] == '合成公开会合地点'
                assert all(item['id'] != aid for item in get(partner, '/api/accounts')['accounts'])
                open_accounts(page)
                remote.fail_snapshot = True
                fixture.due(engine)
                engine.tick()
                assert all(item['error'] and item['lastSuccess'] for item in account(owner)['sources'])
                open_accounts(page)
                expect(page.locator('body')).to_contain_text('同步暂时失败')
                assert any(item['title'] == '合成云清单事项' for item in get(owner, '/api/state')['tasks'])
                remote.fail_snapshot = False
                fixture.due(engine)
                engine.tick()
                open_accounts(page)
                passed('queue acknowledgement does not claim source success; actual worker snapshot records success, failure keeps prior mirror and visible error, retry recovers')

                # The background poll must never replace a draft or its CAS baseline.
                open_editor(page)
                checkbox(page, '选择清单：可选清单').click()
                search = page.get_by_role('textbox', name='搜索日历或清单', exact=True)
                search.fill('共同')
                reads_before = sum(r['method'] == 'GET' and r['path'] == '/api/accounts' for r in requests)
                for _ in range(120):
                    if sum(r['method'] == 'GET' and r['path'] == '/api/accounts' for r in requests) > reads_before:
                        break
                    page.wait_for_timeout(150)
                assert sum(r['method'] == 'GET' and r['path'] == '/api/accounts' for r in requests) > reads_before
                expect(search).to_have_value('共同')
                search.fill('')
                expect(checkbox(page, '选择清单：可选清单')).to_be_checked()
                concurrent = account(owner)
                write(owner, 'POST', source_path, {'selectionVersion': concurrent['selectionVersion'],
                    'sources': [{'kind': 'calendar', 'remoteId': 'cal-1', 'owner': 'shared', 'primary': False}]})
                review_save(page)
                button(page, '确认保存').click()
                expect(button(page, '已核对最新选择，继续编辑')).to_be_enabled()
                assert saved(owner) == {('calendar', 'cal-1'): ('shared', False)}
                button(page, '已核对最新选择，继续编辑').click()
                expect(checkbox(page, '选择清单：可选清单')).to_be_checked()
                review_save(page)
                button(page, '确认保存').click()
                expect(button(page, '选择日历与清单').first).to_be_enabled()
                assert set(saved(owner)) == {('calendar', 'cal-1'), ('tasks', 'list-1'), ('tasks', 'list-2')}
                assert any(e['path'] == source_path and e['status'] == 409 for e in report['httpErrors'])
                passed('real 15s poll preserves typed search and unsaved choice; concurrent CAS409 preserves draft until explicit fresh-baseline review and save')

                # Saving is not an idempotent route. A lost committed response must
                # be reconciled by reading actual selections, never blind repetition.
                open_editor(page)
                checkbox(page, '选择日历：私人日历').click()
                checkbox(page, '选择清单：共同待办').click()
                review_save(page)
                expect(page.locator('body')).to_contain_text('私人日历')
                expect(page.locator('body')).to_contain_text('共同待办')
                dropped = {}

                def drop_save(handler):
                    if handler.request.method == 'POST' and not dropped:
                        dropped['body'] = handler.request.post_data_json
                        response = handler.fetch()
                        dropped['status'] = response.status
                        assert response.status == 200
                        handler.abort('failed')
                    else:
                        handler.continue_()

                before_drop = len(source_posts())
                page.route('**' + source_path, drop_save)
                button(page, '确认保存').click()
                expect(button(page, '选择日历与清单').first).to_be_enabled(timeout=15000)
                page.unroute('**' + source_path, drop_save)
                assert dropped and len(source_posts()) == before_drop + 1
                assert saved(owner) == {('tasks', 'list-2'): ('shared', False)}
                assert not get(owner, '/api/state')['events']
                assert all(item['title'] != '合成云清单事项' for item in get(owner, '/api/state')['tasks'])
                report['droppedResponse'] = {'realServerCommit': True, 'status': dropped['status'], 'postCount': 1}
                passed('removal review names removed sources; full replacement removes their local mirrors; dropped committed save is confirmed by GET with exactly one POST')

                # Concealment must be immediate, independent of the poll interval.
                open_editor(page)
                search = page.get_by_role('textbox', name='搜索日历或清单', exact=True)
                search.fill('可选')
                visibility(page, True)
                expect(page.get_by_text(owner_name, exact=True)).not_to_be_visible()
                expect(search).not_to_be_visible()
                visibility(page, False)
                expect(search).to_have_value('可选')
                expect(checkbox(page, '选择清单：可选清单')).to_be_checked()
                owner.set_offline(True)
                expect(page.get_by_text(owner_name, exact=True)).not_to_be_visible()
                expect(search).not_to_be_visible()
                owner.set_offline(False)
                expect(search).to_have_value('可选')
                expect(checkbox(page, '选择清单：可选清单')).to_be_checked()
                open_accounts(page)
                passed('background and browser offline immediately conceal private account/source draft; foreground/online recheck identity before restoring same draft')

                control['discoveryError'] = provider_error('合成来源读取暂时失败', 502)
                button(page, '选择日历与清单').first.click()
                expect(page.locator('body')).to_contain_text('合成来源读取暂时失败')
                expect(checkbox(page, '选择日历：私人日历')).to_have_count(0)
                control['discoveryError'] = None
                open_accounts(page)
                open_editor(page)
                expect(checkbox(page, '选择清单：可选清单')).to_be_checked()
                control['omitSources'] = {'list-2'}
                button(page, '重新读取来源').click()
                expect(page.locator('body')).to_contain_text('本次未发现，已保留')
                expect(checkbox(page, '选择清单：可选清单')).to_be_checked()
                assert saved(owner) == {('tasks', 'list-2'): ('shared', False)}
                control['omitSources'] = set()
                button(page, '重新读取来源').click()
                expect(page.locator('body')).not_to_contain_text('本次未发现，已保留')
                expect(checkbox(page, '选择清单：可选清单')).to_be_checked()
                open_accounts(page)
                write(owner, 'POST', source_path, {'selectionVersion': account(owner)['selectionVersion'],
                    'sources': [{'kind': 'tasks', 'remoteId': 'list-2', 'owner': 'shared', 'primary': True}]})
                open_accounts(page)
                control['discoveryError'] = provider_error('合成授权需要重新确认', 401, reauth=True)
                button(page, '选择日历与清单').first.click()
                expect(page.locator('body')).to_contain_text(re.compile('重新.*授权|重新.*绑定|重新.*连接'))
                assert account(owner)['needsReauth']
                assert account(owner)['sources'][0]['primary']
                before_stop_discovery = control['discoveries']
                button(page, '停止日历与清单同步').click()
                stop_consent = checkbox(page, '我确认停止此账户的日历与清单同步')
                stop_consent.focus()
                stop_consent.press('Space')
                expect(stop_consent).to_be_checked()
                button(page, '查看变更').click()
                expect(page.get_by_text('停止日历与清单同步？', exact=True)).to_be_visible()
                button(page, '确认停止').click()
                expect(button(page, '选择日历与清单').first).to_be_visible()
                assert account(owner)['needsReauth'] and account(owner)['sources'] == []
                assert control['discoveries'] == before_stop_discovery
                assert source_posts()[-1]['body']['sources'] == [] and source_posts()[-1]['body']['selectionVersion']
                assert get(owner, '/api/state')['sync']['primaryTaskSource'] is None
                passed('expired account can explicitly stop with CAS empty selection and no provider discovery; binding remains while selected sources and primary are released')
                control['discoveryError'] = None
                with engine.db() as con:
                    con.execute('UPDATE cloud_accounts SET needs_reauth=0 WHERE id=?', (aid,))
                write(owner, 'POST', source_path, {'selectionVersion': account(owner)['selectionVersion'],
                    'sources': [{'kind': 'tasks', 'remoteId': 'list-2', 'owner': 'shared', 'primary': False}]})
                fixture.due(engine)
                engine.tick()
                open_accounts(page)
                passed('provider failure invents no sources, omitted selected source is retained until explicit removal, and persisted reauthorization error shows a recovery action')

                for width in (320, 390, 1040, 1440):
                    page.set_viewport_size({'width': width, 'height': 900 if width >= 1000 else 844})
                    open_accounts(page)
                    assert_layout(page, width, 'accounts-overview')
                    open_editor(page)
                    assert_layout(page, width, 'accounts-sources')
                    checkbox(page, '选择日历：私人日历').click()
                    review_save(page)
                    assert_layout(page, width, 'accounts-review')
                    open_accounts(page)
                    button(page, '断开绑定').first.click()
                    expect(button(page, '确认断开')).to_be_enabled()
                    assert_layout(page, width, 'accounts-disconnect')
                    passed(f'{width}px actual account overview/source selection/review/disconnect fit viewport')

                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 900 if width >= 1000 else 844})
                    page.goto(base + '/app')
                    expect(page.get_by_role('heading', name=re.compile('欢迎回家$'))).to_be_visible()
                    expect(page.get_by_text('合成本地待办保留', exact=True)).to_be_visible()
                    assert_layout(page, width, 'home-overview')

                open_accounts(page)
                remote.records[('microsoft', 'list-2')] = {'u': {'id': 'u', 'version': 'v1', 'data':
                    {'title': '合成待移除镜像', 'done': False, 'note': '', 'due': '', 'tripId': ''}}}
                fixture.due(engine)
                engine.tick()
                assert any(item['title'] == '合成待移除镜像' for item in get(owner, '/api/state')['tasks'])
                remote_before = json.dumps(list(remote.records.items()), sort_keys=True)
                button(page, '断开绑定').first.click()
                assert account(owner)['id'] == aid
                disconnected = {}

                def drop_disconnect(handler):
                    if handler.request.method == 'DELETE' and not disconnected:
                        response = handler.fetch()
                        assert response.status == 200
                        disconnected['status'] = response.status
                        handler.abort('failed')
                    else:
                        handler.continue_()

                page.route('**/api/accounts/' + aid, drop_disconnect)
                button(page, '确认断开').click()
                expect(page.get_by_text(owner_name, exact=True)).to_have_count(0)
                page.unroute('**/api/accounts/' + aid, drop_disconnect)
                assert disconnected and len([r for r in requests if r['method'] == 'DELETE' and r['path'] == '/api/accounts/' + aid]) == 1
                assert get(owner, '/api/accounts')['accounts'] == []
                assert {item['title'] for item in get(owner, '/api/state')['tasks']} == {'合成本地待办保留'}
                assert json.dumps(list(remote.records.items()), sort_keys=True) == remote_before
                assert len(get(partner, '/api/accounts')['accounts']) == 1
                with closing(sqlite3.connect(folder / 'data' / 'household.sqlite3')) as con:
                    assert con.execute('PRAGMA foreign_key_check').fetchall() == []
                    assert con.execute('SELECT count(*) FROM cloud_sources WHERE account_id=?', (aid,)).fetchone()[0] == 0
                report['droppedDisconnect'] = {'realServerCommit': True, 'status': disconnected['status'], 'deleteCount': 1}
                passed('explicit disconnect with lost committed response reads back without repeat; owner mirrors removed while manual task, partner binding and provider originals remain')

                # Restore a synthetic account through real OAuth routes for late
                # response/session checks; never navigate to an external provider.
                remote.identities['owner-final'] = {'subject': 'owner-final', 'name': '合成迟到账户', 'email': 'final@example.test'}
                authorization = write(owner, 'POST', '/api/accounts/bind', {'provider': 'microsoft'})
                state = parse_qs(urlsplit(authorization['url']).query)['state'][0]
                callback = owner.request.get(base + '/auth/microsoft/callback?' + urlencode({'state': state, 'code': 'owner-final'}), max_redirects=0)
                assert callback.status == 302 and callback.headers['location'].endswith('/?auth=connected')
                new_aid = get(owner, '/api/accounts')['accounts'][0]['id']
                with engine.db() as con:
                    con.execute('UPDATE cloud_accounts SET name=? WHERE id=?', ('合成迟到账户', new_aid))
                open_accounts(page)
                expect(page.get_by_text('合成迟到账户', exact=True)).to_be_visible()
                held = []
                hold = [True]

                def hold_accounts(handler):
                    if hold[0]:
                        held.append((handler, handler.fetch()))
                    else:
                        handler.continue_()

                page.route('**/api/accounts', hold_accounts)
                for _ in range(130):
                    if held:
                        break
                    page.wait_for_timeout(150)
                assert held
                visibility(page, True)
                write(owner, 'POST', '/api/logout', {})
                login(owner, 2)
                hold[0] = False
                for handler, response in held:
                    handler.fulfill(response=response)
                page.unroute('**/api/accounts', hold_accounts)
                visibility(page, False)
                expect(page.get_by_text('合成迟到账户', exact=True)).to_have_count(0)
                open_accounts(page)
                expect(page.get_by_text(partner_name, exact=True)).to_be_visible()
                expect(page.get_by_text('合成迟到账户', exact=True)).to_have_count(0)
                passed('held genuine owner account response cannot repaint private data or reinstall old session after logout/member switch')

                write(owner, 'POST', '/api/logout', {})
                login(owner, 1)
                invitation = write(owner, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
                created = write(owner, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成账户第二家庭',
                    'slug': 'expo-accounts-two', 'MEMBER1_PASSWORD': 'testing-password-one', 'MEMBER2_PASSWORD': 'testing-password-two'}, 201)
                child = context()
                child_page = child.new_page()
                child_page.goto(base + created['entry'])
                login(child)
                open_accounts(child_page)
                assert get(child, '/api/accounts')['accounts'] == []
                assert child.request.get(base + '/api/accounts/' + new_aid + '/sources').status == 404
                expect(child_page.locator('body')).not_to_contain_text('合成迟到账户')
                expect(child_page.locator('body')).not_to_contain_text(partner_name)

                open_accounts(page)
                expect(page.get_by_text('合成迟到账户', exact=True)).to_be_visible()
                held.clear()
                hold[0] = True
                page.route('**/api/accounts', hold_accounts)
                for _ in range(130):
                    if held:
                        break
                    page.wait_for_timeout(150)
                assert held
                visibility(page, True)
                switch = owner.request.get(base + created['entry'])
                assert switch.status == 200
                login(owner)
                assert get(owner, '/api/me')['user']['householdId'] != 'default'
                hold[0] = False
                for handler, response in held:
                    handler.fulfill(response=response)
                page.unroute('**/api/accounts', hold_accounts)
                visibility(page, False)
                expect(page.get_by_text('合成迟到账户', exact=True)).to_have_count(0)
                open_accounts(page)
                assert get(owner, '/api/accounts')['accounts'] == []
                expect(page.locator('body')).not_to_contain_text('合成迟到账户')
                assert owner.request.get(base + '/space/home').status == 200
                login(owner)
                assert get(owner, '/api/me')['user']['householdId'] == 'default'
                passed('same member ID in another real household cannot receive held prior-household account response; returning requires a fresh household session')

                tv = context()
                pairing = tv.request.post(base + '/api/pair/start', data={}).json()
                write(owner, 'POST', '/api/pair/approve', {'code': pairing['code'], 'name': '合成账户电视'})
                assert tv.request.post(base + '/api/pair/poll', data={'secret': pairing['secret']}).json()['approved']
                assert get(tv, '/api/me')['user']['role'] == 'tv'
                assert tv.request.get(base + '/api/accounts').status == 403
                tv_page = tv.new_page()
                tv_reads = []
                tv_page.on('request', lambda request: tv_reads.append(urlsplit(request.url).path))
                tv_page.goto(base + '/app/connections')
                tv_page.wait_for_load_state('networkidle')
                assert not any(path == '/api/accounts' or path.startswith('/api/accounts/') for path in tv_reads)
                passed('real second-household session cannot read first household account IDs; paired TV is server-denied and makes no private account reads')
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
    finally:
        report['sourceHashesAfter'] = hashes()
        report['bundleHashesAfter'] = bundle_hashes()
        report['sourceUnchanged'] = report['sourceHashesBefore'] == report['sourceHashesAfter']
        report['bundleUnchanged'] = report['bundleHashesBefore'] == report['bundleHashesAfter']
        report['passed'] = report['passed'] and report['sourceUnchanged'] and report['bundleUnchanged']
        (out / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'report': str(out / 'result.json')}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
