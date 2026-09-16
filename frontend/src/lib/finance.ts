export type Flow = 'expense' | 'income' | 'refund' | 'transfer' | 'unknown' | 'excluded';
export type RelationKind = 'order_payment' | 'refund_payment' | 'duplicate';
export type Transaction = {
  id: string; revision: number; date: string; amountCents: number; currency: string; title: string; category: string;
  source: string; kind: 'payments' | 'orders'; flow: Flow; visibility: 'private' | 'shared';
  externalId: string; status: string; merchantOrderId?: string; paymentId?: string; originalTransactionId?: string;
  importedAt: string; checkedAt: string | null;
  reconciliation?: { duplicateOf: string | null; relationCount: number; allocatedCents: number; unallocatedCents: number; refundedCents: number; remainingAfterRefundCents?: number };
  orderItems?: { title: string; variant: string; quantityText: string; listedAmountText: string; sourceLine: number; productUrl: string }[];
  provenance?: { status: 'unknown' } | { status: 'recorded'; batchId: string; source: string; kind: string; fileName: string | null; format: 'csv' | 'xlsx'; sheet: string | null; lineStart: number; lineEnd: number; lineKind: 'csv_lines' | 'worksheet_rows'; importedAt: string };
};
export type Totals = { currency: string; count: number; expenseCents: number; refundCents: number; netSpendCents: number; incomeCents?: number; transferCents?: number; unknownCents?: number; excludedCents?: number; orderCents?: number; duplicateCents?: number; duplicateCount?: number; recordedSurplusCents?: number; categories?: Record<string, number> };
export type Budget = { month: string; currency: string; category: string; amountCents: number; revision: number; spentCents: number; remainingCents: number };
export type Overview = { month: string; totalRecordCount: number; transactionCount: number; availableMonths: { month: string; recordCount: number }[]; totals: Totals[]; budgets: Budget[]; coverage: string; imports: { id: string; source: string; kind: string; importedCount: number; createdAt: string }[] };
export type Ledger = { month: string; q: string; page: number; pageSize: number; transactionCount: number; filteredCount: number; totalPages: number; hasNext: boolean; hasPrevious: boolean; snapshot: string; transactions: Transaction[] };
export type Relation = { id: string; kind: RelationKind; leftId: string; rightId: string; amountCents: number; status: 'active' | 'revoked'; revision: number; createdAt: string; updatedAt: string; left?: Transaction | null; right?: Transaction | null };
export type Candidate = { kind: RelationKind; left: Transaction; right: Transaction; maxAmountCents: number; suggestedAmountCents: number; reasons: string[]; uncertainty: string[] };
export type Reconciliation = { transaction: Transaction; candidates: Candidate[]; relations: Relation[]; candidateCount: number; truncated: boolean; note: string };
export type RelationPreview = { kind: RelationKind; left: Transaction; right: Transaction; leftId: string; rightId: string; leftRevision: number; rightRevision: number; amountCents: number; previewToken: string; effect: string; reasons: string[]; uncertainty: string[] };
export const flowLabels: Record<Flow, string> = { expense: '消费', income: '收入', refund: '退款', transfer: '转账', unknown: '待核对', excluded: '排除' };
export const relationLabels: Record<RelationKind, string> = { order_payment: '订单与付款', refund_payment: '退款与付款', duplicate: '重复记录' };
const sourceLabels: Record<string, string> = { generic: '整理表', alipay: '支付宝', wechat: '微信', taobao: '淘宝', pinduoduo: '拼多多' };
export const sourceLabel = (source: string) => sourceLabels[source] || source;
const bad = (): never => { throw new Error('财务数据暂时无法核对，请刷新后查看。'); };
const object = (v: unknown): Record<string, any> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, any> : bad();
const str = (v: unknown, max = 2000): string => typeof v === 'string' && v.length <= max ? v : bad();
const integer = (v: unknown, min = 0): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min ? v : bad();
const amount = (v: unknown): number => integer(v, -Number.MAX_SAFE_INTEGER);
const flag = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const array = (v: unknown, max = 20000): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
const currency = (v: unknown): string => typeof v === 'string' && /^[A-Z]{3}$/.test(v) ? v : bad();
export const financeId = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{24}$/.test(v);
const id = (v: unknown) => financeId(v) ? v : bad();
export const validFinanceMonth = (v: unknown): v is string => typeof v === 'string' && /^(?!0000)\d{4}-(0[1-9]|1[0-2])$/.test(v);
const month = (v: unknown) => validFinanceMonth(v) ? v : bad();
const flow = (v: unknown): Flow => typeof v === 'string' && Object.hasOwn(flowLabels, v) ? v as Flow : bad();
const relationKind = (v: unknown): RelationKind => typeof v === 'string' && Object.hasOwn(relationLabels, v) ? v as RelationKind : bad();
const strings = (v: unknown) => array(v, 50).map(x => str(x));

// The API supplies integer hundredths. Formatting does no floating point
// arithmetic, rounding, conversion, or cross-currency aggregation.
export function centsToDecimal(value: number): string {
  amount(value); const n = BigInt(value), abs = n < 0n ? -n : n;
  return `${n < 0n ? '-' : ''}${abs / 100n}.${String(abs % 100n).padStart(2, '0')}`;
}
export function formatFinanceAmount(value: number, code: string): string {
  currency(code); const [whole, fraction] = centsToDecimal(value).split('.');
  return `${code} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction}`;
}
export function decimalInput(value: string, positive = false, maximum = 1000000000000n): string {
  const raw = value.trim();
  if (!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(raw)) throw new Error('请填写非负金额，最多两位小数，不使用千分位或货币符号。');
  const [whole, fraction = ''] = raw.split('.'), scaled = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  if (scaled > maximum * 100n || positive && scaled === 0n) throw new Error('金额超出允许范围。');
  return `${whole}.${fraction.padEnd(2, '0')}`;
}
export function readTransaction(value: unknown): Transaction {
  const v = object(value);
  const result: Transaction = { id: id(v.id), revision: integer(v.revision, 1), date: str(v.date, 10), amountCents: integer(v.amountCents), currency: currency(v.currency), title: str(v.title, 200), category: str(v.category, 60), source: str(v.source, 50), kind: v.kind === 'payments' || v.kind === 'orders' ? v.kind : bad(), flow: flow(v.flow), visibility: v.visibility === 'private' || v.visibility === 'shared' ? v.visibility : bad(), externalId: str(v.externalId), status: str(v.status), importedAt: str(v.importedAt, 100), checkedAt: v.checkedAt === null ? null : str(v.checkedAt, 100) };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result.date)) bad();
  for (const key of ['merchantOrderId', 'paymentId', 'originalTransactionId'] as const) if (v[key] !== undefined) result[key] = str(v[key]);
  if (v.reconciliation) { const r = object(v.reconciliation); result.reconciliation = { duplicateOf: r.duplicateOf === null ? null : id(r.duplicateOf), relationCount: integer(r.relationCount), allocatedCents: integer(r.allocatedCents), unallocatedCents: integer(r.unallocatedCents), refundedCents: integer(r.refundedCents) }; if (r.remainingAfterRefundCents !== undefined) result.reconciliation.remainingAfterRefundCents = integer(r.remainingAfterRefundCents); }
  if (v.orderItems) result.orderItems = array(v.orderItems, 1000).map(x => { const r = object(x); return { title: str(r.title, 500), variant: str(r.variant, 500), quantityText: str(r.quantityText, 100), listedAmountText: str(r.listedAmountText, 100), sourceLine: integer(r.sourceLine, 1), productUrl: str(r.productUrl, 2000) }; });
  if (v.provenance !== undefined) {
    const p = object(v.provenance);
    if (p.status === 'unknown') result.provenance = { status: 'unknown' };
    else if (p.status === 'recorded') {
      const source = str(p.source, 50), kind = str(p.kind, 20), lineStart = integer(p.lineStart, 1), lineEnd = integer(p.lineEnd, 1);
      if (source !== result.source || kind !== result.kind || lineEnd < lineStart) bad();
      result.provenance = { status: 'recorded', batchId: id(p.batchId), source, kind, fileName: p.fileName === null ? null : str(p.fileName, 255), format: p.format === 'csv' || p.format === 'xlsx' ? p.format : bad(), sheet: p.sheet === null ? null : str(p.sheet, 200), lineStart, lineEnd, lineKind: p.lineKind === 'csv_lines' || p.lineKind === 'worksheet_rows' ? p.lineKind : bad(), importedAt: str(p.importedAt, 100) };
    } else bad();
  }
  return result;
}
export function readTotals(value: unknown): Totals[] {
  return array(value, 200).map(x => { const v = object(x), result: Totals = { currency: currency(v.currency), count: integer(v.count), expenseCents: integer(v.expenseCents), refundCents: integer(v.refundCents), netSpendCents: amount(v.netSpendCents) };
    for (const key of ['incomeCents', 'transferCents', 'unknownCents', 'excludedCents', 'orderCents', 'duplicateCents', 'duplicateCount', 'recordedSurplusCents'] as const) if (v[key] !== undefined) result[key] = amount(v[key]);
    if (v.categories !== undefined) result.categories = Object.fromEntries(Object.entries(object(v.categories)).map(([k, n]) => [k, amount(n)])); return result; });
}
export function readOverview(value: unknown): Overview {
  const v = object(value); return { month: month(v.month), totalRecordCount: integer(v.totalRecordCount), transactionCount: integer(v.transactionCount), availableMonths: array(v.availableMonths).map(x => { const r = object(x); return { month: month(r.month), recordCount: integer(r.recordCount) }; }), totals: readTotals(v.totals), coverage: str(v.coverage),
    budgets: array(v.budgets, 1200).map(x => { const r = object(x); return { month: month(r.month), currency: currency(r.currency), category: str(r.category, 60), amountCents: integer(r.amountCents), revision: integer(r.revision, 1), spentCents: amount(r.spentCents), remainingCents: amount(r.remainingCents) }; }),
    imports: array(v.imports, 12).map(x => { const r = object(x); return { id: id(r.id), source: str(r.source, 50), kind: str(r.kind, 20), importedCount: integer(r.importedCount), createdAt: str(r.createdAt, 100) }; }) };
}
export function readLedger(value: unknown): Ledger {
  const v = object(value); if (typeof v.snapshot !== 'string' || !/^[a-f0-9]{64}$/.test(v.snapshot)) bad();
  const result = { month: month(v.month), q: str(v.q, 160), page: integer(v.page, 1), pageSize: integer(v.pageSize, 1), transactionCount: integer(v.transactionCount), filteredCount: integer(v.filteredCount), totalPages: integer(v.totalPages, 1), hasNext: flag(v.hasNext), hasPrevious: flag(v.hasPrevious), snapshot: v.snapshot, transactions: array(v.transactions, 100).map(readTransaction) };
  if (result.page > result.totalPages || result.pageSize > 100 || result.transactions.length > result.pageSize || new Set(result.transactions.map(t => t.id)).size !== result.transactions.length) bad(); return result;
}
export function ledgerPath(value: { month: string; q: string; page: number; snapshot?: string }) {
  month(value.month); integer(value.page, 1); str(value.q, 160);
  const p = new URLSearchParams({ month: value.month, q: value.q, page: String(value.page), pageSize: '25' });
  if (value.snapshot) { if (!/^[a-f0-9]{64}$/.test(value.snapshot)) bad(); p.set('snapshot', value.snapshot); } return '/finance-hub/transactions?' + p;
}
function pair(value: unknown) { const v = object(value); return { kind: relationKind(v.kind), left: readTransaction(v.left), right: readTransaction(v.right), reasons: strings(v.reasons), uncertainty: strings(v.uncertainty) }; }
export function readRelation(value: unknown): Relation {
  const v = object(value), r: Relation = { id: id(v.id), kind: relationKind(v.kind), leftId: id(v.leftId), rightId: id(v.rightId), amountCents: integer(v.amountCents, 1), status: v.status === 'active' || v.status === 'revoked' ? v.status : bad(), revision: integer(v.revision, 1), createdAt: str(v.createdAt, 100), updatedAt: str(v.updatedAt, 100) };
  if (v.left) r.left = readTransaction(v.left); if (v.right) r.right = readTransaction(v.right); return r;
}
export function readReconciliation(value: unknown): Reconciliation {
  const v = object(value); return { transaction: readTransaction(v.transaction), candidates: array(v.candidates, 40).map(x => { const r = object(x); return { ...pair(x), maxAmountCents: integer(r.maxAmountCents, 1), suggestedAmountCents: integer(r.suggestedAmountCents, 1) }; }), relations: array(v.relations, 100).map(readRelation), candidateCount: integer(v.candidateCount), truncated: flag(v.truncated), note: str(v.note) };
}
export function readRelationPreview(value: unknown): RelationPreview {
  const v = object(value), r = { ...pair(value), leftId: id(v.leftId), rightId: id(v.rightId), leftRevision: integer(v.leftRevision, 1), rightRevision: integer(v.rightRevision, 1), amountCents: integer(v.amountCents, 1), previewToken: str(v.previewToken, 3000), effect: str(v.effect) };
  if (!r.previewToken || r.left.id !== r.leftId || r.right.id !== r.rightId || r.left.revision !== r.leftRevision || r.right.revision !== r.rightRevision || r.left.currency !== r.right.currency) bad(); return r;
}
export function transactionPatch(row: Transaction, category: string, nextFlow: Flow, shared: boolean) {
  if (!category.trim() || category.trim().length > 60) throw new Error('分类需要 1 至 60 个字符。');
  flow(nextFlow); if (shared && (row.kind !== 'payments' || !['expense', 'refund'].includes(nextFlow))) throw new Error('只有付款中的消费和退款可以纳入共同消费汇总。');
  return { revision: row.revision, category: category.trim(), flow: nextFlow, visibility: shared ? 'shared' : 'private' };
}
export function budgetPayload(draft: { month: string; currency: string; category: string; amount: string; revision: number }) {
  if (!validFinanceMonth(draft.month)) throw new Error('请填写有效月份，例如 2026-09。');
  const code = draft.currency.trim().toUpperCase(); if (!/^[A-Z]{3}$/.test(code)) throw new Error('币种请使用三位代码，例如 CNY。');
  const category = draft.category.trim(); if (!category || category.length > 60) throw new Error('分类需要 1 至 60 个字符；总预算使用“全部”。');
  return { month: draft.month, currency: code, category, amount: decimalInput(draft.amount), revision: integer(draft.revision) };
}
export const sharedFinanceFields = ['wallet', 'livingBudget', 'livingSpent', 'travelSaved', 'longterm', 'reserveTarget'] as const;
export const sharedFinanceLabels = { wallet: '荷包余额', livingBudget: '日常预算', livingSpent: '本月日常支出', travelSaved: '旅行准备金', longterm: '长期共同储蓄', reserveTarget: '周转目标' };
export type SharedSnapshot = Record<typeof sharedFinanceFields[number], number> & { contributionPercent: number; note: string; revision: number; confirmedAt?: string };
export function readSharedSnapshot(value: unknown): SharedSnapshot {
  const v = object(value), r: Record<string, any> = { revision: integer(v.revision, 1), contributionPercent: v.contributionPercent, note: str(v.note ?? '', 500) };
  for (const k of [...sharedFinanceFields, 'contributionPercent'] as const) { if (typeof v[k] !== 'number' || !Number.isFinite(v[k]) || v[k] < 0) bad(); decimalInput(String(v[k]), false, k === 'contributionPercent' ? 100n : 100000000000n); r[k] = v[k]; }
  if (v.confirmedAt) r.confirmedAt = str(v.confirmedAt, 100); return r as SharedSnapshot;
}
export function sharedSnapshotPayload(base: SharedSnapshot, inputs: Record<string, string>) {
  const values = Object.fromEntries(sharedFinanceFields.map(k => [k, decimalInput(inputs[k], false, 100000000000n)]));
  return { ...values, contributionPercent: decimalInput(inputs.contributionPercent, false, 100n), note: str(inputs.note, 500), revision: base.revision };
}
