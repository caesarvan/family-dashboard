export type Span = { start: string | null; end: string | null };
export type ImpactKind = 'overview' | 'destination' | 'segment' | 'task' | 'shopping' | 'place';
export type Clock = { local: string; timeZone: string; offsetMinutes?: number };
export type Clocks = { start?: Clock; end?: Clock };
export type Impact = { key: string; kind: ImpactKind; title: string; before: Span; eligible: boolean; reason: string | null; endExclusive: boolean; timeBefore?: Clocks };
export type Warning = { code: string; key: string | null; message: string };
export type Issue = Warning & { field?: 'start' | 'end'; local?: string; timeZone?: string; choices?: { offsetMinutes: number; instant: string }[] };
export type Snapshot = { journeyId: string; revision: number; start: string; end: string; snapshotToken: string; expiresIn: number; items: Impact[]; warnings: Warning[]; capabilities: { shoppingDue: false } };
export type LocalOverride = { local: string; offsetMinutes?: number };
export type TimeOverrides = Record<string, { start?: LocalOverride; end?: LocalOverride }>;
export type RescheduleDraft = { start: string; end: string; selectedKeys: string[]; timeOverrides: TimeOverrides };
export type ReschedulePreview = { journeyId: string; revision: number; start: string; end: string; items: (Impact & { selected: boolean; after: Span; timeAfter?: Clocks })[]; warnings: Warning[]; blockingIssues: Issue[]; canApply: boolean; previewToken: string | null; expiresIn: number };
export type RescheduleReceipt = { id: string; tripId: string; revision: number; replayed: boolean; operation: 'reschedule'; reschedule: { start: string; end: string; changedKeys: string[] } };
export type Intent = { body: Readonly<{ previewToken: string; idempotencyKey: string }>; start: string; end: string; uncertain: boolean };
export const impactLabels: Record<ImpactKind, string> = { overview: '旅行日期', destination: '目的地停留', segment: '行程与日历', task: '准备截止', shopping: '采购', place: '计划地点' };
const error = () => new Error('改期数据无法核对，请重新读取旅行。');
const object = (raw: unknown): Record<string, unknown> => { if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw error(); return raw as Record<string, unknown>; };
const text = (raw: unknown, max = 500): string => { if (typeof raw !== 'string' || Array.from(raw).length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(raw)) throw error(); return raw; };
const boolean = (raw: unknown): boolean => { if (typeof raw !== 'boolean') throw error(); return raw; };
const integer = (raw: unknown, min = 1, max = Number.MAX_SAFE_INTEGER): number => { if (!Number.isSafeInteger(raw) || Number(raw) < min || Number(raw) > max) throw error(); return raw as number; };
const list = (raw: unknown, max = 3321): unknown[] => { if (!Array.isArray(raw) || raw.length > max) throw error(); return raw; };
export function validRescheduleDay(raw: unknown): raw is string {
  if (typeof raw !== 'string' || !/^(20\d{2}|2100)-\d{2}-\d{2}$/.test(raw)) return false;
  const time = new Date(raw + 'T00:00:00Z'); return Number.isFinite(time.getTime()) && time.toISOString().slice(0, 10) === raw;
}
const day = (raw: unknown): string => { if (!validRescheduleDay(raw)) throw new Error('日期请填写有效的 YYYY-MM-DD（2000—2100 年）。'); return raw; };
function dates(start: unknown, end: unknown) { const a = day(start), b = day(end); if (b < a || (Date.parse(b) - Date.parse(a)) / 86400000 > 366) throw new Error('返程不能早于出发，单次旅行最多 367 天。'); return { start: a, end: b }; }
const id = (raw: unknown) => { const value = text(raw, 24); if (!/^[a-f0-9]{24}$/.test(value)) throw error(); return value; };
const key = (raw: unknown) => { const value = text(raw, 100); if (!/^(trip|(?:destination|segment|task|shopping|place):[A-Za-z0-9_-]{1,64})$/.test(value)) throw error(); return value; };
const span = (raw: unknown): Span => { const value = object(raw); return { start: value.start === null ? null : day(value.start), end: value.end === null ? null : day(value.end) }; };
function impact(raw: unknown): Impact {
  const value = object(raw), kind = text(value.kind) as ImpactKind, itemKey = key(value.key);
  if (!(kind in impactLabels) || (kind === 'overview' ? itemKey !== 'trip' : !itemKey.startsWith(kind + ':'))) throw error();
  return { key: itemKey, kind, title: text(value.title), before: span(value.before), eligible: boolean(value.eligible), reason: value.reason === null ? null : text(value.reason, 100), endExclusive: boolean(value.endExclusive), ...(value.timeBefore === undefined ? {} : { timeBefore: clocks(value.timeBefore) }) };
}
function impacts(raw: unknown) { const rows = list(raw).map(impact); if (new Set(rows.map(row => row.key)).size !== rows.length || rows.filter(row => row.key === 'trip').length !== 1 || rows.find(row => row.key === 'trip')!.eligible) throw error(); return rows; }
const warning = (raw: unknown): Warning => { const value = object(raw); return { code: text(value.code, 100), key: value.key === null ? null : key(value.key), message: text(value.message, 2000) }; };
export function readRescheduleSnapshot(raw: unknown, journeyId: string): Snapshot {
  const value = object(raw); if (id(value.journeyId) !== journeyId || object(value.capabilities).shoppingDue !== false) throw error();
  return { journeyId, revision: integer(value.revision), ...dates(value.start, value.end), snapshotToken: text(value.snapshotToken, 2000000), expiresIn: integer(value.expiresIn, 1, 86400), items: impacts(value.items), warnings: list(value.warnings, 6742).map(warning), capabilities: { shoppingDue: false } };
}
export const snapshotVersion = (source: Snapshot) => JSON.stringify([source.journeyId, source.revision, source.start, source.end, source.items]);
export const initialRescheduleDraft = (source: Snapshot): RescheduleDraft => ({ start: source.start, end: source.end, selectedKeys: [], timeOverrides: {} });
export function rebaseRescheduleDraft(draft: RescheduleDraft, source: Snapshot): { draft: RescheduleDraft; removed: string[] } {
  const allowed = new Set(source.items.filter(row => row.eligible).map(row => row.key)), selectedKeys = draft.selectedKeys.filter(item => allowed.has(item));
  return { draft: { ...draft, selectedKeys, timeOverrides: Object.fromEntries(Object.entries(draft.timeOverrides).filter(([item]) => selectedKeys.includes(item))) }, removed: draft.selectedKeys.filter(item => !allowed.has(item)) };
}
export function localOverride(raw: unknown): LocalOverride {
  const value = object(raw), local = text(value.local, 19);
  if (!/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(local) || !validRescheduleDay(local.slice(0, 10))) throw new Error('当地时间请填写有效的 YYYY-MM-DDTHH:mm，可包含秒。');
  return { local, ...(value.offsetMinutes === undefined ? {} : { offsetMinutes: integer(value.offsetMinutes, -840, 840) }) };
}
function clocks(raw: unknown): Clocks {
  const value = object(raw), result: Clocks = {};
  for (const endpoint of ['start', 'end'] as const) if (value[endpoint] !== undefined) {
    const clock = object(value[endpoint]); result[endpoint] = { ...localOverride(clock), timeZone: text(clock.timeZone, 100) };
  }
  return result;
}
export function offsetText(minutes: number) { return `UTC${minutes >= 0 ? '+' : '-'}${String(Math.floor(Math.abs(minutes) / 60)).padStart(2, '0')}:${String(Math.abs(minutes) % 60).padStart(2, '0')}`; }
export function clockText(clock?: Clock) { return clock ? `${clock.local.replace('T', ' ')} · ${clock.timeZone}${clock.offsetMinutes === undefined ? '' : ' · ' + offsetText(clock.offsetMinutes)}` : '未设时刻'; }
export function reschedulePayload(source: Snapshot, draft: RescheduleDraft) {
  const value = dates(draft.start.trim(), draft.end.trim()), available = new Map(source.items.map(row => [row.key, row]));
  if (new Set(draft.selectedKeys).size !== draft.selectedKeys.length || draft.selectedKeys.some(item => !available.get(item)?.eligible)) throw new Error('选择的项目已变化，请读取最新内容并重新核对。');
  const timeOverrides: TimeOverrides = {};
  for (const [item, raw] of Object.entries(draft.timeOverrides)) {
    if (!draft.selectedKeys.includes(item) || available.get(item)?.kind !== 'segment') throw new Error('只能纠正本次选择的行程时间。');
    const correction: { start?: LocalOverride; end?: LocalOverride } = {};
    if (raw.start !== undefined) correction.start = localOverride(raw.start);
    if (raw.end !== undefined) correction.end = localOverride(raw.end);
    if (Object.keys(correction).length) timeOverrides[item] = correction;
  }
  return { snapshotToken: source.snapshotToken, ...value, selectedKeys: [...draft.selectedKeys], ...(Object.keys(timeOverrides).length ? { timeOverrides } : {}) };
}
export function readReschedulePreview(raw: unknown, source: Snapshot, draft: RescheduleDraft): ReschedulePreview {
  const value = object(raw), payload = reschedulePayload(source, draft), rows = impacts(value.items);
  if (id(value.journeyId) !== source.journeyId || integer(value.revision) !== source.revision || value.start !== payload.start || value.end !== payload.end || rows.length !== source.items.length) throw error();
  const original = new Map(source.items.map(row => [row.key, row]));
  const items = rows.map((row, index) => {
    if (JSON.stringify(row) !== JSON.stringify(original.get(row.key))) throw error();
    const rawRow = object(list(value.items)[index]), selected = boolean(rawRow.selected), after = span(rawRow.after);
    if (row.kind !== 'overview' && selected !== payload.selectedKeys.includes(row.key)) throw error();
    if (!selected && row.kind !== 'overview' && JSON.stringify(after) !== JSON.stringify(row.before)) throw error();
    const timeAfter = rawRow.timeAfter === undefined ? undefined : clocks(rawRow.timeAfter);
    if (row.timeBefore !== undefined && timeAfter === undefined || row.timeBefore === undefined && timeAfter !== undefined) throw error();
    if (!selected && row.kind !== 'overview' && JSON.stringify(timeAfter) !== JSON.stringify(row.timeBefore)) throw error();
    return { ...row, selected, after, ...(timeAfter === undefined ? {} : { timeAfter }) };
  });
  const blockingIssues = list(value.blockingIssues, 600).map(rawIssue => {
    const issue = object(rawIssue), result: Issue = warning(issue);
    if (issue.field !== undefined) { if (!['start', 'end'].includes(String(issue.field))) throw error(); result.field = issue.field as 'start' | 'end'; }
    if (issue.local !== undefined) result.local = text(issue.local, 30);
    if (issue.timeZone !== undefined) result.timeZone = text(issue.timeZone, 100);
    if (issue.choices !== undefined) result.choices = list(issue.choices, 20).map(rawChoice => { const choice = object(rawChoice); return { offsetMinutes: integer(choice.offsetMinutes, -840, 840), instant: text(choice.instant, 80) }; });
    return result;
  });
  const canApply = boolean(value.canApply), token = value.previewToken === null ? null : text(value.previewToken, 2000000);
  if (canApply && (!token || blockingIssues.length) || !canApply && token !== null) throw error();
  return { journeyId: source.journeyId, revision: source.revision, start: payload.start, end: payload.end, items, warnings: list(value.warnings, 6742).map(warning), blockingIssues, canApply, previewToken: token, expiresIn: integer(value.expiresIn, 1, 86400) };
}
export function readRescheduleReceipt(raw: unknown, journeyId: string, intent: Intent): RescheduleReceipt {
  const value = object(raw), result = object(value.reschedule);
  if (id(value.id) !== journeyId || value.operation !== 'reschedule' || result.start !== intent.start || result.end !== intent.end) throw error();
  return { id: journeyId, tripId: id(value.tripId), revision: integer(value.revision), replayed: boolean(value.replayed), operation: 'reschedule', reschedule: { ...dates(result.start, result.end), changedKeys: list(result.changedKeys).map(key) } };
}
export function readRescheduleOperation(raw: unknown, journeyId: string, intent: Intent) {
  const value = object(raw); if (value.found !== true || value.idempotencyKey !== intent.body.idempotencyKey) throw error();
  // Stored results predate the transport-only replayed flag. A successful
  // operation lookup confirms that original historical receipt, not a new write.
  return readRescheduleReceipt({ ...object(value.result), replayed: true }, journeyId, intent);
}
export class RescheduleRejected extends Error { constructor(readonly status: number, message: string, readonly code = '') { super(message); } }
export class RescheduleUnverified extends Error { constructor(readonly reason: unknown) { super('改期保存前后的身份暂时无法核对。'); } }
export async function checkedRescheduleWrite<T>(guard: <R>(action: (csrf: string) => Promise<R>) => Promise<R>, action: (csrf: string) => Promise<T>, http: (failure: unknown) => { status: number; code?: string } | undefined): Promise<T> {
  let outcome: { ok: true; value: T } | { ok: false; failure: unknown };
  try { outcome = await guard(async csrf => { try { return { ok: true as const, value: await action(csrf) }; } catch (failure) { return { ok: false as const, failure }; } }); }
  catch (reason) { throw new RescheduleUnverified(reason); }
  if (outcome.ok) return outcome.value;
  const status = http(outcome.failure);
  if (status && [400, 403, 404, 409, 410, 413, 415, 422, 429].includes(status.status)) throw new RescheduleRejected(status.status, outcome.failure instanceof Error ? outcome.failure.message : '改期请求被拒绝。', status.code);
  throw outcome.failure;
}
export const failedRescheduleIntent = (intent: Intent, failure: unknown): Intent | null => intent.uncertain || !(failure instanceof RescheduleRejected) ? { ...intent, uncertain: true } : null;
export const mayExitReschedule = (pending: Intent | null, working: boolean) => !pending && !working;
export function impactReason(item: Impact) {
  if (item.kind === 'overview') return '旅行总日期会更新';
  if (item.kind === 'shopping') return '采购没有截止日期，保持原记录';
  if (item.eligible) return '未选择时保持原日期';
  const reasons: Record<string, string> = { completed: '已完成', no_date: '未设日期', cloud_managed: '由云端来源管理', fixed: '固定安排', booked: '已预订', cancelled: '已取消', not_planned: '不是计划地点', missing_event: '关联日程已不存在', timing_changed: '日程时间类型或时区已变化' };
  return '保持原日期 · ' + (reasons[item.reason || ''] || '当前不可调整');
}
export const spanText = (value: Span) => value.start === value.end ? value.start || '未设日期' : `${value.start || '未设日期'} — ${value.end || '未设日期'}`;
export function pageItems<T>(items: T[], page: number, size = 12) { const pages = Math.max(1, Math.ceil(items.length / size)), safePage = Math.max(0, Math.min(Number.isSafeInteger(page) ? page : 0, pages - 1)); return { items: items.slice(safePage * size, (safePage + 1) * size), page: safePage, pages }; }
