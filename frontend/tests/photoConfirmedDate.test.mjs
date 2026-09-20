import assert from 'node:assert/strict';
import { test } from 'node:test';
import { registerHooks } from 'node:module';
registerHooks({ resolve(name, context, next) { return next(context.parentURL?.includes('/src/lib/') && /^\.\/\w+$/.test(name) ? name + '.ts' : name, context); } });
const { isConfirmedDate, confirmedDateBody } = await import('../src/lib/photoConfirmedDate.ts');
const { validatePhoto } = await import('../src/lib/photos.ts');
const { readPhotoJourneySuggestions: suggestions, photoSuggestionBody } = await import('../src/lib/photoJourneySuggestions.ts');
const { readPhotoMemories: memories, unknownMemoryDates, memoryDisplayDate, memoryDateLabel } = await import('../src/lib/photoMemories.ts');
const id = n => n.toString(16).padStart(24, '0');
const photo = (n = 1) => ({ id: id(n), revision: 7, caption: '合成照片', width: 600, height: 400,
  previewUrl: `/api/media/items/${id(n)}/preview`, visibility: 'private', canManage: true, createdAt: '2026-09-21T00:00:00Z',
  source: 'local-upload', sourceCreatedAt: null, sourceTimeState: 'unknown', journey: null, mediaType: 'photo', userConfirmedDate: '2016-02-29' });
const suggestionPage = p => ({ version: 2, photoId: p.id, photoRevision: p.revision, sourceTimeState: p.sourceTimeState,
  sourceCreatedAt: p.sourceCreatedAt, userConfirmedDate: p.userConfirmedDate, dateBasis: 'userConfirmedDate', currentJourneyId: null,
  limit: 20, hasMore: false, reason: { code: 'date_overlap', message: '日期相符' }, suggestions: [{ journeyId: id(2), journeyRevision: 3,
    tripRevision: 2, title: '合成旅行', start: '2016-02-28', end: '2016-03-01', matchDate: '2016-02-29',
    referenceTimezone: 'America/Los_Angeles', referenceTimezoneSource: 'plan', alreadyLinked: false, reason: { code: 'date_overlap', message: '日期相符' } }] });
const memoryPage = p => ({ version: 2, datePolicy: 'confirmed-or-source', referenceDate: '2024-02-29', referenceTimezone: 'Asia/Shanghai',
  scope: 'mine', items: [{ item: p, displayDate: p.userConfirmedDate, dateBasis: 'userConfirmedDate', yearsAgo: 8 }],
  total: 1, limit: 24, offset: 0, hasMore: false, unknownSourceTimeCount: 5, unknownEffectiveDateCount: 4 });

test('literal Gregorian dates cover years 0001..9999 without JS instant conversion', () => {
  for (const d of ['0001-01-01', '0099-12-31', '2000-02-29', '2016-02-29', '9999-12-31']) assert.equal(isConfirmedDate(d), true, d);
  for (const d of ['', '0000-01-01', '1900-02-29', '2023-02-29', '2024-04-31', '2024-00-01', '2024-01-00', '10000-01-01', '2024-1-01', ' 2024-01-01', '2024-01-01T00:00:00Z', null]) assert.equal(isConfirmedDate(d), false, String(d));
});
test('date body is independent and only owner saved-local detail is eligible', () => {
  assert.deepEqual(confirmedDateBody(photo(), '0001-01-01'), { revision: 7, userConfirmedDate: '0001-01-01' });
  assert.deepEqual(confirmedDateBody(photo(), null), { revision: 7, userConfirmedDate: null });
  for (const patch of [{ canManage: false }, { source: 'google-photos' }, { mediaType: 'video' }, { revision: 0 }])
    assert.throws(() => confirmedDateBody({ ...photo(), ...patch }, '2016-02-29'));
  assert.throws(() => confirmedDateBody(photo(), ''));
});
test('owner DTO accepts null and literal date, but never a date field on shared DTOs or an ineligible manual date', () => {
  assert.equal(validatePhoto(photo()).userConfirmedDate, '2016-02-29');
  assert.equal(validatePhoto({ ...photo(), userConfirmedDate: null, source: 'google-photos' }).userConfirmedDate, null);
  for (const patch of [{ canManage: false }, { canManage: false, userConfirmedDate: null }, { source: 'google-photos' }, { userConfirmedDate: '2023-02-29' }])
    assert.throws(() => validatePhoto({ ...photo(), ...patch }));
});
test('v2 suggestions bind original ID/revision and manual date without changing for trip timezone', () => {
  const p = photo(), raw = suggestionPage(p), parsed = suggestions(raw, p); assert.deepEqual(parsed, raw);
  assert.equal(parsed.suggestions[0].matchDate, '2016-02-29');
  assert.deepEqual(photoSuggestionBody(p, parsed, id(2)), { revision: 7, journeyId: id(2), expectedJourneyRevision: 3, expectedTripRevision: 2 });
  assert.throws(() => photoSuggestionBody({ ...p, revision: 8 }, parsed, id(2)));
  for (const change of [v => v.suggestions[0].matchDate = '2016-02-28', v => v.suggestions[0].sourceDate = '2016-02-29',
    v => v.userConfirmedDate = '2016-02-28', v => v.dateBasis = 'sourceCreatedAt', v => v.version = 3]) {
    const v = structuredClone(raw); change(v); assert.throws(() => suggestions(v, p));
  }
});
test('v2 source/unknown paths retain source instant and require explicit date_unknown when neither exists', () => {
  const p = { ...photo(), source: 'google-photos', userConfirmedDate: null, sourceTimeState: 'known', sourceCreatedAt: '2016-02-29T23:30:00-08:00' };
  const raw = { ...suggestionPage(p), dateBasis: 'sourceCreatedAt' };
  assert.equal(suggestions(raw, p).sourceCreatedAt, p.sourceCreatedAt);
  const unknown = { ...photo(), userConfirmedDate: null };
  const empty = { ...suggestionPage(unknown), dateBasis: 'unknown', suggestions: [], reason: { code: 'date_unknown', message: '日期未知' } };
  assert.deepEqual(suggestions(empty, unknown), empty);
  assert.throws(() => suggestions({ ...empty, suggestions: raw.suggestions }, unknown));
});
test('v2 memories counts exclusion by effective date, labels manual, keeps original IDs and year 0001', () => {
  const page = memoryPage(photo()); assert.deepEqual(memories(page, 0), page);
  assert.equal(unknownMemoryDates(page), 4); assert.equal(memoryDisplayDate(page.items[0]), '2016-02-29');
  assert.equal(memoryDateLabel(page.items[0]), '本人确认日期');
  const ancient = memoryPage({ ...photo(), userConfirmedDate: '0001-01-01' }); ancient.referenceDate = '9999-01-01'; ancient.items[0].yearsAgo = 9998;
  assert.equal(memories(ancient, 0).items[0].displayDate, '0001-01-01');
});
test('v2 memories rejects source fallback when manual exists, old row keys, bad dates/basis/counts/sorting and nonowners', () => {
  for (const change of [v => v.items[0].dateBasis = 'sourceCreatedAt', v => v.items[0].sourceLocalDate = '2016-02-29',
    v => v.items[0].displayDate = '2016-02-28', v => v.unknownEffectiveDateCount = 6, v => v.dateBasis = 'sourceCreatedAt',
    v => v.items[0].item.canManage = false, v => v.referenceDate = '2023-02-29']) {
    const v = memoryPage(photo()); change(v); assert.throws(() => memories(v, 0));
  }
  const p = { ...photo(), source: 'google-photos', userConfirmedDate: null, sourceCreatedAt: '2016-02-28T18:00:00Z', sourceTimeState: 'known' };
  const v = memoryPage(p); v.items[0].displayDate = '2016-02-29'; v.items[0].dateBasis = 'sourceCreatedAt';
  assert.equal(memoryDateLabel(memories(v, 0).items[0]), '来源日期');
  const second = structuredClone(v.items[0]); second.item = { ...p, id: id(2), previewUrl: `/api/media/items/${id(2)}/preview` };
  assert.throws(() => memories({ ...v, items: [second, v.items[0]], total: 2 }, 0));
});
