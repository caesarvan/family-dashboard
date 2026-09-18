/** Planned membership API contracts. This module never persists credentials. */
export class MembershipError extends Error { constructor(message: string, public status = 0, public code = '') { super(message); } }
export class MembershipDiscarded extends Error {}
export const invalidMembership = (): never => { throw new MembershipError('暂时无法核对返回的信息，请重新读取。'); };
export const record = (v: unknown): Record<string, unknown> => !v || typeof v !== 'object' || Array.isArray(v) ? invalidMembership() : v as Record<string, unknown>;
export const boundedText = (v: unknown, limit = 120): string => typeof v === 'string' && !!v.trim() && v.length <= limit && !/[\x00-\x1f\x7f]/.test(v) ? v : invalidMembership();
export const version = (v: unknown): number => Number.isSafeInteger(v) && Number(v) >= 1 ? Number(v) : invalidMembership();
export const hexId = (v: unknown): string => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v) ? v : invalidMembership();
export const memberId = (v: unknown): string => typeof v === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(v) ? v : invalidMembership();
export const householdId = (v: unknown): string => v === 'default' || typeof v === 'string' && /^[a-f0-9]{24}$/.test(v) ? v : invalidMembership();
export const loginName = (v: unknown): string => typeof v === 'string' && /^[a-z0-9][a-z0-9._-]{2,63}$/.test(v) ? v : invalidMembership();
export const passwordValue = (v: unknown): string => typeof v === 'string' && v.length >= 12 && v.length <= 128 ? v : invalidMembership();
const legacyPassword = (v: unknown): string => typeof v === 'string' && v.length > 0 && v.length <= 512 ? v : invalidMembership();
export type Account = { id: string; login: string };
export type AccountSession = { account: Account | null; csrf: string; authVersion: number | null; authenticationGeneration: number };
export type MemberSession = { user: null | { id: string; householdId: string; role: 'member' | 'tv'; auth_version: number; membershipRevision: number;
  accountId?: string; accountAuthVersion?: number; authenticationGeneration?: number }; csrf: string | null };
export type MembershipIdentity = { account: AccountSession; member: MemberSession };
export function readAccount(v: unknown): Account { const r = record(v); return { id: hexId(r.id), login: loginName(r.login) }; }
export function readAccountSession(v: unknown): AccountSession {
  const r = record(v), account = r.account === null ? null : readAccount(r.account);
  if (!Number.isSafeInteger(r.authenticationGeneration) || Number(r.authenticationGeneration) < 0 || !account && r.authVersion !== null) return invalidMembership();
  return { account, csrf: boundedText(r.csrf, 512), authVersion: account ? version(r.authVersion) : null, authenticationGeneration: Number(r.authenticationGeneration) };
}
export function readMemberSession(v: unknown): MemberSession {
  const r = record(v); if (r.user === null) return { user: null, csrf: null };
  const u = record(r.user); if (u.role !== 'member' && u.role !== 'tv') return invalidMembership();
  return { user: { id: memberId(u.id), householdId: householdId(u.householdId), role: u.role,
    auth_version: u.role === 'member' ? version(u.auth_version) : 0, membershipRevision: u.role === 'member' ? version(u.membershipRevision) : 0,
    ...(u.accountId === undefined ? {} : { accountId: hexId(u.accountId) }), ...(u.accountAuthVersion === undefined ? {} : { accountAuthVersion: version(u.accountAuthVersion) }),
    ...(u.authenticationGeneration === undefined ? {} : { authenticationGeneration: version(u.authenticationGeneration) }) }, csrf: u.role === 'member' ? boundedText(r.csrf, 512) : null };
}
export const accountSignature = (s: AccountSession) => JSON.stringify([s.account?.id, s.account?.login, s.authVersion, s.authenticationGeneration, s.csrf]);
export const memberSignature = (s: MemberSession) => JSON.stringify([s.user?.role, s.user?.householdId, s.user?.id, s.user?.auth_version, s.user?.membershipRevision,
  s.user?.accountId, s.user?.accountAuthVersion, s.user?.authenticationGeneration, s.csrf]);
export const identitySignature = (s: MembershipIdentity) => accountSignature(s.account) + memberSignature(s.member);
export function newMembershipRequestId(): string {
  if (!globalThis.crypto?.getRandomValues) throw new MembershipError('当前环境无法安全生成操作编号。');
  return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
}
export type OperationState = null | 'pending' | 'completed' | 'not_committed';
export type Operation<T = unknown> = { requestId: string; found: boolean; state: OperationState; result: T | null };
export function readOperation<T>(v: unknown, requestId: string, result: (v: unknown) => T): Operation<T> {
  const r = record(v); if (hexId(r.requestId) !== hexId(requestId) || typeof r.found !== 'boolean') return invalidMembership();
  if (!r.found) { if (r.state !== null || r.result !== null) return invalidMembership(); return { requestId, found: false, state: null, result: null }; }
  if (!['pending', 'completed', 'not_committed'].includes(String(r.state))) return invalidMembership();
  if (r.state !== 'completed' && r.result !== null) return invalidMembership();
  return { requestId, found: true, state: r.state as OperationState, result: r.state === 'completed' ? result(r.result) : null };
}
export const canStartNewMembershipOperation = (op: Operation | null) => !!op?.found && op.state === 'not_committed';
export class MembershipFence {
  private epoch = 0;
  constructor(private identity: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<MembershipIdentity>, work: (identity: MembershipIdentity) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (s: MembershipIdentity) => { if (!current() || epoch !== this.epoch) throw new MembershipDiscarded();
      if (identitySignature(s) !== this.identity) throw new MembershipDiscarded('identity'); return s; };
    const before = check(await me()); let result!: T, failure: unknown, failed = false;
    try { result = await work(before); } catch (e) { failed = true; failure = e; }
    check(await me()); if (failed) throw failure; return result;
  }
}

type Method = 'GET' | 'POST';
export type MembershipRequest = { method?: Method; payload?: Record<string, unknown>; csrf?: string; memberCsrf?: string; accountCsrf?: string };
const sameKeys = (p: Record<string, unknown>, keys: string[]) => Object.keys(p).sort().join('|') === keys.slice().sort().join('|');
/** Allowlist is deliberately independent of UI visibility and never accepts owner selectors. */
export function validateMembershipRequest(path: string, options: MembershipRequest): void {
  const method = options.method || 'GET';
  if (method === 'GET') {
    if (!['/account/me', '/me', '/account/households', '/spaces/current', '/members', '/member-invitations', '/memberships?status=all'].includes(path)
      && !/^\/(?:account\/operations|membership-operations)\/[a-f0-9]{32}$/.test(path)) return invalidMembership();
    if (options.payload !== undefined || options.csrf !== undefined || options.memberCsrf !== undefined || options.accountCsrf !== undefined) return invalidMembership(); return;
  }
  if (method !== 'POST') return invalidMembership();
  const p = record(options.payload); boundedText(options.csrf, 512);
  let keys: string[];
  if (path === '/account/login') { keys = ['login', 'password']; loginName(p.login); passwordValue(p.password); }
  else if (path === '/account/eligibility') { keys = ['memberPassword']; legacyPassword(p.memberPassword); }
  else if (path === '/account/register') { keys = ['requestId', 'login', 'password', 'eligibilityToken']; loginName(p.login); passwordValue(p.password); boundedText(p.eligibilityToken, 2048); }
  else if (path === '/account/logout') keys = ['requestId'];
  else if (path === '/account/switch-household') { keys = ['requestId', 'membershipId', 'expectedRevision']; hexId(p.membershipId); version(p.expectedRevision); }
  else if (path === '/membership-links') { keys = ['requestId', 'memberPassword', 'expectedAuthVersion', 'expectedRevision']; legacyPassword(p.memberPassword); version(p.expectedAuthVersion); version(p.expectedRevision); }
  else if (path === '/member-invitations') { keys = ['requestId', 'expectedAuthVersion']; version(p.expectedAuthVersion); }
  else if (/^\/member-invitations\/[a-f0-9]{32}\/revoke$/.test(path)) { keys = ['requestId', 'expectedRevision']; version(p.expectedRevision); }
  else if (path === '/account/invitations/inspect') { keys = ['householdSlug', 'token']; if (typeof p.householdSlug !== 'string' || !/^[a-z][a-z0-9-]{2,31}$/.test(p.householdSlug)) return invalidMembership(); boundedText(p.token, 2048); }
  else if (path === '/account/invitations/accept') { keys = ['requestId', 'joinTicket']; boundedText(p.joinTicket, 2048); }
  else if (/^\/memberships\/[A-Za-z0-9_-]{1,100}\/remove$/.test(path) || path === '/memberships/self/leave') { keys = ['requestId', 'expectedRevision', 'expectedAuthVersion']; version(p.expectedRevision); version(p.expectedAuthVersion); }
  else if (/^\/account\/operations\/[a-f0-9]{32}\/resume$/.test(path)) keys = [];
  else return invalidMembership();
  if (!sameKeys(p, keys)) return invalidMembership(); if (keys.includes('requestId')) hexId(p.requestId);
  if (path === '/account/eligibility') boundedText(options.memberCsrf, 512); else if (options.memberCsrf !== undefined) return invalidMembership();
  if (['/membership-links', '/memberships/self/leave'].includes(path)) boundedText(options.accountCsrf, 512); else if (options.accountCsrf !== undefined) return invalidMembership();
}
export async function membershipRequest(path: string, signal: AbortSignal, options: MembershipRequest = {}): Promise<unknown> {
  validateMembershipRequest(path, options);
  const method = options.method || 'GET', controller = new AbortController(), deadline = performance.now() + 15000;
  const abort = () => controller.abort(), check = () => { if (signal.aborted) throw new MembershipDiscarded();
    if (controller.signal.aborted || performance.now() >= deadline) throw new MembershipError('连接中断，请核对原操作。'); };
  check(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 15000);
  try {
    const response = await fetch('/api' + path, { method, credentials: 'same-origin', mode: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal,
      headers: { Accept: 'application/json', ...(method === 'POST' ? { 'Content-Type': 'application/json', 'X-CSRF-Token': options.csrf!,
        ...(options.memberCsrf ? { 'X-Member-CSRF-Token': options.memberCsrf } : {}), ...(options.accountCsrf ? { 'X-Account-CSRF-Token': options.accountCsrf } : {}) } : {}) }, ...(method === 'POST' ? { body: JSON.stringify(options.payload) } : {}) });
    check(); if (response.redirected || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('Content-Type') || '') || !response.body || Number(response.headers.get('Content-Length') || 0) > 512000)
      throw new MembershipError('暂时无法核对返回的信息。', response.ok ? 0 : response.status);
    const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
    try { while (true) { const part = await reader.read(); check(); if (part.done) break; size += part.value.byteLength;
      if (size > 512000) { await reader.cancel(); throw new MembershipError('返回的信息过大，请重新读取。'); } chunks.push(part.value); } } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(size); let offset = 0; for (const part of chunks) { bytes.set(part, offset); offset += part.length; }
    const raw: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); check();
    if (!response.ok) { const error = record(raw); throw new MembershipError(typeof error.error === 'string' && error.error.length <= 300 ? error.error : '暂时无法完成，请重新核对。', response.status,
      typeof error.code === 'string' ? error.code.slice(0, 80) : ''); } return raw;
  } catch (e) { check(); if (e instanceof MembershipError || e instanceof MembershipDiscarded) throw e; throw new MembershipError('暂时无法确认结果，请核对原操作。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
export async function readMembershipIdentity(signal: AbortSignal): Promise<MembershipIdentity> {
  const account = readAccountSession(await membershipRequest('/account/me', signal));
  const member = readMemberSession(await membershipRequest('/me', signal));
  const after = readAccountSession(await membershipRequest('/account/me', signal));
  if (accountSignature(account) !== accountSignature(after)) throw new MembershipDiscarded('identity');
  const user = member.user;
  if (user?.accountId !== undefined && (user.accountId !== account.account?.id || user.accountAuthVersion !== account.authVersion
    || user.authenticationGeneration !== account.authenticationGeneration)) throw new MembershipDiscarded('identity');
  return { account, member };
}
