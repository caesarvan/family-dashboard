import { ApiError } from './api';
import { sessionIdentity, type IdentitySession } from './sessionIdentity';
import { journeyStatusIntent } from './assistantJourney';

export type StatusSection = 'tasks' | 'shopping';
export type StatusCandidate = { tripId: string; journeyId: string | null; tripRevision: number; title: string; destination: string; start: string; end: string; status: 'available' | 'legacy' | 'needs_review' };
export type StatusTrip = Omit<StatusCandidate, 'status'> & { journeyRevision: number | null };
export type StatusItem = { kind: StatusSection; id: string; revision: number; title: string; owner: { id: string | null; name: string | null }; due: string } & (
  { kind: 'tasks'; dependencyStatus: 'ready' | 'blocked'; blockers: Array<{ id: string | null; title: string | null; reason: 'unfinished' | 'unavailable' }> }
  | { kind: 'shopping'; quantity: string; priority: 'low' | 'normal' | 'high' });
type Count = { done: number; total: number; remaining: number };
export type Candidates = { version: 1; view: 'candidates'; query: string; items: StatusCandidate[]; limit: 20; offset: number; nextOffset: number | null;
  coverage: { scannedTrips: number; scanLimit: 1000; capped: boolean; unverifiable: number } };
export type JourneyStatus = { version: 1; view: 'status'; state: 'ready' | 'legacy' | 'needs_review'; trip: StatusTrip; sourceVersion: string;
  summary: null | { tasks: Count & { blocked: number }; shopping: Count }; section: StatusSection; items: StatusItem[]; limit: 20; offset: number; nextOffset: number | null;
  coverage: { complete: boolean; unverifiable: number; reasonCodes: Array<'legacy_without_workflow' | 'linked_source_unavailable' | 'item_limit'> } };
export type StatusTarget = { tripId: string; section: StatusSection; offset: number; sourceVersion?: string };
export type StatusSelection = { query: string; offset: number; target: StatusTarget | null };
const bad = (): never => { throw new Error('旅行准备结果暂时无法核对，请重新读取。'); };
const object = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : bad();
const text = (v: unknown, max: number, empty = true): string => typeof v === 'string' && Array.from(v).length <= max && (empty || !!v.trim()) ? v : bad();
const integer = (v: unknown, max: number, min = 0): number => Number.isSafeInteger(v) && (v as number) >= min && (v as number) <= max ? v as number : bad();
const choice = <T extends string>(v: unknown, list: readonly T[]): T => list.includes(v as T) ? v as T : bad();
const id = (v: unknown): string => typeof v === 'string' && /^[a-f0-9]{24}$/.test(v) ? v : bad();
const version = (v: unknown): string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v) ? v : bad();
const bool = (v: unknown): boolean => typeof v === 'boolean' ? v : bad();
const array = (v: unknown, max: number): unknown[] => Array.isArray(v) && v.length <= max ? v : bad();
function date(v: unknown, empty = true): string {
  if (v === '' && empty) return '';
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return bad();
  const [y, m, d] = v.split('-').map(Number), days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return y >= 1 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1] ? v : bad();
}
function trip(raw: unknown) {
  const v = object(raw);
  const value = { tripId: id(v.tripId), journeyId: v.journeyId === null ? null : id(v.journeyId), tripRevision: integer(v.tripRevision, Number.MAX_SAFE_INTEGER, 1),
    title: text(v.title, 100, false), destination: text(v.destination, 80), start: date(v.start, false), end: date(v.end, false) };
  if (value.start && value.end && value.end < value.start) bad();
  return value;
}
function paging(v: Record<string, unknown>, offset: number, max: number) {
  if (v.version !== 1 || v.limit !== 20 || integer(v.offset, max) !== offset || offset % 20) bad();
  if (v.nextOffset !== null && (v.nextOffset !== offset + 20 || integer(v.nextOffset, max) % 20)) bad();
  return { version: 1 as const, limit: 20 as const, offset, nextOffset: v.nextOffset as number | null };
}
function ordered(rows: { id: string }[]) { for (let n = 1; n < rows.length; n++) if (rows[n - 1].id >= rows[n].id) bad(); }
export function readStatusCandidates(raw: unknown, query: string, offset: number): Candidates {
  const v = object(raw), c = object(v.coverage), page = paging(v, offset, 980);
  if (v.view !== 'candidates' || text(v.query, 100) !== query) bad();
  const items = array(v.items, 20).map(raw => { const item = object(raw); return { ...trip(item), status: choice(item.status, ['available', 'legacy', 'needs_review']) }; });
  ordered(items.map(item => ({ id: item.tripId })));
  if (page.nextOffset !== null && items.length !== 20) bad();
  const coverage = { scannedTrips: integer(c.scannedTrips, 1000), scanLimit: 1000 as const, capped: bool(c.capped), unverifiable: integer(c.unverifiable, 1000) };
  if (c.scanLimit !== 1000 || coverage.unverifiable > coverage.scannedTrips || coverage.capped && coverage.scannedTrips !== 1000) bad();
  return { ...page, view: 'candidates', query, items, coverage };
}
function count(raw: unknown): Count { const c = object(raw); const value = { done: integer(c.done, 100), total: integer(c.total, 100), remaining: integer(c.remaining, 100) }; if (value.done + value.remaining !== value.total) bad(); return value; }
export function readJourneyStatus(raw: unknown, target: StatusTarget): JourneyStatus {
  const v = object(raw), c = object(v.coverage), t = object(v.trip), page = paging(v, target.offset, 80);
  if (v.view !== 'status' || v.section !== target.section) bad();
  const sourceVersion = version(v.sourceVersion);
  if (target.offset && sourceVersion !== target.sourceVersion) bad();
  const detail = { ...trip(t), journeyRevision: t.journeyRevision === null ? null : integer(t.journeyRevision, Number.MAX_SAFE_INTEGER, 1) };
  if (detail.tripId !== target.tripId) bad();
  const state = choice(v.state, ['ready', 'legacy', 'needs_review']);
  const coverage: JourneyStatus['coverage'] = { complete: bool(c.complete), unverifiable: integer(c.unverifiable, Number.MAX_SAFE_INTEGER), reasonCodes: array(c.reasonCodes, 3).map(v => choice(v, ['legacy_without_workflow', 'linked_source_unavailable', 'item_limit'])) };
  if (new Set(coverage.reasonCodes).size !== coverage.reasonCodes.length || coverage.complete && (coverage.unverifiable || coverage.reasonCodes.length) || state === 'ready' && !coverage.complete) bad();
  let summary: JourneyStatus['summary'] = null;
  if (v.summary !== null) { const s = object(v.summary); summary = { tasks: { ...count(s.tasks), blocked: integer(object(s.tasks).blocked, 100) }, shopping: count(s.shopping) }; if (summary.tasks.blocked > summary.tasks.remaining) bad(); }
  const items: StatusItem[] = array(v.items, 20).map(raw => {
    const row = object(raw), o = object(row.owner), kind = choice(row.kind, ['tasks', 'shopping']);
    if (kind !== target.section) bad();
    const owner = { id: o.id === null ? null : text(o.id, 100, false), name: o.name === null ? null : text(o.name, 20, false) };
    if ((owner.id === null) !== (owner.name === null) || owner.id === 'shared' && owner.name !== '一起') bad();
    const common = { id: id(row.id), revision: integer(row.revision, Number.MAX_SAFE_INTEGER, 1), title: text(row.title, 100, false), owner, due: date(row.due) };
    if (kind === 'shopping') return { ...common, kind, quantity: text(row.quantity, 30), priority: choice(row.priority, ['low', 'normal', 'high']) };
    const blockers = array(row.blockers, 20).map(raw => { const b = object(raw), reason = choice(b.reason, ['unfinished', 'unavailable']);
      if (reason === 'unavailable') { if (b.id !== null || b.title !== null) bad(); return { id: null, title: null, reason }; }
      return { id: id(b.id), title: text(b.title, 100, false), reason }; });
    const dependencyStatus = choice(row.dependencyStatus, ['ready', 'blocked']);
    if ((dependencyStatus === 'blocked') !== (blockers.length > 0)) bad();
    return { ...common, kind, dependencyStatus, blockers };
  });
  ordered(items);
  if (page.nextOffset !== null && items.length !== 20 || !summary && (items.length || page.nextOffset !== null) || state === 'ready' && !summary || state === 'legacy' && (summary || items.length || detail.journeyId !== null || coverage.complete)) bad();
  return { ...page, view: 'status', state, trip: detail, sourceVersion, summary, section: target.section, items, coverage };
}
export function statusPath(selection: StatusSelection): string {
  const target = selection.target;
  const params = new URLSearchParams({ limit: '20', offset: String(target?.offset ?? selection.offset) });
  if (target) {
    params.set('tripId', id(target.tripId)); params.set('section', choice(target.section, ['tasks', 'shopping']));
    if (integer(target.offset, 80) % 20) bad();
    if (target.offset) params.set('sourceVersion', version(target.sourceVersion));
  } else { if (integer(selection.offset, 980) % 20) bad(); params.set('q', text(selection.query.trim(), 100)); }
  return '/assistant/journey-status?' + params;
}

/** GET only; the caller supplies one signal/deadline across both identity reads and the data read. */
export async function statusRead(path: string, signal: AbortSignal): Promise<unknown> {
  const origin = (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
  const response = await fetch(origin + '/api' + path, { method: 'GET', credentials: 'include', cache: 'no-store', signal, headers: { Accept: 'application/json' } });
  if (response.status === 401 || response.status === 403) { await response.body?.cancel(); throw new ApiError('身份或权限已变化', response.status, ''); }
  const max = 256 * 1024;
  if (Number(response.headers.get('content-length')) > max) { await response.body?.cancel(); throw new Error('响应过大'); }
  if (!response.body) throw new Error('无法有界读取响应');
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const part = await reader.read(); if (part.done) break; size += part.value.byteLength; if (size > max) throw new Error('响应过大'); chunks.push(part.value); } }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  const bytes = new Uint8Array(size); let at = 0; for (const part of chunks) { bytes.set(part, at); at += part.byteLength; }
  const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  if (!response.ok) throw new ApiError('旅行查询暂不可用', response.status, typeof value?.code === 'string' ? value.code : '');
  return value;
}
export type StatusState = { prompt: string; query: string; selection: StatusSelection; result: Candidates | JourneyStatus | null; visible: boolean; busy: boolean; expired: boolean; error: string; notice: string; clarification: string };
type IO = { read: (path: string, signal: AbortSignal) => Promise<unknown>; current: () => boolean; expired: () => void };
class Discarded extends Error {}
class ChangedIdentity extends Error {}
export class JourneyStatusFlow {
  state: StatusState;
  private alive = true; private foreground = false; private serial = 0; private job: AbortController | null = null;
  constructor(private actor: string, prompt: string, private io: IO, private changed: (state: StatusState) => void) {
    const intent = journeyStatusIntent(prompt);
    this.state = { prompt, query: intent.query, selection: { query: intent.query, offset: 0, target: null }, result: null, visible: false, busy: false, expired: false, error: '', notice: '', clarification: intent.clarification };
  }
  private emit(patch: Partial<StatusState>) { this.state = { ...this.state, ...patch }; if (this.alive) this.changed(this.state); }
  private current(ticket: number) { return this.alive && this.foreground && !this.state.expired && this.io.current() && ticket === this.serial; }
  conceal() { this.foreground = false; ++this.serial; this.job?.abort(); this.job = null; this.emit({ result: null, visible: false, busy: false, error: '' }); }
  close() { this.conceal(); this.alive = false; }
  async resume(originalTripId?: string) {
    if (!this.alive || this.state.expired || !this.io.current() || this.state.busy) return;
    this.foreground = true;
    if (originalTripId && this.state.selection.target?.tripId !== originalTripId)
      this.emit({ selection: { ...this.state.selection, target: { tripId: id(originalTripId), section: 'tasks', offset: 0 } } });
    await this.load(true);
  }
  editQuery(value: string) { if (!this.state.visible || this.state.busy || Array.from(value).length > 100) return; this.emit({ query: value, result: null }); }
  async search() {
    if (!this.state.visible || this.state.busy) return;
    const intent = journeyStatusIntent(this.state.query);
    if (intent.clarification.startsWith('这句话同时')) { this.emit({ result: null, clarification: intent.clarification }); return; }
    const query = intent.clarification ? this.state.query.trim() : intent.query;
    this.emit({ query, selection: { query, offset: 0, target: null }, clarification: '', notice: '' }); await this.load();
  }
  async select(tripId: string) { if (!this.state.visible || this.state.busy || this.state.result?.view !== 'candidates' || !this.state.result.items.some(v => v.tripId === tripId)) return;
    this.emit({ selection: { ...this.state.selection, target: { tripId, section: 'tasks', offset: 0 } }, notice: '' }); await this.load(); }
  async candidates() { if (!this.state.visible || this.state.busy) return; this.emit({ selection: { ...this.state.selection, target: null }, notice: '' }); await this.load(); }
  async section(section: StatusSection) { const target = this.state.selection.target; if (!this.state.visible || this.state.busy || !target) return; this.emit({ selection: { ...this.state.selection, target: { ...target, section, offset: 0 } }, notice: '' }); await this.load(); }
  async page(next: boolean) {
    const r = this.state.result; if (!this.state.visible || this.state.busy || !r) return;
    const offset = next ? r.nextOffset : Math.max(0, r.offset - 20); if (offset === null || offset === r.offset) return;
    this.emit({ selection: r.view === 'candidates' ? { ...this.state.selection, offset } : { ...this.state.selection, target: { tripId: r.trip.tripId, section: r.section, offset, sourceVersion: r.sourceVersion } }, notice: '' }); await this.load();
  }
  async load(refresh = false) {
    if (!this.current(this.serial) || this.state.busy) return;
    const ticket = ++this.serial, controller = new AbortController(); this.job = controller;
    const selection = this.state.selection; const phase: { origin: 'identity' | 'status' } = { origin: 'identity' };
    this.emit({ busy: true, result: null, visible: false, error: '' });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error('timeout')); }, 15000); });
    const ensure = () => { if (!this.current(ticket) || controller.signal.aborted) throw new Discarded(); };
    const me = async () => { phase.origin = 'identity'; const raw = await this.io.read('/me', controller.signal); ensure(); const session = raw as IdentitySession; if (session.user?.role !== 'member' || sessionIdentity(session) !== this.actor) throw new ChangedIdentity(); };
    try {
      const read = async (selected: StatusSelection) => { phase.origin = 'status'; const raw = await this.io.read(statusPath(selected), controller.signal); ensure(); return selected.target ? readJourneyStatus(raw, selected.target) : readStatusCandidates(raw, selected.query, selected.offset); };
      const work = async () => {
        await me(); let selected = selection, notice = this.state.notice;
        if (refresh && selection.target?.offset) selected = { ...selection, target: { ...selection.target, offset: 0 } };
        let result = await read(selected);
        if (refresh && selection.target?.offset && result.view === 'status') {
          if (result.sourceVersion === selection.target.sourceVersion) { selected = selection; result = await read(selected); }
          else notice = '准备记录已有变化，已从本类第一页重新核对。';
        }
        await me(); ensure();
        if (result.view === 'status') selected = { ...selected, target: { tripId: result.trip.tripId, section: result.section, offset: result.offset, sourceVersion: result.sourceVersion } };
        return { result, selection: selected, notice };
      };
      const value = await Promise.race([work(), timeout]); ensure(); this.emit({ ...value, visible: true });
    } catch (error) {
      if (!this.current(ticket)) return;
      if (error instanceof ChangedIdentity || error instanceof ApiError && [401, 403].includes(error.status)) {
        this.emit({ prompt: '', query: '', selection: { query: '', offset: 0, target: null }, result: null, visible: false, expired: true, clarification: '', notice: '', error: '身份或权限已变化，旅行查询已清除，请返回助理。' }); this.io.expired();
      } else if (phase.origin === 'status' && error instanceof ApiError && [404, 410].includes(error.status) && error.code === 'journey_status_unavailable') {
        this.emit({ selection: { ...selection, target: null }, result: null, error: '原旅行当前不可用，请重新读取候选旅行。' });
      } else if (phase.origin === 'status' && error instanceof ApiError && error.status === 409 && error.code === 'stale_journey_status') {
        this.emit({ selection: { ...selection, target: selection.target ? { ...selection.target, offset: 0, sourceVersion: undefined } : null }, error: '准备记录已有变化，请重新读取本类第一页。' });
      } else if (!(error instanceof Discarded)) this.emit({ error: phase.origin === 'identity' ? '暂时无法核对登录身份，查询内容已隐藏，请重新读取。' : '暂时无法读取旅行准备情况，请重新读取。' });
    } finally { if (timer) clearTimeout(timer); if (ticket === this.serial) { controller.abort(); this.job = null; this.emit({ busy: false }); } }
  }
}
