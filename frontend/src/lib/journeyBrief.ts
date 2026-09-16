import type { Draft, Plan, Preparation, Segment } from './trips';
import type { Person } from './types';

export type BriefStop = { country: string; city: string; arrival: string; departure: string };
export type BriefForm = { title: string; start: string; end: string; budget: string; international: boolean | null; destinations: BriefStop[]; memberIds: string[]; note: string };
export type JourneyBriefResult = { mode: 'local' | 'model'; form: BriefForm; notice: string };
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
export const emptyBrief = (prompt = ''): BriefForm => ({ title: '', start: '', end: '', budget: '', international: null, destinations: [blankBriefStop()], memberIds: [], note: prompt });
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
export function readJourneyBrief(value: unknown, prompt: string, memberIds: string[] = []): JourneyBriefResult {
  const result = object(value), brief = object(result.brief);
  if (result.mode !== 'local' && result.mode !== 'model') throw new Error('旅行简报来源无法确认。');
  if (brief.international !== null && typeof brief.international !== 'boolean') throw new Error('请选择国内或境外旅行。');
  const destinations = stops(brief.destinations, true);
  return { mode: result.mode, notice: text(result.notice, '整理说明', 2000), form: {
    title: text(brief.title, '旅行名称', 100), start: briefDay(brief.start, true), end: briefDay(brief.end, true),
    budget: brief.budgetCents === null ? '' : briefAmountText(cents(brief.budgetCents)), international: brief.international,
    destinations: destinations.length ? destinations : [blankBriefStop()], memberIds: [...memberIds],
    // Never adopt model-provided note, identities, actions, bookings, or payment state.
    note: journeyBriefRequest(prompt, false).prompt,
  } };
}
function members(value: unknown, people: Person[]): string[] {
  if (!Array.isArray(value) || !value.length || value.length > people.length || new Set(value).size !== value.length
    || value.some(id => typeof id !== 'string' || !people.some(person => person.id === id))) throw new Error('请勾选当前家庭的出行成员。');
  return [...value] as string[];
}
export function journeyBriefPlan(form: BriefForm, people: Person[]): { plan: Plan } {
  const start = briefDay(form.start), end = briefDay(form.end);
  const duration = (Date.parse(end + 'T00:00:00Z') - Date.parse(start + 'T00:00:00Z')) / 86400000;
  if (duration < 0 || duration > 366) throw new Error('返程不得早于出发，单次旅行最多 367 天。');
  if (typeof form.international !== 'boolean') throw new Error('请选择国内或境外旅行。');
  const destinations = stops(form.destinations, false);
  if (!destinations.length) throw new Error('请至少填写一个目的地。');
  if (destinations.some(row => row.arrival < start || row.departure > end || row.arrival > row.departure)) throw new Error('每个目的地的停留日期须落在旅行日期内。');
  return { plan: { schemaVersion: 1, title: text(form.title, '旅行名称', 100, false), start, end, international: form.international,
    memberIds: members(form.memberIds, people), budget: briefAmount(form.budget), saved: 0, paid: 0, note: text(form.note, '旅行备注', 2000),
    destinations: destinations.map((row, i) => ({ key: `brief-stop-${i + 1}`, ...row })), shopping: [],
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
    title: text(raw.title, '旅行名称', 100, false), start: briefDay(raw.start), end: briefDay(raw.end),
    budget: briefAmountText(cents(raw.budget)), international: raw.international as boolean,
    destinations: stops(raw.destinations, false), memberIds: members(raw.memberIds, people), note: text(raw.note, '旅行备注', 2000),
  };
  if (raw.saved !== 0 || raw.paid !== 0 || !Array.isArray(raw.shopping) || raw.shopping.length) throw new Error('新旅行不应包含已付款或未核对的采购。');
  const plan = journeyBriefPlan(form, people).plan;
  plan.checklist = rows(raw.checklist, '准备清单').map(row => {
    if (typeof row.owner !== 'string' || row.owner !== 'shared' && !people.some(person => person.id === row.owner)) throw new Error('准备事项负责人不属于当前家庭。');
    const due = briefDay(row.due);
    if (due > plan.end || !Number.isInteger(row.dueOffsetDays) || Number(row.dueOffsetDays) < -730 || Number(row.dueOffsetDays) > 366) throw new Error('准备事项截止日期无效。');
    return { key: key(row.key), title: text(row.title, '准备事项', 100, false), owner: row.owner, due,
      dueOffsetDays: Number(row.dueOffsetDays), note: text(row.note, '准备事项备注', 500), category: text(row.category, '事项分类', 40, false) } satisfies Preparation;
  });
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
