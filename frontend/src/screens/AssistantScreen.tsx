import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { Button, Chip, Divider, HelperText, Text, TextInput, useTheme } from 'react-native-paper';
import { request } from '../lib/api';
import { assistantPlanOptions, assistantTripRequest, isAssistantSearchRequest, isExistingTripChangeRequest, isJourneyRequest, isJourneyStatusRequest, journeySessionKey } from '../lib/assistantJourney';
import type { Draft, Session } from '../lib/trips';
import JourneyBriefPanel from './JourneyBriefPanel';
import TripsScreen from './TripsScreen';
import { AssistantFlow, AssistantState, assistantContentRequest, memberKey, type Match } from '../lib/assistant';
import JourneyDocumentsPanel from './JourneyDocumentsPanel';
import PhotosScreen from './PhotosScreen';
import MapWorkspace from './MapWorkspace';
import { useHousehold } from '../lib/household';
import type { ScreenProps } from '../lib/types';
import { PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import ExistingTripChangePanel from '../components/ExistingTripChangePanel';
import AssistantFinanceQueryPanel from '../components/AssistantFinanceQueryPanel';
import { isAssistantFinanceQuery } from '../lib/assistantFinanceQuery';
import AssistantActionEditor from '../components/AssistantActionEditor';
import { actionDraft, browserPlanStorage, editedAction, type ActionDraft } from '../lib/assistantList';
import { shoppingScheduleText } from '../lib/trips';
import AssistantJourneyStatusPanel from '../components/AssistantJourneyStatusPanel';

function inventorySummary(item: Match) {
  const quantities = [item.onHandQty, item.inTransitQty, item.plannedQty];
  if (!item.unit || !quantities.every(value => Number.isSafeInteger(value) && value! >= 0)) return '打开物品，查看最新库存和到货情况。';
  return `现有 ${item.onHandQty} ${item.unit} · 在途 ${item.inTransitQty} ${item.unit} · 计划 ${item.plannedQty} ${item.unit}`;
}

type JourneyPanel = { kind: 'brief'; key: number; prompt: string; useModel: boolean; prepare: boolean }
  | { kind: 'journey_status'; key: number; prompt: string }
  | { kind: 'finance_query'; key: number; prompt: string; useModel: boolean; modelConfigured: boolean }
  | { kind: 'trip_change'; key: number; prompt: string; useModel: boolean; modelConfigured: boolean }
  | { kind: 'planning'; key: number; draft: Draft }
  | { kind: 'existing'; key: number; id: string }
  | { kind: 'documents'; key: number; id: string; journeyId?: string }
  | { kind: 'media' | 'places'; key: number; id: string };
type SearchReturn = { query: string; offset: number };

export function AssistantScreen(props: ScreenProps) {
  const household = useHousehold();
  return <AssistantEntry key={household.identityKey} {...props} />;
}

function AssistantEntry(props: ScreenProps) {
  const household = useHousehold(), actor = household.identityKey;
  const [panel, setPanel] = useState<JourneyPanel | null>(null), [sourcePrompt, setSourcePrompt] = useState('');
  const [sourceSearch, setSourceSearch] = useState<SearchReturn | undefined>();
  const [visible, setVisible] = useState(false), [gateError, setGateError] = useState('');
  const sequence = useRef(0), focused = useRef(false), generation = useRef(0), ready = useRef(false);
  const latest = useRef(household); latest.current = household;
  const panelRef = useRef(panel); panelRef.current = panel;
  const reschedulePending = useRef(false);
  const documentsPending = useRef(false);
  const segmentsPending = useRef(false);
  const tripImportPending = useRef(false);
  const pendingReschedule = (pending: boolean) => { reschedulePending.current = pending; props.onReschedulePending?.(pending); };
  const pendingDocuments = useCallback((pending: boolean) => { documentsPending.current = pending; props.onDocumentsPending?.(pending); }, [props.onDocumentsPending]);
  const pendingSegments = useCallback((pending: boolean) => { segmentsPending.current = pending; props.onSegmentsPending?.(pending); }, [props.onSegmentsPending]);
  const pendingTripImport = useCallback((pending: boolean) => { tripImportPending.current = pending; props.onTripImportPending?.(pending); }, [props.onTripImportPending]);
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
        setPanel(null); setSourcePrompt(''); setSourceSearch(undefined); void latest.current.refresh(); return;
      }
      ready.current = true; setVisible(true); setGateError('');
    } catch {
      if (ticket === generation.current && available()) setGateError('连接暂时无法核对，旅行草稿已隐藏。请重试。');
    }
  }
  useFocusEffect(useCallback(() => {
    focused.current = true;
    return () => { focused.current = false; conceal(); if (panelRef.current?.kind !== 'finance_query' && panelRef.current?.kind !== 'journey_status' && !reschedulePending.current && !documentsPending.current && !segmentsPending.current && !tripImportPending.current) { setPanel(null); setSourcePrompt(''); setSourceSearch(undefined); } };
  }, [actor]));
  useEffect(() => {
    if (!panel || panel.kind === 'finance_query' || panel.kind === 'journey_status') return;
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
    setSourcePrompt(prompt); setSourceSearch(undefined);
    setPanel({ kind: 'brief', key: ++sequence.current, prompt, useModel, prepare });
  };
  const beginTripChange = (prompt: string, useModel: boolean, modelConfigured: boolean) => {
    if (!available() || panelRef.current) return;
    setSourcePrompt(prompt); setSourceSearch(undefined);
    const next: JourneyPanel = { kind: 'trip_change', key: ++sequence.current, prompt, useModel, modelConfigured };
    panelRef.current = next; setPanel(next);
  };
  const beginFinanceQuery = (prompt: string, useModel: boolean, modelConfigured: boolean) => {
    if (!available() || panelRef.current) return;
    setSourcePrompt(prompt); setSourceSearch(undefined);
    const next: JourneyPanel = { kind: 'finance_query', key: ++sequence.current, prompt, useModel, modelConfigured };
    panelRef.current = next; setPanel(next);
  };
  const beginJourneyStatus = (prompt: string) => {
    if (!available() || panelRef.current) return;
    setSourcePrompt(prompt); setSourceSearch(undefined);
    const next: JourneyPanel = { kind: 'journey_status', key: ++sequence.current, prompt };
    panelRef.current = next; setPanel(next);
  };
  const openExisting = (match: Match, prompt: string, search: SearchReturn) => {
    if (!available() || panelRef.current) return;
    const target = assistantTripRequest(match, sequence.current + 1);
    if (!target) return;
    sequence.current = target.key;
    setSourcePrompt(prompt); setSourceSearch({ query: search.query, offset: search.offset });
    const next: JourneyPanel = { kind: 'existing', ...target };
    panelRef.current = next; setPanel(next);
  };
  const openContent = (match: Match, prompt: string, search: SearchReturn) => {
    if (!available() || panelRef.current) return;
    const next = assistantContentRequest(match, sequence.current + 1);
    if (!next) return;
    sequence.current = next.key; setSourcePrompt(prompt); setSourceSearch({ query: search.query, offset: search.offset });
    panelRef.current = next; setPanel(next);
  };
  if (!panel) return <AssistantWorkspace {...props} initialPrompt={sourcePrompt} initialSearch={sourceSearch}
    onJourney={begin} onTripChange={beginTripChange} onFinanceQuery={beginFinanceQuery} onJourneyStatus={beginJourneyStatus} onExistingTrip={openExisting} onContent={openContent} />;
  if (panel.kind === 'journey_status') return <AssistantJourneyStatusPanel key={panel.key} initialPrompt={panel.prompt} screenProps={props}
    onBack={prompt => { if (available()) { setSourcePrompt(prompt); panelRef.current = null; setPanel(null); } }} />;
  if (panel.kind === 'finance_query') return <AssistantFinanceQueryPanel key={panel.key} initialPrompt={panel.prompt} initialUseModel={panel.useModel} modelConfigured={panel.modelConfigured} screenProps={props}
    onBack={prompt => { if (available()) { setSourcePrompt(prompt); panelRef.current = null; setPanel(null); } }} />;
  if (panel.kind === 'documents') return <JourneyDocumentsPanel key={panel.key} journeyId={panel.journeyId} initialDocumentId={panel.id} onPendingChange={pendingDocuments}
    onBack={() => { if (available() && panelRef.current?.key === panel.key && !documentsPending.current) { panelRef.current = null; setPanel(null); } }} />;
  if (panel.kind === 'media') return <PhotosScreen {...props} key={panel.key} initialPhotoId={panel.id}
    onBack={() => { if (available() && panelRef.current?.key === panel.key) { panelRef.current = null; setPanel(null); } }} />;
  if (panel.kind === 'places') return <MapWorkspace {...props} key={panel.key} initialPlaceId={panel.id}
    onBack={() => { if (available() && panelRef.current?.key === panel.key) { panelRef.current = null; setPanel(null); } }} />;
  const allowed = visible && household.online;
  return <View>
    {!allowed && <SectionCard title="旅行草稿暂时隐藏">
      <Text>{gateError || '返回前台并连接网络后，核对当前登录再继续。'}</Text>
      <Button onPress={() => void verify()}>重新连接旅行</Button>
    </SectionCard>}
    <View style={allowed ? undefined : { display: 'none' }}>
      {panel.kind === 'trip_change' ? <ExistingTripChangePanel key={panel.key} initialPrompt={panel.prompt} initialUseModel={panel.useModel} modelConfigured={panel.modelConfigured}
        onPendingChange={pendingReschedule}
        onBack={prompt => { if (ready.current && available() && !reschedulePending.current) { setSourcePrompt(prompt); setPanel(null); } }}
        onSaved={id => {
          if (!ready.current || !available() || reschedulePending.current || panelRef.current?.key !== panel.key) return;
          void latest.current.refresh(); setPanel({ kind: 'existing', key: ++sequence.current, id });
        }} />
        : panel.kind === 'brief' ? <JourneyBriefPanel key={panel.key} user={props.user} people={props.state.people}
        initialPrompt={panel.prompt} initialUseModel={panel.useModel} prepareOnOpen={panel.prepare}
        onCancel={() => { if (ready.current && available()) setPanel(null); }}
        onPrepared={draft => {
          if (!ready.current || !available() || panelRef.current?.key !== panel.key || panelRef.current.kind !== 'brief') return;
          setPanel({ kind: 'planning', key: ++sequence.current, draft });
        }} />
        : <TripsScreen {...props} key={panel.key} tripRequest={panel.kind === 'existing' ? { key: panel.key, id: panel.id } : undefined}
          initialDraft={panel.kind === 'planning' ? panel.draft : undefined} onReschedulePending={pendingReschedule} onDocumentsPending={pendingDocuments} onSegmentsPending={pendingSegments} onTripImportPending={pendingTripImport}
          onExitPlanning={() => {
            if (ready.current && available() && panelRef.current?.key === panel.key && !reschedulePending.current
              && !documentsPending.current && !segmentsPending.current && !tripImportPending.current) setPanel(null);
          }} />}
    </View>
  </View>;
}

function AssistantWorkspace(props: ScreenProps & {
  initialPrompt?: string; initialSearch?: SearchReturn; onJourney: (prompt: string, useModel: boolean, prepare: boolean) => void;
  onTripChange: (prompt: string, useModel: boolean, modelConfigured: boolean) => void;
  onFinanceQuery: (prompt: string, useModel: boolean, modelConfigured: boolean) => void;
  onJourneyStatus: (prompt: string) => void;
  onExistingTrip: (match: Match, prompt: string, search: SearchReturn) => void;
  onContent: (match: Match, prompt: string, search: SearchReturn) => void;
}) {
  const household = useHousehold(), theme = useTheme();
  const latest = useRef({ household, user: props.user }); latest.current = { household, user: props.user };
  const [flow, setFlow] = useState<AssistantFlow | null>(null);
  const [view, setView] = useState<AssistantState | null>(null);
  const [prompt, setPrompt] = useState(''), [useModel, setUseModel] = useState(false), [includeContext, setIncludeContext] = useState(false);
  const [foreground, setForeground] = useState(true);
  const [editor, setEditor] = useState<{ index: number; draft: ActionDraft } | null>(null), [editError, setEditError] = useState('');
  const actor = memberKey(props.user);
  useFocusEffect(useCallback(() => {
    let active = true;
    setPrompt(props.initialPrompt || ''); setUseModel(false); setIncludeContext(false); setView(null); setEditor(null); setEditError('');
    const current = new AssistantFlow(latest.current.user, {
      read: path => request(path),
      mutate: (path, method, body) => latest.current.household.mutate(path, method, body),
      refresh: () => latest.current.household.refresh(),
      current: () => active && memberKey(latest.current.user) === actor,
      storage: browserPlanStorage(),
    }, setView);
    const available = latest.current.household.online && (typeof navigator === 'undefined' || navigator.onLine !== false)
      && (typeof document === 'undefined' || !document.hidden);
    setForeground(available); current.setForeground(available);
    setFlow(current); void current.load().then(() => {
      if (active && current.state.ready && !current.state.expired && latest.current.household.online
        && (typeof document === 'undefined' || !document.hidden) && (typeof navigator === 'undefined' || navigator.onLine !== false)
        && props.initialSearch) void current.search(props.initialSearch.query, props.initialSearch.offset);
    });
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
  useEffect(() => { if (view?.expired) { setPrompt(''); setUseModel(false); setIncludeContext(false); setEditor(null); } }, [view?.expired]);

  const shown = !!view?.visible && foreground && household.online && !view.expired;
  const locked = !view?.ready || view.busy || !shown;
  const editingLocked = locked || !!view?.pending || !!view?.needsReview || !!view?.unavailable || !!editor;
  const localSearch = isAssistantSearchRequest(prompt);
  const financeQuery = isAssistantFinanceQuery(prompt);
  const tripChange = isExistingTripChangeRequest(prompt);
  const journeyStatus = !financeQuery && isJourneyStatusRequest(prompt);
  const selected = view?.selected || [], draft = view?.plan, receipt = view?.receipt;
  const changedPrompt = !!draft && prompt.trim() !== view?.planPrompt;
  const people = props.state.people;
  return <View style={styles.page}>
    <PageHeader title="家庭助理" description="查询预算支出、找地点和资料照片、整理清单或规划旅行。" />
    {!shown && <SectionCard title="助理内容已隐藏"><Text>{view?.expired ? view.error : '请联网并核对当前身份后继续。本页草稿不会自动提交。'}</Text>
      {!view?.expired && <Button disabled={!!view?.busy || !foreground || !household.online} onPress={() => void flow?.load()}>核对身份并继续</Button>}
    </SectionCard>}
    {shown && <SectionCard title="今天想处理什么？">
      <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} multiline label="告诉助理你的需求" accessibilityLabel="告诉助理你的需求" value={prompt}
        onChangeText={setPrompt} disabled={editingLocked} maxLength={2000} style={styles.input}
        placeholder="待办：明天预约保洁；确认酒店" />
      <View style={styles.choices}>{['待办：明天预约保洁；确认酒店', '采购：收纳袋；转换插头', '搜索：电池', '搜索：旅行凭证', '本月花了多少', '看看这周安排'].map(text =>
        <Chip key={text} disabled={editingLocked} onPress={() => { if (!editingLocked) setPrompt(text); }}>{text.startsWith('待办') ? '整理待办' : text.startsWith('采购') ? '准备采购' : text === '搜索：旅行凭证' ? '找资料照片' : text.startsWith('搜索') ? '查找家里物品' : text === '本月花了多少' ? '查询支出' : '本周概览'}</Chip>)}</View>
      <SelectionRow label="使用已配置的 AI 整理" checked={useModel} disabled={editingLocked || !view?.modelConfigured}
        onPress={() => { if (!editingLocked && view?.modelConfigured) { setUseModel(!useModel); setIncludeContext(false); } }} />
      {(localSearch || journeyStatus) && <Text variant="bodySmall">本次只查找已有记录，不会发送给 AI。</Text>}
      {useModel && !localSearch && !journeyStatus && <><Text variant="bodySmall">{financeQuery ? '仅本次问题文字发送给 AI；不会附带账本、预算金额或家庭资料。' : tripChange ? '本次文字及必要候选的旅行标题、日期、时区会发送给已配置的 AI。结果是建议，尚未改期。' : '本次文字会发送给已配置的 AI 服务。结果是建议，尚未执行。'}</Text>
        {!tripChange && !financeQuery && <SelectionRow label="附带近期日程和待办标题" checked={includeContext} disabled={editingLocked}
          onPress={() => { if (!editingLocked) setIncludeContext(!includeContext); }} />}</>}
      {!view?.modelConfigured && <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>可直接查询预算支出、整理本地待办采购或搜索已有记录。</Text>}
      <Button mode="contained" loading={!!view?.busy && !view?.pending} disabled={editingLocked || !prompt.trim()}
        onPress={() => {
          if (editingLocked || !prompt.trim()) return;
          if (isAssistantFinanceQuery(prompt)) props.onFinanceQuery(prompt, useModel, !!view?.modelConfigured);
          else if (isExistingTripChangeRequest(prompt)) props.onTripChange(prompt, useModel, !!view?.modelConfigured);
          else if (isJourneyStatusRequest(prompt)) props.onJourneyStatus(prompt);
          else if (isJourneyRequest(prompt)) props.onJourney(prompt, useModel, true);
          else {
            const options = assistantPlanOptions(prompt, useModel, includeContext);
            void flow?.plan(prompt, options.useModel, options.includeHouseholdContext);
          }
        }}>{financeQuery || journeyStatus ? '查询' : '整理并预览'}</Button>
      <Button testID="assistant-journey-status-entry" mode="outlined" disabled={editingLocked} onPress={() => { if (!editingLocked) props.onJourneyStatus(prompt); }}>查询旅行准备情况</Button>
      <Text variant="bodySmall">输入“搜索 关键词”“查找关键词”或“找一下关键词”可查找当前可见的记录；搜索始终只在本地进行。</Text>
      <Text variant="bodySmall">资料可按标题、文件名或关联旅行查找；照片可按说明或关联旅行查找。</Text>
    </SectionCard>}
    {shown && !!view?.error && <HelperText type="error" accessibilityRole="alert">{view.error}</HelperText>}
    {shown && !!view?.notice && <Text accessibilityLiveRegion="polite">{view.notice}</Text>}
    {!view?.ready && !view?.busy && !view?.expired && <Button onPress={() => void flow?.load()}>重新连接助理</Button>}
    {shown && draft && <SectionCard title={receipt ? '已保存' : '先核对，再确认'}>
      {!receipt && <><Chip compact style={styles.mode}>{draft.mode === 'model' ? 'AI 建议' : '本地整理'}</Chip>
        <Text selectable>{draft.summary}</Text></>}
      {!receipt && draft.actions.map((action, index) => {
        const data = view.edits[index] || action.data;
        return <View key={index} testID={'assistant-list-action-' + index} style={styles.block}>
          <View style={styles.action}><View style={styles.copy}>
            <SelectionRow accessibilityLabel={'选择' + data.title} label={data.title} checked={selected.includes(index)}
              disabled={editingLocked || !!receipt} onPress={() => flow?.select(index)} />
            <Text variant="bodySmall">{action.kind === 'tasks' ? '待办' : '采购'} · {data.owner === 'shared' ? '一起' : people.find(person => person.id === data.owner)?.name || '家庭成员'}
              {action.kind === 'shopping' ? ' · ' + (data.quantity || '1 件') : data.due ? ' · ' + data.due : ''}</Text>
            {action.kind === 'shopping' && <Text variant="bodySmall">{shoppingScheduleText(data, '', true)} · {data.budget == null ? '未设预算' : '预算 ¥' + (data.budget / 100).toFixed(2)}</Text>}
            {!!data.note && <Text variant="bodySmall">{data.note}</Text>}
          </View>{!receipt && <Button testID={'action-edit-' + index} accessibilityLabel={'调整第' + (index + 1) + '项'} disabled={editingLocked}
            onPress={() => { setEditor({ index, draft: actionDraft({ kind: action.kind, data }) }); setEditError(''); }}>调整</Button>}</View>
          {editor?.index === index && <AssistantActionEditor kind={action.kind} draft={editor.draft} people={people} disabled={locked}
            error={editError} onChange={patch => { setEditor({ ...editor, draft: { ...editor.draft, ...patch } }); setEditError(''); }}
            onCancel={() => { setEditor(null); setEditError(''); }} onSave={() => {
              try { flow?.edit(index, editedAction(action.kind, editor.draft, people.map(person => person.id))); setEditor(null); setEditError(''); }
              catch (failure) { setEditError(failure instanceof Error ? failure.message : '请核对输入。'); }
            }} />}
        </View>;
      })}
      {changedPrompt && !receipt && <Text>请求文字已修改，请先重新整理并预览。</Text>}
      {!!draft.actions.length && !receipt && <Text variant="bodySmall">保存到家庭共享清单。负责人只表示分工，不限制家人查看；不会下单、扣款或自动写入云端。</Text>}
      {view.needsReview && <Button testID="assistant-list-review" disabled={locked || view.unavailable} onPress={() => flow?.reviewDraft()}>核对原草案</Button>}
      {!!draft.actions.length && !receipt && !view?.pending && <Button testID="assistant-list-apply" mode="contained" disabled={editingLocked || !selected.length || changedPrompt} onPress={() => void flow?.apply()}>确认保存 {selected.length} 项</Button>}
      {view?.pending && <View testID="assistant-list-unknown" style={styles.block}>
        <Text>原确认已锁定 {view.pending.selected.length} 项。先读回核对，不能更换选择或生成另一份计划。</Text>
        <Button testID="assistant-list-recheck" mode="outlined" disabled={locked} onPress={() => void flow?.checkOutcome()}>核对保存结果</Button>
        <Button mode="contained" disabled={locked || view.unavailable || !view.checkedAfterUnknown} onPress={() => void flow?.apply()}>继续原确认（不会重复创建）</Button>
        {view.checkedAfterUnknown && <Button disabled={locked || view.unavailable} onPress={() => flow?.reviewDraft()}>重新核对原草案</Button>}
      </View>}
      {receipt && <View testID="assistant-list-receipt" style={styles.block}><Divider /><Text variant="titleMedium">本次已保存 {receipt.created.length} 项</Text>
        {receipt.created.map(item => <Text key={item.id}>{item.kind === 'tasks' ? '待办' : '采购'} · {item.title}</Text>)}
        <View style={styles.choices}>{(['tasks', 'shopping'] as const).filter(kind => receipt.created.some(item => item.kind === kind)).map(kind =>
          <Button key={kind} mode="outlined" onPress={() => props.onNavigate(kind)}>{kind === 'tasks' ? '查看待办' : '查看采购'}</Button>)}</View>
        <Button disabled={locked} onPress={() => void flow?.checkOutcome()}>刷新清单</Button>
      </View>}
    </SectionCard>}
    {shown && view?.unavailable && <SectionCard title="结束原计划核对"><Text>请先查看清单，确认是否已有之前保存的事项。此操作只清除本页恢复标识，不撤销已经保存的事项。</Text>
      <View style={styles.choices}><Button onPress={() => props.onNavigate('tasks')}>查看待办</Button><Button onPress={() => props.onNavigate('shopping')}>查看采购</Button></View>
      <Button testID="assistant-list-new-after-review" mode="outlined" disabled={locked} onPress={() => { flow?.startAfterReview(); setPrompt(''); setEditor(null); }}>已核对清单，开始新计划</Button>
    </SectionCard>}
    {shown && view?.recoveryId && !view.pending && !receipt && <Button testID="assistant-list-recheck" disabled={locked} onPress={() => void flow?.checkOutcome()}>核对原计划</Button>}
    {shown && view?.search && <SectionCard title={`搜索结果 · ${view.search.total} 条`}>
      {!view.search.matches.length && <Text>没有找到当前可见的匹配记录。</Text>}
      {view.search.matches.map(item => <View key={item.kind + ':' + item.id} testID={'assistant-search-' + item.kind + '-' + item.id} style={styles.result}>
        <Text variant="titleMedium">{item.title}</Text><Text variant="bodySmall">{({ tasks: '待办', shopping: '采购', events: '日程', trips: '旅行', media: '照片', places: '地点', inventory: '家庭物品', documents: '资料' })[item.kind]}</Text>
        {(item.kind === 'documents' || item.kind === 'media' || item.kind === 'places') && <>
          {item.kind === 'documents' && <Text variant="bodySmall">{item.filename}</Text>}
          <Text variant="bodySmall">{item.visibility === 'shared' ? '家庭共享' : '仅本人'} · {item.journey?.title || '未关联旅行'}</Text>
          {!!assistantContentRequest(item, 1) && <Button mode="outlined" contentStyle={{ minHeight: 44 }} disabled={editingLocked}
            accessibilityLabel={(item.kind === 'documents' ? '查看资料 ' : item.kind === 'places' ? '查看地点 ' : '查看照片 ') + item.title} onPress={() => {
              const current = flow?.state;
              if (editingLocked || !current?.ready || current.busy || current.expired || current.pending || !current.search) return;
              const latestMatch = current.search.matches.find(match => match.kind === item.kind && match.id === item.id);
              if (latestMatch) props.onContent(latestMatch, prompt, { query: current.search.query, offset: current.search.offset });
            }}>{item.kind === 'documents' ? '查看资料' : item.kind === 'places' ? '在地图查看' : '查看照片'}</Button>}
        </>}
        {item.kind === 'inventory' && <>
          <Text variant="bodySmall">{inventorySummary(item)}</Text>
          {!!item.location && <Text variant="bodySmall">存放位置：{item.location}</Text>}
          <Button mode="outlined" disabled={locked || !!view.pending} accessibilityLabel={'查看物品 ' + item.title} onPress={() => props.onInventory(item.id)}>查看物品</Button>
        </>}
        {item.kind === 'trips' && assistantTripRequest(item, 1) && <Button mode="outlined" contentStyle={{ minHeight: 44 }}
          disabled={editingLocked} accessibilityLabel={'查看旅行 ' + item.title} onPress={() => {
            const current = flow?.state;
            if (editingLocked || !current?.ready || current.busy || current.expired || current.pending || !current.search
              || !current.search.matches.some(match => match.kind === 'trips' && match.id === item.id)) return;
            props.onExistingTrip(item, prompt, { query: current.search.query, offset: current.search.offset });
          }}>查看旅行</Button>}
      </View>)}
      <View style={styles.choices}><Button disabled={locked || view.search.offset === 0} onPress={() => void flow?.search(view.search!.query, Math.max(0, view.search!.offset - 20))}>上一页</Button>
        <Text style={styles.pageNumber}>第 {Math.floor(view.search.offset / 20) + 1} 页</Text>
        <Button disabled={locked || view.search.nextOffset === null} onPress={() => void flow?.search(view.search!.query, view.search!.nextOffset!)}>下一页</Button></View>
      <Text variant="bodySmall">仅显示当前可见的文字，权限变化后会重新读取。</Text>
    </SectionCard>}
    <Button icon="airplane" mode="outlined" disabled={editingLocked} onPress={() => props.onJourney(prompt, useModel, false)}>规划一次旅行</Button>
    <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>修改只保留在本页；刷新只恢复原计划编号，再核对保存结果。不会自动执行。</Text>
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 18 }, input: { minHeight: 116 }, choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
  mode: { alignSelf: 'flex-start' }, action: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', paddingVertical: 8 }, copy: { flex: 1, minWidth: 0, gap: 4 },
  block: { gap: 12 }, result: { paddingVertical: 10, gap: 4 }, pageNumber: { flexShrink: 1 } });
