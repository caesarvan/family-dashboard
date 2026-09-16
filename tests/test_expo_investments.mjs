import assert from 'node:assert/strict';
import { test } from 'node:test';
import { filterInvestments, formatInvestmentCents, investmentAmount, investmentDecimal, investmentDraft, investmentIntent, investmentPayload, investmentQuantity, newInvestmentRequestId, readInvestmentAck, readInvestmentList, readInvestmentReceipt, sumInvestments, validInvestmentDate } from '../frontend/src/lib/investments.ts';

const id = 'a'.repeat(24), operationId = 'c'.repeat(32);
const holding = (patch = {}) => ({ id, revision: 3, name: '合成基金', institution: '示例机构', assetType: '基金', currency: 'CNY', quantity: '12.00000001', costCents: 10000, valueCents: 13000, asOf: '2026-09-01', note: '虚构测试', valuationSource: 'manual', visibility: 'private', updatedAt: '2026-09-17T00:00:00+00:00', source: null, ...patch });
const list = (investments = [holding()], sources = []) => ({ investments, sources });
const draft = () => investmentDraft(holding());

test('integer formatter preserves full safe integer and BigInt aggregate precision', () => {
  assert.equal(investmentDecimal(9007199254740991), '90071992547409.91');
  assert.equal(formatInvestmentCents(2702159776422297300n, 'USD'), 'USD 27,021,597,764,222,973.00');
  assert.equal(formatInvestmentCents(-1n, 'CNY'), 'CNY -0.01');
  for (const value of [NaN, Infinity, '100', 1.1, Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => investmentDecimal(value));
  assert.throws(() => formatInvestmentCents(0n, 'bad-code'));
});

test('partial valuation totals exclude unknown costs from gain and never combine currencies', () => {
  const rows = [holding(), holding({ id: 'b'.repeat(24), costCents: 3000, valueCents: null }), holding({ id: 'd'.repeat(24), costCents: 700, valueCents: 0 }), holding({ id: 'e'.repeat(24), currency: 'USD', costCents: 10, valueCents: 11 })];
  assert.deepEqual(sumInvestments(rows), [
    { currency: 'CNY', count: 3, knownCount: 2, unknownCount: 1, costCents: 13700n, knownCostCents: 10700n, knownValueCents: 13000n, knownGainCents: 2300n },
    { currency: 'USD', count: 1, knownCount: 1, unknownCount: 0, costCents: 10n, knownCostCents: 10n, knownValueCents: 11n, knownGainCents: 1n },
  ]);
  const many = Array.from({ length: 300 }, () => holding({ costCents: Number.MAX_SAFE_INTEGER, valueCents: Number.MAX_SAFE_INTEGER }));
  assert.equal(sumInvestments(many)[0].costCents, 2702159776422297300n);
});

test('amount and quantity inputs are strict strings with exact upper bounds', () => {
  assert.equal(investmentAmount(' 12.3 '), '12.30');
  assert.equal(investmentAmount('1000000000000'), '1000000000000.00');
  for (const value of ['1,200', '￥12', '1e2', '.1', '01', '-1', '+1', '1.001', '', '1000000000000.01', 12]) assert.throws(() => investmentAmount(value));
  assert.equal(investmentQuantity('999999999999999.12345678'), '999999999999999.12345678');
  assert.equal(investmentQuantity(''), '');
  for (const value of ['1000000000000000', '1.123456789', '-1', '1e2', '1,000', 10]) assert.throws(() => investmentQuantity(value));
});

test('unknown valuation remains blank while real zero remains 0.00 through edit payload', () => {
  const unknown = investmentDraft(holding({ valueCents: null, quantity: null }));
  assert.equal(unknown.value, ''); assert.equal(unknown.quantity, '');
  assert.equal(investmentPayload(unknown, operationId).value, '');
  const zero = investmentDraft(holding({ valueCents: 0 }));
  assert.equal(zero.value, '0.00'); assert.equal(investmentPayload(zero, operationId).value, '0.00');
  const payload = investmentPayload(draft(), operationId, 3);
  assert.deepEqual(Object.keys(payload).sort(), ['asOf', 'assetType', 'cost', 'currency', 'institution', 'name', 'note', 'quantity', 'requestId', 'revision', 'value']);
  assert.equal(payload.cost, '100.00'); assert.equal(payload.revision, 3);
});

test('real calendar dates and mandatory complete fields are checked without guessing', () => {
  for (const value of ['2024-02-29', '2026-09-30', '0001-01-01']) assert.equal(validInvestmentDate(value), true);
  for (const value of ['2026-02-29', '2026-09-31', '0000-01-01', '2026-9-01', 'not-a-date']) assert.equal(validInvestmentDate(value), false);
  for (const patch of [{ name: '' }, { institution: '' }, { assetType: '' }, { name: 'a'.repeat(121) }, { currency: 'CN' }, { asOf: '2026-02-29' }, { note: 'x'.repeat(1001) }]) assert.throws(() => investmentPayload({ ...draft(), ...patch }, operationId));
});

test('full private list validates source metadata, limits, duplicate identity and integer fields', () => {
  const row = holding({ source: { sourceName: '合成来源', holdingKey: 'holding-01' }, valuationSource: 'file_import' });
  const value = list([row], [{ sourceName: '合成来源', revision: 2, updatedAt: row.updatedAt, holdingCount: 1, deletedCount: 4 }]);
  assert.deepEqual(readInvestmentList(value), value);
  for (const patch of [{ visibility: 'shared' }, { costCents: 1.1 }, { valueCents: Number.MAX_SAFE_INTEGER + 1 }, { source: undefined }, { updatedAt: '' }]) assert.throws(() => readInvestmentList(list([holding(patch)])));
  assert.throws(() => readInvestmentList(list([holding(), holding()])));
  assert.throws(() => readInvestmentList(list(Array.from({ length: 301 }, () => holding()))));
});

test('local filters include all holdings and respect independent name institution and currency', () => {
  const first = holding(), second = holding({ id: 'b'.repeat(24), name: '合成股票', currency: 'USD', institution: 'Another Bank' });
  assert.deepEqual(filterInvestments([first, second], { name: '股票', institution: 'bank', currency: 'usd' }), [second]);
  assert.equal(filterInvestments([first, second], { name: '', institution: '', currency: '' }).length, 2);
  assert.equal(filterInvestments([first, second], { name: '基金', institution: 'Bank', currency: '' }).length, 0);
});

test('immutable operation intent binds exact id revision payload and same-request replay', () => {
  const input = draft(), intent = investmentIntent('update', input, operationId, holding());
  input.name = 'later draft';
  assert.equal(intent.payload.name, '合成基金'); assert.equal(intent.payload.requestId, operationId);
  assert.equal(intent.path, '/finance-hub/investments/' + id); assert.equal(intent.method, 'PATCH');
  assert.deepEqual(investmentIntent('delete', null, operationId, holding()).payload, { revision: 3, requestId: operationId });
  assert.throws(() => investmentIntent('update', draft(), operationId, holding({ id: '../foreign' })));
  assert.throws(() => investmentIntent('create', draft(), operationId.toUpperCase()));
  assert.match(newInvestmentRequestId(), /^[a-f0-9]{32}$/);
});

test('receipt and acknowledgement reject another request, kind or record without inferring current state', () => {
  const intent = investmentIntent('update', draft(), operationId, holding());
  const result = holding({ revision: 4 });
  const receipt = { requestId: operationId, kind: 'update', recordId: id, result, completedAt: '2026-09-17T00:00:00+00:00' };
  assert.equal(readInvestmentReceipt(receipt, intent).result.revision, 4);
  for (const patch of [{ requestId: 'f'.repeat(32) }, { kind: 'create' }, { recordId: 'b'.repeat(24) }, { result: { deleted: true } }]) assert.throws(() => readInvestmentReceipt({ ...receipt, ...patch }, intent));
  readInvestmentAck({ ...result, requestId: operationId, replayed: true }, intent);
  assert.throws(() => readInvestmentAck({ ...result, requestId: operationId }, intent));
  const removal = investmentIntent('delete', null, operationId, holding());
  assert.equal(readInvestmentReceipt({ ...receipt, kind: 'delete', result: { deleted: true } }, removal).result.deleted, true);
});
