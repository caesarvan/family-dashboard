import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, List, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { centsToDecimal, decimalInput, formatFinanceAmount } from '../lib/finance';
import { canEndSettlementReview, checkedSettlementWrite, readSettlementContext, readSettlementPreview, readSettlementReceipt,
  SETTLEMENT_PATH, SettlementDiscarded, SettlementError, SettlementFence, SettlementRejected, settlementPlan, settlementQuery, settlementReadQuery, settlementRequest,
  type SettlementContext, type SettlementDraft, type SettlementIntent, type SettlementLink, type SettlementQuery, type SettlementReceipt,
  type SettlementReview, type SettlementSession } from '../lib/shoppingSettlement';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';

export type ShoppingSettlementSaved = { shoppingId: string; linkId: string; operation: 'apply' | 'update' | 'revoke' };
type Props = { shoppingId?: string; transactionId?: string; onClose: () => void;
  onSaved: (result: ShoppingSettlementSaved) => void | Promise<void>; onPendingChange?: (pending: boolean) => void };
type Model = { context: SettlementContext | null; draft: SettlementDraft; preview: SettlementIntent | null; acknowledged: boolean;
  unknown: SettlementIntent | null; review: SettlementReview | null; receipt: SettlementReceipt | null; completed: boolean; missing: boolean };
const blankDraft = (): SettlementDraft => ({ operation: 'apply', shoppingId: '', paymentId: '', linkId: '', amount: '', done: false, mode: 'detach_keep_current', dirty: false });
const empty = (): Model => ({ context: null, draft: blankDraft(), preview: null, acknowledged: false, unknown: null, review: null, receipt: null, completed: false, missing: false });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const money = (amount: number | null) => amount === null ? '未填写' : formatFinanceAmount(amount, 'CNY');
const done = (value: boolean) => value ? '已买到' : '尚未买到';
const reasons: Record<string, string> = { not_payment: '订单不能直接当作付款', not_expense: '不是实际消费付款', duplicate: '已确认重复，不可再分配', unsupported_currency: '仅支持人民币付款',
  source_missing: '原付款已不可用', source_changed: '付款或退款关系已变化', source_ineligible: '付款已不适合用于核对', shopping_missing: '原采购已不可用', shopping_changed: '采购已被修改，需要重新核对' };

export default function ShoppingSettlementPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户核对采购实付" />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ props, household }); latest.current = { props, household };
  // The caller remounts a deliberately selected target only after its navigation guard.
  const focus = useRef<SettlementQuery>({ ...(props.shoppingId ? { shoppingId: props.shoppingId } : {}), ...(props.transactionId ? { transactionId: props.transactionId } : {}) });
  const [model, setModel] = useState<Model>(empty), live = useRef(model), [query, setQuery] = useState(''), [page, setPage] = useState(0);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [discard, setDiscard] = useState(false);
  const alive = useRef(false), focused = useRef(false), active = useRef(false), epoch = useRef(0), working = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const windowFocused = useRef(typeof document === 'undefined' || document.hasFocus()), pageHidden = useRef(false);
  const flight = useRef<AbortController | null>(null), fence = useRef(new SettlementFence(props.identityKey));
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && foreground.current && windowFocused.current && !pageHidden.current
    && epoch.current === ticket && online() && latest.current.household.online && latest.current.household.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  const pending = () => working.current || live.current.draft.dirty || !!live.current.preview || !!live.current.unknown || !!live.current.receipt && !live.current.completed;
  function notify() { latest.current.props.onPendingChange?.(pending()); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    setVisible(false); working.current = false; setBusy(false); setError(''); setNotice(''); setDiscard(false);
    install(clear ? empty() : { context: null, preview: null, acknowledged: false, review: null, completed: false });
  }
  function failure(e: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (e instanceof SettlementDiscarded) { if (e.message === 'identity') { conceal(true); void latest.current.household.refresh(); } return; }
    if (e instanceof SettlementError && [401, 403].includes(e.status)) { conceal(); setError('身份或权限已变化，资料已隐藏。'); void latest.current.household.refresh(); return; }
    if (e instanceof SettlementError && [404, 410].includes(e.status)) install({ context: null, preview: null, acknowledged: false, review: null, missing: true });
    setError(e instanceof Error ? e.message : '暂时无法核对采购。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    try { await action(ticket, controller.signal); } catch (e) { failure(e, ticket); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const guard = <T,>(ticket: number, signal: AbortSignal, action: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await settlementRequest('/me', signal) as SettlementSession, action, () => current(ticket));
  function initialDraft(context: SettlementContext): SettlementDraft {
    const shop = context.shopping.find(s => s.id === focus.current.shoppingId), link = context.links.find(l => l.status === 'active' && l.shoppingId === shop?.id);
    return { ...blankDraft(), shoppingId: shop?.id || '', paymentId: link?.paymentId || (context.transaction?.kind === 'payments' && context.payments.some(p => p.id === context.transaction?.id && p.eligible) ? context.transaction.id : ''),
      linkId: link?.id || '', operation: link ? 'update' : 'apply', amount: shop?.actual == null ? '' : centsToDecimal(shop.actual), done: shop?.done || false };
  }
  async function load(ticket: number, signal: AbortSignal, options: { review?: boolean; unscoped?: boolean; q?: string; page?: number } = {}) {
    const unknown = live.current.unknown, receipt = live.current.receipt;
    const nextPage = options.page ?? page, nextQuery = options.q ?? query;
    const requestQuery = settlementReadQuery(focus.current, live.current.draft,
      { q: nextQuery, page: nextPage, receiptLinkId: receipt?.link.id, unscoped: options.unscoped });
    install({ context: null, preview: null, acknowledged: false, review: null, completed: false });
    const context = readSettlementContext(await guard(ticket, signal, () => settlementRequest(settlementQuery(requestQuery), signal)), requestQuery);
    if (!current(ticket)) return;
    const draft = live.current.draft;
    install({ context, missing: !!options.unscoped, draft: draft.dirty || unknown || receipt || draft.shoppingId || draft.paymentId ? draft : initialDraft(context),
      review: options.review && unknown && unknown === live.current.unknown ? { intent: unknown, identity: props.identityKey, epoch: ticket } : null });
    setVisible(true); setPage(requestQuery.page || 0);
    if (options.unscoped) setQuery('');
    if (unknown) setNotice(options.unscoped ? '原目标暂时不可读。以下只显示当前可用资料，不是刚才请求的回执。' : '已读取当前资料；这不能证明刚才那次操作是否完成。');
    if (receipt) {
      // Parent refresh is part of readback; failing it keeps the receipt and locks
      // new mutations. Retrying this method never calls confirm again.
      try { await latest.current.props.onSaved({ shoppingId: receipt.link.shoppingId, linkId: receipt.link.id, operation: receipt.operation }); }
      catch (e) { if (current(ticket)) install({ context: null, completed: false }); throw e; }
      if (current(ticket) && receipt === live.current.receipt) { install({ completed: true, draft: { ...live.current.draft, dirty: false } }); setNotice('已收到保存确认，以下为重新读取的当前资料。'); }
    }
  }
  async function resume(ticket: number, signal: AbortSignal) {
    if (live.current.unknown) { await guard(ticket, signal, async () => undefined); if (current(ticket)) setVisible(true); }
    else await load(ticket, signal);
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || !windowFocused.current || !foreground.current || pageHidden.current || !online()
      || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void job(resume);
  }
  const lifecycle = useRef({ enter, conceal }); lifecycle.current = { enter, conceal };
  function retry() { if (!latest.current.household.online) void latest.current.household.refresh(); else if (active.current) void job(resume); else enter(); }
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); live.current = empty(); latest.current.props.onPendingChange?.(false); };
  }, []);
  useFocusEffect(useCallback(() => { focused.current = true; lifecycle.current.enter(); return () => { focused.current = false; lifecycle.current.conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const sync = () => { if (typeof document !== 'undefined' && document.hidden || !online()) lifecycle.current.conceal(); else lifecycle.current.enter(); };
    const blur = () => { windowFocused.current = false; lifecycle.current.conceal(); }, focusWindow = () => { windowFocused.current = true; sync(); };
    const hide = () => { pageHidden.current = true; lifecycle.current.conceal(); }, show = () => { pageHidden.current = false; sync(); };
    const beforeUnload = (e: BeforeUnloadEvent) => { if (pending()) { e.preventDefault(); e.returnValue = ''; } };
    const app = AppState.addEventListener('change', value => { foreground.current = value === 'active'; if (foreground.current) sync(); else lifecycle.current.conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', sync);
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focusWindow); window.addEventListener('offline', sync);
      window.addEventListener('online', sync); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', beforeUnload); }
    return () => { app.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', sync);
      if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focusWindow); window.removeEventListener('offline', sync);
        window.removeEventListener('online', sync); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', beforeUnload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  useEffect(() => {
    if (!model.preview) return;
    const intent = model.preview, timer = setTimeout(() => { if (live.current.preview === intent) { install({ preview: null, acknowledged: false }); setNotice('预览已过期，请重新核对并预览。'); } }, Math.max(0, intent.expiresAt - performance.now()));
    return () => clearTimeout(timer);
  }, [model.preview]);
  function change(patch: Partial<SettlementDraft>) {
    if (!current() || working.current || live.current.unknown || live.current.receipt) return;
    install({ draft: { ...live.current.draft, ...patch, dirty: true }, preview: null, acknowledged: false, review: null }); setNotice(''); setError('');
  }
  async function chooseLink(link: SettlementLink, operation: 'update' | 'revoke') {
    if (!current() || working.current || live.current.unknown || live.current.receipt) return;
    change({ operation, linkId: link.id, shoppingId: link.shoppingId, paymentId: link.paymentId, mode: 'detach_keep_current' });
    await job(async (ticket, signal) => {
      await load(ticket, signal);
      if (current(ticket) && live.current.context) {
        const shop = live.current.context.shopping.find(s => s.id === link.shoppingId);
        install({ draft: { ...live.current.draft, amount: shop?.actual == null ? centsToDecimal(link.amountCents) : centsToDecimal(shop.actual), done: shop?.done || false } });
      }
    });
  }
  async function makePreview() {
    if (!live.current.context || live.current.unknown || live.current.receipt) return;
    await job(async (ticket, signal) => {
      const context = live.current.context!, draft = live.current.draft;
      // Existing decimal helper checks the text; BigInt scales exact hundredths.
      const amount = draft.operation === 'revoke' ? 0 : Number(BigInt(decimalInput(draft.amount, false, 1_000_000_000n).replace('.', '')));
      const plan = settlementPlan(context, draft, amount);
      install({ preview: null, acknowledged: false });
      let intent: SettlementIntent;
      try { intent = readSettlementPreview(await guard(ticket, signal, csrf => settlementRequest(SETTLEMENT_PATH + '/preview', signal, { payload: plan, csrf })), plan, context); }
      catch (e) { if (current(ticket) && e instanceof SettlementError && e.status === 409) install({ context: null }); throw e; }
      if (current(ticket) && draft === live.current.draft) install({ preview: intent });
    });
  }
  async function confirm() {
    const intent = live.current.preview;
    if (!current() || working.current || !intent || !live.current.acknowledged || live.current.unknown || live.current.receipt) return;
    if (performance.now() >= intent.expiresAt) { install({ preview: null, acknowledged: false }); setError('预览已过期，请重新预览。'); return; }
    await job(async (ticket, signal) => {
      try {
        const receipt = await checkedSettlementWrite<SettlementReceipt>(action => guard(ticket, signal, action), async csrf => {
          install({ unknown: intent, preview: null, context: null, acknowledged: false, review: null });
          return readSettlementReceipt(await settlementRequest(SETTLEMENT_PATH + '/confirm', signal, { payload: { previewToken: intent.preview.previewToken }, csrf }), intent);
        });
        if (!current(ticket)) return;
        install({ unknown: null, receipt, context: null, completed: false, draft: { ...live.current.draft, dirty: false } });
        setNotice('已收到保存确认，正在读取当前资料。');
      } catch (e) {
        if (!current(ticket)) return;
        if (e instanceof SettlementRejected) { install({ unknown: null, context: null, preview: null }); setNotice('本次请求未获接受，输入仍保留；请重新读取后再预览。'); }
        else if (live.current.unknown) setNotice('请求可能已经执行，请只读核对当前资料。不会自动再次确认。');
        throw e;
      }
      await load(ticket, signal);
    });
  }
  function close() {
    if (!alive.current || working.current || latest.current.household.identityKey !== props.identityKey || live.current.unknown || live.current.receipt && !live.current.completed) return;
    if (live.current.draft.dirty || live.current.preview) { setDiscard(true); return; }
    latest.current.props.onPendingChange?.(false); latest.current.props.onClose();
  }
  function finishReview() {
    if (!current() || working.current || !canEndSettlementReview(live.current.review, live.current.unknown, props.identityKey, epoch.current)) return;
    install(empty()); latest.current.props.onPendingChange?.(false); latest.current.props.onClose();
  }
  function again() { if (!current() || working.current || !live.current.completed || !live.current.context) return; install({ receipt: null, completed: false, draft: initialDraft(live.current.context), preview: null, acknowledged: false }); setNotice(''); }
  const button = (label: string, action: () => void, disabled = false, mode: 'text' | 'outlined' | 'contained' = 'outlined') =>
    <Button accessibilityLabel={label} contentStyle={styles.touch} labelStyle={styles.buttonLabel} mode={mode} disabled={disabled} onPress={action}>{label.split('：')[0]}</Button>;
  const stack = { gap: density.sectionGap }, locked = busy || !visible || !!model.unknown || !!model.receipt;
  const context = visible ? model.context : null, draft = model.draft, preview = visible ? model.preview : null;
  const selected = context?.shopping.find(s => s.id === (model.receipt?.link.shoppingId || draft.shoppingId));
  const selectedLink = context?.links.find(l => l.id === draft.linkId);
  return <View testID="shopping-settlement-panel" style={{ gap: density.screenGap }}>
    <PageHeader title="核对采购实付" description="用本人付款核对采购，确认后才与家人共享。" action={button('返回', close, busy || !!model.unknown || !!model.receipt && !model.completed)} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对采购资料" />}
    {!visible ? <EmptyState title="核对资料已隐藏" description="回到前台并联网后，重新核对身份；输入不会自动提交。" action={button('重新读取核对资料', retry, busy || !online())} /> : <>
      {!!notice && <Text accessibilityLiveRegion="polite" style={styles.wrap}>{notice}</Text>}
      {model.unknown && <SectionCard title="先核对当前状态"><View testID="settlement-unknown" style={stack}>
        <Text>刚才为「{model.unknown.shoppingTitle}」保存的结果尚未确认。当前资料不是本次操作的回执。</Text>
        {button('读取当前核对资料', () => void job((t, s) => load(t, s, { review: true })), busy, 'contained')}
        {model.missing && <><Text>原记录可能已移除。可以读取本人当前可用资料，再决定是否结束本地核对。</Text>{button('读取当前可用资料', () => void job((t, s) => load(t, s, { review: true, unscoped: true })), busy)}</>}
        {canEndSettlementReview(model.review, model.unknown, props.identityKey, epoch.current) && <><Text>结束后返回上一页，不会再次提交，也不代表原请求成功或失败。</Text>{button('结束本次核对', finishReview, busy)}</>}
      </View></SectionCard>}
      {model.receipt && <SectionCard title="已收到保存确认"><View style={stack}><Text>确认结果：{model.receipt.operation === 'revoke' ? '关联已解除' : '采购实付已核对'}。历史确认不能代替当前资料。</Text>
        {!model.completed && button('重新读取当前资料', () => void job(load), busy, 'contained')}
        {model.completed && button('继续核对', again, busy)}
      </View></SectionCard>}
      {!context && !model.unknown && !model.receipt && button('读取当前核对资料', () => void job(load), busy, 'contained')}
      {context && <View testID="settlement-current" style={stack}>
        {(model.unknown || model.receipt) && <SectionCard title="当前资料"><View style={stack}>
          {selected ? <><Text>{selected.title}</Text><Text>整项实付 {money(selected.actual)} · {done(selected.done)}</Text></> : <Text>当前资料中未见所选采购；不据此推断原请求的执行结果。</Text>}
          {context.links.map(link => <Text key={link.id}>{link.status === 'revoked' ? '关联已解除' : link.state === 'needs_review' ? '关联需要核对' : '关联当前有效'}{link.reviewReasons.map(r => ' · ' + reasons[r]).join('')}</Text>)}
        </View></SectionCard>}
        {!model.unknown && !model.receipt && <>
          {context.warnings.map((text, index) => <Text key={index} style={styles.wrap}>{text}</Text>)}
          {context.transaction?.kind === 'orders' && <Text>这里只列这笔订单已经核对关联的付款。尚无付款时，请先回账本关联订单与付款。</Text>}
          <View style={styles.actions}><TextInput mode="outlined" label="查找付款或采购" accessibilityLabel="查找付款或采购" value={query} maxLength={80} disabled={locked || !!preview} onChangeText={setQuery} style={styles.search} />
            {button('查找', () => void job((t, s) => load(t, s, { q: query.trim(), page: 0 })), locked || !!preview)}</View>
          {!!context.links.length && <List.Accordion title="本人的关联记录"><View style={stack}>{context.links.map(link => <SectionCard key={link.id} title={context.shopping.find(s => s.id === link.shoppingId)?.title || '采购关联'}><View style={stack}>
            <Text>{money(link.amountCents)} · {link.status === 'revoked' ? '已解除' : link.state === 'needs_review' ? '需要核对' : '当前有效'}</Text>
            {link.reviewReasons.map(r => <Text key={r}>{reasons[r]}</Text>)}
            {link.status === 'active' && <View style={styles.actions}>{button('更新关联：' + link.id, () => void chooseLink(link, 'update'), locked || !!preview)}{button('解除关联：' + link.id, () => void chooseLink(link, 'revoke'), locked || !!preview)}</View>}
          </View></SectionCard>)}</View></List.Accordion>}
          {!preview && <SectionCard title={draft.operation === 'revoke' ? '解除本人关联' : draft.operation === 'update' ? '更新原关联' : '选择付款与采购'}><View style={stack}>
            {draft.operation === 'apply' ? <>
              <Text variant="titleSmall">本人付款</Text><View accessibilityRole="radiogroup" accessibilityLabel="本人付款" style={stack}>
                {context.payments.map(pay => <View key={pay.id}><SelectionRow kind="radio" label={pay.title} accessibilityLabel={'选择付款：' + pay.title} checked={draft.paymentId === pay.id} disabled={locked || !pay.eligible} onPress={() => change({ paymentId: pay.id })} />
                  <Text style={styles.indent}>{pay.date} · {formatFinanceAmount(pay.amountCents, pay.currency)}{pay.eligible ? ' · 当前可分配 ' + money(pay.availableCents) : ' · ' + reasons[pay.reasonCode!]}</Text>
                  {pay.refundedCents > 0 && <Text style={styles.indent}>已关联退款 {formatFinanceAmount(pay.refundedCents, pay.currency)}</Text>}</View>)}
                {!context.payments.length && <Text>没有可用付款。可调整搜索或返回本人账本，先导入并核对付款。</Text>}
              </View><Text variant="titleSmall">家庭采购</Text><View accessibilityRole="radiogroup" accessibilityLabel="家庭采购" style={stack}>
                {context.shopping.map(shop => { const linked = context.links.some(l => l.status === 'active' && l.shoppingId === shop.id); return <View key={shop.id}>
                  <SelectionRow kind="radio" label={shop.title} accessibilityLabel={'选择采购：' + shop.title} checked={draft.shoppingId === shop.id} disabled={locked || linked} onPress={() => change({ shoppingId: shop.id, amount: shop.actual === null ? '' : centsToDecimal(shop.actual), done: shop.done })} />
                  <Text style={styles.indent}>当前 {money(shop.actual)} · {done(shop.done)}{linked ? ' · 请从上方更新本人原关联' : ''}</Text></View>; })}
                {!context.shopping.length && <Text>没有符合条件的采购，可返回采购清单先记录物品。</Text>}
              </View>
            </> : <><Text>{selected?.title || '原采购'} · {context.payments.find(p => p.id === draft.paymentId)?.title || '原付款'}</Text>
              {!!selectedLink && selectedLink.reviewReasons.map(r => <Text key={r}>{reasons[r]}</Text>)}
              <Text>更新保留原付款与采购；更换付款需先明确解除原关联。</Text></>}
            {draft.operation === 'revoke' ? <View accessibilityRole="radiogroup" accessibilityLabel="解除方式">
              <SelectionRow kind="radio" label="保留采购当前值" checked={draft.mode === 'detach_keep_current'} disabled={locked} onPress={() => change({ mode: 'detach_keep_current' })} />
              <SelectionRow kind="radio" label="安全恢复核对前的采购值" checked={draft.mode === 'restore_if_unchanged'} disabled={locked} onPress={() => change({ mode: 'restore_if_unchanged' })} />
              <Text>恢复仅在采购仍保持上次核对后的版本和值时可用；后来修改过则拒绝。不会删除付款或采购。</Text>
            </View> : <>
              <TextInput mode="outlined" label="整项实付（元）" accessibilityLabel="整项实付（元）" keyboardType="decimal-pad" value={draft.amount} maxLength={16} disabled={locked} onChangeText={amount => change({ amount })} />
              <SelectionRow kind="checkbox" label="已买到" checked={draft.done} disabled={locked} onPress={() => change({ done: !draft.done })} />
              <Text>实付替换整项原值；付款不表示物品已经买到。只共享金额和已买到状态，账本、预算、公共余额及旅行已付款保持。</Text>
            </>}
            {button(draft.operation === 'revoke' ? '预览解除影响' : '预览共享变化', () => void makePreview(), locked, 'contained')}
            {draft.operation !== 'apply' && button('选择其他采购', () => change({ ...blankDraft() }), locked)}
          </View></SectionCard>}
          {preview && <SectionCard title="确认共享变化"><View testID="settlement-preview" style={stack}>
            <Text variant="titleSmall">{preview.shoppingTitle}</Text><Text>来源付款：{preview.paymentTitle}</Text>
            <Text>当前：{preview.preview.before ? money(preview.preview.before.actual) + ' · ' + done(preview.preview.before.done) : '原采购不可用'}</Text>
            <Text>确认后：{preview.preview.after ? money(preview.preview.after.actual) + ' · ' + done(preview.preview.after.done) : '不改变采购'}</Text>
            {preview.preview.payment && <Text>本次可分配上限 {formatFinanceAmount(preview.preview.payment.availableCents, preview.preview.payment.currency)}</Text>}
            {preview.preview.warnings.map((text, index) => <Text key={index}>{text}</Text>)}
            <SelectionRow kind="checkbox" label="我确认共享整项实付和已买到状态" checked={model.acknowledged} disabled={busy} onPress={() => install({ acknowledged: !live.current.acknowledged })} />
            <View style={styles.actions}>{button('返回修改', () => install({ preview: null, acknowledged: false }), busy)}{button('确认保存', () => void confirm(), busy || !model.acknowledged, 'contained')}</View>
          </View></SectionCard>}
          {!preview && <View style={styles.actions}>{button('上一页', () => void job((t, s) => load(t, s, { page: Math.max(0, page - 1) })), locked || page === 0)}
            <Text>第 {page + 1} 页 · 每类最多 40 项，定位记录另保留</Text>{button('下一页', () => void job((t, s) => load(t, s, { page: page + 1 })), locked || !Object.entries(context.pageInfo).some(([key, value]) => key.endsWith('More') && value === true))}</View>}
        </>}
      </View>}
    </>}
    <Portal><Dialog visible={discard} onDismiss={() => setDiscard(false)} style={styles.dialog}><Dialog.Title>放弃本次输入？</Dialog.Title>
      <Dialog.Content><Text>本次未保存的输入和预览会清除，不会提交或更改采购。</Text></Dialog.Content><Dialog.Actions style={styles.actions}>
        {button('继续核对', () => setDiscard(false))}{button('放弃输入并返回', () => { if (working.current || live.current.unknown) return; install(empty()); setDiscard(false); latest.current.props.onClose(); })}
      </Dialog.Actions></Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, buttonLabel: { flexShrink: 1 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 },
  search: { flexGrow: 1, flexBasis: 210, minWidth: 0 }, indent: { paddingHorizontal: 14 },
  wrap: { flexShrink: 1, ...(Platform.OS === 'web' ? { overflowWrap: 'anywhere' as const } : {}) }, dialog: { width: '92%', maxWidth: 520, alignSelf: 'center' } });
