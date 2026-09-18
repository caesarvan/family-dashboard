import { accountSignature, identitySignature, memberSignature, boundedText, hexId, householdId, invalidMembership, memberId, readAccount, readOperation, record, version, type Account,
  type MembershipIdentity, type Operation } from './personalAccounts';

export type Membership = { id: string; householdId: string; memberId: string; memberName: string;
  householdRole: 'admin' | 'member'; state: 'active' | 'left' | 'removed'; revision: number };
export type MyHousehold = Omit<Membership, 'state'> & { name: string; slug: string };
export type Households = { memberships: MyHousehold[]; unavailable: { householdId: string; code: 'temporarily_unavailable' }[] };
export type Invitation = { id: string; state: 'pending' | 'used' | 'revoked' | 'expired' | 'invalid'; revision: number; expiresAt: string; householdRole: 'member' };
export type InvitationCreated = { invitation: Invitation; token: string | null };
export type JoinPreview = { household: { id: string; name: string; slug: string }; householdRole: 'member'; joinTicket: string; eligibilityToken: string; expiresAt: string };
export type SwitchResult = { ok: true; householdId: string; memberId: string; entry: '/app/home' };
export type MembershipResult = Membership | InvitationCreated | Invitation | SwitchResult | { account: Account } | { ok: true };
export type MembershipAction = 'register' | 'logout' | 'link' | 'switch' | 'invite' | 'revoke' | 'accept' | 'remove' | 'leave';
export type MembershipHandle = { requestId: string; action: MembershipAction; scope: 'account' | 'member';
  accountId: string | null; login: string | null; householdId: string | null; memberId: string | null;
  targetId?: string; historical?: boolean; retry?: { path: string; body: Record<string, unknown> }; operation: Operation<MembershipResult> | null };
export const roleLabel = (r: Membership['householdRole']) => r === 'admin' ? '管理员' : '普通成员';
export const stateLabel = (s: Membership['state']) => ({ active: '已加入', left: '已退出', removed: '已移除' })[s];
const slug = (v: unknown): string => typeof v === 'string' && /^(?:home|[a-z][a-z0-9-]{2,31})$/.test(v) ? v : invalidMembership();
const dateTime = (v: unknown): string => typeof v === 'string' && v.length <= 64 && /(?:Z|[+-]\d{2}:?\d{2})$/.test(v) && Number.isFinite(Date.parse(v)) ? v : invalidMembership();
const rows = (v: unknown): unknown[] => Array.isArray(v) && v.length <= 1000 ? v : invalidMembership();
const unique = <T extends { id: string }>(items: T[]): T[] => new Set(items.map(v => v.id)).size === items.length ? items : invalidMembership();
export function readCurrentHousehold(raw: unknown, expected: string) {
  const r = record(raw); if (householdId(r.id) !== expected) return invalidMembership();
  return { id: expected, name: boundedText(r.name, 40), slug: slug(r.slug) };
}
export function readMembership(raw: unknown): Membership {
  const r = record(raw); if (!['admin', 'member'].includes(String(r.householdRole)) || !['active', 'left', 'removed'].includes(String(r.state))) return invalidMembership();
  return { id: hexId(r.id), householdId: householdId(r.householdId), memberId: memberId(r.memberId), memberName: boundedText(r.memberName, 80),
    householdRole: r.householdRole as Membership['householdRole'], state: r.state as Membership['state'], revision: version(r.revision) };
}
export function readMemberships(raw: unknown, expectedHousehold: string): Membership[] {
  const values = unique(rows(record(raw).memberships).map(readMembership));
  if (values.some(v => v.householdId !== expectedHousehold) || new Set(values.map(v => v.memberId)).size !== values.length) return invalidMembership(); return values;
}
export function readHouseholds(raw: unknown): Households {
  const r = record(raw), memberships = unique(rows(r.memberships).map(v => { const row = record(v), base = readMembership({ ...row, state: 'active' });
    const { state: _, ...membership } = base; return { ...membership, name: boundedText(row.name, 40), slug: slug(row.slug) }; }));
  const unavailable = rows(r.unavailable).map(v => { const row = record(v); if (row.code !== 'temporarily_unavailable') return invalidMembership();
    return { householdId: householdId(row.householdId), code: 'temporarily_unavailable' as const }; });
  const ids = [...memberships.map(v => v.householdId), ...unavailable.map(v => v.householdId)];
  if (ids.length > 30 || new Set(ids).size !== ids.length) return invalidMembership(); return { memberships, unavailable };
}
export function readInvitation(raw: unknown): Invitation {
  const r = record(raw); if (r.householdRole !== 'member' || !['pending', 'used', 'revoked', 'expired', 'invalid'].includes(String(r.state))) return invalidMembership();
  return { id: hexId(r.id), state: r.state as Invitation['state'], revision: version(r.revision), expiresAt: dateTime(r.expiresAt), householdRole: 'member' };
}
export const readInvitations = (v: unknown): Invitation[] => unique(rows(record(v).invitations).map(readInvitation));
export function readInvitationCreated(v: unknown, receipt = false): InvitationCreated {
  const r = record(v); if (receipt && r.token !== undefined && r.token !== null) return invalidMembership();
  return { invitation: readInvitation(r.invitation), token: r.token === undefined || r.token === null ? null : boundedText(r.token, 2048) };
}
export function readJoinPreview(raw: unknown): JoinPreview {
  const r = record(raw), h = record(r.household); if (r.householdRole !== 'member') return invalidMembership();
  return { household: { id: householdId(h.id), name: boundedText(h.name, 40), slug: slug(h.slug) }, householdRole: 'member',
    joinTicket: boundedText(r.joinTicket, 2048), eligibilityToken: boundedText(r.eligibilityToken, 2048), expiresAt: dateTime(r.expiresAt) };
}
export function readMembershipResult(action: MembershipAction, raw: unknown, receipt = false): MembershipResult {
  const r = record(raw);
  if (action === 'invite') return readInvitationCreated(r, receipt);
  if (action === 'revoke') return { invitation: readInvitation(r.invitation), token: null };
  if (action === 'register') return { account: readAccount(r.account) };
  if (action === 'logout') { if (r.ok !== true) return invalidMembership(); return { ok: true }; }
  if (action === 'switch') { if (r.ok !== true || r.entry !== '/app/home') return invalidMembership(); return { ok: true, householdId: householdId(r.householdId), memberId: memberId(r.memberId), entry: '/app/home' }; }
  return readMembership(r);
}
export function readMembershipWriteReply(handle: MembershipHandle, raw: unknown): Operation<MembershipResult> {
  const r = record(raw);
  if ('requestId' in r || 'found' in r) return readOperation(r, handle.requestId, result => validateResultTarget(handle, readMembershipResult(handle.action, result, true)));
  return { requestId: handle.requestId, found: true, state: 'completed', result: validateResultTarget(handle, readMembershipResult(handle.action, r)) };
}
export function operationBelongsTo(handle: MembershipHandle, identity: MembershipIdentity): boolean {
  if (handle.scope === 'account') return handle.accountId ? handle.accountId === identity.account.account?.id
    : handle.action === 'register' && !!handle.login && handle.login === identity.account.account?.login;
  return identity.member.user?.role === 'member' && handle.memberId === identity.member.user.id && handle.householdId === identity.member.user.householdId;
}
export function validateResultTarget(handle: MembershipHandle, result: MembershipResult): MembershipResult {
  // Historical lookups are authorized by the server and parsed by action; they never replay a write.
  if (handle.historical) return result;
  if (['link', 'remove', 'leave'].includes(handle.action)) {
    if (!('memberId' in result) || !('state' in result) || result.householdId !== handle.householdId || result.memberId !== (handle.targetId || handle.memberId)) return invalidMembership();
  }
  if (handle.action === 'revoke' && (!('invitation' in result) || result.invitation.id !== handle.targetId || result.invitation.state !== 'revoked')) return invalidMembership();
  if (handle.action === 'register' && (!('account' in result) || result.account.login !== handle.login)) return invalidMembership();
  if (handle.action === 'switch' && (!('entry' in result) || result.householdId !== handle.targetId)) return invalidMembership();
  if (handle.action === 'accept' && (!('state' in result) || !('householdId' in result) || result.householdId !== handle.targetId || result.state !== 'active')) return invalidMembership();
  if (handle.action === 'leave' && 'state' in result && result.state !== 'left' || handle.action === 'remove' && 'state' in result && result.state !== 'removed') return invalidMembership();
  return result;
}
export function acceptedMembershipTransition(before: MembershipIdentity, after: MembershipIdentity, action: MembershipAction | 'login', result: MembershipResult): boolean {
  const rotated = after.account.authenticationGeneration === before.account.authenticationGeneration + 1 && before.account.csrf !== after.account.csrf;
  if (action === 'register' || action === 'login') return rotated && 'account' in result && after.account.account?.id === result.account.id && after.account.account.login === result.account.login
    && (!after.member.user || memberSignature(before.member) === memberSignature(after.member));
  if (action === 'logout') return rotated && !after.account.account && (!after.member.user || !before.member.user?.accountId && memberSignature(before.member) === memberSignature(after.member));
  if (action === 'switch') return rotated && 'entry' in result && before.account.account?.id === after.account.account?.id
    && before.account.authVersion === after.account.authVersion && after.member.user?.role === 'member'
    && after.member.user.householdId === result.householdId && after.member.user.id === result.memberId
    && after.member.user.accountId === after.account.account?.id
    && after.member.user.accountAuthVersion === after.account.authVersion
    && after.member.user.authenticationGeneration === after.account.authenticationGeneration;
  if (action === 'leave') return accountSignature(before.account) === accountSignature(after.account) && !after.member.user;
  if (action === 'link') return accountSignature(before.account) === accountSignature(after.account) && !!before.member.user && !!after.member.user
    && before.member.user.id === after.member.user.id && before.member.user.householdId === after.member.user.householdId
    && before.member.user.auth_version === after.member.user.auth_version && before.member.csrf === after.member.csrf
    && 'revision' in result && after.member.user.membershipRevision === result.revision
    && [before.member.user.membershipRevision, before.member.user.membershipRevision + 1].includes(result.revision);
  return identitySignature(before) === identitySignature(after);
}
