export type ProviderId = 'microsoft' | 'google';
export type SourceKind = 'calendar' | 'tasks';
export type SourceOwner = 'member1' | 'member2' | 'shared';
export type SourceChoice = { remoteId: string; kind: SourceKind; owner: SourceOwner; primary: boolean };
export type SavedSource = SourceChoice & { id: string; name: string; lastSuccess: string; error: string };
export type CloudSource = { id: string; kind: SourceKind; name: string; writable: boolean };
export type CloudAccount = { id: string; provider: ProviderId; name: string; email: string; needsReauth: boolean; capabilities: { sync: boolean; photos: boolean }; sources: SavedSource[]; selectionVersion: string };
export type AccountProvider = { id: ProviderId; name: string; configured: boolean };
export type AccountList = { accounts: CloudAccount[]; providers: AccountProvider[] };
export type SourceDiscovery = { sources: CloudSource[]; selected: SavedSource[]; selectionVersion: string };
export type DraftSource = CloudSource & { owner: SourceOwner; primary: boolean; selected: boolean; available: boolean };
export type SelectionDraft = { accountId: string; version: string; rows: DraftSource[]; saved: SavedSource[] };
const bad = () => { throw new Error('账户数据暂时无法核对，请刷新。'); };
const record = (value: unknown): Record<string, any> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : bad();
const text = (value: unknown, max = 200): string => typeof value === 'string' && value.length <= max ? value : bad();
const flag = (value: unknown): boolean => typeof value === 'boolean' ? value : bad();
export const accountId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
export const selectionVersion = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export const sourceKey = (value: { kind: SourceKind; id?: string; remoteId?: string }) => JSON.stringify([value.kind, value.remoteId ?? value.id]);
export const providerName = (provider: ProviderId) => provider === 'microsoft' ? 'Microsoft' : 'Google';
const kind = (value: unknown): SourceKind => value === 'calendar' || value === 'tasks' ? value : bad();
const owner = (value: unknown): SourceOwner => value === 'member1' || value === 'member2' || value === 'shared' ? value : bad();
const remote = (value: unknown) => { const id = text(value, 8192); return id ? id : bad(); };
function chosen(value: unknown): SourceChoice {
  const row = record(value), result = { remoteId: remote(row.remoteId), kind: kind(row.kind), owner: owner(row.owner), primary: flag(row.primary) };
  if (result.kind === 'tasks' ? result.owner !== 'shared' : result.primary) bad(); return result;
}
function savedSources(value: unknown): SavedSource[] {
  if (!Array.isArray(value) || value.length > 12) return bad();
  const rows = value.map(input => {
    const row = record(input); if (!accountId(row.id)) return bad();
    return { ...chosen(row), id: row.id, name: text(row.name), lastSuccess: text(row.lastSuccess, 100), error: text(row.error, 2000) };
  });
  if (new Set(rows.map(sourceKey)).size !== rows.length || new Set(rows.map(row => row.id)).size !== rows.length || rows.filter(row => row.primary).length > 1) bad();
  return rows;
}
export function readAccounts(value: unknown): AccountList {
  const input = record(value);
  if (!Array.isArray(input.accounts) || input.accounts.length > 4 || !Array.isArray(input.providers) || input.providers.length > 2) return bad();
  const providers = input.providers.map((v: unknown) => {
    const row = record(v); if (!['microsoft', 'google'].includes(row.id)) return bad();
    return { id: row.id as ProviderId, name: providerName(row.id), configured: flag(row.configured) };
  });
  const accounts = input.accounts.map((v: unknown) => {
    const row = record(v), capabilities = record(row.capabilities);
    if (!accountId(row.id) || !selectionVersion(row.selectionVersion) || !['microsoft', 'google'].includes(row.provider)) return bad();
    return { id: row.id, provider: row.provider as ProviderId, name: text(row.name), email: text(row.email, 320), needsReauth: flag(row.needsReauth),
      capabilities: { sync: flag(capabilities.sync), photos: flag(capabilities.photos) }, sources: savedSources(row.sources), selectionVersion: row.selectionVersion };
  });
  if (new Set(accounts.map(a => a.id)).size !== accounts.length || new Set(providers.map(p => p.id)).size !== providers.length) bad();
  return { accounts, providers };
}
export function readDiscovery(value: unknown): SourceDiscovery {
  const input = record(value); if (!selectionVersion(input.selectionVersion) || !Array.isArray(input.sources) || input.sources.length > 1000) return bad();
  const sources = input.sources.map((v: unknown) => {
    const row = record(v); return { id: remote(row.id), kind: kind(row.kind), name: text(row.name), writable: flag(row.writable) };
  });
  if (new Set(sources.map(sourceKey)).size !== sources.length || ['calendar', 'tasks'].some(k => sources.filter(s => s.kind === k).length > 500)) bad();
  return { sources, selected: savedSources(input.selected), selectionVersion: input.selectionVersion };
}
export function selectionDraft(id: string, discovery: SourceDiscovery, member: string): SelectionDraft {
  if (!accountId(id) || !['member1', 'member2'].includes(member)) return bad();
  const saved = new Map(discovery.selected.map(s => [sourceKey(s), s]));
  const rows: DraftSource[] = discovery.sources.map(s => {
    const existing = saved.get(sourceKey(s)); return { ...s, selected: !!existing, available: true,
      owner: existing?.owner || (s.kind === 'tasks' ? 'shared' : member as SourceOwner), primary: existing?.primary || false };
  });
  const known = new Set(rows.map(sourceKey));
  for (const s of discovery.selected) if (!known.has(sourceKey(s))) rows.push({ id: s.remoteId, kind: s.kind, name: s.name, writable: false, owner: s.owner, primary: s.primary, selected: true, available: false });
  return { accountId: id, rows, saved: discovery.selected, version: discovery.selectionVersion };
}
export function stopSyncDraft(account: CloudAccount, member: string): SelectionDraft {
  const draft = selectionDraft(account.id, { sources: [], selected: account.sources, selectionVersion: account.selectionVersion }, member);
  return { ...draft, rows: draft.rows.map(row => ({ ...row, selected: false, primary: false })) };
}
export function sourcePayload(draft: SelectionDraft) {
  if (!selectionVersion(draft.version) || !accountId(draft.accountId)) return bad();
  const selected = draft.rows.filter(row => row.selected);
  if (selected.length > 12) throw new Error('每个账户最多选择 12 个来源。');
  if (selected.some(row => !row.available)) throw new Error('有已选来源本次未发现。请重新读取，或明确取消该来源后保存。');
  if (selected.some(row => row.kind === 'tasks' && !row.writable)) throw new Error('所选清单没有写入权限，请取消该清单或重新授权。');
  const sources = selected.map(row => chosen({ remoteId: row.id, kind: row.kind, owner: row.owner, primary: row.primary }));
  if (new Set(sources.map(sourceKey)).size !== sources.length || sources.filter(row => row.primary).length > 1) throw new Error('只能设置一份共同主清单。');
  return { sources, selectionVersion: draft.version };
}
export function sameSelection(left: SourceChoice[], right: SourceChoice[]): boolean {
  const normalized = (rows: SourceChoice[]) => rows.map(v => chosen(v)).sort((a, b) => sourceKey(a).localeCompare(sourceKey(b)));
  return JSON.stringify(normalized(left)) === JSON.stringify(normalized(right));
}
export function selectionChanges(draft: SelectionDraft) {
  const selected = draft.rows.filter(row => row.selected), keys = new Set(selected.map(sourceKey));
  return { removed: draft.saved.filter(s => !keys.has(sourceKey(s))), selected };
}
// A fresh saved snapshot is authoritative, but its version is adopted only by
// an explicit review action. Missing sources stay in the draft until removed.
export function reviewSelection(draft: SelectionDraft, fresh: CloudAccount): SelectionDraft {
  if (fresh.id !== draft.accountId) return bad();
  const keys = new Set(draft.rows.map(sourceKey));
  const rows = [...draft.rows];
  for (const s of fresh.sources) if (!keys.has(sourceKey(s))) rows.push({ id: s.remoteId, kind: s.kind, name: s.name, selected: false, available: false, writable: false, owner: s.owner, primary: false });
  return { ...draft, version: fresh.selectionVersion, saved: fresh.sources, rows };
}
export function accountTime(raw: string) {
  if (!raw) return '尚无成功记录';
  const date = new Date(raw); return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '成功时间无法识别';
}
