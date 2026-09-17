import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Icon, Portal, Text, TextInput, TouchableRipple, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PhotoReadDiscarded, PhotoReadFence, type PhotoSession } from '../lib/photos';
import { budgetPayload, centsToDecimal, decimalInput, flowLabels, formatFinanceAmount, ledgerPath, readLedger, readOverview, readReconciliation, readRelation, readRelationPreview, readSharedSnapshot, readTotals, relationLabels, sharedFinanceFields, sharedFinanceLabels, sharedSnapshotPayload, sourceLabel, transactionPatch, validFinanceMonth,
  type Budget, type Candidate, type Flow, type Ledger, type Overview, type Reconciliation, type Relation, type RelationPreview, type SharedSnapshot, type Totals, type Transaction } from '../lib/finance';
import type { ScreenProps } from '../lib/types';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import FinanceImportPanel from './FinanceImportPanel';

type Data = { overview: Overview; ledger: Ledger; shared: Totals[]; finance: SharedSnapshot };
type Query = { month: string; q: string; page: number; snapshot?: string };
type Edit = { original: Transaction; category: string; flow: Flow; shared: boolean; conflict: boolean };
type BudgetDraft = { month: string; currency: string; category: string; amount: string; revision: number; conflict?: boolean };
type ImportedResult = { imported: number; duplicates: number; conflicts: number; confirmedAt: string; resultMonths: { month: string; recordCount: number }[]; requestId?: string; batchId?: string | null };
type Pending = { kind: 'transaction'; id: string; payload: ReturnType<typeof transactionPatch> }
  | { kind: 'budget'; payload: ReturnType<typeof budgetPayload> }
  | { kind: 'finance'; payload: ReturnType<typeof sharedSnapshotPayload> }
  | { kind: 'confirm'; preview: RelationPreview; transactionId: string }
  | { kind: 'revoke'; relation: Relation; transactionId: string };
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const foreground = () => typeof document === 'undefined' || !document.hidden;
const message = (v: unknown) => v instanceof Error ? v.message : '暂时无法完成操作，请刷新核对。';
const currentMonth = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit' }).format(new Date());
const sharedConsent = '将本笔金额纳入共同消费汇总';
const sharedNumericFields = [...sharedFinanceFields, 'contributionPercent'] as const;
const sharedInputs = (base: SharedSnapshot): Record<string, string> => ({ ...Object.fromEntries(sharedFinanceFields.map(k => [k, centsToDecimal(base[k])])), contributionPercent: String(base.contributionPercent), note: base.note });
const time = (s: string | null | undefined) => s ? s.replace('T', ' ').replace(/\.\d+/, '') : '尚未记录';
const decimalDisplay = (value: number) => formatFinanceAmount(value, 'CNY');

function Check({ label, checked, disabled, onPress }: { label: string; checked: boolean; disabled: boolean; onPress: () => void }) {
  const styles = useStyles();
  const keyboard = Platform.OS === 'web' ? { onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => { if (e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); e.stopPropagation(); if (!e.repeat && !disabled) onPress(); } } } : {};
  return <TouchableRipple {...keyboard} accessibilityRole="checkbox" accessibilityLabel={label} accessibilityState={{ checked, disabled }} aria-checked={checked} aria-disabled={disabled} disabled={disabled} onPress={onPress} style={styles.check}>
    <View style={styles.row} pointerEvents="none" aria-hidden accessibilityElementsHidden importantForAccessibility="no-hide-descendants"><Icon source={checked ? 'checkbox-marked' : 'checkbox-blank-outline'} size={24} /><Text style={styles.grow}>{label}</Text></View>
  </TouchableRipple>;
}
function Amount({ cents, currency, prominent = false }: { cents: number; currency: string; prominent?: boolean }) {
  const styles = useStyles();
  return <Text variant={prominent ? 'headlineSmall' : 'bodyMedium'} style={styles.money}>{formatFinanceAmount(cents, currency)}</Text>;
}
function TransactionCopy({ row }: { row: Transaction }) {
  const styles = useStyles();
  return <View style={styles.stackSmall}><Text variant="titleMedium" style={styles.wrap}>{row.title}</Text><Amount cents={row.amountCents} currency={row.currency} /><Text style={styles.muted}>{row.date} · {sourceLabel(row.source)} · {row.kind === 'orders' ? '订单' : flowLabels[row.flow]} · {row.category}</Text></View>;
}

export default function FinanceScreen(props: ScreenProps) {
  const household = useHousehold();
  if (props.user.role !== 'member') return <EmptyState title="财务明细仅本人查看" description="请使用成员账户登录。电视不能读取个人财务。" />;
  return <FinanceWorkspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function FinanceWorkspace(props: ScreenProps & { identityKey: string }) {
  const styles = useStyles();
  const household = useHousehold(), theme = useTheme(), { height, width } = useWindowDimensions();
  const latest = useRef(household); latest.current = household;
  const alive = useRef(false), active = useRef(false), focused = useRef(false), denied = useRef(false), writing = useRef(false), reading = useRef(false);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), epoch = useRef(0);
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), props.user, props.identityKey));
  const query = useRef<Query>({ month: currentMonth(), q: '', page: 1 });
  const [data, setData] = useState<Data | null>(null), [visible, setVisible] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [tab, setTab] = useState<'shared' | 'ledger' | 'budgets'>('shared');
  const [monthInput, setMonthInput] = useState(query.current.month), [searchInput, setSearchInput] = useState(''), [ledgerChanged, setLedgerChanged] = useState(false);
  const [detail, setDetailState] = useState<Reconciliation | null>(null), detailRef = useRef<Reconciliation | null>(null);
  const [edit, setEditState] = useState<Edit | null>(null), editRef = useRef<Edit | null>(null);
  const [candidate, setCandidate] = useState<Candidate | null>(null), [allocation, setAllocation] = useState(''), [preview, setPreview] = useState<RelationPreview | null>(null), [revoke, setRevoke] = useState<Relation | null>(null), [relationQuery, setRelationQuery] = useState('');
  const [budget, setBudgetState] = useState<BudgetDraft | null>(null), budgetRef = useRef<BudgetDraft | null>(null);
  const [sharedEditor, setSharedEditorState] = useState<{ base: SharedSnapshot; inputs: Record<string, string>; conflict: boolean } | null>(null), sharedRef = useRef<typeof sharedEditor>(null);
  const [pending, setPendingState] = useState<Pending | null>(null), pendingRef = useRef<Pending | null>(null);
  const [importing, setImporting] = useState(false), [importMonths, setImportMonths] = useState<{ month: string; recordCount: number }[]>([]);
  const current = () => alive.current && active.current && focused.current && appActive.current && !denied.current && latest.current.identityKey === props.identityKey && latest.current.online && online() && foreground();
  const setDetail = (v: Reconciliation | null) => { detailRef.current = v; setDetailState(v); };
  const setEdit = (v: Edit | null) => { editRef.current = v; setEditState(v); };
  const setBudget = (v: BudgetDraft | null) => { budgetRef.current = v; setBudgetState(v); };
  const setSharedEditor = (v: typeof sharedEditor) => { sharedRef.current = v; setSharedEditorState(v); };
  const setPending = (v: Pending | null) => { pendingRef.current = v; setPendingState(v); };
  function closeDetail() { setDetail(null); setEdit(null); setCandidate(null); setPreview(null); setRevoke(null); setRelationQuery(''); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); reading.current = false; writing.current = false;
    setVisible(false); setBusy(false); setData(null); setPreview(null); setRevoke(null);
    if (clear) { closeDetail(); setBudget(null); setSharedEditor(null); setPending(null); setNotice(''); setError(''); setImporting(false); setImportMonths([]); }
  }
  function failure(caught: unknown) {
    if (!current()) return;
    if (caught instanceof PhotoReadDiscarded && caught.message !== 'identity') return;
    if (caught instanceof PhotoReadDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) { conceal(true); denied.current = true; setError('登录身份已变化，请重新打开财务页面。'); void latest.current.refresh(); return; }
    if (caught instanceof ApiError && caught.code === 'ledger_changed') setLedgerChanged(true);
    setError(message(caught));
  }
  async function guarded<T>(load: () => Promise<T>, ticket = epoch.current) { return fence.current.read(load, () => current() && ticket === epoch.current); }
  async function fetchDetail(id: string, q = '', ticket = epoch.current) { return readReconciliation(await guarded(() => request<unknown>('/finance-hub/reconciliation?' + new URLSearchParams({ transactionId: id, q })), ticket)); }
  async function fetchFocus(id: string, q = ''): Promise<Reconciliation | null> {
    const ticket = epoch.current;
    try { return await fetchDetail(id, q, ticket); }
    catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 404)) throw caught;
      // A failed GET does not run the fence's post-read check. Verify the
      // complete session again before installing the already-read ledger.
      await guarded(async () => true, ticket); return null;
    }
  }
  function installDetail(next: Reconciliation, reset = false) {
    setDetail(next); const prior = editRef.current;
    if (reset || !prior || prior.original.id !== next.transaction.id) setEdit({ original: next.transaction, category: next.transaction.category, flow: next.transaction.flow, shared: next.transaction.visibility === 'shared', conflict: false });
    else if (prior.original.revision !== next.transaction.revision) setEdit({ ...prior, conflict: true });
  }
  async function fetchData(resetSnapshot = false): Promise<Data> {
    const q = { ...query.current }; if (resetSnapshot) delete q.snapshot;
    const result = await guarded(async () => {
      const [overview, ledger, shared, state] = await Promise.all([request<unknown>('/finance-hub/overview?month=' + q.month), request<unknown>(ledgerPath(q)), request<{ month: string; totals: unknown }>('/finance-hub/shared?month=' + q.month), request<{ finance: unknown }>('/state')]);
      const o = readOverview(overview), l = readLedger(ledger); if (o.month !== q.month || l.month !== q.month || l.q !== q.q || shared.month !== q.month) throw new Error('账本筛选结果无法核对，请刷新。');
      return { overview: o, ledger: l, shared: readTotals(shared.totals), finance: readSharedSnapshot(state.finance) };
    });
    return result;
  }
  function installData(next: Data) {
    setData(next); query.current = { ...query.current, page: next.ledger.page, snapshot: next.ledger.snapshot }; setLedgerChanged(false);
    const b = budgetRef.current;
    if (b && b.month === next.overview.month) { const fresh = next.overview.budgets.find(v => v.currency === b.currency && v.category === b.category); if ((fresh?.revision || 0) !== b.revision) setBudget({ ...b, conflict: true }); }
    const s = sharedRef.current; if (s && s.base.revision !== next.finance.revision) setSharedEditor({ ...s, conflict: true });
  }
  async function recover(intent: Pending, acknowledged = false) {
    let matches = false;
    const next = await fetchData(true);
    if (intent.kind === 'transaction' || intent.kind === 'confirm' || intent.kind === 'revoke') {
      const context = await fetchFocus(intent.kind === 'transaction' ? intent.id : intent.transactionId);
      if (!context) {
        if (!current()) return;
        closeDetail(); installData(next); setPending(null); setVisible(true); setTab('ledger');
        setNotice('当前记录已不存在。本次操作的历史结果无法仅凭当前缺失确认；已回到账本，不会自动重复提交或重建记录。'); void latest.current.refresh(); return;
      }
      if (intent.kind === 'transaction') { const row = context.transaction, p = intent.payload; matches = row.revision > p.revision && row.category === p.category && row.flow === p.flow && row.visibility === p.visibility; }
      else if (intent.kind === 'confirm') { const p = intent.preview; matches = context.relations.some(r => r.kind === p.kind && r.leftId === p.leftId && r.rightId === p.rightId && r.amountCents === p.amountCents && r.status === 'active'); }
      else matches = context.relations.some(r => r.id === intent.relation.id && r.status === 'revoked' && r.revision > intent.relation.revision);
      if (!current()) return;
      installDetail(context, matches); setPreview(null); setCandidate(null); setRevoke(null);
    } else if (intent.kind === 'budget') { const p = intent.payload; const view = p.month === next.overview.month ? next.overview : readOverview(await guarded(() => request<unknown>('/finance-hub/overview?month=' + p.month)));
      matches = view.budgets.some(b => b.month === p.month && b.currency === p.currency && b.category === p.category && b.revision > p.revision && centsToDecimal(b.amountCents) === p.amount); if (matches) setBudget(null);
    } else { const p = intent.payload; matches = next.finance.revision > p.revision && sharedNumericFields.every(k => next.finance[k] === p[k]) && next.finance.note === p.note; if (matches) setSharedEditor(null); }
    if (!current()) return;
    installData(next); setPending(null); setVisible(true);
    setNotice(matches ? (acknowledged ? '已保存，并读取最新记录核对。' : '已读取最新记录：当前状态与本次操作一致。') : '已读取最新记录，但当前状态与本次操作不一致。请核对最新版本后重新决定；不会自动重复提交。');
    if (!matches) { if (editRef.current) setEdit({ ...editRef.current, conflict: true }); if (budgetRef.current) setBudget({ ...budgetRef.current, conflict: true }); if (sharedRef.current) setSharedEditor({ ...sharedRef.current, conflict: true }); }
    void latest.current.refresh();
  }
  async function reload(resetSnapshot = false) {
    if (!current() || reading.current || writing.current) return;
    reading.current = true; setBusy(true); setError(''); const ticket = epoch.current;
    try {
      if (pendingRef.current) await recover(pendingRef.current);
      else { const next = await fetchData(resetSnapshot); const id = detailRef.current?.transaction.id; const context = id ? await fetchFocus(id) : null; if (current() && ticket === epoch.current) { installData(next); if (context) installDetail(context); else if (id) { closeDetail(); setTab('ledger'); setNotice('这条记录已删除或不再存在，已回到最新账本。'); } setVisible(true); } }
    } catch (caught) { if (ticket === epoch.current) { failure(caught); if (!(caught instanceof ApiError && caught.code === 'ledger_changed')) { setVisible(false); setData(null); } } }
    finally { if (ticket === epoch.current) { reading.current = false; if (alive.current) setBusy(false); } }
  }
  function enter() { if (!alive.current || active.current || !focused.current || denied.current || !appActive.current || !online() || !foreground() || !latest.current.online) return; active.current = true; void reload(); }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(true); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => foreground() ? enter() : conceal(); const offline = () => { conceal(); setError('网络已断开，财务内容已隐藏。恢复后会重新核对，原输入暂时保留。'); }; const connected = () => enter();
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); }
    const subscription = AppState.addEventListener('change', state => { appActive.current = state === 'active'; if (appActive.current) enter(); else conceal(); });
    const timer = setInterval(() => { if (current() && !reading.current && !writing.current) void guarded(async () => true).catch(failure); }, 15000);
    return () => { if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility); if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); } subscription.remove(); clearInterval(timer); };
  }, [props.identityKey]);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  async function operation(job: () => Promise<void>) {
    if (!current() || reading.current || writing.current || pendingRef.current) return;
    writing.current = true; setBusy(true); setError(''); setNotice(''); const ticket = epoch.current;
    try { await job(); }
    catch (caught) {
      if (ticket !== epoch.current || !current()) return;
      if (caught instanceof ApiError && caught.status > 0 && caught.status < 500) {
        setPending(null); if (caught.status === 409) { setPreview(null); if (editRef.current) setEdit({ ...editRef.current, conflict: true }); if (budgetRef.current) setBudget({ ...budgetRef.current, conflict: true }); if (sharedRef.current) setSharedEditor({ ...sharedRef.current, conflict: true }); }
      }
      failure(caught);
      if (current() && pendingRef.current) { setNotice('操作结果尚未确认，正在只读核对；不会自动重复提交。'); try { await recover(pendingRef.current); } catch (followup) { failure(followup); if (current()) setNotice('操作结果尚未确认，请点击“刷新核对结果”。不要重复提交。'); } }
    } finally { if (ticket === epoch.current) { writing.current = false; if (alive.current) setBusy(false); } }
  }
  async function write(intent: Pending, path: string, method: string, payload: unknown, validate?: (v: unknown) => unknown) {
    setPending(intent); const result = await guarded(() => latest.current.mutate<unknown>(path, method, payload)); if (validate) validate(result); await recover(intent, true);
  }
  function changeMonth(value: string) {
    if (!validFinanceMonth(value)) { setError('请填写有效月份，例如 2026-09。'); return; }
    if (busy || pendingRef.current || !current()) return;
    query.current = { month: value, q: '', page: 1 }; setMonthInput(value); setSearchInput(''); closeDetail(); void reload(true);
  }
  function search() { if (!current() || busy || pending) return; query.current = { ...query.current, q: searchInput.trim(), page: 1 }; void reload(); }
  function turnPage(page: number) { if (!current() || busy || pending || ledgerChanged) return; query.current = { ...query.current, page }; void reload(); }
  async function openTransaction(id: string, reset = true, q = '') {
    await operation(async () => { const context = await fetchFocus(id, q); if (!current()) return;
      if (!context) { const next = await fetchData(true); if (current()) { closeDetail(); installData(next); setTab('ledger'); setNotice('这条记录已删除或不再存在，已回到最新账本。'); } return; }
      installDetail(context, reset); setCandidate(null); setPreview(null); setRevoke(null); if (reset) setRelationQuery(''); });
  }
  async function saveTransaction() {
    const draft = editRef.current; if (!draft || draft.conflict) return;
    await operation(async () => { const payload = transactionPatch(draft.original, draft.category, draft.flow, draft.shared); await write({ kind: 'transaction', id: draft.original.id, payload }, '/finance-hub/transactions/' + draft.original.id, 'PATCH', payload); });
  }
  async function previewRelation() {
    const pair = candidate; if (!pair) return;
    await operation(async () => { const result = readRelationPreview(await guarded(() => latest.current.mutate('/finance-hub/reconciliation/preview', 'POST', { kind: pair.kind, leftId: pair.left.id, rightId: pair.right.id, amount: decimalInput(allocation, true) })));
      if (!current()) return; if (result.kind !== pair.kind || result.leftId !== pair.left.id || result.rightId !== pair.right.id || result.amountCents > pair.maxAmountCents || centsToDecimal(result.amountCents) !== decimalInput(allocation, true)) throw new Error('预览与本次选择不一致，请重新核对。'); setPreview(result); });
  }
  async function confirmRelation() {
    const p = preview, id = detailRef.current?.transaction.id; if (!p || !id) return;
    await operation(async () => { await write({ kind: 'confirm', preview: p, transactionId: id }, '/finance-hub/reconciliation/confirm', 'POST', { previewToken: p.previewToken }, v => readRelation((v as { relation: unknown })?.relation)); });
  }
  async function revokeRelation() {
    const relation = revoke, id = detailRef.current?.transaction.id; if (!relation || !id) return;
    await operation(async () => { await write({ kind: 'revoke', relation, transactionId: id }, '/finance-hub/reconciliation/' + relation.id + '/revoke', 'POST', { revision: relation.revision }, v => readRelation((v as { relation: unknown })?.relation)); });
  }
  function openBudget(row?: Budget) { if (busy || pending || !current()) return; setBudget(row ? { month: row.month, currency: row.currency, category: row.category, amount: centsToDecimal(row.amountCents), revision: row.revision } : { month: query.current.month, currency: 'CNY', category: '全部', amount: '', revision: 0 }); setError(''); }
  async function refreshBudget() {
    const draft = budgetRef.current; if (!draft) return;
    await operation(async () => { const p = budgetPayload({ ...draft, amount: draft.amount || '0' }), view = readOverview(await guarded(() => request('/finance-hub/overview?month=' + p.month))); const row = view.budgets.find(b => b.currency === p.currency && b.category === p.category);
      if (current()) { setBudget({ ...draft, ...p, amount: row ? centsToDecimal(row.amountCents) : draft.amount, revision: row?.revision || 0, conflict: false }); setNotice('已读取此月份、币种与分类的最新预算。请核对金额后再保存。'); } });
  }
  async function saveBudget() { const draft = budgetRef.current; if (!draft || draft.conflict) return; await operation(async () => { const payload = budgetPayload(draft); await write({ kind: 'budget', payload }, '/finance-hub/budgets', 'PUT', payload); }); }
  function openShared(base: SharedSnapshot) { if (!current() || busy || pending) return; setSharedEditor({ base, inputs: sharedInputs(base), conflict: false }); }
  async function refreshShared() { await operation(async () => { const response = await guarded(() => request<{ finance: unknown }>('/state')); const base = readSharedSnapshot(response.finance); if (current()) { setSharedEditor({ base, inputs: sharedInputs(base), conflict: false }); setNotice('已读取共同资金的最新值。请重新核对后保存。'); } }); }
  async function saveShared() { const editor = sharedRef.current; if (!editor || editor.conflict) return; await operation(async () => { const payload = sharedSnapshotPayload(editor.base, editor.inputs); await write({ kind: 'finance', payload }, '/finance', 'PUT', payload); }); }
  const locked = busy || !!pending || !current(), privateVisible = visible && current();
  const dialogStyle = [styles.dialog, { maxHeight: Math.max(240, height - 40), backgroundColor: theme.colors.surfaceVariant }];
  const recoveryAction = pending ? <Button disabled={busy || !current()} onPress={() => void reload(true)}>刷新核对结果</Button> : null;
  const monthControls = <View style={styles.stack}><View style={styles.row}><TextInput label="账本月份" accessibilityLabel="账本月份" value={monthInput} maxLength={7} disabled={locked} onChangeText={setMonthInput} mode="outlined" style={[styles.input, styles.monthInput]} /><Button disabled={locked} onPress={() => changeMonth(monthInput)}>查看月份</Button></View>
    {!!importMonths.length && <View style={styles.stackSmall}><Text>本次导入涉及月份</Text><View style={styles.row}>{importMonths.map(m => <Button key={m.month} disabled={locked} mode="outlined" onPress={() => { setTab('ledger'); changeMonth(m.month); }}>{m.month} · {m.recordCount} 笔</Button>)}</View></View>}
    {!!data?.overview.availableMonths.length && <ScrollView horizontal showsHorizontalScrollIndicator accessibilityLabel="已有记录的月份"><View style={styles.row}>{data.overview.availableMonths.map(m => <Button key={m.month} mode={query.current.month === m.month ? 'contained' : 'text'} disabled={locked} onPress={() => changeMonth(m.month)}>{m.month} · {m.recordCount}</Button>)}</View></ScrollView>}
  </View>;

  if (importing) return <FinanceImportPanel onClose={() => { setImporting(false); if (current()) void reload(true); }} onImported={(result: ImportedResult) => {
    if (!current()) return; setImporting(false); setTab('ledger'); setImportMonths(result.resultMonths); setNotice(`已导入 ${result.imported} 笔，重复 ${result.duplicates} 笔，保留冲突旧记录 ${result.conflicts} 笔。确认时间：${time(result.confirmedAt)}。`);
    if (result.resultMonths.length) changeMonth(result.resultMonths[0].month); else void reload(true);
  }} />;

  return <View style={styles.page}>
    <PageHeader title={detail && privateVisible ? '交易详情' : '家庭资金'} description={detail && privateVisible ? '保留原始金额，核对分类与关联。' : '共同资金一起看，个人账本自己管。'} action={<View style={styles.row}>{detail && privateVisible ? <Button disabled={locked} onPress={closeDetail}>返回账本</Button> : <Button icon="file-upload-outline" accessibilityLabel="导入账单" mode="contained" disabled={locked || !privateVisible} onPress={() => { closeDetail(); setImporting(true); }}>导入账单</Button>}<Button icon="refresh" accessibilityLabel={pending ? '刷新核对结果' : '刷新账本'} disabled={busy || !online() || denied.current} onPress={() => { if (!active.current) enter(); else void reload(true); }}>{pending ? '刷新核对结果' : '刷新账本'}</Button></View>} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {!!notice && privateVisible && <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对财务记录" />}
    {!privateVisible && <EmptyState title={busy ? '正在核对登录与财务记录' : '财务内容已隐藏'} description="联网并确认本人身份后，才能查看和编辑。" />}
    {privateVisible && data && <>
      {ledgerChanged && <View style={styles.warning}><Text>账本已变化。请刷新后重新查看，当前页面不能继续翻页。</Text><Button disabled={locked} onPress={() => { query.current.page = 1; void reload(true); }}>刷新到最新账本</Button></View>}
      {!detail ? <>
        <View style={styles.row}>{([['shared', '共同资金'], ['ledger', '我的账本'], ['budgets', '月预算']] as const).map(([key, label]) => <Button key={key} mode={tab === key ? 'contained' : 'outlined'} disabled={locked} onPress={() => setTab(key)}>{label}</Button>)}</View>
        {monthControls}
        {tab === 'shared' && <>
          <SectionCard title="共同资金快照" action={<Button disabled={locked} onPress={() => openShared(data.finance)}>核对资金</Button>}><View style={styles.stack}><Text style={styles.muted}>手工核对账户余额与准备金。本人账单不会自动修改这些值。</Text><Text variant="displaySmall" style={styles.money}>{data.finance.confirmedAt ? decimalDisplay(data.finance.wallet) : '待核对'}</Text><Text>周转目标 {decimalDisplay(data.finance.reserveTarget)}</Text><View style={styles.grid}>{sharedFinanceFields.filter(k => k !== 'wallet' && k !== 'reserveTarget').map(k => <View key={k} style={[styles.metric, width < 600 && styles.full]}><Text style={styles.muted}>{sharedFinanceLabels[k]}</Text><Text variant="titleLarge" style={styles.money}>{data.finance.confirmedAt ? decimalDisplay(data.finance[k]) : '待核对'}</Text></View>)}</View><Text>税后收入 {data.finance.contributionPercent}% 共同出资</Text><Text style={styles.muted}>最近核对：{time(data.finance.confirmedAt)}</Text>{!!data.finance.note && <Text>{data.finance.note}</Text>}</View></SectionCard>
          <SectionCard title={`${data.overview.month} 已共享消费`}><View style={styles.stack}>{data.shared.length ? data.shared.map(t => <View key={t.currency} style={styles.white}><Text variant="titleMedium">{t.currency} · {t.count} 笔</Text><Amount cents={t.netSpendCents} currency={t.currency} prominent /><Text style={styles.muted}>消费 {formatFinanceAmount(t.expenseCents, t.currency)} · 退款 {formatFinanceAmount(t.refundCents, t.currency)}</Text></View>) : <EmptyState title="这个月还没有共享消费" description="仅在本人逐笔选择共享后，金额才出现在这里。" />}<Text style={styles.muted}>只显示明确共享的消费与退款金额，不公开账户、标题和编号；不会自动改变荷包余额。</Text></View></SectionCard>
        </>}
        {tab === 'ledger' && !ledgerChanged && <>
          <SectionCard title={`${data.overview.month} 本人收支`}><View style={styles.stack}>{data.overview.totals.length ? data.overview.totals.map(t => <View style={styles.white} key={t.currency}><Text variant="titleMedium">{t.currency} · {t.count} 条原始记录</Text><Amount cents={t.netSpendCents} currency={t.currency} prominent /><Text>已记录净消费</Text><Text style={styles.muted}>收入 {formatFinanceAmount(t.incomeCents ?? 0, t.currency)} · 消费 {formatFinanceAmount(t.expenseCents, t.currency)} · 退款 {formatFinanceAmount(t.refundCents, t.currency)}</Text><Text style={styles.muted}>转账 {formatFinanceAmount(t.transferCents ?? 0, t.currency)} · 订单 {formatFinanceAmount(t.orderCents ?? 0, t.currency)} · 待核对 {formatFinanceAmount(t.unknownCents ?? 0, t.currency)}</Text><Text style={styles.muted}>已确认重复 {t.duplicateCount ?? 0} 笔 · {formatFinanceAmount(t.duplicateCents ?? 0, t.currency)}；订单与排除记录不重复计入消费。</Text></View>) : <Text>这个月还没有已导入记录。</Text>}<Text style={styles.muted}>{data.overview.coverage} 各币种独立统计；已记录净消费不能当作账户余额。</Text></View></SectionCard>
          <SectionCard title="完整账本"><View style={styles.stack}><View style={styles.row}><TextInput label="搜索账本" accessibilityLabel="搜索账本" mode="outlined" style={[styles.input, styles.search]} value={searchInput} maxLength={160} disabled={locked} onChangeText={setSearchInput} onSubmitEditing={search} /><Button disabled={locked || ledgerChanged} onPress={search}>搜索</Button></View><Text style={styles.muted}>{data.ledger.month} · 共 {data.ledger.transactionCount} 笔，匹配 {data.ledger.filteredCount} 笔 · 本人所有月份 {data.overview.totalRecordCount} 笔</Text>
            {!data.ledger.transactions.length ? <EmptyState title="没有符合条件的记录" description={data.overview.totalRecordCount ? '可以更换月份、调整搜索词，或导入新的账单。' : '导入账单后，在这里核对来源、分类和关联。'} /> : data.ledger.transactions.map(row => <View key={row.id} testID={'finance-transaction-' + row.id} style={styles.white}><TransactionCopy row={row} /><Text style={styles.muted}>{row.visibility === 'shared' ? '金额已加入共同消费汇总' : '仅本人'}{row.reconciliation?.duplicateOf ? ' · 已确认重复，排除统计' : ''}</Text><Button disabled={locked || ledgerChanged} accessibilityLabel={'查看交易' + row.title} onPress={() => void openTransaction(row.id)}>查看详情</Button></View>)}
            <View style={styles.pagination}><Button disabled={locked || ledgerChanged || !data.ledger.hasPrevious} onPress={() => turnPage(data.ledger.page - 1)}>上一页</Button><Text>第 {data.ledger.page} / {data.ledger.totalPages} 页</Text><Button disabled={locked || ledgerChanged || !data.ledger.hasNext} onPress={() => turnPage(data.ledger.page + 1)}>下一页</Button></View>
          </View></SectionCard>
        </>}
        {tab === 'budgets' && <SectionCard title={`${data.overview.month} 本人月预算`} action={<Button disabled={locked} onPress={() => openBudget()}>新增预算</Button>}><View style={styles.stack}><Text style={styles.muted}>预算按币种与分类独立管理。“全部”是该币种总预算，分类预算不再与总预算相加。花费来自已导入消费减退款，可能尚未覆盖全部支出。</Text>{data.overview.budgets.length ? data.overview.budgets.map(b => <View key={b.currency + b.category} testID={`finance-budget-${b.currency}-${b.category}`} style={styles.white}><Text variant="titleMedium">{b.category} · {b.currency}</Text><Amount cents={b.amountCents} currency={b.currency} prominent /><Text>已记录支出 {formatFinanceAmount(b.spentCents, b.currency)}</Text><Text style={b.remainingCents < 0 ? { color: theme.colors.error } : styles.muted}>剩余额度 {formatFinanceAmount(b.remainingCents, b.currency)}</Text><Button disabled={locked} onPress={() => openBudget(b)}>修改预算</Button></View>) : <EmptyState title="这个月还没有预算" description="可以先设置总预算，再按需要增加分类预算。" />}</View></SectionCard>}
        <View style={styles.row}><Button icon="chart-donut" accessibilityLabel="我的持仓" disabled={locked} onPress={() => props.onNavigate('investments')}>我的持仓</Button><Button icon="folder-outline" accessibilityLabel="来源报告与高级财务" disabled={locked} onPress={() => props.onLegacy('finance')}>来源报告与高级财务</Button></View><Text style={styles.muted}>持仓记录与导入可在「我的持仓」管理。资产基线与来源报告仍在高级财务中查看。</Text>
      </> : <>
        <SectionCard title="原始记录"><View style={styles.stack}><TransactionCopy row={detail.transaction} />{Object.entries({ 来源: sourceLabel(detail.transaction.source), 原始编号: detail.transaction.externalId, 商户订单号: detail.transaction.merchantOrderId, 支付号: detail.transaction.paymentId, 原交易号: detail.transaction.originalTransactionId, 原状态: detail.transaction.status, 入账时间: time(detail.transaction.importedAt), 最近核对: time(detail.transaction.checkedAt) }).filter(([, value]) => value).map(([label, value]) => <Text key={label} style={styles.wrap}>{label}：{value}</Text>)}
          {detail.transaction.provenance?.status === 'recorded' ? <View style={styles.white} testID="finance-provenance"><Text variant="titleMedium">导入来源</Text><Text selectable style={styles.wrap}>导入批次：{detail.transaction.provenance.batchId}</Text><Text style={styles.wrap}>文件名：{detail.transaction.provenance.fileName || '直接粘贴的 CSV 文本'}</Text><Text>文件格式：{detail.transaction.provenance.format.toUpperCase()}</Text>{!!detail.transaction.provenance.sheet && <Text>工作表：{detail.transaction.provenance.sheet}</Text>}<Text>{detail.transaction.provenance.lineKind === 'worksheet_rows' ? '工作表原行号' : 'CSV 物理行号'}：{detail.transaction.provenance.lineStart}–{detail.transaction.provenance.lineEnd}</Text><Text>首次入账：{time(detail.transaction.provenance.importedAt)}</Text><Text style={styles.muted}>重复导入与冲突核对保留首次来源。此处为来源索引，不保存原始附件。</Text></View> : <Text style={styles.muted}>历史来源批次未记录，不能从时间推断所属文件。</Text>}
          {detail.transaction.orderItems?.map((item, index) => <View key={index} style={styles.white}><Text>{item.title}</Text>{!!item.variant && <Text>{item.variant}</Text>}<Text style={styles.muted}>数量原文：{item.quantityText || '未记录'} · 商品金额原文：{item.listedAmountText || '未记录'} · 原工作表第 {item.sourceLine} 行</Text>{!!item.productUrl && <Text selectable style={styles.wrap}>{item.productUrl}</Text>}</View>)}
          <Text style={styles.muted}>金额和原始文件内容保留原值，分类核对不会改写来源。商品金额原文不用于重复计算订单实付。</Text>
        </View></SectionCard>
        {edit && <SectionCard title="核对分类与共享"><View style={styles.stack}><TextInput accessibilityLabel="交易分类" label="交易分类" maxLength={60} mode="outlined" style={styles.input} disabled={locked} value={edit.category} onChangeText={value => setEdit({ ...edit, category: value })} /><View style={styles.row}>{(Object.entries(flowLabels) as [Flow, string][]).map(([flow, label]) => <Button key={flow} disabled={locked} mode={edit.flow === flow ? 'contained' : 'outlined'} onPress={() => setEdit({ ...edit, flow, shared: ['expense', 'refund'].includes(flow) ? edit.shared : false })}>{label}</Button>)}</View><Check label={sharedConsent} checked={edit.shared} disabled={locked || edit.original.kind !== 'payments' || !['expense', 'refund'].includes(edit.flow)} onPress={() => setEdit({ ...edit, shared: !edit.shared })} /><Text style={styles.muted}>共享后家人可见该月的消费与退款金额汇总；标题、账户、来源、编号和本人收入仍仅本人可见。</Text>{edit.conflict && <Text style={styles.warning}>记录已变化，原输入保留。请重新读取交易，再核对最新版本。</Text>}<View style={styles.row}><Button mode="contained" disabled={locked || edit.conflict || ledgerChanged} onPress={() => void saveTransaction()}>保存核对</Button><Button disabled={locked} onPress={() => void openTransaction(detail.transaction.id)}>重新读取交易</Button></View></View></SectionCard>}
        <SectionCard title="订单、付款与退款"><View style={styles.stack}><Text style={styles.muted}>{detail.note}</Text><View style={styles.row}><TextInput label="查找订单或付款" accessibilityLabel="查找订单或付款" maxLength={160} mode="outlined" style={[styles.input, styles.search]} disabled={locked} value={relationQuery} onChangeText={setRelationQuery} /><Button disabled={locked} onPress={() => void openTransaction(detail.transaction.id, false, relationQuery.trim())}>查找关联</Button></View>
          {detail.candidates.length ? detail.candidates.map(pair => <View key={[pair.kind, pair.left.id, pair.right.id].join('-')} testID={`finance-candidate-${pair.kind}-${pair.left.id}-${pair.right.id}`} style={styles.white}><Text variant="titleMedium">{relationLabels[pair.kind]}</Text><Text>{pair.kind === 'duplicate' ? '排除：' : '关联：'}{pair.left.title}</Text><Text>{pair.kind === 'duplicate' ? '保留：' : '付款：'}{pair.right.title}</Text><Text style={styles.muted}>可分配上限 {formatFinanceAmount(pair.maxAmountCents, pair.left.currency)}</Text>{pair.reasons.map((r, i) => <Text key={i}>{r}</Text>)}{pair.uncertainty.map((r, i) => <Text style={styles.muted} key={i}>{r}</Text>)}<Button disabled={locked || ledgerChanged} onPress={() => { setCandidate(pair); setAllocation(centsToDecimal(pair.suggestedAmountCents)); setPreview(null); }}>核对这组记录</Button></View>) : <EmptyState title="没有可用关联候选" description="可用另一笔标题或编号搜索；跨币种、方向不符或已分配完的记录不会作为候选。" />}
          {detail.truncated && <Text>共有 {detail.candidateCount} 组候选，当前显示 40 组。请用标题或编号缩小范围。</Text>}
        </View></SectionCard>
        <SectionCard title="关联历史"><View style={styles.stack}>{detail.relations.length ? detail.relations.map(r => <View key={r.id} testID={'finance-relation-' + r.id} style={styles.white}><Text variant="titleMedium">{relationLabels[r.kind]} · {r.status === 'active' ? '已确认' : '已撤销'}</Text><Text>{r.left?.title || '原记录'} → {r.right?.title || '付款记录'}</Text><Amount cents={r.amountCents} currency={r.left?.currency || r.right?.currency || detail.transaction.currency} /><Text style={styles.muted}>更新：{time(r.updatedAt)}</Text><View style={styles.row}>{r.right && r.rightId !== detail.transaction.id && <Button disabled={locked} onPress={() => void openTransaction(r.rightId)}>查看关联付款</Button>}{r.status === 'active' && <Button disabled={locked || ledgerChanged} onPress={() => setRevoke(r)}>撤销关联</Button>}</View></View>) : <Text>尚未确认关联。候选和预览不会写入账本。</Text>}<Text style={styles.muted}>显示最近 100 条关联历史，含撤销记录。退款按退款发生的月份计入，关联不会推断全额退款。</Text></View></SectionCard>
      </>}
    </>}
    <Portal>
      <Dialog visible={privateVisible && !!candidate} onDismiss={() => { if (!locked) { setCandidate(null); setPreview(null); } }} style={dialogStyle}>
        <Dialog.Title>{preview ? '确认关联' : '核对关联记录'}</Dialog.Title><Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.dialogContent}>
          {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}{!!pending && <Text>操作结果尚未确认。请先刷新核对结果。</Text>}
          {candidate && <><Text variant="titleMedium">{relationLabels[candidate.kind]}</Text><Text>{candidate.kind === 'duplicate' ? '从统计排除的记录' : '订单或退款'}</Text><TransactionCopy row={candidate.left} /><Divider /><Text>{candidate.kind === 'duplicate' ? '保留计入统计的记录' : '对应付款'}</Text><TransactionCopy row={candidate.right} />{!preview ? <><TextInput label="分配金额" accessibilityLabel="分配金额" mode="outlined" style={styles.input} value={allocation} keyboardType="decimal-pad" disabled={locked || candidate.kind === 'duplicate'} onChangeText={setAllocation} /><Text>可分配上限 {formatFinanceAmount(candidate.maxAmountCents, candidate.left.currency)}{candidate.kind === 'duplicate' ? '；重复记录按整笔金额核对。' : ''}</Text></> : <><Amount cents={preview.amountCents} currency={preview.left.currency} prominent /><Text>{preview.effect}</Text>{preview.uncertainty.map((v, i) => <Text style={styles.muted} key={i}>{v}</Text>)}<Text>我已核对这两笔记录及金额，确认后才修改本地关联和统计。</Text></>}</>}
        </ScrollView></Dialog.ScrollArea><Dialog.Actions style={styles.row}>{recoveryAction}<Button disabled={locked} onPress={() => { setCandidate(null); setPreview(null); }}>取消</Button>{preview ? <Button mode="contained" disabled={locked || ledgerChanged} onPress={() => void confirmRelation()}>确认关联</Button> : <Button mode="contained" disabled={locked || ledgerChanged} onPress={() => void previewRelation()}>预览关联</Button>}</Dialog.Actions>
      </Dialog>
      <Dialog visible={privateVisible && !!revoke} onDismiss={() => { if (!locked) setRevoke(null); }} style={dialogStyle}><Dialog.Title>撤销这项关联</Dialog.Title><Dialog.Content>{!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}<Text>仅撤销本地关联，不删除原始流水。重复记录将恢复计入统计；退款分配恢复自身分类。云端订单与付款不会改变。</Text></Dialog.Content><Dialog.Actions style={styles.row}>{recoveryAction}<Button disabled={locked} onPress={() => setRevoke(null)}>保留关联</Button><Button mode="contained" disabled={locked} onPress={() => void revokeRelation()}>确认撤销</Button></Dialog.Actions></Dialog>
      <Dialog visible={privateVisible && !!budget} onDismiss={() => { if (!locked) setBudget(null); }} style={dialogStyle}><Dialog.Title>{budget?.revision ? '修改本人预算' : '新增本人预算'}</Dialog.Title><Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.dialogContent}>
        {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}{budget && <>{(['month', 'currency', 'category', 'amount'] as const).map(key => <TextInput key={key} accessibilityLabel={{ month: '预算月份', currency: '预算币种', category: '预算分类', amount: '预算金额' }[key]} label={{ month: '预算月份', currency: '预算币种', category: '预算分类', amount: '预算金额' }[key]} mode="outlined" style={styles.input} value={budget[key]} maxLength={key === 'category' ? 60 : key === 'currency' ? 3 : key === 'month' ? 7 : 18} disabled={locked || budget.revision > 0 && key !== 'amount'} onChangeText={value => setBudget({ ...budget, [key]: value })} />)}<Text style={styles.muted}>预算币种填写 CNY、USD 等三位代码。“全部”表示同币种本月总预算。金额不会换算为其他币种。</Text>{budget.conflict && <Text style={styles.warning}>预算已存在或版本已变化。原输入保留，请读取最新预算再核对金额。</Text>}</>}
      </ScrollView></Dialog.ScrollArea><Dialog.Actions style={styles.row}>{recoveryAction}<Button disabled={locked} onPress={() => setBudget(null)}>取消</Button><Button disabled={locked} onPress={() => void refreshBudget()}>读取最新预算</Button><Button mode="contained" disabled={locked || !!budget?.conflict} onPress={() => void saveBudget()}>保存预算</Button></Dialog.Actions></Dialog>
      <Dialog visible={privateVisible && !!sharedEditor} onDismiss={() => { if (!locked) setSharedEditor(null); }} style={dialogStyle}><Dialog.Title>核对共同资金</Dialog.Title><Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.dialogContent}>
        {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}<Text>请根据共同账户实际情况核对。保存会更新家人可见的共同资金快照；本人账本、投资和消费记录不会写入这些金额。</Text>{sharedEditor && <>{[...sharedFinanceFields, 'contributionPercent', 'note'].map(key => <TextInput key={key} label={key === 'contributionPercent' ? '共同出资比例（%）' : key === 'note' ? '共同资金备注' : sharedFinanceLabels[key as keyof typeof sharedFinanceLabels]} accessibilityLabel={key === 'contributionPercent' ? '共同出资比例（%）' : key === 'note' ? '共同资金备注' : sharedFinanceLabels[key as keyof typeof sharedFinanceLabels]} mode="outlined" style={styles.input} value={sharedEditor.inputs[key]} disabled={locked} maxLength={key === 'note' ? 500 : 18} onChangeText={value => setSharedEditor({ ...sharedEditor, inputs: { ...sharedEditor.inputs, [key]: value } })} />)}{sharedEditor.conflict && <Text style={styles.warning}>共同资金已经变化。请读取最新资金，重新核对后再保存。</Text>}</>}
      </ScrollView></Dialog.ScrollArea><Dialog.Actions style={styles.row}>{recoveryAction}<Button disabled={locked} onPress={() => setSharedEditor(null)}>取消</Button><Button disabled={locked} onPress={() => void refreshShared()}>读取最新资金</Button><Button mode="contained" disabled={locked || !!sharedEditor?.conflict} onPress={() => void saveShared()}>确认共同资金</Button></Dialog.Actions></Dialog>
    </Portal>
  </View>;
}
function useStyles() {
  const theme = useTheme();
  return StyleSheet.create({
    page: { gap: 20 }, stack: { gap: 16 }, stackSmall: { gap: 7 }, row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, grow: { flex: 1, minWidth: 0 }, wrap: { flexShrink: 1 }, muted: { color: theme.colors.onSurfaceVariant, flexShrink: 1 }, money: { fontVariant: ['tabular-nums'], flexShrink: 1 },
    grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, metric: { minWidth: 0, flexBasis: '45%', flexGrow: 1, gap: 6 }, full: { flexBasis: '100%' }, white: { backgroundColor: theme.colors.surface, borderRadius: 16, padding: 16, gap: 10, minWidth: 0 },
    input: { minWidth: 0, backgroundColor: theme.colors.surface }, search: { flexGrow: 1, flexShrink: 1, flexBasis: 180 }, monthInput: { flexGrow: 1, flexShrink: 1, maxWidth: 180, minWidth: 100 }, check: { padding: 8, borderRadius: 10 },
    notice: { backgroundColor: theme.colors.secondaryContainer, padding: 16, borderRadius: 16 }, warning: { backgroundColor: theme.dark ? theme.colors.tertiaryContainer : '#fff5df', padding: 14, borderRadius: 14, gap: 10 }, pagination: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
    dialog: { width: '92%', maxWidth: 640, alignSelf: 'center', borderRadius: 24 }, dialogScroll: { paddingHorizontal: 0, flexShrink: 1 }, dialogContent: { padding: 20, gap: 16 },
  });
}
