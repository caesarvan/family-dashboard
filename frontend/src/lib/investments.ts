export type InvestmentRecord = {
  id: string; revision: number; name: string; institution: string; assetType: string;
  currency: string; quantity: string | null; costCents: number; valueCents: number | null;
  asOf: string; note: string; valuationSource: 'manual' | 'file_import'; visibility: 'private';
};
export type Investment = InvestmentRecord & { updatedAt: string; source: null | { sourceName: string; holdingKey: string } };
export type InvestmentSource = { sourceName: string; revision: number; updatedAt: string; holdingCount: number; deletedCount: number };
export type InvestmentList = { investments: Investment[]; sources: InvestmentSource[] };
export type InvestmentDraft = { name: string; institution: string; assetType: string; currency: string; quantity: string; cost: string; value: string; asOf: string; note: string };
export type InvestmentPayload = InvestmentDraft & { revision?: number; requestId: string };
export type InvestmentIntent = { requestId: string; kind: 'create' | 'update' | 'delete'; recordId?: string; path: string; method: 'POST' | 'PATCH' | 'DELETE'; payload: InvestmentPayload | { revision: number; requestId: string } };
export type InvestmentReceipt = { requestId: string; kind: InvestmentIntent['kind']; recordId: string; result: InvestmentRecord | { deleted: true }; completedAt: string };
export type InvestmentTotals = { currency: string; count: number; knownCount: number; unknownCount: number; costCents: bigint; knownCostCents: bigint; knownValueCents: bigint; knownGainCents: bigint };
const invalid = (): never => { throw new Error('持仓数据无法安全核对，请重新读取。'); };
const object = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : invalid();
const text = (v: unknown, max: number, required = false): string => typeof v === 'string' && v.length <= max && (!required || v.trim().length > 0) ? v : invalid();
const int = (v: unknown, min = 0): number => typeof v === 'number' && Number.isSafeInteger(v) && v >= min ? v : invalid();
const rows = (v: unknown, max: number): unknown[] => Array.isArray(v) && v.length <= max ? v : invalid();
const code = (v: unknown): string => typeof v === 'string' && /^[A-Z]{3}$/.test(v) ? v : invalid();
export const isInvestmentId = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{24}$/.test(v);
export const isInvestmentRequestId = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
const id = (v: unknown): string => isInvestmentId(v) ? v : invalid();
const requestId = (v: unknown): string => isInvestmentRequestId(v) ? v : invalid();

export function validInvestmentDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const d = new Date(value + 'T00:00:00Z');
  return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === value;
}
export function investmentDecimal(value: number | bigint): string {
  if (typeof value !== 'bigint' && (typeof value !== 'number' || !Number.isSafeInteger(value))) invalid();
  const n = BigInt(value), absolute = n < 0n ? -n : n;
  return `${n < 0n ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`;
}
export function formatInvestmentCents(value: number | bigint, currency: string): string {
  code(currency); const [whole, fraction] = investmentDecimal(value).split('.');
  return `${currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction}`;
}
export function investmentAmount(value: string): string {
  if (typeof value !== 'string') throw new Error('金额须为十进制文本。');
  const input = value.trim();
  if (!/^(0|[1-9]\d{0,12})(?:\.\d{1,2})?$/.test(input)) throw new Error('金额须为非负数，最多两位小数，不含逗号或货币符号。');
  const [whole, fraction = ''] = input.split('.');
  if (BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0')) > 100000000000000n) throw new Error('金额超出允许范围。');
  return `${whole}.${fraction.padEnd(2, '0')}`;
}
export function investmentQuantity(value: string): string {
  if (typeof value !== 'string') throw new Error('数量须为文本。');
  const result = value.trim();
  if (result && !/^\d{1,15}(?:\.\d{1,8})?$/.test(result)) throw new Error('数量最多 15 位整数、8 位小数，或留空。');
  return result;
}
export function readInvestmentRecord(value: unknown): InvestmentRecord {
  const v = object(value);
  const quantity = v.quantity === null ? null : text(v.quantity, 24);
  if (quantity !== null && (!quantity || investmentQuantity(quantity) !== quantity)) invalid();
  if (!validInvestmentDate(v.asOf)) invalid();
  return {
    id: id(v.id), revision: int(v.revision, 1), name: text(v.name, 120, true), institution: text(v.institution, 120, true), assetType: text(v.assetType, 60, true),
    currency: code(v.currency), quantity, costCents: int(v.costCents), valueCents: v.valueCents === null ? null : int(v.valueCents),
    asOf: v.asOf as string, note: text(v.note, 1000), valuationSource: v.valuationSource === 'manual' || v.valuationSource === 'file_import' ? v.valuationSource : invalid(),
    visibility: v.visibility === 'private' ? v.visibility : invalid(),
  };
}
export function readInvestmentList(value: unknown): InvestmentList {
  const v = object(value);
  const investments = rows(v.investments, 300).map(item => {
    const raw = object(item), core = readInvestmentRecord(raw);
    const source = raw.source === null ? null : object(raw.source);
    return { ...core, updatedAt: text(raw.updatedAt, 100, true), source: source === null ? null : { sourceName: text(source.sourceName, 80, true), holdingKey: text(source.holdingKey, 120, true) } };
  });
  const sources = rows(v.sources, 300).map(item => {
    const s = object(item);
    return { sourceName: text(s.sourceName, 80, true), revision: int(s.revision, 1), updatedAt: text(s.updatedAt, 100, true), holdingCount: int(s.holdingCount), deletedCount: int(s.deletedCount) };
  });
  if (new Set(investments.map(v => v.id)).size !== investments.length || new Set(sources.map(v => v.sourceName)).size !== sources.length) invalid();
  return { investments, sources };
}
export function filterInvestments(values: Investment[], filters: { name: string; institution: string; currency: string }): Investment[] {
  const name = filters.name.trim().toLocaleLowerCase(), institution = filters.institution.trim().toLocaleLowerCase(), currency = filters.currency.trim().toUpperCase();
  return values.filter(v => (!name || v.name.toLocaleLowerCase().includes(name)) && (!institution || v.institution.toLocaleLowerCase().includes(institution)) && (!currency || v.currency === currency));
}
export function sumInvestments(values: InvestmentRecord[]): InvestmentTotals[] {
  const totals = new Map<string, InvestmentTotals>();
  for (const raw of values) {
    const item = readInvestmentRecord(raw);
    const result = totals.get(item.currency) || { currency: item.currency, count: 0, knownCount: 0, unknownCount: 0, costCents: 0n, knownCostCents: 0n, knownValueCents: 0n, knownGainCents: 0n };
    result.count++; result.costCents += BigInt(item.costCents);
    if (item.valueCents === null) result.unknownCount++;
    else { result.knownCount++; result.knownCostCents += BigInt(item.costCents); result.knownValueCents += BigInt(item.valueCents); result.knownGainCents += BigInt(item.valueCents) - BigInt(item.costCents); }
    totals.set(item.currency, result);
  }
  return [...totals.values()].sort((a, b) => a.currency.localeCompare(b.currency));
}
export function investmentDraft(row?: InvestmentRecord): InvestmentDraft {
  return row ? { name: row.name, institution: row.institution, assetType: row.assetType, currency: row.currency, quantity: row.quantity ?? '', cost: investmentDecimal(row.costCents), value: row.valueCents === null ? '' : investmentDecimal(row.valueCents), asOf: row.asOf, note: row.note }
    : { name: '', institution: '', assetType: '', currency: 'CNY', quantity: '', cost: '', value: '', asOf: new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()), note: '' };
}
function input(value: string, label: string, max: number, required = false): string {
  if (typeof value !== 'string' || value.trim().length > max || required && !value.trim() || value.includes('\u0000')) throw new Error(`${label}${required ? '不能为空，' : ''}请检查长度和不可见字符。`);
  return value.trim();
}
export function investmentPayload(draft: InvestmentDraft, operationId: string, revision?: number): InvestmentPayload {
  requestId(operationId); if (revision !== undefined) int(revision, 1);
  const currency = input(draft.currency, '币种', 3, true).toUpperCase();
  if (!/^[A-Z]{3}$/.test(currency)) throw new Error('币种请填写 CNY、USD 等三位字母代码。');
  const asOf = draft.asOf.trim(); if (!validInvestmentDate(asOf)) throw new Error('核对日期须为存在的 YYYY-MM-DD 日期。');
  return { name: input(draft.name, '名称', 120, true), institution: input(draft.institution, '机构', 120, true), assetType: input(draft.assetType, '资产类型', 60, true), currency,
    quantity: investmentQuantity(draft.quantity), cost: investmentAmount(draft.cost), value: draft.value.trim() === '' ? '' : investmentAmount(draft.value), asOf, note: input(draft.note, '备注', 1000),
    requestId: operationId, ...(revision === undefined ? {} : { revision }),
  };
}
export function newInvestmentRequestId(): string {
  if (!globalThis.crypto?.getRandomValues) throw new Error('当前浏览器无法生成安全操作编号，请使用 HTTPS 页面。');
  return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), v => v.toString(16).padStart(2, '0')).join('');
}
export function investmentIntent(kind: 'create' | 'update', draft: InvestmentDraft, operationId: string, original?: InvestmentRecord): InvestmentIntent;
export function investmentIntent(kind: 'delete', draft: null, operationId: string, original: InvestmentRecord): InvestmentIntent;
export function investmentIntent(kind: InvestmentIntent['kind'], draft: InvestmentDraft | null, operationId: string, original?: InvestmentRecord): InvestmentIntent {
  requestId(operationId);
  if (kind !== 'create' && !original) invalid();
  const recordId = original ? id(original.id) : undefined;
  const payload = kind === 'delete' ? { revision: int(original!.revision, 1), requestId: operationId } : investmentPayload(draft!, operationId, kind === 'update' ? original!.revision : undefined);
  return { kind, requestId: operationId, recordId, method: kind === 'create' ? 'POST' : kind === 'update' ? 'PATCH' : 'DELETE', path: '/finance-hub/investments' + (kind === 'create' ? '' : '/' + recordId), payload };
}
export function readInvestmentReceipt(value: unknown, intent: InvestmentIntent): InvestmentReceipt {
  const v = object(value);
  if (requestId(v.requestId) !== intent.requestId || v.kind !== intent.kind || intent.recordId && v.recordId !== intent.recordId) invalid();
  const recordId = id(v.recordId);
  const result = v.kind === 'delete' ? object(v.result).deleted === true ? { deleted: true as const } : invalid() : readInvestmentRecord(v.result);
  if ('id' in result && result.id !== recordId) invalid();
  return { requestId: intent.requestId, kind: intent.kind, recordId, result, completedAt: text(v.completedAt, 100, true) };
}
export function readInvestmentAck(value: unknown, intent: InvestmentIntent): void {
  const v = object(value);
  if (requestId(v.requestId) !== intent.requestId || typeof v.replayed !== 'boolean') invalid();
  if (intent.kind === 'delete') { if (v.deleted !== true) invalid(); }
  else { const row = readInvestmentRecord(v); if (intent.recordId && row.id !== intent.recordId) invalid(); }
}
