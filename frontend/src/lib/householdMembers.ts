import type { Member } from './types';

export type HouseholdRole = 'admin' | 'member';
export type HouseholdMember = { id: string; name: string; householdRole: HouseholdRole; authVersion: number;
  activeSessionCount: number | null; capabilities: { changeRole: boolean; revokeSessions: boolean } };
export type MembersSnapshot = { currentMemberId: string; members: HouseholdMember[] };
export type MembersSession = { user: Member | null; csrf?: string | null };
export type MemberIntent = Readonly<{ targetId: string; targetName: string; kind: 'role' | 'revoke'; previousRole: HouseholdRole;
  body: Readonly<{ expectedAuthVersion: number; householdRole?: HouseholdRole }> }>;
export type MemberResult = { ok: true; member: { id: string; householdRole: HouseholdRole; authVersion: number }; revoked: number };
export class MembersError extends Error { constructor(message: string, public status = 0) { super(message); } }
export class MembersDiscarded extends Error {}
export class MembersRejected extends MembersError {}
const invalid = (): never => { throw new MembersError('成员信息暂时无法核对，请重新读取。'); };
const object = (v: unknown): Record<string, unknown> => { if (!v || typeof v !== 'object' || Array.isArray(v)) return invalid(); return v as Record<string, unknown>; };
const integer = (v: unknown, min = 0): number => { if (!Number.isSafeInteger(v) || Number(v) < min) return invalid(); return Number(v); };
const memberId = (v: unknown): string => { if (typeof v !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(v)) return invalid(); return v; };
const role = (v: unknown): HouseholdRole => { if (v !== 'admin' && v !== 'member') return invalid(); return v; };
const name = (v: unknown): string => { if (typeof v !== 'string' || !v.trim() || v.length > 80 || /[\x00-\x1f\x7f]/.test(v)) return invalid(); return v; };
const bool = (v: unknown): boolean => { if (typeof v !== 'boolean') return invalid(); return v; };
export function readMembers(raw: unknown, owner: string, authVersion: number): MembersSnapshot {
  const v = object(raw), currentMemberId = memberId(v.currentMemberId);
  if (currentMemberId !== memberId(owner) || !Array.isArray(v.members) || !v.members.length || v.members.length > 100) return invalid();
  const members = v.members.map(rawMember => { const m = object(rawMember), c = object(m.capabilities); return {
    id: memberId(m.id), name: name(m.name), householdRole: role(m.householdRole), authVersion: integer(m.authVersion, 1),
    activeSessionCount: m.activeSessionCount === null ? null : integer(m.activeSessionCount),
    capabilities: { changeRole: bool(c.changeRole), revokeSessions: bool(c.revokeSessions) },
  }; });
  const self = members.find(m => m.id === currentMemberId);
  if (!self || self.authVersion !== integer(authVersion, 1) || new Set(members.map(m => m.id)).size !== members.length) return invalid();
  for (const m of members) {
    if ((m.id === currentMemberId || self.householdRole !== 'admin') && (m.capabilities.changeRole || m.capabilities.revokeSessions)) return invalid();
    if (self.householdRole === 'admin' ? m.activeSessionCount === null : m.activeSessionCount !== null) return invalid();
  }
  return { currentMemberId, members };
}
export function memberIntent(snapshot: MembersSnapshot, targetId: string, kind: 'role' | 'revoke', nextRole?: HouseholdRole): MemberIntent {
  const self = snapshot.members.find(m => m.id === snapshot.currentMemberId);
  if (!self) return invalid();
  snapshot = readMembers(snapshot, self.id, self.authVersion);
  const target = snapshot.members.find(m => m.id === targetId);
  if (!target || target.id === snapshot.currentMemberId || !target.capabilities[kind === 'role' ? 'changeRole' : 'revokeSessions']) return invalid();
  if (kind !== 'role' && kind !== 'revoke') return invalid();
  if (kind === 'role' && (role(nextRole) === target.householdRole || nextRole === 'member' && snapshot.members.filter(m => m.householdRole === 'admin').length < 2)) return invalid();
  return Object.freeze({ targetId: target.id, targetName: target.name, kind, previousRole: target.householdRole,
    body: Object.freeze({ expectedAuthVersion: target.authVersion, ...(kind === 'role' ? { householdRole: nextRole } : {}) }) });
}
export function intentStillAllowed(intent: MemberIntent, snapshot: MembersSnapshot): boolean {
  try { const fresh = memberIntent(snapshot, intent.targetId, intent.kind, intent.body.householdRole);
    return fresh.body.expectedAuthVersion === intent.body.expectedAuthVersion && fresh.previousRole === intent.previousRole && fresh.targetName === intent.targetName;
  } catch { return false; }
}
export function readMemberResult(raw: unknown, intent: MemberIntent): MemberResult {
  const v = object(raw), m = object(v.member), version = integer(m.authVersion, 1);
  if (v.ok !== true || memberId(m.id) !== intent.targetId || version !== intent.body.expectedAuthVersion + 1
    || role(m.householdRole) !== (intent.kind === 'role' ? intent.body.householdRole : intent.previousRole)) return invalid();
  return { ok: true, member: { id: intent.targetId, authVersion: version, householdRole: role(m.householdRole) }, revoked: integer(v.revoked) };
}
/** A current list permits an explicit local acknowledgement, never an inferred write receipt. */
export type MemberReview = Readonly<{ intent: MemberIntent; identity: string; epoch: number }>;
export const canEndMemberReview = (review: MemberReview | null, intent: MemberIntent | null, identity: string, epoch: number): boolean =>
  !!review && !!intent && review.intent === intent && review.identity === identity && review.epoch === epoch;
export const membersSignature = (s: MembersSession) => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id, s.user?.auth_version, s.csrf]);
export class MembersFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<MembersSession>, job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (value: MembersSession) => {
      if (epoch !== this.epoch || !current()) throw new MembersDiscarded();
      if (!value || value.user?.role !== 'member' || typeof value.csrf !== 'string' || !value.csrf
        || !Number.isSafeInteger(value.user.auth_version) || Number(value.user.auth_version) < 1 || membersSignature(value) !== this.expected) throw new MembersDiscarded('identity');
      return value.csrf;
    };
    const csrf = check(await me()); let result!: T, failure: unknown, failed = false;
    try { result = await job(csrf); } catch (e) { failed = true; failure = e; }
    check(await me()); if (failed) throw failure; return result;
  }
}
export async function checkedMemberWrite<T>(guard: (job: (csrf: string) => Promise<T>) => Promise<T>, write: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => { try { return await write(csrf); } catch (e) {
    if (e instanceof MembersError && [400, 403, 404, 409, 415, 422, 429].includes(e.status)) throw new MembersRejected(e.message, e.status);
    throw e;
  } });
}
export async function membersRequest(path: string, signal: AbortSignal, options: { method?: 'GET' | 'POST' | 'PATCH'; payload?: unknown; csrf?: string } = {}): Promise<unknown> {
  const method = options.method || 'GET', writing = method !== 'GET';
  if (!writing && (!['/me', '/members'].includes(path) || options.payload !== undefined || options.csrf !== undefined)) return invalid();
  if (writing) {
    const match = /^\/members\/([A-Za-z0-9_-]{1,100})\/(role|revoke-sessions)$/.exec(path), p = object(options.payload);
    if (!match || method !== (match[2] === 'role' ? 'PATCH' : 'POST') || typeof options.csrf !== 'string' || !options.csrf) return invalid();
    if (Object.keys(p).sort().join('|') !== (match[2] === 'role' ? 'expectedAuthVersion|householdRole' : 'expectedAuthVersion')) return invalid();
    integer(p.expectedAuthVersion, 1); if (match[2] === 'role') role(p.householdRole);
  }
  const controller = new AbortController(), deadline = performance.now() + 15000, abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new MembersDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new MembersError('连接中断，请重新核对当前成员状态。'); };
  check(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15000);
  try {
    const response = await fetch('/api' + path, { method, mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal,
      headers: { Accept: 'application/json', ...(writing ? { 'Content-Type': 'application/json', 'X-CSRF-Token': options.csrf! } : {}) }, ...(writing ? { body: JSON.stringify(options.payload) } : {}) });
    check(); if (response.redirected) return invalid();
    if (!response.ok) throw new MembersError(response.status === 409 ? '成员状态已变化，请重新读取后再选择。' : [401, 403].includes(response.status)
      ? '登录身份或管理权限已变化，请重新核对。' : response.status === 404 ? '成员暂时无法读取，请核对当前家庭。' : '暂时无法处理，请重新核对成员状态。', response.status);
    if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get('Content-Type') || '')) return invalid();
    if (Number(response.headers.get('Content-Length') || 0) > 128000 || !response.body) return invalid();
    const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
    try { while (true) { const part = await reader.read(); check(); if (part.done) break; size += part.value.byteLength;
      if (size > 128000) { await reader.cancel(); return invalid(); } chunks.push(part.value); }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const raw: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); check(); return raw;
  } catch (e) { check(); if (e instanceof MembersError || e instanceof MembersDiscarded) throw e; throw new MembersError('暂时无法核对成员状态，请重新读取。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
