import { sessionIdentity } from './sessionIdentity.ts';
import type { Member } from './types';

export type InventoryItem = {
  id: string; owner: string; title: string; unit: string; variant: string; location: string;
  visibility: 'private' | 'shared'; reorderPoint: number | null; belowThreshold: boolean;
  revision: number; onHandQty: number; inTransitQty: number; plannedQty: number;
  canRead: boolean; canMutate: boolean; canManage: boolean; createdAt: string; updatedAt: string;
};
export const orderLabels = { planned: '计划采购', ordered: '已下单', in_transit: '运输中', closed: '已结束', cancelled: '已取消' };
export const afterSalesLabels = { none: '无售后', open: '售后处理中', closed: '售后已结束' };
export const movementLabels = { receive: '收货', consume: '使用', dispose: '报损', return: '退回', adjust: '更正', reverse: '撤销原记录' };
export type MovementKind = Exclude<keyof typeof movementLabels, 'reverse'>;
export type Acquisition = {
  id: string; itemId: string; kind: 'purchase' | 'opening'; shoppingId: string | null;
  orderedQty: number; orderState: keyof typeof orderLabels; orderedOn: string | null; expectedOn: string | null;
  warrantyUntil: string | null; afterSalesState: keyof typeof afterSalesLabels; note: string;
  revision: number; itemRevision: number; canMutate: boolean; canEditAllFields: boolean; editableFields: string[];
  onHandQty: number; receivedQty: number; returnedQty: number; remainingExpectedQty: number;
  fulfillmentState: 'unreceived' | 'partial' | 'received'; createdAt: string; updatedAt: string;
};
export type Movement = { id: string; acquisitionId: string; actor: string; kind: keyof typeof movementLabels; deltaQty: number; occurredOn: string; reason: string; reversesId: string | null; canReverse: boolean; createdAt: string };
export type InventoryPage<T> = { items: T[]; total: number; offset: number; limit: number; nextOffset: number | null };
export type InventoryResult = {
  operation: { itemId: string; itemRevision: number; acquisitionId?: string; acquisitionRevision?: number; movementId?: string; entityId?: string; deleted?: boolean; replayed: boolean };
  item?: InventoryItem; acquisition?: Acquisition;
};
export type InventorySession = { user: Member | null; csrf?: string | null };
export const inventorySignature = sessionIdentity;
export const isInventoryId = (id: unknown): id is string => typeof id === 'string' && /^[a-f0-9]{24}$/.test(id);
const natural = (n: unknown) => Number.isSafeInteger(n) && Number(n) >= 0;
const revision = (n: unknown) => natural(n) && Number(n) > 0;
const invalid = () => new Error('物品数据无法核对，请重新读取。');
export function validateItem(value: InventoryItem): InventoryItem {
  if (!value || !isInventoryId(value.id) || !revision(value.revision) || !['private', 'shared'].includes(value.visibility)
    || typeof value.owner !== 'string' || typeof value.title !== 'string' || typeof value.unit !== 'string'
    || typeof value.variant !== 'string' || typeof value.location !== 'string'
    || ![value.onHandQty, value.inTransitQty, value.plannedQty].every(natural)
    || value.reorderPoint !== null && !natural(value.reorderPoint)
    || ![value.canRead, value.canMutate, value.canManage, value.belowThreshold].every(n => typeof n === 'boolean')) throw invalid();
  return value;
}
export function validateAcquisition(value: Acquisition): Acquisition {
  if (!value || !isInventoryId(value.id) || !isInventoryId(value.itemId) || !revision(value.revision) || !revision(value.itemRevision)
    || !['purchase', 'opening'].includes(value.kind) || !Object.hasOwn(orderLabels, value.orderState) || !Object.hasOwn(afterSalesLabels, value.afterSalesState)
    || ![value.orderedQty, value.onHandQty, value.receivedQty, value.returnedQty, value.remainingExpectedQty].every(natural)
    || !Array.isArray(value.editableFields) || value.editableFields.some(field => typeof field !== 'string')
    || typeof value.canMutate !== 'boolean' || typeof value.canEditAllFields !== 'boolean' || typeof value.note !== 'string') throw invalid();
  return value;
}
export function validateMovement(value: Movement): Movement {
  if (!value || !isInventoryId(value.id) || !isInventoryId(value.acquisitionId) || !Object.hasOwn(movementLabels, value.kind)
    || !Number.isSafeInteger(value.deltaQty) || !value.deltaQty || typeof value.reason !== 'string'
    || typeof value.occurredOn !== 'string' || typeof value.canReverse !== 'boolean') throw invalid();
  return value;
}
export function validatePage<T>(value: InventoryPage<T>, limit: number, validate: (row: T) => T): InventoryPage<T> {
  if (!value || !Array.isArray(value.items) || value.items.length > limit || !natural(value.total) || !natural(value.offset)
    || value.limit !== limit || value.nextOffset !== null && (!natural(value.nextOffset) || value.nextOffset <= value.offset)) throw invalid();
  value.items.forEach(validate); return value;
}
export function validateResult(value: InventoryResult, itemId?: string, acquisitionId?: string, requireEntity = false): InventoryResult {
  const operation = value?.operation;
  if (!operation || !isInventoryId(operation.itemId) || !revision(operation.itemRevision) || typeof operation.replayed !== 'boolean'
    || itemId && itemId !== operation.itemId || acquisitionId && acquisitionId !== operation.acquisitionId) throw invalid();
  if ((requireEntity || operation.entityId !== undefined) && (!isInventoryId(operation.entityId) || !isInventoryId(operation.acquisitionId) || !revision(operation.acquisitionRevision) || operation.deleted)) throw invalid();
  if (operation.deleted) { if (value.item || value.acquisition) throw invalid(); return value; }
  if (!value.item || validateItem(value.item).id !== operation.itemId) throw invalid();
  if (operation.acquisitionId && (!value.acquisition || validateAcquisition(value.acquisition).id !== operation.acquisitionId || value.acquisition.itemId !== value.item.id)) throw invalid();
  return value;
}
export function inventoryRequestId(): string {
  if (!globalThis.crypto?.randomUUID) throw new Error('请使用安全连接后重试。');
  return globalThis.crypto.randomUUID().replace(/-/g, '');
}
export function quantityInput(value: string, signed = false, zero = false): number {
  const trimmed = value.trim();
  if (!(signed ? /^[+-]?\d+$/ : /^\d+$/).test(trimmed)) throw new Error(signed ? '更正数量请填写带正负号的整数。' : '数量请填写整数。');
  const quantity = Number(trimmed);
  if (!Number.isSafeInteger(quantity) || Math.abs(quantity) > 1000000 || !zero && quantity === 0) throw new Error('数量须在 1 到 1000000 之间；更正可填写负数。');
  return quantity;
}
export function inventoryDate(value: string, required = false): string | null {
  const trimmed = value.trim();
  if (!trimmed && !required) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) throw new Error('日期请填写 YYYY-MM-DD。');
  const date = new Date(trimmed + 'T12:00:00Z');
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== trimmed) throw new Error('请填写有效日期。');
  return trimmed;
}
export const movementConfirmations: Record<MovementKind, string> = { receive: 'confirmReceived', consume: 'confirmConsumed', dispose: 'confirmDisposed', return: 'confirmReturned', adjust: 'confirmCorrection' };

export class InventoryDiscarded extends Error {}
// One fence for reads AND writes. Failed requests also recheck the session, so
// an old-account error cannot restore a private draft or retry under a new user.
export class InventoryFence {
  private epoch = 0;
  constructor(private me: () => Promise<InventorySession>, private expected: string) {}
  invalidate() { this.epoch++; }
  async run<T>(action: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (session: InventorySession) => {
      if (!current() || epoch !== this.epoch) throw new InventoryDiscarded();
      if (session.user?.role !== 'member' || !session.csrf || inventorySignature(session) !== this.expected) throw new InventoryDiscarded('identity');
      return session.csrf;
    };
    const csrf = check(await this.me());
    let value!: T, failure: unknown, failed = false;
    try { value = await action(csrf); } catch (caught) { failed = true; failure = caught; }
    check(await this.me());
    if (failed) throw failure;
    return value;
  }
}


export type ShoppingInventoryPage = InventoryPage<{ item: InventoryItem; acquisition: Acquisition }> & {
  shopping: { id: string; revision: number; title: string; quantity: string };
};
export class InventoryShoppingMissing extends Error {}
export function shoppingInventoryPath(id: string, offset = 0): string {
  if (!isInventoryId(id) || !Number.isSafeInteger(offset) || offset < 0 || offset > 100000) throw invalid();
  return `/inventory/shopping/${id}/acquisitions?limit=12&offset=${offset}`;
}
export function validateShoppingInventoryPage(value: ShoppingInventoryPage, id: string, offset = 0): ShoppingInventoryPage {
  const shopping = value?.shopping;
  if (!shopping || shopping.id !== id || !isInventoryId(id) || !revision(shopping.revision)
    || typeof shopping.title !== 'string' || typeof shopping.quantity !== 'string' || value.offset !== offset) throw invalid();
  const ids = new Set<string>();
  validatePage(value, 12, row => {
    if (!row || !row.item || !row.acquisition) throw invalid();
    const item = validateItem(row.item), acquisition = validateAcquisition(row.acquisition);
    if (!item.canRead || acquisition.itemId !== item.id || acquisition.itemRevision !== item.revision
      || acquisition.shoppingId !== id || acquisition.kind !== 'purchase' || ids.has(acquisition.id)) throw invalid();
    ids.add(acquisition.id); return row;
  });
  // Keep free-text quantity as display text. It is never an inventory quantity.
  return { ...value, shopping: { id, revision: shopping.revision, title: shopping.title, quantity: shopping.quantity } };
}

export type InventoryFollowupData = { title: string; owner: string; due: string; note: string };
export type InventoryFollowup = {
  itemId: string; acquisitionId: string; state: 'none' | 'linked' | 'deleted';
  task: (InventoryFollowupData & { id: string; revision: number; done: boolean }) | null;
};
export function validateFollowup(value: InventoryFollowup, itemId: string, acquisitionId: string): InventoryFollowup {
  if (!value || !isInventoryId(itemId) || !isInventoryId(acquisitionId) || value.itemId !== itemId || value.acquisitionId !== acquisitionId
    || !['none', 'linked', 'deleted'].includes(value.state)) throw invalid();
  if (value.state !== 'linked') {
    if (value.task !== null) throw invalid();
    return { itemId, acquisitionId, state: value.state, task: null };
  }
  const task = value.task;
  if (!task || !isInventoryId(task.id) || !revision(task.revision) || typeof task.done !== 'boolean'
    || typeof task.title !== 'string' || !task.title.trim() || [...task.title].length > 100
    || typeof task.owner !== 'string' || !task.owner.trim() || typeof task.note !== 'string' || [...task.note].length > 500
    || typeof task.due !== 'string' || task.due !== (inventoryDate(task.due) || '')) throw invalid();
  // Only the explicitly shared task projection; never retain private source fields.
  return { itemId, acquisitionId, state: 'linked', task: { id: task.id, revision: task.revision, title: task.title, owner: task.owner, due: task.due, done: task.done, note: task.note } };
}
export function followupInput(value: InventoryFollowupData, memberIds: string[]): InventoryFollowupData {
  const title = value.title.trim(), note = value.note.trim();
  if (!title || [...title].length > 100) throw new Error('请填写不超过 100 字的待办标题。');
  if ([...note].length > 500) throw new Error('待办备注不能超过 500 字。');
  if (value.owner !== 'shared' && !memberIds.includes(value.owner)) throw new Error('请重新选择当前家庭的负责人。');
  return { title, owner: value.owner, due: inventoryDate(value.due) || '', note };
}
