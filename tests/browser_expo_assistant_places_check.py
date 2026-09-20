"""Actual assistant -> original place/trip/photo flows on isolated HTTPS SQLite.

No model, map provider or browser-facing business DTO is substituted. Delayed
reads retain the bytes/status of a completed real response before delivery.
"""
from contextlib import ExitStack, closing, contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import traceback
from urllib.parse import urlencode

from playwright.sync_api import expect
from browser_expo_finance_check import sha
from browser_expo_local_photo_check import Run as LocalRun, make_picture
from browser_expo_trip_recap_check import Run as TripRun

HARNESS = 'tests/browser_expo_assistant_places_check.py'
CASES = ('page_original_return', 'filters_clear_selection', 'revocation_identity_late')
CASE_SCREENSHOTS = dict(zip(CASES, (3, 2, 3)))
PATH = '/api/journey-places'
PROMPT = '告诉助理你的需求'


def button(page, name):
    # Paper web includes a leading icon glyph in some accessible names.
    return page.get_by_role('button', name=re.compile(r'^(?:\S+\s+)?' + re.escape(name) + r'$'))


def page_path(query, offset):
    return '/api/assistant/search?' + urlencode(dict(q=query, limit=20, offset=offset))


def choose_page_target(search, first_map):
    assert search['offset'] == 20 and search['total'] == 21 and len(search['matches']) == 1
    target = search['matches'][0]
    assert target['kind'] == 'places' and re.fullmatch('[a-f0-9]{24}', target['id'])
    assert target['id'] not in {row['id'] for row in first_map['items']}
    assert first_map['limit'] == 24 and len(first_map['items']) == 24 and first_map['hasMore']
    return target


class Run(LocalRun):
    journey = TripRun.journey
    place = TripRun.place

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.serial = 0
        for name, relative in (
            ('browser_expo_assistant_places_check', HARNESS),
            ('browser_expo_trip_recap_check', 'tests/browser_expo_trip_recap_check.py'),
            ('home_assistant', 'home_assistant.py'), ('journey_places', 'journey_places.py')):
            actual = Path(importlib.import_module(name).__file__).resolve()
            assert actual == (self.root / relative).resolve()
            self.report.setdefault('fixtureHashes', {})[relative] = sha(actual)
        assert self.report['fixtureHashes'][HARNESS] == self.report['harnessSha256']

    def start(self, port=0):
        self.cfg['ASSISTANT_PROVIDER'] = 'local'
        super().start(port)

    def exchange(self, page, name, method, path, trigger, status=200):
        self.serial += 1
        return self.completed_json(page, '%02d-%s' % (self.serial, name), method,
                                   self.base + path, trigger, status)

    def snapshot(self):
        assert self.database.resolve().is_relative_to(self.folder.resolve())
        with closing(sqlite3.connect(self.database)) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            return {table: hashlib.sha256(repr(sorted(con.execute('SELECT * FROM ' + table).fetchall(), key=repr)).encode()).hexdigest()
                    for table in ('entities', 'journey_workflows', 'journey_links', 'journey_places',
                                  'media_items', 'media_imports', 'media_tv_grants', 'assistant_plans')}

    @staticmethod
    def prompt(page):
        return page.get_by_role('textbox', name=PROMPT, exact=True)

    def assistant(self, page):
        page.goto(self.base + '/app/assistant')
        expect(page.get_by_role('heading', name='家庭助理', exact=True)).to_be_visible(timeout=15000)
        expect(self.prompt(page)).to_be_enabled(timeout=15000)

    def search(self, page, query):
        self.prompt(page).fill('搜索：' + query)
        value, body = self.exchange(page, 'search', 'POST', '/api/assistant/plan', lambda: button(page, '整理并预览').click())
        assert body == dict(prompt='搜索：' + query, useModel=False, includeHouseholdContext=False)
        assert value['mode'] == 'local' and value['id'] is None and value['actions'] == []
        assert value['search']['query'] == query
        expect(page.get_by_text('第 1 页', exact=True)).to_be_visible()
        return {**value['search'], 'matches': value['matches']}

    @staticmethod
    def hit(page, uid):
        return page.get_by_test_id('assistant-search-places-' + uid).get_by_role('button')

    def open_place(self, page, item):
        value, _ = self.exchange(page, 'open-original-place', 'GET', PATH + '/' + item['id'], lambda: self.hit(page, item['id']).click())
        assert value['place']['id'] == item['id']
        expect(page.get_by_role('heading', name=value['place']['name'], exact=True)).to_be_visible(timeout=15000)
        expect(button(page, '编辑地点')).to_have_count(1 if value['place']['canManage'] else 0)
        return value['place']

    def return_search(self, page, query, offset):
        value, _ = self.exchange(page, 'return-search', 'GET', page_path(query, offset), lambda: button(page, '返回地点搜索').click())
        assert value['query'] == query and value['offset'] == offset
        expect(self.prompt(page)).to_have_value('搜索：' + query)
        expect(page.get_by_text('第 %d 页' % (offset // 20 + 1), exact=True)).to_be_visible()
        return value

    def seed_photo(self, ctx, journey):
        path = self.raw_files / 'original-trip-photo.png'
        spec = make_picture(path, 'PNG', '#4a738d')
        detail = self.write(ctx, 'POST', '/api/media/local-imports', dict(requestId=secrets.token_hex(16),
            consentVersion='media-v1', allowTemporaryProcessing=True, files=[dict(clientFileId=secrets.token_hex(16),
            filename=spec['name'], contentType='image/png', bytes=spec['bytes'], sha256=spec['sha256'])]), 201)
        batch = detail['import']['id']; slot = detail['upload']['files'][0]['slotId']
        response = ctx.request.put(self.base + '/api/media/local-imports/' + batch + '/files/' + slot, data=path.read_bytes(),
            headers={'Origin': self.base, 'X-CSRF-Token': self.get(ctx, '/api/me')['csrf'], 'Content-Type': 'image/png',
                     'X-Import-Revision': str(detail['import']['revision'])})
        assert response.status == 200, response.text()
        detail = response.json()
        detail = self.write(ctx, 'POST', '/api/media/local-imports/' + batch + '/finish',
                            dict(requestId=secrets.token_hex(16), revision=detail['import']['revision']))
        uid = detail['items'][0]['id']
        self.write(ctx, 'POST', '/api/media/imports/' + batch + '/confirm', dict(revision=detail['import']['revision'],
            confirmRequestId=secrets.token_hex(16), consentVersion='media-v1', persistSelected=True, itemIds=[uid]))
        current = self.get(ctx, '/api/media/items/' + uid)['item']
        return self.write(ctx, 'PATCH', '/api/media/items/' + uid, dict(revision=current['revision'],
            journeyId=journey['id'], caption='合成原旅行照片'))['item']

    def paged_fixture(self, ctx):
        journey = self.journey(ctx); query = '合成地点分页'
        items = [self.place(ctx, journey, query + ' %02d' % n) for n in range(21)]
        # Created last: map's updated_at ordering puts all matching IDs outside
        # the first page, independently of the assistant's random-ID ordering.
        for n in range(24): self.place(ctx, journey, '地图填充 %02d' % n)
        search = self.get(ctx, page_path(query, 20))
        first_map = self.get(ctx, PATH + '?limit=24&offset=0&scope=visible')
        hit = choose_page_target(search, first_map)
        item = next(row for row in items if row['id'] == hit['id'])
        self.record('fixture-page-binding', dict(query=query, search=search, map=first_map, original=item))
        return journey, query, item

    def page_original_return(self, browser):
        with self.flow(browser) as (ctx, page):
            journey, query, item = self.paged_fixture(ctx); photo = self.seed_photo(ctx, journey)
            before = self.snapshot(); original_ids = self.get(ctx, PATH + '?limit=100&offset=0')['items']
            self.assistant(page); assert self.search(page, query)['total'] == 21
            second, _ = self.exchange(page, 'search-page-two', 'GET', page_path(query, 20), lambda: button(page, '下一页').click())
            assert second['matches'][0]['id'] == item['id']
            current = self.open_place(page, item)
            self.capture(page, 'original-outside-map-page-390', page.get_by_role('heading', name=item['name'], exact=True))
            button(page, '编辑地点').click()
            field = page.get_by_role('textbox', name='地点名称', exact=True)
            expect(field).to_have_value(item['name']); field.fill(item['name'] + ' 已核对')
            saved, body = self.exchange(page, 'edit-same-id', 'PATCH', PATH + '/' + item['id'], lambda: button(page, '保存地点').click())
            assert body['revision'] == current['revision'] and saved['place']['id'] == item['id']
            assert saved['place']['revision'] == current['revision'] + 1
            expect(field).to_have_count(0); expect(button(page, '查看旅行')).to_be_enabled()
            mark = len(self.requests); button(page, '查看旅行').click()
            expect(button(page, '返回足迹地图')).to_be_visible(timeout=15000)
            expect(page.get_by_role('heading', name=journey['trip']['title'], exact=True)).to_be_visible()
            assert any(r['path'] == '/api/journeys/' + journey['id'] for r in self.requests[mark:])
            button(page, '返回足迹地图').click(); expect(button(page, '查看旅行照片')).to_be_enabled()
            mark = len(self.requests); button(page, '查看旅行照片').click()
            expect(page.get_by_role('heading', name='旅行相册', exact=True)).to_be_visible(timeout=15000)
            picture = page.get_by_role('button', name='查看照片：' + photo['caption'], exact=True)
            expect(picture).to_be_visible(); picture.click()
            expect(page.get_by_role('heading', name='照片详情', exact=True)).to_be_visible()
            expect(page.get_by_role('img', name=photo['caption'], exact=True).last).to_be_visible()
            assert any(r['path'] == '/api/media/items/' + photo['id'] for r in self.requests[mark:])
            self.capture(page, 'linked-original-photo-390', page.get_by_role('heading', name='照片详情', exact=True))
            button(page, '关闭').click(); button(page, '返回地图').click()
            expect(button(page, '返回地点搜索')).to_be_enabled()
            returned = self.return_search(page, query, 20)
            assert returned['matches'][0]['id'] == item['id'] and returned['matches'][0]['revision'] == saved['place']['revision']
            self.capture(page, 'same-query-page-two-390', self.hit(page, item['id']))
            after = self.snapshot(); assert {k:v for k,v in before.items() if k!='journey_places'} == {k:v for k,v in after.items() if k!='journey_places'}
            assert sorted(r['id'] for r in original_ids) == sorted(r['id'] for r in self.get(ctx, PATH+'?limit=100&offset=0')['items'])
            self.record('same-original-id-database', dict(before=before, after=after, placeBefore=current, placeAfter=self.get(ctx, PATH+'/'+item['id'])['place'], journeyId=journey['id'], photoId=photo['id']), 'databaseEvidence')
            self.passed('Page-two place outside map page opens original ID; one revision PATCH, real original trip/photo and same query/page return')

    def filters_clear_selection(self, browser):
        with self.flow(browser) as (ctx, page):
            page.set_viewport_size(dict(width=1280,height=1000)); _,query,item = self.paged_fixture(ctx)
            before = self.snapshot(); self.assistant(page); self.search(page, query)
            self.exchange(page, 'second-page', 'GET', page_path(query,20), lambda: button(page,'下一页').click())
            self.open_place(page,item)
            self.exchange(page, 'refresh-original', 'GET', PATH+'/'+item['id'], lambda: button(page,'刷新地点').click())
            expect(page.get_by_role('heading',name=item['name'],exact=True)).to_be_visible()
            button(page,'筛选地点').click(); page.get_by_role('textbox',name='年份',exact=True).fill('2099')
            button(page,'应用筛选').click()
            expect(page.get_by_text('选一个地点看看',exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_role('heading',name=item['name'],exact=True)).to_have_count(0)
            expect(page.get_by_text('共 0 个地点 · 本页 0 个 · 0 个无可显示坐标',exact=True)).to_be_visible()
            self.capture(page,'filter-clears-selected-1280',page.get_by_text('选一个地点看看',exact=True))
            button(page,'重置筛选').click(); expect(button(page,'下一页')).to_be_enabled()
            row=self.get(ctx,PATH+'?limit=24&offset=0&scope=visible')['items'][0]
            button(page,'打开地点：'+row['name']).click(); expect(page.get_by_role('heading',name=row['name'],exact=True)).to_be_visible()
            button(page,'重置筛选').click()
            expect(page.get_by_text('选一个地点看看',exact=True)).to_be_visible()
            expect(page.get_by_role('heading',name=row['name'],exact=True)).to_have_count(0)
            button(page,'打开地点：'+row['name']).click(); expect(page.get_by_role('heading',name=row['name'],exact=True)).to_be_visible()
            button(page,'下一页').click(); expect(page.get_by_text('第 2 页',exact=True)).to_be_visible()
            expect(page.get_by_text('选一个地点看看',exact=True)).to_be_visible()
            row=self.get(ctx,PATH+'?limit=24&offset=24&scope=visible')['items'][0]
            button(page,'打开地点：'+row['name']).click(); expect(page.get_by_role('heading',name=row['name'],exact=True)).to_be_visible()
            button(page,'上一页').click(); expect(page.get_by_text('第 1 页',exact=True)).to_be_visible()
            expect(page.get_by_text('选一个地点看看',exact=True)).to_be_visible()
            self.capture(page,'page-changes-clear-selection-1280',page.get_by_text('选一个地点看看',exact=True))
            self.return_search(page,query,20); assert self.snapshot()==before
            self.record('filters-readonly',before,'databaseEvidence')
            self.passed('Refresh preserves original selection; active filters/reset/next/previous clear it without business writes')

    @contextmanager
    def held_detail(self,page,uid):
        held=[];url=self.base+PATH+'/'+uid
        def hold(route):
            response=route.fetch(timeout=15000,max_redirects=0); assert response.status==200 and 'set-cookie' not in response.headers
            raw=response.body(); self.record('held-private-detail',dict(status=response.status,url=url,body=json.loads(raw),sha256=hashlib.sha256(raw).hexdigest()))
            held.append((route,response.status,response.headers,raw))
        page.route(url,hold)
        try:yield held
        finally:
            page.unroute(url,hold)
            for route,*_ in held:route.abort('failed')

    def revocation_identity_late(self,browser):
        with self.flow(browser) as (ctx,page), ExitStack() as stack:
            page.set_viewport_size(dict(width=1280,height=1000)); journey=self.journey(ctx)
            shared=self.place(ctx,journey,'合成共享撤回地点',visibility='shared',coordinateDisclosure='coarse')
            private=self.place(ctx,journey,'合成原成员私密地点')
            owner=self.context(browser,1); stack.callback(owner.close)
            self.login(ctx,2);self.assistant(page);assert self.search(page,shared['name'])['total']==1
            projected=self.open_place(page,shared);assert not projected['canManage'] and projected['coordinatePrecision']=='approximate'
            assert projected['coordinates']!=shared['coordinates']
            self.capture(page,'partner-coarse-readonly-1280',page.get_by_role('heading',name=shared['name'],exact=True))
            ctx.set_offline(True);page.evaluate("() => window.dispatchEvent(new Event('offline'))")
            expect(page.get_by_role('heading',name=shared['name'],exact=True)).to_have_count(0)
            ctx.set_offline(False);page.evaluate("() => window.dispatchEvent(new Event('online'))")
            expect(page.get_by_role('heading',name=shared['name'],exact=True)).to_be_visible(timeout=20000)
            self.write(owner,'PATCH',PATH+'/'+shared['id'],dict(revision=shared['revision'],visibility='private'))
            # Natural 15s permission poll. Do not replace or retry its response.
            expect(page.get_by_text('地点或关联旅行已移除，或不再对你可见。旧详情和草稿已清空。',exact=True)).to_be_visible(timeout=25000)
            expect(page.get_by_role('heading',name=shared['name'],exact=True)).to_have_count(0)
            self.get(ctx,PATH+'/'+shared['id'],404)
            self.capture(page,'shared-revoked-1280',page.get_by_text('选一个地点看看',exact=True))
            assert self.return_search(page,shared['name'],0)['total']==0
            self.login(ctx,1);self.assistant(page);assert self.search(page,private['name'])['total']==1
            before=self.snapshot()
            with self.held_detail(page,private['id']) as held:
                self.hit(page,private['id']).click();self.settle(page,lambda:len(held)==1)
                old=self.get(ctx,'/api/me')['user'];self.login(ctx,2);new=self.get(ctx,'/api/me')['user'];assert old['id']!=new['id']
                reads=self.count_requests('GET','/api/me');route,status,headers,raw=held.pop();route.fulfill(status=status,headers=headers,body=raw)
                self.settle(page,lambda:self.count_requests('GET','/api/me')>reads)
                expect(self.prompt(page)).to_be_enabled(timeout=15000)
                expect(self.hit(page,private['id'])).to_have_count(0)
                expect(page.get_by_role('heading',name=private['name'],exact=True)).to_have_count(0)
                assert self.search(page,private['name'])['total']==0
            self.capture(page,'late-private-response-cleared-1280',self.prompt(page))
            assert self.snapshot()==before
            self.record('identity-readonly',dict(before=before,after=self.snapshot(),oldMember=old['id'],newMember=new['id']), 'databaseEvidence')
            self.passed('Partner coarse read, offline hide/recovery, real sharing revoke and changed-member late response enforce current original-ID authority')

    @classmethod
    def run_scenarios(cls,root,bundle,report,out,browser,temp_root,cases=CASES):
        for name in cases:
            case_out=out/name;case_out.mkdir();folder=None;before=len(report['checks']);shots=len(report['screenshots']);case=dict(name=name,passed=False)
            try:
                with ExitStack() as lifecycle:
                    folder=Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='ap-',dir=temp_root)))
                    run=cls(root,bundle,folder,report,case_out,lifecycle);getattr(run,name)(browser)
                assert len(report['checks'])==before+1 and not folder.exists()
                assert len(report['screenshots'])-shots==CASE_SCREENSHOTS[name]
                assert run.server is None and not run.thread.is_alive();case.update(passed=True,listenerStopped=True)
            except Exception:
                del report['checks'][before:];failure=traceback.format_exc();(case_out/'failure.txt').write_text(failure,encoding='utf-8')
                report['scenarioFailures'].append(dict(scenario=name,traceback=failure));print('FAIL '+name+'\n'+failure,flush=True)
            finally:
                case['temporaryFixtureRemoved']=folder is not None and not folder.exists();report['scenarioResults'].append(case)
