import type { Draft, Plan, Preparation, Purchase, Segment } from './trips';
import type { Person } from './types';

export type BriefStop = { country: string; city: string; arrival: string; departure: string };
export type BriefItem = { key: string; title: string; assigneeText: string; owner: string | null; note: string; sourceText: string };
export type BriefPreparation = BriefItem & { due: string; dueMode: 'date' | 'offset'; dueOffsetDays: string };
export type BriefPriority = 'low' | 'normal' | 'high';
export type BriefPurchase = BriefItem & { quantity: string; budget: string; due: string; dueMode: 'none' | 'date' | 'offset'; dueOffsetDays: string; priority: BriefPriority };
export type BriefForm = { title: string; start: string; end: string; budget: string; international: boolean | null; destinations: BriefStop[]; memberIds: string[]; note: string;
  checklist: BriefPreparation[]; shopping: BriefPurchase[]; useDefaultChecklist: boolean };
export type JourneyBriefResult = { mode: 'local' | 'model'; form: BriefForm; notice: string; warnings: string[] };
const MAX_CENTS = 100_000_000_000;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('旅行简报格式无效，请重新核对。');
  return value as Record<string, unknown>;
}
function text(value: unknown, label: string, limit: number, optional = true): string {
  if (typeof value !== 'string' || [...value].length > limit || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value) || !optional && !value.trim()) throw new Error(`${label}格式或长度无效。`);
  return value.trim();
}
export function briefDay(value: unknown, optional = false): string {
  if (optional && value === '') return '';
  if (typeof value !== 'string' || !/^(20\d{2}|2100)-\d{2}-\d{2}$/.test(value)) throw new Error('日期请填写 YYYY-MM-DD（2000—2100 年）。');
  const parsed = new Date(value + 'T00:00:00Z');
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error('请填写真实存在的日期。');
  return value;
}
function cents(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0 || value > MAX_CENTS) throw new Error('预算须为允许范围内的整数分。');
  return value;
}
export function briefAmountText(value: number): string {
  const exact = BigInt(cents(value));
  return `${exact / 100n}.${String(exact % 100n).padStart(2, '0')}`;
}
export function briefAmount(value: string): number {
  if (typeof value !== 'string' || !/^\d{1,10}(\.\d{1,2})?$/.test(value.trim())) throw new Error('请明确旅行总预算，用非负数字，最多两位小数；未知时不要填 0。');
  const [whole, fraction = ''] = value.trim().split('.');
  const exact = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  if (exact > BigInt(MAX_CENTS)) throw new Error('旅行总预算超出允许范围。');
  return Number(exact);
}
export const blankBriefStop = (): BriefStop => ({ country: '', city: '', arrival: '', departure: '' });
export const emptyBrief = (prompt = ''): BriefForm => ({ title: '', start: '', end: '', budget: '', international: null, destinations: [blankBriefStop()], memberIds: [], note: prompt,
  checklist: [], shopping: [], useDefaultChecklist: true });
export const blankBriefPreparation = (key: string): BriefPreparation => ({ key, title: '', assigneeText: '', owner: null, note: '', sourceText: '', due: '', dueMode: 'date', dueOffsetDays: '' });
export const blankBriefPurchase = (key: string): BriefPurchase => ({ key, title: '', assigneeText: '', owner: null, note: '', sourceText: '', quantity: '', budget: '', due: '', dueMode: 'none', dueOffsetDays: '', priority: 'normal' });
function purchasePriority(value: unknown): BriefPriority {
  if (value === undefined) return 'normal';
  if (value !== 'low' && value !== 'normal' && value !== 'high') throw new Error('请明确采购优先级：低、普通或高。');
  return value;
}
export function briefPersonLabel(person: Person, people: Person[], actorId: string): string {
  if (person.id === actorId) return person.name + '（我）';
  const same = people.filter(p => p.name === person.name);
  if (same.length < 2) return person.name;
  return person.name + (same.filter(p => p.id !== actorId).length === 1 ? '（另一位成员）' : '（同名成员，暂无法区分）');
}
export function briefOwnerOptions(people: Person[], actorId: string) {
  return [{ id: 'shared', label: '一起', disabled: false }, ...people.map(person => ({ id: person.id, label: briefPersonLabel(person, people, actorId),
    disabled: person.id !== actorId && people.filter(p => p.id !== actorId && p.name === person.name).length > 1 }))];
}
export function journeyBriefRequest(prompt: string, useModel: boolean) {
  const raw = text(prompt, '原始需求', 2000);
  if (typeof useModel !== 'boolean' || useModel && !raw) throw new Error('使用 AI 前请先填写旅行需求。');
  // No household context, member identifiers, or prior draft is sent to the model endpoint.
  return { prompt: raw, useModel };
}
function stops(value: unknown, optionalDates: boolean): BriefStop[] {
  if (!Array.isArray(value) || value.length > 20) throw new Error('最多填写 20 个目的地。');
  return value.map(raw => { const row = object(raw); return {
    country: text(row.country, '国家或地区', 60), city: text(row.city, '目的地城市', 80, optionalDates),
    arrival: briefDay(row.arrival, optionalDates), departure: briefDay(row.departure, optionalDates),
  }; });
}
function briefItem(row: Record<string, unknown>, prompt: string, people: Person[]): BriefItem {
  if (row.owner !== null && typeof row.owner !== 'string') throw new Error('事项负责人格式无效。');
  const sourceText = text(row.sourceText, '事项原文', 500);
  if (sourceText && !prompt.includes(sourceText)) throw new Error('事项原文无法核对，请重新整理。');
  return { key: key(row.key), title: text(row.title, '事项标题', 100, false), assigneeText: text(row.assigneeText, '原文分工', 80),
    owner: row.owner === 'shared' || people.some(p => p.id === row.owner) ? row.owner as string : null,
    note: text(row.note, '事项备注', 500), sourceText };
}
export function readJourneyBrief(value: unknown, prompt: string, memberIds: string[] = [], people: Person[] = []): JourneyBriefResult {
  const result = object(value), brief = object(result.brief);
  if (result.mode !== 'local' && result.mode !== 'model') throw new Error('旅行简报来源无法确认。');
  if (brief.international !== null && typeof brief.international !== 'boolean') throw new Error('请选择国内或境外旅行。');
  const destinations = stops(brief.destinations, true);
  const checklist = rows(brief.checklist === undefined ? [] : brief.checklist, '准备清单').map(row => {
    const due = briefDay(row.due, true), offset = row.dueOffsetDays;
    if (offset !== null && (!Number.isSafeInteger(offset) || Number(offset) < -730 || Number(offset) > 366) || due && offset !== null) throw new Error('准备截止日期与相对天数需要分别核对。');
    return { ...briefItem(row, prompt, people), due, dueMode: offset === null ? 'date' as const : 'offset' as const, dueOffsetDays: offset === null ? '' : String(offset) };
  });
  const shopping = rows(brief.shopping === undefined ? [] : brief.shopping, '采购清单').map(row => {
    const due = briefDay(row.due === undefined ? '' : row.due, true), offset = row.dueOffsetDays === undefined ? null : row.dueOffsetDays;
    if (offset !== null && (!Number.isSafeInteger(offset) || Number(offset) < -730 || Number(offset) > 366) || due && offset !== null) throw new Error('采购截止日期与相对天数需要分别核对。');
    return { ...briefItem(row, prompt, people), due, dueMode: offset !== null ? 'offset' as const : due ? 'date' as const : 'none' as const,
      dueOffsetDays: offset === null ? '' : String(offset), priority: purchasePriority(row.priority),
      quantity: text(row.quantity, '采购数量', 30), budget: row.budgetCents === null ? '' : briefAmountText(cents(row.budgetCents)) };
  });
  const warnings = result.warnings === undefined ? [] : result.warnings;
  if (!Array.isArray(warnings) || warnings.length > 500) throw new Error('整理说明格式无效。');
  return { mode: result.mode, notice: text(result.notice, '整理说明', 2000), warnings: warnings.map(v => text(v, '整理说明', 2000)), form: {
    title: text(brief.title, '旅行名称', 100), start: briefDay(brief.start, true), end: briefDay(brief.end, true),
    budget: brief.budgetCents === null ? '' : briefAmountText(cents(brief.budgetCents)), international: brief.international,
    destinations: destinations.length ? destinations : [blankBriefStop()], memberIds: [...memberIds],
    // Never adopt model-provided note, identities, actions, bookings, or payment state.
    note: journeyBriefRequest(prompt, false).prompt, checklist, shopping, useDefaultChecklist: checklist.length === 0,
  } };
}
function members(value: unknown, people: Person[]): string[] {
  if (!Array.isArray(value) || !value.length || value.length > people.length || new Set(value).size !== value.length
    || value.some(id => typeof id !== 'string' || !people.some(person => person.id === id))) throw new Error('请勾选当前家庭的出行成员。');
  return [...value] as string[];
}
function itemOwner(value: unknown, people: Person[]): string {
  if (typeof value !== 'string' || value !== 'shared' && !people.some(person => person.id === value)) throw new Error('请为每项准备与采购明确选择当前家庭负责人。');
  return value;
}
export function briefPreparationDate(row: BriefPreparation, start: string): string {
  if (row.dueMode === 'date') {
    if (row.dueOffsetDays !== '') throw new Error('请只选择一种截止方式。');
    if (!row.due) throw new Error('准备事项截止日期待核对，请填写日期或距出发天数。');
    return briefDay(row.due);
  }
  if (row.dueMode !== 'offset' || row.due || !/^-?\d{1,3}$/.test(row.dueOffsetDays)) throw new Error('请填写完整的距出发天数，负数表示出发前。');
  const offset = Number(row.dueOffsetDays);
  if (offset < -730 || offset > 366) throw new Error('准备日期最多提前 730 天或延后 366 天。');
  return briefDay(new Date(Date.parse(briefDay(start) + 'T00:00:00Z') + offset * 86400000).toISOString().slice(0, 10));
}
export function briefPurchaseDate(row: BriefPurchase, start: string): string {
  if (row.dueMode === 'none') {
    if (row.due !== '' || row.dueOffsetDays !== '') throw new Error('未设截止时请清空采购日期与相对天数。');
    return '';
  }
  if (row.dueMode !== 'date' && row.dueMode !== 'offset') throw new Error('请选择采购截止方式。');
  return briefPreparationDate({ ...row, dueMode: row.dueMode }, start);
}
export function journeyBriefPlan(form: BriefForm, people: Person[]): { plan: Plan } {
  const start = briefDay(form.start), end = briefDay(form.end);
  const duration = (Date.parse(end + 'T00:00:00Z') - Date.parse(start + 'T00:00:00Z')) / 86400000;
  if (duration < 0 || duration > 366) throw new Error('返程不得早于出发，单次旅行最多 367 天。');
  if (typeof form.international !== 'boolean') throw new Error('请选择国内或境外旅行。');
  const destinations = stops(form.destinations, false);
  if (!destinations.length) throw new Error('请至少填写一个目的地。');
  if (destinations.some(row => row.arrival < start || row.departure > end || row.arrival > row.departure)) throw new Error('每个目的地的停留日期须落在旅行日期内。');
  rows(form.checklist, '准备清单'); rows(form.shopping, '采购清单');
  if (typeof form.useDefaultChecklist !== 'boolean' || form.useDefaultChecklist && form.checklist.length) throw new Error('请核对准备清单选择。');
  const checklist = form.checklist.map(row => {
    const due = briefPreparationDate(row, start);
    if (due > end || (Date.parse(due) - Date.parse(start)) / 86400000 < -730) throw new Error('准备截止须在返程前，最多提前 730 天。');
    return { key: key(row.key), title: text(row.title, '准备事项', 100, false), owner: itemOwner(row.owner, people), note: text(row.note, '准备事项备注', 500),
      ...(row.dueMode === 'date' ? { due } : { dueOffsetDays: Number(row.dueOffsetDays) }) } satisfies Preparation;
  });
  const shopping = form.shopping.map(row => ({ key: key(row.key), title: text(row.title, '采购名称', 100, false), owner: itemOwner(row.owner, people),
    quantity: text(row.quantity, '采购数量', 30, false), budget: row.budget.trim() === '' ? null : briefAmount(row.budget), note: text(row.note, '采购备注', 500),
    due: briefPurchaseDate(row, start), priority: purchasePriority(row.priority) } satisfies Purchase & { due: string; priority: BriefPriority }));
  return { plan: { schemaVersion: 1, title: text(form.title, '旅行名称', 100, false), start, end, international: form.international,
    memberIds: members(form.memberIds, people), budget: briefAmount(form.budget), saved: 0, paid: 0, note: text(form.note, '旅行备注', 2000),
    destinations: destinations.map((row, i) => ({ key: `brief-stop-${i + 1}`, ...row })), shopping,
    ...(!form.useDefaultChecklist ? { checklist } : {}),
  } };
}
function key(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,64}$/.test(value)) throw new Error('旅行准备项标识无效。');
  return value;
}
function rows(value: unknown, label: string): Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length > 100) throw new Error(`${label}格式无效。`);
  const result = value.map(object), keys = result.map(row => key(row.key));
  if (new Set(keys).size !== keys.length) throw new Error(`${label}包含重复标识。`);
  return result;
}
/** Keep only a normalized new v1 plan, never a target identity or this preview's token. */
export function preparedJourneyDraft(value: unknown, people: Person[]): Draft {
  const result = object(value), raw = object(result.plan);
  if (typeof result.canApply !== 'boolean' || raw.schemaVersion !== undefined && raw.schemaVersion !== 1) throw new Error('旅行校验结果无效。');
  const form: BriefForm = {
    ...emptyBrief(),
    title: text(raw.title, '旅行名称', 100, false), start: briefDay(raw.start), end: briefDay(raw.end),
    budget: briefAmountText(cents(raw.budget)), international: raw.international as boolean,
    destinations: stops(raw.destinations, false), memberIds: members(raw.memberIds, people), note: text(raw.note, '旅行备注', 2000),
  };
  if (raw.saved !== 0 || raw.paid !== 0) throw new Error('新旅行不应包含已付款或预留金额。');
  const plan = journeyBriefPlan(form, people).plan;
  plan.checklist = rows(raw.checklist, '准备清单').map(row => {
    if (typeof row.owner !== 'string' || row.owner !== 'shared' && !people.some(person => person.id === row.owner)) throw new Error('准备事项负责人不属于当前家庭。');
    const due = briefDay(row.due);
    if (due > plan.end || !Number.isInteger(row.dueOffsetDays) || Number(row.dueOffsetDays) < -730 || Number(row.dueOffsetDays) > 366
      || Number(row.dueOffsetDays) !== (Date.parse(due) - Date.parse(plan.start)) / 86400000) throw new Error('准备事项截止日期无效。');
    return { key: key(row.key), title: text(row.title, '准备事项', 100, false), owner: row.owner, due,
      dueOffsetDays: Number(row.dueOffsetDays), note: text(row.note, '准备事项备注', 500), category: text(row.category, '事项分类', 40, false) } satisfies Preparation;
  });
  plan.shopping = rows(raw.shopping, '采购清单').map(row => ({ key: key(row.key), title: text(row.title, '采购名称', 100, false), owner: itemOwner(row.owner, people),
    quantity: text(row.quantity, '采购数量', 30, false), budget: row.budget === null ? null : cents(row.budget), note: text(row.note, '采购备注', 500),
    due: briefDay(row.due === undefined ? '' : row.due, true), priority: purchasePriority(row.priority) } satisfies Purchase & { due: string; priority: BriefPriority }));
  plan.segments = rows(raw.segments, '分段行程').map(row => {
    const start = briefDay(row.start), end = briefDay(row.end);
    if (start < plan.start || end > plan.end || start > end) throw new Error('停留安排超出旅行日期。');
    return { key: key(row.key), title: text(row.title, '行程标题', 100, false), start, end,
      location: text(row.location, '行程地点', 200), note: text(row.note, '行程备注', 500) } satisfies Segment;
  });
  return { plan, budget: briefAmountText(plan.budget), saved: '0.00', paid: '0.00' };
}
export type BriefReadFence = { read: <T>(load: () => Promise<T>, current: () => boolean) => Promise<T> };
// Capture endpoint failures as values so the existing identity fence always reads /me afterward.
export async function journeyCheckedRead<T>(fence: BriefReadFence, load: () => Promise<T>, current: () => boolean): Promise<T> {
  const result = await fence.read(async () => {
    try { return { ok: true as const, value: await load() }; } catch (error) { return { ok: false as const, error }; }
  }, current);
  if (!result.ok) throw result.error;
  return result.value;
}
