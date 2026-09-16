"""Real Edge with a synthetic suggestion HTTP contract; no Google/model access."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
import traceback
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from flask import jsonify, request
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from browser_household_media_check import Fixture, Quiet, OWN, SHARED, JOURNEY


class SuggestionFixture(Fixture):
    def __init__(self):
        super().__init__()
        self.items[OWN].update(sourceTimeState='known',sourceCreatedAt='2026-12-01T23:30:00-08:00',createdAt='2020-01-01T00:00:00Z')
        self.title='合成旅行 <img src=x onerror=alert(1)>'
        self.journey_revision=3;self.trip_revision=4
        self.unknown=False;self.conflict=False;self.lose_reply=False;self.more=False;self.hold=False;self.gone=False
        self.suggestion_started=threading.Event();self.suggestion_release=threading.Event()

    def create_app(self):
        app=super().create_app()
        @app.before_request
        def suggestions():
            path=request.path.removeprefix('/api/')
            is_read=path==f'media/items/{OWN}/journey-suggestions'
            body=request.get_json(silent=True) or {}
            is_write=path==f'media/items/{OWN}' and request.method=='PATCH' and 'expectedTripRevision' in body
            if not (is_read or is_write):return None
            self.records.append(dict(path=path,method=request.method,body=deepcopy(body)))
            item=self.items[OWN]
            if self.gone:return jsonify(error='照片已移除',code='gone'),410
            if is_read:
                assert not request.args
                rows=[] if self.unknown else [dict(journeyId=JOURNEY,journeyRevision=self.journey_revision,tripRevision=self.trip_revision,
                    title=self.title,start='2026-12-01',end='2026-12-04',referenceTimezone='Asia/Shanghai',referenceTimezoneSource='legacy_default',
                    sourceDate='2026-12-02',alreadyLinked=(item['journey'] or {}).get('id')==JOURNEY,reason={'code':'date_overlap','message':'合成日期交叠'})]
                if self.more:
                    rows += [dict(rows[0],journeyId=f'{n:024x}',alreadyLinked=False,title='其他匹配旅行 '+str(n)) for n in range(1,20)]
                result=dict(photoId=OWN,photoRevision=item['revision'],sourceTimeState='unknown' if self.unknown else 'known',
                    sourceCreatedAt=None if self.unknown else item['sourceCreatedAt'],currentJourneyId=(item['journey'] or {}).get('id'),
                    reason={'code':'source_time_unknown' if self.unknown else 'date_overlap','message':'合成契约'},suggestions=rows,limit=20,hasMore=self.more)
                if self.hold:
                    self.suggestion_started.set();self.suggestion_release.wait(8)
                return jsonify(result)
            assert set(body)=={'revision','journeyId','expectedJourneyRevision','expectedTripRevision'}
            if self.conflict:
                self.conflict=False;self.journey_revision+=1;self.trip_revision+=1;item['revision']+=1
                return jsonify(error='照片或旅行已更新',code='conflict'),409
            assert body==dict(revision=item['revision'],journeyId=JOURNEY,expectedJourneyRevision=self.journey_revision,expectedTripRevision=self.trip_revision)
            item.update(journey={'id':JOURNEY,'tripId':'trip-synthetic','title':self.title},revision=item['revision']+1)
            if self.lose_reply:
                self.lose_reply=False
                return jsonify(error='合成已提交但响应丢失'),503
            return jsonify(item=item)
        return app


def main():
    out=ROOT/'test-results'/('media-journey-suggestions-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    files=['static/household-media.js','static/household-media.css',Path(__file__).relative_to(ROOT).as_posix()]
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}
    report={'passed':False,'checks':[],'pageErrors':[],'externalRequests':[],'sourceHashesBefore':hashes(),
            'realBackend':False,'realGoogle':False,'modelCalls':0,'productionWrites':0,'screenshots':[]}
    fixture=SuggestionFixture();server=make_server('127.0.0.1',0,fixture.create_app(),threaded=True,request_handler=Quiet)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def passed(name):report['checks'].append(name);print('PASS '+name,flush=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context(viewport={'width':390,'height':844})
            def local(route):
                if urlsplit(route.request.url).hostname=='127.0.0.1':route.continue_()
                else:report['externalRequests'].append(route.request.url);route.abort()
            context.route('**/*',local)
            page=context.new_page();page.on('pageerror',lambda error:report['pageErrors'].append(str(error)))
            base='http://127.0.0.1:'+str(server.server_port)
            def open_owner():
                page.goto(base);expect(page.locator('.hm-card')).to_have_count(1)
                page.locator(f'[data-hm=detail][data-id="{OWN}"]').click();expect(page.locator('[data-hm-suggestions]')).to_be_visible()
            def load():
                page.locator('[data-hm=journey-suggestions]').click();expect(page.locator('[data-hm=journey-suggestions]')).to_be_enabled()
            def writes():return [r for r in fixture.records if 'expectedTripRevision' in r['body']]
            open_owner()
            assert not any(r['path'].endswith('/journey-suggestions') for r in fixture.records)
            load();expect(page.locator('.hm-journey-option')).to_have_count(1)
            expect(page.locator('.hm-journey-option')).to_contain_text('2026-12-02')
            expect(page.locator('.hm-journey-option')).to_contain_text('Asia/Shanghai（旧旅行使用默认时区）')
            expect(page.locator('.hm-journey-option img')).to_have_count(0)
            assert not writes()
            passed('owner_explicit_local_read_escaped_title_timezone_and_no_write')
            page.locator('[data-hm-editor] [name=journeyId]').select_option(JOURNEY)
            expect(page.locator('.hm-journey-option')).to_have_count(0)
            load();expect(page.locator('[data-hm=confirm-journey]')).to_be_disabled()
            expect(page.locator('[data-hm-suggestions]')).to_contain_text('有未保存的照片编辑')
            assert not writes()
            passed('manual_choice_invalidates_suggestions_and_dirty_draft_blocks_recommendation_write')
            fixture.unknown=True;open_owner();load()
            expect(page.locator('[data-hm-suggestions]')).to_contain_text('没有已记录的来源创建时间')
            expect(page.locator('.hm-journey-option')).to_have_count(0)
            page.locator('[data-hm-editor] [name=journeyId]').select_option(JOURNEY)
            page.locator('[data-hm-editor] [type=submit]').click()
            expect(page.locator('[data-hm-message]')).to_contain_text('照片信息已保存')
            manual=[r for r in fixture.records if r['method']=='PATCH'][-1]
            assert set(manual['body'])=={'revision','caption','visibility','journeyId'}
            passed('legacy_unknown_never_uses_createdAt_and_manual_link_contract_unchanged')
            fixture.unknown=False;fixture.items[OWN]['journey']=None;fixture.conflict=True
            open_owner();load();page.locator('[data-hm=confirm-journey]').click()
            expect(page.locator('[data-hm-suggestions]')).to_contain_text('核对后再次明确确认')
            expect(page.locator('[data-hm=confirm-journey]')).to_have_count(0)
            assert len(writes())==1
            load();expect(page.locator('[data-hm=confirm-journey]')).to_be_enabled()
            assert len(writes())==1
            page.locator('[data-hm=confirm-journey]').click()
            expect(page.locator('[data-hm-suggestions]')).to_contain_text('关联已保存')
            assert len(writes())==2 and writes()[0]['body']['expectedTripRevision']!=writes()[1]['body']['expectedTripRevision']
            assert fixture.items[OWN]['visibility']=='private' and fixture.grants[OWN]==[]
            passed('409_clears_stale_options_then_refetches_photo_and_all_revisions_before_explicit_confirm')
            fixture.items[OWN]['journey']=None;fixture.lose_reply=True
            open_owner();load();before=len(writes());page.locator('[data-hm=confirm-journey]').click()
            expect(page.locator('[data-hm-suggestions]')).to_contain_text('不会自动重发')
            load();expect(page.locator('[data-hm=confirm-journey]')).to_be_disabled()
            expect(page.locator('[data-hm=confirm-journey]')).to_have_text('已关联这次旅行')
            assert len(writes())==before+1
            passed('committed_lost_reply_readback_does_not_repeat_patch_or_broaden_sharing')
            fixture.more=True;load();expect(page.locator('.hm-journey-option')).to_have_count(20)
            expect(page.locator('[data-hm-suggestions]')).to_contain_text('仅显示前 20 条推荐')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.locator('[data-hm-suggestions]').evaluate("node=>node.scrollIntoView({block:'start'})")
            page.screenshot(path=str(out/'phone.png'));report['screenshots'].append(str(out/'phone.png'))
            fixture.more=False
            passed('bounded_20_matches_and_mobile_layout_no_overflow')
            page.locator('[data-hm=close-detail]').click()
            page.locator('[data-hm-filters] [name=scope]').select_option('shared')
            page.locator('[data-hm-filters] [type=submit]').click();expect(page.locator('.hm-card')).to_have_count(1)
            page.locator(f'[data-hm=detail][data-id="{SHARED}"]').click()
            expect(page.locator('.hm-detail')).to_be_visible();expect(page.locator('[data-hm-suggestions]')).to_have_count(0)
            passed('shared_readonly_photo_never_has_suggestion_controls')
            open_owner();load();fixture.gone=True;page.locator('[data-hm=journey-suggestions]').click()
            expect(page.locator('.hm-detail')).to_have_count(0);fixture.gone=False
            passed('source_removal_410_clears_old_detail_and_suggestions')
            open_owner();fixture.hold=True;fixture.suggestion_started.clear();fixture.suggestion_release.clear()
            page.locator('[data-hm=journey-suggestions]').click()
            for _ in range(100):
                if fixture.suggestion_started.is_set():break
                page.wait_for_timeout(25)
            assert fixture.suggestion_started.is_set()
            context.set_offline(True);expect(page.locator('.hm-journey-option')).to_have_count(0)
            context.set_offline(False);fixture.hold=False;fixture.suggestion_release.set()
            expect(page.locator('[data-hm=journey-suggestions]')).to_be_enabled()
            expect(page.locator('.hm-journey-option')).to_have_count(0)
            passed('offline_discards_pending_suggestion_generation_no_late_restore')
            fixture.hold=True;fixture.suggestion_started.clear();fixture.suggestion_release.clear()
            page.locator('[data-hm=journey-suggestions]').click()
            for _ in range(100):
                if fixture.suggestion_started.is_set():break
                page.wait_for_timeout(25)
            assert fixture.suggestion_started.is_set()
            fixture.actor='member2';page.evaluate('switchLocal()');fixture.suggestion_release.set();fixture.hold=False
            expect(page.locator('#host')).not_to_contain_text(fixture.title)
            expect(page.locator('[data-hm-suggestions],.hm-detail')).to_have_count(0)
            passed('identity_switch_fences_delayed_private_suggestion_response')
            browser.close()
            assert not report['pageErrors'] and not report['externalRequests'];report['passed']=True
    except Exception:
        report['failure']=traceback.format_exc();print(report['failure'],flush=True)
    finally:
        fixture.suggestion_release.set();server.shutdown();server.server_close()
        report['sourceHashesAfter']=hashes();report['passed'] &= report['sourceHashesBefore']==report['sourceHashesAfter']
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'report':str(out/'result.json')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
