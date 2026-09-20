import { readJourneyScope, journeyCanStart, type JourneyReview } from './tvTripRecap.ts';
import { sessionIdentity } from './sessionIdentity.ts';
import type { CalendarMode, Member, Person } from './types';
import { isOwnerId } from './memberId.ts';

export const deviceCards = ['calendar', 'finance', 'tasks', 'shopping', 'trips'] as const;
export type DeviceCard = typeof deviceCards[number];
export const deviceCardNames: Record<DeviceCard, string> = { calendar: '日程安排', finance: '家庭财务', tasks: '共同待办', shopping: '采购清单', trips: '下一趟旅行' };
export type DeviceLayout = { order: DeviceCard[]; hidden: DeviceCard[]; theme: 'forest' | 'light' | 'ocean'; density: 'comfortable' | 'compact' };
export type Device = { id: string; name: string; focus: string; calendarView: CalendarMode; revision: number; created_at: string; layout: DeviceLayout };
export type DeviceDraft = Pick<Device, 'name' | 'focus' | 'calendarView' | 'layout'>;
export type PairDraft = { code: string; name: string; focus: string; calendarView: CalendarMode };
export type Playback = { scope?: 'all' | 'journey'; journeyReview?: JourneyReview | null; deviceId: string; revision: number; mode: 'dashboard' | 'photos'; paused: boolean; intervalSeconds: number; position: number; photoCount: number; canStart: boolean; updatedAt: string | null };
export type PlaybackAction = 'start' | 'dashboard' | 'pause' | 'resume' | 'previous' | 'next' | 'interval';
export type DeviceSession = { user: Member | null; csrf?: string | null };
export type DeviceIntent = { kind: 'pair' | 'settings' | 'revoke' | 'playback'; path: string; method: 'POST' | 'PATCH' | 'DELETE' | 'PUT'; body: Record<string, unknown>; deviceId?: string };
const invalid = () => new Error('电视数据无法核对，请重新读取。');
const object = (value: unknown): Record<string, any> => { if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(); return value; };
const integer = (value: unknown, min: number, max = Number.MAX_SAFE_INTEGER): value is number => Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max;
export const isDeviceId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{24}$/.test(value);
export const defaultDeviceLayout = (): DeviceLayout => ({ order: [...deviceCards], hidden: [], theme: 'forest', density: 'comfortable' });
export function readDeviceLayout(raw: unknown): DeviceLayout {
  const value = object(raw), keys = Object.keys(value);
  if (keys.length !== 4 || keys.some(key => !['order', 'hidden', 'theme', 'density'].includes(key))
    || !Array.isArray(value.order) || value.order.length !== 5 || new Set(value.order).size !== 5 || value.order.some((key: unknown) => !deviceCards.includes(key as DeviceCard))
    || !Array.isArray(value.hidden) || value.hidden.length > 4 || new Set(value.hidden).size !== value.hidden.length || value.hidden.some((key: unknown) => !deviceCards.includes(key as DeviceCard))
    || !['forest', 'light', 'ocean'].includes(value.theme) || !['comfortable', 'compact'].includes(value.density)) throw invalid();
  return { order: [...value.order], hidden: value.order.filter((key: DeviceCard) => value.hidden.includes(key)), theme: value.theme, density: value.density };
}
export function readDevices(raw: unknown): Device[] {
  if (!Array.isArray(raw)) throw invalid();
  const result = raw.map(entry => {
    const value = object(entry);
    if (!isDeviceId(value.id) || typeof value.name !== 'string' || !value.name || Array.from(value.name).length > 30 || typeof value.focus !== 'string'
      || !isOwnerId(value.focus) || !['today', 'week', 'around'].includes(value.calendarView)
      || !integer(value.revision, 1) || typeof value.created_at !== 'string') throw invalid();
    return { id: value.id, name: value.name, focus: value.focus, calendarView: value.calendarView, revision: value.revision, created_at: value.created_at, layout: readDeviceLayout(value.layout) } as Device;
  });
  if (new Set(result.map(row => row.id)).size !== result.length) throw invalid();
  return result;
}
export function deviceDraft(device: Device): DeviceDraft { return { name: device.name, focus: device.focus, calendarView: device.calendarView, layout: readDeviceLayout(device.layout) }; }
function fields(draft: Pick<DeviceDraft, 'name' | 'focus' | 'calendarView'>, people: Person[]) {
  const name = draft.name.trim();
  if (!name || Array.from(name).length > 30 || /[\u0000-\u001f\u007f]/.test(name)) throw new Error('电视名称请填写 1～30 个字符。');
  if (draft.focus !== 'shared' && !people.some(person => person.id === draft.focus)) throw new Error('请重新选择侧重成员。');
  if (!isOwnerId(draft.focus) || !['today', 'week', 'around'].includes(draft.calendarView)) throw new Error('请重新选择侧重成员和日程范围。');
  return { name, focus: draft.focus, calendarView: draft.calendarView };
}
export function pairPayload(draft: PairDraft, people: Person[]): Record<string, unknown> {
  const code = draft.code.replace(/\s/g, '').toUpperCase();
  if (!/^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/.test(code)) throw new Error('请输入电视上显示的 8 位配对码。');
  return { code, ...fields(draft, people) };
}
export function devicePayload(draft: DeviceDraft, original: Device, people: Person[]): Record<string, unknown> {
  if (!isDeviceId(original.id) || !integer(original.revision, 1)) throw invalid();
  return { revision: original.revision, ...fields(draft, people), layout: readDeviceLayout(draft.layout) };
}
export function sameDeviceSettings(a: DeviceDraft, b: DeviceDraft): boolean {
  return a.name === b.name && a.focus === b.focus && a.calendarView === b.calendarView && JSON.stringify(a.layout) === JSON.stringify(b.layout);
}
export function moveDeviceCard(layout: DeviceLayout, key: DeviceCard, direction: -1 | 1): DeviceLayout {
  const result = readDeviceLayout(layout), index = result.order.indexOf(key), next = index + direction;
  if (index >= 0 && next >= 0 && next < result.order.length) [result.order[index], result.order[next]] = [result.order[next], result.order[index]];
  return readDeviceLayout(result);
}
export function toggleDeviceCard(layout: DeviceLayout, key: DeviceCard): DeviceLayout {
  const result = readDeviceLayout(layout);
  if (result.hidden.includes(key)) result.hidden = result.hidden.filter(value => value !== key);
  else { if (result.hidden.length === 4) throw new Error('至少保留一张可见卡片。'); result.hidden.push(key); }
  return readDeviceLayout(result);
}
export function readPlayback(raw: unknown, deviceId: string): Playback {
  const value = object(raw), scope = readJourneyScope(value);
  if (!isDeviceId(deviceId) || value.deviceId !== deviceId || !integer(value.revision, 0) || !['dashboard', 'photos'].includes(value.mode)
    || typeof value.paused !== 'boolean' || !integer(value.intervalSeconds, 5, 120) || !integer(value.position, 0, 1000000)
    || !integer(value.photoCount, 0, 2000) || typeof value.canStart !== 'boolean' || value.canStart !== journeyCanStart(scope.journeyReview, value.photoCount)
    || value.updatedAt !== null && typeof value.updatedAt !== 'string') throw invalid();
  return { ...scope, deviceId, revision: value.revision, mode: value.mode, paused: value.paused, intervalSeconds: value.intervalSeconds,
    position: value.position, photoCount: value.photoCount, canStart: value.canStart, updatedAt: value.updatedAt };
}
export function playbackPayload(state: Playback, action: PlaybackAction, interval = ''): Record<string, unknown> {
  readPlayback(state, state.deviceId);
  if (!['start', 'dashboard', 'pause', 'resume', 'previous', 'next', 'interval'].includes(action)) throw invalid();
  if (action === 'start' && !state.canStart && state.scope !== 'journey') throw new Error('这台电视还没有可播放的授权照片。');
  if (['pause', 'resume', 'previous', 'next'].includes(action) && state.mode !== 'photos') throw new Error('请先开始照片播放。');
  if (['previous', 'next'].includes(action) && !state.photoCount) throw new Error('当前旅行没有可切换的授权媒体。');
  if (action === 'interval') {
    if (!/^\d{1,3}$/.test(interval.trim()) || !integer(Number(interval.trim()), 5, 120)) throw new Error('轮播间隔请填写 5～120 的整数秒。');
    return { revision: state.revision, action, intervalSeconds: Number(interval.trim()) };
  }
  return { revision: state.revision, action };
}
export const deviceSignature = sessionIdentity;
export class DeviceDiscarded extends Error {}
export class DeviceFence {
  private epoch = 0;
  constructor(private me: () => Promise<DeviceSession>, private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (session: DeviceSession) => {
      if (!current() || epoch !== this.epoch) throw new DeviceDiscarded();
      if (session.user?.role !== 'member' || !session.csrf || deviceSignature(session) !== this.expected) throw new DeviceDiscarded('identity');
      return session.csrf;
    };
    const csrf = check(await this.me()); let value!: T, failure: unknown, rejected = false;
    try { value = await job(csrf); } catch (caught) { failure = caught; rejected = true; }
    check(await this.me()); if (rejected) throw failure; return value;
  }
}
export class DeviceWriteRejected extends Error { constructor(public status: number, message: string) { super(message); } }
// Only a mutation's own rejection, followed by a successful identity check, is
// definitive. An error from either /me is never proof that a write did not run.
export async function checkedDeviceMutation<T>(guard: (job: (csrf: string) => Promise<T>) => Promise<T>, write: (csrf: string) => Promise<T>, status: (error: unknown) => number | undefined): Promise<T> {
  return guard(async csrf => {
    try { return await write(csrf); }
    catch (failure) {
      const code = status(failure);
      if (code && [400, 404, 409, 410, 415, 422, 429].includes(code)) throw new DeviceWriteRejected(code, failure instanceof Error ? failure.message : '操作未保存。');
      throw failure;
    }
  });
}
