import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { assistantPlanOptions, assistantTripRequest, isAssistantSearchRequest, isJourneyRequest, journeySessionKey } from '../frontend/src/lib/assistantJourney.ts';

test('explicit task, shopping and search prefixes keep their existing meaning', () => {
  for (const text of ['待办：确认旅行酒店', '  采购:旅行转换插头', '搜索 ： 东京行程']) {
    assert.equal(isJourneyRequest(text), false);
  }
  for (const text of ['规划一次旅行', '帮我整理行程', '返程日期：2027-10-12']) {
    assert.equal(isJourneyRequest(text), true);
  }
  assert.equal(isJourneyRequest('看看这周安排'), false);
  assert.equal(isJourneyRequest(''), false);
});

const searches = ['找一下冰岛旅行', '搜索 冰岛旅行', '查找冰岛旅行', '搜索：冰岛旅行', ' 查找 : 冰岛旅行 ', '找一下\n冰岛旅行'];

test('all existing local-search prefixes take precedence over travel words without changing the query', () => {
  for (const prompt of searches) {
    assert.equal(isAssistantSearchRequest(prompt), true, prompt);
    assert.equal(isJourneyRequest(prompt), false, prompt);
  }
  for (const prompt of ['规划一次旅行', '帮我整理行程', '旅行中查找冰岛酒店']) {
    assert.equal(isAssistantSearchRequest(prompt), false, prompt);
    assert.equal(isJourneyRequest(prompt), true, prompt);
  }
  for (const prompt of ['待办：查找旅行保险', '采购：旅行收纳袋']) assert.equal(isJourneyRequest(prompt), false);
});

test('explicit search turns off model and context even when both were selected', () => {
  for (const prompt of searches) {
    assert.deepEqual(assistantPlanOptions(prompt, true, true), { useModel: false, includeHouseholdContext: false });
  }
  assert.deepEqual(assistantPlanOptions('待办：查找旅行保险', true, true), { useModel: true, includeHouseholdContext: true });
  assert.deepEqual(assistantPlanOptions('整理采购', true, false), { useModel: true, includeHouseholdContext: false });
  assert.deepEqual(assistantPlanOptions('整理采购', false, true), { useModel: false, includeHouseholdContext: false });
});

test('trip navigation retains only the entity ID and a valid new request key', () => {
  const id = 'a'.repeat(24), journeyId = 'b'.repeat(24);
  assert.deepEqual(assistantTripRequest({ kind: 'trips', id, journeyId, title: '过时标题', plan: { title: '不得复制' } }, 7), { id, key: 7 });
  for (const kind of ['tasks', 'shopping', 'media', 'places', 'inventory', 'journeys']) {
    assert.equal(assistantTripRequest({ kind, id }, 7), null);
  }
  for (const bad of [undefined, null, '', 'A'.repeat(24), '../trips', 'a'.repeat(23), journeyId + '?edit=true']) {
    assert.equal(assistantTripRequest({ kind: 'trips', id: bad }, 7), null);
  }
  for (const key of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(assistantTripRequest({ kind: 'trips', id }, key), null);
  }
});

test('real Flask search stays local, exposes trip entity IDs and rereads changed/deleted matches', { timeout: 60000 }, () => {
  const root = fileURLToPath(new URL('..', import.meta.url));
  const requests = searches.map(prompt => ({ prompt, ...assistantPlanOptions(prompt, true, true) }));
  const result = spawnSync(process.env.ASSISTANT_ENTRY_TEST_PYTHON || 'python', ['-B', '-X', 'utf8', '-c', String.raw`
import sys,json,os,socket,tempfile,sqlite3
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
root=Path(sys.argv[1]);sys.path[:0]=[str(root),str(root/'tests')]
from app import create_app
from test_app import member
from test_journey_workflows import plan,preview,apply
import home_assistant
requests=json.load(sys.stdin)
def deny(*args,**kwargs):raise AssertionError('No network or model call is allowed')
with tempfile.TemporaryDirectory(prefix='assistant-trip-entry-') as folder, patch.dict(os.environ,{'MEMBER1_PASSWORD':'testing-password-one','MEMBER2_PASSWORD':'testing-password-two'}), patch.object(socket.socket,'connect',deny), patch('socket.create_connection',deny), patch.object(home_assistant,'model_plan',deny), patch.object(home_assistant,'model_journey_brief',deny):
    app=create_app({'TESTING':True,'SECRET_KEY':'synthetic-assistant-entry','DATA_DIR':folder,'SESSION_COOKIE_SECURE':False})
    c,h=member(app)
    value=preview(c,h,plan(title='冰岛旅行 已有计划'))
    response=apply(c,h,value,'assistant-search-existing');assert response.status_code==201,response.json
    journey=response.json;assert journey['id']!=journey['tripId']
    response=c.post('/api/items/trips',json={'title':'冰岛旅行 旧旅行','start':'2026-12-03','end':'2026-12-09','budget':10000},headers=h);assert response.status_code==201,response.json
    legacy=response.json
    def counts():
        with closing(sqlite3.connect(Path(folder)/'household.sqlite3')) as con:
            return {table:con.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['entities','journey_workflows','assistant_plans']}
    before=counts();outputs=[]
    # The frontend's real helper-generated payloads and a deliberately selected
    # AI request both hit the existing backend search branch before any provider.
    for payload in requests+[{'prompt':'找一下冰岛旅行','useModel':True,'includeHouseholdContext':True}]:
        r=c.post('/api/assistant/plan',json=payload,headers=h);assert r.status_code==200,r.json
        d=r.json;assert d['mode']=='local' and d['id'] is None and d['actions']==[]
        assert d['search']['query']=='冰岛旅行'
        matches=[m for m in d['matches'] if m['kind']=='trips'];assert {m['id'] for m in matches}=={journey['tripId'],legacy['id']}
        outputs.append(d)
    assert counts()==before
    journeys=c.get('/api/journeys').json['journeys'];linked=next(x for x in journeys if x['tripId']==journey['tripId']);assert linked['id']==journey['id']
    detail=c.get('/api/journeys/'+linked['id']);assert detail.status_code==200
    trip=detail.json['trip'];r=c.patch('/api/items/trips/'+trip['id'],json={'revision':trip['revision'],'title':'冰岛旅行 最新标题'},headers=h);assert r.status_code==200,r.json
    fresh=c.get('/api/journeys/'+linked['id']);assert fresh.status_code==200 and fresh.json['trip']['title']=='冰岛旅行 最新标题'
    r=c.delete('/api/items/trips/'+legacy['id'],json={'revision':legacy['revision']},headers=h);assert r.status_code==200,r.json
    returned=c.get('/api/assistant/search',query_string={'q':'冰岛旅行','offset':0,'limit':20});assert returned.status_code==200,returned.json
    assert [m['id'] for m in returned.json['matches'] if m['kind']=='trips']==[journey['tripId']]
    assert next(m for m in returned.json['matches'] if m['kind']=='trips')['title']=='冰岛旅行 最新标题'
    print(json.dumps({'responses':outputs,'tripId':journey['tripId'],'journeyId':journey['id'],'freshTitle':fresh.json['trip']['title'],'returned':returned.json,'countsUnchangedBySearch':True},ensure_ascii=False))
`, root], { input: JSON.stringify(requests), encoding: 'utf8', timeout: 55000 });
  assert.equal(result.status, 0, result.stderr || result.stdout || String(result.error));
  const dto = JSON.parse(result.stdout);
  assert.equal(dto.responses.length, searches.length + 1);
  for (const response of dto.responses) {
    for (const match of response.matches.filter(item => item.kind === 'trips')) {
      assert.deepEqual(assistantTripRequest(match, 9), { key: 9, id: match.id });
      assert.notEqual(assistantTripRequest(match, 9).id, dto.journeyId);
    }
  }
  assert.equal(dto.countsUnchangedBySearch, true);
  assert.equal(dto.freshTitle, '冰岛旅行 最新标题');
});

test('journey entry identity binds household, member, role, auth version and csrf', () => {
  const user = { id: 'member1', name: '合成成员', role: 'member', householdId: 'one', auth_version: 1 };
  const current = journeySessionKey({ user, csrf: 'synthetic-a' });
  assert.equal(current, JSON.stringify(['member', 'one', 'member1', 1, null, null, null, null, 'synthetic-a']));
  for (const patch of [{ id: 'member2' }, { householdId: 'two' }, { role: 'tv' }, { auth_version: 2 },
    { membershipRevision: 2 }, { accountId: 'a'.repeat(32) }, { accountAuthVersion: 2 }, { authenticationGeneration: 2 }]) {
    assert.notEqual(journeySessionKey({ user: { ...user, ...patch }, csrf: 'synthetic-a' }), current);
  }
  assert.notEqual(journeySessionKey({ user, csrf: 'synthetic-b' }), current);
  assert.notEqual(journeySessionKey({ user: null }), current);
});
