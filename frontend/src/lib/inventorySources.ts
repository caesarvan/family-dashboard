import { isInventoryId, validateAcquisition, validateItem, validateResult, type Acquisition, type InventoryItem, type InventoryResult } from './inventory.ts';

export type SourceOrder = { id: string; revision: number; title: string; date: string; status: string };
export type SourceLine = { lineKey: string; title: string; variant: string; quantityText: string };
export type OrderLine = SourceLine & { linkState: 'none' | 'linked' | 'unavailable'; link: null | { sourceLinkId: string; sourceRevision: number; itemId: string; acquisitionId: string } };
export type OrderSources = { order: SourceOrder; lines: OrderLine[]; total: number; limit: number; offset: number; nextOffset: number | null };
export type SourceLink = { id: string; revision: number; status: 'active' | 'detached'; state: 'current' | 'needs_review' | 'detached'; reviewReasons: ('source_missing' | 'source_changed')[]; orderId: string; lineKey: string; orderRevision: number; order: SourceOrder | null; line: SourceLine | null };
export type AcquisitionSource = { itemId: string; acquisitionId: string; link: SourceLink | null };
export type SourceIntent = { requestId: string; operation: 'attach'; acquisitionId: string; itemRevision: number; revision: number; orderId: string; lineKey: string; orderRevision: number }
  | { requestId: string; operation: 'detach'; acquisitionId: string; itemRevision: number; revision: number; sourceLinkId: string; sourceRevision: number };
export type SourcePreview = { requestId: string; operation: 'attach' | 'detach'; item: InventoryItem; acquisition: Acquisition; order: SourceOrder | null; line: SourceLine | null; link: SourceLink | null; previewToken: string; expiresInSeconds: number };
const invalid = () => { throw new Error('订单来源无法核对，请重新读取。'); };
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
const string = (value: unknown, max = 1000) => typeof value === 'string' && value.length <= max ? value : invalid();
const id = (value: unknown) => isInventoryId(value) ? value : invalid();
const integer = (value: unknown, min = 0) => Number.isSafeInteger(value) && Number(value) >= min ? Number(value) : invalid();
const key = (value: unknown) => typeof value === 'string' && /^(order|item:(0|[1-9]\d{0,3}))$/.test(value) ? value : invalid();
export function canManageSource(value: Acquisition): boolean { return value.kind === 'purchase' && value.canMutate && value.canManageSources === true; }
function order(value: unknown): SourceOrder { const row = object(value); return { id: id(row.id), revision: integer(row.revision, 1), title: string(row.title), date: string(row.date, 40), status: string(row.status, 1000) }; }
function line(value: unknown): SourceLine { const row = object(value); return { lineKey: key(row.lineKey), title: string(row.title), variant: string(row.variant), quantityText: string(row.quantityText) }; }
function link(value: unknown): SourceLink {
  const row = object(value), status = row.status, state = row.state;
  if (!['active', 'detached'].includes(String(status)) || !['current', 'needs_review', 'detached'].includes(String(state))
    || !Array.isArray(row.reviewReasons) || row.reviewReasons.some(v => !['source_missing', 'source_changed'].includes(String(v)))
    || (status === 'detached') !== (state === 'detached') || state === 'needs_review' && row.line !== null) return invalid();
  const result: SourceLink = { id: id(row.id), revision: integer(row.revision, 1), status: status as SourceLink['status'], state: state as SourceLink['state'], reviewReasons: row.reviewReasons as SourceLink['reviewReasons'],
    orderId: id(row.orderId), lineKey: key(row.lineKey), orderRevision: integer(row.orderRevision, 1), order: row.order === null ? null : order(row.order), line: row.line === null ? null : line(row.line) };
  if (result.order && result.order.id !== result.orderId || result.line && result.line.lineKey !== result.lineKey
    || state === 'current' && (!result.order || !result.line || result.order.revision !== result.orderRevision || result.reviewReasons.length)) return invalid();
  return result;
}
export function orderSourcesPath(orderId: string, offset = 0): string {
  id(orderId); integer(offset); if (offset > 100000) return invalid();
  return `/inventory/orders/${orderId}?limit=50&offset=${offset}`;
}
export function readOrderSources(value: unknown, orderId: string, offset = 0): OrderSources {
  const row = object(value), source = order(row.order), total = integer(row.total);
  if (source.id !== orderId || row.offset !== offset || row.limit !== 50 || !Array.isArray(row.lines) || row.lines.length > 50
    || row.nextOffset !== null && (integer(row.nextOffset) !== offset + row.lines.length || Number(row.nextOffset) >= total)
    || row.lines.length > 0 && total < offset + row.lines.length) return invalid();
  const seen = new Set<string>();
  const lines: OrderLine[] = row.lines.map(raw => {
    const r = object(raw), sourceLine = line(r);
    if (seen.has(sourceLine.lineKey) || !['none', 'linked', 'unavailable'].includes(String(r.linkState)) || (r.linkState === 'linked') !== (r.link !== null)) return invalid();
    seen.add(sourceLine.lineKey);
    const target = r.link === null ? null : object(r.link);
    return { ...sourceLine, linkState: r.linkState as OrderLine['linkState'], link: target ? { sourceLinkId: id(target.sourceLinkId), sourceRevision: integer(target.sourceRevision, 1), itemId: id(target.itemId), acquisitionId: id(target.acquisitionId) } : null };
  });
  return { order: source, lines, total, limit: 50, offset, nextOffset: row.nextOffset as number | null };
}
export function readAcquisitionSource(value: unknown, itemId: string, acquisitionId: string): AcquisitionSource {
  const row = object(value); if (row.itemId !== itemId || row.acquisitionId !== acquisitionId) return invalid();
  return { itemId: id(row.itemId), acquisitionId: id(row.acquisitionId), link: row.link === null ? null : link(row.link) };
}
export function readSourcePreview(value: unknown, intent: SourceIntent, itemId: string): SourcePreview {
  const row = object(value), item = validateItem(row.item as InventoryItem), acquisition = validateAcquisition(row.acquisition as Acquisition);
  if (row.requestId !== intent.requestId || row.operation !== intent.operation || item.id !== itemId || acquisition.id !== intent.acquisitionId || acquisition.itemId !== itemId
    || item.revision !== intent.itemRevision || acquisition.itemRevision !== item.revision || acquisition.revision !== intent.revision || !canManageSource(acquisition)
    || row.expiresInSeconds !== 900 || typeof row.previewToken !== 'string' || !row.previewToken || row.previewToken.length > 20000) return invalid();
  const result: SourcePreview = { requestId: intent.requestId, operation: intent.operation, item, acquisition, order: row.order === null ? null : order(row.order), line: row.line === null ? null : line(row.line), link: row.link === null ? null : link(row.link), previewToken: row.previewToken, expiresInSeconds: 900 };
  if (intent.operation === 'attach' && (!result.order || result.order.id !== intent.orderId || result.order.revision !== intent.orderRevision || result.line?.lineKey !== intent.lineKey)
    || intent.operation === 'detach' && (result.link?.id !== intent.sourceLinkId || result.link.revision !== intent.sourceRevision)) return invalid();
  return result;
}
export function readSourceReceipt(value: unknown, itemId: string, acquisitionId: string): InventoryResult {
  const result = validateResult(value as InventoryResult, itemId, acquisitionId), operation = result.operation as InventoryResult['operation'] & { sourceLinkId?: unknown; sourceRevision?: unknown };
  id(operation.sourceLinkId); integer(operation.sourceRevision, 1); return result;
}
