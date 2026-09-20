"""Real local video flows. Only Google's transport is synthetic; no business DTO mocks."""
from contextlib import ExitStack
from io import BytesIO
import importlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import expect
from werkzeug.serving import ThreadedWSGIServer
from browser_expo_finance_check import button, sha
from browser_expo_trip_recap_check import Run as MediaRun
from scripts.check_expo_calendar_conflicts_browser import layout_metrics

HARNESS = 'tests/browser_expo_media_video_check.py'
CASES = ('member_import_play', 'television_mixed_controls', 'revocation_offline_identity')
CASE_SCREENSHOTS = dict(zip(CASES, (2, 2, 2)))
TEMP_CONSENT = '允许临时处理本次选择，供我预览确认；未保存的内容最迟 24 小时后清理。'
SAVE_CONSENT = '同意将勾选照片或视频的展示副本持久保存在私密相册中。之后另行设置家庭共享和电视展示。'

# Observation only: never alter currentTime, duration, ended, visibility, media
# methods, or playback clock. Keep references to detached elements for cleanup.
OBSERVE = """(() => {
  window.__mediaEvidence = {ended: [], revoked: [], nodes: []};
  const revoke = URL.revokeObjectURL.bind(URL);
  URL.revokeObjectURL = url => { window.__mediaEvidence.revoked.push(url); return revoke(url); };
  document.addEventListener('ended', e => {
    if (e.target instanceof HTMLVideoElement) window.__mediaEvidence.ended.push({
      src:e.target.currentSrc, time:e.target.currentTime, duration:e.target.duration,
      ended:e.target.ended, wall:performance.now()});
  }, true);
})();"""


def fixture_command(ffmpeg, path):
    return [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24:duration=8',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
            '-c:v', 'libx264', '-threads:v', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
            '-metadata', 'comment=SYNTHETIC-BROWSER-VIDEO', '-movflags', '+faststart', str(path)]


class Run(MediaRun):
    def __init__(self, root, bundle, folder, report, out, lifecycle, tools):
        assert ThreadedWSGIServer.block_on_close is True
        lifecycle.enter_context(patch.object(ThreadedWSGIServer, 'daemon_threads', False))
        super().__init__(root, bundle, folder, report, out, lifecycle)
        self.tools = tools
        self.picker = importlib.import_module('test_google_photos_picker')
        self.worker_module = importlib.import_module('media_import_worker')
        self.picker_module = importlib.import_module('google_photos_picker')
        names = ('app', 'household_media', 'media_videos', 'media_video_storage', 'media_crypto',
                 'media_import_worker', 'google_photos_picker', 'media_playback', 'media_playback_progress',
                 'home_assistant', 'member_sessions', 'membership_storage')
        for name in names:
            actual = Path(importlib.import_module(name).__file__).resolve()
            assert actual == (root / (name + '.py')).resolve()
            report.setdefault('fixtureHashes', {})[name + '.py'] = sha(actual)
        for name in ('test_google_photos_picker', 'browser_expo_media_video_check'):
            actual = Path(sys.modules[name].__file__).resolve()
            assert actual == (root / 'tests' / (name + '.py')).resolve()
            report['fixtureHashes']['tests/' + name + '.py'] = sha(actual)
        helper = 'scripts/check_expo_calendar_conflicts_browser.py'
        report['fixtureHashes'][helper] = sha(root / helper)
        def forbidden(*_args, **_kwargs):
            report['unexpectedProviderAttempts'].append('external provider/model')
            raise AssertionError('External provider/model forbidden')
        lifecycle.enter_context(patch.object(self.picker_module, '_transport', forbidden))
        for name in ('_model_json', 'model_plan', 'model_journey_brief'):
            lifecycle.enter_context(patch.object(sys.modules['home_assistant'], name, forbidden))
        lifecycle.enter_context(patch.object(self.engine.accounts, 'active_provider', forbidden))
        path = folder / 'synthetic.mp4'
        command = fixture_command(tools.ffmpeg, path)
        started = time.monotonic()
        result = subprocess.run(command, capture_output=True, timeout=60)
        (out / 'ffmpeg.stdout').write_bytes(result.stdout)
        (out / 'ffmpeg.stderr').write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr[-2000:]
        self.clip = path.read_bytes()
        assert 0 < len(self.clip) < 4 * 1024 * 1024
        self.record('synthetic-source', dict(argv=command, exitCode=result.returncode,
            seconds=time.monotonic() - started, sha256=sha(path), bytes=len(self.clip)), 'databaseEvidence')

    def context(self, browser, member=1):
        ctx = super().context(browser, member)
        ctx.add_init_script(OBSERVE)
        return ctx

    def record(self, name, value, group='httpEvidence'):
        target = self.out / (name + '.json')
        with target.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
        self.report[group].append({'path': str(target.relative_to(self.out.parent)), 'sha256': sha(target)})

    def capture(self, page, name, focus=None):
        if focus is not None:
            expect(focus).to_be_visible(); focus.scroll_into_view_if_needed()
        page.evaluate('document.fonts.ready')
        page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        metrics = layout_metrics(page)
        assert metrics['viewport'] in (390, 1920), metrics
        assert metrics['bodyScroll'] <= metrics['viewport'] + 2 and metrics['rootScroll'] <= metrics['viewport'] + 2, metrics
        assert not metrics['clipped'], metrics
        path = self.out / (name + '.png'); page.screenshot(path=str(path), full_page=True)
        self.report['screenshots'].append({'path': str(path.relative_to(self.out.parent)), 'sha256': sha(path), 'metrics': metrics})

    def response_action(self, page, path, method, action, status=200, name=None):
        with page.expect_response(lambda r: r.url == self.base + path and r.request.method == method) as awaited:
            action()
        response = awaited.value
        assert response.status == status and response.finished() is None, (path, response.status)
        value = response.json()
        self.last_action_request = response.request.post_data_json
        self.record(name or (str(len(self.report['httpEvidence'])) + '-action'),
                    dict(method=method, path=path, status=response.status, request=response.request.post_data_json, response=value))
        return value

    def media(self, ctx, uid):
        return self.get(ctx, '/api/media/items/' + uid)['item']

    def create_video(self, ctx):
        return self.write(ctx, 'POST', '/api/media/imports', dict(requestId=secrets.token_hex(16),
            accountId=self.synthetic_accounts[1], consentVersion='media-v1', allowTemporaryProcessing=True), 202)['import']

    def stage_video(self, ctx, imported):
        remote = self.picker.item('synthetic-video-' + secrets.token_hex(8), 'VIDEO')
        transport = self.picker.Transport(self.picker.session(), self.picker.session(), {'mediaItems': [remote]},
            self.picker.session(), {'mediaItems': [remote]}, self.picker.Response(self.clip, mime='video/mp4'),
            self.picker.Response(b'', status=204))
        worker = self.worker_module.MediaImportWorker(self.engine,
            picker_factory=lambda token: self.picker_module.GooglePhotosPicker(token, transport=transport),
            video_tools=self.tools, video_temp_root=self.folder, jitter=lambda: 0)
        assert worker.tick() and worker.tick() and worker.tick()
        detail = self.get(ctx, '/api/media/imports/' + imported['id'])
        assert detail['import']['state'] == 'awaiting_confirmation' and detail['import']['canConfirm']
        assert len(detail['items']) == 1
        value = detail['items'][0]['item']
        assert value['mediaType'] == 'video' and value['visibility'] == 'private'
        assert 7750 <= value['durationMs'] <= 8500 and value['hasAudio'] is True
        assert sum(c['method'] == 'POST' for c in transport.calls) == 1
        assert any(c['url'].endswith('=dv') for c in transport.calls)
        self.record('worker-' + imported['id'], {'importId': imported['id'], 'itemId': value['id'],
            'revision': value['revision'], 'durationMs': value['durationMs'], 'calls': [
                {'method': c['method'], 'host': urlsplit(c['url']).hostname, 'videoDownload': c['url'].endswith('=dv')}
                for c in transport.calls]}, 'databaseEvidence')
        return detail, worker, transport

    def video(self, ctx):
        detail, worker, transport = self.stage_video(ctx, self.create_video(ctx))
        self.write(ctx, 'POST', '/api/media/imports/' + detail['import']['id'] + '/confirm',
            dict(revision=detail['import']['revision'], confirmRequestId=secrets.token_hex(16),
                 itemIds=[detail['items'][0]['id']], consentVersion='media-v1', persistSelected=True))
        assert worker.tick() and not transport.responses
        return self.media(ctx, detail['items'][0]['id'])

    def photo(self, ctx):
        imported = self.create_video(ctx)
        job = self.engine.claim_next(); assert job['action'] == 'create'
        assert self.engine.complete(job, self.media_fixture.session((None, None, [time.time()], None)))
        selected = self.media_fixture.selected('synthetic-photo-' + secrets.token_hex(8))
        job = self.engine.claim_next(); assert job['action'] == 'list' and self.engine.complete(job, [selected])
        stream = BytesIO(); Image.new('RGB', (320, 180), '#69774a').save(stream, 'PNG')
        jpeg = self.images.sanitize_media_preview(stream.getvalue(), 'image/png')
        job = self.engine.claim_next(); assert job['action'] == 'download'
        assert self.engine.complete(job, dict(mediaId=job['media']['id'], manifest=[selected], preview=jpeg))
        detail = self.get(ctx, '/api/media/imports/' + imported['id'])
        self.write(ctx, 'POST', '/api/media/imports/' + imported['id'] + '/confirm', dict(revision=detail['import']['revision'],
            confirmRequestId=secrets.token_hex(16), itemIds=[detail['items'][0]['id']], consentVersion='media-v1', persistSelected=True))
        job = self.engine.claim_next(); assert job['action'] == 'cleanup' and self.engine.complete(job, None)
        return self.media(ctx, detail['items'][0]['id'])

    def pair(self, browser, owner, name):
        tv = self.context(browser, None); self.lifecycle.callback(tv.close)
        response = tv.request.post(self.base + '/api/pair/start', data={}); assert response.status == 200
        pair = response.json()
        self.write(owner, 'POST', '/api/pair/approve', dict(code=pair['code'], name=name))
        assert tv.request.post(self.base + '/api/pair/poll', data={'secret': pair['secret']}).json()['approved']
        assert self.get(tv, '/api/me')['user']['role'] == 'tv'
        return next(d for d in self.get(owner, '/api/devices') if d['name'] == name), tv

    def share(self, ctx, item, visibility='shared'):
        return self.write(ctx, 'PATCH', '/api/media/items/' + item['id'],
            dict(revision=item['revision'], visibility=visibility))['item']

    def grant(self, ctx, item, device):
        self.write(ctx, 'PUT', '/api/media/items/' + item['id'] + '/tv-grants', dict(revision=item['revision'],
            deviceIds=[device['id']], consentVersion='media-v1', allowTvDisplay=True))
        return self.media(ctx, item['id'])

    def open_detail(self, page, item, shared=False):
        page.goto(self.base + '/app/photos')
        expect(page.get_by_role('heading', name='相册', exact=True)).to_be_visible(timeout=15000)
        if shared: button(page, '家人共享').click()
        label = ('查看视频：' if item.get('mediaType') == 'video' else '查看照片：') + (item.get('caption') or '未添加说明')
        page.get_by_label(label, exact=True).click()
        expect(button(page, '播放视频')).to_be_enabled(timeout=15000)

    def play(self, page):
        button(page, '播放视频').click()
        video = page.locator('video[controls]'); expect(video).to_be_visible(timeout=20000)
        # A real user click requested loading; use the actual native play API.
        # No seeking, mocked media properties, autoplay-policy flag or fast clock.
        video.evaluate('(v) => v.play()')
        page.wait_for_function("() => {const v=document.querySelector('video[controls]'); return v && v.videoWidth>0 && v.currentTime>.35 && !v.paused}", timeout=15000)
        return self.remember(video)

    def remember(self, video):
        return video.evaluate("v => {window.__mediaEvidence.nodes.push(v); return {index:window.__mediaEvidence.nodes.length-1, url:v.src, time:v.currentTime, duration:v.duration, width:v.videoWidth, height:v.videoHeight}}")

    def cleaned(self, page, retained):
        page.wait_for_function("r => {const s=window.__mediaEvidence, v=s.nodes[r.index]; return v.paused && !v.getAttribute('src') && s.revoked.includes(r.url)}", arg=retained, timeout=15000)
        assert page.evaluate("async u => {try {await fetch(u); return false} catch {return true}}", retained['url'])

    def proof(self, name):
        with self.engine.transaction() as con:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            value = {'schemaTableCount': len(tables), 'items': [dict(r) for r in con.execute(
                'SELECT id,owner,import_id,state,visibility,revision FROM media_items ORDER BY id')],
                'imports': [dict(r) for r in con.execute('SELECT id,state,revision,confirm_request_id,reserved_bytes FROM media_imports ORDER BY id')],
                'cache': [dict(r) for r in con.execute('SELECT media_id,length(cipher) AS cipherBytes FROM media_video_cache ORDER BY media_id')],
                'grants': [dict(r) for r in con.execute('SELECT media_id,device_id FROM media_tv_grants ORDER BY media_id,device_id')]}
            # Synthetic audit only; deliberately exclude encrypted metadata and credentials.
            value['audit'] = [dict(r) for r in con.execute("SELECT action,target FROM audit WHERE action LIKE 'media_%' ORDER BY rowid")]
        self.record(name, value, 'databaseEvidence')
        return value

    def member_import_play(self, browser):
        with self.flow(browser) as (ctx, page):
            page.goto(self.base + '/app/photos')
            button(page, '选择照片').click()
            expect(button(page, '虚构照片账户')).to_be_visible(timeout=15000)
            page.get_by_role('checkbox', name=TEMP_CONSENT, exact=True).check()
            created = self.response_action(page, '/api/media/imports', 'POST', lambda: button(page, '开始选择照片').click(), 202, 'ui-create')
            detail, worker, transport = self.stage_video(ctx, created['import'])
            button(page, '刷新状态').click()
            expect(page.get_by_label('待保存视频封面', exact=True)).to_be_visible(timeout=15000)
            assert page.locator('video').count() == 0 and button(page, '播放视频').count() == 0
            staged = detail['items'][0]['item']; uid = staged['id']
            assert not any(r['path'] == '/api/media/items/' + uid + '/video' for r in self.requests)
            peer = self.context(browser, 2); self.lifecycle.callback(peer.close)
            _, tv = self.pair(browser, ctx, '未经相册许可的电视')
            self.get(peer, '/api/media/items/' + uid + '/video', 404)
            self.get(tv, '/api/media-tv/items/' + uid + '/video', 404)
            self.capture(page, '390-staged-confirmation', page.get_by_label('待保存视频封面', exact=True))
            keep = page.get_by_role('checkbox', name='保留此视频', exact=True)
            if keep.get_attribute('aria-checked') != 'true': keep.click()
            page.get_by_role('checkbox', name=SAVE_CONSENT, exact=True).check()
            path = '/api/media/imports/' + created['import']['id'] + '/confirm'
            receipt = self.response_action(page, path, 'POST', lambda: button(page, '保存选中的 1 项').click(), name='ui-confirm')
            confirm_request = dict(self.last_action_request)
            assert receipt['itemIds'] == [uid]
            assert worker.tick() and not transport.responses
            item = self.media(ctx, uid)
            assert item['visibility'] == 'private' and item['revision'] == staged['revision'] + 1
            self.get(peer, '/api/media/items/' + uid, 404)
            self.get(peer, item['videoUrl'], 404)
            self.get(tv, '/api/media-tv/items/' + uid + '/video', 404)
            self.open_detail(page, item); retained = self.play(page)
            self.capture(page, '390-real-video-playing', page.locator('video[controls]'))
            self.record('actual-member-play', retained)
            button(page, '停止播放').click(); self.cleaned(page, retained)
            proof = self.proof('confirmed-private-original-id')
            assert len(proof['items']) == len(proof['cache']) == 1 and proof['items'][0]['id'] == uid
            assert len(proof['imports']) == 1 and proof['imports'][0]['confirm_request_id'] == confirm_request['confirmRequestId'] and not proof['grants']
            assert [r['action'] for r in proof['audit']] == ['media_import_start', 'media_import_confirm']
            assert all(r['target'] == created['import']['id'] for r in proof['audit'])
            assert sum(r['method'] == 'POST' and r['path'] == path for r in self.requests) == 1
            self.passed('Member explicitly imports/confirms one real decoded private video, plays advancing media time, and stops/revokes its Blob; partner and ungranted TV are denied')

    def tv_state(self, ctx):
        response = ctx.request.get(self.base + '/api/media-tv/playback', headers={'X-Display-Mode': 'tv'})
        assert response.status == 200
        value = response.json(); assert value['protocol'] == 2
        return value

    def television_mixed_controls(self, browser):
        with self.flow(browser) as (ctx, phone):
            video, photo = self.video(ctx), self.photo(ctx)
            device, tv = self.pair(browser, ctx, '合成客厅电视')
            _, denied = self.pair(browser, ctx, '合成未授权电视')
            video = self.grant(ctx, self.share(ctx, video), device)
            photo = self.grant(ctx, self.share(ctx, photo), device)
            self.get(denied, '/api/media-tv/items/' + video['id'] + '/video', 404)
            self.get(denied, '/api/media-tv/items/' + photo['id'] + '/preview', 404)
            phone.goto(self.base + '/app/devices')
            button(phone, '播放控制：' + device['name']).click()
            phone.get_by_role('textbox', name='照片间隔（秒）', exact=True).fill('5')
            control = '/api/media-playback/devices/' + device['id']
            self.response_action(phone, control, 'PUT', lambda: button(phone, '保存照片间隔').click(), name='phone-interval')
            self.response_action(phone, control, 'PUT', lambda: button(phone, '开始相册播放').click(), name='phone-start')
            if self.tv_state(tv)['item']['id'] != photo['id']:
                self.response_action(phone, control, 'PUT', lambda: button(phone, '下一项').click(), name='phone-select-photo')
            screen = tv.new_page(); screen.set_viewport_size({'width': 1920, 'height': 1080})
            events = []
            def progress(route):
                if route.request.method != 'POST': route.continue_(); return
                response = route.fetch(); value = response.json()
                events.append(dict(request=route.request.post_data_json, status=response.status, response=value))
                route.fulfill(response=response)
            screen.route(self.base + '/api/media-tv/playback/progress', progress)
            screen.goto(self.base + '/tv')
            expect(screen.get_by_test_id('tv-photo-image')).to_be_visible(timeout=20000)
            screen.wait_for_function("() => {const i=document.querySelector('[data-testid=tv-photo-image]'); return i.complete && i.naturalWidth>0}")
            self.capture(screen, '1920-photo-before-video', screen.get_by_test_id('tv-photo-image'))
            screen.wait_for_function("() => {const v=document.querySelector('[data-testid=tv-media-video]'); return v && !v.hidden && v.currentTime>.3 && !v.paused}", timeout=25000)
            retained = self.remember(screen.get_by_test_id('tv-media-video'))
            self.capture(screen, '1920-video-real-play', screen.get_by_test_id('tv-media-video'))
            self.response_action(phone, control, 'PUT', lambda: button(phone, '暂停播放').click(), name='phone-pause')
            screen.wait_for_function("() => document.querySelector('[data-testid=tv-media-video]').paused", timeout=15000)
            paused = screen.get_by_test_id('tv-media-video').evaluate('v => v.currentTime')
            screen.wait_for_timeout(450)
            assert abs(screen.get_by_test_id('tv-media-video').evaluate('v => v.currentTime') - paused) < .08
            assert self.tv_state(tv)['paused'] is True
            self.response_action(phone, control, 'PUT', lambda: button(phone, '继续播放').click(), name='phone-resume')
            screen.wait_for_function("t => {const v=document.querySelector('[data-testid=tv-media-video]'); return !v.paused && v.currentTime>t+.2}", arg=paused, timeout=15000)
            screen.wait_for_function('() => window.__mediaEvidence.ended.some(e => e.ended && e.time>=e.duration-.1)', timeout=20000)
            expect(screen.get_by_test_id('tv-photo-image')).to_be_visible(timeout=15000)
            state = self.tv_state(tv); assert state['item']['id'] == photo['id']
            ended = [e for e in events if e['request']['event'] == 'ended' and e['request']['itemId'] == video['id']]
            assert len(ended) == 1 and ended[0]['status'] == 200
            assert ended[0]['request']['itemRevision'] == video['revision']
            self.response_action(phone, control, 'PUT', lambda: button(phone, '下一项').click(), name='phone-next')
            state = self.tv_state(tv); assert state['item']['id'] == video['id'] and state['progress']['positionMs'] == 0
            screen.wait_for_function("() => {const v=document.querySelector('[data-testid=tv-media-video]'); return !v.hidden && v.currentTime>.2 && !v.paused}", timeout=15000)
            self.record('actual-tv-events', dict(native=screen.evaluate('window.__mediaEvidence.ended'), progress=events, pauseSeconds=paused, first=retained))
            self.proof('mixed-tv-original-records')
            self.passed('One explicitly granted browser TV displays JPEG then real video ended, accepts phone pause/resume/next; a second paired TV remains unauthorized')

    def revocation_offline_identity(self, browser):
        with self.flow(browser) as (ctx, page):
            item = self.video(ctx); self.open_detail(page, item); first = self.play(page)
            ctx.set_offline(True)
            self.cleaned(page, first)
            expect(page.get_by_text('照片内容已隐藏', exact=True)).to_be_visible(timeout=15000)
            self.capture(page, '390-offline-cleared')
            ctx.set_offline(False); self.open_detail(page, item); second = self.play(page)
            self.login(ctx, 2)
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            self.cleaned(page, second)
            expect(page.get_by_test_id('photo-editor')).to_have_count(0, timeout=15000)
            self.get(ctx, '/api/media/items/' + item['id'], 404)
            self.get(ctx, item['videoUrl'], 404)
            owner = self.context(browser, 1); self.lifecycle.callback(owner.close)
            device, tv = self.pair(browser, owner, '将收回的视频电视')
            item = self.grant(owner, self.share(owner, item), device)
            self.open_detail(page, item, shared=True); third = self.play(page)
            state = self.get(owner, '/api/media-playback/devices/' + device['id'])
            self.write(owner, 'PUT', '/api/media-playback/devices/' + device['id'], dict(revision=state['revision'], action='start'))
            screen = tv.new_page(); screen.set_viewport_size({'width': 1920, 'height': 1080}); screen.goto(self.base + '/tv')
            screen.wait_for_function("() => {const v=document.querySelector('[data-testid=tv-media-video]'); return v && !v.hidden && v.currentTime>.2}", timeout=25000)
            television = self.remember(screen.get_by_test_id('tv-media-video'))
            latest = self.media(owner, item['id']); item = self.share(owner, latest, 'private')
            self.cleaned(page, third); self.cleaned(screen, television)
            self.get(ctx, '/api/media/items/' + item['id'], 404)
            self.get(ctx, item['videoUrl'], 404)
            self.get(tv, '/api/media-tv/items/' + item['id'] + '/video', 404)
            assert self.tv_state(tv)['item'] is None
            self.capture(screen, '1920-revoked-cleared')
            proof = self.proof('revoked-private-no-grants')
            assert len(proof['items']) == 1 and proof['items'][0]['id'] == item['id']
            assert proof['items'][0]['visibility'] == 'private' and not proof['grants']
            self.record('cleanup', dict(offline=first, identity=second, partner=third, television=television,
                ownerRevision=item['revision'], memberRevoked=page.evaluate('window.__mediaEvidence.revoked'),
                televisionRevoked=screen.evaluate('window.__mediaEvidence.revoked')))
            self.passed('Offline and actual member-session switch clear private playback; withdrawing shared visibility clears both partner and TV video and revokes all grants')

    @classmethod
    def run_scenarios(cls, root, bundle, report, out, browser, temp_root, tools, cases=CASES):
        for name in cases:
            case_out = out / name; case_out.mkdir()
            folder, before, count = None, len(report['checks']), len(report['screenshots'])
            case = {'name': name, 'passed': False}
            try:
                with ExitStack() as lifecycle:
                    folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='mv-', dir=temp_root)))
                    run = cls(root, bundle, folder, report, case_out, lifecycle, tools)
                    getattr(run, name)(browser)
                assert len(report['checks']) == before + 1 and not folder.exists()
                assert len(report['screenshots']) - count == CASE_SCREENSHOTS[name]
                assert run.server is None and not run.thread.is_alive()
                case.update(passed=True, listenerStopped=True)
            except Exception:
                del report['checks'][before:]
                failure = traceback.format_exc(); (case_out / 'failure.txt').write_text(failure, encoding='utf-8')
                report['scenarioFailures'].append({'scenario': name, 'traceback': failure})
                print('FAIL ' + name + '\n' + failure, flush=True)
            finally:
                case['temporaryFixtureRemoved'] = folder is not None and not folder.exists()
                report['scenarioResults'].append(case)
