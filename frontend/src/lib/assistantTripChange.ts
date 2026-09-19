import { validRescheduleDay, type RescheduleDraft, type Snapshot } from './journeyReschedule.ts';

export type TripCandidate = { ref: string; journeyId: string; tripId: string; revision: number; title: string; start: string; end: string; timeZones: string[]; sourceIssues: string[] };
export type TripChangeSource = { journeyId: string; tripId: string; revision: number; tripRevision: number; title: string; start: string; end: string; sourceVersion: string };
export type TripDateChange = { kind: 'shift_days' | 'start_date' | 'unspecified'; days: number | null; startDate: string | null; monthDay: string | null };
export type TripDateDraft = { journeyId: string; tripId: string; revision: number; start: string; end: string; calendarDays: true };
export type TripSuggestion = { source: TripChangeSource; draft: TripDateDraft };
export type TripChangePlan = {
  version: 1; intent: 'reschedule_existing' | 'other'; status: 'ready' | 'choose_trip' | 'needs_input' | 'not_found' | 'not_applicable';
  mode: 'local' | 'model'; candidates: TripCandidate[]; selected: TripCandidate | null; change: TripDateChange;
  missingFields: string[]; issues: string[]; draft: TripDateDraft | null; requiresPreview: true;
  source: TripChangeSource | null; selectionToken: string | null; selectionExpiresIn: 600 | null;
};
const bad = () => new Error('旅行建议无法核对，请保留原文重新整理。');
const object = (raw: unknown): Record<string, unknown> => { if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw bad(); return raw as Record<string, unknown>; };
const text = (raw: unknown, max = 200, empty = false): string => {
  if (typeof raw !== 'string' || Array.from(raw).length > max || !empty && !raw.trim() || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\ud800-\udfff]/u.test(raw)) throw bad();
  return raw;
};
const integer = (raw: unknown) => { if (!Number.isSafeInteger(raw) || Number(raw) < 1) throw bad(); return raw as number; };
const list = (raw: unknown, max: number): unknown[] => { if (!Array.isArray(raw) || raw.length > max) throw bad(); return raw; };
const id = (raw: unknown) => { const value = text(raw, 24); if (!/^[a-f0-9]{24}$/.test(value)) throw bad(); return value; };
const ref = (raw: unknown) => { const value = text(raw, 29); if (!/^trip_[a-f0-9]{24}$/.test(value)) throw bad(); return value; };
const day = (raw: unknown): string => { if (!validRescheduleDay(raw)) throw bad(); return raw; };
const dates = (a: unknown, b: unknown) => { const start = day(a), end = day(b); if (end < start || Date.parse(end) - Date.parse(start) > 366 * 86400000) throw bad(); return { start, end }; };
const codeList = (raw: unknown, max: number) => { const values = list(raw, max).map(value => text(value, 100)); if (values.some(value => !/^[a-zA-Z_]+$/.test(value)) || new Set(values).size !== values.length) throw bad(); return values; };
function candidate(raw: unknown): TripCandidate {
  const value = object(raw), timeZones = list(value.timeZones, 100).map(zone => text(zone, 100)), sourceIssues = codeList(value.sourceIssues, 2);
  if (new Set(timeZones).size !== timeZones.length || sourceIssues.some(issue => !['source_timezone_missing', 'source_timezone_invalid'].includes(issue))) throw bad();
  return { ref: ref(value.ref), journeyId: id(value.journeyId), tripId: id(value.tripId), revision: integer(value.revision), title: text(value.title), ...dates(value.start, value.end), timeZones, sourceIssues };
}
function change(raw: unknown): TripDateChange {
  const value = object(raw), kind = value.kind;
  if (!['shift_days', 'start_date', 'unspecified'].includes(String(kind))) throw bad();
  const days = value.days === null ? null : Number.isSafeInteger(value.days) && Math.abs(Number(value.days)) >= 1 && Math.abs(Number(value.days)) <= 366 ? Number(value.days) : NaN;
  const startDate = value.startDate === null ? null : day(value.startDate), monthDay = value.monthDay === null ? null : text(value.monthDay, 5);
  if (Number.isNaN(days) || monthDay !== null && (!/^\d{2}-\d{2}$/.test(monthDay) || !validRescheduleDay('2000-' + monthDay))) throw bad();
  if (kind === 'shift_days' ? days === null || startDate !== null || monthDay !== null : kind === 'start_date' ? days !== null || (startDate === null) === (monthDay === null) : days !== null || startDate !== null || monthDay !== null) throw bad();
  return { kind: kind as TripDateChange['kind'], days, startDate, monthDay };
}
export function tripChangeRequest(prompt: string, useModel: boolean) {
  return { prompt: text(prompt.trim(), 2000), useModel: useModel === true };
}
export function tripSelectionRequest(plan: TripChangePlan, selectedRef: string) {
  if (plan.status !== 'choose_trip' || !plan.selectionToken || !plan.candidates.some(value => value.ref === selectedRef)) throw bad();
  return { selectionToken: text(plan.selectionToken, 16000), selectedRef: ref(selectedRef) };
}
export function readTripChange(raw: unknown, selectedRef?: string): TripChangePlan {
  const value = object(raw), status = value.status, mode = value.mode, intent = value.intent;
  if (value.version !== 1 || value.requiresPreview !== true || !['ready', 'choose_trip', 'needs_input', 'not_found', 'not_applicable'].includes(String(status)) || !['local', 'model'].includes(String(mode)) || !['reschedule_existing', 'other'].includes(String(intent))) throw bad();
  const candidates = list(value.candidates, 200).map(candidate), selected = value.selected === null ? null : candidate(value.selected);
  if (new Set(candidates.map(c => c.ref)).size !== candidates.length || new Set(candidates.map(c => c.journeyId)).size !== candidates.length || selected && !candidates.some(c => JSON.stringify(c) === JSON.stringify(selected))) throw bad();
  const dateChange = change(value.change), missingFields = codeList(value.missingFields, 3), issues = codeList(value.issues, 40);
  if (missingFields.some(field => !['trip', 'dateChange', 'year'].includes(field))) throw bad();
  let source: TripChangeSource | null = null, draft: TripDateDraft | null = null;
  if (value.source !== null) {
    const s = object(value.source), sourceVersion = text(s.sourceVersion, 64);
    if (!/^[a-f0-9]{64}$/.test(sourceVersion)) throw bad();
    source = { journeyId: id(s.journeyId), tripId: id(s.tripId), revision: integer(s.revision), tripRevision: integer(s.tripRevision), title: text(s.title), ...dates(s.start, s.end), sourceVersion };
  }
  if (!!selected !== !!source || selected && source && ['journeyId', 'tripId', 'revision', 'title', 'start', 'end'].some(key => selected[key as keyof TripCandidate] !== source[key as keyof TripChangeSource])) throw bad();
  if (value.draft !== null) {
    const d = object(value.draft); if (d.calendarDays !== true) throw bad();
    draft = { journeyId: id(d.journeyId), tripId: id(d.tripId), revision: integer(d.revision), ...dates(d.start, d.end), calendarDays: true };
  }
  const selectionToken = value.selectionToken === null ? null : text(value.selectionToken, 16000), selectionExpiresIn = value.selectionExpiresIn;
  if (status === 'choose_trip' ? !selectionToken || selectionExpiresIn !== 600 || !!selected || !candidates.length : selectionToken !== null || selectionExpiresIn !== null) throw bad();
  if (status === 'ready') {
    if (!selected || !source || !draft || missingFields.length || issues.length || dateChange.kind === 'unspecified' || ['journeyId', 'tripId', 'revision'].some(key => draft![key as keyof TripDateDraft] !== source![key as keyof TripChangeSource])) throw bad();
    if (Date.parse(draft.end) - Date.parse(draft.start) !== Date.parse(source.end) - Date.parse(source.start) || draft.start === source.start) throw bad();
    if (dateChange.kind === 'shift_days' ? Date.parse(draft.start) - Date.parse(source.start) !== dateChange.days! * 86400000 : draft.start !== dateChange.startDate) throw bad();
  } else if (draft !== null) throw bad();
  if (intent === 'other' ? status !== 'not_applicable' || candidates.length || selected !== null : status === 'not_applicable') throw bad();
  if (selectedRef !== undefined && selected?.ref !== selectedRef) throw bad();
  return { version: 1, intent: intent as TripChangePlan['intent'], status: status as TripChangePlan['status'], mode: mode as TripChangePlan['mode'], candidates, selected, change: dateChange, missingFields, issues, draft, requiresPreview: true, source, selectionToken, selectionExpiresIn: selectionExpiresIn as 600 | null };
}
export function tripSuggestion(plan: TripChangePlan): TripSuggestion {
  if (plan.status !== 'ready' || !plan.source || !plan.draft) throw bad();
  return { source: { ...plan.source }, draft: { ...plan.draft } };
}
/** Only current source fields available in the real reschedule DTO are compared. */
export function checkedTripSuggestion(snapshot: Snapshot, suggestion: TripSuggestion): RescheduleDraft {
  const s = suggestion.source, d = suggestion.draft, trip = snapshot.items.find(item => item.key === 'trip');
  if (snapshot.journeyId !== s.journeyId || snapshot.revision !== s.revision || snapshot.start !== s.start || snapshot.end !== s.end || trip?.title !== s.title || trip.before.start !== s.start || trip.before.end !== s.end || d.journeyId !== s.journeyId || d.tripId !== s.tripId || d.revision !== s.revision) throw new Error('旅行内容已变化，请返回助理重新整理需求。原建议没有带入或保存。');
  return { ...dates(d.start, d.end), selectedKeys: [], timeOverrides: {} };
}
const issueText: Record<string, string> = {
  negated_request: '请求含否定或取消，请明确是否要改期。', multiple_trip_targets: '请每次指定一趟旅行。',
  partial_day_shift: '请按完整日历天说明改期；具体时刻可在原改期预览中核对。', unconsumed_date_expression: '检测到日期范围或更正，请明确一个新的出发日期。',
  multiple_date_instructions: '请求含多个日期动作，请保留本次要执行的一个。', conflicting_date_requests: '日期要求互相矛盾，请补充准确日期。',
  invalid_shift_days: '请填写 1–366 个完整日历天。', invalid_start_date: '请填写有效的出发日期。', alternative_request: '请选定一个日期方案。', ambiguous_shift_range: '请明确要移动多少天。',
  mixed_create_and_modify: '请求同时包含新建与修改，请明确本次要修改的已有旅行。', partial_change_requires_manual_review: '这次只改部分行程，请从旅行详情手动调整并核对范围。', time_or_timezone_requires_manual_review: '请求含具体时刻或时区，请从旅行详情进入原改期页面核对。',
  model_intent_conflict: 'AI 理解与原文不一致，请补充需求后重新整理。', model_date_conflict: 'AI 日期建议与原文不一致，请补充准确日期。', model_target_conflict: 'AI 目标与原文不一致，请明确旅行名称。',
  unchanged_dates: '建议日期与原日期相同，请核对要修改的日期。', date_out_of_range: '日期超出支持范围（2000–2100 年）。', source_timezone_missing: '原行程缺少时区，请先在旅行详情补齐。', source_timezone_invalid: '原行程时区需要核对，请先打开旅行详情。',
};
export function tripChangeHints(plan: TripChangePlan): string[] {
  const hints = plan.issues.map(issue => issueText[issue] || '这份建议仍有待核对内容，请补充原文后重新整理。');
  if (plan.missingFields.includes('year')) hints.push('请补充年份，例如“改到2026年10月8日”。');
  if (plan.missingFields.includes('dateChange')) hints.push('请说明延后／提前多少天，或新的完整出发日期。');
  if (plan.status === 'not_found') hints.push('没有匹配到当前可修改的旅行，请核对名称或从旅行列表进入。');
  if (plan.status === 'not_applicable') hints.push('这段文字尚未识别为已有旅行改期，请明确旅行名称和日期要求。');
  return [...new Set(hints)];
}
