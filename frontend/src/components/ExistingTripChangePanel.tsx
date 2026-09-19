import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Text, TextInput } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PlaceDiscarded, PlaceFence, type PlaceSession } from '../lib/places';
import { checkedRescheduleWrite, RescheduleUnverified } from '../lib/journeyReschedule';
import { readTripChange, tripChangeHints, tripChangeRequest, tripSelectionRequest, tripSuggestion, type TripChangePlan, type TripSuggestion } from '../lib/assistantTripChange';
import JourneyReschedulePanel from '../screens/JourneyReschedulePanel';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = { initialPrompt: string; initialUseModel: boolean; modelConfigured: boolean; onBack: (prompt: string) => void; onSaved: (tripId: string) => void; onPendingChange?: (pending: boolean) => void };
const front = () => (typeof document === 'undefined' || !document.hidden) && (typeof navigator === 'undefined' || navigator.onLine !== false);
export default function ExistingTripChangePanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户调整已有旅行" />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef(household); latest.current = household;
  const alive = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false), working = useRef(false), started = useRef(false), epoch = useRef(0);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PlaceFence(() => request<PlaceSession>('/me'), props.identityKey));
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [prompt, setPrompt] = useState(props.initialPrompt), [useModel, setUseModel] = useState(props.initialUseModel);
  const [plan, setPlan] = useState<TripChangePlan | null>(null), [suggestion, setSuggestion] = useState<TripSuggestion | null>(null), [page, setPage] = useState(0);
  const live = useRef({ prompt, useModel, plan }); live.current = { prompt, useModel, plan };
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && !denied.current && appActive.current && front()
    && latest.current.online && latest.current.identityKey === props.identityKey && ticket === epoch.current;
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); working.current = false; setVisible(false); setBusy(false);
    if (clear) { setPrompt(''); setUseModel(false); setPlan(null); setSuggestion(null); live.current = { prompt: '', useModel: false, plan: null }; }
  }
  function failed(failure: unknown, ticket: number) {
    if (!alive.current || ticket !== epoch.current) return;
    const original = failure instanceof RescheduleUnverified ? failure.reason : failure;
    if (original instanceof PlaceDiscarded && original.message !== 'identity') return;
    if (original instanceof PlaceDiscarded || original instanceof ApiError && [401, 403].includes(original.status)) {
      conceal(true); denied.current = true; setError('登录身份或权限已变化，建议已清除。请返回助理重新进入。'); void latest.current.refresh(); return;
    }
    if (failure instanceof RescheduleUnverified) { conceal(); setError('暂时无法核对登录身份。需求保留在本页，重新连接后继续。'); return; }
    if (!current(ticket)) return;
    if (original instanceof ApiError) {
      if (original.status === 409) { setPlan(null); setError('旅行来源或选择期限已变化。需求仍保留，请重新整理。'); }
      else if (original.status === 429) setError('整理请求较多，请稍后重试；本次尚未改期。');
      else if (original.status >= 500) setError('暂时无法生成建议，尚未改期。请保留文字后重试，或关闭 AI 使用本地整理。');
      else if (original.code === 'candidate_limit' || original.code === 'model_candidate_limit') setError('匹配旅行过多，请写明旅行名称，或从旅行列表手动改期。');
      else if (original.status === 0) setError('连接中断，需求仍保留。重新连接后可再整理，尚未改期。');
      else setError('请求暂时无法核对，请补充旅行名称和准确日期后重新整理。');
    } else setError(original instanceof Error ? original.message : '暂时无法读取旅行建议，请保留原文重试。');
  }
  function guarded<T>(action: (csrf: string) => Promise<T>, ticket: number) {
    // A failed final /me must conceal even a successful read-only planning POST.
    return checkedRescheduleWrite(job => fence.current.run(job, () => current(ticket)), action, () => undefined);
  }
  function enter() {
    if (!alive.current || !focused.current || active.current || denied.current || !appActive.current || !front() || !latest.current.online || latest.current.identityKey !== props.identityKey) return;
    active.current = true; const ticket = epoch.current; working.current = true; setBusy(true);
    void (async () => {
      try { await guarded(async () => true, ticket); if (current(ticket)) setVisible(true); }
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
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', change); if (typeof window !== 'undefined') { window.removeEventListener('online', change); window.removeEventListener('offline', change); } };
  }, []);
  useEffect(() => {
    if (household.identityKey !== props.identityKey) { conceal(true); denied.current = true; }
    else if (!household.online) conceal(); else enter();
  }, [household.identityKey, household.online]);
  // Opening this panel follows the user's explicit 整理并预览 action. Resume is
  // only a session check; it never silently invokes a model for a second time.
  useEffect(() => { if (visible && current() && !busy && !started.current) { started.current = true; void prepare(); } }, [visible, busy]);
  async function prepare(selectedRef?: string) {
    if (!current() || working.current) return;
    let body;
    try { body = selectedRef ? tripSelectionRequest(live.current.plan!, selectedRef) : tripChangeRequest(live.current.prompt, live.current.useModel); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '请补充需求。'); return; }
    const ticket = epoch.current; working.current = true; setBusy(true); setError(''); setPlan(null);
    try {
      const result = readTripChange(await guarded(csrf => request<unknown>('/assistant/trip-change', { method: 'POST', body: JSON.stringify(body) }, csrf), ticket), selectedRef);
      if (current(ticket)) { setPlan(result); setPage(0); }
    } catch (failure) { failed(failure, ticket); }
    finally { if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  const locked = !visible || busy || !household.online || denied.current;
  const hints = plan ? tripChangeHints(plan) : [], candidates = plan?.status === 'choose_trip' ? plan.candidates : [], pages = Math.max(1, Math.ceil(candidates.length / 8));
  const hidden = <SectionCard title="旅行建议暂时隐藏"><Text>{error || '连接网络并核对当前登录后继续，原需求留在本页。'}</Text><Button disabled={busy || !household.online || denied.current} onPress={enter}>重新连接旅行建议</Button><Button disabled={busy} onPress={() => props.onBack(live.current.prompt)}>返回助理</Button></SectionCard>;
  if (suggestion) return <View>{!visible && hidden}<View style={visible ? undefined : { display: 'none' }}>
    <JourneyReschedulePanel journeyId={suggestion.source.journeyId} initialSuggestion={suggestion} onPendingChange={props.onPendingChange}
      onBack={() => { if (current()) { setSuggestion(null); setPlan(null); setError('需求仍保留，可重新整理建议。'); } }}
      onSaved={result => { if (current() && result.journeyId === suggestion.source.journeyId) props.onSaved(suggestion.source.tripId); }} />
  </View></View>;
  if (!visible) return <View style={styles.page}><ActivityIndicator animating={busy} />{hidden}</View>;
  return <View style={styles.page} testID="assistant-trip-change-panel">
    <PageHeader title="调整已有旅行" description="先确认原旅行与日期，再核对需要联动的安排。" />
    <Button disabled={busy} onPress={() => props.onBack(prompt)}>返回助理</Button>
    <SectionCard title="这次改期需求">
      <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} multiline label="改期需求" accessibilityLabel="改期需求" value={prompt} maxLength={2000} disabled={locked}
        onChangeText={value => { if (!current() || working.current) return; setPrompt(value); setPlan(null); setError(''); }} />
      <SelectionRow label="使用已配置的 AI 整理" checked={useModel} disabled={locked || !props.modelConfigured}
        onPress={() => { if (current() && !working.current && props.modelConfigured) { setUseModel(!useModel); setPlan(null); setError(''); } }} />
      {useModel && <Text variant="bodySmall">本次文字及必要候选的旅行标题、日期、时区会发送给已配置的 AI。模型只提供建议。</Text>}
      <Button mode={plan?.status === 'ready' ? 'outlined' : 'contained'} loading={busy} disabled={locked || !prompt.trim()} onPress={() => void prepare()}>{plan ? '重新整理需求' : '整理改期建议'}</Button>
    </SectionCard>
    {!!error && <Text accessibilityRole="alert">{error}</Text>}
    {!!hints.length && <SectionCard title="还需要核对"><View testID="assistant-trip-change-clarification" style={styles.page}>{hints.map(hint => <Text key={hint}>{hint}</Text>)}</View></SectionCard>}
    {plan?.status === 'choose_trip' && <SectionCard title="你要调整哪趟旅行？"><Text>选择同名或相关旅行，沿用这次需求继续核对。</Text>
      {candidates.slice(page * 8, page * 8 + 8).map(candidate => <View key={candidate.ref} style={styles.item}>
        <Text variant="titleMedium">{candidate.title}</Text><Text>{candidate.start} — {candidate.end}</Text>
        <Button mode="outlined" disabled={locked} accessibilityLabel={`选择旅行 ${candidate.title} ${candidate.start}`} onPress={() => void prepare(candidate.ref)}>选择这趟旅行</Button>
      </View>)}
      {pages > 1 && <View style={styles.actions}><Button disabled={locked || page === 0} onPress={() => setPage(page - 1)}>上一页</Button><Text>{page + 1} / {pages}</Text><Button disabled={locked || page + 1 >= pages} onPress={() => setPage(page + 1)}>下一页</Button></View>}
    </SectionCard>}
    {plan?.status === 'ready' && plan.source && plan.draft && <View testID="assistant-trip-change-suggestion"><SectionCard title={plan.source.title}>
      <Text>{plan.mode === 'model' ? 'AI 建议' : '本地整理'} · 尚未改期</Text><Text>原日期：{plan.source.start} — {plan.source.end}</Text><Text>建议日期：{plan.draft.start} — {plan.draft.end}</Text>
      <Text>下一步读取最新旅行，选择需要联动的行程与准备事项，再预览确认。</Text>
      <Button mode="contained" disabled={locked} onPress={() => { if (current() && !working.current) setSuggestion(tripSuggestion(plan)); }}>核对改期影响</Button>
    </SectionCard></View>}
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16 }, item: { gap: 8, paddingVertical: 8 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 } });
