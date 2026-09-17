import type { HomeLayout, Member } from './types';

export const homeCards = ['calendar', 'finance', 'tasks', 'shopping', 'trips'] as const;
export type HomeCard = typeof homeCards[number];
export const homeCardNames: Record<HomeCard, string> = { calendar: '日程安排', finance: '共同资金', tasks: '共同待办', shopping: '采购清单', trips: '下一趟旅行' };
export type LayoutSession = { user: Member | null; csrf?: string | null };
export class LayoutError extends Error { constructor(message: string, public status = 0) { super(message); } }
export class LayoutDiscarded extends Error {}
export class LayoutRejected extends LayoutError {}
const invalid = () => new LayoutError('首页布局暂时无法核对，请重新读取。');
export const isHomeCard = (key: string): key is HomeCard => (homeCards as readonly string[]).includes(key);
export function readHomeLayout(raw: unknown): HomeLayout {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw invalid();
  const value = raw as Record<string, unknown>;
  const strings = (list: unknown): list is string[] => Array.isArray(list) && list.every(key => typeof key === 'string') && new Set(list).size === list.length;
  const order = value.order, hidden = value.hidden;
  if (!Number.isSafeInteger(value.revision) || Number(value.revision) < 0 || !strings(order) || !strings(hidden)
    || !homeCards.every(key => order.includes(key)) || hidden.some(key => !order.includes(key))
    || homeCards.every(key => hidden.includes(key))) throw invalid();
  return { revision: Number(value.revision), order: [...order], hidden: [...hidden] };
}
/** Older clients submit only known keys; the server preserves future stored keys. */
export function homeLayoutPayload(value: HomeLayout): HomeLayout {
  const valid = readHomeLayout(value);
  return { revision: valid.revision, order: valid.order.filter(isHomeCard), hidden: valid.hidden.filter(isHomeCard) };
}
export function sameHomeLayout(a: HomeLayout, b: HomeLayout): boolean {
  const left = homeLayoutPayload(a), right = homeLayoutPayload(b);
  return left.order.join('|') === right.order.join('|') && [...left.hidden].sort().join('|') === [...right.hidden].sort().join('|');
}
export function moveHomeCard(value: HomeLayout, key: HomeCard, direction: -1 | 1): HomeLayout {
  const next = readHomeLayout(value), positions = next.order.map((item, index) => isHomeCard(item) ? index : -1).filter(index => index >= 0);
  const at = positions.indexOf(next.order.indexOf(key)), target = at + direction;
  if (at >= 0 && target >= 0 && target < positions.length) {
    const a = positions[at], b = positions[target]; [next.order[a], next.order[b]] = [next.order[b], next.order[a]];
  }
  return next;
}
export function toggleHomeCard(value: HomeLayout, key: HomeCard): HomeLayout {
  const next = readHomeLayout(value);
  next.hidden = next.hidden.includes(key) ? next.hidden.filter(item => item !== key) : [...next.hidden, key];
  if (homeCards.every(item => next.hidden.includes(item))) throw new LayoutError('首页至少保留一张可见卡片。');
  return next;
}
export function resetHomeLayout(value: HomeLayout): HomeLayout {
  return { revision: value.revision, order: [...homeCards, ...value.order.filter(key => !isHomeCard(key))], hidden: value.hidden.filter(key => !isHomeCard(key)) };
}
export function rebaseHomeDraft(draft: HomeLayout, latest: HomeLayout): HomeLayout {
  latest = readHomeLayout(latest);
  const next = homeLayoutPayload(draft);
  return { revision: latest.revision, order: [...next.order, ...latest.order.filter(key => !isHomeCard(key))],
    hidden: [...next.hidden, ...latest.hidden.filter(key => !isHomeCard(key))] };
}
export const layoutSignature = (session: LayoutSession) => JSON.stringify([session.user?.role, session.user?.householdId, session.user?.id, session.user?.auth_version, session.csrf]);
export class HomeLayoutFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<LayoutSession>, job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (value: LayoutSession) => {
      if (epoch !== this.epoch || !current()) throw new LayoutDiscarded();
      if (value.user?.role !== 'member' || !value.csrf || layoutSignature(value) !== this.expected) throw new LayoutDiscarded('identity');
      return value.csrf;
    };
    const csrf = check(await me()); let result!: T, failure: unknown, failed = false;
    try { result = await job(csrf); } catch (error) { failed = true; failure = error; }
    check(await me()); if (failed) throw failure; return result;
  }
}
export async function checkedLayoutWrite<T>(guard: (job: (csrf: string) => Promise<T>) => Promise<T>, write: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => {
    try { return await write(csrf); }
    catch (error) {
      if (error instanceof LayoutError && [400, 409, 415, 422, 429].includes(error.status)) throw new LayoutRejected(error.message, error.status);
      throw error;
    }
  });
}
export async function layoutRequest(path: '/me' | '/dashboard-layout', signal: AbortSignal, payload?: HomeLayout, csrf = ''): Promise<unknown> {
  if (!['/me', '/dashboard-layout'].includes(path) || payload && (path !== '/dashboard-layout' || !csrf)) throw invalid();
  const controller = new AbortController(), deadline = performance.now() + 15_000;
  const abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new LayoutDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new LayoutError('连接中断，请先核对当前首页布局。'); };
  if (signal.aborted) throw new LayoutDiscarded();
  signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15_000);
  try {
    const response = await fetch('/api' + path, { method: payload ? 'PUT' : 'GET', mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(payload ? { 'X-CSRF-Token': csrf } : {}) }, ...(payload ? { body: JSON.stringify(payload) } : {}) });
    check(); if (response.redirected) throw invalid();
    if (!response.ok) throw new LayoutError(response.status === 409 ? '首页布局已被其他设备修改，请核对最新布局。' : response.status === 401 || response.status === 403
      ? '当前身份或权限需要重新核对。' : '未能保存或读取首页布局。', response.status);
    if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/json')) throw invalid();
    const result: unknown = await response.json(); check(); return result;
  } catch (error) { check(); if (error instanceof LayoutError || error instanceof LayoutDiscarded) throw error; throw new LayoutError('连接中断，请先核对当前首页布局。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
