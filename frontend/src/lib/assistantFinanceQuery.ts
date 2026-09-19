import { validFinanceMonth } from './finance';
import { isAssistantSearchRequest, isExistingTripChangeRequest } from './assistantJourney';
import type { FinanceNavigationRequest } from './types';

export type FinanceQuery = { scope: 'personal' | 'shared' | 'public'; month: string | null; metric: 'spending' | 'budget' | 'summary'; currency: string | null; category: string | null };
export type FinanceQueryResult = {
  status: 'ready' | 'clarify' | 'unsupported'; mode: 'local' | 'model'; message: string; query: FinanceQuery | null;
  totals: { currency: string; expenseCents: number; refundCents: number; netSpendCents: number; count: number }[];
  budgets: { currency: string; category: string; amountCents: number; spentCents: number; remainingCents: number }[];
  snapshot: { walletCents: number | null; livingSpentCents: number | null; livingBudgetCents: number | null; savingsCents: number | null; confirmedAt: string | null } | null;
  coverage: { status: 'recorded' | 'partial' | 'no_records' | 'manual_snapshot'; note: string; recordCount: number; unknownCount: number; orderCount: number; duplicateCount: number };
  navigation: { screen: 'finance'; tab: 'ledger' | 'budgets' | 'shared'; month: string | null } | null;
};
const bad = (): never => { throw new Error('查询结果暂时无法核对，请重新查询。'); };
const object = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const text = (v: unknown, max = 2000): string => typeof v === 'string' && Array.from(v).length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\p{Cs}]/u.test(v) ? v : bad();
const integer = (v: unknown, signed = false): number => typeof v === 'number' && Number.isSafeInteger(v) && (signed || v >= 0) ? v : bad();
const currency = (v: unknown): string => typeof v === 'string' && /^[A-Z]{3}$/.test(v) ? v : bad();
const month = (v: unknown) => validFinanceMonth(v) ? v : bad();
const list = (v: unknown, max: number): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
const choice = <T extends string>(v: unknown, values: readonly T[]): T => typeof v === 'string' && values.includes(v as T) ? v as T : bad();
const nullable = <T,>(v: unknown, read: (v: unknown) => T): T | null => v === null ? null : read(v);

// Routing identifies the finance domain only. The server decides whether the
// whole request is a supported read; edits, negation and mixed requests survive.
export function isAssistantFinanceQuery(prompt: string): boolean {
  const p = prompt.trim();
  if (isAssistantSearchRequest(p) || /^(?:待办|采购|任务)\s*[:：]/.test(p)
    || /^(?:请|帮我|请帮我)?(?:创建|新建|添加)(?:(?:一|两|几|\d+)(?:个|项|条))?(?:待办|任务|采购)/.test(p)) return false;
  const financeQuestion = /(?:查|看看|瞧瞧|多少|还剩|余额|开销|开支|花销|支出|消费)/.test(p);
  if (!financeQuestion && (isExistingTripChangeRequest(p)
    || /^(?:请|帮我|请帮我|我想|我要)?(?:计划|规划|安排|准备|创建|新建).*(?:旅行|旅游|行程)/.test(p))) return false;
  return /(?:预算|支出|消费|开销|开支|花销|账单|账本|荷包|共同资金|公共资金|长期储蓄|生活费)/.test(p)
    || /(?:本月|这个月|这月|上月|上个月|\d{4}年\d{1,2}月|\d{4}-\d{2}).*(?:花了?多少|花费|用了?多少钱)/.test(p);
}
export function financeQueryRequest(prompt: string, useModel: boolean) {
  const p = text(prompt).trim();
  if (!p || typeof useModel !== 'boolean') throw new Error('请填写要查询的月份和财务问题。');
  return { prompt: p, useModel };
}
export function financeQueryRefreshPrompt(query: FinanceQuery): string {
  if (query.scope === 'public') return '查询公共荷包';
  if (!validFinanceMonth(query.month)) return bad();
  if (query.currency !== null) currency(query.currency);
  if (query.scope === 'shared') return ['查询', query.month, query.currency, '共享消费'].filter(Boolean).join(' ');
  if (query.category !== null && !['餐饮', '交通', '购物', '住房', '医疗', '教育', '娱乐', '旅行', '日用', '其他', '未分类'].includes(query.category)) return bad();
  return ['查询本人', query.month, query.currency, query.category, { spending: '支出', budget: '预算', summary: '支出与预算' }[query.metric]].filter(Boolean).join(' ');
}
export const sameFinanceQuery = (a: FinanceQuery | null, b: FinanceQuery | null) => !!a && !!b && (['scope', 'month', 'metric', 'currency', 'category'] as const).every(key => a[key] === b[key]);
export function readFinanceQuery(value: unknown): FinanceQueryResult {
  const v = object(value), c = object(v.coverage);
  const result: FinanceQueryResult = {
    status: choice(v.status, ['ready', 'clarify', 'unsupported']), mode: choice(v.mode, ['local', 'model']), message: text(v.message),
    query: null, snapshot: null, navigation: null,
    totals: list(v.totals, 200).map(raw => { const t = object(raw); const row = { currency: currency(t.currency), expenseCents: integer(t.expenseCents), refundCents: integer(t.refundCents), netSpendCents: integer(t.netSpendCents, true), count: integer(t.count) };
      if (BigInt(row.expenseCents) - BigInt(row.refundCents) !== BigInt(row.netSpendCents)) bad(); return row; }),
    budgets: list(v.budgets, 1200).map(raw => { const b = object(raw); const row = { currency: currency(b.currency), category: text(b.category, 60), amountCents: integer(b.amountCents), spentCents: integer(b.spentCents, true), remainingCents: integer(b.remainingCents, true) };
      if (!row.category || BigInt(row.amountCents) - BigInt(row.spentCents) !== BigInt(row.remainingCents)) bad(); return row; }),
    coverage: { status: choice(c.status, ['recorded', 'partial', 'no_records', 'manual_snapshot']), note: text(c.note), recordCount: integer(c.recordCount), unknownCount: integer(c.unknownCount), orderCount: integer(c.orderCount), duplicateCount: integer(c.duplicateCount) },
  };
  if (new Set(result.totals.map(t => t.currency)).size !== result.totals.length || new Set(result.budgets.map(b => b.currency + ':' + b.category)).size !== result.budgets.length) bad();
  if (result.status !== 'ready') {
    if (v.query !== null || v.snapshot !== null || v.navigation !== null || result.totals.length || result.budgets.length) bad(); return result;
  }
  const q = object(v.query), n = object(v.navigation);
  result.query = { scope: choice(q.scope, ['personal', 'shared', 'public']), month: nullable(q.month, month), metric: choice(q.metric, ['spending', 'budget', 'summary']), currency: nullable(q.currency, currency), category: nullable(q.category, x => text(x, 60)) };
  result.navigation = { screen: n.screen === 'finance' ? 'finance' : bad(), tab: choice(n.tab, ['ledger', 'budgets', 'shared']), month: nullable(n.month, month) };
  if (result.navigation.month !== result.query.month || result.query.currency && [...result.totals, ...result.budgets].some(t => t.currency !== result.query!.currency)) bad();
  if (result.query.scope === 'public') {
    const s = object(v.snapshot);
    result.snapshot = { walletCents: nullable(s.walletCents, integer), livingSpentCents: nullable(s.livingSpentCents, integer), livingBudgetCents: nullable(s.livingBudgetCents, integer), savingsCents: nullable(s.savingsCents, integer), confirmedAt: nullable(s.confirmedAt, x => text(x, 100)) };
    if (result.query.month !== null || result.query.currency !== null || result.query.category !== null || result.navigation.tab !== 'shared' || result.totals.length || result.budgets.length || result.coverage.status !== 'manual_snapshot') bad();
    if (result.snapshot.confirmedAt === null && Object.entries(result.snapshot).some(([k, amount]) => k !== 'confirmedAt' && amount !== null)) bad();
  } else {
    if (v.snapshot !== null || !result.query.month || result.coverage.status === 'manual_snapshot') bad();
    if (result.query.scope === 'shared') { if (result.navigation.tab !== 'shared' || result.budgets.length || result.query.category !== null) bad(); }
    else if (result.navigation.tab !== (result.query.metric === 'budget' ? 'budgets' : 'ledger')) bad();
  }
  return result;
}
export function financeQueryNavigation(result: FinanceQueryResult, identityKey: string, key: number): FinanceNavigationRequest {
  if (result.status !== 'ready' || !result.navigation) return bad();
  const request = { ...result.navigation, identityKey, key };
  if (!readFinanceNavigation(request, identityKey)) return bad(); return request;
}
export function readFinanceNavigation(value: unknown, identityKey: string): FinanceNavigationRequest | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const v = value as FinanceNavigationRequest;
  if (!identityKey || v.identityKey !== identityKey || !Number.isSafeInteger(v.key) || v.key < 1 || v.screen !== 'finance'
    || !['ledger', 'budgets', 'shared'].includes(v.tab) || !(validFinanceMonth(v.month) || v.month === null && v.tab === 'shared')) return null;
  return { key: v.key, identityKey, screen: 'finance', tab: v.tab, month: v.month };
}
