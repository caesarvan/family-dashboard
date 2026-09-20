import type { Action } from './assistant';
import { shoppingSchedule } from './trips';

export type ActionData = Action['data'];
export type ActionDraft = { title: string; owner: string; due: string; note: string; quantity: string; budget: string; priority: 'low' | 'normal' | 'high' };
export type ActionOverride = { index: number; data: ActionData };
export type ApplyIntent = { id: string; selected: number[]; overrides: ActionOverride[] };
export const assistantPlanStorageKey = 'family-assistant-plan-v1';
export type PlanStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export function browserPlanStorage(): PlanStorage | undefined {
  try { return typeof window === 'undefined' ? undefined : window.sessionStorage; } catch { return undefined; }
}
export function recoverPlan(storage: PlanStorage | undefined, memberIdentity: string): string | null {
  try {
    const raw = storage?.getItem(assistantPlanStorageKey); if (!raw) return null;
    const value = JSON.parse(raw);
    if (!value || Object.keys(value).sort().join(',') !== 'memberIdentity,planId' || value.memberIdentity !== memberIdentity
      || typeof value.planId !== 'string' || !/^[a-f0-9]{32}$/.test(value.planId)) { storage?.removeItem(assistantPlanStorageKey); return null; }
    return value.planId;
  } catch { try { storage?.removeItem(assistantPlanStorageKey); } catch {} return null; }
}
export function retainPlan(storage: PlanStorage | undefined, memberIdentity: string, planId: string | null): boolean {
  try {
    if (planId === null) {
      const raw = storage?.getItem(assistantPlanStorageKey);
      if (raw && JSON.parse(raw)?.memberIdentity === memberIdentity) storage?.removeItem(assistantPlanStorageKey);
    }
    else if (/^[a-f0-9]{32}$/.test(planId)) storage?.setItem(assistantPlanStorageKey, JSON.stringify({ memberIdentity, planId }));
    else return false;
    return !!storage;
  } catch { return false; }
}
export function actionDraft(action: Action): ActionDraft {
  const d = action.data;
  return { title: d.title, owner: d.owner, due: d.due || '', note: d.note || '', quantity: d.quantity || '1 件',
    budget: d.budget == null ? '' : (d.budget / 100).toFixed(2), priority: d.priority || 'normal' };
}
export function actionBudget(value: string): number | null {
  const text = value.trim(); if (!text) return null;
  if (!/^\d{1,10}(?:\.\d{1,2})?$/.test(text)) throw new Error('预算请填非负金额，最多两位小数，或留空。');
  const [yuan, cents = ''] = text.split('.'), amount = Number(yuan) * 100 + Number(cents.padEnd(2, '0'));
  if (!Number.isSafeInteger(amount) || amount > 100000000000) throw new Error('预算超出可填写范围。');
  return amount;
}
export function editedAction(kind: Action['kind'], draft: ActionDraft, members: string[]): ActionData {
  const title = draft.title.trim(), note = draft.note.trim(), due = draft.due.trim();
  if (!title || Array.from(title).length > 100) throw new Error('名称请填写 1～100 字。');
  if (Array.from(note).length > 500) throw new Error('备注最多 500 字。');
  if (draft.owner !== 'shared' && !members.includes(draft.owner)) throw new Error('请重新选择当前家庭成员。');
  if (due) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(due);
    if (!match) throw new Error('截止日请填有效的 YYYY-MM-DD，或留空。');
    const y = Number(match[1]), m = Number(match[2]), d = Number(match[3]);
    const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (!y || m < 1 || m > 12 || d < 1 || d > days[m - 1]) throw new Error('截止日请填有效日期。');
  }
  const result: ActionData = { title, owner: draft.owner, due, note };
  if (kind === 'shopping') {
    const quantity = draft.quantity.trim(); if (!quantity || Array.from(quantity).length > 30) throw new Error('数量请填写 1～30 字。');
    Object.assign(result, shoppingSchedule({ due, priority: draft.priority }), { quantity, budget: actionBudget(draft.budget) });
  }
  return result;
}
export function snapshotIntent(id: string, selected: number[], edits: Record<number, ActionData>): ApplyIntent {
  return { id, selected: [...selected].sort((a, b) => a - b), overrides: selected.filter(index => edits[index]).sort((a, b) => a - b)
    .map(index => ({ index, data: { ...edits[index] } })) };
}
