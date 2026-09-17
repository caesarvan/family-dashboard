import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { formatBaselineTime } from '../lib/financeBaseline';
import { AccountDiscarded, AccountError, AccountFence, AccountRecoveryMemory, AccountRejected, accountActor, accountDay, accountEndReview, canEndAccountReview, accountHistoryPath, accountListPath, accountOperationPath, accountRequest, checkedAccountWrite, createAccountIntent, failedAccountIntent, formatAccountMoney, readAccountHistory, readAccountList, readAccountOperation, readAccountReceipt, updateAccountIntent, valuationAccountIntent,
  type AccountDraft, type AccountEndReview, type AccountHistory, type AccountIntent, type AccountList, type AccountReceipt, type AccountSession, type AccountStatus, type FinanceAccount } from '../lib/financeAccounts';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';

type Props = { onBack: () => void; onPendingChange?: (pending: boolean) => void };
type Mode = 'list' | 'detail' | 'create' | 'edit' | 'valuation';
type Model = { view: Mode; list: AccountList | null; history: AccountHistory | null; selected: string | null; base: FinanceAccount | null; latest: FinanceAccount | null;
  draft: AccountDraft | null; asOf: string; dateInput: string; filter: AccountStatus; query: string; page: number; historyPage: number; visible: boolean;
  requestId: string | null; intent: AccountIntent | null; receipt: AccountReceipt | null; error: string; message: string; conflict: boolean; leave: boolean; discard: boolean; archive: boolean; operationInput: string; endReview: AccountEndReview | null; ending: boolean; endedId: string };
const recovery = new AccountRecoveryMemory();
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const today = () => { const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()); return accountDay(date); };
const initial = (requestId: string | null): Model => { const asOf = today(); return { view: 'list', list: null, history: null, selected: null, base: null, latest: null, draft: null, asOf, dateInput: asOf, filter: 'active', query: '', page: 0, historyPage: 1, visible: false, requestId, intent: null, receipt: null, error: '', message: '', conflict: false, leave: false, discard: false, archive: false, operationInput: '', endReview: null, ending: false, endedId: '' }; };
const blank = (asOf: string, account?: FinanceAccount): AccountDraft => ({ name: account?.name || '', institution: account?.institution || '', kind: account?.kind || 'asset', currency: account?.currency || 'CNY', note: account?.note || '', asOf, amount: '', unknown: true });

export default function FinanceAccountsPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户查看本人资产账户" action={<Button contentStyle={styles.touch} onPress={props.onBack}>返回财务</Button>} />;
  return <Workspace key={household.identityKey} {...props} identity={household.identityKey} actor={accountActor({ user: household.user })} owner={household.user.id} />;
}
function Workspace(props: Props & { identity: string; actor: string; owner: string }) {
  const household = useHousehold(), theme = useTheme(), density = useDisplayDensity();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState(() => initial(recovery.get(props.actor))), [busy, setBusy] = useState(false);
  const live = useRef(model), alive = useRef(false), active = useRef(false), focused = useRef(false), working = useRef(false), epoch = useRef(0), denied = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), pageHidden = useRef(false), flight = useRef<AbortController | null>(null), fence = useRef(new AccountFence(props.identity));
  const sameIdentity = () => latest.current.household.identityKey === props.identity;
  const current = (ticket = epoch.current) => alive.current && sameIdentity() && active.current && focused.current && foreground.current && !pageHidden.current && !denied.current && ticket === epoch.current && latest.current.household.online && connected() && (typeof document === 'undefined' || !document.hidden);
  const pending = () => working.current || !!live.current.draft || !!live.current.requestId;
  function report() { if (alive.current && sameIdentity()) latest.current.props.onPendingChange?.(pending()); }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); report(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); report(); }
  function remember(requestId: string | null) { if (requestId) recovery.set(props.actor, requestId); else if (live.current.requestId) recovery.clear(props.actor, live.current.requestId); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null; working.current = false; setBusy(false);
    // Same identity: retain unsaved input privately in memory; do not render until fresh identity + GET.
    live.current = clear ? initial(live.current.requestId) : { ...live.current, visible: false, list: null, history: null, latest: null, receipt: null, error: '', message: '', leave: false, discard: false, archive: false, endReview: null, ending: false };
    setModel(live.current); report();
  }
  function failed(error: unknown) {
    if (error instanceof AccountDiscarded && error.message !== 'identity') return;
    if (error instanceof AccountDiscarded || error instanceof AccountError && [401, 403].includes(error.status)) { denied.current = true; conceal(true); install({ error: '身份或权限已变化，私密内容已清除。请重新登录核对。' }); void latest.current.household.refresh(); return; }
    install({ error: error instanceof AccountError ? error.message : '暂时无法读取账户，请重试。' });
  }
  const guard = <T,>(controller: AbortController, ticket: number, job: (csrf: string) => Promise<T>) => fence.current.run(async () => await accountRequest('/me', controller.signal) as AccountSession, job, () => current(ticket));
  async function load(controller: AbortController, ticket: number, selected = live.current.selected, page = live.current.historyPage) {
    const { asOf, filter } = live.current;
    const result = await guard(controller, ticket, async () => { const list = readAccountList(await accountRequest(accountListPath(asOf, filter), controller.signal), props.owner, asOf, filter); const history = selected ? readAccountHistory(await accountRequest(accountHistoryPath(selected, page), controller.signal), props.owner, selected, page) : null; return { list, history }; });
    if (!current(ticket)) return;
    const changed = !!live.current.draft && !!live.current.base && !!result.history && live.current.base.revision !== result.history.account.revision;
    install({ ...result, visible: true, historyPage: page, latest: result.history?.account || null, conflict: live.current.conflict || changed });
  }
  async function run(job: (controller: AbortController, ticket: number) => Promise<void>) {
    if (!current() || working.current) return; const controller = new AbortController(), ticket = epoch.current; flight.current = controller; setWorking(true); install({ error: '', leave: false });
    try { await job(controller, ticket); } catch (error) { if (current(ticket)) failed(error); } finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  function enter() { if (active.current || denied.current || !alive.current || !focused.current || !foreground.current || pageHidden.current || !sameIdentity() || !connected() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return; active.current = true; void run((controller, ticket) => load(controller, ticket)); }
  function refresh() { if (!active.current) enter(); else void run(async (controller, ticket) => { install({ list: null, history: null, latest: null }); await load(controller, ticket); }); }
  useEffect(() => { alive.current = true; report(); return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); live.current = initial(null); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identity]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); }, offline = () => conceal(), online = () => enter(), hide = () => { pageHidden.current = true; conceal(); }, show = (event: PageTransitionEvent) => { if (event.persisted || pageHidden.current) { pageHidden.current = false; conceal(); enter(); } };
    const unload = (event: BeforeUnloadEvent) => { if (pending()) { event.preventDefault(); event.returnValue = ''; } };
    const subscription = AppState.addEventListener('change', value => { foreground.current = value === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', online); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); window.addEventListener('beforeunload', unload); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility); if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', online); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); window.removeEventListener('beforeunload', unload); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function back() { if (working.current) return; if (pending()) install({ leave: true }); else exit(); }
  function exit() { if (working.current) return; conceal(true); latest.current.props.onPendingChange?.(false); latest.current.props.onBack(); }
  function open(accountId: string) { if (pending()) return; install({ view: 'detail', selected: accountId, history: null, latest: null, historyPage: 1, receipt: null }); void run((controller, ticket) => load(controller, ticket, accountId, 1)); }
  function start(view: 'create' | 'edit' | 'valuation') { if (!current() || pending()) return; const account = live.current.history?.account; if (view !== 'create' && !account) return; install({ view, draft: blank(live.current.asOf, account), base: account || null, conflict: false, error: '', message: '', receipt: null }); }
  function edit(patch: Partial<AccountDraft>) { if (!current() || working.current || live.current.requestId || !live.current.draft) return; install({ draft: { ...live.current.draft, ...patch }, error: '' }); }
  function cancelDraft() { if (working.current || live.current.requestId) return; install({ draft: null, base: null, conflict: false, discard: false, view: live.current.selected ? 'detail' : 'list' }); }
  async function accepted(receipt: AccountReceipt, controller: AbortController, ticket: number) {
    if (!current(ticket)) return; remember(null);
    // Historical result confirms the operation, never replaces current account/history.
    install({ requestId: null, intent: null, draft: null, base: null, conflict: false, endReview: null, ending: false, latest: null, list: null, history: null, receipt, selected: receipt.accountId, historyPage: 1, view: 'detail', message: '对应操作已保存。正在重新读取当前账户。' });
    await load(controller, ticket, receipt.accountId, 1);
  }
  async function send(intent: AccountIntent, controller: AbortController, ticket: number) {
    let attempted = false;
    try {
      const receipt = await checkedAccountWrite<AccountReceipt>(job => guard(controller, ticket, job), async csrf => {
        attempted = true; remember(intent.requestId); install({ requestId: intent.requestId, intent: { ...intent, uncertain: true }, archive: false, endReview: null, ending: false, history: null, latest: null, list: null });
        return readAccountReceipt(await accountRequest(intent.path, controller.signal, { method: intent.method, payload: intent.body, csrf }), props.owner, intent.requestId, intent);
      });
      await accepted(receipt, controller, ticket);
    } catch (error) {
      if (!current(ticket)) throw error;
      if (attempted && live.current.requestId === intent.requestId) {
        const next = failedAccountIntent(intent, error); if (!next) { remember(null); install({ requestId: null, intent: null }); if (error instanceof AccountRejected && error.status === 409 && ['revision_conflict', 'account_archived'].includes(error.code)) { install({ conflict: true, history: null, latest: null, message: '账户已变化。请读取最新内容，明确选择后再保存。' }); } }
        else install({ intent: next, message: '保存结果尚未确认。请核对原操作编号，或明确按原请求重试。' });
      }
      throw error;
    }
  }
  function save() {
    if (!live.current.draft || live.current.requestId || live.current.conflict) return;
    void run(async (controller, ticket) => { const draft = live.current.draft!, base = live.current.base; const intent = live.current.view === 'create' ? createAccountIntent(draft) : live.current.view === 'edit' && base ? updateAccountIntent(base, { name: draft.name, institution: draft.institution, note: draft.note }) : base ? valuationAccountIntent(base, draft.asOf, draft.amount, draft.unknown) : null; if (intent) await send(intent, controller, ticket); });
  }
  function archive() { const account = live.current.history?.account; if (!account || live.current.requestId || live.current.draft) return; void run((controller, ticket) => send(updateAccountIntent(account, { archived: !account.archived }), controller, ticket)); }
  function recover() { const requestId = live.current.requestId; if (!requestId) return; void run(async (controller, ticket) => {
    install({ endReview: null, ending: false });
    const { receipt, review } = await guard(controller, ticket, async () => {
      const list = readAccountList(await accountRequest(accountListPath(live.current.asOf, 'all'), controller.signal), props.owner, live.current.asOf, 'all');
      const operation = await accountRequest(accountOperationPath(requestId), controller.signal), receipt = readAccountOperation(operation, props.owner, requestId);
      return { receipt, review: accountEndReview(list, operation, props.owner, requestId, props.identity) };
    });
    if (receipt) await accepted(receipt, controller, ticket);
    else if (review) install({ endReview: review, list: review.list, filter: 'all', page: 0, query: '', message: '暂未查到结果，原请求仍可能完成。请先核对账户列表；重新新建可能产生重复账户。' });
  }); }
  function endRecovery() {
    if (!current() || working.current || !canEndAccountReview(live.current.endReview, live.current.requestId, props.identity, live.current.ending)) return;
    const requestId = live.current.requestId!; remember(null);
    install({ requestId: null, intent: null, draft: null, base: null, endReview: null, ending: false, conflict: false, view: 'list', selected: null, history: null, latest: null, endedId: requestId, operationInput: requestId, message: '已按你的决定结束本次核对，未再次提交。原操作编号仍可复制或查询；原请求仍可能完成。' });
  }
  function retry() { const intent = live.current.intent; if (!intent || !live.current.requestId) return; void run((controller, ticket) => send({ ...intent, uncertain: true }, controller, ticket)); }
  function useOperation() { if (pending() || !current()) return; try { const requestId = live.current.operationInput.trim(); accountOperationPath(requestId); remember(requestId); install({ requestId, operationInput: '', receipt: null, message: '请读取此编号对应的本人历史回执。' }); } catch { install({ error: '操作编号应为 32 位小写十六进制字符。' }); } }
  function resolveConflict(keep: boolean) { const account = live.current.latest; if (!current() || working.current || live.current.requestId || !account || !live.current.draft) return; install({ base: account, draft: keep ? live.current.draft : blank(live.current.asOf, account), conflict: false, message: keep ? '草稿已保留。请核对最新账户后，再明确保存。' : '已采用最新账户文字；估值需要重新填写。', error: '' }); }
  function applyFilter(filter = live.current.filter) { if (pending()) return; try { const asOf = accountDay(live.current.dateInput); install({ filter, asOf, list: null, page: 0 }); void run((controller, ticket) => load(controller, ticket)); } catch (error) { failed(error); } }
  const show = model.visible && current(), disabled = busy || !show, locked = disabled || !!model.requestId, account = model.history?.account;
  const filtered = (model.list?.accounts || []).filter(row => [row.name, row.institution, row.currency, row.note].join(' ').toLocaleLowerCase().includes(model.query.toLocaleLowerCase()));
  const pages = Math.max(1, Math.ceil(filtered.length / 10)), page = Math.min(model.page, pages - 1), rows = filtered.slice(page * 10, page * 10 + 10), stack = { gap: density.sectionGap };
  return <View testID="finance-accounts-panel" style={{ gap: density.screenGap }}>
    <PageHeader title="我的资产账户" description="手动记录本人的资产与负债及按日估值。仅本人可见，不连接金融机构，也不与来源报告、持仓或荷包合并。"
      action={<Button accessibilityLabel="返回财务" contentStyle={styles.touch} disabled={busy} onPress={back}>返回财务</Button>} />
    {!!model.error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{model.error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对本人资产账户" />}
    {!show ? <EmptyState title={connected() && household.online ? '正在核对本人身份和账户' : '离线时隐藏私密账户'} description="同一身份的未保存草稿只在内存中保留，恢复连接后先重新核对身份与账户。"
      action={<Button contentStyle={styles.touch} disabled={busy || !connected() || !household.online || denied.current} onPress={refresh}>重新读取账户</Button>} /> : <>
      {!!model.message && <Text accessibilityLiveRegion="polite">{model.message}</Text>}
      {model.requestId && <SectionCard title="核对上次保存"><View testID="finance-accounts-unknown" style={stack}><Text>结果尚未确认。没有找到回执不代表未保存。</Text><Text selectable style={styles.wrap}>操作编号：{model.requestId}</Text>
        <Button mode="contained" contentStyle={styles.touch} disabled={disabled} onPress={recover}>核对账户操作结果</Button>
        {model.intent && <Button mode="outlined" contentStyle={styles.touch} disabled={disabled} onPress={retry}>按原账户请求重试</Button>}
        {model.endReview && <Button contentStyle={styles.touch} disabled={disabled} onPress={() => install({ ending: true })}>结束本次核对</Button>}<Button contentStyle={styles.touch} disabled={disabled} onPress={back}>保留操作编号并返回</Button></View></SectionCard>}
      {model.receipt && <SectionCard title="保存回执"><View testID="finance-accounts-receipt" style={stack}><Text>{model.receipt.replayed ? '已找到历史操作回执。' : '账户操作已保存。'}回执不是当前账户资料。</Text><Text>{formatBaselineTime(model.receipt.completedAt)}</Text><Text selectable style={styles.wrap}>操作编号：{model.receipt.requestId}</Text></View></SectionCard>}
      {!model.list && <EmptyState title="当前账户尚未重新读取" description="不会用旧资料或历史回执恢复操作按钮。" action={<Button contentStyle={styles.touch} disabled={disabled} onPress={refresh}>读取当前账户</Button>} />}
      {(model.view === 'list' || !!model.endReview) && <>
        <SectionCard title="查看账户"><View style={stack}><TextInput mode="outlined" label="查看日期" accessibilityLabel="查看日期" value={model.dateInput} onChangeText={dateInput => install({ dateInput })} disabled={locked} placeholder="YYYY-MM-DD" />
          <Text>显示所选日期当日或之前最近一次估值。归档筛选使用账户当前状态；可选“全部账户”查看含归档记录。</Text><Button contentStyle={styles.touch} disabled={locked} onPress={() => applyFilter()}>应用查看日期</Button>
          <View accessibilityRole="radiogroup">{([['active', '使用中的账户'], ['archived', '已归档账户'], ['all', '全部账户']] as const).map(([filter, label]) => <SelectionRow key={filter} kind="radio" label={label} checked={model.filter === filter} disabled={locked} onPress={() => applyFilter(filter)} />)}</View>
          <Button mode="contained" contentStyle={styles.touch} disabled={locked || !model.list} onPress={() => start('create')}>新增资产或负债账户</Button>
        </View></SectionCard>
        {model.list && <SectionCard title="手动账户已知部分"><View style={stack}>
          <Text>所选账户截至 {model.asOf} 的估值，不代表该日完整历史净资产。不同币种不换算。</Text>
          {model.list.totals.map(total => <View key={total.currency} style={[stack, { paddingVertical: density.rowPadding }]}><Text variant="titleMedium">{total.currency}</Text>
            {total.knownCount ? <><Text>已知资产 {formatAccountMoney(total.knownAssetCents, total.currency)}</Text><Text>已知负债 {formatAccountMoney(total.knownLiabilityCents, total.currency)}</Text><Text>已知部分净额 {formatAccountMoney(total.knownNetCents, total.currency)}</Text></> : <Text>暂无已知金额，不能确定净额</Text>}
            <Text>已知 {total.knownCount} · 金额未知 {total.unknownCount} · 尚无记录 {total.missingCount} · 早于查看日期 {total.olderCount}</Text><Divider /></View>)}
          {!model.list.totals.length && <Text>当前筛选没有账户。</Text>}
        </View></SectionCard>}
        {model.list && <SectionCard title="账户列表"><View style={stack}><TextInput mode="outlined" label="搜索全部已载入账户" accessibilityLabel="搜索全部已载入账户" value={model.query} disabled={disabled} onChangeText={query => install({ query, page: 0 })} />
          {rows.map(row => <View key={row.id} testID={'finance-account-' + row.id} style={[stack, { paddingVertical: density.rowPadding }]}><Text variant="titleMedium" style={styles.wrap}>{row.name}</Text><Text>{row.kind === 'asset' ? '资产' : '负债'} · {row.currency}{row.archived ? ' · 已归档' : ''}</Text><Text style={styles.wrap}>{row.institution || '未填写机构'}</Text>
            <Text>{row.valuation ? formatAccountMoney(row.valuation.amountCents, row.currency) : '截至查看日期尚无估值记录'}</Text>{row.valuation && <Text>估值日期 {row.valuation.asOf}{row.valuation.asOf < model.asOf ? ' · 早于查看日期' : ''}</Text>}
            <Button contentStyle={styles.touch} accessibilityLabel={'查看账户 ' + row.name} disabled={locked} onPress={() => open(row.id)}>查看账户</Button><Divider /></View>)}
          <Pager page={page + 1} pages={pages} total={filtered.length} disabled={disabled} onPage={value => install({ page: value - 1 })} />
        </View></SectionCard>}
        {!model.requestId && <SectionCard title="核对已有操作编号"><View style={stack}><Text>重新登录后，可用原编号查询同一家庭中本人的保存回执。</Text>{!!model.endedId && <Text selectable style={styles.wrap}>已结束核对的原编号：{model.endedId}</Text>}<TextInput mode="outlined" label="账户操作编号" accessibilityLabel="账户操作编号" autoCapitalize="none" maxLength={32} value={model.operationInput} disabled={locked} onChangeText={operationInput => install({ operationInput })} /><Button contentStyle={styles.touch} disabled={locked || !model.operationInput.trim()} onPress={useOperation}>使用账户操作编号</Button></View></SectionCard>}
      </>}
      {model.view !== 'list' && !model.draft && !model.requestId && <Button contentStyle={styles.touch} disabled={disabled} onPress={() => install({ view: 'list', selected: null, history: null, latest: null, receipt: null })}>返回账户列表</Button>}
      {model.view === 'detail' && account && <SectionCard title="账户详情"><View testID="finance-account-detail" style={stack}><Text variant="titleLarge" style={styles.wrap}>{account.name}</Text>
        <Text>{account.kind === 'asset' ? '资产' : '负债'} · {account.currency} · {account.archived ? '已归档' : '使用中'}</Text><Text style={styles.wrap}>{account.institution || '未填写机构'}</Text><Text style={styles.wrap}>{account.note || '暂无备注'}</Text>
        <Text>仅本人可见。账户类别和币种创建后保持固定。</Text><View style={styles.actions}><Button mode="contained" contentStyle={styles.touch} disabled={locked || account.archived} onPress={() => start('valuation')}>记录估值</Button><Button contentStyle={styles.touch} disabled={locked} onPress={() => start('edit')}>修改账户信息</Button><Button contentStyle={styles.touch} disabled={locked} onPress={() => install({ archive: true })}>{account.archived ? '恢复账户' : '归档账户'}</Button></View>
        <Divider /><Text variant="titleMedium">估值历史</Text><Text>同一天再次保存会更新当天记录；其他日期保留。不代表实时余额。</Text>
        {model.history!.valuations.map(value => <View key={value.asOf} style={{ gap: 6, paddingVertical: density.rowPadding }}><Text>{value.asOf}</Text><Text>{formatAccountMoney(value.amountCents, account.currency)}</Text><Text>手动记录 · {formatBaselineTime(value.updatedAt)}</Text><Divider /></View>)}
        <Pager page={model.history!.page} pages={Math.max(1, Math.ceil(model.history!.total / 50))} total={model.history!.total} disabled={locked} onPage={value => { install({ history: null, latest: null }); void run((controller, ticket) => load(controller, ticket, account.id, value)); }} />
      </View></SectionCard>}
      {model.selected && !model.history && model.view !== 'list' && model.list && <EmptyState title="请读取当前账户详情" action={<Button contentStyle={styles.touch} disabled={disabled} onPress={refresh}>读取当前账户</Button>} />}
      {model.draft && !model.endReview && <SectionCard title={model.view === 'create' ? '新增账户' : model.view === 'edit' ? '修改账户信息' : '记录按日估值'}><View testID="finance-account-editor" style={stack}>
        {model.conflict && <View testID="finance-account-conflict" style={stack}><Text>当前账户与开始编辑时不同。草稿已保留，请先核对最新内容。</Text>
          {model.latest && <><Text style={styles.wrap}>最新：{model.latest.name} · {model.latest.institution || '未填写机构'} · {model.latest.archived ? '已归档' : '使用中'}</Text><Text style={styles.wrap}>{model.latest.note || '暂无备注'}</Text><Text>最近更新：{formatBaselineTime(model.latest.updatedAt)}</Text></>}
          <Button contentStyle={styles.touch} disabled={locked} onPress={refresh}>读取最新账户核对</Button>
          <Button contentStyle={styles.touch} disabled={locked || !model.latest} onPress={() => resolveConflict(false)}>采用最新账户信息</Button><Button contentStyle={styles.touch} disabled={locked || !model.latest} onPress={() => resolveConflict(true)}>保留我的账户草稿</Button>
        </View>}
        {model.view !== 'valuation' && <><TextInput mode="outlined" label="账户名称" accessibilityLabel="账户名称" value={model.draft.name} disabled={locked} onChangeText={name => edit({ name })} /><TextInput mode="outlined" label="机构（可不填）" accessibilityLabel="机构（可不填）" value={model.draft.institution} disabled={locked} onChangeText={institution => edit({ institution })} />
          <Text>账户备注</Text><TextInput mode="outlined" accessibilityLabel="账户备注" multiline contentStyle={{ minHeight: 104, paddingVertical: 12 }} value={model.draft.note} disabled={locked} onChangeText={note => edit({ note })} /></>}
        {model.view === 'create' && <><View accessibilityRole="radiogroup"><SelectionRow kind="radio" label="资产账户" checked={model.draft.kind === 'asset'} disabled={locked} onPress={() => edit({ kind: 'asset' })} /><SelectionRow kind="radio" label="负债账户" checked={model.draft.kind === 'liability'} disabled={locked} onPress={() => edit({ kind: 'liability' })} /></View>
          <TextInput mode="outlined" label="原币种（三位大写字母）" accessibilityLabel="原币种（三位大写字母）" autoCapitalize="characters" maxLength={3} value={model.draft.currency} disabled={locked} onChangeText={currency => edit({ currency })} /><Text>例如 CNY、USD。类别与币种保存后不可修改；页面不会换汇。</Text></>}
        {model.view !== 'edit' && <><TextInput mode="outlined" label="估值日期" accessibilityLabel="估值日期" value={model.draft.asOf} disabled={locked} placeholder="YYYY-MM-DD" onChangeText={asOf => edit({ asOf })} /><View accessibilityRole="radiogroup"><SelectionRow kind="radio" label="金额未知" checked={model.draft.unknown} disabled={locked} onPress={() => edit({ unknown: true })} /><SelectionRow kind="radio" label="填写已知金额" checked={!model.draft.unknown} disabled={locked} onPress={() => edit({ unknown: false })} /></View>
          {!model.draft.unknown && <TextInput mode="outlined" label={'估值金额（' + model.draft.currency + '）'} accessibilityLabel="估值金额" keyboardType="decimal-pad" value={model.draft.amount} disabled={locked} placeholder="0.00" onChangeText={amount => edit({ amount })} />}
          <Text>零表示明确为零；未知表示已记录日期但尚未确定金额。负债也填写非负金额。</Text>{model.view === 'valuation' && <Text>保存会替换该日已有估值，其他日期保留。</Text>}{model.view === 'valuation' && model.base?.archived && <Text>此账户已归档。请放弃当前估值草稿，先恢复账户。</Text>}</>}
        <View style={styles.actions}><Button mode="contained" contentStyle={styles.touch} disabled={locked || model.conflict || model.view === 'valuation' && !!model.base?.archived} onPress={save}>保存账户记录</Button><Button contentStyle={styles.touch} disabled={locked} onPress={() => install({ discard: true })}>放弃账户草稿</Button></View>
      </View></SectionCard>}
    </>}
    <Portal><Dialog visible={show && model.ending && !busy} onDismiss={() => install({ ending: false })}><Dialog.Title>结束本次核对？</Dialog.Title><Dialog.Content><Text>暂未查到结果，原请求仍可能完成。请先核对账户列表；重新新建可能产生重复账户。</Text><Text selectable style={styles.wrap}>原操作编号：{model.requestId}</Text></Dialog.Content><Dialog.Actions><Button contentStyle={styles.touch} onPress={() => install({ ending: false })}>继续核对</Button><Button contentStyle={styles.touch} onPress={endRecovery}>确认结束账户核对</Button></Dialog.Actions></Dialog><Dialog visible={show && model.archive && !busy && !!account} onDismiss={() => install({ archive: false })}><Dialog.Title>{account?.archived ? '恢复这个账户？' : '归档这个账户？'}</Dialog.Title><Dialog.Content><Text>归档不会删除估值历史。恢复后可以继续记录估值；当前筛选的汇总会随账户范围变化。</Text></Dialog.Content><Dialog.Actions><Button contentStyle={styles.touch} onPress={() => install({ archive: false })}>取消</Button><Button contentStyle={styles.touch} onPress={archive}>{account?.archived ? '确认恢复账户' : '确认归档账户'}</Button></Dialog.Actions></Dialog>
      <Dialog visible={show && model.discard && !busy} onDismiss={() => install({ discard: false })}><Dialog.Title>放弃未保存的账户草稿？</Dialog.Title><Dialog.Content><Text>只清除当前页面草稿，已保存的账户不变。</Text></Dialog.Content><Dialog.Actions><Button contentStyle={styles.touch} onPress={() => install({ discard: false })}>继续编辑</Button><Button contentStyle={styles.touch} onPress={cancelDraft}>确认放弃账户草稿</Button></Dialog.Actions></Dialog>
      <Dialog visible={model.leave && !busy} onDismiss={() => install({ leave: false })}><Dialog.Title>{model.requestId ? '保留核对编号并返回？' : '放弃草稿并返回？'}</Dialog.Title><Dialog.Content><Text>{model.requestId ? '页面会清除私密资料和原请求内容，仅在当前应用内存中保留本人操作编号。重新进入可读回核对；关闭或刷新应用前，请自行保留编号。未找到回执不代表未保存。' : '当前尚未保存的账户草稿会清除。'}</Text>{model.requestId && <Text selectable style={styles.wrap}>{model.requestId}</Text>}</Dialog.Content><Dialog.Actions><Button contentStyle={styles.touch} onPress={() => install({ leave: false })}>继续核对</Button><Button contentStyle={styles.touch} onPress={exit}>{model.requestId ? '保留编号并返回财务' : '放弃并返回财务'}</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}
function Pager({ page, pages, total, disabled, onPage }: { page: number; pages: number; total: number; disabled: boolean; onPage: (page: number) => void }) { return <View style={styles.actions}><Text>{total ? `第 ${page} / ${pages} 页，共 ${total} 项` : '没有匹配的记录'}</Text><Button contentStyle={styles.touch} disabled={disabled || page <= 1} onPress={() => onPage(page - 1)}>上一页</Button><Button contentStyle={styles.touch} disabled={disabled || page >= pages} onPress={() => onPage(page + 1)}>下一页</Button></View>; }
const styles = StyleSheet.create({ touch: { minHeight: 44 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, wrap: { flexShrink: 1, ...(Platform.OS === 'web' ? { overflowWrap: 'anywhere' as const } : {}) } });
