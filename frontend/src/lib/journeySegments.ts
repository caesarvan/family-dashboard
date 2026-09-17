/** Existing-journey v2 editing. UTC/DST normalization belongs to the server. */
export type TimePoint = { local: string; timeZone: string; offsetMinutes?: number; instant?: string };
export type Destination = { key: string; country: string; city: string; arrival: string; departure: string; timeZone: string };
export type SegmentBase = { key: string; title: string; location: string; note: string; destinationKey?: string; bookingState: 'idea' | 'booked' | 'cancelled'; datePolicy: 'fixed' | 'shift_with_trip' };
export type Flight = SegmentBase & { kind: 'flight'; flightNumber: string; departure: TimePoint & { airport: string; city: string }; arrival: TimePoint & { airport: string; city: string } };
export type Stay = SegmentBase & { kind: 'stay'; propertyName: string; address: string; timeZone: string; checkInDate: string; checkOutDate: string; checkInTime: string; checkOutTime: string; checkInOffsetMinutes?: number; checkOutOffsetMinutes?: number; checkInInstant?: string; checkOutInstant?: string; nights?: number };
export type TimedActivity = SegmentBase & { kind: 'activity'; start: TimePoint; end: TimePoint; dateRange?: never; timeZone?: never };
export type DayActivity = SegmentBase & { kind: 'activity'; dateRange: { startDate: string; endDateExclusive: string }; timeZone: string; start?: never; end?: never };
export type LegacyDay = SegmentBase & { kind: 'legacy_day'; start: string; end: string };
export type Segment = Flight | Stay | TimedActivity | DayActivity | LegacyDay;
export type LegacySegment = { key: string; title: string; location: string; note: string; start: string; end: string };
export type Preparation = { key: string; title: string; owner: string; due: string; dueOffsetDays: number; note: string; category: string };
export type Purchase = { key: string; title: string; owner: string; quantity: string; budget: number | null; note: string };
type PlanBase = { title: string; start: string; end: string; international: boolean; memberIds: string[]; budget: number; saved: number; paid: number; note: string; checklist: Preparation[]; shopping: Purchase[] };
export type JourneyPlanV1 = PlanBase & { schemaVersion?: 1; destinations: Omit<Destination, 'timeZone'>[]; segments: LegacySegment[] };
export type JourneyPlanV2 = PlanBase & { schemaVersion: 2; referenceTimezone: string; destinations: Destination[]; segments: Segment[] };
export type JourneyPlan = JourneyPlanV1 | JourneyPlanV2;
export type Capabilities = { schemaVersions: (1 | 2)[]; editSourceSnapshot: boolean; canWriteV2: boolean };
type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type JsonObject = { [key: string]: Json };
export type LinkedRecord = JsonObject & { id: string; revision: number; workflowKey: string };
export type JourneyDetail = { id: string; tripId: string; revision: number; plan: JourneyPlan; trip: LinkedRecord | null; tasks: LinkedRecord[]; shopping: LinkedRecord[]; events: LinkedRecord[]; policyNotice: string };
export type SegmentDraft = { journeyId: string; tripId: string; revision: number; sourceVersion: 1 | 2; plan: JourneyPlan; observed: string; expectedEntities: Record<string, number> };
export type ConflictGroup = 'timing' | 'title' | 'location' | 'note' | 'owner';
export type ConflictResolutions = Record<string, Partial<Record<ConflictGroup, 'current' | 'plan'>>>;
export type Conflict = { itemKey: string; entityId: string; fieldGroup: ConflictGroup; base: JsonObject; current: JsonObject; proposed: JsonObject; choices: ['current', 'plan']; resolution?: 'current' | 'plan' };
export type SegmentPreview = { plan: JourneyPlanV2; canApply: boolean; previewToken: string | null; expiresIn: number; summary: { create: Record<string, number>; update: Record<string, number>; detach: number; policyNotice: string; calendar: string; removedItems: string; conflicts: Conflict[]; preserved: Conflict[]; resolved: Conflict[]; cloudReviews: { itemKey: string; entityId: string; message: string }[]; warnings: (JsonObject & { code: string; itemKey: string; message: string })[] } };
export type SegmentIntent = { body: Readonly<{ previewToken: string; idempotencyKey: string }>; journeyId: string; tripId: string; revision: number; uncertain: boolean };
export type SegmentReceipt = { id: string; tripId: string; revision: number; replayed: boolean; calendar: { local: 'created'; cloud: 'not_requested'; icsUrl: string } };
export type TimeIssue = { error: string; code: string; field: string; choices: { offsetMinutes: number; instant: string }[]; draftFingerprint: string };
export class SegmentError extends Error { constructor(message: string, public status = 0, public body?: unknown) { super(message); } }
export class SegmentDiscarded extends Error {}
export class SegmentRejected extends SegmentError {}
class SegmentResponseError extends SegmentError {}
function bad(): never { throw new SegmentError('行程数据无法核对，请保留草稿并重新读取。'); }
const object = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const text = (v: unknown, max = 100, empty = false): string => typeof v === 'string' && Array.from(v).length <= max && (empty || !!v.trim()) && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v) ? v : bad();
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min && v <= max ? v : bad();
const money = (v: unknown) => integer(v, 0, 100_000_000_000);
const bool = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const array = (v: unknown, max = 100): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
const unique = <T>(items: T[], key: (item: T) => string): T[] => new Set(items.map(key)).size === items.length ? items : bad();
const one = <T extends string>(v: unknown, values: readonly T[]): T => typeof v === 'string' && values.includes(v as T) ? v as T : bad();
const fields = (v: Record<string, unknown>, allowed: string[]) => { if (Object.keys(v).some(k => !allowed.includes(k))) bad(); };
const key = (v: unknown): string => typeof v === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(v) ? v : bad();
const id = (v: unknown): string => typeof v === 'string' && /^[a-f0-9]{24}$/.test(v) ? v : bad();
const operationKey = (v: unknown): string => typeof v === 'string' && /^[A-Za-z0-9_-]{8,80}$/.test(v) ? v : bad();
const eventKey = (v: unknown): string => v === 'event:overview' ? v : typeof v === 'string' && /^segment:[A-Za-z0-9_-]{1,64}$/.test(v) ? v : bad();
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v));
export function validSegmentDay(v: unknown): v is string { if (typeof v !== 'string' || !/^(20\d\d|2100)-\d\d-\d\d$/.test(v)) return false; const d = new Date(v + 'T00:00:00Z'); return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === v; }
const day = (v: unknown) => validSegmentDay(v) ? v : bad();
const timezone = (v: unknown) => { const s = text(v, 100); if (!/^[A-Za-z0-9_+.-]+(?:\/[A-Za-z0-9_+.-]+)*$/.test(s) || s.split('/').some(x => x === '.' || x === '..')) bad(); return s; };
const local = (v: unknown) => { const s = text(v, 19); if (!/^\d{4}-\d\d-\d\dT(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(s)) bad(); day(s.slice(0, 10)); return s; };
const instant = (v: unknown) => { const s = text(v, 30); if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(s) || !Number.isFinite(Date.parse(s)) || new Date(s).toISOString().replace('.000Z', 'Z') !== s) bad(); return s; };
const clock = (v: unknown) => { const s = text(v, 5, true); if (s && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(s)) bad(); return s; };
function json(v: unknown, depth = 0): Json { if (depth > 12) bad(); if (v === null || typeof v === 'boolean') return v; if (typeof v === 'string') return text(v, 20_000, true); if (typeof v === 'number') return Number.isFinite(v) ? v : bad(); if (Array.isArray(v)) return array(v, 1000).map(x => json(x, depth + 1)); const o = object(v); if (Object.keys(o).length > 100 || Object.keys(o).some(k => ['__proto__', 'prototype', 'constructor'].includes(k))) bad(); return Object.fromEntries(Object.entries(o).map(([k, x]) => [k, json(x, depth + 1)])); }
const jsonObject = (v: unknown) => { object(v); return json(v) as JsonObject; };
function point(v: unknown, normalized: boolean, airport = false): TimePoint & { airport?: string; city?: string } {
  const r = object(v); fields(r, ['local', 'timeZone', 'offsetMinutes', 'instant', ...(airport ? ['airport', 'city'] : [])]);
  const out: TimePoint & { airport?: string; city?: string } = { local: local(r.local), timeZone: timezone(r.timeZone) };
  if (r.offsetMinutes !== undefined) out.offsetMinutes = integer(r.offsetMinutes, -840, 840);
  if (r.instant !== undefined) out.instant = instant(r.instant);
  if (normalized && (out.offsetMinutes === undefined || out.instant === undefined)) bad();
  if (airport) Object.assign(out, { airport: text(r.airport, 80, true), city: text(r.city, 80, true) });
  return out;
}
const baseFields = ['key', 'kind', 'title', 'location', 'note', 'destinationKey', 'bookingState', 'datePolicy'];
export function readSegment(v: unknown, normalized = false): Segment {
  const r = object(v), kind = one(r.kind, ['flight', 'stay', 'activity', 'legacy_day'] as const);
  const base: SegmentBase = { key: key(r.key), title: text(r.title), location: text(r.location, 200, true), note: text(r.note, 500, true), bookingState: one(r.bookingState, ['idea', 'booked', 'cancelled']), datePolicy: one(r.datePolicy, ['fixed', 'shift_with_trip']) };
  if (r.destinationKey !== undefined) base.destinationKey = key(r.destinationKey);
  if (kind === 'flight') { fields(r, [...baseFields, 'flightNumber', 'departure', 'arrival']); const departure = point(r.departure, normalized, true) as Flight['departure'], arrival = point(r.arrival, normalized, true) as Flight['arrival']; if (normalized && arrival.instant! <= departure.instant!) bad(); return { ...base, kind, flightNumber: text(r.flightNumber, 40, true), departure, arrival }; }
  if (kind === 'stay') {
    fields(r, [...baseFields, 'propertyName', 'address', 'timeZone', 'checkInDate', 'checkOutDate', 'checkInTime', 'checkOutTime', 'checkInOffsetMinutes', 'checkOutOffsetMinutes', 'checkInInstant', 'checkOutInstant', 'nights']);
    const s: Stay = { ...base, kind, propertyName: text(r.propertyName, 150, true), address: text(r.address, 300, true), timeZone: timezone(r.timeZone), checkInDate: day(r.checkInDate), checkOutDate: day(r.checkOutDate), checkInTime: clock(r.checkInTime), checkOutTime: clock(r.checkOutTime) };
    if (s.checkOutDate <= s.checkInDate) bad();
    if (r.nights !== undefined) s.nights = integer(r.nights, 1, 36889);
    if (normalized && s.nights !== (Date.parse(s.checkOutDate) - Date.parse(s.checkInDate)) / 86400000) bad();
    for (const prefix of ['checkIn', 'checkOut'] as const) { const offset = r[`${prefix}OffsetMinutes`], utc = r[`${prefix}Instant`]; if (!s[`${prefix}Time`] && (offset !== undefined || utc !== undefined)) bad(); if (offset !== undefined) s[`${prefix}OffsetMinutes`] = integer(offset, -840, 840); if (utc !== undefined) s[`${prefix}Instant`] = instant(utc); if (normalized && s[`${prefix}Time`] && (offset === undefined || utc === undefined)) bad(); }
    return s;
  }
  if (kind === 'activity' && r.dateRange !== undefined) { fields(r, [...baseFields, 'dateRange', 'timeZone']); const dr = object(r.dateRange); fields(dr, ['startDate', 'endDateExclusive']); const range = { startDate: day(dr.startDate), endDateExclusive: day(dr.endDateExclusive) }; if (range.endDateExclusive <= range.startDate) bad(); return { ...base, kind, dateRange: range, timeZone: timezone(r.timeZone) }; }
  if (kind === 'activity') { fields(r, [...baseFields, 'start', 'end']); const start = point(r.start, normalized), end = point(r.end, normalized); if (normalized && end.instant! <= start.instant!) bad(); return { ...base, kind, start, end }; }
  fields(r, [...baseFields, 'start', 'end']); const start = day(r.start), end = day(r.end); if (end < start) bad(); return { ...base, kind, start, end };
}
export function readPlan(v: unknown, normalized = false): JourneyPlan {
  const r = object(v), version = r.schemaVersion === undefined ? 1 : integer(r.schemaVersion, 1, 2);
  fields(r, ['schemaVersion', 'title', 'start', 'end', 'international', 'memberIds', 'budget', 'saved', 'paid', 'note', 'destinations', 'checklist', 'shopping', 'segments', ...(version === 2 ? ['referenceTimezone'] : [])]);
  const start = day(r.start), end = day(r.end); if (end < start || (Date.parse(end) - Date.parse(start)) / 86400000 > 366) bad();
  const common: PlanBase = { title: text(r.title), start, end, international: bool(r.international), memberIds: unique(array(r.memberIds, 100).map(x => text(x, 100)), x => x), budget: money(r.budget), saved: money(r.saved), paid: money(r.paid), note: text(r.note, 2000, true),
    checklist: unique(array(r.checklist).map(v => { const x = object(v); fields(x, ['key', 'title', 'owner', 'due', 'dueOffsetDays', 'note', 'category']); return { key: key(x.key), title: text(x.title), owner: text(x.owner, 100), due: day(x.due), dueOffsetDays: integer(x.dueOffsetDays, -36889, 36889), note: text(x.note, 500, true), category: text(x.category, 40) }; }), x => x.key),
    shopping: unique(array(r.shopping).map(v => { const x = object(v); fields(x, ['key', 'title', 'owner', 'quantity', 'budget', 'note']); return { key: key(x.key), title: text(x.title), owner: text(x.owner, 100), quantity: text(x.quantity, 30), budget: x.budget === null ? null : money(x.budget), note: text(x.note, 500, true) }; }), x => x.key) };
  if (!common.memberIds.length) bad();
  const destinations = unique(array(r.destinations, 20).map(v => { const x = object(v); fields(x, ['key', 'country', 'city', 'arrival', 'departure', ...(version === 2 ? ['timeZone'] : [])]); const d = { key: key(x.key), country: text(x.country, 60, true), city: text(x.city, 80), arrival: day(x.arrival), departure: day(x.departure) }; if (d.departure < d.arrival) bad(); return version === 2 ? { ...d, timeZone: timezone(x.timeZone) } : d; }), x => x.key);
  if (!destinations.length) bad();
  if (version === 1) return { ...common, ...(r.schemaVersion === 1 ? { schemaVersion: 1 as const } : {}), destinations, segments: unique(array(r.segments).map(v => { const x = object(v); fields(x, ['key', 'title', 'location', 'note', 'start', 'end']); const start = day(x.start), end = day(x.end); if (end < start) bad(); return { key: key(x.key), title: text(x.title), location: text(x.location, 200, true), note: text(x.note, 500, true), start, end }; }), x => x.key) };
  const segments = unique(array(r.segments).map(x => readSegment(x, normalized)), x => x.key);
  if (segments.some(s => s.destinationKey && !destinations.some(d => d.key === s.destinationKey))) bad();
  return { ...common, schemaVersion: 2, referenceTimezone: timezone(r.referenceTimezone), destinations: destinations as Destination[], segments };
}
export function readCapabilities(raw: unknown): Capabilities { const r = object(raw), c = r.capabilities === undefined ? {} : object(r.capabilities); const values = r.supportedSchemaVersions ?? c.schemaVersions ?? []; const schemaVersions = unique(array(values, 2).map(v => integer(v, 1, 2) as 1 | 2), String); const editSourceSnapshot = c.editSourceSnapshot === undefined ? false : bool(c.editSourceSnapshot); return { schemaVersions, editSourceSnapshot, canWriteV2: schemaVersions.includes(2) && editSourceSnapshot }; }
function linked(v: unknown): LinkedRecord { const r = jsonObject(v); return { ...r, id: id(r.id), revision: integer(r.revision, 1), workflowKey: text(r.workflowKey, 100) }; }
export function readJourneyDetail(raw: unknown, expectedId?: string): JourneyDetail {
  const r = object(raw), uid = id(r.id); if (expectedId !== undefined && uid !== id(expectedId)) bad();
  const d: JourneyDetail = { id: uid, tripId: id(r.tripId), revision: integer(r.revision, 1), plan: readPlan(r.plan, true), trip: r.trip === null ? null : linked(r.trip), tasks: array(r.tasks).map(linked), shopping: array(r.shopping).map(linked), events: array(r.events, 101).map(linked), policyNotice: text(r.policyNotice, 4000) };
  const all = [...(d.trip ? [d.trip] : []), ...d.tasks, ...d.shopping, ...d.events]; unique(all, x => x.id); unique(all, x => x.workflowKey);
  if (d.trip && (d.trip.id !== d.tripId || d.trip.workflowKey !== 'trip') || d.tasks.some(x => !/^task:[A-Za-z0-9_-]{1,64}$/.test(x.workflowKey)) || d.shopping.some(x => !/^shopping:[A-Za-z0-9_-]{1,64}$/.test(x.workflowKey))) bad(); d.events.forEach(x => eventKey(x.workflowKey));
  return d;
}
export const detailFingerprint = (d: JourneyDetail) => JSON.stringify([d.id, d.tripId, d.revision, [...(d.trip ? [d.trip] : []), ...d.tasks, ...d.shopping, ...d.events].map(x => [x.id, x.revision]).sort((a, b) => String(a[0]).localeCompare(String(b[0])))]);
export function editSegmentDraft(detail: JourneyDetail): SegmentDraft {
  const d = readJourneyDetail(detail), plan = copy(d.plan), t = d.trip;
  if (!t) throw new SegmentError('关联旅行已不存在，请重新核对。');
  for (const [rows, records, prefix, label] of [[plan.checklist, d.tasks, 'task:', '准备事项'], [plan.shopping, d.shopping, 'shopping:', '采购事项']] as const) {
    if (rows.length !== records.length || rows.some(row => !records.some(record => record.workflowKey === prefix + row.key))) throw new SegmentError(`关联${label}已被单独删除或解除关联，请先核对旅行清单，再编辑详细行程。`);
  }
  if (d.tasks.some(record => !record.due)) throw new SegmentError('关联准备事项已被单独清空截止日期，请先核对旅行清单，再编辑详细行程。');
  Object.assign(plan, { title: text(t.title), start: day(t.start), end: day(t.end), budget: money(t.budget), saved: money(t.saved), paid: money(t.paid), note: text(t.note ?? '', 2000, true) });
  plan.checklist = plan.checklist.map(row => { const live = d.tasks.find(x => x.workflowKey === 'task:' + row.key); return live ? { ...row, title: text(live.title), owner: text(live.owner, 100), due: day(live.due), note: text(live.note ?? '', 500, true) } : row; });
  plan.shopping = plan.shopping.map(row => { const live = d.shopping.find(x => x.workflowKey === 'shopping:' + row.key); return live ? { ...row, title: text(live.title), owner: text(live.owner, 100), quantity: text(live.quantity ?? row.quantity, 30), budget: live.budget === null || live.budget === undefined ? null : money(live.budget), note: text(live.note ?? '', 500, true) } : row; });
  return { journeyId: d.id, tripId: d.tripId, revision: d.revision, sourceVersion: d.plan.schemaVersion === 2 ? 2 : 1, observed: detailFingerprint(d), expectedEntities: Object.fromEntries([t, ...d.tasks, ...d.shopping, ...d.events].map(x => [x.id, x.revision])), plan };
}
export function upgradeToV2(draft: SegmentDraft, referenceTimezone: string, destinationTimeZones: Record<string, string>, capabilities: Capabilities): SegmentDraft {
  if (!capabilities.canWriteV2 || !capabilities.editSourceSnapshot || !capabilities.schemaVersions.includes(2) || draft.plan.schemaVersion === 2) bad();
  const p = readPlan(draft.plan); if (p.schemaVersion === 2 || Object.keys(destinationTimeZones).sort().join('|') !== p.destinations.map(d => d.key).sort().join('|')) bad();
  return { ...copy(draft), plan: { ...p, schemaVersion: 2, referenceTimezone: timezone(referenceTimezone), destinations: p.destinations.map(d => ({ ...d, timeZone: timezone(destinationTimeZones[d.key]) })), segments: p.segments.map(s => ({ ...s, kind: 'legacy_day', bookingState: 'idea', datePolicy: 'shift_with_trip' })) } };
}
export function rebaseSegmentDraft(draft: SegmentDraft, latest: JourneyDetail): SegmentDraft { const next = editSegmentDraft(latest); if (next.journeyId !== draft.journeyId || next.tripId !== draft.tripId || draft.plan.schemaVersion !== 2) bad(); return { ...next, plan: { ...next.plan, schemaVersion: 2, referenceTimezone: draft.plan.referenceTimezone, destinations: copy(draft.plan.destinations), segments: copy(draft.plan.segments) } }; }
function resolutions(raw: unknown): ConflictResolutions { const out: ConflictResolutions = {}; const r = object(raw); if (Object.keys(r).length > 101) bad(); for (const [k, value] of Object.entries(r)) { eventKey(k); const groups = object(value); fields(groups, ['timing', 'title', 'location', 'note', 'owner']); out[k] = Object.fromEntries(Object.entries(groups).map(([g, v]) => [g, one(v, ['current', 'plan'])])); } return out; }
export function previewPayload(draft: SegmentDraft, capabilities: Capabilities, memberIds: readonly string[], conflictResolutions: ConflictResolutions = {}) {
  if (!capabilities.canWriteV2 || !capabilities.editSourceSnapshot || !capabilities.schemaVersions.includes(2) || draft.plan.schemaVersion !== 2) throw new SegmentError('服务尚未声明 v2 编辑快照能力，或需要先明确升级。');
  const plan = readPlan(draft.plan); if (plan.schemaVersion !== 2 || plan.memberIds.some(x => !memberIds.includes(x)) || [...plan.checklist, ...plan.shopping].some(x => x.owner !== 'shared' && !memberIds.includes(x.owner))) bad();
  const expectedEntities = Object.fromEntries(Object.entries(object(draft.expectedEntities)).map(([uid, rev]) => [id(uid), integer(rev, 1)]));
  if (!Object.hasOwn(expectedEntities, draft.tripId) || Object.keys(expectedEntities).length > 302 || draft.observed !== JSON.stringify([draft.journeyId, draft.tripId, draft.revision, Object.entries(expectedEntities).sort((a, b) => a[0].localeCompare(b[0]))])) bad();
  return { journeyId: id(draft.journeyId), revision: integer(draft.revision, 1), expectedEntities, plan, conflictResolutions: resolutions(conflictResolutions) };
}
const groups = ['timing', 'title', 'location', 'note', 'owner'] as const;
function conflict(v: unknown): Conflict { const r = object(v); if (JSON.stringify(r.choices) !== '["current","plan"]') bad(); const c: Conflict = { itemKey: eventKey(r.itemKey), entityId: id(r.entityId), fieldGroup: one(r.fieldGroup, groups), base: jsonObject(r.base), current: jsonObject(r.current), proposed: jsonObject(r.proposed), choices: ['current', 'plan'] }; if (r.resolution !== undefined) c.resolution = one(r.resolution, ['current', 'plan'] as const); return c; }
function counts(v: unknown): Record<string, number> { const r = object(v); fields(r, ['trips', 'events', 'tasks', 'shopping']); return Object.fromEntries(Object.entries(r).map(([k, n]) => [k, integer(n, 0, 101)])); }
export function readSegmentPreview(raw: unknown): SegmentPreview {
  const r = object(raw), s = object(r.summary), plan = readPlan(r.plan, true); if (plan.schemaVersion !== 2) bad(); const canApply = bool(r.canApply), token = r.previewToken === null ? null : text(r.previewToken, 500000); const conflicts = array(s.conflicts, 404).map(conflict);
  if (canApply !== (conflicts.length === 0) || canApply && !token || !canApply && token !== null) bad();
  return { plan, canApply, previewToken: token, expiresIn: integer(r.expiresIn, 1, 1800), summary: { create: counts(s.create), update: counts(s.update), detach: integer(s.detach, 0, 302), policyNotice: text(s.policyNotice, 4000), calendar: text(s.calendar, 4000), removedItems: text(s.removedItems, 4000), conflicts, preserved: array(s.preserved, 404).map(conflict), resolved: array(s.resolved, 404).map(v => { const c = conflict(v); if (!c.resolution) bad(); return c; }), cloudReviews: array(s.cloudReviews, 101).map(v => { const x = object(v); return { itemKey: eventKey(x.itemKey), entityId: id(x.entityId), message: text(x.message, 4000) }; }), warnings: array(s.warnings, 500).map(v => { const x = jsonObject(v); return { ...x, code: text(x.code, 80), itemKey: text(x.itemKey, 100), message: text(x.message, 4000) }; }) } };
}
export function newSegmentKey(): string { if (!globalThis.crypto?.getRandomValues) throw new SegmentError('当前环境无法生成安全编号。'); return Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join(''); }
export function newDestination(itemKey = newSegmentKey()): Destination { return { key: key(itemKey), country: '', city: '', arrival: '', departure: '', timeZone: '' }; }
export function newSegment(kind: Segment['kind'], itemKey = newSegmentKey()): Segment { const b: SegmentBase = { key: key(itemKey), title: '', location: '', note: '', bookingState: 'idea', datePolicy: kind === 'flight' ? 'fixed' : 'shift_with_trip' }; if (kind === 'flight') return { ...b, kind, flightNumber: '', departure: { local: '', timeZone: '', airport: '', city: '' }, arrival: { local: '', timeZone: '', airport: '', city: '' } }; if (kind === 'stay') return { ...b, kind, propertyName: '', address: '', timeZone: '', checkInDate: '', checkOutDate: '', checkInTime: '', checkOutTime: '' }; if (kind === 'activity') return { ...b, kind, dateRange: { startDate: '', endDateExclusive: '' }, timeZone: '' }; if (kind === 'legacy_day') return { ...b, kind, start: '', end: '' }; return bad(); }
export function updateTimePoint<T extends TimePoint>(point: T, patch: Partial<Pick<TimePoint, 'local' | 'timeZone'>>): T { fields(patch, ['local', 'timeZone']); const out = { ...point, ...patch }; if (out.local !== point.local || out.timeZone !== point.timeZone) { delete out.instant; delete out.offsetMinutes; } return out; }
export function updateStayTiming(stay: Stay, patch: Partial<Pick<Stay, 'timeZone' | 'checkInDate' | 'checkOutDate' | 'checkInTime' | 'checkOutTime'>>): Stay { fields(patch, ['timeZone', 'checkInDate', 'checkOutDate', 'checkInTime', 'checkOutTime']); const out = { ...stay, ...patch }; for (const p of ['checkIn', 'checkOut'] as const) if (out.timeZone !== stay.timeZone || out[`${p}Date`] !== stay[`${p}Date`] || out[`${p}Time`] !== stay[`${p}Time`]) { delete out[`${p}Instant`]; delete out[`${p}OffsetMinutes`]; } if (out.checkInDate !== stay.checkInDate || out.checkOutDate !== stay.checkOutDate) delete out.nights; return out; }
export function readTimeIssue(raw: unknown, draft: SegmentDraft): TimeIssue { const r = object(raw); return { error: text(r.error, 4000), code: text(r.code, 80), field: text(r.field, 200), choices: unique(array(r.choices, 2).map(v => { const x = object(v); return { offsetMinutes: integer(x.offsetMinutes, -840, 840), instant: instant(x.instant) }; }), x => String(x.offsetMinutes)), draftFingerprint: JSON.stringify(draft.plan) }; }
export function applyTimeChoice(draft: SegmentDraft, issue: TimeIssue, offset: number): SegmentDraft { if (issue.draftFingerprint !== JSON.stringify(draft.plan) || !issue.choices.some(c => c.offsetMinutes === offset) || draft.plan.schemaVersion !== 2) bad(); const match = /^segments\[(\d+)\]\.(departure|arrival|start|end|checkInTime|checkOutTime)$/.exec(issue.field); if (!match) bad(); const next = copy(draft), segment = (next.plan as JourneyPlanV2).segments[Number(match[1])]; if (!segment) bad(); const field = match[2]; if (segment.kind === 'stay' && (field === 'checkInTime' || field === 'checkOutTime')) { const prefix = field === 'checkInTime' ? 'checkIn' : 'checkOut'; if (!segment[field]) bad(); segment[`${prefix}OffsetMinutes`] = offset; delete segment[`${prefix}Instant`]; } else if (segment.kind === 'flight' && (field === 'departure' || field === 'arrival')) { segment[field].offsetMinutes = offset; delete segment[field].instant; } else if (segment.kind === 'activity' && !segment.dateRange && (field === 'start' || field === 'end')) { segment[field].offsetMinutes = offset; delete segment[field].instant; } else bad(); return next; }
export function createSegmentIntent(preview: SegmentPreview, draft: SegmentDraft, requestKey = newSegmentKey()): SegmentIntent { if (!preview.canApply || !preview.previewToken) bad(); return { journeyId: id(draft.journeyId), tripId: id(draft.tripId), revision: integer(draft.revision, 1), uncertain: false, body: Object.freeze({ previewToken: text(preview.previewToken, 500000), idempotencyKey: operationKey(requestKey) }) }; }
export function readSegmentReceipt(raw: unknown, intent: SegmentIntent): SegmentReceipt { const r = object(raw), c = object(r.calendar); if (r.operation !== undefined || id(r.id) !== intent.journeyId || id(r.tripId) !== intent.tripId || integer(r.revision, 1) !== intent.revision + 1 || c.local !== 'created' || c.cloud !== 'not_requested' || c.icsUrl !== `/api/journeys/${intent.journeyId}/calendar.ics`) bad(); return { id: r.id as string, tripId: r.tripId as string, revision: r.revision as number, replayed: bool(r.replayed), calendar: { local: 'created', cloud: 'not_requested', icsUrl: c.icsUrl as string } }; }
export function readSegmentOperation(raw: unknown, intent: SegmentIntent): SegmentReceipt { const r = object(raw); if (r.found !== true || r.idempotencyKey !== intent.body.idempotencyKey) bad(); return readSegmentReceipt({ ...object(r.result), replayed: true }, intent); }
export const failedSegmentIntent = (intent: SegmentIntent, error: unknown): SegmentIntent | null => intent.uncertain || !(error instanceof SegmentRejected) ? { ...intent, uncertain: true } : null;
export type SegmentSession = { user: { role: 'member' | 'tv'; householdId?: string; id: string; auth_version?: number } | null; csrf?: string | null };
export type SegmentGuard = <T>(job: (csrf: string) => Promise<T>) => Promise<T>;
export const segmentSignature = (s: SegmentSession) => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id, s.user?.auth_version, s.csrf]);
export class SegmentFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<SegmentSession>, job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (s: SegmentSession) => { if (epoch !== this.epoch || !current()) throw new SegmentDiscarded(); if (!s || s.user?.role !== 'member' || typeof s.user.id !== 'string' || !s.user.id || typeof s.user.householdId !== 'string' || !s.user.householdId || !Number.isSafeInteger(s.user.auth_version) || Number(s.user.auth_version) < 1 || typeof s.csrf !== 'string' || !s.csrf || segmentSignature(s) !== this.expected) throw new SegmentDiscarded('identity'); return s.csrf; };
    const csrf = check(await me()); let value!: T, failed = false, error: unknown; try { value = await job(csrf); } catch (e) { failed = true; error = e; } check(await me()); if (failed) throw error; return value;
  }
}
export async function checkedSegmentWrite<T>(guard: SegmentGuard, write: (csrf: string) => Promise<T>): Promise<T> { const outcome = await guard(async csrf => { try { return { ok: true as const, value: await write(csrf) }; } catch (error) { return { ok: false as const, error }; } }); if (outcome.ok) return outcome.value; if (outcome.error instanceof SegmentResponseError && [400, 403, 404, 409, 413, 415, 422, 429].includes(outcome.error.status)) throw new SegmentRejected(outcome.error.message, outcome.error.status, outcome.error.body); throw outcome.error; }
export async function segmentRequest(path: string, signal: AbortSignal, options: { method?: 'GET' | 'POST'; payload?: unknown; csrf?: string } = {}): Promise<unknown> {
  const method = options.method ?? 'GET'; const allowed = method === 'GET' ? path === '/me' || path === '/journeys/templates' || /^\/journeys\/[a-f0-9]{24}$/.test(path) || /^\/journeys\/operations\/[A-Za-z0-9_-]{8,80}$/.test(path) : path === '/journeys/preview' || path === '/journeys/apply';
  if (!['GET', 'POST'].includes(method) || !allowed || method === 'GET' && options.payload !== undefined || method === 'POST' && (!options.csrf || options.payload === undefined)) bad();
  const controller = new AbortController(), deadline = performance.now() + 15000; const abort = () => controller.abort(); const check = () => { if (signal.aborted) throw new SegmentDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new SegmentError('连接中断，请先核对原操作结果。'); };
  if (signal.aborted) throw new SegmentDiscarded(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15000);
  try { const response = await fetch('/api' + path, { method, mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal, headers: { 'Content-Type': 'application/json', ...(method === 'POST' ? { 'X-CSRF-Token': options.csrf! } : {}) }, ...(method === 'POST' ? { body: JSON.stringify(options.payload) } : {}) }); check(); if (response.redirected) bad();
    const contentType = response.headers.get('Content-Type') || ''; let body: unknown; if (contentType.toLowerCase().includes('application/json')) { const raw = await response.text(); check(); if (raw.length > 2_000_000) bad(); try { body = JSON.parse(raw); } catch { if (response.ok) bad(); } }
    if (!response.ok) throw new SegmentResponseError(body && typeof body === 'object' && typeof (body as Record<string, unknown>).error === 'string' ? text((body as Record<string, unknown>).error, 4000) : '旅行请求未完成，请核对当前身份与原操作。', response.status, body);
    if (body === undefined) bad(); return body;
  } catch (error) { check(); if (error instanceof SegmentError || error instanceof SegmentDiscarded) throw error; throw new SegmentError('连接中断，请先核对原操作结果。'); } finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
