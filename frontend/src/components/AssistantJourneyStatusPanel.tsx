import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Chip, Text, TextInput } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { JourneyStatusFlow, statusRead, type StatusState } from '../lib/assistantJourneyStatus';
import type { ScreenProps } from '../lib/types';
import TripsScreen from '../screens/TripsScreen';
import { PageHeader, SectionCard } from '../ui/components';

type Props = { initialPrompt: string; screenProps: ScreenProps; onBack: (prompt: string) => void };
const front = () => (typeof document === 'undefined' || !document.hidden) && (typeof navigator === 'undefined' || navigator.onLine !== false);
export default function AssistantJourneyStatusPanel(props: Props) {
  const household = useHousehold();
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef(household); latest.current = household;
  const focused = useRef(false), appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const [flow, setFlow] = useState<JourneyStatusFlow | null>(null), [state, setState] = useState<StatusState | null>(null);
  const [trip, setTrip] = useState<{ id?: string; key: number } | null>(null), sequence = useRef(0), tripRef = useRef(trip); tripRef.current = trip;
  const pending = useRef({ reschedule: false, documents: false, segments: false, import: false, finance: false });
  const current = () => focused.current && appActive.current && front() && latest.current.online && latest.current.identityKey === props.identityKey;
  useEffect(() => {
    const next = new JourneyStatusFlow(props.identityKey, props.initialPrompt, {
      read: statusRead, current, expired: () => { setTrip(null); void latest.current.refresh(); },
    }, setState);
    setFlow(next); setState(next.state); if (current()) void next.resume();
    return () => next.close();
  }, [props.identityKey]);
  useFocusEffect(useCallback(() => { focused.current = true; if (current()) void flow?.resume(); return () => { focused.current = false; flow?.conceal(); }; }, [flow]));
  useEffect(() => {
    const visibility = () => { if (current()) void flow?.resume(); else flow?.conceal(); };
    const subscription = AppState.addEventListener('change', value => { appActive.current = value === 'active'; visibility(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', visibility); window.addEventListener('online', visibility); }
    const timer = setInterval(() => { if (current() && !tripRef.current && flow?.state.result && !flow.state.busy) void flow.load(true); }, 10000);
    return () => { clearInterval(timer); subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', visibility); window.removeEventListener('online', visibility); } };
  }, [flow]);
  useEffect(() => { if (!household.online) flow?.conceal(); else if (current()) void flow?.resume(); }, [household.online]);
  const pendingReschedule = useCallback((v: boolean) => { pending.current.reschedule = v; props.screenProps.onReschedulePending?.(v); }, [props.screenProps.onReschedulePending]);
  const pendingDocuments = useCallback((v: boolean) => { pending.current.documents = v; props.screenProps.onDocumentsPending?.(v); }, [props.screenProps.onDocumentsPending]);
  const pendingSegments = useCallback((v: boolean) => { pending.current.segments = v; props.screenProps.onSegmentsPending?.(v); }, [props.screenProps.onSegmentsPending]);
  const pendingImport = useCallback((v: boolean) => { pending.current.import = v; props.screenProps.onTripImportPending?.(v); }, [props.screenProps.onTripImportPending]);
  const pendingFinance = useCallback((v: boolean) => { pending.current.finance = v; props.screenProps.onJourneyFinancePending?.(v); }, [props.screenProps.onJourneyFinancePending]);
  const shown = !!state?.visible && current() && !state.expired;
  const locked = !shown || !!state?.busy;
  const hidden = <SectionCard title="旅行查询暂时隐藏"><View testID="assistant-journey-status-hidden" style={styles.page}>
    <Text accessibilityRole={state?.error ? 'alert' : undefined}>{state?.error || '联网并核对当前身份后继续，查询只保留在本页。'}</Text>
    <Button testID="assistant-journey-status-refresh" disabled={!!state?.busy || !current() || !!state?.expired} onPress={() => void flow?.resume()}>重新读取</Button>
    {!trip && <Button disabled={!!state?.busy} onPress={() => props.onBack(state?.expired ? '' : state?.prompt || '')}>返回助理</Button>}
    {trip && <Button disabled={!!state?.busy || Object.values(pending.current).some(Boolean)} onPress={() => {
      if (state?.busy || Object.values(pending.current).some(Boolean)) return;
      setTrip(null); tripRef.current = null; if (current()) void flow?.resume();
    }}>放弃未提交编辑，返回准备查询</Button>}
  </View></SectionCard>;
  if (trip) return <View style={styles.page}>
    {!shown && hidden}
    <View style={shown ? undefined : { display: 'none' }}>
      <TripsScreen {...props.screenProps} key={trip.key} tripRequest={trip}
        onReschedulePending={pendingReschedule} onDocumentsPending={pendingDocuments} onSegmentsPending={pendingSegments}
        onTripImportPending={pendingImport} onJourneyFinancePending={pendingFinance}
        onExitPlanning={() => {
          if (!current() || !flow?.state.visible || flow.state.expired || Object.values(pending.current).some(Boolean)) return;
          setTrip(null); tripRef.current = null; void flow.load(true);
        }} />
    </View>
  </View>;
  if (!shown) return <View style={styles.page}><ActivityIndicator animating={!!state?.busy} />{hidden}</View>;
  const result = state.result, status = result?.view === 'status' ? result : null, candidates = result?.view === 'candidates' ? result : null;
  return <View style={styles.page} testID="assistant-journey-status-panel">
    <PageHeader title="旅行准备情况" description="只读取本家庭已保存的旅行准备记录，不调用 AI。" />
    <Button disabled={locked} onPress={() => props.onBack(state.prompt)}>返回助理</Button>
    {!!state.prompt && <Text testID="assistant-journey-status-question">原问题：{state.prompt}</Text>}
    {!status && <SectionCard title="选择已有旅行">
      {!!state.clarification && <Text>{state.clarification}</Text>}
      <TextInput testID="assistant-journey-status-query" accessibilityLabel="旅行关键词" label="旅行关键词" mode="outlined" outlineStyle={{ borderRadius: 8 }} maxLength={200}
        value={state.query} disabled={locked} onChangeText={value => flow?.editQuery(value)} placeholder="名称或目的地；留空查看已有旅行" />
      <Button testID="assistant-journey-status-search" mode="contained" disabled={locked} onPress={() => void flow?.search()}>查询已有旅行</Button>
    </SectionCard>}
    {!!state.notice && <Text accessibilityLiveRegion="polite">{state.notice}</Text>}
    {candidates && <SectionCard title={candidates.query ? `匹配旅行 · ${candidates.query}` : '已有旅行'}>
      {(candidates.coverage.capped || candidates.coverage.unverifiable > 0) && <Text>仅核对部分已有旅行；未显示的记录不能视为不存在。</Text>}
      {!candidates.items.length && <Text>本次范围没有匹配的旅行。可修改关键词或查看旅行列表，不会自动新建。</Text>}
      {candidates.items.map(item => <View testID={'assistant-journey-status-candidate-' + item.tripId} key={item.tripId} style={styles.item}>
        <Text variant="titleMedium">{item.title}</Text><Text>{item.start || '日期待核对'} — {item.end || '日期待核对'} · {item.destination || '目的地未填写'}</Text>
        {item.status !== 'available' && <Text>{item.status === 'legacy' ? '尚无可核对的准备清单' : '关联记录需核对'}</Text>}
        <Button disabled={locked} accessibilityLabel={'查看这趟准备 ' + item.title + ' ' + item.start} onPress={() => void flow?.select(item.tripId)}>查看这趟准备</Button>
      </View>)}
      <View style={styles.actions}><Button testID="assistant-journey-status-candidates-prev" disabled={locked || candidates.offset === 0} onPress={() => void flow?.page(false)}>上一页旅行</Button>
        <Text>第 {candidates.offset / 20 + 1} 页</Text><Button testID="assistant-journey-status-candidates-next" disabled={locked || candidates.nextOffset === null} onPress={() => void flow?.page(true)}>下一页旅行</Button></View>
    </SectionCard>}
    {status && <View style={styles.page} testID="assistant-journey-status-status">
      <SectionCard title={status.trip.title}>
        <Text>{status.trip.start} — {status.trip.end} · {status.trip.destination || '目的地未填写'}</Text>
        {status.state === 'legacy' && <Text>这趟旅行尚未建立可核对的准备清单。</Text>}
        {status.state === 'needs_review' && <Text>关联准备记录需核对。以下仅为可核实的范围，不能视为全部准备量。</Text>}
        {status.summary && <View testID="assistant-journey-status-summary" style={styles.page}>
          <Text>准备：已完成 {status.summary.tasks.done} / {status.summary.tasks.total} · 未完成 {status.summary.tasks.remaining} · 阻塞 {status.summary.tasks.blocked}</Text>
          <Text>采购：已完成 {status.summary.shopping.done} / {status.summary.shopping.total} · 未完成 {status.summary.shopping.remaining}</Text>
          {status.state === 'ready' && status.coverage.complete && status.summary.tasks.remaining === 0 && status.summary.shopping.remaining === 0 && <Text>已记录的准备事项均已完成。</Text>}
        </View>}
        <Text variant="bodySmall">未记录事项、真实预订和云同步尚未核验；采购完成不代表已经下单、付款或入库。</Text>
        <Button testID="assistant-journey-status-open" mode="contained" disabled={locked} onPress={() => {
          if (locked || !current() || flow?.state.result?.view !== 'status') return;
          setTrip({ id: flow.state.result.trip.tripId, key: ++sequence.current });
        }}>打开原旅行处理</Button>
      </SectionCard>
      {status.summary && <SectionCard title="尚未完成">
        <View style={styles.actions}>{(['tasks', 'shopping'] as const).map(section => <Chip key={section} testID={'assistant-journey-status-' + section} selected={status.section === section} disabled={locked} onPress={() => void flow?.section(section)}>{section === 'tasks' ? '准备事项' : '采购事项'}</Chip>)}</View>
        {!status.items.length && <Text>此页没有可核实的未完成事项。</Text>}
        {status.items.map(item => <View key={item.id} testID={'assistant-journey-status-item-' + item.id} style={styles.item}>
          <Text variant="titleMedium">{item.title}</Text><Text>{item.owner.name || '负责人待核对'} · {item.due || '未设截止'}</Text>
          {item.kind === 'shopping' ? <Text>{item.quantity} · {{ low: '低优先级', normal: '普通优先级', high: '高优先级' }[item.priority]}</Text>
            : <><Text>{item.dependencyStatus === 'blocked' ? '前置未完成，当前阻塞' : '无未完成的直接前置'}</Text>{item.blockers.map((blocker, i) => <Text key={i} variant="bodySmall">{blocker.reason === 'unavailable' ? '前置事项当前不可核对' : '等待：' + blocker.title}</Text>)}</>}
        </View>)}
        <View style={styles.actions}><Button testID="assistant-journey-status-items-prev" disabled={locked || status.offset === 0} onPress={() => void flow?.page(false)}>上一页事项</Button><Text>第 {status.offset / 20 + 1} 页</Text>
          <Button testID="assistant-journey-status-items-next" disabled={locked || status.nextOffset === null} onPress={() => void flow?.page(true)}>下一页事项</Button></View>
      </SectionCard>}
      <Button testID="assistant-journey-status-back-candidates" disabled={locked} onPress={() => void flow?.candidates()}>返回候选旅行</Button>
    </View>}
    <View style={styles.actions}><Button testID="assistant-journey-status-refresh" disabled={locked} onPress={() => void flow?.load(true)}>重新读取</Button>
      {!status && <Button testID="assistant-journey-status-trips" disabled={locked} onPress={() => setTrip({ key: ++sequence.current })}>查看旅行列表</Button>}</View>
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16 }, item: { gap: 6, paddingVertical: 12 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 } });
