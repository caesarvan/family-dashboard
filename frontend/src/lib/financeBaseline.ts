/** Owner-only read model. Source amounts and coverage are observations, not live balances. */
export type BaselineRow = { label: string; category: string; status: string; source: string; asOf: string; amountCents: number | null; currency: string;
  includedInRecordedSubtotal: boolean | null; exclusionReason: string | null; dateBasis: string | null; period: string | null; note: string | null };
export type BaselineQuality = { knownGapsCount: number | null; unreadableStatementsCount: number | null; channelOnlyAdded: boolean | null; orderOnlyAdded: boolean | null };
export type BaselineMonth = { period: string; currency: string | null; grossSpendCents: number | null; refundCents: number | null; netSpendCents: number | null; transactionCount: number | null };
export type BaselineSpending = { generatedAt: string | null; requestedStart: string | null; requestedEnd: string | null; monthly: BaselineMonth[]; quality: BaselineQuality | null; note: string | null };
export type BaselineSource = { converterVersion: string | null; files: { path: string; bytes: number | null }[]; generatedAt: string | null;
  requestedStart: string | null; requestedEnd: string | null; quality: BaselineQuality | null };
export type FinanceBaseline = { owner: string; revision: number; asOf: string; importedAt: string; balanceAsOfStart: string; balanceAsOfEnd: string;
  totals: { complete: boolean; assetCents: number | null; liabilityCents: number | null; netCents: number | null; recordedAssetCents: number; recordedLiabilityCents: number };
  assets: BaselineRow[]; liabilities: BaselineRow[]; income: BaselineRow[]; spending: BaselineSpending | null; sourceBridge: BaselineSource | null;
  spendingObservation: { revision: number; acceptedAt: string; origin: 'baseline' | 'spending_observation'; warnings: string[]; assetBaselineUnchanged: true } | null };
export class BaselineError extends Error { constructor(message: string, public status = 0) { super(message); } }
export class BaselineDiscarded extends Error {}
function bad(): never { throw new BaselineError('来源记录无法完整核对，请重新读取；未显示未核对的数据。'); }
const object = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const text = (v: unknown, max = 2000): string => typeof v === 'string' && Array.from(v).length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v) ? v : bad();
const requiredText = (v: unknown, max = 2000): string => text(v, max).trim() ? v as string : bad();
const optional = <T>(v: unknown, read: (value: unknown) => T): T | null => v === undefined || v === null ? null : read(v);
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min && v <= max ? v : bad();
const money = (v: unknown, signed = false): number => integer(v, signed ? -100_000_000_000_000 : 0, 100_000_000_000_000);
const currency = (v: unknown): string => typeof v === 'string' && /^[A-Z]{3}$/.test(v) ? v : bad();
const flag = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const array = (v: unknown, max: number): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
const day = (v: unknown): string => { const s = requiredText(v, 10); const d = new Date(s + 'T00:00:00Z'); return /^(?!0000)\d{4}-\d{2}-\d{2}$/.test(s) && Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === s ? s : bad(); };
const timestamp = (v: unknown): string => { const s = requiredText(v, 40); if (!/^\d{4}-\d\d-\d\dT(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(s) || !Number.isFinite(Date.parse(s))) bad(); day(s.slice(0, 10)); return s; };
const hash = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v) ? v : bad();
function quality(raw: unknown): BaselineQuality { const r = object(raw); return { knownGapsCount: optional(r.knownGapsCount, v => integer(v, 0, 1_000_000)), unreadableStatementsCount: optional(r.unreadableStatementsCount, v => integer(v, 0, 1_000_000)), channelOnlyAdded: optional(r.channelOnlyAdded, flag), orderOnlyAdded: optional(r.orderOnlyAdded, flag) }; }
function range(start: string | null, end: string | null) { if (start && end && start > end) bad(); }
function row(raw: unknown, income: boolean): BaselineRow { const r = object(raw); return { label: requiredText(r.label), category: requiredText(r.category), status: requiredText(r.status), source: requiredText(r.source), asOf: day(r.asOf), amountCents: r.amountCents === null ? null : money(r.amountCents), currency: currency(r.currency),
  includedInRecordedSubtotal: income ? optional(r.includedInRecordedSubtotal, flag) : flag(r.includedInRecordedSubtotal), exclusionReason: optional(r.exclusionReason, v => text(v)), dateBasis: optional(r.dateBasis, v => text(v)), period: optional(r.period, v => text(v, 100)), note: optional(r.note, v => text(v, 10000)) }; }
function spending(raw: unknown): BaselineSpending {
  const r = object(raw), start = optional(r.requestedStart, day), end = optional(r.requestedEnd, day); range(start, end);
  const monthly = array(r.monthly ?? [], 240).map(value => { const m = object(value), period = requiredText(m.period, 7); if (!/^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(period)) bad();
    const item: BaselineMonth = { period, currency: optional(m.currency, currency), grossSpendCents: optional(m.grossSpendCents, v => money(v)), refundCents: optional(m.refundCents, v => money(v)), netSpendCents: optional(m.netSpendCents, v => money(v, true)), transactionCount: optional(m.transactionCount, v => integer(v, 0, 1_000_000)) };
    if (item.grossSpendCents !== null && item.refundCents !== null && item.netSpendCents !== null && item.grossSpendCents - item.refundCents !== item.netSpendCents) bad();
    if (start && period < start.slice(0, 7) || end && period > end.slice(0, 7)) bad(); return item;
  });
  if (new Set(monthly.map(m => m.period + ':' + m.currency)).size !== monthly.length) bad();
  return { generatedAt: optional(r.generatedAt, timestamp), requestedStart: start, requestedEnd: end, monthly, quality: optional(r.quality, quality), note: optional(r.note, v => text(v, 10000)) };
}
function source(raw: unknown): BaselineSource {
  const r = object(raw), manifest = r.manifest === undefined ? {} : object(r.manifest), run = manifest.run === undefined ? {} : object(manifest.run), coverage = manifest.coverage === undefined ? {} : object(manifest.coverage);
  const requestedStart = optional(coverage.requestedStart, day), requestedEnd = optional(coverage.requestedEnd, day); range(requestedStart, requestedEnd);
  const files = array(manifest.files ?? [], 50).map(value => { const f = object(value); if (f.sha256 !== undefined) hash(f.sha256); return { path: requiredText(f.path), bytes: optional(f.bytes, v => integer(v, 0, 50_000_000)) }; });
  return { converterVersion: optional(r.converterVersion, v => text(v, 100)), files, generatedAt: optional(run.generatedAt, timestamp), requestedStart, requestedEnd, quality: manifest.coverage === undefined ? null : quality(coverage) };
}
export function readFinanceBaseline(raw: unknown, expectedOwner: string): FinanceBaseline | null {
  if (!expectedOwner) bad(); if (raw === null) return null;
  const r = object(raw); if (r.schemaVersion !== 1 || r.owner !== expectedOwner || r.currency !== 'CNY') bad(); hash(r.sourceDigest);
  const t = object(r.totals); for (const key of ['assetCents', 'liabilityCents', 'netCents']) if (!Object.hasOwn(t, key)) bad();
  const totals = { complete: flag(t.complete), assetCents: optional(t.assetCents, v => money(v)), liabilityCents: optional(t.liabilityCents, v => money(v)), netCents: optional(t.netCents, v => money(v, true)), recordedAssetCents: money(t.recordedAssetCents), recordedLiabilityCents: money(t.recordedLiabilityCents) };
  if (totals.complete ? totals.assetCents !== totals.recordedAssetCents || totals.liabilityCents !== totals.recordedLiabilityCents || totals.netCents !== totals.recordedAssetCents - totals.recordedLiabilityCents : [totals.assetCents, totals.liabilityCents, totals.netCents].some(v => v !== null)) bad();
  const assets = array(r.assets, 500).map(v => row(v, false)), liabilities = array(r.liabilities, 500).map(v => row(v, false)), income = array(r.income, 500).map(v => row(v, true));
  for (const [rows, sum] of [[assets, totals.recordedAssetCents], [liabilities, totals.recordedLiabilityCents]] as const) {
    let actual = 0n; for (const item of rows) if (item.includedInRecordedSubtotal) { if (item.currency !== 'CNY' || item.amountCents === null) bad(); actual += BigInt(item.amountCents); } if (actual !== BigInt(sum)) bad();
  }
  let observation: FinanceBaseline['spendingObservation'] = null;
  if (r.spendingObservation !== undefined && r.spendingObservation !== null) { const o = object(r.spendingObservation); hash(o.sourceDigest); if (o.origin !== 'baseline' && o.origin !== 'spending_observation' || o.assetBaselineUnchanged !== true) bad();
    observation = { revision: integer(o.revision, 1), acceptedAt: timestamp(o.acceptedAt), origin: o.origin, assetBaselineUnchanged: true, warnings: array(o.warnings, 50).map(v => text(v, 10000)) };
  }
  const result: FinanceBaseline = { owner: expectedOwner, revision: integer(r.revision, 1), asOf: day(r.asOf), importedAt: timestamp(r.importedAt), balanceAsOfStart: day(r.balanceAsOfStart), balanceAsOfEnd: day(r.balanceAsOfEnd), totals, assets, liabilities, income,
    spending: optional(r.spending, spending), sourceBridge: optional(r.sourceBridge, source), spendingObservation: observation };
  if (result.balanceAsOfStart > result.balanceAsOfEnd || result.balanceAsOfEnd > result.asOf) bad(); return result;
}
/** No floating-point division, conversion, inferred zero, or cross-currency sums. */
export function formatBaselineMoney(value: number | null, code: string | null): string {
  if (value === null) return '金额待核对'; const amount = BigInt(money(value, true)), absolute = amount < 0n ? -amount : amount;
  const whole = String(absolute / 100n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${code === null ? '币种待核对' : currency(code)} ${amount < 0n ? '-' : ''}${whole}.${String(absolute % 100n).padStart(2, '0')}`;
}
export function formatBaselineTime(value: string | null): string { return value === null ? '日期待核对' : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(timestamp(value))) + '（北京时间）'; }
export function baselinePage<T>(rows: readonly T[], query: string, page: number, searchable: (row: T) => string, size = 10): { rows: T[]; page: number; pages: number; count: number } {
  integer(page); integer(size, 1, 50); const needle = text(query, 200).trim().toLocaleLowerCase();
  const filtered = needle ? rows.filter(item => searchable(item).toLocaleLowerCase().includes(needle)) : [...rows]; const pages = Math.max(1, Math.ceil(filtered.length / size)), selected = Math.min(page, pages - 1);
  return { rows: filtered.slice(selected * size, (selected + 1) * size), page: selected, pages, count: filtered.length };
}
export type BaselineSession = { user: { role: 'member' | 'tv'; householdId?: string; id: string; auth_version?: number } | null; csrf?: string | null };
export const baselineSignature = (s: BaselineSession) => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id, s.user?.auth_version, s.csrf]);
export class BaselineFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<BaselineSession>, read: () => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (s: BaselineSession) => { if (!current() || this.epoch !== epoch) throw new BaselineDiscarded(); if (!s || s.user?.role !== 'member' || typeof s.user.householdId !== 'string' || !s.user.householdId || typeof s.user.id !== 'string' || !s.user.id || !Number.isSafeInteger(s.user.auth_version) || Number(s.user.auth_version) < 1 || typeof s.csrf !== 'string' || !s.csrf || baselineSignature(s) !== this.expected) throw new BaselineDiscarded('identity'); };
    check(await me()); let result!: T, error: unknown, failed = false; try { result = await read(); } catch (e) { error = e; failed = true; }
    check(await me()); if (failed) throw error; return result;
  }
}
export async function baselineRequest(path: '/me' | '/finance-baseline/private', signal: AbortSignal): Promise<unknown> {
  if (path !== '/me' && path !== '/finance-baseline/private') bad();
  const controller = new AbortController(), deadline = performance.now() + 15000, abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new BaselineDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new BaselineError('读取超时或连接中断，请重新读取。'); };
  if (signal.aborted) throw new BaselineDiscarded(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15000);
  try { const response = await fetch('/api' + path, { method: 'GET', mode: 'same-origin', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal, headers: { Accept: 'application/json' } }); check();
    if (!response.ok) throw new BaselineError([401, 403].includes(response.status) ? '身份或权限需要重新核对。' : '暂时无法读取来源报告，请稍后重试。', response.status);
    if (response.redirected || !(response.headers.get('Content-Type') || '').toLowerCase().includes('application/json')) bad();
    // Count bytes while streaming: a malformed source cannot force an unbounded body read.
    const reader = response.body?.getReader(); if (!reader) bad(); const chunks: Uint8Array[] = []; let length = 0;
    try { while (true) { const { done, value } = await reader.read(); check(); if (done) break; length += value.byteLength; if (length > 4_000_000) { controller.abort(); throw new BaselineError('来源记录超过可读取范围，请先核对来源。'); } chunks.push(value); } }
    finally { void reader.cancel().catch(() => {}); reader.releaseLock(); }
    const all = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { all.set(chunk, offset); offset += chunk.byteLength; }
    check(); try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(all)); } catch { return bad(); }
  } catch (e) { check(); if (e instanceof BaselineError || e instanceof BaselineDiscarded) throw e; throw new BaselineError('连接中断，请重新读取来源报告。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
