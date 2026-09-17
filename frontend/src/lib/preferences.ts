import type { Member, Preferences } from './types';

export type PreferenceChanges = Partial<Pick<Preferences, 'theme' | 'colorMode' | 'density' | 'homeView'>>;
export type PreferencePayload = { revision: number; changes: PreferenceChanges };
export type PreferenceSession = { user: Member | null; csrf?: string | null };
export class PreferenceError extends Error { constructor(message: string, public status = 0) { super(message); } }
export class PreferenceDiscarded extends Error {}
export class PreferenceRejected extends PreferenceError {}
const choices = { theme: ['forest', 'light', 'ocean'], colorMode: ['light', 'dark'], density: ['comfortable', 'compact'], homeView: ['today', 'week', 'around'] } as const;
const keys = Object.keys(choices) as (keyof PreferenceChanges)[];
const invalid = () => new PreferenceError('显示设置暂时无法核对，请重新读取。');
const record = (raw: unknown): Record<string, unknown> => {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw invalid();
  return raw as Record<string, unknown>;
};
export function readPreferences(raw: unknown): Preferences {
  const value = record(raw);
  if (!Number.isSafeInteger(value.revision) || Number(value.revision) < 0
    || keys.some(key => typeof value[key] !== 'string' || !(choices[key] as readonly string[]).includes(value[key] as string))) throw invalid();
  return { revision: Number(value.revision), theme: value.theme as Preferences['theme'], colorMode: value.colorMode as Preferences['colorMode'],
    density: value.density as Preferences['density'], homeView: value.homeView as Preferences['homeView'] };
}
export function readPreferencePayload(raw: unknown): PreferencePayload {
  const value = record(raw), changes = record(value.changes), names = Object.keys(changes);
  if (Object.keys(value).sort().join('|') !== 'changes|revision' || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0 || !names.length
    || names.some(key => !keys.includes(key as keyof PreferenceChanges) || typeof changes[key] !== 'string'
      || !(choices[key as keyof PreferenceChanges] as readonly string[]).includes(changes[key] as string))) throw invalid();
  return { revision: Number(value.revision), changes: { ...changes } as PreferenceChanges };
}
export function preferencesPayload(base: Preferences, draft: Preferences): PreferencePayload {
  base = readPreferences(base); draft = readPreferences(draft);
  return readPreferencePayload({ revision: base.revision, changes: Object.fromEntries(keys.filter(key => base[key] !== draft[key]).map(key => [key, draft[key]])) });
}
export const samePreferences = (a: Preferences, b: Preferences) => keys.every(key => a[key] === b[key]);
/** Apply only the user's changed fields to a newly acknowledged revision. */
export function rebasePreferences(base: Preferences, draft: Preferences, latest: Preferences): Preferences {
  latest = readPreferences(latest);
  if (samePreferences(base, draft)) return latest;
  return readPreferences({ ...latest, ...preferencesPayload(base, draft).changes });
}
export function acceptPreferences(current: Preferences, next: unknown, expectedIdentity: string, actualIdentity: string): Preferences | null {
  if (expectedIdentity !== actualIdentity) return null;
  const candidate = readPreferences(next);
  return candidate.revision < current.revision ? current : candidate;
}
export const preferenceSignature = (session: PreferenceSession) => JSON.stringify([session.user?.role, session.user?.householdId, session.user?.id, session.user?.auth_version, session.csrf]);
export class PreferenceFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<PreferenceSession>, job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (value: PreferenceSession) => {
      if (epoch !== this.epoch || !current()) throw new PreferenceDiscarded();
      if (!value || typeof value !== 'object' || value.user?.role !== 'member' || !value.csrf || preferenceSignature(value) !== this.expected) throw new PreferenceDiscarded('identity');
      return value.csrf;
    };
    const csrf = check(await me()); let result!: T, failure: unknown, failed = false;
    try { result = await job(csrf); } catch (error) { failed = true; failure = error; }
    check(await me()); if (failed) throw failure; return result;
  }
}
/** Only a PUT error followed by successful identity verification is definitive. */
export async function checkedPreferenceWrite<T>(guard: (job: (csrf: string) => Promise<T>) => Promise<T>, write: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => {
    try { return await write(csrf); }
    catch (error) {
      if (error instanceof PreferenceError && [400, 409, 415, 422, 429].includes(error.status)) throw new PreferenceRejected(error.message, error.status);
      throw error;
    }
  });
}
export async function preferenceRequest(path: '/me' | '/preferences', signal: AbortSignal, payload?: PreferencePayload, csrf = ''): Promise<unknown> {
  if (!['/me', '/preferences'].includes(path) || payload && (path !== '/preferences' || !csrf)) throw invalid();
  const body = payload ? JSON.stringify(readPreferencePayload(payload)) : undefined;
  const controller = new AbortController(), deadline = performance.now() + 15_000;
  const abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new PreferenceDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new PreferenceError('连接中断，请先核对当前显示设置。'); };
  if (signal.aborted) throw new PreferenceDiscarded();
  signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15_000);
  try {
    const response = await fetch('/api' + path, { method: payload ? 'PUT' : 'GET', mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(payload ? { 'X-CSRF-Token': csrf } : {}) }, ...(body ? { body } : {}) });
    check(); if (response.redirected) throw invalid();
    if (!response.ok) throw new PreferenceError(response.status === 409 ? '显示设置已变化，请查看最新设置后再次选择。' : response.status === 401 || response.status === 403
      ? '当前身份或权限需要重新核对。' : '未能保存或读取显示设置。', response.status);
    if (!response.headers.get('Content-Type')?.toLowerCase().includes('application/json')) throw invalid();
    const result: unknown = await response.json(); check(); return result;
  } catch (error) { check(); if (error instanceof PreferenceError || error instanceof PreferenceDiscarded) throw error; throw new PreferenceError('连接中断，请先核对当前显示设置。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
