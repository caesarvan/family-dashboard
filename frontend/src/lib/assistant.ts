import { ApiError } from './api';
import type { Member } from './types';
import { memberIdentity, sessionIdentity } from './sessionIdentity.ts';
import { recoverPlan, retainPlan, snapshotIntent, type ActionData, type ApplyIntent, type PlanStorage } from './assistantList';

export type Action = { kind: 'tasks' | 'shopping'; data: { title: string; owner: string; due?: string; quantity?: string; note?: string; budget?: number | null; priority?: 'low' | 'normal' | 'high' } };
export type Match = { id: string; kind: 'tasks' | 'shopping' | 'events' | 'trips' | 'media' | 'places' | 'inventory' | 'documents'; title: string; due?: string; start?: string;
  unit?: string; location?: string; onHandQty?: number; inTransitQty?: number; plannedQty?: number;
  filename?: string; mimeType?: 'application/pdf' | 'image/jpeg'; revision?: number; visibility?: 'private' | 'shared';
  journey?: { id: string; tripId: string; title: string } | null };
export type Search = { query: string; matches: Match[]; total: number; limit: number; offset: number; nextOffset: number | null };
export type Plan = { id: string | null; mode: 'local' | 'model'; summary: string; actions: Action[]; matches: Match[]; search?: Omit<Search, 'matches'> };
export type Receipt = { ok: true; destination: 'household'; created: { id: string; kind: 'tasks' | 'shopping'; title: string }[] };
type Session = { user: Member | null; csrf?: string | null };
export type AssistantState = {
  busy: boolean; error: string; notice: string; ready: boolean; expired: boolean;
  modelConfigured: boolean; plan: Plan | null; planPrompt: string; selected: number[]; receipt: Receipt | null;
  pending: ApplyIntent | null; checkedAfterUnknown: boolean; search: Search | null;
  visible: boolean; edits: Record<number, ActionData>; recoveryId: string | null; needsReview: boolean; unavailable: boolean;
};
type IO = {
  read: <T>(path: string) => Promise<T>;
  mutate: <T>(path: string, method: string, payload: unknown) => Promise<T>;
  refresh: () => Promise<void>;
  current: () => boolean;
  storage?: PlanStorage;
};
const initial = (): AssistantState => ({ busy: false, error: '', notice: '', ready: false, expired: false,
  modelConfigured: false, plan: null, planPrompt: '', selected: [], receipt: null, pending: null, checkedAfterUnknown: false, search: null,
  visible: false, edits: {}, recoveryId: null, needsReview: false, unavailable: false });
export const memberKey = memberIdentity;
const sessionKey = sessionIdentity;
const message = (error: unknown) => error instanceof Error ? error.message : '暂时无法完成，请稍后核对';

export function readAssistantSearch(value: unknown, expected?: { query: string; offset: number }): Search {
  const invalid = (): never => { throw new Error('搜索结果无法核对，请重新查询。'); };
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  const row = value as Search;
  if (typeof row.query !== 'string' || !row.query.trim() || Array.from(row.query).length > 100 || !Array.isArray(row.matches)
    || !Number.isSafeInteger(row.total) || row.total < 0 || !Number.isSafeInteger(row.limit) || row.limit < 1 || row.limit > 30
    || !Number.isSafeInteger(row.offset) || row.offset < 0 || row.offset > 20000
    || row.matches.length !== Math.max(0, Math.min(row.limit, row.total - row.offset))
    || row.nextOffset !== (row.offset + row.matches.length < row.total ? row.offset + row.matches.length : null)
    || expected && (row.query !== expected.query.trim() || row.offset !== expected.offset)) return invalid();
  const seen = new Set<string>();
  const matches = row.matches.map(item => {
    if (!item || !['tasks', 'shopping', 'events', 'trips', 'media', 'places', 'inventory', 'documents'].includes(item.kind)
      || typeof item.id !== 'string' || typeof item.title !== 'string' || seen.has(item.kind + ':' + item.id)) return invalid();
    seen.add(item.kind + ':' + item.id);
    if (item.kind !== 'documents' && item.kind !== 'media' && item.kind !== 'places') return item;
    if (!(item.kind === 'documents' ? /^[a-f0-9]{32}$/ : /^[a-f0-9]{24}$/).test(item.id)
      || !Number.isSafeInteger(item.revision) || item.revision! < 1 || !['private', 'shared'].includes(item.visibility || '')
      || !(item.journey === null || item.journey && /^[a-f0-9]{24}$/.test(item.journey.id)
        && /^[a-f0-9]{24}$/.test(item.journey.tripId) && typeof item.journey.title === 'string')) return invalid();
    const common = { id: item.id, kind: item.kind, title: item.title, revision: item.revision, visibility: item.visibility,
      journey: item.journey ? { id: item.journey.id, tripId: item.journey.tripId, title: item.journey.title } : null };
    if (item.kind === 'media' || item.kind === 'places') return common;
    if (typeof item.filename !== 'string' || !item.filename.trim() || Array.from(item.filename).length > 180 || /[\\/]/.test(item.filename)
      || !['application/pdf', 'image/jpeg'].includes(item.mimeType || '') || item.journey === null && item.visibility !== 'private') return invalid();
    // Search is text metadata only, never a download or sharing authority.
    return { ...common, filename: item.filename, mimeType: item.mimeType };
  });
  return { query: row.query, matches, total: row.total, limit: row.limit, offset: row.offset, nextOffset: row.nextOffset };
}

export function assistantContentRequest(match: Match, key: number):
  { kind: 'documents'; key: number; id: string; journeyId?: string } | { kind: 'media' | 'places'; key: number; id: string } | null {
  if (!Number.isSafeInteger(key) || key < 1) return null;
  if ((match.kind === 'media' || match.kind === 'places') && /^[a-f0-9]{24}$/.test(match.id)) return { kind: match.kind, key, id: match.id };
  if (match.kind === 'documents' && /^[a-f0-9]{32}$/.test(match.id)
    && (match.journey === null || match.journey && /^[a-f0-9]{24}$/.test(match.journey.id)))
    return { kind: 'documents', key, id: match.id, ...(match.journey ? { journeyId: match.journey.id } : {}) };
  return null;
}

function checkedPlan(value: Plan, applied = false): Plan {
  if (!value || !['local', 'model'].includes(value.mode) || typeof value.summary !== 'string' ||
      !Array.isArray(value.actions) || value.actions.length > 12 ||
      !(value.id === null || (typeof value.id === 'string' && /^[a-f0-9]{32}$/.test(value.id))) ||
      value.actions.some(a => !['tasks', 'shopping'].includes(a.kind) || !a.data || typeof a.data.title !== 'string' || typeof a.data.owner !== 'string') ||
      (value.actions.length > 0 && !value.id)) throw new Error('服务返回的草案不完整，请重新核对');
  return { ...value, actions: value.actions.map(action => ({ kind: action.kind, data: {
    title: action.data.title, owner: action.data.owner,
    ...(typeof action.data.due === 'string' ? { due: action.data.due } : {}),
    ...(action.kind === 'shopping' && typeof action.data.quantity === 'string' ? { quantity: action.data.quantity } : {}),
    ...(applied && typeof action.data.note === 'string' ? { note: action.data.note } : {}),
    ...(applied && action.kind === 'shopping' && (action.data.budget === null || Number.isSafeInteger(action.data.budget) && action.data.budget! >= 0 && action.data.budget! <= 100000000000) ? { budget: action.data.budget } : {}),
    ...(applied && action.kind === 'shopping' && ['low', 'normal', 'high'].includes(action.data.priority || '') ? { priority: action.data.priority } : {}),
  } })) };
}
function checkedReceipt(value: Receipt): Receipt {
  if (!value || value.ok !== true || value.destination !== 'household' || !Array.isArray(value.created) ||
      !value.created.length || value.created.length > 12 || value.created.some(item => !/^[a-f0-9]{24}$/.test(item.id) ||
        !['tasks', 'shopping'].includes(item.kind) || typeof item.title !== 'string')) throw new Error('暂时无法确认服务返回的执行结果');
  return value;
}
function checkedSavedPlan(value: unknown, id: string): { plan: Plan; status: 'pending' | 'applied' | 'expired'; receipt: Receipt | null } {
  const row = value as { id: string; status: 'pending' | 'applied' | 'expired'; plan: Plan; receipt: Receipt | null };
  if (!row || row.id !== id || !['pending', 'applied', 'expired'].includes(row.status) || row.plan?.id !== id
    || row.status !== 'applied' && row.receipt !== null) throw new Error('原计划返回不完整，请重新核对。');
  return { plan: checkedPlan(row.plan, row.status === 'applied'), status: row.status, receipt: row.status === 'applied' ? checkedReceipt(row.receipt!) : null };
}

/** Screen-local flow. The backend plan ID is the idempotency key; no invented request IDs. */
export class AssistantFlow {
  state = initial();
  private alive = true;
  private identity: string | null = null;
  private foreground = true;
  private searchEpoch = 0;
  private epoch = 0;
  constructor(private actor: Member, private io: IO, private changed: (value: AssistantState) => void) {}
  private live() { return this.alive && this.io.current(); }
  private update(patch: Partial<AssistantState>) {
    if (!this.live()) return;
    this.state = { ...this.state, ...patch }; this.changed(this.state);
  }
  close() { this.alive = false; this.state = initial(); }
  private expire() {
    ++this.epoch; retainPlan(this.io.storage, memberKey(this.actor), null);
    this.state = { ...initial(), expired: true, error: '登录身份已变化，已清除本页草案。请刷新后重新打开助理。' };
    if (this.live()) this.changed(this.state);
  }
  private async verify(ticket = this.epoch) {
    const check = () => { if (!this.live() || this.state.expired || !this.foreground || ticket !== this.epoch) throw new Error('页面已隐藏，请回到前台核对。'); };
    check();
    let session: Session;
    try { session = await this.io.read<Session>('/me'); }
    catch (error) {
      check(); // A closed/hidden request cannot clear a newer identity's recovery marker.
      this.update({ visible: false });
      if (error instanceof ApiError && [401, 403, 409].includes(error.status)) this.expire();
      throw error;
    }
    check();
    if (session.user?.role !== 'member' || memberKey(session.user) !== memberKey(this.actor) ||
        (this.identity !== null && this.identity !== sessionKey(session))) {
      this.expire(); throw new ApiError('登录身份已变化', 401);
    }
    this.identity = sessionKey(session);
  }
  private async run(work: (ticket: number) => Promise<void>) {
    if (!this.live() || !this.foreground || this.state.busy || this.state.expired) return;
    const ticket = this.epoch;
    this.update({ busy: true, error: '' });
    try { await this.verify(ticket); await work(ticket); }
    catch (error) { if (!this.state.expired && ticket === this.epoch) this.update({ error: message(error) }); }
    finally { this.update({ busy: false }); }
  }
  async load() {
    await this.run(async ticket => {
      const brief = await this.io.read<{ modelConfigured: boolean }>('/assistant/brief');
      await this.verify(ticket);
      const restoredId = this.state.recoveryId || recoverPlan(this.io.storage, memberKey(this.actor));
      this.update({ ready: true, modelConfigured: brief.modelConfigured === true, recoveryId: restoredId });
      if (restoredId) await this.readOutcome(restoredId, ticket);
      await this.verify(ticket); this.update({ visible: true });
    });
  }
  async plan(prompt: string, useModel: boolean, includeHouseholdContext: boolean) {
    if (this.state.pending || this.state.needsReview || this.state.unavailable) return;
    await this.run(async ticket => {
      if (!prompt.trim() || prompt.trim().length > 2000) throw new Error('请填写 1～2000 字的请求');
      // A new intent cannot leave an earlier plan's confirmation button on screen after failure.
      retainPlan(this.io.storage, memberKey(this.actor), null);
      this.update({ plan: null, receipt: null, search: null, selected: [], edits: {}, recoveryId: null, notice: '' });
      const epoch = this.searchEpoch;
      const result = checkedPlan(await this.io.mutate<Plan>('/assistant/plan', 'POST', { prompt: prompt.trim(), useModel, includeHouseholdContext: useModel && includeHouseholdContext }));
      const search = result.search ? readAssistantSearch({ ...result.search, matches: result.matches }) : null;
      await this.verify(ticket);
      retainPlan(this.io.storage, memberKey(this.actor), result.id);
      this.update({ plan: search ? { ...result, matches: search.matches } : result, planPrompt: prompt.trim(), selected: result.actions.map((_, i) => i),
        recoveryId: result.id, visible: true, search: search && this.foreground && epoch === this.searchEpoch ? search : null });
    });
  }
  select(index: number) {
    if (!this.state.visible || this.state.busy || this.state.pending || this.state.needsReview || this.state.receipt || this.state.expired || !this.state.plan?.actions[index]) return;
    this.update({ selected: this.state.selected.includes(index) ? this.state.selected.filter(i => i !== index) : [...this.state.selected, index].sort((a, b) => a - b) });
  }
  edit(index: number, data: ActionData) {
    if (!this.state.visible || this.state.busy || this.state.pending || this.state.needsReview || this.state.receipt || this.state.expired || !this.state.plan?.actions[index]) return;
    this.update({ edits: { ...this.state.edits, [index]: { ...data } } });
  }
  reviewDraft() {
    if (!this.state.visible || this.state.busy || this.state.unavailable || this.state.receipt || !this.state.plan || this.state.expired
      || this.state.pending && !this.state.checkedAfterUnknown) return;
    this.update({ pending: null, needsReview: false, checkedAfterUnknown: false,
      notice: '请核对同一原计划后明确确认。若此前请求已保存，服务器会保留原回执，不会另建事项。' });
  }
  startAfterReview() {
    if (!this.state.visible || this.state.busy || this.state.expired || !this.state.unavailable) return;
    retainPlan(this.io.storage, memberKey(this.actor), null);
    this.update({ ...initial(), ready: true, visible: true, modelConfigured: this.state.modelConfigured,
      notice: '已结束原计划核对。你可以输入新需求；尚未创建或提交新计划。' });
  }
  async apply() {
    if (!this.state.visible || this.state.needsReview || this.state.unavailable || !this.state.plan?.id || !this.state.selected.length || this.state.receipt ||
        (this.state.pending && !this.state.checkedAfterUnknown)) return;
    await this.run(async ticket => {
      const intent = this.state.pending || snapshotIntent(this.state.plan!.id!, this.state.selected, this.state.edits);
      this.update({ pending: intent, checkedAfterUnknown: false, notice: '' });
      let receipt: Receipt;
      try { receipt = checkedReceipt(await this.io.mutate<Receipt>('/assistant/plans/' + intent.id + '/apply', 'POST', { selected: [...intent.selected], overrides: intent.overrides.map(row => ({ index: row.index, data: { ...row.data } })) })); }
      catch (error) {
        await this.verify(ticket);
        this.update({ error: '保存尚未核对：' + message(error) + '。请读取原计划回执；原选择和修改已保留，未自动重发。' });
        return;
      }
      await this.verify(ticket);
      this.update({ receipt, pending: null, notice: '已收到本次保存回执。事项保存在家庭看板，不会自动写入云端。' });
      try { await this.io.refresh(); await this.verify(ticket); }
      catch (error) { if (!this.state.expired) this.update({ error: '保存回执已保留，但最新清单尚未刷新，请稍后读取。' }); }
    });
  }
  async checkOutcome() {
    const id = this.state.pending?.id || this.state.recoveryId; if (!id) return;
    await this.run(async ticket => {
      await this.readOutcome(id, ticket); await this.verify(ticket); this.update({ visible: true });
    });
  }
  private async readOutcome(id: string, ticket: number) {
    let value: ReturnType<typeof checkedSavedPlan>;
    try { value = checkedSavedPlan(await this.io.read('/assistant/plans/' + id), id); }
    catch (error) {
      await this.verify(ticket);
      if (error instanceof ApiError && [404, 410].includes(error.status)) {
        this.update({ visible: true, unavailable: true, checkedAfterUnknown: false, notice: '原计划已无法读取，不能据此确认之前是否保存。请核对家庭清单；不会自动另建计划。' }); return;
      }
      throw error;
    }
    await this.verify(ticket);
    if (value.status === 'applied') {
      this.update({ plan: value.plan, receipt: value.receipt, pending: null, needsReview: false, unavailable: false, edits: {},
        checkedAfterUnknown: false, notice: '已读取原计划保存回执，没有再次提交。' });
      try { await this.io.refresh(); await this.verify(ticket); } catch { /* The original receipt remains available after a refresh failure. */ }
    } else if (value.status === 'expired') this.update({ unavailable: true, checkedAfterUnknown: false,
      notice: '原计划已过期，当前没有可读取的保存回执。请核对家庭清单；不会自动另建计划。' });
    else {
      const restored = !this.state.plan;
      this.update({ ...(restored ? { plan: value.plan, selected: value.plan.actions.map((_, i) => i), edits: {}, planPrompt: '', needsReview: true } : {}),
        unavailable: false, checkedAfterUnknown: !!this.state.pending,
        notice: restored ? '读取时尚无保存回执；原修改未恢复，请重新核对同一计划，不会自动提交。'
          : this.state.pending ? '读取时尚无保存回执，不代表旧请求从未到达。可继续原确认，或明确重新核对同一草案。' : '身份与原计划已核对，本页修改仍保留。' });
    }
  }
  async search(query: string, offset = 0) {
    if (this.state.pending || !this.foreground) return;
    await this.run(async ticket => {
      this.update({ search: null });
      const epoch = this.searchEpoch;
      const result = readAssistantSearch(await this.io.read<unknown>('/assistant/search?q=' + encodeURIComponent(query) + '&limit=20&offset=' + offset), { query, offset });
      await this.verify(ticket); if (this.foreground && epoch === this.searchEpoch) this.update({ search: result });
    });
  }
  // Revocable search metadata is never kept visible through loss of foreground/connectivity.
  concealSearch() { ++this.searchEpoch; this.update({ search: null }); }
  setForeground(value: boolean) {
    const previous = this.foreground;
    this.foreground = value;
    if (!value) { ++this.epoch; this.concealSearch(); this.update({ visible: false }); }
    else if (!previous && !this.state.visible) void this.load();
  }
}
