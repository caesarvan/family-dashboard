import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Portal, Text } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import type { HomeLayout } from '../lib/types';
import { checkedLayoutWrite, homeCardNames, homeCards, homeLayoutPayload, HomeLayoutFence, isHomeCard, LayoutDiscarded, LayoutError, LayoutRejected,
  layoutRequest, moveHomeCard, readHomeLayout, rebaseHomeDraft, resetHomeLayout, sameHomeLayout, toggleHomeCard, type LayoutSession } from '../lib/homeLayout';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = { onClose: () => void; onPendingChange?: (message: string | null) => void };
type Model = { base: HomeLayout | null; draft: HomeLayout | null; review: HomeLayout | null; unknown: HomeLayout | null; blocked: boolean };
const empty = (): Model => ({ base: null, draft: null, review: null, unknown: null, blocked: false });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const dirty = (model: Model) => !!model.base && !!model.draft && !sameHomeLayout(model.base, model.draft);

export default function HomeLayoutPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户安排首页" />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState<Model>(empty), live = useRef(model);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState(''), [discard, setDiscard] = useState(false);
  const alive = useRef(false), focused = useRef(false), active = useRef(false), epoch = useRef(0), working = useRef(false), flight = useRef<AbortController | null>(null);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new HomeLayoutFence(props.identityKey));
  const current = (ticket = epoch.current) => alive.current && active.current && focused.current && foreground.current && ticket === epoch.current && online()
    && latest.current.household.online && latest.current.household.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  function notify() {
    latest.current.props.onPendingChange?.(live.current.unknown ? '首页布局的保存结果尚未核对，请先核对当前布局。'
      : working.current ? '正在核对首页布局，请稍等。' : dirty(live.current) ? '首页布局还未保存，请先保存或放弃修改。' : null);
  }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    setVisible(false); setDiscard(false); working.current = false; setBusy(false);
    // Same-identity drafts stay only in memory. Rendering remains hidden until
    // a fresh identity check and layout read complete; uncertain writes never retry.
    if (clear) { live.current = empty(); setModel(live.current); }
    notify();
  }
  function failed(caught: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (caught instanceof LayoutDiscarded) {
      if (caught.message === 'identity') { conceal(true); setError('身份已变化，请重新打开首页。'); void latest.current.household.refresh(); }
      return;
    }
    if (caught instanceof LayoutError && [401, 403].includes(caught.status)) {
      conceal(); setError('身份或权限暂时无法核对，布局已隐藏。'); void latest.current.household.refresh(); return;
    }
    setError(caught instanceof Error ? caught.message : '暂时无法核对首页布局。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    try { await action(ticket, controller.signal); } catch (caught) { failed(caught, ticket); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const guard = <T,>(ticket: number, signal: AbortSignal, operation: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await layoutRequest('/me', signal) as LayoutSession, operation, () => current(ticket));
  async function load(ticket: number, signal: AbortSignal) {
    const result = readHomeLayout(await guard(ticket, signal, () => layoutRequest('/dashboard-layout', signal)));
    if (!current(ticket)) return;
    const previous = live.current;
    if (previous.unknown || previous.blocked || dirty(previous) && previous.base?.revision !== result.revision) install({ review: result, blocked: true });
    else install({ base: result, draft: dirty(previous) && previous.draft ? rebaseHomeDraft(previous.draft, result) : result, review: null, blocked: false });
    if (!latest.current.household.applyLayout(result, props.identityKey)) throw new LayoutDiscarded('identity');
    setVisible(true);
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || !foreground.current || !online() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; void job(load);
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); live.current=empty(); latest.current.props.onPendingChange?.(null); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) { conceal(); setMessage('草稿已暂时隐藏，返回前台并核对身份后恢复。'); } else enter(); };
    const offline = () => { conceal(); setMessage('离线时已隐藏布局，草稿保留在内存；联网后重新核对。'); }, connected = () => enter();
    const app = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); }
    return () => { app.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function edit(change: (draft: HomeLayout) => HomeLayout) {
    if (!current() || working.current || live.current.unknown || live.current.blocked || !live.current.draft) return;
    try { install({ draft: change(live.current.draft) }); setError(''); setMessage(''); } catch (caught) { setError(caught instanceof Error ? caught.message : '暂时无法调整。'); }
  }
  async function save() {
    if (!current() || working.current || live.current.unknown || live.current.blocked || !live.current.draft || !dirty(live.current)) return;
    const intent = homeLayoutPayload(live.current.draft);
    await job(async (ticket, signal) => {
      setMessage('');
      try {
        const result = await checkedLayoutWrite<HomeLayout>(operation => guard(ticket, signal, operation), async csrf => {
          install({ unknown: intent, review: null });
          return readHomeLayout(await layoutRequest('/dashboard-layout', signal, intent, csrf));
        });
        if (!current(ticket)) return;
        if (!latest.current.household.applyLayout(result, props.identityKey)) throw new LayoutDiscarded('identity');
        install({ base: result, draft: result, review: null, unknown: null, blocked: false }); setMessage('首页布局已保存。');
        void latest.current.household.refresh();
      } catch (caught) {
        if (!current(ticket)) return;
        if (caught instanceof LayoutRejected) { install({ unknown: null, blocked: caught.status === 409 }); setError(caught.message); }
        else { if (live.current.unknown) setMessage('保存结果尚未确定。请读取当前布局核对；不会自动重复保存。'); throw caught; }
      }
    });
  }
  function decide(keep: boolean) {
    if (!current() || working.current || !live.current.review) return;
    const latestLayout = live.current.review, original = live.current.unknown || live.current.draft;
    install({ base: latestLayout, draft: keep && original ? rebaseHomeDraft(original, latestLayout) : latestLayout, review: null, unknown: null, blocked: false });
    setError(''); setMessage(keep ? '已保留修改。请再次核对，点击保存后才会应用。' : '已采用刚读取的当前布局。');
    void latest.current.household.refresh();
  }
  function close() {
    if (working.current || live.current.unknown) return;
    if (dirty(live.current)) setDiscard(true); else { latest.current.props.onPendingChange?.(null); latest.current.props.onClose(); }
  }
  const locked = busy || !visible || !!model.unknown || model.blocked;
  const keys = model.draft?.order.filter(isHomeCard) || [], future = model.draft?.order.filter(key => !isHomeCard(key)).length || 0;
  return <View style={styles.screen} testID="home-layout-panel">
    <PageHeader title="安排我的首页" description="调整常用卡片的顺序与显示。只影响你的手机和电脑首页，隐藏不会删除数据。"
      action={<Button accessibilityLabel="关闭首页布局" disabled={busy || !!model.unknown} onPress={close}>返回首页</Button>} />
    {!!message && <Text accessibilityRole="text" testID="home-layout-message">{message}</Text>}
    {!!error && <Text accessibilityRole="alert">{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对首页布局" />}
    {!visible ? <EmptyState title="正在核对本人布局" description="离线或权限未确认时不展示旧草稿。"
      action={<Button disabled={busy || !online()} onPress={() => { if (active.current) void job(load); else enter(); }}>重新读取首页布局</Button>} /> : <>
      {model.unknown && <SectionCard title="先核对保存结果"><View testID="home-layout-unknown" style={styles.stack}>
        <Text>先前请求可能已经保存。下方读取只反映当前状态，不能证明是哪一次请求完成；请核对后决定保留哪一版。</Text>
        <Button mode="contained" disabled={busy} onPress={() => void job(load)}>核对首页保存结果</Button>
      </View></SectionCard>}
      {model.draft && !model.unknown && <SectionCard title={`${keys.filter(key => !model.draft!.hidden.includes(key)).length} 张卡片显示在首页`}
        action={<Button disabled={locked} onPress={() => edit(resetHomeLayout)}>恢复默认布局</Button>}>
        <View accessibilityLabel="首页卡片顺序" style={styles.stack}>{keys.map((key, index) => <View key={key} style={styles.row} testID={`home-layout-card-${key}`}>
          <View style={styles.selection}><SelectionRow label={`${index + 1}. ${homeCardNames[key]}`} accessibilityLabel={`在首页显示：${homeCardNames[key]}`}
            checked={!model.draft!.hidden.includes(key)} disabled={locked} onPress={() => edit(draft => toggleHomeCard(draft, key))} /></View>
          <View style={styles.moves}><Button compact accessibilityLabel={`上移：${homeCardNames[key]}`} disabled={locked || index === 0} contentStyle={styles.touch}
            onPress={() => edit(draft => moveHomeCard(draft, key, -1))}>上移</Button>
            <Button compact accessibilityLabel={`下移：${homeCardNames[key]}`} disabled={locked || index === keys.length - 1} contentStyle={styles.touch}
              onPress={() => edit(draft => moveHomeCard(draft, key, 1))}>下移</Button></View>
        </View>)}</View>
        {!!future && <Text>还有 {future} 个当前版本暂不支持的卡片，其设置将由服务器保留。</Text>}
        <Text>使用显示复选框和上下移按钮调整；首页至少保留一张卡片。</Text>
      </SectionCard>}
      {model.blocked && !model.review && !model.unknown && <Button mode="outlined" disabled={busy} onPress={() => void job(load)}>查看最新首页布局</Button>}
      {model.review && <SectionCard title="刚读取的当前首页"><View testID="home-layout-review" style={styles.stack}>
        {model.review.order.filter(isHomeCard).map((key, index) => <Text key={key}>{index + 1}. {homeCardNames[key]} · {model.review!.hidden.includes(key) ? '已隐藏' : '显示'}</Text>)}
        <Text>版本 {model.review.revision}。保留修改后仍需明确保存，不会自动覆盖。</Text>
        <View style={styles.actions}><Button mode="outlined" disabled={busy} onPress={() => decide(false)}>采用当前布局</Button>
          <Button mode="contained" disabled={busy} onPress={() => decide(true)}>保留我的修改</Button></View>
      </View></SectionCard>}
      {!model.unknown && <View style={styles.actions}><Button mode="contained" disabled={locked || !dirty(model)} onPress={() => void save()}>保存首页布局</Button>
        <Button mode="outlined" disabled={busy} onPress={close}>{dirty(model) ? '放弃修改并返回' : '返回首页'}</Button></View>}
    </>}
    <Portal><Dialog visible={discard && !busy && !model.unknown} onDismiss={() => setDiscard(false)}><Dialog.Title>放弃这次布局修改？</Dialog.Title>
      <Dialog.Content><Text>已保存的首页布局保持不变。</Text></Dialog.Content><Dialog.Actions>
        <Button onPress={() => setDiscard(false)}>继续编辑</Button><Button onPress={() => {
          if (working.current || live.current.unknown) return; install(empty()); setDiscard(false); latest.current.props.onClose();
        }}>确认放弃修改</Button>
      </Dialog.Actions></Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ screen: { gap: 20 }, stack: { gap: 12 }, row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 4 },
  selection: { flexGrow: 1, flexBasis: 180, minWidth: 0 }, moves: { flexDirection: 'row', marginLeft: 'auto' }, touch: { minHeight: 44 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 } });
