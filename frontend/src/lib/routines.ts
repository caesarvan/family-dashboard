import type { Member, Person } from './types';

export type RoutineKind = 'tasks' | 'shopping';
export type RoutineOperation = 'create' | 'update' | 'pause' | 'resume' | 'skip' | 'archive';
export type RoutineSchedule = { frequency: 'daily' | 'weekly' | 'monthly'; interval: number; anchor: string; timeZone: 'Asia/Shanghai'; monthEnd: 'clamp' };
export type RoutineTemplate = { title: string; owner: string; note: string; quantity?: string; budget?: number | null };
export type RoutineEntity = { id: string; revision: number; title: string; owner: string; note: string; done: boolean; due?: string; quantity?: string; budget?: number | null };
export type RoutineOccurrence = { index: number; scheduledOn: string; entityId: string; state: 'pending' | 'completed' | 'missing' | 'skipped'; entity: RoutineEntity | null };
export type RoutinePlan = { id: string; revision: number; state: 'active' | 'paused' | 'archived'; status: string; kind: RoutineKind; template: RoutineTemplate;
  schedule: RoutineSchedule; createdBy: string; createdAt: string; updatedAt: string; current: RoutineOccurrence | null; nextDates: string[]; history: RoutineOccurrence[] };
export type RoutineContext = { version: 1; today: string; timeZone: 'Asia/Shanghai'; plans: RoutinePlan[]; pageInfo: { page: number; pageSize: 40; more: boolean } };
export type RoutinePayload = { operation: RoutineOperation; planId?: string; revision?: number; kind?: RoutineKind; template?: RoutineTemplate; schedule?: RoutineSchedule };
export type RoutinePreview = { operation: RoutineOperation; today: string; before: RoutinePlan | null; after: Pick<RoutinePlan, 'kind' | 'template' | 'schedule' | 'state'>;
  nextDates: string[]; willGenerate: { index: number; scheduledOn: string; kind: RoutineKind; data: RoutineTemplate & { done: false } } | null;
  warnings: string[]; previewToken: string; operationKey: string; expiresInSeconds: number };
export type RoutinePending = Readonly<{ previewToken: string; operationKey: string; operation: RoutineOperation; planId?: string }>;
export type RoutineReceipt = { operationKey: string; operation: RoutineOperation; planId: string; revision: number;
  generated: { id: string; kind: RoutineKind; revision: number; scheduledOn: string } | null; createdAt: string };
export type RoutineDraft = { kind: RoutineKind; title: string; owner: string; note: string; quantity: string; budget: string; frequency: RoutineSchedule['frequency']; interval: string; anchor: string };
export type RoutineSession = { user: Member | null; csrf?: string | null };
export type RoutineGuard = <T>(job: (csrf: string) => Promise<T>) => Promise<T>;
export class RoutineError extends Error { constructor(message: string, public status = 0, public code = '') { super(message); } }
export class RoutineDiscarded extends Error {}
export class RoutineRejected extends RoutineError {}
class ResponseError extends RoutineError {}
const invalid = (): never => { throw new RoutineError('例行计划内容无法安全核对，请重新读取。'); };
const object = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : invalid();
const text = (v: unknown, max = 500, empty = false): string => typeof v === 'string' && Array.from(v).length <= max && (empty || !!v.trim()) && !/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(v) ? v : invalid();
const integer = (v: unknown, min = 1, max = Number.MAX_SAFE_INTEGER): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min && v <= max ? v : invalid();
const bool = (v: unknown) => typeof v === 'boolean' ? v : invalid();
const array = (v: unknown, max: number): unknown[] => Array.isArray(v) && v.length <= max ? v : invalid();
const oneOf = <T extends string>(v: unknown, values: readonly T[]): T => typeof v === 'string' && values.includes(v as T) ? v as T : invalid();
const identifier = (v: unknown): string => typeof v === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(v) ? v : invalid();
const key64 = (v: unknown): string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v) ? v : invalid();
const timestamp = (v: unknown) => { const s = text(v, 64); return /^\d{4}-\d\d-\d\dT.+(?:Z|\+00:00)$/.test(s) && Number.isFinite(Date.parse(s)) ? s : invalid(); };
const exact = (v: Record<string, unknown>, keys: string[]) => { if (Object.keys(v).sort().join('|') !== keys.sort().join('|')) invalid(); };
const kind = (v: unknown) => oneOf(v, ['tasks', 'shopping'] as const);
const operation = (v: unknown) => oneOf(v, ['create', 'update', 'pause', 'resume', 'skip', 'archive'] as const);
const state = (v: unknown) => oneOf(v, ['active', 'paused', 'archived'] as const);
function calendarDate(v: unknown): string {
  if (typeof v !== 'string' || !/^\d{4}-\d\d-\d\d$/.test(v) || v < '0001-01-01') return invalid();
  const d = new Date(v + 'T00:00:00Z'); if (!Number.isFinite(d.getTime()) || d.toISOString().slice(0, 10) !== v) invalid(); return v;
}
export function routineDate(v: unknown): string { const value = calendarDate(v); return value >= '2000-01-01' && value <= '2100-12-31' ? value : invalid(); }
function schedule(raw: unknown): RoutineSchedule {
  const v = object(raw), frequency = oneOf(v.frequency, ['daily', 'weekly', 'monthly'] as const);
  if (v.timeZone !== 'Asia/Shanghai' || v.monthEnd !== 'clamp') invalid();
  return { frequency, interval: integer(v.interval, 1, { daily: 365, weekly: 52, monthly: 12 }[frequency]), anchor: routineDate(v.anchor), timeZone: 'Asia/Shanghai', monthEnd: 'clamp' };
}
function template(raw: unknown, category: RoutineKind): RoutineTemplate {
  const v = object(raw), result: RoutineTemplate = { title: text(v.title, 100), owner: identifier(v.owner), note: text(v.note, 500, true) };
  if (category === 'shopping') { result.quantity = text(v.quantity, 30); result.budget = v.budget === null ? null : integer(v.budget, 0, 100_000_000_000); }
  return result;
}
function entity(raw: unknown): RoutineEntity {
  const v = object(raw), result: RoutineEntity = { id: identifier(v.id), revision: integer(v.revision), title: text(v.title, 100), owner: identifier(v.owner), note: text(v.note ?? '', 500, true), done: bool(v.done) };
  if (v.due !== undefined) result.due = v.due === '' ? '' : calendarDate(v.due);
  if (v.quantity !== undefined) result.quantity = text(v.quantity, 30);
  if (v.budget !== undefined) result.budget = v.budget === null ? null : integer(v.budget, 0, 100_000_000_000);
  return result;
}
function occurrence(raw: unknown): RoutineOccurrence {
  const v = object(raw), e = v.entity === null ? null : entity(v.entity), entityId = identifier(v.entityId);
  if (e && e.id !== entityId) invalid();
  return { index: integer(v.index), scheduledOn: routineDate(v.scheduledOn), entityId, state: oneOf(v.state, ['pending', 'completed', 'missing', 'skipped'] as const), entity: e };
}
const dates = (v: unknown) => array(v, 3).map(routineDate);
export function readRoutinePlan(raw: unknown): RoutinePlan {
  const v = object(raw), category = kind(v.kind);
  const result: RoutinePlan = { id: identifier(v.id), revision: integer(v.revision), state: state(v.state), status: oneOf(v.status, ['pending', 'completed', 'missing', 'paused', 'archived', 'capacity_blocked', 'exhausted']),
    kind: category, template: template(v.template, category), schedule: schedule(v.schedule), createdBy: identifier(v.createdBy), createdAt: timestamp(v.createdAt), updatedAt: timestamp(v.updatedAt),
    current: v.current === null ? null : occurrence(v.current), nextDates: dates(v.nextDates), history: array(v.history, 10).map(occurrence) };
  if (new Set(result.history.map(i => i.index)).size !== result.history.length) invalid();
  return result;
}
export function readRoutineContext(raw: unknown, page = 0, planId?: string): RoutineContext {
  const v = object(raw), p = object(v.pageInfo), limits = object(v.limit);
  if (v.version !== 1 || v.timeZone !== 'Asia/Shanghai' || p.pageSize !== 40 || integer(p.page, 0, 999999999) !== page || limits.activePlans !== 100 || limits.itemsPerKind !== 2500) invalid();
  const plans = array(v.plans, planId ? 41 : 40).map(readRoutinePlan);
  if (new Set(plans.map(p => p.id)).size !== plans.length || planId && !plans.some(p => p.id === planId)) invalid();
  return { version: 1, today: routineDate(v.today), timeZone: 'Asia/Shanghai', plans, pageInfo: { page, pageSize: 40, more: bool(p.more) } };
}
export function routineContextPath(page = 0, archived = false, planId?: string): string {
  return `/routines/context?page=${integer(page, 0, 999999999)}&includeArchived=${archived ? 'true' : 'false'}` + (planId ? '&planId=' + identifier(planId) : '');
}
export const routineOperationPath = (key: string) => '/routines/operations/' + key64(key);
export function readRoutinePayload(raw: unknown): RoutinePayload {
  const v = object(raw), op = operation(v.operation), result: RoutinePayload = { operation: op };
  exact(v, op === 'create' ? ['operation', 'kind', 'template', 'schedule'] : op === 'update' ? ['operation', 'planId', 'revision', 'template', 'schedule'] : ['operation', 'planId', 'revision']);
  if (op !== 'create') { result.planId = identifier(v.planId); result.revision = integer(v.revision); }
  if (op === 'create' || op === 'update') {
    const t = object(v.template), category = op === 'create' ? kind(v.kind) : 'quantity' in t || 'budget' in t ? 'shopping' : 'tasks';
    exact(t, category === 'shopping' ? ['title', 'owner', 'note', 'quantity', 'budget'] : ['title', 'owner', 'note']); exact(object(v.schedule), ['frequency', 'interval', 'anchor', 'timeZone', 'monthEnd']);
    result.template = template(t, category); result.schedule = schedule(v.schedule); if (op === 'create') result.kind = category;
  }
  return result;
}
export function routineBudget(value: string): number | null {
  value = value.trim(); if (!value) return null;
  if (!/^(?:0|[1-9]\d{0,9})(?:\.\d{1,2})?$/.test(value)) throw new RoutineError('预算请输入非负金额，最多两位小数；未知请留空。');
  const [whole, fraction = ''] = value.split('.'), cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  if (cents > 100_000_000_000n) throw new RoutineError('每期预算超出支持范围。'); return Number(cents);
}
export function routineAmount(cents: number | null | undefined): string { return cents == null ? '' : `${BigInt(integer(cents, 0, 100_000_000_000)) / 100n}.${String(BigInt(cents) % 100n).padStart(2, '0')}`; }
export function routineDraft(plan?: RoutinePlan, today = '2000-01-01', category: RoutineKind = 'tasks'): RoutineDraft {
  return { kind: plan?.kind ?? category, title: plan?.template.title ?? '', owner: plan?.template.owner ?? 'shared', note: plan?.template.note ?? '', quantity: plan?.template.quantity ?? '1',
    budget: routineAmount(plan?.template.budget), frequency: plan?.schedule.frequency ?? 'weekly', interval: String(plan?.schedule.interval ?? 1), anchor: plan?.schedule.anchor ?? routineDate(today) };
}
export function rebaseRoutineDraft(base: RoutinePlan, draft: RoutineDraft, latest: RoutinePlan): RoutineDraft {
  if (base.id !== latest.id || base.kind !== latest.kind) invalid();
  const before = routineDraft(base), result = routineDraft(latest);
  for (const key of Object.keys(result) as (keyof RoutineDraft)[]) if (draft[key] !== before[key]) (result as Record<string, string>)[key] = draft[key];
  return result;
}
export function draftRoutinePayload(draft: RoutineDraft, people: Person[], base?: RoutinePlan): RoutinePayload {
  if (!people.some(p => p.id === draft.owner) && draft.owner !== 'shared') throw new RoutineError('请选择当前家庭负责人。');
  if (!/^[1-9]\d{0,2}$/.test(draft.interval)) throw new RoutineError('间隔请输入正整数。');
  if (base && draft.kind !== base.kind) invalid();
  const data: RoutineTemplate = { title: draft.title.trim(), owner: draft.owner, note: draft.note.trim(), ...(draft.kind === 'shopping' ? { quantity: draft.quantity.trim(), budget: routineBudget(draft.budget) } : {}) };
  return readRoutinePayload({ operation: base ? 'update' : 'create', ...(base ? { planId: base.id, revision: base.revision } : { kind: draft.kind }), template: data,
    schedule: { frequency: draft.frequency, interval: Number(draft.interval), anchor: draft.anchor, timeZone: 'Asia/Shanghai', monthEnd: 'clamp' } });
}
export function readRoutinePreview(raw: unknown, request: RoutinePayload): RoutinePreview {
  const v = object(raw), a = object(v.after), category = kind(a.kind), op = operation(v.operation), before = v.before === null ? null : readRoutinePlan(v.before);
  if (v.timeZone !== 'Asia/Shanghai' || op !== request.operation || (op === 'create' ? before !== null || category !== request.kind : !before || before.id !== request.planId || before.revision !== request.revision)) invalid();
  const after = { kind: category, template: template(a.template, category), schedule: schedule(a.schedule), state: state(a.state) };
  const expectedState = op === 'create' || op === 'resume' ? 'active' : op === 'pause' ? 'paused' : op === 'archive' ? 'archived' : before?.state;
  if (after.state !== expectedState || before && category !== before.kind) invalid();
  if (request.template && JSON.stringify(after.template) !== JSON.stringify(template(request.template, category)) || request.schedule && JSON.stringify(after.schedule) !== JSON.stringify(schedule(request.schedule))) invalid();
  let willGenerate: RoutinePreview['willGenerate'] = null;
  if (v.willGenerate !== null) { const w = object(v.willGenerate), d = object(w.data); if (kind(w.kind) !== category || d.done !== false) invalid(); willGenerate = { index: integer(w.index), scheduledOn: routineDate(w.scheduledOn), kind: category, data: { ...template(d, category), done: false } }; }
  return { operation: op, today: routineDate(v.today), before, after, nextDates: dates(v.nextDates), willGenerate, warnings: array(v.warnings, 16).map(w => text(w, 2000)),
    previewToken: text(v.previewToken, 12000), operationKey: key64(v.operationKey), expiresInSeconds: integer(v.expiresInSeconds, 1, 600) };
}
function generated(raw: unknown): RoutineReceipt['generated'] { if (raw === null) return null; const v = object(raw); return { id: identifier(v.id), kind: kind(v.kind), revision: integer(v.revision), scheduledOn: routineDate(v.scheduledOn) }; }
function checkReceipt(result: RoutineReceipt, pending: RoutinePending): RoutineReceipt {
  if (result.operationKey !== pending.operationKey || result.operation !== pending.operation || pending.planId && result.planId !== pending.planId) invalid(); return result;
}
export function readRoutineReceipt(raw: unknown, pending: RoutinePending): RoutineReceipt {
  const v = object(raw); if (v.found !== true) invalid();
  return checkReceipt({ operationKey: key64(v.operationKey), operation: operation(v.operation), planId: identifier(v.planId), revision: integer(v.revision), generated: generated(v.generated), createdAt: timestamp(v.createdAt) }, pending);
}
export function readRoutineConfirmed(raw: unknown, pending: RoutinePending): RoutineReceipt {
  const v = object(raw), plan = readRoutinePlan(v.plan); bool(v.replayed);
  return checkReceipt({ operationKey: key64(v.operationKey), operation: operation(v.operation), planId: plan.id, revision: plan.revision, generated: generated(v.generated), createdAt: plan.updatedAt }, pending);
}
export const routineSignature = (s: RoutineSession) => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id, s.user?.auth_version, s.csrf]);
export class RoutineFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<RoutineSession>, job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const ticket = this.epoch;
    const check = (s: RoutineSession) => {
      if (ticket !== this.epoch || !current()) throw new RoutineDiscarded();
      if (!s || s.user?.role !== 'member' || typeof s.user.householdId !== 'string' || !s.user.householdId || typeof s.user.id !== 'string' || !s.user.id
        || !Number.isSafeInteger(s.user.auth_version) || Number(s.user.auth_version) < 1 || typeof s.csrf !== 'string' || !s.csrf || routineSignature(s) !== this.expected) throw new RoutineDiscarded('identity');
      return s.csrf;
    };
    const csrf = check(await me()); let result!: T, error: unknown, failed = false;
    try { result = await job(csrf); } catch (e) { failed = true; error = e; }
    check(await me()); if (failed) throw error; return result;
  }
}
export async function checkedRoutineWrite<T>(guard: RoutineGuard, write: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => { try { return await write(csrf); } catch (e) {
    if (e instanceof ResponseError && ([400, 404, 409].includes(e.status) || e.status === 410 && e.code === 'preview_expired_unapplied')) throw new RoutineRejected(e.message, e.status, e.code); throw e;
  } });
}
export async function routineRequest(path: string, signal: AbortSignal, options: { payload?: RoutinePayload | { previewToken: string }; csrf?: string } = {}): Promise<unknown> {
  const write = options.payload !== undefined;
  if (write ? !['/routines/preview', '/routines/confirm'].includes(path) || !options.csrf : path !== '/me' && !/^\/routines\/operations\/[a-f0-9]{64}$/.test(path) && !/^\/routines\/context\?page=(?:0|[1-9]\d{0,8})&includeArchived=(?:true|false)(?:&planId=[A-Za-z0-9_-]{1,100})?$/.test(path)) invalid();
  let payload: unknown;
  if (write) { if (path.endsWith('/preview')) payload = readRoutinePayload(options.payload); else { const v = object(options.payload); exact(v, ['previewToken']); payload = { previewToken: text(v.previewToken, 12000) }; } }
  const controller = new AbortController(), deadline = performance.now() + 30000, abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new RoutineDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new RoutineError('连接中断，请先核对例行计划操作结果。'); };
  check(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 30000);
  try {
    const response = await fetch('/api' + path, { method: write ? 'POST' : 'GET', mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(write ? { 'X-CSRF-Token': options.csrf! } : {}) }, ...(write ? { body: JSON.stringify(payload) } : {}) });
    check(); if ([401, 403].includes(response.status)) throw new ResponseError('身份或权限需要重新核对。', response.status);
    if (response.redirected || !response.headers.get('content-type')?.toLowerCase().includes('application/json')) invalid();
    const declared = response.headers.get('content-length'); if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > 4_000_000) || !response.body) invalid();
    const reader = response.body!.getReader(), chunks: Uint8Array[] = []; let size = 0;
    try { while (true) { const part = await reader.read(); check(); if (part.done) break; size += part.value.byteLength; if (size > 4_000_000) invalid(); chunks.push(part.value); } }
    catch (e) { await reader.cancel().catch(() => {}); throw e; } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    const value: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); check();
    if (!response.ok) { const code = typeof object(value).code === 'string' ? String(object(value).code) : '';
      throw new ResponseError(response.status === 409 ? '计划或当前事项已变化，请读取最新内容后重新预览。' : response.status === 410 && code === 'preview_expired_unapplied' ? '原预览已过期，服务器核对为尚未执行。' : response.status === 404 ? '当前未找到计划或操作记录，请先核对。' : '暂时无法读取或保存例行计划。', response.status, code); }
    return value;
  } catch (e) { check(); if (e instanceof RoutineError || e instanceof RoutineDiscarded) throw e; throw new RoutineError('连接中断或返回内容无法核对，请先读取操作结果。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
