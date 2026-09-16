import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isJourneyRequest, journeySessionKey } from '../frontend/src/lib/assistantJourney.ts';

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

test('journey entry identity binds household, member, role, auth version and csrf', () => {
  const user = { id: 'member1', name: '合成成员', role: 'member', householdId: 'one', auth_version: 1 };
  const current = journeySessionKey({ user, csrf: 'synthetic-a' });
  assert.equal(current, JSON.stringify(['member', 'one', 'member1', 1, 'synthetic-a']));
  for (const patch of [{ id: 'member2' }, { householdId: 'two' }, { role: 'tv' }, { auth_version: 2 }]) {
    assert.notEqual(journeySessionKey({ user: { ...user, ...patch }, csrf: 'synthetic-a' }), current);
  }
  assert.notEqual(journeySessionKey({ user, csrf: 'synthetic-b' }), current);
  assert.notEqual(journeySessionKey({ user: null }), current);
});
