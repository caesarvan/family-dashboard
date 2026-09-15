'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const cv = require('../static/calendar-ui.js');
const timed = (id, start, end, owner = 'member1') => ({id, start, end, owner, allDay:false});

test('Monday-based week crosses month and year boundaries', () => {
  assert.deepEqual(cv.rangeDays('week', '2027-01-01'), ['2026-12-28','2026-12-29','2026-12-30','2026-12-31','2027-01-01','2027-01-02','2027-01-03']);
  assert.equal(cv.rangeDays('week', '2026-09-20')[0], '2026-09-14');
  assert.equal(cv.rangeDays('week', '2026-09-14')[0], '2026-09-14');
});
test('around means three previous days, anchor, and three following days', () => {
  assert.deepEqual(cv.rangeDays('around','2028-03-01'), ['2028-02-27','2028-02-28','2028-02-29','2028-03-01','2028-03-02','2028-03-03','2028-03-04']);
  assert.deepEqual(cv.rangeDays('today','2026-09-14'), ['2026-09-14']);
});
test('Beijing dates do not inherit UTC or device-local midnight', () => {
  assert.equal(cv.dayKey('2026-09-14T16:00:00Z'), '2026-09-15');
  assert.equal(cv.dayKey('2026-09-14T23:00:00-07:00'), '2026-09-15');
  assert.equal(cv.shiftDay('2026-12-31', 1), '2027-01-01');
});
test('timed midnight ending is exclusive and continuing events clip by Beijing day', () => {
  const untilMidnight = timed('a','2026-09-14T23:00:00+08:00','2026-09-15T00:00:00+08:00');
  assert.equal(cv.overlapsDay(untilMidnight, '2026-09-15'), false);
  const continuing = timed('b','2026-09-14T15:30:00Z','2026-09-14T17:00:00Z');
  assert.equal(cv.daySummary([continuing], '2026-09-14', 'member1').busyMinutes, 30);
  assert.equal(cv.daySummary([continuing], '2026-09-15', 'member1').busyMinutes, 60);
  assert.equal(cv.timeLabel(continuing,'2026-09-14'), '23:30–24:00');
  assert.equal(cv.timeLabel(continuing,'2026-09-15'), '00:00–01:00');
});
test('overlapping member and common slots count once, partner remains visible', () => {
  const events = [timed('a','2026-09-14T09:00:00+08:00','2026-09-14T11:00:00+08:00'), timed('b','2026-09-14T10:00:00+08:00','2026-09-14T12:00:00+08:00','shared'), timed('c','2026-09-14T13:00:00+08:00','2026-09-14T17:00:00+08:00','member2')];
  const summary = cv.daySummary(events, '2026-09-14','member1');
  assert.equal(summary.total, 3); assert.equal(summary.events.length, 3);
  assert.equal(summary.focusedCount, 2); assert.equal(summary.busyMinutes, 180);
  assert.equal(cv.daySummary(events,'2026-09-14','member2').busyMinutes, 360);
});
test('all-day spans preserve inclusive start/exclusive end without adding 24-hour workload', () => {
  const event = {id:'a', start:'2026-09-14T00:00:00+08:00', end:'2026-09-16T00:00:00+08:00', allDay:true, owner:'shared'};
  const summary = cv.rangeSummary([event], cv.rangeDays('week','2026-09-14'), 'member1');
  assert.equal(summary.total, 1); assert.equal(summary.allDay, 1); assert.equal(summary.busyMinutes, 0);
  assert.equal(summary.days[0].allDay, 1); assert.equal(summary.days[1].allDay, 1);
  assert.equal(summary.days[2].total, 0);
});
test('zero-duration reminders remain visible but invalid or reversed events do not count', () => {
  const point = timed('a','2026-09-14T10:00:00+08:00','2026-09-14T10:00:00+08:00');
  assert.equal(cv.overlapsDay(point,'2026-09-14'), true);
  assert.equal(cv.timeLabel(point,'2026-09-14'), '10:00');
  const summary = cv.daySummary([point, timed('bad','unknown','unknown'), timed('reverse','2026-09-14T12:00:00Z','2026-09-14T11:00:00Z')], '2026-09-14','member1');
  assert.equal(summary.total, 1); assert.equal(summary.busyMinutes, 0);
});
test('busy interval union handles nesting, adjacency, duplicates and disjoint slots', () => {
  const minute = 60000;
  assert.equal(cv.unionMinutes([[0,5*minute], [minute,3*minute], [5*minute,7*minute], [10*minute,11*minute], [0,5*minute]]), 8);
  assert.equal(cv.unionMinutes([]), 0);
});
test('TV pages automatically cover every event without dropping or duplicating items', () => {
  const events = Array.from({length:10}, (_, i) => timed(String(i),`2026-09-14T${String(8+i).padStart(2,'0')}:00:00+08:00`,`2026-09-14T${String(9+i).padStart(2,'0')}:00:00+08:00`));
  const pages = Array.from({length:4}, (_, cycle) => cv.tvPage(events, '2026-09-14', cycle, Date.parse('2026-09-14T12:30:00+08:00')));
  assert.deepEqual(pages.map(page => page.items.length), [3,3,3,1]);
  assert.equal(pages[0].items[0].id, '4');
  assert.equal(pages[3].page, 4); assert.equal(pages[3].pages, 4);
  assert.deepEqual(pages.flatMap(page => page.items.map(event => event.id)).sort(), events.map(event => event.id).sort());
  assert.deepEqual(cv.tvPage(events, '2026-09-14', 4, Date.parse('2026-09-14T12:30:00+08:00')).items, pages[0].items);
});
test('TV pagination retains all-day context and every past event', () => {
  const now = Date.parse('2026-09-14T12:30:00+08:00');
  const events = [
    {id:'all',start:'2026-09-14T00:00:00+08:00',end:'2026-09-15T00:00:00+08:00',allDay:true},
    timed('past','2026-09-14T10:00:00+08:00','2026-09-14T11:00:00+08:00'),
    timed('future','2026-09-14T15:00:00+08:00','2026-09-14T16:00:00+08:00')
  ];
  assert.deepEqual(cv.tvPage(events,'2026-09-14',0,now).items.map(event => event.id), ['all','future','past']);
  assert.equal(cv.tvPage([], '2026-09-14',10,now).pages, 1);
});
