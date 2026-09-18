import { ApiError } from './api';
import type { Member } from './types';
import { memberIdentity, sessionIdentity } from './sessionIdentity.ts';

export type Action = { kind: 'tasks' | 'shopping'; data: { title: string; owner: string; due?: string; quantity?: string } };
export type Match = { id: string; kind: 'tasks' | 'shopping' | 'events' | 'trips' | 'media' | 'places' | 'inventory'; title: string; due?: string; start?: string;
  unit?: string; location?: string; onHandQty?: number; inTransitQty?: number; plannedQty?: number };
export type Search = { query: string; matches: Match[]; total: number; limit: number; offset: number; nextOffset: number | null };
export type Plan = { id: string | null; mode: 'local' | 'model'; summary: string; actions: Action[]; matches: Match[]; search?: Omit<Search, 'matches'> };
export type Receipt = { ok: true; destination: 'household'; created: { id: string; kind: 'tasks' | 'shopping'; title: string }[] };
type Session = { user: Member | null; csrf?: string | null };
export type AssistantState = {
  busy: boolean; error: string; notice: string; ready: boolean; expired: boolean;
  modelConfigured: boolean; plan: Plan | null; planPrompt: string; selected: number[]; receipt: Receipt | null;
  pending: { id: string; selected: number[] } | null; checkedAfterUnknown: boolean; search: Search | null;
};
type IO = {
  read: <T>(path: string) => Promise<T>;
  mutate: <T>(path: string, method: string, payload: unknown) => Promise<T>;
  refresh: () => Promise<void>;
  current: () => boolean;
};
const initial = (): AssistantState => ({ busy: false, error: '', notice: '', ready: false, expired: false,
  modelConfigured: false, plan: null, planPrompt: '', selected: [], receipt: null, pending: null, checkedAfterUnknown: false, search: null });
export const memberKey = memberIdentity;
const sessionKey = sessionIdentity;
const unknown = (error: unknown) => !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
const message = (error: unknown) => error instanceof Error ? error.message : '暂时无法完成，请稍后核对';

function checkedPlan(value: Plan): Plan {
  if (!value || !['local', 'model'].includes(value.mode) || typeof value.summary !== 'string' ||
      !Array.isArray(value.actions) || value.actions.length > 12 ||
      !(value.id === null || (typeof value.id === 'string' && /^[a-f0-9]{32}$/.test(value.id))) ||
      value.actions.some(a => !['tasks', 'shopping'].includes(a.kind) || !a.data || typeof a.data.title !== 'string' || typeof a.data.owner !== 'string') ||
      (value.actions.length > 0 && !value.id)) throw new Error('服务返回的草案不完整，请重新核对');
  return value;
}
function checkedReceipt(value: Receipt): Receipt {
  if (!value || value.ok !== true || value.destination !== 'household' || !Array.isArray(value.created) ||
      !value.created.length || value.created.length > 12 || value.created.some(item => !/^[a-f0-9]{24}$/.test(item.id) ||
        !['tasks', 'shopping'].includes(item.kind) || typeof item.title !== 'string')) throw new Error('暂时无法确认服务返回的执行结果');
  return value;
}

/** Screen-local flow. The backend plan ID is the idempotency key; no invented request IDs. */
export class AssistantFlow {
  state = initial();
  private alive = true;
  private identity: string | null = null;
  private foreground = true;
  private searchEpoch = 0;
  constructor(private actor: Member, private io: IO, private changed: (value: AssistantState) => void) {}
  private live() { return this.alive && this.io.current(); }
  private update(patch: Partial<AssistantState>) {
    if (!this.live()) return;
    this.state = { ...this.state, ...patch }; this.changed(this.state);
  }
  close() { this.alive = false; this.state = initial(); }
  private expire() {
    this.state = { ...initial(), expired: true, error: '登录身份已变化，已清除本页草案。请刷新后重新打开助理。' };
    if (this.live()) this.changed(this.state);
  }
  private async verify() {
    if (!this.live()) throw new Error('页面已离开');
    let session: Session;
    try { session = await this.io.read<Session>('/me'); }
    catch (error) { if (error instanceof ApiError && [401, 403, 409].includes(error.status)) this.expire(); throw error; }
    if (!this.live()) throw new Error('页面已离开');
    if (session.user?.role !== 'member' || memberKey(session.user) !== memberKey(this.actor) ||
        (this.identity !== null && this.identity !== sessionKey(session))) {
      this.expire(); throw new ApiError('登录身份已变化', 401);
    }
    this.identity = sessionKey(session);
  }
  private async run(work: () => Promise<void>) {
    if (!this.live() || this.state.busy || this.state.expired) return;
    this.update({ busy: true, error: '' });
    try { await this.verify(); await work(); }
    catch (error) { if (!this.state.expired) this.update({ error: message(error) }); }
    finally { this.update({ busy: false }); }
  }
  async load() {
    await this.run(async () => {
      const brief = await this.io.read<{ modelConfigured: boolean }>('/assistant/brief');
      await this.verify(); this.update({ ready: true, modelConfigured: brief.modelConfigured === true });
    });
  }
  async plan(prompt: string, useModel: boolean, includeHouseholdContext: boolean) {
    if (this.state.pending) return;
    await this.run(async () => {
      if (!prompt.trim() || prompt.trim().length > 2000) throw new Error('请填写 1～2000 字的请求');
      // A new intent cannot leave an earlier plan's confirmation button on screen after failure.
      this.update({ plan: null, receipt: null, search: null, selected: [], notice: '' });
      const epoch = this.searchEpoch;
      const result = checkedPlan(await this.io.mutate<Plan>('/assistant/plan', 'POST', { prompt: prompt.trim(), useModel, includeHouseholdContext: useModel && includeHouseholdContext }));
      await this.verify();
      this.update({ plan: result, planPrompt: prompt.trim(), selected: result.actions.map((_, i) => i),
        search: result.search && this.foreground && epoch === this.searchEpoch ? { ...result.search, matches: result.matches } : null });
    });
  }
  select(index: number) {
    if (this.state.busy || this.state.pending || this.state.receipt || this.state.expired || !this.state.plan?.actions[index]) return;
    this.update({ selected: this.state.selected.includes(index) ? this.state.selected.filter(i => i !== index) : [...this.state.selected, index].sort((a, b) => a - b) });
  }
  async apply() {
    if (!this.state.plan?.id || !this.state.selected.length || this.state.receipt ||
        (this.state.pending && !this.state.checkedAfterUnknown)) return;
    await this.run(async () => {
      const intent = this.state.pending || { id: this.state.plan!.id!, selected: [...this.state.selected] };
      this.update({ pending: intent, checkedAfterUnknown: false, notice: '' });
      let receipt: Receipt;
      try { receipt = checkedReceipt(await this.io.mutate<Receipt>('/assistant/plans/' + intent.id + '/apply', 'POST', { selected: [...intent.selected] })); }
      catch (error) {
        await this.verify();
        if (unknown(error)) this.update({ error: '暂时无法确认保存结果。先读取最新清单，再决定是否继续原确认；原计划和勾选已锁定。' });
        else this.update({ pending: null, error: message(error) });
        return;
      }
      await this.verify();
      this.update({ receipt, pending: null, notice: '已收到本次保存回执。事项保存在家庭看板，不会自动写入云端。' });
      try { await this.io.refresh(); await this.verify(); }
      catch (error) { if (!this.state.expired) this.update({ error: '保存回执已保留，但最新清单尚未刷新，请稍后读取。' }); }
    });
  }
  async checkOutcome() {
    if (!this.state.pending && !this.state.receipt) return;
    await this.run(async () => {
      await this.io.read('/state'); await this.verify();
      await this.io.refresh(); await this.verify();
      this.update({ checkedAfterUnknown: !!this.state.pending,
        notice: this.state.pending ? '已读取当前清单；这不能确认本次计划是否执行。核对后，可使用原计划继续确认，服务器不会重复创建。' : '已刷新当前清单，保存回执仍保留。' });
    });
  }
  async search(query: string, offset = 0) {
    if (this.state.pending || !this.foreground) return;
    await this.run(async () => {
      this.update({ search: null });
      const epoch = this.searchEpoch;
      const result = await this.io.read<Search>('/assistant/search?q=' + encodeURIComponent(query) + '&limit=20&offset=' + offset);
      await this.verify(); if (this.foreground && epoch === this.searchEpoch) this.update({ search: result });
    });
  }
  // Revocable search metadata is never kept visible through loss of foreground/connectivity.
  concealSearch() { ++this.searchEpoch; this.update({ search: null }); }
  setForeground(value: boolean) { this.foreground = value; if (!value) this.concealSearch(); }
}
