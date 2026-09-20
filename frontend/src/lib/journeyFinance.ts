import { ApiError, request } from './api.ts';
import { PlaceFence } from './places.ts';
import { decimalInput } from './finance.ts';

export const JOURNEY_FINANCE = '/finance-hub/journey-allocations';
export type JourneyRef = { id: string; tripId: string; revision: number; tripRevision: number; title: string; sharedBudgetCents: number; sharedManualPaidCents: number; sharedSavedCents: number };
export type Payment = { id: string; revision: number; date: string; title: string; kind: 'payments'; flow: string; currency: string; amountCents: number; refundedCents: number; netCents: number; reservedCents: number; availableCents: number; eligible: boolean; reasonCode: string | null };
export type Allocation = { id: string; revision: number; journeyId: string; tripId: string; paymentId: string; amountCents: number; status: 'active' | 'revoked'; state: 'current' | 'needs_review' | 'revoked'; reasonCodes: string[]; acceptedNetCents: number; acceptedRefundedCents: number; createdAt: string; updatedAt: string; journey: JourneyRef | null; payment: Payment | null };
type Page = { page: number; pageSize: 40; hasMore: boolean };
export type Summary = { currency: 'CNY'; coverage: 'owner_partial'; currentAllocatedCents: number; needsReviewAllocatedCents: number; activeAllocatedCents: number; currentCount: number; needsReviewCount: number; sharedBudgetCents: number };
export type Allocations = { journey: JourneyRef | null; summary: Summary | null; allocations: Allocation[]; pageInfo: Page; readAt: string };
export type Payments = { journey: JourneyRef; payments: Payment[]; focus: Payment | null; pageInfo: Page; readAt: string };
export type Query = { journeyId?: string; paymentId?: string; status?: 'active' | 'all'; page?: number };
export type Plan = { operation: 'apply'; journeyId: string; journeyRevision: number; tripRevision: number; paymentId: string; paymentRevision: number; amountCents: number }
  | { operation: 'update'; allocationId: string; revision: number; journeyRevision: number; tripRevision: number; paymentRevision: number; amountCents: number }
  | { operation: 'revoke'; allocationId: string; revision: number };
export type Preview = { operation: Plan['operation']; allocationId: string | null; journey: JourneyRef | null; payment: Payment | null; beforeAllocatedCents: number; afterAllocatedCents: number; beforeStatus: 'active' | null; afterStatus: 'active' | 'revoked'; warnings: string[]; previewToken: string; expiresAt: string; expiresInSeconds: 600 };
export type Intent = Readonly<{ requestId: string; previewToken: string }>;
export type Receipt = { requestId: string; operation: Plan['operation']; allocationId: string; revision: number; completedAt: string };
export type OriginalPayment = { id: string; revision: number; date: string; title: string; amountCents: number; currency: string; flow: string; category: string; source: string };
export const reasonText: Record<string, string> = { journey_missing: '原旅行已删除，可以解除这项归集', source_missing: '原付款已删除，可以解除这项归集', source_changed: '原付款或退款关联已变化，请重新核对', source_ineligible: '原付款已不适合归集', payment_overallocated: '已归集金额超出当前净付款', not_expense: '不是消费付款', duplicate: '已确认为重复付款', unsupported_currency: '仅支持人民币付款' };
const bad = (): never => { throw new Error('旅行费用资料无法核对，请重新读取。'); };
const obj = (v: unknown): Record<string, any> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, any> : bad();
const text = (v: unknown, max = 2000): string => typeof v === 'string' && v.length <= max && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v) ? v : bad();
const integer = (v: unknown, min = 0): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min ? v : bad();
const flag = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const one = <T extends string>(v: unknown, values: readonly T[]): T => values.includes(v as T) ? v as T : bad();
const id = (v: unknown, size: number): string => typeof v === 'string' && new RegExp('^[a-f0-9]{' + size + '}$').test(v) ? v : bad();
export const paymentId = (v: unknown): string => typeof v === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(v) ? v : bad();
const currency = (v: unknown): string => typeof v === 'string' && /^[A-Z]{3}$/.test(v) ? v : bad();
const timestamp = (v: unknown): string => { const s = text(v, 80); return Number.isFinite(Date.parse(s)) ? s : bad(); };
const array = <T,>(v: unknown, read: (x: unknown) => T, max = 40): T[] => Array.isArray(v) && v.length <= max ? v.map(read) : bad();
const unique = <T extends { id: string }>(v: T[]): T[] => new Set(v.map(x => x.id)).size === v.length ? v : bad();
function version(v: unknown) { const r = obj(v); if (r.version !== 1) bad(); return r; }
function page(v: unknown, expected: number): Page { const r = obj(v); if (r.pageSize !== 40 || r.page !== expected) bad(); return { page: integer(r.page), pageSize: 40, hasMore: flag(r.hasMore) }; }
export function readJourney(v: unknown): JourneyRef { const r = obj(v); return { id: id(r.id, 24), tripId: id(r.tripId, 24), revision: integer(r.revision, 1), tripRevision: integer(r.tripRevision, 1), title: text(r.title), sharedBudgetCents: integer(r.sharedBudgetCents), sharedManualPaidCents: integer(r.sharedManualPaidCents), sharedSavedCents: integer(r.sharedSavedCents) }; }
export function readPayment(v: unknown): Payment {
  const r = obj(v), p: Payment = { id: paymentId(r.id), revision: integer(r.revision, 1), date: text(r.date, 10), title: text(r.title), kind: one(r.kind, ['payments']), flow: one(r.flow, ['expense', 'income', 'refund', 'transfer', 'unknown', 'excluded']), currency: currency(r.currency), amountCents: integer(r.amountCents), refundedCents: integer(r.refundedCents), netCents: integer(r.netCents), reservedCents: integer(r.reservedCents), availableCents: integer(r.availableCents), eligible: flag(r.eligible), reasonCode: r.reasonCode === null ? null : one(r.reasonCode, ['not_expense', 'duplicate', 'unsupported_currency']) };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(p.date) || p.availableCents !== Math.max(0, p.netCents - p.reservedCents) || p.eligible && (p.currency !== 'CNY' || p.flow !== 'expense' || p.reasonCode !== null)) bad();
  return p;
}
export function readAllocation(v: unknown): Allocation {
  const r = obj(v), a: Allocation = { id: id(r.id, 32), revision: integer(r.revision, 1), journeyId: id(r.journeyId, 24), tripId: id(r.tripId, 24), paymentId: paymentId(r.paymentId), amountCents: integer(r.amountCents, 1), status: one(r.status, ['active', 'revoked']), state: one(r.state, ['current', 'needs_review', 'revoked']), reasonCodes: array(r.reasonCodes, x => one(x, ['journey_missing', 'source_missing', 'source_changed', 'source_ineligible', 'payment_overallocated']), 5), acceptedNetCents: integer(r.acceptedNetCents), acceptedRefundedCents: integer(r.acceptedRefundedCents), createdAt: timestamp(r.createdAt), updatedAt: timestamp(r.updatedAt), journey: r.journey === null ? null : readJourney(r.journey), payment: r.payment === null ? null : readPayment(r.payment) };
  if (a.journey && (a.journey.id !== a.journeyId || a.journey.tripId !== a.tripId) || a.payment && a.payment.id !== a.paymentId || (a.status === 'revoked') !== (a.state === 'revoked')) bad();
  return a;
}
export function allocationsPath(q: Query): string {
  if (q.journeyId && q.paymentId) bad();
  const params = new URLSearchParams({ page: String(integer(q.page ?? 0)), status: one(q.status ?? 'active', ['active', 'all']) });
  if (q.journeyId) params.set('journeyId', id(q.journeyId, 24));
  if (q.paymentId) params.set('paymentId', paymentId(q.paymentId));
  return JOURNEY_FINANCE + '?' + params;
}
export function readAllocations(v: unknown, q: Query): Allocations {
  const r = version(v), journey = r.journey === null ? null : readJourney(r.journey);
  if (q.journeyId ? journey?.id !== q.journeyId : journey !== null) bad();
  let summary: Summary | null = null;
  if (r.summary !== null) {
    const s = obj(r.summary); summary = { currency: one(s.currency, ['CNY']), coverage: one(s.coverage, ['owner_partial']), currentAllocatedCents: integer(s.currentAllocatedCents), needsReviewAllocatedCents: integer(s.needsReviewAllocatedCents), activeAllocatedCents: integer(s.activeAllocatedCents), currentCount: integer(s.currentCount), needsReviewCount: integer(s.needsReviewCount), sharedBudgetCents: integer(s.sharedBudgetCents) };
    if (BigInt(summary.currentAllocatedCents) + BigInt(summary.needsReviewAllocatedCents) !== BigInt(summary.activeAllocatedCents)) bad();
  }
  if (!!q.journeyId !== !!summary) bad();
  const allocations = unique(array(r.allocations, readAllocation));
  if (allocations.some(a => q.journeyId && a.journeyId !== q.journeyId || q.paymentId && a.paymentId !== q.paymentId || q.status !== 'all' && a.status !== 'active')) bad();
  return { journey, summary, allocations, pageInfo: page(r.pageInfo, q.page ?? 0), readAt: timestamp(r.readAt) };
}
export function paymentsPath(journeyId: string, q: string, pageNumber: number, allocationId?: string) {
  const p = new URLSearchParams({ journeyId: id(journeyId, 24), q: text(q, 80), page: String(integer(pageNumber)) });
  if (allocationId) p.set('allocationId', id(allocationId, 32));
  return JOURNEY_FINANCE + '/payments?' + p;
}
export function readPayments(v: unknown, journeyId: string, pageNumber: number, originalId?: string): Payments {
  const r = version(v), journey = readJourney(r.journey), focus = r.focus === null ? null : readPayment(r.focus);
  if (journey.id !== journeyId || focus && (!originalId || focus.id !== originalId) || !originalId && focus !== null) bad();
  return { journey, focus, payments: unique(array(r.payments, readPayment)), pageInfo: page(r.pageInfo, pageNumber), readAt: timestamp(r.readAt) };
}
export function amountCents(value: string): number {
  const n = BigInt(decimalInput(value, true, 1_000_000_000n).replace('.', ''));
  if (n > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('金额超出允许范围。');
  return Number(n);
}
export function allocationPlan(j: JourneyRef, p: Payment, value: string, link?: Allocation): Plan {
  if (!p.eligible || p.currency !== 'CNY') throw new Error('请选择本人有效的人民币消费付款。');
  const amount = amountCents(value);
  if (amount > p.availableCents) throw new Error('归集金额超过当前可用净付款，请核对退款及其他旅行归集。');
  if (link && (link.status !== 'active' || link.journeyId !== j.id || link.paymentId !== p.id)) bad();
  return link ? { operation: 'update', allocationId: link.id, revision: link.revision, journeyRevision: j.revision, tripRevision: j.tripRevision, paymentRevision: p.revision, amountCents: amount }
    : { operation: 'apply', journeyId: j.id, journeyRevision: j.revision, tripRevision: j.tripRevision, paymentId: p.id, paymentRevision: p.revision, amountCents: amount };
}
export function readPreview(v: unknown, plan: Plan, expected?: { journeyId: string; paymentId: string }): Preview {
  const r = version(v), p: Preview = { operation: one(r.operation, ['apply', 'update', 'revoke']), allocationId: r.allocationId === null ? null : id(r.allocationId, 32), journey: r.journey === null ? null : readJourney(r.journey), payment: r.payment === null ? null : readPayment(r.payment), beforeAllocatedCents: integer(r.beforeAllocatedCents), afterAllocatedCents: integer(r.afterAllocatedCents), beforeStatus: r.beforeStatus === null ? null : one(r.beforeStatus, ['active'] as const), afterStatus: one(r.afterStatus, ['active', 'revoked']), warnings: array(r.warnings, x => text(x), 30), previewToken: text(r.previewToken, 12000), expiresAt: timestamp(r.expiresAt), expiresInSeconds: r.expiresInSeconds === 600 ? 600 : bad() };
  if (!p.previewToken || p.operation !== plan.operation || p.allocationId !== (plan.operation === 'apply' ? null : plan.allocationId)
    || p.afterAllocatedCents !== (plan.operation === 'revoke' ? 0 : plan.amountCents) || p.afterStatus !== (plan.operation === 'revoke' ? 'revoked' : 'active')
    || r.unchanged?.ledger !== true || r.unchanged?.shopping !== true || r.unchanged?.sharedTrip !== true) bad();
  if (plan.operation !== 'revoke' && (!p.journey || !p.payment || p.journey.revision !== plan.journeyRevision || p.journey.tripRevision !== plan.tripRevision || p.payment.revision !== plan.paymentRevision || p.payment.currency !== 'CNY' || !p.payment.eligible)) bad();
  if (plan.operation === 'apply' && (p.journey?.id !== plan.journeyId || p.payment?.id !== plan.paymentId || p.beforeAllocatedCents !== 0)) bad();
  if (plan.operation === 'update' && (!expected || p.journey?.id !== expected.journeyId || p.payment?.id !== expected.paymentId)) bad();
  return p;
}
export function readReceipt(v: unknown, requestId: string): Receipt {
  const r = obj(v), receipt: Receipt = { requestId: id(r.requestId, 32), operation: one(r.operation, ['apply', 'update', 'revoke']), allocationId: id(r.allocationId, 32), revision: integer(r.revision, 1), completedAt: timestamp(r.completedAt) };
  if (receipt.requestId !== requestId) bad(); return receipt;
}
export function readOperation(v: unknown, intent: Intent): Receipt | null {
  const r = version(v); if (r.requestId !== intent.requestId) bad();
  if (!flag(r.found)) { if (r.receipt !== null) bad(); return null; }
  return readReceipt(r.receipt, intent.requestId);
}
export function readConfirmation(v: unknown, intent: Intent): Receipt { const r = version(v); flag(r.replayed); return readReceipt(r.receipt, intent.requestId); }
export function readOriginalPayment(v: unknown, expected: string): OriginalPayment {
  const r = obj(obj(v).transaction); if (r.id !== expected || r.kind !== 'payments') bad();
  return { id: paymentId(r.id), revision: integer(r.revision, 1), date: text(r.date, 10), title: text(r.title), amountCents: integer(r.amountCents), currency: currency(r.currency), flow: text(r.flow, 40), category: text(r.category, 100), source: text(r.source, 60) };
}

// Only the POST's parsed, contract-specific rejection proves non-acceptance.
// A pre/post identity request or malformed response must not discard an intent.
export class JourneyConfirmRejected extends Error { constructor(public cause: ApiError) { super(cause.message); } }
export async function checkedConfirm<T>(guard: (action: (csrf: string) => Promise<T>) => Promise<T>, write: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => { try { return await write(csrf); } catch (e) {
    if (e instanceof ApiError && [400, 404, 409].includes(e.status) && /^journey_finance_/.test(e.code)) throw new JourneyConfirmRejected(e);
    throw e;
  } });
}
export class JourneyFinanceFence extends PlaceFence {}
export const journeyRequest = (path: string, signal: AbortSignal, body?: unknown, csrf = '') => request<unknown>(path, { signal, ...(body === undefined ? {} : { method: 'POST', body: JSON.stringify(body) }) }, csrf);
export function newIntent(preview: Preview): Intent { return Object.freeze({ requestId: crypto.randomUUID().replaceAll('-', ''), previewToken: preview.previewToken }); }

const STORAGE_KEY = 'family.journey-finance.pending.v1';
export type PendingStore = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export async function identityDigest(identity: string): Promise<string> { return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(identity)))].map(x => x.toString(16).padStart(2, '0')).join(''); }
export function restoreIntent(store: PendingStore, digest: string): Intent | null {
  const raw = store.getItem(STORAGE_KEY); if (!raw) return null;
  try { const v = obj(JSON.parse(raw)); if (v.identity !== digest || v.version !== 1 || Object.keys(v).sort().join(',') !== 'identity,previewToken,requestId,version') throw new Error();
    return Object.freeze({ requestId: id(v.requestId, 32), previewToken: text(v.previewToken, 12000) || bad() });
  } catch { store.removeItem(STORAGE_KEY); return null; }
}
export function persistIntent(store: PendingStore, digest: string, intent: Intent | null) {
  if (!intent) { store.removeItem(STORAGE_KEY); return; }
  if (!/^[a-f0-9]{64}$/.test(digest)) bad();
  store.setItem(STORAGE_KEY, JSON.stringify({ version: 1, identity: digest, requestId: id(intent.requestId, 32), previewToken: text(intent.previewToken, 12000) || bad() }));
}
