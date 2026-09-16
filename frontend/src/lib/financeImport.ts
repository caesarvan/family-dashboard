export type ImportSource = 'generic' | 'alipay' | 'wechat' | 'taobao' | 'pinduoduo';
export type ImportKind = 'payments' | 'orders';
export type ImportFile = { name: string; contentBase64: string; encoding: 'auto' | 'utf-8' | 'gb18030'; sheet?: string };
export type ImportPayload = { source: ImportSource; kind: ImportKind; file: ImportFile; amountColumn?: number; inspectSheets?: boolean };
export type ImportRow = { line: number; title: string; date: string; amountCents: number; currency: string; flow: string; externalId?: string; duplicate: boolean; conflict: boolean; orderItems?: { title: string; variant?: string; quantity?: string; amount?: string }[] };
export type ImportPreview = {
  rows: ImportRow[]; errors: { line: number; message: string }[]; errorCount: number; warnings: string[];
  newCount: number; duplicateCount: number; conflictCount: number; previewToken: string | null;
  requiresSheetSelection: boolean; requiresAmountSelection: boolean;
  fileInfo?: { format?: string; encoding?: string; sheet?: string; sheets?: string[] };
  amountSelection?: { selectedIndex: number | null; columns: { index: number; label: string; columnLabel: string }[] } | null;
};
export type FinanceImportReceipt = {
  requestId: string; receiptId: string; batchId: string | null; imported: number; duplicates: number; conflicts: number;
  confirmedAt: string; resultMonths: { month: string; recordCount: number }[]; note?: string; replayed: boolean;
};
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const object = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
export const isImportRequestId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32,64}$/.test(value);
export function newImportRequestId() {
  if (!globalThis.crypto?.getRandomValues) throw new Error('请通过安全连接打开看板后再导入。');
  return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}
export function importPayload(source: ImportSource, kind: ImportKind, file: ImportFile, amountColumn?: number, inspectSheets = false): ImportPayload {
  if (!file.name || !file.contentBase64) throw new Error('请先选择账单文件。');
  if (inspectSheets && amountColumn !== undefined) throw new Error('请先选工作表，再选择金额列。');
  if (amountColumn !== undefined && (!count(amountColumn) || amountColumn >= 80)) throw new Error('请重新选择入账金额列。');
  return { source, kind, file: { ...file }, ...(amountColumn === undefined ? {} : { amountColumn }), ...(inspectSheets ? { inspectSheets: true } : {}) };
}
export function readImportPreview(value: unknown): ImportPreview {
  if (!object(value) || !Array.isArray(value.rows) || value.rows.length > 5000 || !Array.isArray(value.errors)
    || !count(value.errorCount) || !Array.isArray(value.warnings) || !value.warnings.every((v: unknown) => typeof v === 'string')
    || !['newCount', 'duplicateCount', 'conflictCount'].every(key => count(value[key]))
    || typeof value.requiresSheetSelection !== 'boolean' || typeof value.requiresAmountSelection !== 'boolean'
    || !(value.previewToken === null || typeof value.previewToken === 'string')) throw new Error('文件预览无法核对，请重新预览。');
  for (const row of value.rows) {
    if (!object(row) || !count(row.line) || typeof row.title !== 'string' || typeof row.date !== 'string'
      || !count(row.amountCents) || typeof row.currency !== 'string' || !/^[A-Z]{3}$/.test(row.currency)
      || typeof row.flow !== 'string' || typeof row.duplicate !== 'boolean' || typeof row.conflict !== 'boolean') throw new Error('预览记录不完整，请重新预览。');
    if (row.orderItems !== undefined && (!Array.isArray(row.orderItems) || row.orderItems.some((item: unknown) => !object(item)
      || typeof item.title !== 'string' || ['variant', 'quantity'].some(key => item[key] !== undefined && typeof item[key] !== 'string')))) throw new Error('商品明细无法核对，请重新预览。');
  }
  if (value.errors.some((row: unknown) => !object(row) || !count(row.line) || typeof row.message !== 'string')) throw new Error('文件错误信息无法读取。');
  if (value.requiresSheetSelection && (!Array.isArray(value.fileInfo?.sheets) || !value.fileInfo.sheets.every((v: unknown) => typeof v === 'string'))) throw new Error('工作表名单无法读取。');
  if (value.amountSelection && (!Array.isArray(value.amountSelection.columns)
    || !value.amountSelection.columns.every((v: unknown) => object(v) && count(v.index) && typeof v.label === 'string' && typeof v.columnLabel === 'string'))) throw new Error('金额列名单无法读取。');
  return value as ImportPreview;
}
export function canConfirmImport(preview: ImportPreview | null): preview is ImportPreview {
  return !!preview && !preview.requiresSheetSelection && !preview.requiresAmountSelection && preview.errorCount === 0
    && preview.rows.length > 0 && !!preview.previewToken;
}
export function confirmImportPayload(payload: ImportPayload, preview: ImportPreview, requestId: string) {
  if (!canConfirmImport(preview) || payload.inspectSheets || !isImportRequestId(requestId)) throw new Error('请重新核对文件预览后再保存。');
  return { ...payload, file: { ...payload.file }, previewToken: preview.previewToken!, requestId };
}
export function readImportReceipt(value: unknown, expected: string): FinanceImportReceipt {
  if (!object(value) || !isImportRequestId(expected) || value.requestId !== expected
    || typeof value.receiptId !== 'string' || !/^[a-f0-9]{64}$/.test(value.receiptId)
    || !(value.batchId === null || typeof value.batchId === 'string' && /^[a-f0-9]{24}$/.test(value.batchId))
    || !['imported', 'duplicates', 'conflicts'].every(key => count(value[key]))
    || typeof value.confirmedAt !== 'string' || !Number.isFinite(Date.parse(value.confirmedAt)) || typeof value.replayed !== 'boolean'
    || !Array.isArray(value.resultMonths) || value.resultMonths.some((row: unknown) => !object(row)
      || typeof row.month !== 'string' || !/^\d{4}-(0[1-9]|1[0-2])$/.test(row.month) || !count(row.recordCount))
    || new Set(value.resultMonths.map((row: { month: string }) => row.month)).size !== value.resultMonths.length) throw new Error('保存回执无法核对，请按原请求核对保存结果。');
  return value as FinanceImportReceipt;
}
// Display only: the server remains the authority for all financial arithmetic.
export function importAmount(cents: number, currency: string) {
  if (!count(cents)) return '金额待核对';
  const value = BigInt(cents), whole = (value / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${currency} ${whole}.${(value % 100n).toString().padStart(2, '0')}`;
}
