import assert from 'node:assert/strict';
import { bounds, dayKey, daySummary, duration, eventsForDay, isLocalEvent, overlapsDay, rangeDays, rangeSummary, shiftDay, timeLabel, unionMinutes } from '../frontend/src/lib/calendar.ts';

const event = (id, start, end, owner = 'shared', extra = {}) => ({ id, start, end, owner, title: id, revision: 1, ...extra });
const today = '2026-09-16';
assert.equal(dayKey('2026-09-15T16:00:00Z'), today);
assert.equal(dayKey('2026-09-16T23:30:00-07:00'), '2026-09-17');
assert.deepEqual(rangeDays('week', '2026-09-20'), ['2026-09-14', '2026-09-15', today, '2026-09-17', '2026-09-18', '2026-09-19', '2026-09-20']);
assert.deepEqual(rangeDays('around', '2026-01-01'), ['2025-12-29', '2025-12-30', '2025-12-31', '2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04']);
assert.deepEqual(rangeDays('today', today), [today]);
assert.equal(shiftDay('2024-02-28', 1), '2024-02-29');

const allDay = event('all-day', '2026-09-15', '2026-09-17', 'member1', { allDay: true });
assert(overlapsDay(allDay, '2026-09-15')); assert(overlapsDay(allDay, today)); assert(!overlapsDay(allDay, '2026-09-17'));
assert(!overlapsDay(event('empty-all-day', today, today, 'shared', { allDay: true }), today));
assert(overlapsDay(event('instant', today + 'T23:59:00+08:00', today + 'T23:59:00+08:00'), today));
assert(!overlapsDay(event('midnight', '2026-09-17T00:00:00+08:00', '2026-09-17T00:00:00+08:00'), today));
assert(!overlapsDay(event('invalid', 'bad', 'bad'), today));
assert(!overlapsDay(event('reversed', today + 'T12:00:00+08:00', today + 'T11:00:00+08:00'), today));

const events = [allDay,
  event('morning', today + 'T09:00:00+08:00', today + 'T10:30:00+08:00', 'member1'),
  event('overlap', today + 'T10:00:00+08:00', today + 'T11:00:00+08:00'),
  event('partner', today + 'T12:00:00+08:00', today + 'T14:00:00+08:00', 'member2'),
  event('overnight', '2026-09-15T23:00:00+08:00', today + 'T01:00:00+08:00', 'member1')];
const original = JSON.stringify(events);
const summary = daySummary(events, today, 'member1');
assert.equal(summary.total, 5); assert.equal(summary.allDay, 1); assert.equal(summary.busyMinutes, 180);
assert.equal(daySummary(events, today, 'member2').busyMinutes, 180); // Shared 60 + member2 120; member1 excluded.
assert.equal(daySummary(events, '2026-09-15', 'member1').busyMinutes, 60);
const range = rangeSummary(events, rangeDays('week', today), 'member1');
assert.equal(range.total, 5); assert.equal(range.allDay, 1); assert.equal(range.busyMinutes, 240);
assert.equal(JSON.stringify(events), original, 'summaries must not reorder or modify caller data');
assert.equal(eventsForDay(events, today, 'member1')[0].id, 'all-day');

assert.equal(unionMinutes([[0, 60_000], [30_000, 90_000], [90_000, 120_000], [300_000, 360_000]]), 3);
assert.equal(unionMinutes([[1, 1], [10, 1], [NaN, 10], [0, Infinity]]), 0);
assert.equal(timeLabel(allDay, today), '全天');
assert.equal(timeLabel(events.at(-1), today), '00:00–01:00');
assert.equal(timeLabel(events.at(-1), '2026-09-15'), '23:00–24:00');
assert.equal(timeLabel(event('point', today + 'T12:10:00+08:00', today + 'T12:10:00+08:00'), today), '12:10');
assert.equal(timeLabel(event('invalid', 'bad', 'bad'), today), '时间待核对');
assert.equal(bounds(allDay).start, Date.parse('2026-09-15T00:00:00+08:00'));
assert.equal(duration(0), '0 分钟'); assert.equal(duration(90), '1.5 小时');
assert(isLocalEvent(events[1])); assert(!isLocalEvent({ ...events[1], sync: { readOnly: false } }));
console.log('PASS Expo calendar: Beijing dates, week/year/leap edges, exclusive all-day ends, focus/shared interval union, invalid timestamps, readonly sources, immutable input');
