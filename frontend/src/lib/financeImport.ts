export type ImportSource = 'generic' | 'alipay' | 'wechat' | 'taobao' | 'pinduoduo';
export type ImportKind = 'payments' | 'orders';
export type ImportFile = { name: string; contentBase64: string; encoding: 'auto' | 'utf-8' | 'gb18030'; sheet?: string };
export type ImportColumnField = 'date' | 'amount' | 'title' | 'currency';
export type ImportColumnMapping = ({ version: 1 } | { version: 2; flow: number | null })
  & { headerLine: number } & Record<ImportColumnField, number>;
export type ImportColumnSelection = { headerLine: number; lineKind: 'csv_lines' | 'worksheet_rows';
  columns: { index: number; label: string; columnLabel: string }[];
  suggestedMapping: Record<ImportColumnField, number | null>; mapping?: ImportColumnMapping };
export type ImportPayload = { source: ImportSource; kind: ImportKind; file: ImportFile; amountColumn?: number; inspectSheets?: boolean;
  inspectColumns?: boolean; headerLine?: number; mapping?: ImportColumnMapping };
export type ImportSourceLocation = { lineStart: number; lineEnd: number; lineKind: 'csv_lines' | 'worksheet_rows' };
export type ImportRow = { line: number; sourceLocation: ImportSourceLocation; title: string; date: string; amountCents: number; currency: string; flow: string; externalId?: string; duplicate: boolean; conflict: boolean; orderItems?: { title: string; variant?: string; quantityText?: string; listedAmountText?: string }[] };
export type ImportPreview = {
  rows: ImportRow[]; errors: { line: number; message: string }[]; errorCount: number; warnings: string[];
  newCount: number; duplicateCount: number; conflictCount: number; previewToken: string | null;
  requiresSheetSelection: boolean; requiresAmountSelection: boolean;
  requiresColumnSelection?: boolean; columnSelection?: ImportColumnSelection | null;
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
const columnFields: ImportColumnField[] = ['date', 'amount', 'title', 'currency'];
const columnIndex = (value: unknown): value is number => count(value) && Number(value) < 80;
const headerLine = (value: unknown): value is number => count(value) && Number(value) >= 1 && Number(value) <= 60;
function columnLabel(index: number) {
  let label = '', value = index + 1;
  while (value > 0) { --value; label = String.fromCharCode(65 + value % 26) + label; value = Math.floor(value / 26); }
  return label;
}
function readMapping(value: unknown): ImportColumnMapping {
  if (!object(value) || ![1, 2].includes(value.version)
    || Object.keys(value).sort().join(',') !== (value.version === 2
      ? 'amount,currency,date,flow,headerLine,title,version' : 'amount,currency,date,headerLine,title,version')
    || !headerLine(value.headerLine) || !columnFields.every(field => columnIndex(value[field]))
    || new Set(columnFields.map(field => value[field])).size !== 4) throw new Error('请选择四个不同的列，并核对表头所在行。');
  if (value.version === 2 && value.flow !== null && (!columnIndex(value.flow)
    || columnFields.some(field => value[field] === value.flow))) throw new Error('收支方向须使用其它一列，或选择自动识别。');
  const fields = { headerLine: value.headerLine, date: value.date, amount: value.amount, title: value.title, currency: value.currency };
  return value.version === 2 ? { version: 2, ...fields, flow: value.flow } : { version: 1, ...fields };
}
export function readImportColumnSelection(value: unknown): ImportColumnSelection {
  if (!object(value) || !headerLine(value.headerLine) || !['csv_lines', 'worksheet_rows'].includes(value.lineKind)
    || !Array.isArray(value.columns) || !value.columns.length || value.columns.length > 80
    || !object(value.suggestedMapping) || Object.keys(value.suggestedMapping).sort().join(',') !== 'amount,currency,date,title') throw new Error('表头无法核对，请重新读取。');
  const columns = value.columns.map((column: unknown) => {
    if (!object(column) || !columnIndex(column.index) || typeof column.label !== 'string' || Array.from(column.label).length > 200
      || column.columnLabel !== columnLabel(column.index)) throw new Error('列信息无法核对，请重新读取表头。');
    return { index: column.index, label: column.label, columnLabel: column.columnLabel as string };
  });
  const indices = new Set(columns.map(column => column.index));
  if (indices.size !== columns.length || !columnFields.every(field => value.suggestedMapping[field] === null
    || columnIndex(value.suggestedMapping[field]) && indices.has(value.suggestedMapping[field]))) throw new Error('建议列无法核对，请重新读取表头。');
  const suggestedMapping = Object.fromEntries(columnFields.map(field => [field, value.suggestedMapping[field]])) as ImportColumnSelection['suggestedMapping'];
  const mapping = value.mapping === undefined ? undefined : readMapping(value.mapping);
  if (mapping && (mapping.headerLine !== value.headerLine || !columnFields.every(field => indices.has(mapping[field]))
    || mapping.version === 2 && mapping.flow !== null && !indices.has(mapping.flow))) throw new Error('所选列与当前表头不一致，请重新读取。');
  return { headerLine: value.headerLine, lineKind: value.lineKind, columns, suggestedMapping, ...(mapping ? { mapping } : {}) };
}
export function inspectImportColumnsPayload(source: ImportSource, kind: ImportKind, file: ImportFile, line?: number): ImportPayload {
  if (source !== 'generic') throw new Error('手动指定列仅适用于通用表格。');
  if (line !== undefined && !headerLine(line)) throw new Error('表头所在行须为 1 至 60 的整数。');
  if (/\.xlsx$/i.test(file.name) && !file.sheet) throw new Error('请先选择工作表。');
  return { ...importPayload(source, kind, file), inspectColumns: true, ...(line === undefined ? {} : { headerLine: line }) };
}
export function manualImportPayload(source: ImportSource, kind: ImportKind, file: ImportFile, selection: ImportColumnSelection, value: unknown): ImportPayload {
  const safe = readImportColumnSelection(selection), mapping = readMapping(value);
  if (source !== 'generic' || /\.xlsx$/i.test(file.name) && !file.sheet) throw new Error('请使用通用表格，并先选择工作表。');
  if (mapping.version === 2 && kind !== 'payments') throw new Error('收支方向列仅适用于通用支付账单。');
  if (mapping.headerLine !== safe.headerLine || !columnFields.every(field => safe.columns.some(column => column.index === mapping[field]))
    || mapping.version === 2 && mapping.flow !== null && !safe.columns.some(column => column.index === mapping.flow)) throw new Error('所选列与当前表头不一致，请重新读取。');
  return { ...importPayload(source, kind, file), mapping };
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
    const location = row.sourceLocation;
    if (!object(location) || !count(location.lineStart) || location.lineStart < 1 || !count(location.lineEnd)
      || location.lineEnd < location.lineStart || !['csv_lines', 'worksheet_rows'].includes(location.lineKind)) throw new Error('原文件行号无法核对，请重新预览。');
    if (row.orderItems !== undefined && (!Array.isArray(row.orderItems) || row.orderItems.some((item: unknown) => !object(item)
      || typeof item.title !== 'string' || ['variant', 'quantityText', 'listedAmountText'].some(key => item[key] !== undefined && typeof item[key] !== 'string')))) throw new Error('商品明细无法核对，请重新预览。');
  }
  if (value.errors.some((row: unknown) => !object(row) || !count(row.line) || typeof row.message !== 'string')) throw new Error('文件错误信息无法读取。');
  if (value.requiresSheetSelection && (!Array.isArray(value.fileInfo?.sheets) || !value.fileInfo.sheets.every((v: unknown) => typeof v === 'string'))) throw new Error('工作表名单无法读取。');
  if (value.amountSelection && (!Array.isArray(value.amountSelection.columns)
    || !value.amountSelection.columns.every((v: unknown) => object(v) && count(v.index) && typeof v.label === 'string' && typeof v.columnLabel === 'string'))) throw new Error('金额列名单无法读取。');
  const requiresColumns = value.requiresColumnSelection === undefined ? false : value.requiresColumnSelection;
  if (typeof requiresColumns !== 'boolean' || (value.requiresColumnSelection === undefined) !== (value.columnSelection === undefined)) throw new Error('字段选择状态无法核对。');
  const selection = value.columnSelection == null ? null : readImportColumnSelection(value.columnSelection);
  if (requiresColumns && (!selection || selection.mapping || value.previewToken !== null || value.rows.length || value.errors.length || value.errorCount
    || value.requiresSheetSelection || value.requiresAmountSelection)) throw new Error('读取表头不能作为导入预览。');
  if (selection && !requiresColumns && (!selection.mapping || value.requiresSheetSelection || value.requiresAmountSelection || value.amountSelection != null)) throw new Error('映射预览与所选列不一致。');
  return { ...value, requiresColumnSelection: requiresColumns, columnSelection: selection } as ImportPreview;
}
export function canConfirmImport(preview: ImportPreview | null): preview is ImportPreview {
  return !!preview && !preview.requiresSheetSelection && !preview.requiresAmountSelection && !preview.requiresColumnSelection && preview.errorCount === 0
    && preview.rows.length > 0 && !!preview.previewToken;
}
export function importSourceLabel(location: ImportSourceLocation) {
  const range = location.lineStart === location.lineEnd ? String(location.lineStart) : `${location.lineStart}–${location.lineEnd}`;
  return `${location.lineKind === 'worksheet_rows' ? '工作表' : '原文件'}第 ${range} 行`;
}
// A later rejection cannot prove an earlier request with a lost response did not commit.
export function importRejectionIsDefinite(status: number | undefined, wasUncertain: boolean) {
  return !wasUncertain && status !== undefined && [400, 413, 422].includes(status);
}
export function confirmImportPayload(payload: ImportPayload, preview: ImportPreview, requestId: string) {
  if (!canConfirmImport(preview) || payload.inspectSheets || 'inspectColumns' in payload || 'headerLine' in payload || !isImportRequestId(requestId)) throw new Error('请重新核对文件预览后再保存。');
  if (payload.mapping) {
    const mapping = readMapping(payload.mapping), shown = preview.columnSelection && readImportColumnSelection(preview.columnSelection).mapping;
    if (payload.source !== 'generic' || mapping.version === 2 && payload.kind !== 'payments'
      || 'amountColumn' in payload || !shown || JSON.stringify(mapping) !== JSON.stringify(shown)) throw new Error('所选列已变化，请重新预览。');
  } else if (preview.columnSelection) throw new Error('请重新核对所选列后再保存。');
  return { ...payload, file: { ...payload.file }, ...(payload.mapping ? { mapping: readMapping(payload.mapping) } : {}), previewToken: preview.previewToken!, requestId };
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
