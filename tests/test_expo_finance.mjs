import assert from 'node:assert/strict';
import { test } from 'node:test';
import { centsToDecimal, formatFinanceAmount, decimalInput, readTransaction, readLedger, readOverview, readReconciliation, readRelationPreview, readSharedSnapshot, sharedSnapshotPayload, transactionPatch, budgetPayload, ledgerPath, readTotals } from '../frontend/src/lib/finance.ts';

const first = 'a'.repeat(24), second = 'b'.repeat(24), snapshot = 'c'.repeat(64);
const transaction = (patch = {}) => ({ id: first, revision: 1, date: '2026-09-01', amountCents: 12345, currency: 'CNY', title: '合成采购', category: '家庭采购', source: 'generic', kind: 'payments', flow: 'expense', visibility: 'private', externalId: 'synthetic-1', status: '已完成', importedAt: '2026-09-17T00:00:00+00:00', checkedAt: null, ...patch });
const ledger = (patch = {}) => ({ month: '2026-09', q: '', page: 1, pageSize: 25, totalPages: 1, hasNext: false, hasPrevious: false, transactionCount: 1, filteredCount: 1, snapshot, transactions: [transaction()], ...patch });
const shared = () => ({ wallet: 10000, livingBudget: 1000.25, livingSpent: 150.31, travelSaved: 3500, longterm: 80000, reserveTarget: 10000, contributionPercent: 50, note: '合成快照', revision: 2 });

test('integer formatting preserves cents, negatives and the largest safe integer exactly', () => {
  assert.equal(centsToDecimal(1), '0.01'); assert.equal(centsToDecimal(-1), '-0.01');
  assert.equal(centsToDecimal(9007199254740991), '90071992547409.91');
  assert.equal(formatFinanceAmount(-123456789, 'USD'), 'USD -1,234,567.89');
  assert.equal(formatFinanceAmount(1000, 'JPY'), 'JPY 10.00');
  for (const n of [NaN, Infinity, 1.1, Number.MAX_SAFE_INTEGER + 1, '100', null]) assert.throws(() => formatFinanceAmount(n, 'CNY'));
  assert.throws(() => formatFinanceAmount(10, '<x>'));
});

test('decimal input uses strings and integer comparison without rounding or permissive parsing', () => {
  assert.equal(decimalInput(' 0.1 '), '0.10'); assert.equal(decimalInput('1000000000000.00'), '1000000000000.00');
  for (const v of ['', '-1', '+1', '.1', '01', '1,000', '1.005', '1e2', '￥12', '1000000000000.01', 'NaN']) assert.throws(() => decimalInput(v));
  assert.throws(() => decimalInput('0', true)); assert.equal(decimalInput('0.01', true), '0.01');
});

test('unsafe route identities and invalid financial DTO amounts fail closed', () => {
  assert.equal(readTransaction(transaction()).id, first);
  for (const patch of [{ id: '../private' }, { revision: '1' }, { amountCents: 0.1 }, { amountCents: -1 }, { currency: 'RMB?' }, { flow: 'invest' }, { visibility: 'everyone' }]) assert.throws(() => readTransaction(transaction(patch)));
  assert.throws(() => readTransaction(transaction({ orderItems: [{ title: 'x', sourceLine: 1 }] })));
});

test('ledger pagination preserves opaque snapshots and refuses duplicate rows or invalid pagination', () => {
  const page = readLedger(ledger()); assert.equal(page.transactions.length, 1);
  const url = ledgerPath({ month: '2026-09', q: '订单 & 退款', page: 2, snapshot });
  const params = new URL('https://example.test' + url).searchParams;
  assert.equal(params.get('q'), '订单 & 退款'); assert.equal(params.get('page'), '2'); assert.equal(params.get('snapshot'), snapshot);
  assert.equal(new URL('https://example.test' + ledgerPath({ month: '2026-09', q: '', page: 1 })).searchParams.has('snapshot'), false);
  for (const patch of [{ snapshot: '' }, { snapshot: 'unsafe/?' }, { page: 2 }, { hasNext: 'false' }, { pageSize: 101 }, { transactions: [transaction(), transaction()] }]) assert.throws(() => readLedger(ledger(patch)));
  assert.throws(() => ledgerPath({ month: '2026-13', q: '', page: 1 }));
});

test('transaction patch carries revision and requires explicit valid sharing', () => {
  const row = readTransaction(transaction());
  assert.deepEqual(transactionPatch(row, ' 餐饮 ', 'expense', true), { revision: 1, category: '餐饮', flow: 'expense', visibility: 'shared' });
  assert.deepEqual(transactionPatch(row, '转账', 'transfer', false), { revision: 1, category: '转账', flow: 'transfer', visibility: 'private' });
  for (const flow of ['income', 'transfer', 'unknown', 'excluded']) assert.throws(() => transactionPatch(row, '分类', flow, true));
  assert.throws(() => transactionPatch(readTransaction(transaction({ kind: 'orders' })), '购物', 'expense', true));
  assert.throws(() => transactionPatch(row, ' ', 'expense', false));
});

test('budget keys and revisions retain original currency and separate total/category budgets', () => {
  assert.deepEqual(budgetPayload({ month: '2026-09', currency: ' usd ', category: '全部', amount: '100.01', revision: 0 }), { month: '2026-09', currency: 'USD', category: '全部', amount: '100.01', revision: 0 });
  for (const patch of [{ month: '2026-00' }, { month: '0000-09' }, { currency: 'US' }, { category: '' }, { revision: '1' }, { amount: '0.001' }]) assert.throws(() => budgetPayload({ month: '2026-09', currency: 'CNY', category: '餐饮', amount: '100', revision: 1, ...patch }));
});

test('server currency totals remain separate and negative net spend is preserved', () => {
  const totals = readTotals([{ currency: 'CNY', expenseCents: 10000, refundCents: 13000, netSpendCents: -3000, count: 2 }, { currency: 'USD', expenseCents: 500, refundCents: 0, netSpendCents: 500, count: 1 }]);
  assert.equal(totals[0].netSpendCents, -3000); assert.equal(totals[1].currency, 'USD'); assert.equal(totals.length, 2);
  assert.throws(() => readTotals([{ currency: 'USD', expenseCents: 100.1, refundCents: 0, netSpendCents: 100.1, count: 1 }]));
});

test('reconciliation preview binds both identities versions and currency', () => {
  const left = transaction({ kind: 'orders' }), right = transaction({ id: second });
  const value = { kind: 'order_payment', left, right, leftId: first, rightId: second, leftRevision: 1, rightRevision: 1, amountCents: 12345, previewToken: 'synthetic-only', effect: '订单不重复计入消费', reasons: ['金额相同'], uncertainty: ['需本人核对'] };
  assert.equal(readRelationPreview(value).left.id, first);
  for (const patch of [{ leftId: second }, { rightRevision: 2 }, { previewToken: '' }, { right: transaction({ id: second, currency: 'USD' }) }, { amountCents: 0 }]) assert.throws(() => readRelationPreview({ ...value, ...patch }));
  const context = readReconciliation({ transaction: right, candidates: [{ kind: 'order_payment', left, right, maxAmountCents: 12345, suggestedAmountCents: 12345, reasons: [], uncertainty: [] }], relations: [], candidateCount: 1, truncated: false, note: '需明确确认' });
  assert.equal(context.candidates[0].maxAmountCents, 12345);
});

test('legacy shared snapshot sends all original-unit decimal fields and its revision', () => {
  const snapshot = readSharedSnapshot(shared());
  const inputs = Object.fromEntries(Object.entries(snapshot).filter(([key]) => key !== 'revision').map(([k, v]) => [k, String(v)]));
  const payload = sharedSnapshotPayload(snapshot, inputs);
  assert.equal(payload.wallet, '10000.00'); assert.equal(payload.livingSpent, '150.31'); assert.equal(payload.revision, 2); assert.equal(payload.note, '合成快照');
  assert.throws(() => sharedSnapshotPayload(snapshot, { ...inputs, contributionPercent: '100.01' }));
  assert.throws(() => readSharedSnapshot({ ...shared(), livingSpent: NaN }));
});

test('overview projects actual existing months without treating zero selected-month records as an empty history', () => {
  const value = readOverview({ month: '2026-09', transactionCount: 0, totalRecordCount: 7, availableMonths: [{ month: '2026-08', recordCount: 7 }], totals: [], budgets: [], imports: [], coverage: '仅已导入记录' });
  assert.equal(value.totalRecordCount, 7); assert.equal(value.availableMonths[0].month, '2026-08');
});

test('recorded provenance preserves actual batch/file/line values while unknown history stays unknown', () => {
  const provenance = { status: 'recorded', batchId: second, source: 'generic', kind: 'payments', fileName: 'synthetic.csv', format: 'csv', sheet: null, lineStart: 2, lineEnd: 3, lineKind: 'csv_lines', importedAt: '2026-09-17T00:00:00+00:00' };
  assert.deepEqual(readTransaction(transaction({ provenance })).provenance, provenance);
  assert.deepEqual(readTransaction(transaction({ provenance: { status: 'unknown', fileName: 'must-not-infer.csv' } })).provenance, { status: 'unknown' });
  for (const patch of [{ batchId: '../x' }, { source: 'wechat' }, { lineStart: 4 }, { lineKind: 'guessed' }, { format: 'html' }]) assert.throws(() => readTransaction(transaction({ provenance: { ...provenance, ...patch } })));
});
