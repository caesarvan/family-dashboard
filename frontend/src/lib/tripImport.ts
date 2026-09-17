import { readPlan, readCapabilities, readJourneyDetail, newSegmentKey, SegmentError, SegmentRejected, SegmentDiscarded, segmentRequest,
  type JourneyPlan, type SegmentReceipt, type SegmentSession } from './journeySegments';
export { SegmentFence as TripImportFence, SegmentError as TripImportError, SegmentRejected as TripImportRejected, SegmentDiscarded as TripImportDiscarded,
  checkedSegmentWrite as checkedTripImportWrite, segmentSignature as tripImportSignature } from './journeySegments';
export type { SegmentSession as TripImportSession } from './journeySegments';

export const MAX_TRIP_IMPORT_BYTES = 200_000;
export type ImportInput = { plan: Record<string, unknown> };
export type ImportPreview = { plan: JourneyPlan; previewToken: string; expiresIn: number; create: Record<string, number>; warnings: string[]; policyNotice: string; calendar: string };
export type ImportIntent = { body: Readonly<{ previewToken: string; idempotencyKey: string }>; uncertain: boolean };
export type ImportReceipt = SegmentReceipt;
export type ImportListItem = { id: string; tripId: string; title: string; start: string; end: string };
const fail = (message = '旅行数据无法核对，请保留输入并重新读取。'): never => { throw new SegmentError(message); };
const object = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : fail();
const str = (v: unknown, max = 4000): string => typeof v === 'string' && v.length <= max && !!v.trim() ? v : fail();
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min && v <= max ? v : fail();
const id = (v: unknown): string => typeof v === 'string' && /^[a-f0-9]{24}$/.test(v) ? v : fail();
export const importOperationKey = (v: unknown): string => typeof v === 'string' && /^[A-Za-z0-9_-]{8,80}$/.test(v) ? v : fail('操作编号格式不正确。');
const list = (v: unknown, max: number): unknown[] => Array.isArray(v) && v.length <= max ? v : fail();
const forbidden = new Set(['__proto__', 'constructor', 'prototype', 'journeyId', 'tripId', 'revision', 'tripRevision', 'previewToken', 'idempotencyKey', 'expectedEntities', 'conflictResolutions', 'publish']);
function bounded(value: unknown, depth = 0): void {
  if (depth > 16) fail('JSON 嵌套过深。');
  if (typeof value === 'number' && !Number.isFinite(value)) fail('JSON 数字无效。');
  if (Array.isArray(value)) { if (value.length > 1000) fail('JSON 列表过长。'); value.forEach(v => bounded(v, depth + 1)); }
  else if (value && typeof value === 'object') {
    const entries = Object.entries(value); if (entries.length > 100) fail('JSON 字段过多。');
    for (const [key, v] of entries) { if (forbidden.has(key)) fail('仅支持新建旅行，请移除已有旅行编号、版本、令牌或操作选项。'); bounded(v, depth + 1); }
  }
}
export function parseTripImport(raw: string): ImportInput {
  if (typeof raw !== 'string' || new TextEncoder().encode(raw).byteLength > MAX_TRIP_IMPORT_BYTES) fail('旅行 JSON 最多 200,000 字节。');
  let value: unknown; try { value = JSON.parse(raw.replace(/^\uFEFF/, '')); } catch { fail('请输入有效的 JSON，或选择 JSON 文件。'); }
  const root = object(value); bounded(root);
  if ('plan' in root && Object.keys(root).some(k => k !== 'plan')) fail('包装对象仅可包含 plan，请移除其他操作字段。');
  const plan = object('plan' in root ? root.plan : root);
  const allowed = ['schemaVersion', 'title', 'start', 'end', 'international', 'memberIds', 'budget', 'saved', 'paid', 'note', 'destinations', 'checklist', 'shopping', 'segments', 'referenceTimezone'];
  if (Object.keys(plan).some(k => !allowed.includes(k))) fail('计划包含不支持的顶层字段，请按示例核对。');
  if (plan.schemaVersion !== undefined && plan.schemaVersion !== 1 && plan.schemaVersion !== 2) fail('仅支持第 1 或第 2 版旅行计划。');
  if (plan.destinations !== undefined) list(plan.destinations, 20);
  for (const key of ['checklist', 'shopping', 'segments']) if (plan[key] !== undefined) list(plan[key], 100);
  return { plan }; // Preserve omissions. The server supplies defaults and validates dates, owners and money.
}
export function decodeTripImportFile(bytes: ArrayBuffer): string {
  if (!bytes.byteLength || bytes.byteLength > MAX_TRIP_IMPORT_BYTES) fail('请选择非空且不超过 200,000 字节的 JSON 文件。');
  try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { return fail('文件须使用 UTF-8 编码。'); }
}
export function tripImportVersions(raw: unknown): (1 | 2)[] { return readCapabilities(raw).schemaVersions; }
export function tripImportPreviewBody(input: ImportInput, versions: (1 | 2)[]): ImportInput {
  const checked = parseTripImport(JSON.stringify(input));
  if (!versions.includes(checked.plan.schemaVersion === 2 ? 2 : 1)) fail('当前服务不支持此版本，请保留原文件，不要降级。');
  return checked;
}
export function readTripImportPreview(raw: unknown): ImportPreview {
  const r = object(raw), s = object(r.summary), plan = readPlan(r.plan, true), create = object(s.create), update = object(s.update);
  if (r.canApply !== true || integer(s.detach) !== 0 || Object.values(update).some(v => integer(v) !== 0)) fail('这不是可创建新旅行的预览。');
  for (const key of ['conflicts', 'preserved', 'resolved', 'cloudReviews']) if (list(s[key], 404).length) fail('此预览需要已有旅行的冲突处理，不能作为新旅行导入。');
  if (Object.keys(create).some(k => !['trips', 'tasks', 'shopping', 'events'].includes(k)) || create.trips !== 1) fail();
  return { plan, previewToken: str(r.previewToken, 500000), expiresIn: integer(r.expiresIn, 1, 1800),
    create: Object.fromEntries(Object.entries(create).map(([k, v]) => [k, integer(v, 0, 101)])),
    warnings: list(s.warnings, 500).map(v => str(object(v).message)), policyNotice: str(s.policyNotice), calendar: str(s.calendar) };
}
export function createTripImportIntent(preview: ImportPreview, key = newSegmentKey()): ImportIntent {
  return { body: Object.freeze({ previewToken: str(preview.previewToken, 500000), idempotencyKey: importOperationKey(key) }), uncertain: false };
}
export function failedTripImportIntent(intent: ImportIntent, error: unknown): ImportIntent | null {
  return !intent.uncertain && error instanceof SegmentRejected ? null : { ...intent, uncertain: true };
}
export function readTripImportReceipt(raw: unknown): ImportReceipt {
  const r = object(raw), uid = id(r.id), tripId = id(r.tripId), c = object(r.calendar);
  if (r.revision !== 1 || typeof r.replayed !== 'boolean' || r.operation !== undefined || c.local !== 'created' || c.cloud !== 'not_requested' || c.icsUrl !== `/api/journeys/${uid}/calendar.ics`) fail();
  return { id: uid, tripId, revision: 1, replayed: r.replayed as boolean, calendar: { local: 'created', cloud: 'not_requested', icsUrl: c.icsUrl as string } };
}
export function readTripImportOperation(raw: unknown, key: string): ImportReceipt {
  const r = object(raw); if (r.found !== true || r.idempotencyKey !== importOperationKey(key)) fail();
  return readTripImportReceipt({ ...object(r.result), replayed: true });
}
export function readTripImportCurrent(raw: unknown, receipt: ImportReceipt) {
  const detail = readJourneyDetail(raw, receipt.id);
  if (detail.tripId !== receipt.tripId || detail.revision < receipt.revision || !detail.trip) fail('旅行已移除或变化，请核对当前旅行列表。');
  return detail;
}
export function readTripImportList(raw: unknown): ImportListItem[] {
  const rows = list(object(raw).journeys, 10000).map(v => { const d = readJourneyDetail(v); return { id: d.id, tripId: d.tripId, title: d.plan.title, start: d.plan.start, end: d.plan.end }; });
  if (new Set(rows.map(r => r.id)).size !== rows.length) fail(); return rows;
}
export const tripImportActor = (s: SegmentSession): string => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id]);
/** Only opaque handles survive component/session changes; compare-and-clear excludes late old callbacks. */
export class TripImportRecoveryMemory {
  private rows = new Map<string, { key: string; pending: boolean }>();
  get(actor: string) { const row = this.rows.get(actor); return row ? { ...row } : null; }
  set(actor: string, key: string) { this.rows.set(actor, { key: importOperationKey(key), pending: true }); }
  finish(actor: string, key: string) { if (this.rows.get(actor)?.key === key) this.rows.set(actor, { key, pending: false }); }
}
export type ImportEndProof = Readonly<{ key: string; identity: string; epoch: number }>;
export function canEndTripImport(proof: ImportEndProof | null, key: string | null, identity: string, epoch: number): boolean {
  return !!proof && !!key && proof.key === key && proof.identity === identity && proof.epoch === epoch;
}
export const missingTripImportReceipt = (error: unknown) => error instanceof SegmentError && error.status === 404 && error.body !== null && typeof error.body === 'object' && (error.body as Record<string, unknown>).code === 'operation_not_found';

/** Reuse fixed-path requests; the sole addition is the existing GET list for explicit unknown-result review. */
export async function tripImportRequest(path: string, signal: AbortSignal, options: { method?: 'GET' | 'POST'; payload?: unknown; csrf?: string } = {}): Promise<unknown> {
  if (path !== '/journeys') return segmentRequest(path, signal, options);
  if (options.method && options.method !== 'GET' || options.payload !== undefined || options.csrf !== undefined) fail();
  const controller = new AbortController(), abort = () => controller.abort(), deadline = performance.now() + 15000;
  const check = () => { if (signal.aborted) throw new SegmentDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new SegmentError('暂时无法读取当前旅行。'); };
  if (signal.aborted) throw new SegmentDiscarded(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15000);
  try {
    const response = await fetch('/api/journeys', { mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal }); check();
    if (response.redirected) fail();
    if (!response.ok) throw new SegmentError('暂时无法读取当前旅行。', response.status);
    if (!(response.headers.get('Content-Type') || '').toLowerCase().includes('application/json')) fail();
    const bytes = await response.text(); check(); if (bytes.length > 2_000_000) fail('旅行列表过大，无法在此核对。');
    return JSON.parse(bytes) as unknown;
  } catch (e) { check(); if (e instanceof SegmentError || e instanceof SegmentDiscarded) throw e; throw new SegmentError('暂时无法读取当前旅行。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
