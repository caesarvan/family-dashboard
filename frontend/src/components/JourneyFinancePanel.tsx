import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import { AppState, StyleSheet, View } from 'react-native';
import { ActivityIndicator, Button, Dialog, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { ApiError } from '../lib/api';
import { PlaceDiscarded, type PlaceSession } from '../lib/places';
import { centsToDecimal, formatFinanceAmount, sourceLabel } from '../lib/finance';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import {
  JOURNEY_FINANCE, JourneyConfirmRejected, JourneyFinanceFence, allocationPlan, allocationsPath, checkedConfirm,
  identityDigest, journeyRequest, newIntent, paymentsPath, persistIntent, readAllocations, readConfirmation,
  readOperation, readOriginalPayment, readPayments, readPreview, reasonText, restoreIntent,
  type Allocation, type Allocations, type Intent, type JourneyRef, type OriginalPayment, type Payment,
  type Payments, type PendingStore, type Plan, type Preview, type Query, type Receipt,
} from '../lib/journeyFinance';

type Props = { journeyId?: string; paymentId?: string; onBack: () => void; onPendingChange?: (pending: boolean) => void };
type Draft = { operation: 'apply' | 'update' | 'revoke'; link?: Allocation; journey?: JourneyRef; payment?: Payment; amount: string };
type Model = { rows: Allocations | null; choices: Payments | null; selecting: boolean; draft: Draft | null; preview: Preview | null; pending: Intent | null; receipt: Receipt | null; original: OriginalPayment | null };
const empty = (): Model => ({ rows: null, choices: null, selecting: false, draft: null, preview: null, pending: null, receipt: null, original: null });
const online = () => typeof navigator === 'undefined' || navigator.onLine;
const money = (cents: number) => formatFinanceAmount(cents, 'CNY');
class IdentityReadUnavailable extends Error {}

export default function JourneyFinancePanel(props: Props) {
  const h = useHousehold();
  if (h.user?.role !== 'member') return <EmptyState title="旅行费用仅本人查看" description="请使用成员账户登录。" />;
  return <Workspace key={h.identityKey} {...props} identityKey={h.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), latest = useRef({ props, household }); latest.current = { props, household };
  const [model, setModel] = useState<Model>(empty), live = useRef(model);
  const [busy, setBusy] = useState(false), [visible, setVisible] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [discard, setDiscard] = useState(false), [search, setSearch] = useState(''), [filter, setFilter] = useState<Query>({ journeyId: props.journeyId, paymentId: props.paymentId, page: 0, status: 'active' });
  const query = useRef(filter), searchQuery = useRef({ q: '', page: 0 });
  const alive = useRef(false), focused = useRef(false), active = useRef(false), epoch = useRef(0), working = useRef(false), denied = useRef(false);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const windowFocused = useRef(typeof document === 'undefined' || document.hasFocus()), pageHidden = useRef(false);
  const flight = useRef<AbortController | null>(null), retryProof = useRef<Intent | null>(null);
  const storage = useRef<{ store: PendingStore; digest: string } | null>(null), initialized = useRef(false);
  const fence = useRef(new JourneyFinanceFence(async () => { throw new Error('未初始化核权读取'); }, props.identityKey));
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && !denied.current && appActive.current && windowFocused.current && !pageHidden.current
    && ticket === epoch.current && latest.current.household.identityKey === props.identityKey && latest.current.household.online && online() && (typeof document === 'undefined' || !document.hidden);
  const isPending = () => working.current || !!live.current.draft || !!live.current.pending;
  function notify() { latest.current.props.onPendingChange?.(isPending()); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function keepPending(value: Intent | null) {
    if (!storage.current) throw new Error('当前浏览器无法保存核对请求，请允许会话存储后再确认。');
    persistIntent(storage.current.store, storage.current.digest, value); install({ pending: value }); retryProof.current = null;
  }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    setVisible(false); setBusy(false); working.current = false; setDiscard(false); retryProof.current = null;
    if (clear) {
      if (storage.current) try { persistIntent(storage.current.store, storage.current.digest, null); } catch { /* Storage may have been disabled after submission. */ }
      install(empty()); setSearch(''); searchQuery.current = { q: '', page: 0 }; setNotice('');
    } else install({ rows: null, choices: null, preview: null, original: null });
  }
  function failure(e: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (e instanceof PlaceDiscarded) { if (e.message === 'identity') { denied.current = true; conceal(true); void latest.current.household.refresh(); } return; }
    if (e instanceof IdentityReadUnavailable) { conceal(); setError('身份暂时无法核实，费用内容已隐藏。请联网后刷新核对。'); return; }
    if (e instanceof ApiError && [401, 403].includes(e.status)) { conceal(); setError('身份暂时无法核实，费用内容已隐藏。'); void latest.current.household.refresh(); return; }
    if (e instanceof JourneyConfirmRejected) { install({ preview: null, rows: null, choices: null }); setNotice('请求未获接受，金额草稿仍保留；请刷新后重新预览。'); }
    setError(e instanceof Error ? e.message : '暂时无法读取旅行费用。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    const timer = setTimeout(() => controller.abort(), 20000);
    try { await action(ticket, controller.signal); } catch (e) { failure(e, ticket); }
    finally { clearTimeout(timer); if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  function guard<T>(ticket: number, signal: AbortSignal, action: (csrf: string) => Promise<T>): Promise<T> {
    // Each bounded operation uses the existing pre/post member and session fence.
    const readFence = new JourneyFinanceFence(async () => {
      try { return await journeyRequest('/me', signal) as PlaceSession; }
      catch { throw new IdentityReadUnavailable(); }
    }, props.identityKey);
    fence.current = readFence; return readFence.run(action, () => current(ticket) && !signal.aborted);
  }
  async function initialize(ticket: number) {
    if (initialized.current) return;
    const digest = await identityDigest(props.identityKey);
    if (!current(ticket)) return;
    try {
      const store = window.sessionStorage; storage.current = { store, digest };
      const restored = restoreIntent(store, digest); if (restored) install({ pending: restored });
    } catch { storage.current = null; }
    initialized.current = true;
  }
  async function loadChoices(ticket: number, signal: AbortSignal, draft = live.current.draft) {
    const journeyId = draft?.link?.journeyId || query.current.journeyId;
    if (!journeyId) throw new Error('请从已保存旅行选择实际付款。');
    const q = searchQuery.current;
    const values = readPayments(await guard(ticket, signal, () => journeyRequest(paymentsPath(journeyId, q.q, q.page, draft?.link?.id), signal)), journeyId, q.page, draft?.link?.paymentId);
    if (!current(ticket)) return;
    const payment = draft?.link ? values.focus : values.payments.find(p => p.id === draft?.payment?.id);
    install({ choices: values, draft: draft ? { ...draft, journey: values.journey, payment: payment || undefined } : draft });
  }
  async function load(ticket: number, signal: AbortSignal) {
    const q = { ...query.current };
    install({ rows: null, choices: null, preview: null, original: null });
    const values = readAllocations(await guard(ticket, signal, () => journeyRequest(allocationsPath(q), signal)), q);
    if (!current(ticket)) return;
    const draft = live.current.draft;
    const link = draft?.link ? values.allocations.find(a => a.id === draft.link?.id) : undefined;
    install({ rows: values, ...(draft ? { draft: { ...draft, link, journey: link?.journey || values.journey || undefined, payment: undefined } } : {}) });
    if (draft?.link && (!link || link.status !== 'active')) { install({ draft: null, selecting: false }); setNotice('原归集已变化，以下显示最新记录。'); }
    else if (live.current.selecting || draft && draft.operation !== 'revoke') await loadChoices(ticket, signal, live.current.draft ? { ...live.current.draft, payment: draft?.payment } : null);
    if (current(ticket)) setVisible(true);
  }
  async function receiptRead(ticket: number, signal: AbortSignal) {
    const intent = live.current.pending; if (!intent) return;
    retryProof.current = null;
    const receipt = readOperation(await guard(ticket, signal, () => journeyRequest(JOURNEY_FINANCE + '/operations/' + intent.requestId, signal)), intent);
    if (!current(ticket) || live.current.pending !== intent) return;
    if (!receipt) { retryProof.current = intent; setVisible(true); setNotice('尚未查到原请求回执，不能据此判断未提交。可再次核对，或明确重试同一请求。'); return; }
    keepPending(null); install({ receipt, draft: null, selecting: false, preview: null });
    await afterSaved(ticket, signal);
  }
  async function afterSaved(ticket: number, signal: AbortSignal) {
    setNotice('已保存，正在读取当前归集。');
    try { await load(ticket, signal); if (current(ticket)) setNotice('已保存，以下为当前归集记录；回执不代表关联一直有效。'); }
    catch (e) { if (current(ticket)) { setVisible(true); setNotice('已保存，资料暂未刷新。请刷新旅行费用，只会重新读取。'); } throw e; }
  }
  async function resume(ticket: number, signal: AbortSignal) {
    await initialize(ticket); if (!current(ticket)) return;
    if (live.current.pending) await receiptRead(ticket, signal); else await load(ticket, signal);
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || denied.current || !windowFocused.current || !appActive.current || pageHidden.current || !online() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void job(resume);
  }
  const life = useRef({ enter, conceal }); life.current = { enter, conceal };
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); latest.current.props.onPendingChange?.(false); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; life.current.enter(); return () => { focused.current = false; life.current.conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const sync = () => { if (!online() || typeof document !== 'undefined' && document.hidden) life.current.conceal(); else life.current.enter(); };
    const blur = () => { windowFocused.current = false; life.current.conceal(); }, focus = () => { windowFocused.current = true; sync(); };
    const hide = () => { pageHidden.current = true; life.current.conceal(); }, show = () => { pageHidden.current = false; sync(); };
    const beforeUnload = (e: BeforeUnloadEvent) => { if (isPending()) { e.preventDefault(); e.returnValue = ''; } };
    const app = AppState.addEventListener('change', state => { appActive.current = state === 'active'; if (appActive.current) sync(); else life.current.conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', sync);
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focus); window.addEventListener('offline', sync); window.addEventListener('online', sync); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', beforeUnload); }
    const timer = setInterval(() => { if (current() && !working.current) void job(async (ticket, signal) => { try { await guard(ticket, signal, async () => undefined); } catch (e) { if (current(ticket)) { failure(e, ticket); if (active.current) conceal(); } } }); }, 5000);
    return () => { clearInterval(timer); app.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', sync); if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focus); window.removeEventListener('offline', sync); window.removeEventListener('online', sync); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', beforeUnload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  useEffect(() => {
    if (!model.preview) return;
    const preview = model.preview, timer = setTimeout(() => { if (live.current.preview === preview) { install({ preview: null }); setNotice('预览已过期，请重新预览。'); } }, Math.min(600000, Math.max(0, Date.parse(preview.expiresAt) - Date.now())));
    return () => clearTimeout(timer);
  }, [model.preview]);

  const locked = busy || !current(), unknown = !!model.pending, shown = visible && current();
  function refresh() { if (!latest.current.household.online) void latest.current.household.refresh(); else if (active.current) void job(resume); else enter(); }
  function changeQuery(patch: Partial<Query>) { if (locked || unknown || live.current.draft) return; query.current = { ...query.current, ...patch }; setFilter(query.current); void job(load); }
  function choosePayments() { if (locked || unknown) return; searchQuery.current = { q: '', page: 0 }; setSearch(''); install({ selecting: true, draft: null, preview: null, receipt: null }); void job(loadChoices); }
  function selectPayment(payment: Payment) { if (locked || unknown || !model.choices || !payment.eligible) return; install({ draft: { operation: 'apply', journey: model.choices.journey, payment, amount: '' }, preview: null }); }
  function searchPayments(page = 0) { if (locked || unknown) return; searchQuery.current = { q: search.trim(), page }; install({ preview: null }); void job(async (ticket, signal) => loadChoices(ticket, signal)); }
  function editLink(link: Allocation, operation: 'update' | 'revoke') {
    if (locked || unknown || link.status !== 'active') return;
    install({ draft: { operation, link, journey: link.journey || undefined, amount: centsToDecimal(link.amountCents) }, preview: null, selecting: false, receipt: null });
    if (operation === 'update') { searchQuery.current = { q: '', page: 0 }; void job(async (ticket, signal) => loadChoices(ticket, signal)); }
  }
  async function previewDraft() {
    const draft = live.current.draft; if (!draft || unknown) return;
    await job(async (ticket, signal) => {
      const plan: Plan = draft.operation === 'revoke' && draft.link ? { operation: 'revoke', allocationId: draft.link.id, revision: draft.link.revision }
        : draft.journey && draft.payment ? allocationPlan(draft.journey, draft.payment, draft.amount, draft.link) : (() => { throw new Error('请刷新并选择当前可用的付款。'); })();
      install({ preview: null });
      const preview = readPreview(await guard(ticket, signal, csrf => journeyRequest(JOURNEY_FINANCE + '/preview', signal, plan, csrf)), plan, draft.link ? { journeyId: draft.link.journeyId, paymentId: draft.link.paymentId } : undefined);
      if (current(ticket) && live.current.draft === draft) install({ preview });
    });
  }
  async function submit(retry = false) {
    if (locked) return;
    const intent = retry ? live.current.pending : live.current.preview && newIntent(live.current.preview);
    if (!intent || retry && retryProof.current !== intent || !retry && (live.current.pending || !live.current.preview || Date.parse(live.current.preview.expiresAt) <= Date.now())) return;
    await job(async (ticket, signal) => {
      try {
        const receipt = await checkedConfirm<Receipt>(action => guard(ticket, signal, action), async csrf => {
          keepPending(intent); install({ preview: null, rows: null, choices: null, original: null });
          return readConfirmation(await journeyRequest(JOURNEY_FINANCE + '/confirm', signal, intent, csrf), intent);
        });
        if (!current(ticket)) return;
        keepPending(null); install({ receipt, draft: null, selecting: false }); await afterSaved(ticket, signal);
      } catch (e) {
        if (!current(ticket)) return;
        if (e instanceof JourneyConfirmRejected) keepPending(null);
        else if (live.current.pending) { setVisible(true); setNotice('结果暂未确认，请核对原请求。不会自动重发。'); }
        throw e;
      }
    });
  }
  async function openOriginal(id: string) {
    if (locked || unknown || live.current.draft) return;
    await job(async (ticket, signal) => { const original = readOriginalPayment(await guard(ticket, signal, () => journeyRequest('/finance-hub/reconciliation?transactionId=' + encodeURIComponent(id), signal)), id); if (current(ticket)) install({ original }); });
  }
  function back() { if (locked || unknown) return; if (live.current.draft) setDiscard(true); else props.onBack(); }
  return <View testID="journey-finance-panel" style={styles.page}>
    <PageHeader title="我的旅行费用" description="仅本人已归集的人民币净付款，不是家庭完整费用。" action={<View style={styles.row}><Button disabled={locked || unknown} onPress={back}>返回</Button><Button accessibilityLabel="刷新旅行费用" disabled={busy || denied.current || !online()} onPress={refresh}>刷新旅行费用</Button></View>} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对旅行费用" />}
    {!shown && <View testID="journey-finance-hidden"><EmptyState title="旅行费用已隐藏" description="联网并核对本人身份后继续，未完成的安全草稿暂时保留。" /></View>}
    {shown && <>
      {!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
      {unknown ? <SectionCard title="结果暂未确认"><View testID="journey-finance-unknown" style={styles.stack}><Text>请先核对原请求。刷新页面后仍使用原编号，不会自动再提交。</Text><Button disabled={locked} onPress={() => void job(receiptRead)}>核对原请求</Button><Button disabled={locked || retryProof.current !== model.pending} onPress={() => void submit(true)}>重试原请求</Button></View></SectionCard> : model.original ? <SectionCard title="原付款记录"><View testID="journey-finance-original-payment" style={styles.stack}><Text variant="titleMedium">{model.original.title}</Text><Text>{model.original.date} · {sourceLabel(model.original.source)} · {model.original.category}</Text><Text>{formatFinanceAmount(model.original.amountCents, model.original.currency)}</Text><Text>原记录编号 {model.original.id} · 版本 {model.original.revision}</Text><Text>此处只读显示原付款。归集不会修改付款金额或对账关系。</Text><Button disabled={locked} onPress={() => void job(load)}>返回旅行费用</Button></View></SectionCard> : <>
        {model.rows?.summary && <SectionCard title={model.rows.journey?.title || '当前旅行'}><View testID="journey-finance-summary" style={styles.stack}><Text>仅本人已归集 {money(model.rows.summary.currentAllocatedCents)}</Text><Text>需核对 {money(model.rows.summary.needsReviewAllocatedCents)} · {model.rows.summary.needsReviewCount} 项</Text><Text>旅行共享预算 {money(model.rows.summary.sharedBudgetCents)}</Text><Text>统计覆盖全部归集页，仅代表本人已核对的部分费用。共享预算单列；订单、采购实付、旅行手填已付和储蓄不会与归集相加。</Text></View></SectionCard>}
        {!model.draft && <View style={styles.row}>{filter.journeyId && <Button mode="contained" disabled={locked || !model.rows?.journey} onPress={choosePayments}>选择实际付款</Button>}<Button disabled={locked} onPress={() => changeQuery({ status: filter.status === 'all' ? 'active' : 'all', page: 0 })}>{filter.status === 'all' ? '只看有效归集' : '查看全部历史'}</Button>{filter.journeyId && !model.rows && <Button disabled={locked} onPress={() => changeQuery({ journeyId: undefined, paymentId: undefined, page: 0, status: 'all' })}>查看本人全部历史</Button>}</View>}
        {model.selecting && model.choices && <SectionCard title="选择本人已有实际付款"><View style={styles.stack}><View style={styles.row}><TextInput label="搜索付款" accessibilityLabel="搜索付款" mode="outlined" style={styles.input} value={search} maxLength={80} disabled={locked || !!model.preview} onChangeText={setSearch} /><Button disabled={locked || !!model.preview} onPress={() => searchPayments()}>查找付款</Button></View>{model.choices.payments.map(p => <View key={p.id} testID={'journey-payment-' + p.id} style={[styles.record, { backgroundColor: theme.colors.surface }]}><Text variant="titleMedium">{p.title}</Text><Text>{p.date} · {formatFinanceAmount(p.amountCents, p.currency)}</Text><Text>退款 {formatFinanceAmount(p.refundedCents, p.currency)} · 可用净额 {formatFinanceAmount(p.availableCents, p.currency)}</Text>{!p.eligible && <Text>{reasonText[p.reasonCode || ''] || '这笔付款不能归集'}</Text>}<Button disabled={locked || !p.eligible || !!model.preview} onPress={() => selectPayment(p)}>选择这笔付款</Button></View>)}{!model.choices.payments.length && <Text>没有符合条件的付款，请调整搜索词。</Text>}<View style={styles.row}><Button disabled={locked || !!model.preview || searchQuery.current.page === 0} onPress={() => searchPayments(searchQuery.current.page - 1)}>上一页付款</Button><Text>第 {searchQuery.current.page + 1} 页</Text><Button disabled={locked || !!model.preview || !model.choices.pageInfo.hasMore} onPress={() => searchPayments(searchQuery.current.page + 1)}>下一页付款</Button></View></View></SectionCard>}
        {model.draft && <SectionCard title={model.draft.operation === 'revoke' ? '解除本人归集' : model.draft.operation === 'update' ? '调整本人归集' : '归集这笔付款'}><View style={styles.stack}><Text>{model.draft.journey?.title || '原旅行已不可用'}</Text><Text>{model.draft.payment?.title || model.draft.link?.payment?.title || '原付款已不可用'}</Text>{model.draft.operation !== 'revoke' ? <><TextInput label="归集金额" accessibilityLabel="归集金额" value={model.draft.amount} keyboardType="decimal-pad" mode="outlined" style={styles.input} maxLength={18} disabled={locked || !!model.preview} onChangeText={amount => install({ draft: { ...model.draft!, amount }, preview: null })} /><Text>仅 CNY，最多两位小数。可用净额 {model.draft.payment ? money(model.draft.payment.availableCents) : '请刷新核对'}</Text></> : <Text>仅解除这项归集并释放额度，保留历史。不会删除旅行、原付款或采购记录。</Text>}{model.preview ? <View testID="journey-finance-preview" style={styles.stack}><Text>归集前 {money(model.preview.beforeAllocatedCents)} → 归集后 {money(model.preview.afterAllocatedCents)}</Text>{model.preview.warnings.map((w, i) => <Text key={i}>{w}</Text>)}<Text>请核对旅行、原付款及金额，确认后才保存本人归集。</Text><Button mode="contained" disabled={locked} onPress={() => void submit()}>{model.draft.operation === 'revoke' ? '确认解除' : '确认归集'}</Button></View> : <Button mode="contained" disabled={locked} onPress={() => void previewDraft()}>{model.draft.operation === 'revoke' ? '预览解除' : '预览归集'}</Button>}<Button disabled={locked} onPress={() => { install({ draft: null, preview: null, selecting: false, choices: null }); }}>取消编辑</Button></View></SectionCard>}
        {model.rows && !model.draft && <SectionCard title={filter.paymentId ? '这笔付款的旅行归集' : filter.journeyId ? '本人归集记录' : '本人全部旅行归集'}><View style={styles.stack}>{model.rows.allocations.map(a => <View key={a.id} testID={'journey-allocation-' + a.id} style={[styles.record, { backgroundColor: theme.colors.surface }]}><Text variant="titleMedium">{a.journey?.title || '原旅行已删除'}</Text><Text>{a.payment?.title || '原付款已删除'}</Text><Text>{money(a.amountCents)} · {a.state === 'current' ? '仅本人已归集' : a.state === 'needs_review' ? '需核对' : '已解除'}</Text>{a.reasonCodes.map(r => <Text key={r}>{reasonText[r]}</Text>)}<View style={styles.row}>{a.payment && <Button disabled={locked} onPress={() => void openOriginal(a.paymentId)}>查看原付款</Button>}{a.status === 'active' && <><Button disabled={locked || !a.journey || !a.payment?.eligible} onPress={() => editLink(a, 'update')}>调整归集</Button><Button disabled={locked} onPress={() => editLink(a, 'revoke')}>解除归集</Button></>}</View></View>)}{!model.rows.allocations.length && <EmptyState title="还没有符合条件的归集" description="从已保存旅行选择本人的实际付款；订单不会作为付款重复归集。" />}<View style={styles.row}><Button disabled={locked || (filter.page || 0) === 0} onPress={() => changeQuery({ page: (filter.page || 0) - 1 })}>上一页归集</Button><Text>第 {(filter.page || 0) + 1} 页</Text><Button disabled={locked || !model.rows.pageInfo.hasMore} onPress={() => changeQuery({ page: (filter.page || 0) + 1 })}>下一页归集</Button></View></View></SectionCard>}
      </>}
    </>}
    <Portal><Dialog visible={shown && discard} onDismiss={() => setDiscard(false)}><Dialog.Title>离开旅行费用？</Dialog.Title><Dialog.Content><Text>尚未提交的金额草稿将丢弃。</Text></Dialog.Content><Dialog.Actions><Button onPress={() => setDiscard(false)}>继续编辑</Button><Button onPress={() => { install({ draft: null, preview: null }); setDiscard(false); props.onBack(); }}>放弃草稿并返回</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16, paddingBottom: 24 }, stack: { gap: 12 }, row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' }, input: { flexGrow: 1, minWidth: 180, backgroundColor: 'transparent' }, record: { gap: 8, padding: 16, borderRadius: 12 } });
