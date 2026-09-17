import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Portal, Text } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import type { Preferences } from '../lib/types';
import { checkedPreferenceWrite, PreferenceFence, PreferenceDiscarded, PreferenceError, PreferenceRejected,
  preferenceRequest, readPreferences, preferencesPayload, rebasePreferences, samePreferences, type PreferenceSession, type PreferencePayload } from '../lib/preferences';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = { onClose: () => void; onPendingChange?: (message: string | null) => void };
type Model = { base: Preferences | null; draft: Preferences | null; review: Preferences | null; unknown: PreferencePayload | null; blocked: boolean };
const empty = (): Model => ({ base: null, draft: null, review: null, unknown: null, blocked: false });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const dirty = (model: Model) => !!model.base && !!model.draft && !samePreferences(model.base, model.draft);

export default function AppearancePanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户设置外观" />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef({ household, props }); latest.current = { household, props };
  const [model, setModel] = useState<Model>(empty), live = useRef(model);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState(''), [discard, setDiscard] = useState(false);
  const alive = useRef(false), focused = useRef(false), active = useRef(false), epoch = useRef(0), working = useRef(false), flight = useRef<AbortController | null>(null);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PreferenceFence(props.identityKey));
  const current = (ticket = epoch.current) => alive.current && active.current && focused.current && foreground.current && ticket === epoch.current && online()
    && latest.current.household.online && latest.current.household.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  function notify() {
    latest.current.props.onPendingChange?.(live.current.unknown ? '外观设置的保存结果尚未核对，请先核对当前外观设置。'
      : working.current ? '正在核对外观设置，请稍等。' : dirty(live.current) ? '外观设置还未保存，请先保存或放弃修改。' : null);
  }
  function install(patch: Partial<Model>) { live.current = { ...live.current, ...patch }; setModel(live.current); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null;
    setVisible(false); setDiscard(false); working.current = false; setBusy(false);
    // Same-identity drafts stay only in memory. Rendering remains hidden until
    // a fresh identity check and preference read complete; uncertain writes never retry.
    if (clear) { live.current = empty(); setModel(live.current); }
    notify();
  }
  function failed(caught: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (caught instanceof PreferenceDiscarded) {
      if (caught.message === 'identity') { conceal(true); setError('身份已变化，请重新打开外观设置。'); void latest.current.household.refresh(); }
      return;
    }
    if (caught instanceof PreferenceError && [401, 403].includes(caught.status)) {
      conceal(); setError('身份或权限暂时无法核对，外观设置已隐藏。'); void latest.current.household.refresh(); return;
    }
    setError(caught instanceof Error ? caught.message : '暂时无法核对外观设置。');
  }
  async function job(action: (ticket: number, signal: AbortSignal) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; setWorking(true); setError('');
    try { await action(ticket, controller.signal); } catch (caught) { failed(caught, ticket); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) setWorking(false); }
  }
  const guard = <T,>(ticket: number, signal: AbortSignal, operation: (csrf: string) => Promise<T>) => fence.current.run(
    async () => await preferenceRequest('/me', signal) as PreferenceSession, operation, () => current(ticket));
  async function load(ticket: number, signal: AbortSignal) {
    const result = readPreferences(await guard(ticket, signal, () => preferenceRequest('/preferences', signal)));
    if (!current(ticket)) return;
    const previous = live.current;
    if (previous.unknown || previous.blocked || dirty(previous) && previous.base?.revision !== result.revision) install({ review: result, blocked: true });
    else install({ base: result, draft: dirty(previous) && previous.draft ? rebasePreferences(previous.base!, previous.draft, result) : result, review: null, blocked: false });
    if (!latest.current.household.applyPreferences(result, props.identityKey)) throw new PreferenceDiscarded('identity');
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
    const offline = () => { conceal(); setMessage('离线时已隐藏外观设置，草稿保留在内存；联网后重新核对。'); }, connected = () => enter();
    const app = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); }
    return () => { app.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  function edit(change: (draft: Preferences) => Preferences) {
    if (!current() || working.current || live.current.unknown || live.current.blocked || !live.current.draft) return;
    try { install({ draft: change(live.current.draft) }); setError(''); setMessage(''); } catch (caught) { setError(caught instanceof Error ? caught.message : '暂时无法调整。'); }
  }
  async function save() {
    if (!current() || working.current || live.current.unknown || live.current.blocked || !live.current.draft || !dirty(live.current)) return;
    const intent = preferencesPayload(live.current.base!, live.current.draft);
    await job(async (ticket, signal) => {
      setMessage('');
      try {
        const result = await checkedPreferenceWrite<Preferences>(operation => guard(ticket, signal, operation), async csrf => {
          install({ unknown: intent, review: null });
          return readPreferences(await preferenceRequest('/preferences', signal, intent, csrf));
        });
        if (!current(ticket)) return;
        if (!latest.current.household.applyPreferences(result, props.identityKey)) throw new PreferenceDiscarded('identity');
        install({ base: result, draft: result, review: null, unknown: null, blocked: false }); setMessage('外观设置已保存。');
        void latest.current.household.refresh();
      } catch (caught) {
        if (!current(ticket)) return;
        if (caught instanceof PreferenceRejected) { install({ unknown: null, blocked: caught.status === 409 }); setError(caught.message); }
        else { if (live.current.unknown) setMessage('保存结果尚未确定。请读取当前外观设置核对；不会自动重复保存。'); throw caught; }
      }
    });
  }
  function decide(keep: boolean) {
    if (!current() || working.current || !live.current.review) return;
    const latestPreferences = live.current.review;
    const retained = live.current.unknown ? readPreferences({ ...latestPreferences, ...live.current.unknown.changes })
      : live.current.base && live.current.draft ? rebasePreferences(live.current.base, live.current.draft, latestPreferences) : latestPreferences;
    install({ base: latestPreferences, draft: keep ? retained : latestPreferences, review: null, unknown: null, blocked: false });
    setError(''); setMessage(keep ? samePreferences(retained, latestPreferences) ? '当前设置与你的选择相同，无需再次保存。' : '已保留修改。请再次核对，点击保存后才会应用。' : '已采用刚读取的当前外观设置。');
    void latest.current.household.refresh();
  }
  function close() {
    if (working.current || live.current.unknown) return;
    if (dirty(live.current)) setDiscard(true); else { latest.current.props.onPendingChange?.(null); latest.current.props.onClose(); }
  }
  const locked = busy || !visible || !!model.unknown || model.blocked;
  const describe = (value: Preferences) => `${value.colorMode === 'dark' ? '深色' : '浅色'} · ${value.density === 'compact' ? '紧凑' : '标准'}密度`;
  return <View style={styles.screen} testID="appearance-panel">
    <PageHeader title="我的外观" description="为你的手机和电脑选择显示方式。伴侣和电视保留各自的设置。"
      action={<Button accessibilityLabel="关闭外观设置" disabled={busy || !!model.unknown} onPress={close}>返回更多</Button>} />
    {!!message && <Text testID="appearance-message">{message}</Text>}
    {!!error && <Text accessibilityRole="alert">{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对外观设置" />}
    {!visible ? <EmptyState title="正在核对本人设置" description="离线或身份未确认时隐藏草稿；返回并核对后恢复。"
      action={<Button disabled={busy || !online()} onPress={() => { if (active.current) void job(load); else enter(); }}>重新读取外观设置</Button>} /> : <>
      {model.unknown && <SectionCard title="先核对保存结果"><View testID="appearance-unknown" style={styles.stack}>
        <Text>刚才的请求可能已经保存。读取只能显示当前设置，不能证明是哪一次请求完成；不会自动重复保存。</Text>
        {model.draft && <Text>这次选择：{describe(model.draft)}</Text>}
        <Button mode="contained" disabled={busy} onPress={() => void job(load)}>核对外观保存结果</Button>
      </View></SectionCard>}
      {model.draft && !model.unknown && <>
        <SectionCard title="颜色"><View accessibilityRole="radiogroup" accessibilityLabel="外观颜色" style={styles.stack}>
          <SelectionRow kind="radio" label="浅色" accessibilityLabel="浅色外观" checked={model.draft.colorMode === 'light'} disabled={locked} onPress={() => edit(draft => ({ ...draft, colorMode: 'light' }))} />
          <SelectionRow kind="radio" label="深色" accessibilityLabel="深色外观" checked={model.draft.colorMode === 'dark'} disabled={locked} onPress={() => edit(draft => ({ ...draft, colorMode: 'dark' }))} />
        </View></SectionCard>
        <SectionCard title="内容密度"><View accessibilityRole="radiogroup" accessibilityLabel="显示密度" style={styles.stack}>
          <SelectionRow kind="radio" label="标准 · 留白更充足" accessibilityLabel="标准密度" checked={model.draft.density === 'comfortable'} disabled={locked} onPress={() => edit(draft => ({ ...draft, density: 'comfortable' }))} />
          <SelectionRow kind="radio" label="紧凑 · 更集中地查看内容" accessibilityLabel="紧凑密度" checked={model.draft.density === 'compact'} disabled={locked} onPress={() => edit(draft => ({ ...draft, density: 'compact' }))} />
        </View></SectionCard>
      </>}
      {model.blocked && !model.review && !model.unknown && <Button mode="outlined" disabled={busy} onPress={() => void job(load)}>查看最新外观设置</Button>}
      {model.review && <SectionCard title="刚读取的当前设置"><View testID="appearance-review" style={styles.stack}>
        <Text>{describe(model.review)}</Text><Text>版本 {model.review.revision}。保留修改后仍需明确保存。</Text>
        <View style={styles.actions}><Button mode="outlined" disabled={busy} onPress={() => decide(false)}>采用当前设置</Button>
          <Button mode="contained" disabled={busy} onPress={() => decide(true)}>保留我的修改</Button></View>
      </View></SectionCard>}
      {!model.unknown && <View style={styles.actions}><Button mode="contained" disabled={locked || !dirty(model)} onPress={() => void save()}>保存外观设置</Button>
        <Button mode="outlined" disabled={busy} onPress={close}>{dirty(model) ? '放弃修改并返回' : '返回更多'}</Button></View>}
    </>}
    <Portal><Dialog visible={discard && !busy && !model.unknown} onDismiss={() => setDiscard(false)}><Dialog.Title>放弃这次外观修改？</Dialog.Title>
      <Dialog.Content><Text>已保存的显示设置保持不变。</Text></Dialog.Content><Dialog.Actions>
        <Button onPress={() => setDiscard(false)}>继续编辑</Button><Button onPress={() => {
          if (working.current || live.current.unknown) return; install(empty()); setDiscard(false); latest.current.props.onClose();
        }}>确认放弃修改</Button>
      </Dialog.Actions></Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ screen: { gap: 20 }, stack: { gap: 12 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 } });
