import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canConfirmHoldingImport, holdingCheckedRead, holdingImportAttempt, holdingImportPayload, holdingMoney, holdingReceiptPath, holdingRecoveryChoices,
  holdingSourceName, readHoldingImportPreview, readHoldingSources, readHoldingTemplate, readImportHolding, readInvestmentImportReceipt,
  HOLDING_FILE_LIMIT, HOLDING_PREVIEW_MS } from '../frontend/src/lib/investmentImport.ts';
import { PhotoReadDiscarded, PhotoReadFence, photoSignature } from '../frontend/src/lib/photos.ts';

const sourceName = '合成券商 · 个人账户', sourceDigest = 'a'.repeat(64);
const file = () => ({ name: 'synthetic.csv', contentBase64: 'YWJj', encoding: 'auto' });
const holding = () => ({ name: '合成基金', institution: '合成机构', assetType: '基金', currency: 'CNY', quantity: '10.00000001',
  costCents: 10000, valueCents: 11000, asOf: '2026-09-01', note: '虚构记录\n第二行', visibility: 'private', valuationSource: 'file_import' });
const row = () => ({ line: 3, holdingKey: 'synthetic-001', action: 'create', before: null, after: holding(), warnings: [] });
const preview = () => ({ sourceName, sourceDigest, requiresSheetSelection: false,
  fileInfo: { name: 'synthetic.csv', format: 'csv', encoding: 'UTF-8', sheet: null, sheets: [] },
  rows: [row()], counts: { create: 1, update: 0, unchanged: 0 }, preservedCount: 0,
  warnings: [], errors: [], errorCount: 0, previewToken: 'synthetic.preview.token' });
const receipt = () => ({ created: 1, updated: 0, unchanged: 0, replayed: false, receiptId: 'b'.repeat(32), confirmedAt: '2026-09-17T04:00:00+00:00' });
const lookupReceipt = () => ({ ...receipt(), sourceName, sourceDigest, replayed: true });
const intent = () => holdingImportAttempt(holdingImportPayload(sourceName, file()), readHoldingImportPreview(preview(), sourceName), 1000);
const session = () => ({ user: { id: 'member1', role: 'member', householdId: 'synthetic', auth_version: 1 }, csrf: 'synthetic-csrf' });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

test('ready standard preview preserves each before/after value without computing quantities or exchange rates', () => {
  const before = { ...holding(), id: 'synthetic-record', revision: 3, valuationSource: 'manual', costCents: 9000 };
  const value = readHoldingImportPreview({ ...preview(), rows: [{ ...row(), action: 'update', before }], counts: { create: 0, update: 1, unchanged: 0 } }, sourceName);
  assert.equal(canConfirmHoldingImport(value), true); assert.equal(value.rows[0].before.costCents, 9000);
  assert.equal(value.rows[0].after.quantity, '10.00000001'); assert.equal(value.rows[0].after.note, '虚构记录\n第二行');
});

test('unknown valuation is distinct from zero and money boundaries preserve integer cents', () => {
  assert.equal(readImportHolding({ ...holding(), valueCents: null }).valueCents, null);
  assert.equal(readImportHolding({ ...holding(), valueCents: 0 }).valueCents, 0);
  assert.equal(holdingMoney(null, 'CNY'), '现值未知'); assert.equal(holdingMoney(0, 'CNY'), 'CNY 0.00');
  assert.equal(holdingMoney(100_000_000_000_000, 'USD'), 'USD 1,000,000,000,000.00');
  for (const value of [-1, 1.2, Infinity, NaN, 100_000_000_000_001, '1', true]) {
    assert.throws(() => readImportHolding({ ...holding(), costCents: value }));
    assert.throws(() => readImportHolding({ ...holding(), valueCents: value }));
  }
  assert.equal(holdingMoney(1100, 'JPY'), 'JPY 11.00');
});

test('holding parser validates real calendar days, quantities, privacy and existing record identity', () => {
  for (const change of [{ quantity: 10 }, { quantity: '1e9' }, { quantity: '-1' }, { quantity: '1.123456789' }, { quantity: '1234567890123456' },
    { currency: 'usd' }, { currency: 'CNY + USD' }, { asOf: '2026-02-29' }, { asOf: '2024-02-30' }, { asOf: '0000-01-01' },
    { name: '' }, { name: 'a'.repeat(121) }, { note: 'a'.repeat(1001) }, { visibility: 'shared' }, { valuationSource: 'market' }, { name: '\ud800' }]) {
    assert.throws(() => readImportHolding({ ...holding(), ...change }));
  }
  assert.equal(readImportHolding({ ...holding(), asOf: '2024-02-29', quantity: null }).asOf, '2024-02-29');
  assert.throws(() => readImportHolding({ ...holding(), id: '../member2', revision: 1 }, true));
  assert.throws(() => readImportHolding({ ...holding(), id: 'safe', revision: 0 }, true));
});

test('XLSX discovery is never confirmable and the selected sheet stays attached to its original file', () => {
  const workbook = holdingImportPayload(sourceName, { ...file(), name: 'synthetic.xlsx' });
  assert.equal(workbook.inspectSheets, true);
  const discovery = readHoldingImportPreview({ ...preview(), sourceDigest: undefined, requiresSheetSelection: true, rows: [], previewToken: null,
    counts: { create: 0, update: 0, unchanged: 0 }, fileInfo: { name: 'synthetic.xlsx', format: 'xlsx', encoding: 'OOXML / UTF-8', sheet: null, sheets: ['说明', '本人持仓'] } }, sourceName);
  assert.equal(canConfirmHoldingImport(discovery), false);
  const selected = holdingImportPayload(sourceName, { ...workbook.file, sheet: '本人持仓' });
  assert.equal(selected.inspectSheets, undefined); assert.equal(selected.file.sheet, '本人持仓');
  assert.throws(() => readHoldingImportPreview({ ...discovery, previewToken: 'not-ready' }, sourceName));
  assert.throws(() => readHoldingImportPreview({ ...discovery, fileInfo: { ...discovery.fileInfo, sheets: [] } }, sourceName));
  assert.throws(() => readHoldingImportPreview({ ...discovery, fileInfo: { ...discovery.fileInfo, sheets: ['本人持仓', '本人持仓'] } }, sourceName));
});

test('file metadata rejects unsupported inputs, traversal, malformed bytes and over-limit files', () => {
  for (const change of [{ name: 'bank.pdf' }, { name: 'holdings.xlsm' }, { name: '../holdings.csv' }, { name: 'x\u0000.csv' }, { name: 'a'.repeat(201) + '.csv' },
    { contentBase64: '' }, { contentBase64: '***=' }, { contentBase64: 'YWJj\n' }, { contentBase64: 'YQ=' }, { encoding: 'utf-16' }, { sheet: 'unexpected CSV sheet' }]) {
    assert.throws(() => holdingImportPayload(sourceName, { ...file(), ...change }));
  }
  const max = Buffer.alloc(HOLDING_FILE_LIMIT, 65).toString('base64');
  assert.equal(holdingImportPayload(sourceName, { ...file(), contentBase64: max }).file.contentBase64, max);
  assert.throws(() => holdingImportPayload(sourceName, { ...file(), contentBase64: Buffer.alloc(HOLDING_FILE_LIMIT + 1, 65).toString('base64') }));
  assert.equal(holdingImportPayload(sourceName, { ...file(), name: 'holdings.txt' }).file.name, 'holdings.txt');
});

test('source names preserve stable case and characters while receipt queries cannot add parameters', () => {
  const name = '账户 &sourceDigest=other / #本人';
  assert.equal(holdingSourceName('  ' + name + ' '), name);
  assert.notEqual(holdingSourceName('broker'), holdingSourceName('Broker'));
  assert.equal(holdingSourceName('😀'.repeat(80)), '😀'.repeat(80));
  for (const invalid of ['', '  ', 'x\ny', 'a'.repeat(81), null, { source: 'x' }]) assert.throws(() => holdingSourceName(invalid));
  const url = new URL(holdingReceiptPath(name, sourceDigest), 'https://example.invalid');
  assert.equal(url.searchParams.get('sourceName'), name); assert.equal(url.searchParams.get('sourceDigest'), sourceDigest);
  assert.equal([...url.searchParams].length, 2);
  for (const invalid of ['A'.repeat(64), 'a'.repeat(63), sourceDigest + '&owner=member2']) assert.throws(() => holdingReceiptPath(name, invalid));
});

test('row/count inconsistencies and batch errors cannot become partial confirmations', () => {
  for (const change of [{ errorCount: 1 }, { rows: [...preview().rows, row()] }, { counts: { create: 2, update: 0, unchanged: 0 } },
    { sourceName: 'another source' }, { sourceDigest: '../other' }, { preservedCount: 301 }, { rows: [{ ...row(), action: 'update' }] },
    { rows: [{ ...row(), action: 'create', before: { ...holding(), id: 'existing', revision: 1 } }] }, { rows: [{ ...row(), line: 0 }] },
    { rows: [{ ...row(), warnings: [{ unexpected: true }] }] }, { warnings: ['x'.repeat(4001)] }]) {
    assert.throws(() => readHoldingImportPreview({ ...preview(), ...change }, sourceName));
  }
  const invalid = readHoldingImportPreview({ ...preview(), errorCount: 1, errors: [{ line: 0, message: '整批错误' }], previewToken: null }, sourceName);
  assert.equal(canConfirmHoldingImport(invalid), false);
  assert.throws(() => readHoldingImportPreview({ ...invalid, previewToken: 'unsafe-partial' }, sourceName));
  assert.throws(() => holdingImportAttempt(holdingImportPayload(sourceName, file()), invalid, 1000));
});

test('historical replay has no current rows, can fetch its receipt explicitly and preserves missing holdings', () => {
  const replay = readHoldingImportPreview({ ...preview(), rows: [], counts: { create: 0, update: 0, unchanged: 2 }, replayed: true,
    warnings: ['这份文件此前已确认，不恢复删除记录'] }, sourceName);
  assert.equal(canConfirmHoldingImport(replay), true); assert.deepEqual(replay.rows, []);
  assert.throws(() => readHoldingImportPreview({ ...replay, rows: [row()] }, sourceName));
  assert.throws(() => readHoldingImportPreview({ ...replay, counts: { create: 1, update: 0, unchanged: 2 } }, sourceName));
  const missing = readHoldingImportPreview({ ...preview(), preservedCount: 5, warnings: ['缺行保留'] }, sourceName);
  assert.equal(missing.preservedCount, 5); assert.equal(missing.counts.create, 1);
});

test('pending operation snapshots the exact file/source/token and cannot silently follow edited draft objects', () => {
  const original = file(), payload = holdingImportPayload(sourceName, original), result = readHoldingImportPreview(preview(), sourceName);
  const pending = holdingImportAttempt(payload, result, 1000);
  original.contentBase64 = 'YWJk'; payload.file.name = 'other.csv'; payload.sourceName = 'other'; result.previewToken = 'other';
  assert.deepEqual(pending.original.file, file()); assert.equal(pending.sourceName, sourceName);
  assert.equal(pending.previewToken, 'synthetic.preview.token'); assert.equal(pending.sourceDigest, sourceDigest);
});

test('unknown saves always require receipt lookup before retry or repreview; expiration never means not saved', () => {
  const pending = intent(); pending.uncertain = true;
  for (const now of [1000, 1000 + HOLDING_PREVIEW_MS, 999]) assert.deepEqual(holdingRecoveryChoices(pending, now), { retryOriginal: false, repreviewOriginal: false });
  pending.notFound = true;
  assert.deepEqual(holdingRecoveryChoices(pending, 1001), { retryOriginal: true, repreviewOriginal: true });
  assert.deepEqual(holdingRecoveryChoices(pending, 1000 + HOLDING_PREVIEW_MS), { retryOriginal: false, repreviewOriginal: true });
  pending.previewRejected = true;
  assert.deepEqual(holdingRecoveryChoices(pending, 1001), { retryOriginal: false, repreviewOriginal: true });
  assert.equal(pending.uncertain, true); assert.equal(pending.previewToken, 'synthetic.preview.token');
});

test('receipt lookup is exact source/file history and POST results do not invent server identity fields', () => {
  const expected = { sourceName, sourceDigest };
  assert.deepEqual(readInvestmentImportReceipt(receipt(), expected), { ...receipt(), ...expected });
  assert.deepEqual(readInvestmentImportReceipt(lookupReceipt(), expected, true), lookupReceipt());
  for (const bad of [{ sourceName: 'other' }, { sourceDigest: 'c'.repeat(64) }, { replayed: false }, { receiptId: 'x'.repeat(32) },
    { created: -1 }, { updated: 0.1 }, { unchanged: 301 }, { confirmedAt: '2026-02-30T04:00:00Z' }, { confirmedAt: '2026-09-17T24:00:00Z' }, { confirmedAt: '' }]) {
    assert.throws(() => readInvestmentImportReceipt({ ...lookupReceipt(), ...bad }, expected, true));
  }
  assert.throws(() => readInvestmentImportReceipt(receipt(), expected, true));
});

test('source options are bounded, unique and validate counts without exposing full investments', () => {
  const value = { investments: [{ privateValue: 'not retained' }], sources: [{ sourceName, revision: 1, updatedAt: receipt().confirmedAt, holdingCount: 3, deletedCount: 1000 }] };
  assert.deepEqual(readHoldingSources(value), value.sources);
  for (const change of [{ revision: 0 }, { holdingCount: 301 }, { deletedCount: -1 }, { updatedAt: '2026-02-30' }, { sourceName: 'x\ny' }]) {
    assert.throws(() => readHoldingSources({ ...value, sources: [{ ...value.sources[0], ...change }] }));
  }
  assert.throws(() => readHoldingSources({ sources: [...value.sources, ...value.sources] }));
});

test('downloads accept only fixed CSV filenames, expected source and reversible current-template header', () => {
  const header = 'holdingKey,name,institution,assetType,currency,quantity,cost,value,asOf,note,recordId';
  const current = { filename: 'investment-holdings-current.csv', csv: header + ',csvTextEncoding\n', rowCount: 0, warnings: ['保留文本保护列'], sourceName };
  assert.equal(readHoldingTemplate(current, 'current', sourceName).filename, current.filename);
  const sample = { filename: 'investment-holdings-template.csv', csv: header + '\nsynthetic\n', rowCount: 1, warnings: [] };
  assert.equal(readHoldingTemplate(sample, 'sample').csv, sample.csv);
  for (const change of [{ filename: 'data:text/html,bad' }, { filename: '../secret.csv' }, { csv: '<script>bad</script>' }, { sourceName: 'other' }, { rowCount: 301 }, { csv: header + '\n' }]) {
    assert.throws(() => readHoldingTemplate({ ...current, ...change }, 'current', sourceName));
  }
});

test('real read fence rejects late private data after offline/background invalidation', async () => {
  for (const boundary of ['offline', 'background', 'route']) {
    const me = session(), gate = deferred(), started = deferred(); let active = true;
    const fence = new PhotoReadFence(async () => me, me.user, photoSignature(me));
    const response = fence.read(async () => { started.resolve(); return gate.promise; }, () => active);
    await started.promise; active = false; fence.invalidate(); gate.resolve(preview());
    await assert.rejects(response, PhotoReadDiscarded, boundary);
  }
});

test('real read fence verifies member/family/auth version and CSRF on both sides of import response', async () => {
  for (const patch of [{ user: { ...session().user, id: 'member2' } }, { user: { ...session().user, householdId: 'other' } },
    { user: { ...session().user, auth_version: 2 } }, { user: { ...session().user, role: 'tv' } }, { csrf: 'new-session' }]) {
    const initial = session(); let me = initial;
    const fence = new PhotoReadFence(async () => me, initial.user, photoSignature(initial));
    await assert.rejects(fence.read(async () => { me = { ...initial, ...patch }; return lookupReceipt(); }, () => true), error => error instanceof PhotoReadDiscarded && error.message === 'identity');
  }
});

test('foreground same-identity recovery can read receipt without replaying a mutation', async () => {
  const me = session(); const fence = new PhotoReadFence(async () => me, me.user, photoSignature(me));
  let reads = 0, writes = 0;
  const result = await fence.read(async () => { reads++; return lookupReceipt(); }, () => true);
  assert.equal(readInvestmentImportReceipt(result, intent(), true).replayed, true);
  assert.equal(reads, 1); assert.equal(writes, 0);
});

test('late receipt 404 cannot release retry after real member, household, session or CSRF changes', async () => {
  for (const patch of [{ user: { ...session().user, id: 'member2' } }, { user: { ...session().user, householdId: 'other' } },
    { user: { ...session().user, auth_version: 2 } }, { user: { ...session().user, role: 'tv' } }, { csrf: 'new-session' }]) {
    const initial = session(), pending = intent(), started = deferred(), gate = deferred(); let me = initial;
    const fence = new PhotoReadFence(async () => me, initial.user, photoSignature(initial));
    const missing = Object.assign(new Error('synthetic private error'), { status: 404, code: 'investment_import_receipt_not_found' });
    const result = holdingCheckedRead(fence, async () => { started.resolve(); await gate.promise; throw missing; }, () => true);
    const checked = result.catch(error => { if (error === missing) pending.notFound = true; throw error; });
    await started.promise; me = { ...initial, ...patch }; gate.resolve();
    await assert.rejects(checked, error => error instanceof PhotoReadDiscarded && error.message === 'identity');
    assert.deepEqual(holdingRecoveryChoices(pending, 1001), { retryOriginal: false, repreviewOriginal: false });
  }
});

test('failed private reads are discarded after background or newer request generation, even when foreground returns', async () => {
  for (const boundary of ['background', 'new-generation']) {
    const me = session(), pending = intent(), started = deferred(), gate = deferred(); let generation = 1;
    const fence = new PhotoReadFence(async () => me, me.user, photoSignature(me));
    const missing = Object.assign(new Error('synthetic late 404'), { status: 404, code: 'investment_import_receipt_not_found' });
    const ticket = generation;
    const result = holdingCheckedRead(fence, async () => { started.resolve(); await gate.promise; throw missing; }, () => generation === ticket);
    await started.promise;
    if (boundary === 'background') fence.invalidate(); else generation++;
    gate.resolve(); await assert.rejects(result, PhotoReadDiscarded);
    assert.equal(pending.notFound, false); assert.equal(holdingRecoveryChoices(pending, 1001).retryOriginal, false);
  }
});

test('same-session failed reads verify identity after the load before exposing an error, without replaying load', async () => {
  const me = session(); let identityReads = 0, loads = 0;
  const fence = new PhotoReadFence(async () => { identityReads++; return me; }, me.user, photoSignature(me));
  const missing = Object.assign(new Error('synthetic 404'), { status: 404, code: 'investment_import_receipt_not_found' });
  await assert.rejects(holdingCheckedRead(fence, async () => { loads++; throw missing; }, () => true), error => error === missing);
  assert.equal(identityReads, 2); assert.equal(loads, 1);
  assert.deepEqual(await holdingCheckedRead(fence, async () => lookupReceipt(), () => true), lookupReceipt());
});
