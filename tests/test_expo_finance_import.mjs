import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canConfirmImport, confirmImportPayload, importAmount, importPayload, importRejectionIsDefinite, importSourceLabel, inspectImportColumnsPayload, manualImportPayload, readImportColumnSelection, isImportRequestId, newImportRequestId, readImportPreview, readImportReceipt } from '../frontend/src/lib/financeImport.ts';

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

const selection = () => ({ headerLine: 2, lineKind: 'csv_lines', columns: [
  { index: 0, label: '日期', columnLabel: 'A' }, { index: 1, label: '', columnLabel: 'B' },
  { index: 2, label: '标题', columnLabel: 'C' }, { index: 3, label: '币种', columnLabel: 'D' },
  { index: 4, label: '金额', columnLabel: 'E' }], suggestedMapping: { date: 0, amount: null, title: 2, currency: 3 } });
const mapping = () => ({ version: 1, headerLine: 2, date: 0, amount: 1, title: 2, currency: 3 });
const mappedPreview = () => ({ ...preview(), requiresColumnSelection: false,
  columnSelection: { ...selection(), mapping: mapping() }, amountSelection: null });

test('header discovery is bounded, non-confirmable and contains no automatic import intent', () => {
  const payload = inspectImportColumnsPayload('generic', 'payments', file, 2);
  assert.deepEqual(payload, { source: 'generic', kind: 'payments', file, inspectColumns: true, headerLine: 2 });
  assert.equal('headerLine' in inspectImportColumnsPayload('generic', 'orders', file), false);
  const raw = { ...preview(), rows: [], previewToken: null, requiresColumnSelection: true, columnSelection: selection() };
  const inspected = readImportPreview(raw); assert.equal(canConfirmImport(inspected), false);
  assert.throws(() => confirmImportPayload(payload, inspected, id));
  for (const line of [0, -1, 61, 1.5, NaN, '2']) assert.throws(() => inspectImportColumnsPayload('generic', 'payments', file, line));
  assert.throws(() => inspectImportColumnsPayload('wechat', 'payments', file));
  assert.throws(() => inspectImportColumnsPayload('generic', 'payments', { ...file, name: 'sheet.xlsx' }));
  assert.equal(inspectImportColumnsPayload('generic', 'orders', { ...file, name: 'sheet.xlsx', sheet: '账单' }).file.sheet, '账单');
});

test('all four mapping fields are required, different, in the current header and cloned', () => {
  const map = mapping(), input = { ...file }, meta = selection();
  const payload = manualImportPayload('generic', 'payments', input, meta, map);
  assert.deepEqual(Object.keys(payload).sort(), ['file', 'kind', 'mapping', 'source']);
  map.amount = 4; input.name = 'changed.csv'; meta.columns[0].label = '改后';
  assert.equal(payload.mapping.amount, 1); assert.equal(payload.file.name, 'synthetic.csv');
  for (const patch of [{ currency: null }, { currency: 1 }, { currency: 79 }, { date: 1.5 }, { headerLine: 3 }, { version: 2 }, { amountColumn: 4 }]) {
    assert.throws(() => manualImportPayload('generic', 'payments', file, selection(), { ...mapping(), ...patch }));
  }
  const missing = mapping(); delete missing.currency;
  assert.throws(() => manualImportPayload('generic', 'payments', file, selection(), missing));
  assert.throws(() => manualImportPayload('alipay', 'payments', file, selection(), mapping()));
});

test('column reader preserves blank, duplicate and Unicode labels without accepting wrong coordinates', () => {
  const raw = selection(); raw.columns[0].label = '😀'.repeat(200); raw.columns[2].label = '';
  const result = readImportColumnSelection(raw); assert.equal(result.columns[1].label, ''); assert.equal(result.columns[2].label, '');
  raw.columns[1].label = 'mutated'; raw.suggestedMapping.date = null;
  assert.equal(result.columns[1].label, ''); assert.equal(result.suggestedMapping.date, 0);
  for (const patch of [{ headerLine: 61 }, { lineKind: 'guessed' }, { columns: [] },
    { columns: [...selection().columns, selection().columns[0]] },
    { columns: [{ index: 0, label: '日期', columnLabel: 'Z' }] },
    { suggestedMapping: { ...selection().suggestedMapping, currency: 79 } },
    { suggestedMapping: { date: 0, amount: 1, title: 2 } }]) assert.throws(() => readImportColumnSelection({ ...selection(), ...patch }));
  assert.throws(() => readImportColumnSelection({ ...selection(), columns: [{ index: 0, columnLabel: 'A', label: '😀'.repeat(201) }] }));
});

test('a malformed or ambiguous column response cannot become a valid preview', () => {
  assert.equal(canConfirmImport(readImportPreview(mappedPreview())), true);
  for (const patch of [{ requiresColumnSelection: null }, { requiresColumnSelection: 'false' }, { columnSelection: undefined },
    { columnSelection: selection() }, { requiresAmountSelection: true }, { amountSelection: { selectedIndex: 1, columns: [] } }])
    assert.throws(() => readImportPreview({ ...mappedPreview(), ...patch }));
  const raw = { ...preview(), rows: [], previewToken: null, requiresColumnSelection: true, columnSelection: selection() };
  for (const patch of [{ rows: [row] }, { previewToken: 'not-discovery' }, { requiresSheetSelection: true },
    { errorCount: 1 }, { columnSelection: { ...selection(), mapping: mapping() } }]) assert.throws(() => readImportPreview({ ...raw, ...patch }));
});

test('unknown confirmation retains a deep copy of the original four columns and signed preview', () => {
  const payload = manualImportPayload('generic', 'payments', file, selection(), mapping());
  const shown = readImportPreview(mappedPreview()), intent = confirmImportPayload(payload, shown, id);
  payload.mapping.amount = 4; shown.columnSelection.mapping.amount = 4;
  assert.deepEqual(intent.mapping, mapping()); assert.equal(intent.requestId, id); assert.equal(intent.previewToken, 'synthetic-signed-preview');
  assert.equal(intent.file.contentBase64, file.contentBase64);
  assert.equal(importRejectionIsDefinite(400, true), false);
  assert.throws(() => confirmImportPayload(payload, readImportPreview(mappedPreview()), id));
  assert.throws(() => confirmImportPayload({ ...intent, amountColumn: 1 }, readImportPreview(mappedPreview()), id));
  assert.throws(() => confirmImportPayload({ ...intent, inspectColumns: false }, readImportPreview(mappedPreview()), id));
  assert.throws(() => confirmImportPayload(importPayload('generic', 'payments', file), readImportPreview(mappedPreview()), id));
});

test('manual preview preserves server amounts, currencies, errors and physical row ranges', () => {
  const raw = mappedPreview(); raw.rows = [{ ...row, title: '多行\n标题', currency: 'USD', amountCents: 1,
    sourceLocation: { lineStart: 3, lineEnd: 4, lineKind: 'csv_lines' } }];
  const value = readImportPreview(raw); assert.equal(importAmount(value.rows[0].amountCents, value.rows[0].currency), 'USD 0.01');
  assert.equal(importSourceLabel(value.rows[0].sourceLocation), '原文件第 3–4 行');
  assert.equal(value.rows[0].title, '多行\n标题');
  const erroneous = readImportPreview({ ...raw, previewToken: null, errorCount: 1, errors: [{ line: 7, message: '缺少币种' }] });
  assert.equal(canConfirmImport(erroneous), false); assert.throws(() => confirmImportPayload(manualImportPayload('generic', 'payments', file, selection(), mapping()), erroneous, id));
});
