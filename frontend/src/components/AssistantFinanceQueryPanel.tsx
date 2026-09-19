import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Text, TextInput } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PlaceDiscarded, PlaceFence, type PlaceSession } from '../lib/places';
import { checkedRescheduleWrite, RescheduleUnverified } from '../lib/journeyReschedule';
import { financeQueryNavigation, financeQueryRefreshPrompt, financeQueryRequest, readFinanceQuery, sameFinanceQuery, type FinanceQuery, type FinanceQueryResult } from '../lib/assistantFinanceQuery';
import { formatFinanceAmount } from '../lib/finance';
import type { FinanceNavigationRequest, ScreenProps } from '../lib/types';
import FinanceScreen from '../screens/FinanceScreen';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = { initialPrompt: string; initialUseModel: boolean; modelConfigured: boolean; screenProps: ScreenProps; onBack: (prompt: string) => void };
const front = () => (typeof document === 'undefined' || !document.hidden) && (typeof navigator === 'undefined' || navigator.onLine !== false);
export default function AssistantFinanceQueryPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请使用成员账户查询财务" />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef(household); latest.current = household;
  const alive = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false), working = useRef(false), started = useRef(false), epoch = useRef(0), sequence = useRef(0);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PlaceFence(() => request<PlaceSession>('/me'), props.identityKey));
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [prompt, setPrompt] = useState(props.initialPrompt), [useModel, setUseModel] = useState(props.initialUseModel);
  const [result, setResult] = useState<FinanceQueryResult | null>(null), [navigation, setNavigation] = useState<FinanceNavigationRequest | null>(null);
  const returnQuery = useRef<FinanceQuery | null>(null), pendingRefresh = useRef<FinanceQuery | null>(null);
  const live = useRef({ prompt, useModel }); live.current = { prompt, useModel };
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && !denied.current && appActive.current && front()
    && latest.current.online && latest.current.identityKey === props.identityKey && ticket === epoch.current;
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); working.current = false; setVisible(false); setBusy(false); setResult(null);
    pendingRefresh.current = returnQuery.current;
    if (clear) { setPrompt(''); setUseModel(false); setNavigation(null); returnQuery.current = null; pendingRefresh.current = null; live.current = { prompt: '', useModel: false }; }
  }
  function failed(failure: unknown, ticket: number) {
    if (!alive.current || ticket !== epoch.current) return;
    const reason = failure instanceof RescheduleUnverified ? failure.reason : failure;
    if (reason instanceof PlaceDiscarded && reason.message !== 'identity') return;
    if (reason instanceof PlaceDiscarded || reason instanceof ApiError && [401, 403].includes(reason.status)) {
      conceal(true); denied.current = true; setError('登录身份或权限已变化，财务查询已清除。请返回助理重新进入。'); void latest.current.refresh(); return;
    }
    if (failure instanceof RescheduleUnverified) { conceal(); setError('暂时无法核对登录身份，财务内容已隐藏。请重新连接。'); return; }
    if (!current(ticket)) return;
    if (reason instanceof ApiError) setError(reason.status === 429 ? '查询较多，请稍后再试。' : reason.status >= 500 ? '暂时无法查询。问题已保留，可重试或关闭 AI 使用本地查询。' : reason.status === 0 ? '连接中断，问题已保留，请重新连接后查询。' : '暂时无法查询，请补充月份和查询范围后重试。');
    else setError('查询结果暂时无法核对，请重新查询。');
  }
  const guarded = <T,>(action: (csrf: string) => Promise<T>, ticket: number) => checkedRescheduleWrite(job => fence.current.run(job, () => current(ticket)), action, () => undefined);
  function enter() {
    if (!alive.current || !focused.current || active.current || denied.current || !appActive.current || !front() || !latest.current.online || latest.current.identityKey !== props.identityKey) return;
    active.current = true; const ticket = epoch.current; working.current = true; setBusy(true);
    void (async () => {
      try { await guarded(async () => true, ticket); if (current(ticket)) { setVisible(true); setError(''); } }
      catch (failure) { failed(failure, ticket); }
      finally { if (current(ticket)) { working.current = false; setBusy(false); } }
    })();
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const change = () => { if (front()) enter(); else conceal(); };
    const subscription = AppState.addEventListener('change', state => { appActive.current = state === 'active'; if (appActive.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', change);
    if (typeof window !== 'undefined') { window.addEventListener('online', change); window.addEventListener('offline', change); }
    const timer = setInterval(() => { if (current() && !working.current) { const ticket = epoch.current; void guarded(async () => true, ticket).catch(failure => failed(failure, ticket)); } }, 15000);
    return () => { clearInterval(timer); subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', change); if (typeof window !== 'undefined') { window.removeEventListener('online', change); window.removeEventListener('offline', change); } };
  }, []);
  useEffect(() => { if (household.identityKey !== props.identityKey) { conceal(true); denied.current = true; } else if (!household.online) conceal(); else enter(); }, [household.identityKey, household.online]);
  useEffect(() => {
    if (!visible || !current() || busy || navigation) return;
    if (pendingRefresh.current) { const query = pendingRefresh.current; pendingRefresh.current = null; void queryFinance(query); }
    else if (!started.current) { started.current = true; void queryFinance(); }
  }, [visible, busy, navigation]);
  async function queryFinance(refresh?: FinanceQuery) {
    if (!current() || working.current) return;
    let body;
    try { body = financeQueryRequest(refresh ? financeQueryRefreshPrompt(refresh) : live.current.prompt, refresh ? false : live.current.useModel); }
    catch { setError('请补充财务问题后查询。'); return; }
    const ticket = epoch.current; working.current = true; setBusy(true); setError(''); setResult(null);
    try {
      const next = readFinanceQuery(await guarded(csrf => request('/assistant/finance-query', { method: 'POST', body: JSON.stringify(body) }, csrf), ticket));
      if (refresh && !sameFinanceQuery(next.query, refresh)) throw new Error('scope changed');
      if (current(ticket)) { returnQuery.current = next.query; setResult(next); }
    } catch (failure) { failed(failure, ticket); }
    finally { if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  const locked = !visible || busy || !household.online || denied.current;
  const hidden = <SectionCard title="财务查询暂时隐藏"><Text>{error || '联网并核对本人身份后继续，问题仅保留在当前登录页面。'}</Text><Button disabled={busy || !household.online || denied.current} onPress={enter}>重新连接查询</Button>{!navigation && <Button disabled={busy} onPress={() => props.onBack(denied.current ? '' : live.current.prompt)}>返回助理</Button>}</SectionCard>;
  if (navigation) return <View>{!visible && hidden}<View style={visible ? undefined : { display: 'none' }}><FinanceScreen {...props.screenProps} financeRequest={navigation} onReturnToQuery={() => {
    if (!current() || working.current) return;
    pendingRefresh.current = returnQuery.current; setNavigation(null); setResult(null); conceal(); enter();
  }} /></View></View>;
  if (!visible) return <View style={styles.page}><ActivityIndicator animating={busy} />{hidden}</View>;
  return <View style={styles.page} testID="assistant-finance-query-panel">
    <PageHeader title="预算与支出" description="按账本已记录的范围查询，各币种分别展示。" />
    <Button disabled={busy} onPress={() => props.onBack(prompt)}>返回助理</Button>
    <SectionCard title="想了解什么？">
      <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} label="财务问题" accessibilityLabel="财务问题" multiline value={prompt} maxLength={2000} disabled={locked}
        onChangeText={value => { if (current() && !working.current) { setPrompt(value); setResult(null); returnQuery.current = null; pendingRefresh.current = null; setError(''); } }} />
      <SelectionRow label="使用已配置的 AI 整理" checked={useModel} disabled={locked || !props.modelConfigured}
        onPress={() => { if (current() && !working.current && props.modelConfigured) { setUseModel(!useModel); setResult(null); returnQuery.current = null; pendingRefresh.current = null; } }} />
      {useModel && <Text variant="bodySmall">允许 AI 理解较复杂的说法。仅发送本次问题，不会附带账本、预算金额和家庭资料。</Text>}
      <Button mode="contained" loading={busy} disabled={locked || !prompt.trim()} onPress={() => void queryFinance()}>查询</Button>
    </SectionCard>
    {!!error && <Text accessibilityRole="alert">{error}</Text>}
    {result && result.status !== 'ready' && <View testID="assistant-finance-query-clarification"><SectionCard title={result.status === 'clarify' ? '请补充查询范围' : '这项需求暂不支持'}><Text>{result.message}</Text></SectionCard></View>}
    {result?.status === 'ready' && result.query && <View testID="assistant-finance-query-result" style={styles.page}>
      <SectionCard title={result.query.scope === 'personal' ? '本人账本' : result.query.scope === 'shared' ? '已共享消费' : '共同资金当前快照'}>
        <Text>{result.message}</Text>
        {result.query.month && <Text>{result.query.month}{result.query.category ? ' · ' + result.query.category : ''}</Text>}
        {result.totals.map(total => <View key={total.currency} style={styles.item}><Text variant="titleMedium">{total.currency} · 已记录净支出</Text><Text variant="headlineSmall" selectable>{formatFinanceAmount(total.netSpendCents, total.currency)}</Text><Text>消费 {formatFinanceAmount(total.expenseCents, total.currency)} · 退款 {formatFinanceAmount(total.refundCents, total.currency)}</Text></View>)}
        {!result.totals.length && result.query.scope !== 'public' && <Text>此范围暂无可汇总的消费记录，不能据此认定没有支出。</Text>}
        {result.query.scope === 'shared' && <Text>只包括明确共享的消费与退款，不是荷包余额。</Text>}
        {result.snapshot && <><Text>手工核对的当前金额，不代表所选历史月份。</Text>{([['walletCents', '公共荷包'], ['livingSpentCents', '生活已花费'], ['livingBudgetCents', '生活预算'], ['savingsCents', '共同长期储蓄']] as const).map(([key, label]) => <View key={key} style={styles.item}><Text>{label}</Text><Text variant="titleLarge">{result.snapshot![key] === null ? '待核对' : formatFinanceAmount(result.snapshot![key]!, 'CNY')}</Text></View>)}<Text>最近核对：{result.snapshot.confirmedAt || '尚未核对'}</Text></>}
        <Text variant="bodySmall">{result.coverage.note}</Text>
      </SectionCard>
      {result.query.scope === 'personal' && result.query.metric !== 'spending' && <SectionCard title="月预算">
        {!result.budgets.length ? <Text>此范围尚未设置预算，无法计算还剩多少。</Text> : result.budgets.map(budget => <View key={budget.currency + ':' + budget.category} style={styles.item}><Text variant="titleMedium">{budget.currency} · {budget.category}</Text><Text variant="headlineSmall">剩余 {formatFinanceAmount(budget.remainingCents, budget.currency)}</Text><Text>预算 {formatFinanceAmount(budget.amountCents, budget.currency)} · 已记净支出 {formatFinanceAmount(budget.spentCents, budget.currency)}</Text></View>)}
        {!!result.budgets.length && <Text variant="bodySmall">总预算与分类预算分别核对，不能相加；未导入支出可能影响剩余额度。</Text>}
      </SectionCard>}
      <Button mode="outlined" disabled={locked} onPress={() => { if (!current() || working.current) return; returnQuery.current = result.query; setNavigation(financeQueryNavigation(result, props.identityKey, ++sequence.current)); setResult(null); }}>{result.navigation?.tab === 'ledger' ? '查看本人账本' : result.navigation?.tab === 'budgets' ? '查看月预算' : '查看共同资金'}</Button>
    </View>}
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16 }, item: { gap: 6, paddingVertical: 10 } });
