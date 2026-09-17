import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { Button, Checkbox, Chip, Divider, HelperText, Text, TextInput, useTheme } from 'react-native-paper';
import { request } from '../lib/api';
import { isJourneyRequest, journeySessionKey } from '../lib/assistantJourney';
import type { Draft, Session } from '../lib/trips';
import JourneyBriefPanel from './JourneyBriefPanel';
import TripsScreen from './TripsScreen';
import { AssistantFlow, AssistantState, memberKey, type Match } from '../lib/assistant';
import { useHousehold } from '../lib/household';
import type { ScreenProps } from '../lib/types';
import { PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

function inventorySummary(item: Match) {
  const quantities = [item.onHandQty, item.inTransitQty, item.plannedQty];
  if (!item.unit || !quantities.every(value => Number.isSafeInteger(value) && value! >= 0)) return '打开物品，查看最新库存和到货情况。';
  return `现有 ${item.onHandQty} ${item.unit} · 在途 ${item.inTransitQty} ${item.unit} · 计划 ${item.plannedQty} ${item.unit}`;
}

type JourneyPanel = { kind: 'brief'; key: number; prompt: string; useModel: boolean; prepare: boolean }
  | { kind: 'planning'; key: number; draft: Draft };

export function AssistantScreen(props: ScreenProps) {
  const household = useHousehold();
  return <AssistantEntry key={household.identityKey} {...props} />;
}

function AssistantEntry(props: ScreenProps) {
  const household = useHousehold(), actor = household.identityKey;
  const [panel, setPanel] = useState<JourneyPanel | null>(null), [sourcePrompt, setSourcePrompt] = useState('');
  const [visible, setVisible] = useState(false), [gateError, setGateError] = useState('');
  const sequence = useRef(0), focused = useRef(false), generation = useRef(0), ready = useRef(false);
  const latest = useRef(household); latest.current = household;
  const panelRef = useRef(panel); panelRef.current = panel;
  const reschedulePending = useRef(false);
  const pendingReschedule = (pending: boolean) => { reschedulePending.current = pending; props.onReschedulePending?.(pending); };
  const available = () => focused.current && latest.current.identityKey === actor
    && latest.current.online && (typeof navigator === 'undefined' || navigator.onLine !== false)
    && (typeof document === 'undefined' || !document.hidden);
  const conceal = () => { ++generation.current; ready.current = false; setVisible(false); };
  async function verify() {
    conceal();
    const ticket = generation.current;
    if (!available()) return;
    try {
      const session = await request<Session>('/me');
      if (ticket !== generation.current || !available()) return;
      if (session.user?.role !== 'member' || journeySessionKey(session) !== actor) {
        setPanel(null); setSourcePrompt(''); void latest.current.refresh(); return;
      }
      ready.current = true; setVisible(true); setGateError('');
    } catch {
      if (ticket === generation.current && available()) setGateError('连接暂时无法核对，旅行草稿已隐藏。请重试。');
    }
  }
  useFocusEffect(useCallback(() => {
    focused.current = true;
    return () => { focused.current = false; conceal(); if (!reschedulePending.current) { setPanel(null); setSourcePrompt(''); } };
  }, [actor]));
  useEffect(() => {
    if (!panel) return;
    void verify();
    const subscription = AppState.addEventListener('change', state => { if (state === 'active') void verify(); else conceal(); });
    const visibility = () => { if (document.hidden) conceal(); else void verify(); };
    const offline = () => conceal(), online = () => void verify();
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', online); }
    return () => {
      conceal(); subscription.remove();
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', online); }
    };
  }, [!!panel, actor]);
  const begin = (prompt: string, useModel: boolean, prepare: boolean) => {
    if (!available() || panelRef.current) return;
    setSourcePrompt(prompt);
    setPanel({ kind: 'brief', key: ++sequence.current, prompt, useModel, prepare });
  };
  if (!panel) return <AssistantWorkspace {...props} initialPrompt={sourcePrompt} onJourney={begin} />;
  const allowed = visible && household.online;
  return <View>
    {!allowed && <SectionCard title="旅行草稿暂时隐藏">
      <Text>{gateError || '返回前台并连接网络后，核对当前登录再继续。'}</Text>
      <Button onPress={() => void verify()}>重新连接旅行</Button>
    </SectionCard>}
    <View style={allowed ? undefined : { display: 'none' }}>
      {panel.kind === 'brief' ? <JourneyBriefPanel key={panel.key} user={props.user} people={props.state.people}
        initialPrompt={panel.prompt} initialUseModel={panel.useModel} prepareOnOpen={panel.prepare}
        onCancel={() => { if (ready.current && available()) setPanel(null); }}
        onPrepared={draft => {
          if (!ready.current || !available() || panelRef.current?.key !== panel.key || panelRef.current.kind !== 'brief') return;
          setPanel({ kind: 'planning', key: ++sequence.current, draft });
        }} />
        : <TripsScreen {...props} key={panel.key} tripRequest={undefined} initialDraft={panel.draft} onReschedulePending={pendingReschedule}
          onExitPlanning={() => { if (ready.current && available()) setPanel(null); }} />}
    </View>
  </View>;
}

function AssistantWorkspace(props: ScreenProps & {
  initialPrompt?: string; onJourney: (prompt: string, useModel: boolean, prepare: boolean) => void;
}) {
  const household = useHousehold(), theme = useTheme();
  const latest = useRef({ household, user: props.user }); latest.current = { household, user: props.user };
  const [flow, setFlow] = useState<AssistantFlow | null>(null);
  const [view, setView] = useState<AssistantState | null>(null);
  const [prompt, setPrompt] = useState(''), [useModel, setUseModel] = useState(false), [includeContext, setIncludeContext] = useState(false);
  const [foreground, setForeground] = useState(true);
  const actor = memberKey(props.user);
  useFocusEffect(useCallback(() => {
    let active = true;
    setPrompt(props.initialPrompt || ''); setUseModel(false); setIncludeContext(false); setView(null);
    const current = new AssistantFlow(latest.current.user, {
      read: path => request(path),
      mutate: (path, method, body) => latest.current.household.mutate(path, method, body),
      refresh: () => latest.current.household.refresh(),
      current: () => active && memberKey(latest.current.user) === actor,
    }, setView);
    setFlow(current); void current.load();
    return () => { active = false; current.close(); };
  }, [actor]));
  useEffect(() => {
    const visibility = (visible: boolean) => { setForeground(visible); flow?.setForeground(visible); };
    const sub = AppState.addEventListener('change', state => visibility(state === 'active'));
    const hidden = () => visibility(!document.hidden);
    const offline = () => visibility(false);
    const online = () => visibility(typeof document === 'undefined' || !document.hidden);
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', hidden);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', online); }
    return () => { sub.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', hidden);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', online); } };
  }, [flow]);
  useEffect(() => {
    if (!view?.search || !foreground || !household.online) return;
    const { query, offset } = view.search;
    const timer = setTimeout(() => { flow?.concealSearch(); void flow?.search(query, offset); }, 10000);
    return () => clearTimeout(timer);
  }, [flow, view?.search, foreground, household.online]);
  useEffect(() => { if (view?.expired) { setPrompt(''); setUseModel(false); setIncludeContext(false); } }, [view?.expired]);

  const locked = !view?.ready || view.busy || view.expired || !foreground || !household.online;
  const editingLocked = locked || !!view?.pending;
  const selected = view?.selected || [], draft = view?.plan, receipt = view?.receipt;
  const changedPrompt = !!draft && prompt.trim() !== view?.planPrompt;
  const people = props.state.people;
  return <View style={styles.page}>
    <PageHeader title="家庭助理" description="整理清单或规划旅行，核对后再保存。" />
    <SectionCard title="今天想处理什么？">
      <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} multiline label="告诉助理你的需求" accessibilityLabel="告诉助理你的需求" value={prompt}
        onChangeText={setPrompt} disabled={editingLocked} maxLength={2000} style={styles.input}
        placeholder="待办：明天预约保洁；确认酒店" />
      <View style={styles.choices}>{['待办：明天预约保洁；确认酒店', '采购：收纳袋；转换插头', '搜索：电池', '看看这周安排'].map(text =>
        <Chip key={text} disabled={editingLocked} onPress={() => { if (!editingLocked) setPrompt(text); }}>{text.startsWith('待办') ? '整理待办' : text.startsWith('采购') ? '准备采购' : text.startsWith('搜索') ? '查找家里物品' : '本周概览'}</Chip>)}</View>
      <SelectionRow label="使用已配置的 AI 整理" checked={useModel} disabled={editingLocked || !view?.modelConfigured}
        onPress={() => { if (!editingLocked && view?.modelConfigured) { setUseModel(!useModel); setIncludeContext(false); } }} />
      {useModel && <><Text variant="bodySmall">本次文字会发送给已配置的 AI 服务。结果是建议，尚未执行。</Text>
        <SelectionRow label="附带近期日程和待办标题" checked={includeContext} disabled={editingLocked}
          onPress={() => { if (!editingLocked) setIncludeContext(!includeContext); }} /></>}
      {!view?.modelConfigured && <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>可直接整理本地待办、采购或搜索已有记录。</Text>}
      <Button mode="contained" loading={!!view?.busy && !view?.pending} disabled={editingLocked || !prompt.trim()}
        onPress={() => {
          if (editingLocked || !prompt.trim()) return;
          if (isJourneyRequest(prompt)) props.onJourney(prompt, useModel, true);
          else void flow?.plan(prompt, useModel, includeContext);
        }}>整理并预览</Button>
      <Text variant="bodySmall">输入“搜索：关键词”可查找当前可见的日程、清单、旅行、家庭物品、照片说明及地点文字；搜索始终只在本地进行。</Text>
    </SectionCard>
    {!!view?.error && <HelperText type="error" accessibilityRole="alert">{view.error}</HelperText>}
    {!!view?.notice && <Text accessibilityLiveRegion="polite">{view.notice}</Text>}
    {!view?.ready && !view?.busy && !view?.expired && <Button onPress={() => void flow?.load()}>重新连接助理</Button>}
    {draft && !view?.expired && <SectionCard title={receipt ? '已保存' : '先核对，再确认'}>
      <Chip compact style={styles.mode}>{draft.mode === 'model' ? 'AI 建议' : '本地整理'}</Chip>
      <Text selectable>{draft.summary}</Text>
      {draft.actions.map((action, index) => <View key={index} style={styles.action}>
        <Checkbox.Android accessibilityLabel={'选择' + action.data.title} status={selected.includes(index) ? 'checked' : 'unchecked'}
          disabled={locked || !!view?.pending || !!receipt} onPress={() => flow?.select(index)} />
        <View style={styles.copy}><Text variant="titleMedium">{action.data.title}</Text>
          <Text variant="bodySmall">{action.kind === 'tasks' ? '待办' : '采购'} · {action.data.owner === 'shared' ? '一起' : people.find(person => person.id === action.data.owner)?.name || '家庭成员'}
            {action.data.due ? ' · ' + action.data.due : ''}{action.kind === 'shopping' ? ' · ' + (action.data.quantity || '1 件') : ''}</Text></View>
      </View>)}
      {changedPrompt && !receipt && <Text>请求文字已修改，请先重新整理并预览。</Text>}
      {!!draft.actions.length && !receipt && !view?.pending && <Button mode="contained" disabled={locked || !selected.length || changedPrompt} onPress={() => void flow?.apply()}>确认保存 {selected.length} 项</Button>}
      {view?.pending && <View style={styles.block}>
        <Text>原确认已锁定 {view.pending.selected.length} 项。先读回核对，不能更换选择或生成另一份计划。</Text>
        <Button mode="outlined" disabled={locked} onPress={() => void flow?.checkOutcome()}>读取最新清单</Button>
        <Button mode="contained" disabled={locked || !view.checkedAfterUnknown} onPress={() => void flow?.apply()}>继续原确认（不会重复创建）</Button>
      </View>}
      {receipt && <View style={styles.block}><Divider /><Text variant="titleMedium">本次已保存 {receipt.created.length} 项</Text>
        {receipt.created.map(item => <Text key={item.id}>{item.kind === 'tasks' ? '待办' : '采购'} · {item.title}</Text>)}
        <View style={styles.choices}>{(['tasks', 'shopping'] as const).filter(kind => receipt.created.some(item => item.kind === kind)).map(kind =>
          <Button key={kind} mode="outlined" onPress={() => props.onNavigate(kind)}>{kind === 'tasks' ? '查看待办' : '查看采购'}</Button>)}</View>
        <Button disabled={locked} onPress={() => void flow?.checkOutcome()}>刷新清单</Button>
      </View>}
    </SectionCard>}
    {view?.search && foreground && household.online && !view.expired && <SectionCard title={`搜索结果 · ${view.search.total} 条`}>
      {!view.search.matches.length && <Text>没有找到当前可见的匹配记录。</Text>}
      {view.search.matches.map(item => <View key={item.kind + ':' + item.id} style={styles.result}>
        <Text variant="titleMedium">{item.title}</Text><Text variant="bodySmall">{({ tasks: '待办', shopping: '采购', events: '日程', trips: '旅行', media: '照片', places: '地点', inventory: '家庭物品' })[item.kind]}</Text>
        {item.kind === 'inventory' && <>
          <Text variant="bodySmall">{inventorySummary(item)}</Text>
          {!!item.location && <Text variant="bodySmall">存放位置：{item.location}</Text>}
          <Button mode="outlined" disabled={locked || !!view.pending} accessibilityLabel={'查看物品 ' + item.title} onPress={() => props.onInventory(item.id)}>查看物品</Button>
        </>}
      </View>)}
      <View style={styles.choices}><Button disabled={locked || view.search.offset === 0} onPress={() => void flow?.search(view.search!.query, Math.max(0, view.search!.offset - 20))}>上一页</Button>
        <Text style={styles.pageNumber}>第 {Math.floor(view.search.offset / 20) + 1} 页</Text>
        <Button disabled={locked || view.search.nextOffset === null} onPress={() => void flow?.search(view.search!.query, view.search!.nextOffset!)}>下一页</Button></View>
      <Text variant="bodySmall">仅显示当前可见的文字，权限变化后会重新读取。</Text>
    </SectionCard>}
    <Button icon="airplane" mode="outlined" disabled={editingLocked} onPress={() => props.onJourney(prompt, useModel, false)}>规划一次旅行</Button>
    <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>草案只保留在本页。离开后不会自动执行；结果不明时，请先在本页核对。</Text>
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 18 }, input: { minHeight: 116 }, choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
  mode: { alignSelf: 'flex-start' }, action: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', paddingVertical: 8 }, copy: { flex: 1, minWidth: 0, gap: 4 },
  block: { gap: 12 }, result: { paddingVertical: 10, gap: 4 }, pageNumber: { flexShrink: 1 } });
