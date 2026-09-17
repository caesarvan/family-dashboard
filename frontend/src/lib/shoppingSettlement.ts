import type { Member } from './types';

export const SETTLEMENT_PATH = '/finance-hub/shopping-settlements';
export type SettlementSession = { user: Member | null; csrf?: string | null };
export type SettlementPayment = { id: string; revision: number; title: string; date: string; currency: string; amountCents: number;
  refundedCents: number; netCents: number; reservedCents: number; availableCents: number; eligible: boolean; reasonCode: string | null };
export type SettlementShopping = { id: string; revision: number; title: string; actual: number | null; done: boolean };
export type SettlementLink = { id: string; revision: number; shoppingId: string; paymentId: string; amountCents: number;
  status: 'active' | 'revoked'; state: 'current' | 'needs_review' | 'revoked'; reviewReasons: string[];
  appliedShoppingRevision: number; createdAt: string; updatedAt: string };
export type SettlementContext = { version: 1; transaction: { id: string; revision: number; kind: 'payments' | 'orders'; flow: string; currency: string } | null;
  payments: SettlementPayment[]; shopping: SettlementShopping[]; links: SettlementLink[]; warnings: string[];
  pageInfo: { page: number; pageSize: 40; paymentsMore: boolean; shoppingMore: boolean; linksMore: boolean } };
export type SettlementQuery = { shoppingId?: string; transactionId?: string; linkId?: string; q?: string; page?: number };
export type SettlementDraft = { operation: 'apply' | 'update' | 'revoke'; shoppingId: string; paymentId: string; linkId: string;
  amount: string; done: boolean; mode: 'detach_keep_current' | 'restore_if_unchanged'; dirty: boolean };
export type SettlementPlan = { operation: 'apply'; paymentId: string; shoppingId: string; shoppingRevision: number; amountCents: number; done: boolean }
  | { operation: 'update'; linkId: string; revision: number; shoppingRevision: number; amountCents: number; done: boolean }
  | { operation: 'revoke'; linkId: string; revision: number; shoppingRevision: number | null; mode: 'detach_keep_current' | 'restore_if_unchanged' };
type Projection = { shoppingId: string; actual: number | null; done: boolean };
export type SettlementPreview = { operation: SettlementPlan['operation']; linkId: string | null; before: (Projection & { revision: number }) | null; after: Projection | null;
  payment: { id: string; currency: string; netCents: number; reservedOtherCents: number; availableCents: number } | null;
  warnings: string[]; previewToken: string; expiresInSeconds: 600 };
export type SettlementIntent = Readonly<{ plan: Readonly<SettlementPlan>; preview: SettlementPreview; shoppingId: string; paymentId: string;
  shoppingTitle: string; paymentTitle: string; expiresAt: number }>;
export type SettlementReceipt = { operation: SettlementPlan['operation']; link: SettlementLink;
  shopping: Omit<SettlementShopping, 'title'> | null; changedFields: ('actual' | 'done')[]; replayed: boolean };
export type SettlementReview = { intent: SettlementIntent; identity: string; epoch: number };
export class SettlementError extends Error { constructor(message: string, public status = 0) { super(message); } }
export class SettlementDiscarded extends Error {}
export class SettlementRejected extends SettlementError {}
const bad = (): never => { throw new SettlementError('核对资料格式不正确，请重新读取。'); };
const obj = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const str = (v: unknown, max = 2000): string => typeof v === 'string' && [...v].length <= max && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v) ? v : bad();
export const settlementId = (v: unknown): string => typeof v === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(v) ? v : bad();
const num = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max ? Number(v) : bad();
const cents = (v: unknown) => num(v, 0, 100_000_000_000);
const bool = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const one = <T extends string>(v: unknown, values: readonly T[]): T => values.includes(v as T) ? v as T : bad();
const list = <T,>(v: unknown, reader: (v: unknown) => T, max = 50): T[] => Array.isArray(v) && v.length <= max ? v.map(reader) : bad();
const unique = <T extends { id: string }>(v: T[]): T[] => new Set(v.map(r => r.id)).size === v.length ? v : bad();
const currency = (v: unknown): string => typeof v === 'string' && /^[A-Z]{3}$/.test(v) ? v : bad();
const actual = (v: unknown) => v === null ? null : cents(v);
const warnings = (v: unknown) => list(v, x => str(x), 30);
const reviewReasons = ['source_missing', 'source_changed', 'source_ineligible', 'shopping_missing', 'shopping_changed'] as const;
const reasonCodes = ['not_payment', 'not_expense', 'duplicate', 'unsupported_currency'] as const;
export function readSettlementLink(raw: unknown): SettlementLink {
  const v = obj(raw), status = one(v.status, ['active', 'revoked']), state = one(v.state, ['current', 'needs_review', 'revoked']);
  const reasons = list(v.reviewReasons, x => one(x, reviewReasons), 5);
  if (new Set(reasons).size !== reasons.length || (status === 'revoked' ? state !== 'revoked' || reasons.length : state !== (reasons.length ? 'needs_review' : 'current'))) return bad();
  return { id: settlementId(v.id), revision: num(v.revision, 1), shoppingId: settlementId(v.shoppingId), paymentId: settlementId(v.paymentId), amountCents: cents(v.amountCents),
    status, state, reviewReasons: reasons, appliedShoppingRevision: num(v.appliedShoppingRevision, 1), createdAt: str(v.createdAt, 100), updatedAt: str(v.updatedAt, 100) };
}
function readShopping(raw: unknown): SettlementShopping {
  const v = obj(raw); return { id: settlementId(v.id), revision: num(v.revision, 1), title: str(v.title), actual: actual(v.actual), done: bool(v.done) };
}
export function readSettlementContext(raw: unknown, query: SettlementQuery = {}): SettlementContext {
  const v = obj(raw), p = obj(v.pageInfo); if (v.version !== 1 || p.pageSize !== 40 || p.page !== (query.page || 0)) return bad();
  const payments = unique(list(v.payments, rawPay => {
    const r = obj(rawPay), reason = r.reasonCode === null ? null : one(r.reasonCode, reasonCodes);
    const value = { id: settlementId(r.id), revision: num(r.revision, 1), title: str(r.title), date: str(r.date, 10), currency: currency(r.currency),
      amountCents: num(r.amountCents, 0, 100_000_000_000_000), refundedCents: num(r.refundedCents), netCents: num(r.netCents, -Number.MAX_SAFE_INTEGER),
      reservedCents: num(r.reservedCents), availableCents: num(r.availableCents), eligible: bool(r.eligible), reasonCode: reason };
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value.date) || value.eligible !== (reason === null) || value.eligible && value.currency !== 'CNY') return bad();
    return value;
  }));
  const shopping = unique(list(v.shopping, readShopping)), links = unique(list(v.links, readSettlementLink));
  const t = v.transaction === null ? null : obj(v.transaction);
  const transaction = t && { id: settlementId(t.id), revision: num(t.revision, 1), kind: one(t.kind, ['payments', 'orders']),
    flow: one(t.flow, ['expense', 'income', 'refund', 'transfer', 'unknown', 'excluded']), currency: currency(t.currency) };
  if (query.transactionId && transaction?.id !== query.transactionId || query.shoppingId && !shopping.some(s => s.id === query.shoppingId)
    || query.linkId && !links.some(l => l.id === query.linkId)) return bad();
  return { version: 1, transaction, payments, shopping, links, warnings: warnings(v.warnings), pageInfo: { page: num(p.page, 0, 999999999), pageSize: 40,
    paymentsMore: bool(p.paymentsMore), shoppingMore: bool(p.shoppingMore), linksMore: bool(p.linksMore) } };
}
export function settlementQuery(query: SettlementQuery): string {
  const params = new URLSearchParams();
  for (const key of ['transactionId', 'shoppingId', 'linkId'] as const) if (query[key]) params.set(key, settlementId(query[key]));
  if (query.q) { const q = str(query.q, 80); if (/[\x00-\x1f\x7f]/.test(q)) return bad(); params.set('q', q); }
  if (query.page !== undefined) params.set('page', String(num(query.page, 0, 999999999)));
  return SETTLEMENT_PATH + '/context' + (params.size ? '?' + params.toString() : '');
}
// Link context can outlive either linked object. Do not add stale object focus
// to this read; the server can return needs_review and an explicit detach plan.
export function settlementReadQuery(focus: SettlementQuery, draft: Pick<SettlementDraft, 'shoppingId' | 'paymentId' | 'linkId'>,
  options: { q: string; page: number; receiptLinkId?: string; unscoped?: boolean }): SettlementQuery {
  if (options.unscoped) return { q: '', page: 0 };
  const linkId = options.receiptLinkId || draft.linkId;
  if (linkId) return { linkId, q: options.q, page: options.page };
  return { ...focus, q: options.q, page: options.page,
    ...(draft.shoppingId ? { shoppingId: draft.shoppingId } : {}),
    ...(!focus.transactionId && draft.paymentId ? { transactionId: draft.paymentId } : {}) };
}
export function settlementPlan(context: SettlementContext, draft: SettlementDraft, amountCents: number): SettlementPlan {
  const shop = context.shopping.find(r => r.id === draft.shoppingId), link = context.links.find(r => r.id === draft.linkId);
  if (draft.operation !== 'apply' && (!link || link.status !== 'active' || link.shoppingId !== draft.shoppingId || link.paymentId !== draft.paymentId)) return bad();
  if (draft.operation === 'revoke') return { operation: 'revoke', linkId: link!.id, revision: link!.revision,
    shoppingRevision: shop?.revision ?? null, mode: one(draft.mode, ['detach_keep_current', 'restore_if_unchanged']) };
  const pay = context.payments.find(r => r.id === draft.paymentId);
  if (!shop || !pay?.eligible || pay.currency !== 'CNY') throw new SettlementError('请选择采购和本人有效的人民币消费付款。');
  if (draft.operation === 'apply' && context.links.some(r => r.status === 'active' && r.shoppingId === shop.id)) throw new SettlementError('此采购已有本人关联，请更新或解除原关联。');
  const common = { shoppingRevision: shop.revision, amountCents: cents(amountCents), done: bool(draft.done) };
  return draft.operation === 'apply' ? { operation: 'apply', paymentId: pay.id, shoppingId: shop.id, ...common }
    : { operation: 'update', linkId: link!.id, revision: link!.revision, ...common };
}
function projection(raw: unknown): Projection | null {
  if (raw === null) return null; const v = obj(raw); return { shoppingId: settlementId(v.shoppingId), actual: actual(v.actual), done: bool(v.done) };
}
export function readSettlementPreview(raw: unknown, plan: SettlementPlan, context: SettlementContext, now = performance.now()): SettlementIntent {
  const v = obj(raw), link = plan.operation === 'apply' ? null : context.links.find(r => r.id === plan.linkId);
  const sid = plan.operation === 'apply' ? plan.shoppingId : link?.shoppingId, pid = plan.operation === 'apply' ? plan.paymentId : link?.paymentId;
  if (!sid || !pid || v.operation !== plan.operation || v.linkId !== (link?.id ?? null) || v.expiresInSeconds !== 600) return bad();
  const beforeValue = projection(v.before), before = beforeValue && { ...beforeValue, revision: num(obj(v.before).revision, 1) }, after = projection(v.after);
  const shop = context.shopping.find(r => r.id === sid), pay = context.payments.find(r => r.id === pid), sharing = obj(v.sharing);
  if (before?.shoppingId !== shop?.id || (before?.revision ?? null) !== plan.shoppingRevision || before?.actual !== shop?.actual || before?.done !== shop?.done
    || JSON.stringify(sharing.fields) !== '["actual","done"]' || sharing.ledgerUnchanged !== true) return bad();
  if (after && after.shoppingId !== sid || Boolean(after) !== Boolean(before)) return bad();
  if (plan.operation !== 'revoke' && (!after || after.actual !== plan.amountCents || after.done !== plan.done)) return bad();
  if (plan.operation === 'revoke' && plan.mode === 'detach_keep_current' && (after?.actual !== before?.actual || after?.done !== before?.done)) return bad();
  const p = v.payment === null ? null : obj(v.payment), payment = p && { id: settlementId(p.id), currency: currency(p.currency),
    netCents: num(p.netCents, -Number.MAX_SAFE_INTEGER), reservedOtherCents: num(p.reservedOtherCents), availableCents: num(p.availableCents) };
  if (payment && payment.id !== pid || plan.operation !== 'revoke' && (!payment || payment.currency !== 'CNY' || plan.amountCents > payment.availableCents)) return bad();
  const token = str(v.previewToken, 12000); if (token.length < 20) return bad();
  const preview: SettlementPreview = { operation: plan.operation, linkId: link?.id ?? null, before, after, payment, warnings: warnings(v.warnings), previewToken: token, expiresInSeconds: 600 };
  return Object.freeze({ plan: Object.freeze({ ...plan }), preview, shoppingId: sid, paymentId: pid, shoppingTitle: shop?.title || '原采购', paymentTitle: pay?.title || '原付款', expiresAt: now + 600000 });
}
export function readSettlementReceipt(raw: unknown, intent: SettlementIntent): SettlementReceipt {
  const v = obj(raw), link = readSettlementLink(v.link), p = v.shopping === null ? null : obj(v.shopping), after = intent.preview.after;
  const shopping = p && { id: settlementId(p.id), revision: num(p.revision, 1), actual: actual(p.actual), done: bool(p.done) };
  if (v.operation !== intent.plan.operation || link.shoppingId !== intent.shoppingId || link.paymentId !== intent.paymentId
    || intent.plan.operation !== 'apply' && link.id !== intent.plan.linkId || link.status !== (intent.plan.operation === 'revoke' ? 'revoked' : 'active')
    || Boolean(shopping) !== Boolean(after) || shopping && (shopping.id !== after!.shoppingId || shopping.actual !== after!.actual || shopping.done !== after!.done)) return bad();
  const changedFields = list(v.changedFields, x => one(x, ['actual', 'done'] as const), 2);
  const expected = after ? (['actual', 'done'] as const).filter(key => after[key] !== intent.preview.before?.[key]) : [];
  if (new Set(changedFields).size !== changedFields.length || JSON.stringify(changedFields) !== JSON.stringify(expected)
    || link.revision !== (intent.plan.operation === 'apply' ? 1 : intent.plan.revision + 1)
    || intent.plan.operation !== 'revoke' && link.amountCents !== intent.plan.amountCents
    || shopping && shopping.revision !== intent.preview.before!.revision + (expected.length ? 1 : 0)) return bad();
  return { operation: intent.plan.operation, link, shopping, changedFields, replayed: bool(v.replayed) };
}
export const canEndSettlementReview = (review: SettlementReview | null, intent: SettlementIntent | null, identity: string, epoch: number) =>
  !!review && !!intent && review.intent === intent && review.identity === identity && review.epoch === epoch;
export const settlementSignature = (s: SettlementSession) => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id, s.user?.auth_version, s.csrf]);
export class SettlementFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<SettlementSession>, action: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (s: SettlementSession) => {
      if (epoch !== this.epoch || !current()) throw new SettlementDiscarded();
      if (!s || s.user?.role !== 'member' || !s.user.householdId || !s.user.id || !Number.isSafeInteger(s.user.auth_version)
        || Number(s.user.auth_version) < 1 || typeof s.csrf !== 'string' || !s.csrf || settlementSignature(s) !== this.expected) throw new SettlementDiscarded('identity');
      return s.csrf;
    };
    const csrf = check(await me()); let value!: T, failure: unknown, failed = false;
    try { value = await action(csrf); } catch (e) { failed = true; failure = e; }
    check(await me()); if (failed) throw failure; return value;
  }
}
export async function checkedSettlementWrite<T>(guard: (action: (csrf: string) => Promise<T>) => Promise<T>, action: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => { try { return await action(csrf); } catch (e) {
    if (e instanceof SettlementError && [400, 403, 404, 409, 415, 422, 429].includes(e.status)) throw new SettlementRejected(e.message, e.status);
    throw e;
  } });
}
export async function settlementRequest(path: string, signal: AbortSignal, options: { payload?: unknown; csrf?: string } = {}): Promise<unknown> {
  const writing = options.payload !== undefined;
  if (writing) {
    if (![SETTLEMENT_PATH + '/preview', SETTLEMENT_PATH + '/confirm'].includes(path) || !options.csrf) return bad();
    const p = obj(options.payload);
    if (path.endsWith('/confirm')) { if (Object.keys(p).join() !== 'previewToken' || str(p.previewToken, 12000).length < 20) return bad(); }
    else {
      const fields = p.operation === 'apply' ? 'amountCents|done|operation|paymentId|shoppingId|shoppingRevision' : p.operation === 'update'
        ? 'amountCents|done|linkId|operation|revision|shoppingRevision' : p.operation === 'revoke' ? 'linkId|mode|operation|revision|shoppingRevision' : '';
      if (!fields || Object.keys(p).sort().join('|') !== fields) return bad();
      if (p.operation === 'apply') { settlementId(p.paymentId); settlementId(p.shoppingId); } else { settlementId(p.linkId); num(p.revision, 1); }
      if (p.operation === 'revoke') { one(p.mode, ['detach_keep_current', 'restore_if_unchanged']); if (p.shoppingRevision !== null) num(p.shoppingRevision, 1); }
      else { num(p.shoppingRevision, 1); cents(p.amountCents); bool(p.done); }
    }
  } else {
    if (options.csrf !== undefined) return bad();
    if (path !== '/me') {
      const [base, query = ''] = path.split('?'); if (base !== SETTLEMENT_PATH + '/context' || path.split('?').length > 2) return bad();
      const params = new URLSearchParams(query), seen = new Set<string>();
      for (const [key, value] of params) { if (seen.has(key)) return bad(); seen.add(key);
        if (['shoppingId', 'transactionId', 'linkId'].includes(key)) settlementId(value);
        else if (key === 'page') { if (!/^(0|[1-9]\d{0,8})$/.test(value)) return bad(); }
        else if (key === 'q') { str(value, 80); if (/[\x00-\x1f\x7f]/.test(value)) return bad(); } else return bad(); }
    }
  }
  const controller = new AbortController(), end = performance.now() + 15000, abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new SettlementDiscarded(); if (controller.signal.aborted || performance.now() >= end) throw new SettlementError('连接中断，请重新读取核对资料。'); };
  check(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15000);
  try {
    const r = await fetch('/api' + path, { method: writing ? 'POST' : 'GET', mode: 'same-origin', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
      headers: { Accept: 'application/json', ...(writing ? { 'Content-Type': 'application/json', 'X-CSRF-Token': options.csrf! } : {}) }, ...(writing ? { body: JSON.stringify(options.payload) } : {}) });
    check(); if (r.redirected) return bad();
    if (!r.ok) throw new SettlementError(r.status === 409 ? '付款、分配或采购已变化，请重新读取后再预览。' : [401, 403].includes(r.status) ? '登录或访问权限已变化，请重新核对。'
      : [404, 410].includes(r.status) ? '原记录暂时无法读取，旧资料已隐藏。' : r.status === 400 ? '预览已失效或当前分配不适用，请核对金额、来源与采购后重新预览。' : '暂时无法完成核对，请重新读取。', r.status);
    if (!/^application\/json(?:\s*;|$)/i.test(r.headers.get('Content-Type') || '') || Number(r.headers.get('Content-Length') || 0) > 512000 || !r.body) return bad();
    const reader = r.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
    try { while (true) { const part = await reader.read(); check(); if (part.done) break; size += part.value.byteLength;
      if (size > 512000) { await reader.cancel(); return bad(); } chunks.push(part.value); } } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const value: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); check(); return value;
  } catch (e) { check(); if (e instanceof SettlementError || e instanceof SettlementDiscarded) throw e; throw new SettlementError('核对资料暂时不可用，请重新读取。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
