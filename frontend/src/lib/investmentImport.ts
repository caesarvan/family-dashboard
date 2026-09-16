// Decode the existing standard holdings-template API. Financial calculations remain on the server.
export type HoldingFile = { name: string; contentBase64: string; encoding: 'auto' | 'utf-8' | 'gb18030'; sheet?: string };
export type HoldingImportPayload = { sourceName: string; file: HoldingFile; inspectSheets?: true };
export type ImportHolding = {
  name: string; institution: string; assetType: string; currency: string; quantity: string | null;
  costCents: number; valueCents: number | null; asOf: string; note: string;
  visibility: 'private'; valuationSource: 'manual' | 'file_import'; id?: string; revision?: number;
};
export type HoldingImportRow = { line: number; holdingKey: string; action: 'create' | 'update' | 'unchanged'; before: ImportHolding | null; after: ImportHolding; warnings: string[] };
export type HoldingImportPreview = {
  sourceName: string; sourceDigest: string | null; requiresSheetSelection: boolean; replayed: boolean;
  fileInfo: { name: string; format: 'csv' | 'xlsx'; encoding: string; sheet: string | null; sheets: string[] };
  rows: HoldingImportRow[]; counts: { create: number; update: number; unchanged: number }; preservedCount: number;
  warnings: string[]; errors: { line: number; message: string }[]; errorCount: number; previewToken: string | null;
};
export type InvestmentImportReceipt = { created: number; updated: number; unchanged: number; replayed: boolean; receiptId: string; confirmedAt: string; sourceName: string; sourceDigest: string };
export type HoldingSource = { sourceName: string; revision: number; updatedAt: string; holdingCount: number; deletedCount: number };
export type HoldingImportAttempt = {
  sourceName: string; sourceDigest: string; previewToken: string; original: HoldingImportPayload;
  previewReceivedAt: number; uncertain: boolean; notFound: boolean; previewRejected: boolean;
};
export const HOLDING_FILE_LIMIT = 2 * 1024 * 1024;
export const HOLDING_PREVIEW_MS = 15 * 60 * 1000;
// A failed private response needs the same post-request identity check as a success.
// Carry the rejection through the existing fence before exposing its error or retry state.
export async function holdingCheckedRead<T>(
  fence: { read<R>(load: () => Promise<R>, current: () => boolean): Promise<R> },
  load: () => Promise<T>, current: () => boolean,
): Promise<T> {
  const result = await fence.read(async (): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> => {
    try { return { ok: true, value: await load() }; } catch (error) { return { ok: false, error }; }
  }, current);
  if (result.ok === false) throw result.error;
  return result.value;
}
const object = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
const count = (v: unknown, max = Number.MAX_SAFE_INTEGER): v is number => Number.isSafeInteger(v) && Number(v) >= 0 && Number(v) <= max;
const text = (v: unknown, max: number, empty = false): v is string => typeof v === 'string' && (empty || !!v.trim()) && [...v].length <= max && !/[\u0000\uD800-\uDFFF]/u.test(v);
const digest = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const fail = (message = '持仓预览无法核对，请重新读取。'): never => { throw new Error(message); };
const ensure = (valid: unknown, message?: string): void => { if (!valid) fail(message); };
const lines = (v: unknown, max = 1000): string[] => {
  ensure(Array.isArray(v) && v.length <= max && v.every(x => text(x, 4000, true)));
  return [...v as string[]];
};
export function holdingSourceName(value: unknown): string {
  ensure(text(value, 80) && !/[\u0000-\u001f]/.test(value), '来源名称需为 1–80 个字，不含控制字符。');
  return (value as string).trim();
}
function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}
function timestamp(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 64 && validDate(value.slice(0, 10)) && /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value) && Number.isFinite(Date.parse(value));
}
export function readImportHolding(value: unknown, existing = false): ImportHolding {
  ensure(object(value)); const v = value as Record<string, any>;
  ensure(text(v.name, 120) && text(v.institution, 120) && text(v.assetType, 60) && text(v.note, 1000, true)
    && typeof v.currency === 'string' && /^[A-Z]{3}$/.test(v.currency)
    && (v.quantity === null || typeof v.quantity === 'string' && /^\d{1,15}(?:\.\d{1,8})?$/.test(v.quantity))
    && count(v.costCents, 100_000_000_000_000) && (v.valueCents === null || count(v.valueCents, 100_000_000_000_000))
    && validDate(v.asOf) && v.visibility === 'private' && ['manual', 'file_import'].includes(v.valuationSource));
  if (existing) ensure(typeof v.id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(v.id) && count(v.revision) && v.revision >= 1);
  return { name: v.name, institution: v.institution, assetType: v.assetType, currency: v.currency, quantity: v.quantity,
    costCents: v.costCents, valueCents: v.valueCents, asOf: v.asOf, note: v.note, visibility: 'private', valuationSource: v.valuationSource,
    ...(existing ? { id: v.id, revision: v.revision } : {}) };
}
export function holdingImportPayload(sourceName: unknown, file: HoldingFile): HoldingImportPayload {
  const source = holdingSourceName(sourceName);
  ensure(object(file) && text(file.name, 200) && !/[\\/\u0000-\u001f]/.test(file.name) && /\.(csv|txt|xlsx)$/i.test(file.name), '请选择 CSV、TXT 或无宏 XLSX 文件。');
  ensure(typeof file.contentBase64 === 'string' && file.contentBase64.length > 0 && file.contentBase64.length <= Math.ceil(HOLDING_FILE_LIMIT / 3) * 4
    && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(file.contentBase64), '文件为空、编码无效或超过 2 MiB。');
  const bytes = file.contentBase64.length / 4 * 3 - (file.contentBase64.endsWith('==') ? 2 : file.contentBase64.endsWith('=') ? 1 : 0);
  ensure(bytes > 0 && bytes <= HOLDING_FILE_LIMIT && ['auto', 'utf-8', 'gb18030'].includes(file.encoding), '文件大小或编码无法核对。');
  ensure(file.sheet === undefined || text(file.sheet, 100), '请选择有效工作表。');
  ensure(/\.xlsx$/i.test(file.name) || file.sheet === undefined, 'CSV 不需要工作表。');
  return { sourceName: source, file: { ...file }, ...(/\.xlsx$/i.test(file.name) && !file.sheet ? { inspectSheets: true as const } : {}) };
}
export function readHoldingImportPreview(value: unknown, expectedSource: string): HoldingImportPreview {
  ensure(object(value)); const v = value as Record<string, any>;
  ensure(v.sourceName === holdingSourceName(expectedSource) && typeof v.requiresSheetSelection === 'boolean'
    && (v.replayed === undefined || typeof v.replayed === 'boolean') && object(v.counts)
    && ['create', 'update', 'unchanged'].every(k => count(v.counts[k], 300)) && count(v.preservedCount, 300)
    && Array.isArray(v.rows) && v.rows.length <= 300 && Array.isArray(v.errors) && v.errors.length <= 303
    && count(v.errorCount, 303) && v.errorCount === v.errors.length
    && (v.previewToken === null || text(v.previewToken, 2048)));
  const info = v.fileInfo;
  ensure(object(info) && text(info.name, 200) && ['csv', 'xlsx'].includes(info.format) && text(info.encoding, 100)
    && (info.sheet === null || text(info.sheet, 100)) && Array.isArray(info.sheets) && info.sheets.length <= 20
    && info.sheets.every((s: unknown) => text(s, 100)) && new Set(info.sheets).size === info.sheets.length);
  const rows: HoldingImportRow[] = v.rows.map((row: unknown) => {
    ensure(object(row)); const r = row as Record<string, any>;
    ensure(count(r.line, HOLDING_FILE_LIMIT + 1) && r.line >= 1 && text(r.holdingKey, 120) && !/[\u0000-\u001f]/.test(r.holdingKey)
      && ['create', 'update', 'unchanged'].includes(r.action) && (r.action === 'create' ? r.before === null : object(r.before)));
    return { line: r.line, holdingKey: r.holdingKey, action: r.action, before: r.before === null ? null : readImportHolding(r.before, true),
      after: readImportHolding(r.after), warnings: lines(r.warnings) };
  });
  ensure(new Set(rows.map(r => r.holdingKey)).size === rows.length);
  const errors = v.errors.map((r: any) => { ensure(object(r) && count(r.line, HOLDING_FILE_LIMIT + 1) && text(r.message, 4000)); return { line: r.line, message: r.message }; });
  const replayed = v.replayed === true;
  if (v.requiresSheetSelection) ensure(info.format === 'xlsx' && info.sheet === null && info.sheets.length > 0 && !rows.length && !errors.length
    && !replayed && !v.preservedCount && !v.counts.create && !v.counts.update && !v.counts.unchanged && v.previewToken === null);
  else {
    ensure(digest(v.sourceDigest));
    if (replayed) ensure(!rows.length && !errors.length && !v.counts.create && !v.counts.update && v.counts.unchanged > 0);
    else ensure(['create', 'update', 'unchanged'].every(k => rows.filter(r => r.action === k).length === v.counts[k]));
  }
  if (errors.length) ensure(v.previewToken === null);
  return { sourceName: v.sourceName, sourceDigest: v.sourceDigest ?? null, requiresSheetSelection: v.requiresSheetSelection, replayed,
    fileInfo: { name: info.name, format: info.format, encoding: info.encoding, sheet: info.sheet, sheets: [...info.sheets] }, rows,
    counts: { ...v.counts }, preservedCount: v.preservedCount, warnings: lines(v.warnings), errors, errorCount: v.errorCount, previewToken: v.previewToken };
}
export function canConfirmHoldingImport(preview: HoldingImportPreview | null): preview is HoldingImportPreview {
  return !!preview && !preview.requiresSheetSelection && !preview.errorCount && !!preview.previewToken && !!preview.sourceDigest
    && (preview.rows.length > 0 || preview.replayed && preview.counts.unchanged > 0);
}
export function holdingImportAttempt(payload: HoldingImportPayload, preview: HoldingImportPreview, previewReceivedAt: number): HoldingImportAttempt {
  ensure(canConfirmHoldingImport(preview) && payload.sourceName === preview.sourceName && !payload.inspectSheets
    && preview.fileInfo.name === payload.file.name && preview.fileInfo.sheet === (payload.file.sheet || null)
    && Number.isSafeInteger(previewReceivedAt) && previewReceivedAt >= 0, '请重新核对文件预览后再确认。');
  return { sourceName: preview.sourceName, sourceDigest: preview.sourceDigest!, previewToken: preview.previewToken!,
    original: { sourceName: payload.sourceName, file: { ...payload.file } }, previewReceivedAt, uncertain: false, notFound: false, previewRejected: false };
}
export function holdingRecoveryChoices(intent: HoldingImportAttempt, now = Date.now()) {
  const fresh = Number.isFinite(now) && now >= intent.previewReceivedAt && now - intent.previewReceivedAt < HOLDING_PREVIEW_MS;
  return { retryOriginal: intent.notFound && fresh && !intent.previewRejected, repreviewOriginal: intent.notFound };
}
export function holdingReceiptPath(source: string, sourceDigest: string) {
  ensure(digest(sourceDigest), '保存标识无法核对。');
  return '/finance-hub/investments/imports/receipts?sourceName=' + encodeURIComponent(holdingSourceName(source)) + '&sourceDigest=' + sourceDigest;
}
export function readInvestmentImportReceipt(value: unknown, expected: { sourceName: string; sourceDigest: string }, fromLookup = false): InvestmentImportReceipt {
  ensure(object(value)); const v = value as Record<string, any>;
  ensure(digest(expected.sourceDigest) && expected.sourceName === holdingSourceName(expected.sourceName)
    && ['created', 'updated', 'unchanged'].every(k => count(v[k], 300)) && v.created + v.updated + v.unchanged <= 300
    && typeof v.replayed === 'boolean' && typeof v.receiptId === 'string' && /^[a-f0-9]{32}$/.test(v.receiptId) && timestamp(v.confirmedAt)
    && (!fromLookup || v.replayed === true && v.sourceName === expected.sourceName && v.sourceDigest === expected.sourceDigest)
    && (v.sourceName === undefined || v.sourceName === expected.sourceName) && (v.sourceDigest === undefined || v.sourceDigest === expected.sourceDigest),
  '保存回执无法核对，请继续读取本次结果。');
  return { created: v.created, updated: v.updated, unchanged: v.unchanged, replayed: v.replayed, receiptId: v.receiptId,
    confirmedAt: v.confirmedAt, sourceName: expected.sourceName, sourceDigest: expected.sourceDigest };
}
export function readHoldingSources(value: unknown): HoldingSource[] {
  ensure(object(value) && Array.isArray(value.sources) && value.sources.length <= 300, '来源列表无法核对，请重新读取。');
  const sources = (value as Record<string, any>).sources.map((r: unknown): HoldingSource => {
    ensure(object(r)); const v = r as Record<string, any>;
    ensure(v.sourceName === holdingSourceName(v.sourceName) && count(v.revision) && v.revision > 0
      && timestamp(v.updatedAt) && count(v.holdingCount, 300) && count(v.deletedCount));
    return { sourceName: v.sourceName, revision: v.revision, updatedAt: v.updatedAt, holdingCount: v.holdingCount, deletedCount: v.deletedCount };
  });
  ensure(new Set(sources.map((r: HoldingSource) => r.sourceName)).size === sources.length);
  return sources;
}
export function readHoldingTemplate(value: unknown, mode: 'sample' | 'current', sourceName?: string) {
  ensure(object(value)); const v = value as Record<string, any>;
  const filename = mode === 'sample' ? 'investment-holdings-template.csv' : 'investment-holdings-current.csv';
  const header = 'holdingKey,name,institution,assetType,currency,quantity,cost,value,asOf,note,recordId' + (mode === 'current' ? ',csvTextEncoding' : '');
  ensure(v.filename === filename && typeof v.csv === 'string' && new TextEncoder().encode(v.csv).byteLength <= HOLDING_FILE_LIMIT
    && v.csv.startsWith(header + '\n') && count(v.rowCount, 300)
    && (mode === 'sample' ? v.rowCount === 1 : v.sourceName === holdingSourceName(sourceName)), '整理表下载内容无法核对。');
  return { filename, csv: v.csv, rowCount: v.rowCount as number, warnings: lines(v.warnings) };
}
export function holdingMoney(cents: number | null, currency: string) {
  if (cents === null) return '现值未知';
  if (!count(cents, 100_000_000_000_000) || !/^[A-Z]{3}$/.test(currency)) return '金额待核对';
  const number = BigInt(cents);
  return `${currency} ${(number / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${(number % 100n).toString().padStart(2, '0')}`;
}
