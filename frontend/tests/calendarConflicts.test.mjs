import assert from 'node:assert/strict';
import { test } from 'node:test';
import { calendarConflicts, dayStart, rangeDays } from '../src/lib/calendar.ts';

const day = '2026-09-20';
const stamp = clock => `${day}T${clock}:00+08:00`;
const event = (id, start = stamp('09:00'), end = stamp('11:00'), owner = 'member1', extra = {}) =>
  ({ id, revision: 1, title: `安排 ${id}`, owner, start, end, ...extra });
const pairs = items => items.map(item => [item.first.id, item.second.id]);

test('same member and shared participation count, independent members do not', () => {
  const events = [event('me'), event('mine'), event('partner', undefined, undefined, 'member2'),
    event('partner2', undefined, undefined, 'member2'), event('shared', undefined, undefined, 'shared')];
  assert.deepEqual(pairs(calendarConflicts(events, [day], 'member1')), [['me', 'mine'], ['me', 'shared'], ['mine', 'shared']]);
  assert.deepEqual(pairs(calendarConflicts(events, [day], 'member2')), [['partner', 'partner2'], ['partner', 'shared'], ['partner2', 'shared']]);
  assert.deepEqual(calendarConflicts(events.slice(0, 1).concat(events[2]), [day], 'member1'), []);
  assert.equal(calendarConflicts([event('a', undefined, undefined, 'shared'), event('b', undefined, undefined, 'shared')], [day], 'member1').length, 1);
});

test('empty input, irrelevant people and time outside selected dates produce no pairs', () => {
  assert.deepEqual(calendarConflicts([], [day], 'member1'), []);
  assert.deepEqual(calendarConflicts([event('a'), event('b')], [], 'member1'), []);
  assert.deepEqual(calendarConflicts([event('a'), event('b')], [day], 'member2'), []);
  assert.deepEqual(calendarConflicts([event('a'), event('b')], ['2026-09-21'], 'member1'), []);
});

test('half-open intervals exclude touching ends, zero duration and reversed time', () => {
  assert.deepEqual(calendarConflicts([event('a', stamp('09:00'), stamp('10:00')), event('b', stamp('10:00'), stamp('11:00'))], [day], 'member1'), []);
  const events = [event('a'), event('zero', stamp('10:00'), stamp('10:00')), event('reversed', stamp('10:00'), stamp('09:00'))];
  assert.deepEqual(calendarConflicts(events, [day], 'member1'), []);
  const [overlap] = calendarConflicts([event('a'), event('b', stamp('10:30'), stamp('12:00'))], [day], 'member1');
  assert.equal(overlap.minutes, 30);
  assert.deepEqual(overlap.overlaps, [{ day, start: Date.parse(stamp('10:30')), end: Date.parse(stamp('11:00')), minutes: 30 }]);
});

test('all-day records, invalid timestamps and impossible calendar dates are excluded', () => {
  const invalid = [event('all', day, '2026-09-21', 'shared', { allDay: true }), event('bad-start', 'bad'), event('bad-end', undefined, 'bad'),
    event('bad-month', '2026-13-20T09:00:00+08:00'), event('bad-date', '2026-02-30T09:00:00+08:00', '2026-03-03T09:00:00+08:00')];
  assert.deepEqual(calendarConflicts([event('valid'), ...invalid], [day, '2026-03-02'], 'member1'), []);
  assert.deepEqual(calendarConflicts([event('a'), event('b')], ['bad', '2026-02-30', '2026-9-20', '2026-13-20', ''], 'member1'), []);
});

test('cross-midnight pairs are grouped once and clipped in Beijing time', () => {
  const a = event('a', '2026-09-19T23:00:00+08:00', '2026-09-21T01:00:00+08:00');
  const b = event('b', '2026-09-19T23:30:00+08:00', '2026-09-21T00:30:00+08:00');
  const [overlap] = calendarConflicts([a, b], ['2026-09-21', day, '2026-09-19', day], 'member1');
  assert.equal(overlap.minutes, 1500);
  assert.deepEqual(overlap.overlaps.map(span => [span.day, span.minutes]), [['2026-09-19', 30], [day, 1440], ['2026-09-21', 30]]);
  assert.equal(overlap.overlaps[1].start, dayStart(day));
  assert.equal(overlap.overlaps[1].end, dayStart('2026-09-21'));
  assert.equal(calendarConflicts([a, b], [day], 'member1')[0].minutes, 1440);
  assert.equal(calendarConflicts([a, b], ['2026-09-19', '2026-09-21'], 'member1')[0].minutes, 60, 'unselected day is not counted');
});

test('offsets represent instants while clipping always uses Beijing dates', () => {
  const a = event('a', '2026-09-19T15:30:00Z', '2026-09-19T17:00:00Z');
  const b = event('b', '2026-09-19T09:00:00-07:00', '2026-09-19T10:30:00-07:00');
  const [overlap] = calendarConflicts([a, b], ['2026-09-19', day], 'member1');
  assert.deepEqual(overlap.overlaps, [{ day, start: dayStart(day), end: dayStart(day) + 3_600_000, minutes: 60 }]);
  assert.deepEqual(calendarConflicts([a, b], ['2026-09-19'], 'member1'), []);
});

test('leap and year boundaries work with existing today/week/around ranges', () => {
  const leap = [event('a', '2024-02-28T23:00:00+08:00', '2024-03-01T01:00:00+08:00'), event('b', '2024-02-29T00:00:00+08:00', '2024-03-01T00:00:00+08:00')];
  assert.equal(calendarConflicts(leap, rangeDays('today', '2024-02-29'), 'member1')[0].minutes, 1440);
  const year = [event('a', '2025-12-31T23:30:00+08:00', '2026-01-01T00:30:00+08:00'), event('b', '2025-12-31T23:45:00+08:00', '2026-01-01T00:15:00+08:00')];
  for (const mode of ['week', 'around']) assert.equal(calendarConflicts(year, rangeDays(mode, '2026-01-01'), 'member1')[0].minutes, 30);
});

test('original event identity and revision are retained without changing caller data', () => {
  const a = Object.freeze(event('a', undefined, undefined, 'member1', { revision: 7 }));
  const b = Object.freeze(event('b', undefined, undefined, 'shared', { revision: 42, sync: Object.freeze({ provider: 'microsoft', readOnly: true }) }));
  const events = Object.freeze([b, a]), days = Object.freeze([day, day]);
  const [overlap] = calendarConflicts(events, days, 'member1');
  assert.equal(overlap.first, a); assert.equal(overlap.second, b);
  assert.equal(overlap.first.revision, 7); assert.equal(overlap.second.revision, 42);
  assert.equal(overlap.second.sync, b.sync);
  assert.deepEqual(events, [b, a]); assert.deepEqual(days, [day, day]);
});

test('pair keys are unambiguous, stable across ordering and do not depend on revision', () => {
  const events = ['a', 'b|c', 'a|b', 'c', 'a"b', 'c\\d'].map(id => event(id));
  const result = calendarConflicts(events, [day], 'member1');
  assert.equal(new Set(result.map(item => item.key)).size, 15);
  for (const item of result) assert.deepEqual(JSON.parse(item.key), [item.first.id, item.second.id]);
  assert.deepEqual(calendarConflicts([...events].reverse(), [day], 'member1'), result);
  const updated = events.map(item => ({ ...item, revision: 99, title: '新标题' }));
  assert.deepEqual(calendarConflicts(updated, [day], 'member1').map(item => item.key), result.map(item => item.key));
});

test('duplicate IDs never conflict with themselves or duplicate another pair', () => {
  const a = event('a'), b = event('b');
  assert.deepEqual(calendarConflicts([a, a, { ...a }], [day], 'member1'), []);
  const result = calendarConflicts([a, a, b, { ...b }], [day, day], 'member1');
  assert.equal(result.length, 1); assert.equal(result[0].minutes, 120);
  assert.equal(result[0].first, a); assert.equal(result[0].second, b);
});

test('nested and triple overlaps stay distinct pairs with stable chronological order', () => {
  const result = calendarConflicts([event('outer', stamp('08:00'), stamp('13:00')), event('z', stamp('10:00'), stamp('11:00')),
    event('a', stamp('09:00'), stamp('12:00')), event('after', stamp('13:00'), stamp('14:00'))], [day], 'member1');
  assert.deepEqual(pairs(result), [['a', 'outer'], ['a', 'z'], ['outer', 'z']]);
  assert.deepEqual(result.map(item => item.minutes), [180, 60, 60]);
  // These are minutes per pair, not workload: concurrent triples intentionally share time.
});

test('fractional-minute overlaps remain exact and a refreshed schedule removes resolved pairs', () => {
  const a = event('a', stamp('09:00'), '2026-09-20T10:00:30.500+08:00');
  const b = event('b', stamp('10:00'), stamp('11:00'));
  const [before] = calendarConflicts([a, b], [day], 'member1');
  assert.equal(before.minutes, 30.5 / 60);
  assert.deepEqual(calendarConflicts([a, { ...b, revision: 2, start: stamp('10:30') }], [day], 'member1'), []);
  assert.deepEqual(calendarConflicts([a], [day], 'member1'), []);
});
