import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canConfirmImport, confirmImportPayload, importAmount, importPayload, importRejectionIsDefinite, importSourceLabel, isImportRequestId, newImportRequestId, readImportPreview, readImportReceipt } from '../frontend/src/lib/financeImport.ts';

const id = 'a'.repeat(32);
const file = { name: 'synthetic.csv', contentBase64: 'YWJj', encoding: 'auto' };
const row = { line: 2, sourceLocation: { lineStart: 2, lineEnd: 2, lineKind: 'csv_lines' }, title: '合成咖啡', date: '2026-09-01', amountCents: 123456, currency: 'CNY', flow: 'expense', duplicate: false, conflict: false };
const preview = () => ({ rows: [row], errors: [], errorCount: 0, warnings: [], newCount: 1, duplicateCount: 0, conflictCount: 0,
  previewToken: 'synthetic-signed-preview', requiresSheetSelection: false, requiresAmountSelection: false });
const receipt = () => ({ requestId: id, receiptId: 'b'.repeat(64), batchId: 'c'.repeat(24), imported: 1, duplicates: 0, conflicts: 0,
  confirmedAt: '2026-09-17T03:00:00+08:00', resultMonths: [{ month: '2026-09', recordCount: 1 }], replayed: false });

test('discovery and column choice cannot masquerade as a ready zero-error preview', () => {
  const sheets = readImportPreview({ ...preview(), rows: [], previewToken: null, requiresSheetSelection: true, fileInfo: { sheets: ['账单', '说明'] } });
  const columns = readImportPreview({ ...preview(), rows: [], previewToken: null, requiresAmountSelection: true, amountSelection: { selectedIndex: null, columns: [{ index: 2, label: '金额', columnLabel: 'C' }] } });
  for (const value of [sheets, columns, { ...preview(), errorCount: 1 }, { ...preview(), rows: [] }]) assert.equal(canConfirmImport(value), false);
  assert.equal(canConfirmImport(readImportPreview(preview())), true);
  assert.throws(() => confirmImportPayload(importPayload('generic', 'payments', file), columns, id));
});

test('submitted payload retains the original file, token, column and request across edited draft objects', () => {
  const original = { ...file }, payload = importPayload('wechat', 'payments', original, 2);
  const submitted = confirmImportPayload(payload, preview(), id);
  original.name = 'different.csv'; payload.file.contentBase64 = 'different';
  assert.equal(submitted.file.name, 'synthetic.csv'); assert.equal(submitted.file.contentBase64, 'YWJj');
  assert.equal(submitted.previewToken, 'synthetic-signed-preview'); assert.equal(submitted.requestId, id); assert.equal(submitted.amountColumn, 2);
  assert.throws(() => importPayload('generic', 'payments', file, 2, true));
});

test('receipt must belong to the exact pending operation and remain an identifiable history', () => {
  assert.deepEqual(readImportReceipt(receipt(), id), receipt());
  assert.equal(readImportReceipt({ ...receipt(), batchId: null, replayed: true }, id).replayed, true);
  for (const change of [{ requestId: 'd'.repeat(32) }, { receiptId: '../secret' }, { imported: -1 }, { imported: 1.2 },
    { confirmedAt: '' }, { replayed: 'true' }, { resultMonths: [{ month: '2026-13', recordCount: 1 }] },
    { resultMonths: [{ month: '2026-09', recordCount: 1 }, { month: '2026-09', recordCount: 2 }] }]) assert.throws(() => readImportReceipt({ ...receipt(), ...change }, id));
});

test('unsafe monetary values and malformed row errors never become readable valid previews', () => {
  for (const patch of [{ amountCents: 1.5 }, { amountCents: Number.MAX_SAFE_INTEGER + 1 }, { currency: 'USD + CNY' },
    { orderItems: [{ title: { unexpected: 'object' } }] }]) assert.throws(() => readImportPreview({ ...preview(), rows: [{ ...row, ...patch }] }));
  assert.throws(() => readImportPreview({ ...preview(), errorCount: 1, errors: [{ line: 3, error: 'wrong-shape' }] }));
  assert.equal(readImportPreview({ ...preview(), errorCount: 1, errors: [{ line: 3, message: '金额无法核对' }] }).errorCount, 1);
});

test('integer cent display preserves exact cents and separate currency without conversion', () => {
  assert.equal(importAmount(123456, 'CNY'), 'CNY 1,234.56');
  assert.equal(importAmount(100000000000001, 'USD'), 'USD 1,000,000,000,000.01');
  assert.equal(importAmount(1, 'JPY'), 'JPY 0.01');
  assert.equal(importAmount(NaN, 'CNY'), '金额待核对');
});

test('request identifiers are strong hex and cannot alter the receipt path', () => {
  const one = newImportRequestId(), two = newImportRequestId(); assert.ok(isImportRequestId(one)); assert.notEqual(one, two);
  for (const bad of ['../accounts', 'A'.repeat(32), 'a'.repeat(31), 'a'.repeat(65), 'a'.repeat(32) + '?owner=member2']) assert.equal(isImportRequestId(bad), false);
});

test('multiline cells use physical worksheet rows and order source texts stay intact', () => {
  const value = readImportPreview({ ...preview(), rows: [{ ...row, line: 7,
    sourceLocation: { lineStart: 3, lineEnd: 3, lineKind: 'worksheet_rows' },
    orderItems: [{ title: '合成商品', quantityText: '2 件', listedAmountText: '¥100（优惠前）' }] }] });
  assert.equal(importSourceLabel(value.rows[0].sourceLocation), '工作表第 3 行');
  assert.equal(value.rows[0].orderItems[0].listedAmountText, '¥100（优惠前）');
  assert.equal(importSourceLabel({ lineStart: 2, lineEnd: 4, lineKind: 'csv_lines' }), '原文件第 2–4 行');
  for (const sourceLocation of [undefined, { lineStart: 0, lineEnd: 2, lineKind: 'csv_lines' },
    { lineStart: 4, lineEnd: 2, lineKind: 'worksheet_rows' }, { lineStart: 1, lineEnd: 2, lineKind: 'guessed' }])
    assert.throws(() => readImportPreview({ ...preview(), rows: [{ ...row, sourceLocation }] }));
  assert.throws(() => readImportPreview({ ...preview(), rows: [{ ...row, orderItems: [{ title: '商品', quantityText: 2 }] }] }));
});

test('an expired retry cannot discard the recovery identity of an earlier unknown submission', () => {
  assert.equal(importRejectionIsDefinite(400, false), true);
  for (const status of [undefined, 400, 404, 409, 413, 422, 500, 503]) assert.equal(importRejectionIsDefinite(status, true), false);
  assert.equal(importRejectionIsDefinite(undefined, false), false);
  assert.equal(importRejectionIsDefinite(503, false), false);
});
