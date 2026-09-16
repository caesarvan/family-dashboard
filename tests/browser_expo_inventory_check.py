"""Actual frozen Expo export, Flask/SQLite and Edge inventory workflow review.

No replacement success responses. Only one real committed HTTP response is
deliberately dropped to exercise the immutable operation receipt recovery.
Synthetic data and temporary databases only; external network is denied.
"""
import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

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
    assert (bundle / 'index.html').is_file()
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=root, text=True).strip(), 'Source must be frozen'
    names = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
    hashes = lambda: {name: sha(root / name) for name in names}
    bundle_hashes = lambda: {p.relative_to(bundle).as_posix(): sha(p) for p in bundle.rglob('*') if p.is_file()}
    assert bundle_hashes() == evidence['files'], 'Export bytes must match exact build evidence'
    assert all(sha(root / name) == digest for name, digest in evidence['inputFiles'].items()), 'Build inputs changed'
    out = Path(__file__).resolve().parents[1] / 'test-results' / ('expo-inventory-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed-harness.py')
    report = dict(passed=False, checks=[], pageErrors=[], externalRequests=[], httpErrors=[], screenshots=[],
                  head=head, tree=evidence['sourceTree'], buildEvidenceSha256=sha(evidence_path),
                  harnessSha256=sha(out / 'executed-harness.py'), sourceHashesBefore=hashes(), bundleHashesBefore=bundle_hashes(),
                  scope='Real frozen Expo bundle, factory, member cookies, CSRF, household routing and SQLite; synthetic input only. One committed response deliberately dropped.', productionWrites=0)
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
            folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='expo-inventory-')))
            sys.path.insert(0, str(root))
            source = importlib.import_module('app')
            shutil.copytree(root / 'static', folder / 'static', ignore=shutil.ignore_patterns('experience'))
            shutil.copytree(bundle, folder / 'static' / 'experience')
            lifecycle.enter_context(patch.object(source, 'ROOT', folder))
            server = make_server('127.0.0.1', 0, None, threaded=True, request_handler=Quiet, ssl_context='adhoc')
            base = 'https://127.0.0.1:' + str(server.server_port)
            config = dict(TESTING=True, DATA_DIR=str(folder / 'data'), SECRET_KEY='synthetic-expo-inventory-review', SESSION_COOKIE_SECURE=True,
                          PUBLIC_ORIGIN=base, MEMBER1_PASSWORD='synthetic-owner-password', MEMBER2_PASSWORD='synthetic-partner-password',
                          GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='', MICROSOFT_CLIENT_ID='', MICROSOFT_CLIENT_SECRET='',
                          ASSISTANT_PROVIDER='local', NVIDIA_API_KEY='', NVIDIA_MODEL='', OPENAI_API_KEY='', OPENAI_MODEL='')
            application = source.create_app(config)
            assert 'inventory' in application.extensions, 'Real factory registration required'
            server.app = application
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

                def capture_failure():
                    if not report['passed'] and page is not None and not page.is_closed():
                        try:
                            page.screenshot(path=str(out / 'failure.png'), full_page=True)
                            (out / 'failure-aria.txt').write_text(page.locator('body').aria_snapshot(), encoding='utf-8')
                        except Exception:
                            pass

                browsers.callback(capture_failure)

                def context():
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
                    return ctx

                def headers(ctx):
                    response = ctx.request.get(base + '/api/me')
                    assert response.status == 200
                    return {'X-CSRF-Token': response.json()['csrf'], 'Origin': base}

                def login(ctx, number=1):
                    response = ctx.request.post(base + '/api/login', data={'username': f'member{number}', 'password': config[f'MEMBER{number}_PASSWORD']})
                    assert response.status == 200, response.text()

                def get(ctx, path):
                    response = ctx.request.get(base + path)
                    assert response.status == 200, response.text()
                    return response.json()

                def write(ctx, method, path, body, status=200):
                    response = ctx.request.fetch(base + path, method=method, data=body, headers=headers(ctx))
                    assert response.status == status, response.text()
                    return response.json()

                def button(p, name):
                    return p.get_by_role('button', name=name, exact=True)

                def fill(p, name, value):
                    p.get_by_role('textbox', name=name, exact=True).fill(str(value))

                def open_inventory(p):
                    p.goto(base + '/app/inventory')
                    expect(button(p, '新增物品')).to_be_enabled(timeout=15000)

                def open_item(p, title):
                    button(p, '查看物品 ' + title).click()
                    expect(button(p, '添加采购批次')).to_be_enabled()

                def open_batch(p, batch_id):
                    button(p, '打开批次 ' + batch_id).click()
                    expect(button(p, '收货')).to_be_enabled()

                def move(p, kind, qty, *, saved=True):
                    if kind == 'receive':
                        button(p, '收货').click()
                    else:
                        button(p, '更多实物操作').click()
                        button(p, {'consume': '记录使用', 'return': '记录退回', 'dispose': '记录报损'}[kind]).click()
                    fill(p, '本次数量', qty)
                    fill(p, '操作原因', '合成已核对实物动作')
                    p.get_by_role('checkbox', name='我已核对实际物品和数量', exact=True).check()
                    button(p, '确认实物变动').click()
                    if saved:
                        expect(button(p, '收货')).to_be_enabled()

                def assert_layout(p, width, name):
                    p.evaluate('() => document.fonts.ready')
                    metrics = p.evaluate('''() => ({width:innerWidth, scroll:document.documentElement.scrollWidth,
                      clipped:[...document.querySelectorAll('input,button,[role="button"]')].filter(e=>{const r=e.getBoundingClientRect();
                       const s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&r.right>innerWidth+2&&r.left<innerWidth;})
                       .map(e=>({label:e.getAttribute('aria-label')||e.innerText,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})''')
                    assert metrics['scroll'] <= width + 2, metrics
                    assert not metrics['clipped'], metrics
                    filename = f'{name}-{width}.png'
                    p.screenshot(path=str(out / filename), full_page=True)
                    report['screenshots'].append(filename)

                owner = context()
                login(owner)
                page = owner.new_page()
                open_inventory(page)
                partner = context()
                login(partner, 2)
                partner_page = partner.new_page()
                open_inventory(partner_page)
                title = '合成可充电电池与旅行应急照明设备备用品'
                button(page, '新增物品').click()
                fill(page, '物品名称', title)
                fill(page, '计量单位', '节')
                fill(page, '规格', 'AA 可充电型')
                fill(page, '存放位置', '合成家庭玄关收纳柜第二层靠左备用品抽屉')
                fill(page, '补货提醒数量', 3)
                expect(page.get_by_role('radio', name='仅本人可见', exact=True)).to_be_checked()
                button(page, '保存物品').click()
                expect(button(page, '编辑物品')).to_be_enabled()
                item = get(owner, '/api/inventory/items')['items'][0]
                uid = item['id']
                assert item['visibility'] == 'private' and item['onHandQty'] == 0
                assert get(partner, '/api/inventory/items')['total'] == 0
                assert partner.request.get(base + '/api/inventory/items/' + uid).status == 404
                passed('real Expo mobile UI creates a private item; partner cannot list or read it')

                button(page, '添加采购批次').click()
                fill(page, '批次数量', 8)
                fill(page, '批次备注', '合成八节分批配送')
                page.get_by_role('radio', name='运输中', exact=True).click()
                button(page, '保存批次').click()
                expect(button(page, '收货')).to_be_enabled()
                batch = get(owner, '/api/inventory/items/' + uid + '/acquisitions')['items'][0]
                bid = batch['id']
                movement_path = '/api/inventory/acquisitions/' + bid + '/movements'
                move(page, 'receive', 3)
                current = get(owner, '/api/inventory/items/' + uid)['item']
                assert (current['onHandQty'], current['inTransitQty']) == (3, 5)
                passed('purchase batch starts without stock; explicit first receipt persists three units')

                open_inventory(page)
                open_item(page, title)
                button(page, '编辑物品').click()
                page.get_by_role('radio', name='与家庭共享', exact=True).click()
                button(page, '保存物品').click()
                expect(button(page, '编辑物品')).to_be_enabled()
                open_inventory(partner_page)
                open_item(partner_page, title)
                expect(button(partner_page, '编辑物品')).to_have_count(0)
                open_batch(partner_page, bid)
                move(partner_page, 'receive', 2)
                shared_current = get(partner, '/api/inventory/items/' + uid)['item']
                assert (shared_current['onHandQty'], shared_current['inTransitQty']) == (5, 3)
                denied = partner.request.patch(base + '/api/inventory/items/' + uid, headers=headers(partner),
                    data={'requestId': secrets.token_hex(16), 'revision': shared_current['revision'], 'patch': {'visibility': 'private'}})
                assert denied.status == 403
                passed('explicit sharing allows partner receipt while owner ACL controls stay unavailable and server rejects changes')

                open_inventory(page)
                open_item(page, title)
                open_batch(page, bid)
                move(page, 'consume', 1)
                move(page, 'return', 1)
                current = get(owner, '/api/inventory/items/' + uid)['item']
                assert (current['onHandQty'], current['inTransitQty']) == (3, 3)
                returned = next(x for x in get(owner, movement_path)['items'] if x['kind'] == 'return')
                button(page, '查看变动历史').click()
                button(page, '撤销这条记录 ' + returned['id']).click()
                fill(page, '操作原因', '合成原退回尚未实际发生')
                page.get_by_role('checkbox', name='我已核对实际物品和数量', exact=True).check()
                button(page, '确认撤销原记录').click()
                expect(button(page, '收货')).to_be_enabled()
                assert get(owner, '/api/inventory/items/' + uid)['item']['onHandQty'] == 4
                history = get(owner, movement_path)
                assert history['total'] == 5 and any(x['kind'] == 'reverse' and x['reversesId'] == returned['id'] for x in history['items'])
                passed('use and return reduce stock; explicit historical reversal preserves original event and restores one unit')

                dropped = {}
                pattern = '**/api/inventory/acquisitions/*/movements'

                def drop_response(handler):
                    if handler.request.method != 'POST' or dropped:
                        handler.continue_()
                        return
                    response = handler.fetch()
                    assert response.status == 200, response.text()
                    dropped.update(requestId=handler.request.post_data_json['requestId'], body=handler.request.post_data_json,
                                   result=response.json(), status=response.status)
                    handler.abort('failed')

                page.route(pattern, drop_response)
                move(page, 'receive', 3, saved=False)
                expect(button(page, '核对并重试本次操作')).to_be_enabled()
                assert dropped and get(owner, movement_path)['total'] == 6
                button(page, '核对并重试本次操作').click()
                expect(button(page, '收货')).to_be_enabled()
                page.unroute(pattern, drop_response)
                assert get(owner, movement_path)['total'] == 6
                receipt = get(owner, '/api/inventory/operations/' + dropped['requestId'])
                assert receipt['operation']['replayed'] and receipt['item']['onHandQty'] == 7
                db_path = folder / 'data' / 'household.sqlite3'
                with closing(sqlite3.connect(db_path)) as con:
                    assert con.execute('SELECT count(*) FROM inventory_movements WHERE request_id=?', (dropped['requestId'],)).fetchone()[0] == 1
                    assert con.execute('SELECT count(*) FROM inventory_operations WHERE request_id=?', (dropped['requestId'],)).fetchone()[0] == 1
                report['droppedResponse'] = {'status': dropped['status'], 'requestId': dropped['requestId'], 'realServerCommit': True}
                passed('actual committed response loss recovers original receipt without duplicate stock or SQL movements')

                open_inventory(page)
                open_item(page, title)
                button(page, '编辑物品').click()
                draft_location = '冲突后保留的合成位置草稿'
                fill(page, '存放位置', draft_location)
                snapshot = get(owner, '/api/inventory/items/' + uid)['item']
                write(owner, 'PATCH', '/api/inventory/items/' + uid, {'requestId': secrets.token_hex(16), 'revision': snapshot['revision'], 'patch': {'location': '另一设备已保存位置'}})
                with page.expect_response(lambda response: urlsplit(response.url).path == '/api/inventory/items/' + uid and response.request.method == 'PATCH') as conflict:
                    button(page, '保存物品').click()
                assert conflict.value.status == 409
                expect(button(page, '重新核对并修改草稿')).to_be_enabled()
                expect(page.get_by_role('textbox', name='存放位置', exact=True)).to_have_value(draft_location)
                assert get(owner, '/api/inventory/items/' + uid)['item']['location'] == '另一设备已保存位置'
                button(page, '重新核对并修改草稿').click()
                expect(button(page, '保存物品')).to_be_enabled()
                expect(page.get_by_role('textbox', name='存放位置', exact=True)).to_have_value(draft_location)
                button(page, '保存物品').click()
                expect(button(page, '编辑物品')).to_be_enabled()
                assert get(owner, '/api/inventory/items/' + uid)['item']['location'] == draft_location
                passed('real revision conflict retains draft and requires explicit current-state review before resubmission')

                page.goto(base + '/app/assistant')
                fill(page, '告诉助理你的需求', '搜索：可充电电池')
                button(page, '整理并预览').click()
                expect(button(page, '查看物品 ' + title)).to_be_enabled()
                expect(page.get_by_text('现有 7 节', exact=False)).to_be_visible()
                with page.expect_response(lambda response: '/api/inventory/items/' + uid in response.url and '/acquisitions' not in response.url and response.request.method == 'GET') as detail:
                    button(page, '查看物品 ' + title).click()
                assert detail.value.status == 200
                expect(button(page, '编辑物品')).to_be_enabled()
                expect(page.get_by_text(title, exact=True)).to_be_visible()
                passed('local assistant inventory search shows current quantity and opens matching detail through a fresh authorized GET')

                before_restart = get(owner, '/api/inventory/items/' + uid)['item']
                page.reload()
                expect(button(page, '刷新物品')).to_be_enabled()
                server.app = source.create_app(config)
                open_inventory(page)
                assert get(owner, '/api/inventory/items/' + uid)['item'] == before_restart
                assert get(owner, movement_path)['total'] == 6
                with closing(sqlite3.connect(db_path)) as con:
                    assert con.execute('PRAGMA foreign_key_check').fetchall() == []
                    assert con.execute('SELECT count(*) FROM hub_transactions').fetchone()[0] == 0
                passed('page refresh and actual factory restart retain SQLite quantities and history without creating financial spending')

                open_item(page, title)
                button(page, '编辑物品').click()
                page.get_by_role('radio', name='仅本人可见', exact=True).click()
                button(page, '保存物品').click()
                expect(button(page, '编辑物品')).to_be_enabled()
                open_inventory(partner_page)
                expect(button(partner_page, '查看物品 ' + title)).to_have_count(0)
                for path in ['/api/inventory/items/' + uid, '/api/inventory/items/' + uid + '/acquisitions', '/api/inventory/acquisitions/' + bid, movement_path]:
                    assert partner.request.get(base + path).status == 404, path
                assert get(partner, '/api/assistant/search?q=可充电电池')['total'] == 0
                passed('privacy withdrawal removes partner UI, assistant matches and every later inventory detail read')

                # Use shared data for the cross-family checks so privacy filtering
                # cannot mask an incorrectly selected household database.
                snapshot = get(owner, '/api/inventory/items/' + uid)['item']
                write(owner, 'PATCH', '/api/inventory/items/' + uid, {'requestId': secrets.token_hex(16), 'revision': snapshot['revision'], 'patch': {'visibility': 'shared'}})

                invitation = write(owner, 'POST', '/api/spaces/invitations', {}, 201)['invitation']
                created = write(owner, 'POST', '/api/spaces/redeem', {'invitation': invitation, 'name': '合成库存第二家庭', 'slug': 'expo-inventory-two',
                    'MEMBER1_PASSWORD': config['MEMBER1_PASSWORD'], 'MEMBER2_PASSWORD': config['MEMBER2_PASSWORD']}, 201)
                child = context()
                child_page = child.new_page()
                child_page.goto(base + created['entry'])
                login(child)
                open_inventory(child_page)
                assert get(child, '/api/inventory/items')['total'] == 0
                assert child.request.get(base + '/api/inventory/items/' + uid).status == 404
                assert child.request.get(base + '/api/inventory/operations/' + dropped['requestId']).status == 404
                assert get(child, '/api/assistant/search?q=可充电电池')['total'] == 0
                second = write(child, 'POST', '/api/inventory/items', {'requestId': secrets.token_hex(16), 'data': {'title': '合成另一户独有物品', 'unit': '个', 'visibility': 'shared'}}, 201)['item']
                assert owner.request.get(base + '/api/inventory/items/' + second['id']).status == 404
                passed('real invitation-created second household isolates item IDs, receipts, lists and assistant matches in both directions')

                for width in (320, 390, 1040, 1440):
                    page.set_viewport_size({'width': width, 'height': 900 if width >= 1000 else 844})
                    open_inventory(page)
                    assert_layout(page, width, 'inventory-list')
                    open_item(page, title)
                    assert_layout(page, width, 'inventory-detail')
                    open_batch(page, bid)
                    assert_layout(page, width, 'inventory-batch')
                    if width >= 1040:
                        button(page, '更多功能').click()
                        expect(page.get_by_role('menuitem', name='家庭物品', exact=True)).to_be_visible()
                        page.get_by_role('menuitem', name='家庭物品', exact=True).click()
                        expect(button(page, '新增物品')).to_be_enabled()
                    else:
                        button(page, '返回更多功能').click()
                        expect(page.get_by_text('家庭物品', exact=True)).to_be_visible()
                        page.get_by_text('家庭物品', exact=True).click()
                        expect(button(page, '新增物品')).to_be_enabled()
                    passed(f'{width}px list/detail/batch fit viewport and the navigation menu opens native inventory')
                assert not report['pageErrors'] and not report['externalRequests']
                report['passed'] = True
    except Exception:
        report['failure'] = traceback.format_exc()
        print(report['failure'], flush=True)
        # Browser may already be disposed by ExitStack; never hide original failure.
        if page is not None:
            try:
                page.screenshot(path=str(out / 'failure.png'), full_page=True)
            except Exception:
                pass
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
