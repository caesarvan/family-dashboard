/** Explicit private source import. Financial normalization belongs to the server. */
import { formatBaselineTime } from './financeBaseline';
export type SourceMode = 'baseline' | 'spending_observation';
export type SourceSession = { user: { role: string; householdId?: string; id: string; auth_version?: number } | null; csrf?: string | null };
export type SourceOperation = { mode: SourceMode; operationId: string };
export type SourceReceipt = { receiptId: string; status: 'imported' | 'unchanged'; revision: number; sourceDigest: string; candidateDigest: string; acceptedAt: string; replayed: boolean };
type Dates = { asOf: string | null; balanceAsOfStart: string | null; balanceAsOfEnd: string | null };
type Quality = { knownGapsCount: number; unreadableStatementsCount: number; channelOnlyAdded: boolean; orderOnlyAdded: boolean };
export type SourceStatus = { mode: SourceMode; expected: Record<string, number | string | null>; dates: Dates; baselineExists: boolean; unknownCoverage: boolean; warnings: string[] };
export type SourceRow = { title: string; kind: string; date: string; amountCents: number | null; currency: string; note: string; gross?: number | null; refund?: number | null };
export type SourcePreview = SourceOperation & { previewToken: string; candidateDigest: string; dates: Dates; coverage: { start: string; end: string; generatedAt: string; quality: Quality };
  shared: { assets: number; liabilities: number } | null; changes: { added: number; updated: number; preserved: number }; removedMonths: string[]; warnings: string[]; rows: SourceRow[]; files: string[] };
export type SourceIntent = SourceOperation & { body: Readonly<Record<string, unknown>>; candidateDigest: string; identity: string };
export type SourceEndReview = SourceOperation & { identity: string; status: SourceStatus };
export class SourceError extends Error { status: number; code: string; constructor(message: string, status = 0, code = '') { super(message); this.status = status; this.code = code; } }
export class SourceDiscarded extends Error {}
export class SourceRejected extends SourceError {}
const bad = (): never => { throw new SourceError('来源响应无法完整核对，请重新读取。'); };
const obj = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const text = (v: unknown, max = 2000): string => typeof v === 'string' && v.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v) ? v : bad();
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min && v <= max ? v : bad();
const flag = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const list = (v: unknown, max = 1500): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
const hash = (v: unknown): string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v) ? v : bad();
const modeOf = (v: unknown): SourceMode => v === 'baseline' || v === 'spending_observation' ? v : bad();
const day = (v: unknown): string => { const s = text(v, 10), d = new Date(s + 'T00:00:00Z'); return /^(?!0000)\d{4}-\d{2}-\d{2}$/.test(s) && Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === s ? s : bad(); };
const nullableDay = (v: unknown) => v === null ? null : day(v);
const dates = (raw: unknown): Dates => { const v = obj(raw); return { asOf: nullableDay(v.asOf), balanceAsOfStart: nullableDay(v.balanceAsOfStart), balanceAsOfEnd: nullableDay(v.balanceAsOfEnd) }; };
const warnings = (v: unknown) => list(v, 300).map(x => text(x, 5000));
const currency = (v: unknown) => typeof v === 'string' && /^[A-Z]{3}$/.test(v) ? v : bad();
const money = (v: unknown): number | null => v === null ? null : integer(v, -100_000_000_000_000, 100_000_000_000_000);
const describe = (value: unknown): string => { const s = text(value); return ({ dated_record: '有日期的来源记录', confirmed: '已确认', unknown: '待核对', historical_income_not_asset: '历史收入，不计入资产' } as Record<string, string>)[s] || s; };
const stamp = (v: unknown) => { const s = text(v, 100); try { formatBaselineTime(s); return s; } catch { return bad(); } };
function expected(revision: unknown, digest: unknown) { const n = integer(revision); if (n === 0 && digest !== null) bad(); return { revision: n, digest: n === 0 ? null : hash(digest) }; }
export const sourceSignature = (s: SourceSession) => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id, s.user?.auth_version, s.csrf]);
export const sourceActor = (s: SourceSession): string => s.user?.role === 'member' && s.user.householdId && s.user.id ? JSON.stringify([s.user.householdId, s.user.id]) : bad();
/** Project only the opaque recovery handle, even when passed an in-memory intent. */
export const sourceOperation = (operation: SourceOperation): SourceOperation => ({ mode: modeOf(operation.mode), operationId: hash(operation.operationId) });
/** Scope each opaque handle to its household/member; a late result cannot clear a newer handle. */
export class SourceRecoveryMemory {
  private values = new Map<string, SourceOperation>();
  get(actor: string): SourceOperation | null { const value = this.values.get(actor); return value ? sourceOperation(value) : null; }
  set(actor: string, operation: SourceOperation) { this.values.set(actor, sourceOperation(operation)); }
  clear(actor: string, operation: SourceOperation): boolean { const current = this.values.get(actor); if (current?.mode !== operation.mode || current.operationId !== operation.operationId) return false; this.values.delete(actor); return true; }
}
/** Only a guarded current-status read AND the exact no-receipt read can offer this decision. */
export function sourceEndReview(operation: SourceOperation, status: SourceStatus, receipt: SourceReceipt | null, identity: string): SourceEndReview | null {
  if (receipt !== null || !identity || status.mode !== operation.mode) return null;
  return { ...sourceOperation(operation), identity, status };
}
export function canEndSourceReview(review: SourceEndReview | null, operation: SourceOperation | null, identity: string, confirmed: boolean): boolean {
  return confirmed === true && !!review && !!operation && review.identity === identity && review.mode === operation.mode && review.operationId === operation.operationId;
}
export function sourceStatusPath(mode: SourceMode, operationId?: string): string { return '/finance-baseline/imports/status?mode=' + modeOf(mode) + (operationId === undefined ? '' : '&operationId=' + hash(operationId)); }
export function readSourceStatus(raw: unknown, mode: SourceMode): SourceStatus {
  const v = obj(raw); modeOf(mode);
  if (mode === 'baseline') {
    const current = v.current === null ? null : obj(v.current), e = current ? expected(current.revision, current.sourceDigest) : { revision: 0, digest: null };
    if (v.coverage !== 'partial_dated_records') bad();
    return { mode, expected: { expectedRevision: e.revision, expectedSourceDigest: e.digest }, dates: current ? dates(current) : { asOf: null, balanceAsOfStart: null, balanceAsOfEnd: null }, baselineExists: !!current, unknownCoverage: false, warnings: warnings(v.warnings) };
  }
  if (v.mode !== mode) bad(); const e = obj(v.expected), own = expected(e.expectedRevision, e.expectedSourceDigest), base = expected(e.expectedBaselineRevision, e.expectedBaselineSourceDigest), b = obj(v.baseline);
  const exists = flag(b.exists); if (exists !== (base.revision > 0)) bad();
  return { mode, expected: { expectedRevision: own.revision, expectedSourceDigest: own.digest, expectedBaselineRevision: base.revision, expectedBaselineSourceDigest: base.digest }, dates: dates(b), baselineExists: exists, unknownCoverage: flag(v.requiresUnknownCoverageAcknowledgement), warnings: warnings(v.warnings) };
}
export const MAX_SOURCE_BYTES = 1_950_000;
/** Bound and freeze arbitrary candidate JSON; do not repair its rows or calculate totals. */
export function parseSourceJSON(raw: string, mode: SourceMode): Readonly<Record<string, unknown>> {
  if (typeof raw !== 'string' || !raw.trim() || raw.length >= MAX_SOURCE_BYTES || new TextEncoder().encode(raw).byteLength >= MAX_SOURCE_BYTES) throw new SourceError('请选择或粘贴非空且小于 1.95 MB 的来源 JSON。');
  let value: unknown; try { value = JSON.parse(raw.replace(/^\uFEFF/, '')); } catch { throw new SourceError('JSON 无法解析，请检查文件；页面不会自动修补内容。'); }
  const root = obj(value); if ((root.kind === 'spending_observation') !== (modeOf(mode) === 'spending_observation')) throw new SourceError('来源 JSON 与所选更新范围不一致。');
  let count = 0;
  function freeze(v: unknown, depth: number) { if (++count > 100_000 || depth > 30) throw new SourceError('来源 JSON 结构过大或嵌套过深。'); if (typeof v === 'number' && (!Number.isFinite(v) || Math.abs(v) > Number.MAX_SAFE_INTEGER)) throw new SourceError('来源数字超出安全读取范围，请重新生成来源包。'); if (v && typeof v === 'object') { for (const [k, item] of Object.entries(v)) { if (['__proto__', 'constructor', 'prototype'].includes(k)) throw new SourceError('来源 JSON 含不支持的字段。'); freeze(item, depth + 1); } Object.freeze(v); } }
  freeze(root, 0); return root;
}
export function sourcePreviewBody(status: SourceStatus, candidate: Readonly<Record<string, unknown>>, acknowledge: boolean) {
  if (status.mode === 'spending_observation') {
    if (!status.baselineExists) throw new SourceError('尚无本人资产基线，请先核对完整资产来源。');
    if (status.unknownCoverage && !acknowledge) throw new SourceError('请明确确认旧消费覆盖未知，原快照仍保留。');
    return { mode: status.mode, candidate, ...status.expected, acknowledgeUnknownPreviousCoverage: acknowledge };
  }
  return { candidate, ...status.expected };
}
export function readSourcePreview(raw: unknown, mode: SourceMode, owner: string): SourcePreview {
  const v = obj(raw); if (v.expiresIn !== 1200 || (mode === 'spending_observation' && (v.mode !== mode || v.assetBaselineUnchanged !== true))) bad();
  const c = obj(v.changes); const p = mode === 'baseline' ? obj(v.private) : null;
  if (p && p.owner !== owner) bad();
  const s = obj(mode === 'baseline' ? p!.spending : v.spending), q = obj(s.quality);
  const coverage = { start: day(s.requestedStart), end: day(s.requestedEnd), generatedAt: stamp(s.generatedAt), quality: { knownGapsCount: integer(q.knownGapsCount, 0, 1_000_000), unreadableStatementsCount: integer(q.unreadableStatementsCount, 0, 1_000_000), channelOnlyAdded: flag(q.channelOnlyAdded), orderOnlyAdded: flag(q.orderOnlyAdded) } };
  const rows: SourceRow[] = [];
  if (p) for (const [key, kind] of [['assets', '资产'], ['liabilities', '负债'], ['income', '历史收入']]) for (const item of list(p[key], 500)) { const r = obj(item); rows.push({ title: text(r.label), kind, date: day(r.asOf), amountCents: money(r.amountCents), currency: currency(r.currency), note: [describe(r.status), r.exclusionReason == null ? '' : describe(r.exclusionReason), r.source == null ? '' : text(r.source)].filter(Boolean).join(' · ') }); }
  const months = list(s.monthly, 240);
  for (const item of months) { const r = obj(item), period = text(r.period, 7); if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(period)) bad(); rows.push({ title: period, kind: '消费观察', date: period, amountCents: money(r.netSpendCents), currency: currency(r.currency), gross: money(r.grossSpendCents), refund: money(r.refundCents), note: `来源笔数 ${integer(r.transactionCount, 0, 1_000_000)}` }); }
  const shared = p ? obj(v.shared) : null;
  const bridge = p ? obj(p.sourceBridge) : null;
  return { mode, operationId: hash(v.operationId), previewToken: text(v.previewToken, 4000) || bad(), candidateDigest: hash(v.candidateDigest), dates: dates(p || v.baseline), coverage,
    shared: shared ? { assets: integer(shared.recordedAssetCents, 0, 100_000_000_000_000), liabilities: integer(shared.recordedLiabilityCents, 0, 100_000_000_000_000) } : null,
    changes: { added: integer(c.added, 0, 1740), updated: integer(c.updated, 0, 1740), preserved: integer(c.preserved, 0, 1740) }, rows,
    removedMonths: mode === 'spending_observation' ? list(c.removedMonths, 240).map(x => { const r = obj(x); return text(r.period, 7) + ' · ' + currency(r.currency); }) : [], warnings: warnings(v.warnings),
    files: bridge ? list(obj(bridge.manifest).files, 100).map(x => text(obj(x).path, 1000)) : [] };
}
export function sourceIntent(preview: SourcePreview, candidate: Readonly<Record<string, unknown>>, identity: string): SourceIntent {
  return { mode: preview.mode, operationId: hash(preview.operationId), candidateDigest: preview.candidateDigest, identity,
    body: Object.freeze({ candidate, previewToken: preview.previewToken, ...(preview.mode === 'spending_observation' ? { mode: preview.mode } : {}) }) };
}
export function readSourceReceipt(raw: unknown, operation: SourceOperation, digest?: string): SourceReceipt {
  const v = obj(raw); if (hash(v.receiptId) !== hash(operation.operationId) || !['imported', 'unchanged'].includes(String(v.status)) || (operation.mode === 'spending_observation' && v.assetBaselineUnchanged !== true)) bad();
  if (digest !== undefined && hash(v.candidateDigest) !== hash(digest)) bad();
  return { receiptId: v.receiptId as string, status: v.status as SourceReceipt['status'], revision: integer(v.revision, 1), sourceDigest: hash(v.sourceDigest), candidateDigest: hash(v.candidateDigest), acceptedAt: stamp(v.acceptedAt), replayed: flag(v.replayed) };
}
export function readSourceOperation(raw: unknown, operation: SourceOperation): SourceReceipt | null {
  const v = obj(raw); if (v.mode !== modeOf(operation.mode) || v.operationId !== hash(operation.operationId)) bad();
  if (!flag(v.found)) { if (v.receipt !== null) bad(); return null; }
  const receipt = readSourceReceipt(v.receipt, operation); if (!receipt.replayed) bad(); return receipt;
}
export class SourceFence {
  private epoch = 0;
  private identity: string;
  constructor(identity: string) { this.identity = identity; }
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<SourceSession>, job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (s: SourceSession) => { if (!current() || epoch !== this.epoch) throw new SourceDiscarded(); if (!s || s.user?.role !== 'member' || !s.user.id || !s.user.householdId || !Number.isSafeInteger(s.user.auth_version) || Number(s.user.auth_version) < 1 || typeof s.csrf !== 'string' || !s.csrf || sourceSignature(s) !== this.identity) throw new SourceDiscarded('identity'); return s.csrf; };
    const csrf = check(await me()); let result!: T, failed = false, error: unknown; try { result = await job(csrf); } catch (e) { failed = true; error = e; }
    check(await me()); if (failed) throw error; return result;
  }
}
export async function checkedSourceConfirm<T>(guard: (job: (csrf: string) => Promise<T>) => Promise<T>, write: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => { try { return await write(csrf); } catch (e) { if (e instanceof SourceError && [400, 409, 410, 415, 422, 429].includes(e.status)) throw new SourceRejected(e.message, e.status, e.code); throw e; } });
}
export function permitsSourceRepreview(error: unknown): boolean { return error instanceof SourceRejected && (error.status === 410 && error.code === 'preview_expired' || error.status === 409 && error.code === 'preview_repreview_required'); }
/** Fixed same-origin paths only; the secret candidate never reaches URL or storage. */
export async function sourceRequest(path: string, signal: AbortSignal, payload?: Readonly<Record<string, unknown>>, csrf = ''): Promise<unknown> {
  const read = path === '/me' || /^\/finance-baseline\/imports\/status\?mode=(baseline|spending_observation)(&operationId=[a-f0-9]{64})?$/.test(path);
  const write = ['/finance-baseline/imports/preview', '/finance-baseline/imports/confirm'].includes(path);
  if (payload === undefined ? !read : !write || !csrf) bad();
  const body = payload === undefined ? undefined : JSON.stringify(payload);
  if (body && new TextEncoder().encode(body).byteLength >= 2_000_000) throw new SourceError('来源请求过大，请核对文件大小。');
  const controller = new AbortController(), deadline = performance.now() + 30_000, abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new SourceDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new SourceError('连接中断或超时，请先核对操作结果。'); };
  if (signal.aborted) throw new SourceDiscarded(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 30_000);
  try {
    const response = await fetch('/api' + path, { method: payload === undefined ? 'GET' : 'POST', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json', ...(payload === undefined ? {} : { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }) }, ...(body ? { body } : {}) }); check();
    if (response.status === 401 || response.status === 403) throw new SourceError('登录或权限已变化，请重新核对身份。', response.status);
    if (response.redirected || !response.headers.get('Content-Type')?.toLowerCase().includes('application/json')) throw new SourceError('来源服务未返回可核对的 JSON，请重新读取。', response.status);
    const reader = response.body?.getReader(); if (!reader) throw new SourceError('来源响应为空，请重新读取。'); let size = 0; const parts: Uint8Array[] = [];
    try { while (true) { const part = await reader.read(); check(); if (part.done) break; size += part.value.byteLength; if (size > 4_000_000) { controller.abort(); throw new SourceError('来源响应过大，已停止读取。'); } parts.push(part.value); } } finally { void reader.cancel().catch(() => {}); reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0; for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
    let value: unknown; try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { bad(); } check();
    if (!response.ok) { const error = obj(value); throw new SourceError(typeof error.error === 'string' ? text(error.error, 2000) : '来源操作未完成，请核对当前状态。', response.status, typeof error.code === 'string' ? text(error.code, 100) : ''); }
    return value;
  } catch (e) { check(); if (e instanceof SourceError || e instanceof SourceDiscarded) throw e; throw new SourceError('连接中断，请先核对操作结果。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
