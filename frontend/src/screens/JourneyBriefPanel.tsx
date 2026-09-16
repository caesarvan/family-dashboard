import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, HelperText, Text, TextInput, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PhotoReadDiscarded, PhotoReadFence, type PhotoSession } from '../lib/photos';
import { memberKey, type Draft } from '../lib/trips';
import type { Member, Person } from '../lib/types';
import { blankBriefStop, emptyBrief, journeyBriefPlan, journeyBriefRequest, journeyCheckedRead, preparedJourneyDraft, readJourneyBrief, type BriefForm, type BriefStop } from '../lib/journeyBrief';
import { PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

export type JourneyBriefPanelProps = {
  user: Member; people: Person[]; initialPrompt?: string; initialUseModel?: boolean; prepareOnOpen?: boolean;
  onPrepared: (draft: Draft) => void; onCancel: () => void;
};
const front = () => typeof document === 'undefined' || !document.hidden;
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const errorText = (value: unknown) => value instanceof Error ? value.message : '暂时无法整理，请保留输入后重试。';

export default function JourneyBriefPanel(props: JourneyBriefPanelProps) {
  return props.user.role === 'member' ? <BriefWorkspace {...props} /> : <Text>请使用家庭成员账号整理旅行。</Text>;
}
function BriefWorkspace(props: JourneyBriefPanelProps) {
  const household = useHousehold(), theme = useTheme();
  const latest = useRef({ household, props }); latest.current = { household, props };
  // The initial identity remains fixed for the lifetime of this private draft.
  const identity = useRef(household.identityKey).current, actor = useRef(memberKey(props.user)).current;
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), props.user, identity));
  const mounted = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const generation = useRef(0), editing = useRef(0), writing = useRef(false), started = useRef(false), resuming = useRef<number | null>(null);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState<'extract' | 'prepare' | ''>(''), [error, setError] = useState('');
  const [prompt, setPrompt] = useState(props.initialPrompt || ''), promptRef = useRef(prompt);
  const [useModel, setUseModel] = useState(props.initialUseModel === true), modelRef = useRef(useModel);
  const [form, setForm] = useState<BriefForm>(() => emptyBrief(props.initialPrompt || '')), formRef = useRef(form);
  const [hasBrief, setHasBrief] = useState(false), [mode, setMode] = useState<'local' | 'model' | null>(null), [notice, setNotice] = useState('');
  const [stopsOpen, setStopsOpen] = useState(true);
  const sameIdentity = () => latest.current.household.identityKey === identity && memberKey(latest.current.props.user) === actor
    && memberKey(latest.current.household.user) === actor && latest.current.household.user?.role === 'member';
  const current = () => mounted.current && focused.current && active.current && !denied.current && appActive.current
    && sameIdentity() && latest.current.household.online && front() && connected();
  const installForm = (next: BriefForm) => { formRef.current = next; setForm(next); };
  const changed = () => { ++editing.current; setError(''); setNotice(''); };
  function conceal(clear = false) {
    active.current = false; ++generation.current; fence.current.invalidate(); setVisible(false); resuming.current = null;
    if (clear) {
      ++editing.current; promptRef.current = ''; modelRef.current = false; setPrompt(''); setUseModel(false);
      installForm(emptyBrief()); setMode(null); setHasBrief(false); setNotice('');
    }
  }
  function failed(failure: unknown, ticket: number, edit?: number) {
    // A late identity error is not allowed to erase a resumed or newer workspace.
    if (!mounted.current || ticket !== generation.current || edit !== undefined && edit !== editing.current) return;
    if (failure instanceof PhotoReadDiscarded && failure.message !== 'identity') return;
    if (failure instanceof PhotoReadDiscarded || failure instanceof ApiError && [401, 403].includes(failure.status)) {
      conceal(true); denied.current = true; setError('登录身份已变化，已清除简报。请返回助理后重新进入。'); void latest.current.household.refresh(); return;
    }
    if (current()) setError(errorText(failure));
  }
  async function guarded<T>(load: () => Promise<T>, ticket: number, edit?: number) {
    return journeyCheckedRead(fence.current, load, () => current() && ticket === generation.current && (edit === undefined || edit === editing.current));
  }
  async function resume() {
    if (!mounted.current || !focused.current || !appActive.current || denied.current || !sameIdentity() || !front() || !connected() || !latest.current.household.online
      || active.current || resuming.current !== null) return;
    const ticket = ++generation.current; resuming.current = ticket; active.current = true;
    try {
      await guarded(async () => true, ticket);
      if (current() && ticket === generation.current) setVisible(true);
    } catch (failure) { if (ticket === generation.current) { failed(failure, ticket); active.current = false; } }
    finally { if (resuming.current === ticket) resuming.current = null; }
  }
  useEffect(() => {
    mounted.current = true;
    const change = () => { if (!front() || !connected()) conceal(); else void resume(); };
    const subscription = AppState.addEventListener('change', value => { appActive.current = value === 'active'; if (appActive.current) void resume(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', change);
    if (typeof window !== 'undefined') { window.addEventListener('offline', change); window.addEventListener('online', change); }
    return () => {
      mounted.current = false; focused.current = false; active.current = false; ++generation.current; ++editing.current; fence.current.invalidate(); subscription.remove();
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', change);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', change); window.removeEventListener('online', change); }
    };
  }, []);
  useFocusEffect(useCallback(() => { focused.current = true; void resume(); return () => { focused.current = false; conceal(); }; }, []));
  useEffect(() => {
    if (!sameIdentity()) { conceal(true); denied.current = true; setError('登录身份已变化，已清除简报。请返回助理后重新进入。'); }
    else if (!household.online) conceal(); else if (focused.current) void resume();
  }, [household.identityKey, household.online, memberKey(props.user)]);
  // prepareOnOpen is set only by the parent's explicit submit action. It is not a retry policy.
  useEffect(() => {
    if (visible && current() && props.prepareOnOpen && !started.current) { started.current = true; void extract(); }
  }, [visible, props.prepareOnOpen]);

  function editForm(patch: Partial<BriefForm>) {
    if (!current()) return;
    changed(); installForm({ ...formRef.current, ...patch });
  }
  function editStop(index: number, patch: Partial<BriefStop>) {
    editForm({ destinations: formRef.current.destinations.map((row, i) => i === index ? { ...row, ...patch } : row) });
  }
  async function extract() {
    if (!current() || writing.current) return;
    const ticket = generation.current, edit = editing.current, source = promptRef.current;
    let payload: ReturnType<typeof journeyBriefRequest>;
    try { payload = journeyBriefRequest(source, modelRef.current); } catch (failure) { failed(failure, ticket, edit); return; }
    writing.current = true; setBusy('extract'); setError('');
    try {
      const raw = await guarded(() => latest.current.household.mutate<unknown>('/assistant/journey-brief', 'POST', payload), ticket, edit);
      const result = readJourneyBrief(raw, source, formRef.current.memberIds);
      if (!current() || ticket !== generation.current || edit !== editing.current) return;
      installForm(result.form); setHasBrief(true); setMode(result.mode); setNotice(result.notice); setStopsOpen(true);
    } catch (failure) { failed(failure, ticket, edit); }
    finally { writing.current = false; if (mounted.current) setBusy(''); }
  }
  async function prepare() {
    if (!current() || writing.current) return;
    const ticket = generation.current, edit = editing.current, people = latest.current.props.people;
    const peopleKey = JSON.stringify(people.map(person => person.id).sort());
    let payload: ReturnType<typeof journeyBriefPlan>;
    try { payload = journeyBriefPlan(formRef.current, people); } catch (failure) { failed(failure, ticket, edit); return; }
    writing.current = true; setBusy('prepare'); setError('');
    try {
      const raw = await guarded(() => latest.current.household.mutate<unknown>('/journeys/preview', 'POST', payload), ticket, edit);
      const draft = preparedJourneyDraft(raw, people);
      if (!current() || ticket !== generation.current || edit !== editing.current || peopleKey !== JSON.stringify(latest.current.props.people.map(person => person.id).sort())) return;
      // Only the new editable plan crosses this boundary; the preview's signed token is discarded.
      ++editing.current; latest.current.props.onPrepared(draft);
    } catch (failure) { failed(failure, ticket, edit); }
    finally { writing.current = false; if (mounted.current) setBusy(''); }
  }
  function cancel() {
    if (writing.current) return;
    ++editing.current; conceal(true); latest.current.props.onCancel();
  }
  const ready = visible && current();
  const field = (label: string, value: string, change: (value: string) => void, limit = 100, placeholder?: string) => <TextInput
    mode="outlined" dense outlineStyle={{ borderRadius: 8 }} label={label} accessibilityLabel={label} value={value}
    onChangeText={change} disabled={!ready} maxLength={limit * 2} placeholder={placeholder} style={styles.input} />;
  if (!ready) return <View style={styles.page}>
    <PageHeader title="整理旅行简报" />
    {denied.current ? <Text accessibilityRole="alert">{error}</Text> : <Text>联网并返回此页后会重新核对身份，再显示旅行需求。</Text>}
    {!denied.current && household.online && front() && connected() && <ActivityIndicator accessibilityLabel="正在核对简报身份" />}
    <View style={styles.actions}><Button disabled={!!busy} onPress={cancel}>返回助理</Button>
      {!denied.current && <Button disabled={!!busy || !household.online} onPress={() => void resume()}>重新核对身份</Button>}</View>
  </View>;
  return <View style={styles.page} testID="journey-brief-form">
    <PageHeader title="整理旅行简报" description="补齐日期、目的地和预算，再带入旅行编辑。现在还不会保存。" />
    {!!error && <HelperText type="error" accessibilityRole="alert">{error}</HelperText>}
    {!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
    <SectionCard title="原始需求"><View style={styles.fields}>
      <TextInput mode="outlined" outlineStyle={{ borderRadius: 8 }} multiline label="旅行原始需求" accessibilityLabel="旅行原始需求" value={prompt}
        onChangeText={value => { if (!current()) return; changed(); promptRef.current = value; setPrompt(value); if (!hasBrief) installForm({ ...formRef.current, note: value }); }}
        maxLength={4000} placeholder="想去哪里、何时出发、准备花多少……也可以直接填写下方表单。" style={styles.prompt} />
      <SelectionRow label="使用 AI 整理这段文字" checked={useModel} accessibilityLabel="使用 AI 整理这段文字"
        onPress={() => { if (!current()) return; changed(); modelRef.current = !modelRef.current; setUseModel(modelRef.current); }} />
      <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{useModel ? '只把这次原文发送给已配置的 AI，不附带家庭记录或成员信息。结果需要你核对。' : '不使用 AI 时，只提取明确标注的字段；其他内容在下方补齐。'}</Text>
      <Button mode="outlined" loading={busy === 'extract'} disabled={!!busy} onPress={() => void extract()}>{hasBrief ? '按当前文字重新整理' : '整理旅行简报'}</Button>
      {mode && <Text variant="bodySmall">{mode === 'model' ? '本次由 AI 整理，请逐项核对。' : '本次使用本地明确字段整理。'}重新整理成功后才替换下方内容。</Text>}
      {hasBrief && prompt.trim() !== form.note && <Text variant="bodySmall">原文已修改。下方仍是保留的简报；可重新整理，或继续编辑这份简报。</Text>}
    </View></SectionCard>
    <SectionCard title="基本安排"><View style={styles.fields}>
      {field('旅行名称', form.title, title => editForm({ title }))}
      <View style={styles.row}><View style={styles.column}>{field('出发日期', form.start, start => editForm({ start }), 10, 'YYYY-MM-DD')}</View>
        <View style={styles.column}>{field('返程日期', form.end, end => editForm({ end }), 10, 'YYYY-MM-DD')}</View></View>
      <Text variant="labelLarge">出行范围</Text><View style={styles.row} accessibilityRole="radiogroup" accessibilityLabel="出行范围">
        <SelectionRow kind="radio" label="国内旅行" checked={form.international === false} onPress={() => editForm({ international: false })} />
        <SelectionRow kind="radio" label="境外旅行" checked={form.international === true} onPress={() => editForm({ international: true })} />
      </View>
      {field('旅行总预算（元）', form.budget, budget => editForm({ budget }), 14, '待确认')}
      <Text variant="bodySmall">填写人民币家庭总额。未知可暂留空，继续前请确认；0 只用于明确的零预算，不自动换汇。</Text>
      <Text variant="labelLarge">出行成员</Text>
      {props.people.map(person => <SelectionRow key={person.id} label={person.name} accessibilityLabel={'出行成员：' + person.name}
        checked={form.memberIds.includes(person.id)} onPress={() => editForm({ memberIds: form.memberIds.includes(person.id) ? form.memberIds.filter(id => id !== person.id) : [...form.memberIds, person.id] })} />)}
    </View></SectionCard>
    <SectionCard title={`目的地与停留 · ${form.destinations.length}`} action={<Button accessibilityLabel={stopsOpen ? '收起目的地' : '展开目的地'} onPress={() => setStopsOpen(!stopsOpen)}>{stopsOpen ? '收起' : '展开'}</Button>}>
      {stopsOpen ? <View style={styles.fields}>{form.destinations.map((row, index) => <View key={index} style={styles.stop} testID={`journey-brief-stop-${index + 1}`}>
        <Text variant="titleSmall">第 {index + 1} 站</Text>
        <View style={styles.row}><View style={styles.column}>{field(`国家或地区 ${index + 1}`, row.country, country => editStop(index, { country }), 60)}</View>
          <View style={styles.column}>{field(`城市 ${index + 1}`, row.city, city => editStop(index, { city }), 80)}</View></View>
        <View style={styles.row}><View style={styles.column}>{field(`抵达日期 ${index + 1}`, row.arrival, arrival => editStop(index, { arrival }), 10, 'YYYY-MM-DD')}</View>
          <View style={styles.column}>{field(`离开日期 ${index + 1}`, row.departure, departure => editStop(index, { departure }), 10, 'YYYY-MM-DD')}</View></View>
        <Button accessibilityLabel={`移除目的地 ${index + 1}`} disabled={form.destinations.length === 1} onPress={() => editForm({ destinations: form.destinations.filter((_, i) => i !== index) })}>移除这一站</Button>
      </View>)}<Button mode="outlined" icon="plus" accessibilityLabel="添加目的地" disabled={form.destinations.length >= 20}
        onPress={() => editForm({ destinations: [...form.destinations, blankBriefStop()] })}>添加目的地</Button></View>
        : <Text>{form.destinations.map(row => row.city || '待填写城市').join(' → ')}</Text>}
    </SectionCard>
    <Text variant="bodySmall">继续后可修改准备事项、负责人和采购预算。这里不会创建预订、付款或云日历安排。</Text>
    <View style={styles.actions}><Button mode="contained" loading={busy === 'prepare'} disabled={!!busy} onPress={() => void prepare()}>核对并继续编辑</Button>
      <Button disabled={!!busy} onPress={cancel}>返回助理</Button></View>
  </View>;
}
const styles = StyleSheet.create({
  page: { gap: 16, paddingBottom: 24, minWidth: 0 }, fields: { gap: 12 }, prompt: { minHeight: 112 }, input: { width: '100%' },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, column: { flexGrow: 1, flexBasis: 220, minWidth: 0 },
  stop: { gap: 12, paddingBottom: 16 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
});
