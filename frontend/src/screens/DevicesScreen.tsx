import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, ScrollView, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Portal, Text, TextInput, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import type { ScreenProps } from '../lib/types';
import { checkedDeviceMutation, defaultDeviceLayout, DeviceDiscarded, DeviceFence, DeviceWriteRejected, deviceCardNames, deviceDraft, devicePayload, moveDeviceCard, pairPayload, playbackPayload, readDevices, readPlayback, sameDeviceSettings, toggleDeviceCard, type Device, type DeviceDraft, type DeviceIntent, type DeviceSession, type PairDraft, type Playback, type PlaybackAction } from '../lib/devices';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = ScreenProps & { onDevicePending?: (message: string | null) => void };
type Model = { devices: Device[]; view: 'list' | 'pair' | 'settings' | 'playback'; selected: Device | null; draft: DeviceDraft | null;
  pair: PairDraft; playback: Playback | null; interval: string; review: Device | null; blocked: boolean; unknown: DeviceIntent | null; checked: boolean };
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const errorText = (failure: unknown) => failure instanceof Error ? failure.message : '暂时无法核对电视，请稍后重试。';
async function deviceRequest<T>(path: string, options: RequestInit = {}, csrf = ''): Promise<T> {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
  try { return await request<T>(path, { ...options, signal: controller.signal }, csrf); }
  finally { clearTimeout(timer); }
}
const views = [{ id: 'today', name: '今天' }, { id: 'week', name: '本周' }, { id: 'around', name: '前后3天' }] as const;
const themes = [{ id: 'light', name: '晴日' }, { id: 'forest', name: '森林' }, { id: 'ocean', name: '海岸' }] as const;
const densities = [{ id: 'comfortable', name: '舒适' }, { id: 'compact', name: '紧凑' }] as const;
const freshModel = (focus: string): Model => ({ devices: [], view: 'list', selected: null, draft: null,
  pair: { code: '', name: '', focus, calendarView: 'today' }, playback: null, interval: '10', review: null, blocked: false, unknown: null, checked: false });
function dirty(value: Model) {
  return value.view === 'settings' && !!value.draft && !!value.selected && !sameDeviceSettings(value.draft, value.selected)
    || value.view === 'pair' && !!(value.pair.code || value.pair.name)
    || value.view === 'playback' && !!value.playback && value.interval !== String(value.playback.intervalSeconds);
}
function pendingMessage(value: Model, busy: boolean): string | null {
  if (value.unknown) return '电视操作结果尚未核对，请先核对当前状态。';
  if (busy) return '正在核对电视，请稍等。';
  if (dirty(value)) return '电视设置还未保存，请先保存或明确放弃修改。';
  return null;
}
export default function DevicesScreen(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户管理电视" />;
  return <Workspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const alive = useRef(false), focused = useRef(false), active = useRef(false), epoch = useRef(0), working = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new DeviceFence(() => deviceRequest<DeviceSession>('/me'), props.identityKey));
  const [model, setModel] = useState<Model>(() => freshModel(props.user.id)), live = useRef(model);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [dialog, setDialog] = useState<'discard' | 'revoke' | null>(null);
  const current = (ticket = epoch.current) => alive.current && active.current && focused.current && foreground.current && ticket === epoch.current
    && online() && latest.current.household.online && latest.current.household.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  const notify = () => latest.current.props.onDevicePending?.(pendingMessage(live.current, working.current));
  function install(patch: Partial<Model>) { const next = { ...live.current, ...patch }; live.current = next; setModel(next); notify(); }
  function setWorking(value: boolean) { working.current = value; setBusy(value); notify(); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); setVisible(false); setDialog(null); setWorking(false);
    if (clear) { const next = freshModel(props.user.id); live.current = next; setModel(next); notify(); setNotice(''); }
  }
  function failure(caught: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (caught instanceof DeviceDiscarded) {
      if (caught.message === 'identity') { conceal(true); setError('登录身份已变化，请重新进入电视管理。'); void latest.current.household.refresh(); }
      return;
    }
    if (caught instanceof ApiError && [401, 403].includes(caught.status)) {
      conceal(); setError('身份或权限暂时无法核对，电视内容已隐藏。请重新核对。'); void latest.current.household.refresh(); return;
    }
    setError(errorText(caught));
  }
  const guarded = <T,>(job: (csrf: string) => Promise<T>, ticket: number) => fence.current.run(job, () => current(ticket));
  async function list(ticket: number) { return readDevices(await guarded(() => deviceRequest<unknown>('/devices'), ticket)); }
  async function playback(id: string, ticket: number) { return readPlayback(await guarded(() => deviceRequest<unknown>('/media-playback/devices/' + id), ticket), id); }
  async function reload(ticket: number, explicit = false) {
    const rows = await list(ticket), state = live.current, selected = rows.find(row => row.id === state.selected?.id) || null;
    let play: Playback | null = null;
    if (state.view === 'playback' && selected) play = await playback(selected.id, ticket);
    if (!current(ticket)) return;
    const patch: Partial<Model> = { devices: rows };
    if (state.selected && !selected) {
      Object.assign(patch, { view: 'list', selected: null, draft: null, playback: null, review: null, blocked: false });
      setNotice('这台电视不在当前有效设备列表中；可能已撤销或到期。');
    } else if (state.view === 'settings' && selected) {
      if (selected.revision !== state.selected?.revision || explicit) Object.assign(patch, { review: selected, blocked: true });
    } else if (state.view === 'playback' && selected && play) {
      Object.assign(patch, { selected, playback: play, interval: dirty(state) ? state.interval : String(play.intervalSeconds) });
    }
    install(patch);
  }
  async function readJob(job: (ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current; setWorking(true); setError('');
    try { await job(ticket); } catch (caught) { failure(caught, ticket); }
    finally { if (current(ticket)) setWorking(false); }
  }
  function enter() {
    if (!alive.current || active.current || !focused.current || !foreground.current || !online() || !latest.current.household.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; const ticket = epoch.current; setWorking(true);
    void (async () => {
      try { await reload(ticket); if (current(ticket)) { setVisible(true); setError(''); } }
      catch (caught) { failure(caught, ticket); if (current(ticket)) conceal(); }
      finally { if (current(ticket)) setWorking(false); }
    })();
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); latest.current.props.onDevicePending?.(null); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); };
    const offline = () => { conceal(); setError('离线时隐藏设备内容，联网后重新核对。'); }, connected = () => enter();
    const subscription = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility); if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  useEffect(() => {
    const timer = setInterval(() => {
      const state = live.current;
      if (visible && current() && !working.current && !state.unknown && !dirty(state) && (state.view === 'list' || state.view === 'playback')) void readJob(ticket => reload(ticket));
    }, 10000);
    return () => clearInterval(timer);
  }, [visible]);
  const locked = busy || !!model.unknown || !visible;
  const people = [...props.state.people, { id: 'shared', name: '共同' }];
  const focusName = (id: string) => people.find(person => person.id === id)?.name || '成员';
  function edit(patch: Partial<DeviceDraft>) { if (!current() || locked || !live.current.draft) return; install({ draft: { ...live.current.draft, ...patch } }); }
  function editPair(patch: Partial<PairDraft>) { if (current() && !locked) install({ pair: { ...live.current.pair, ...patch } }); }
  function toList() {
    if (working.current || live.current.unknown) return;
    install({ view: 'list', selected: null, draft: null, playback: null, review: null, blocked: false, pair: freshModel(props.user.id).pair }); setDialog(null); setError('');
  }
  function back() { if (!current() || working.current || live.current.unknown) return; if (dirty(live.current)) setDialog('discard'); else toList(); }
  function open(id: string, view: 'settings' | 'playback') {
    if (locked) return;
    void readJob(async ticket => {
      const rows = await list(ticket), device = rows.find(row => row.id === id);
      if (!device) { install({ devices: rows }); throw new Error('电视已撤销或到期，请重新配对。'); }
      const play = view === 'playback' ? await playback(id, ticket) : null;
      if (current(ticket)) { install({ devices: rows, view, selected: device, draft: view === 'settings' ? deviceDraft(device) : null, playback: play, interval: String(play?.intervalSeconds || 10), review: null, blocked: false }); setNotice(''); }
    });
  }
  async function send(intent: DeviceIntent) {
    if (!current() || working.current || live.current.unknown) return;
    const ticket = epoch.current; install({ unknown: intent, checked: false }); setWorking(true); setError(''); setNotice('');
    try {
      const value = await checkedDeviceMutation(job => guarded(job, ticket), csrf => deviceRequest<unknown>(intent.path, { method: intent.method, body: JSON.stringify(intent.body) }, csrf), caught => caught instanceof ApiError ? caught.status : undefined);
      if (intent.kind === 'playback') readPlayback(value, intent.deviceId!);
      else if (!value || typeof value !== 'object' || !('ok' in value) || value.ok !== true) throw new Error('服务返回结果无法核对。');
      const rows = await list(ticket), device = rows.find(row => row.id === intent.deviceId) || null;
      const play = intent.kind === 'playback' && device ? await playback(device.id, ticket) : null;
      if (!current(ticket)) return;
      if (intent.kind === 'settings' && device) {
        // A concurrent later save is shown for review, never called our result.
        const matching = sameDeviceSettings(device, intent.body as DeviceDraft);
        install({ devices: rows, unknown: null, checked: false, selected: matching ? device : live.current.selected,
          draft: matching ? deviceDraft(device) : live.current.draft, review: matching ? null : device, blocked: !matching });
        setNotice(matching ? '电视设置已保存并读回。' : '保存请求已受理，当前设置已有变化，请核对最新版本。');
      } else if (intent.kind === 'playback' && device && play) {
        install({ devices: rows, unknown: null, checked: false, selected: device, playback: play, interval: String(play.intervalSeconds) }); setNotice('已读取当前播放状态。');
      } else {
        install({ devices: rows, unknown: null, checked: false, view: 'list', selected: null, draft: null, playback: null, review: null, blocked: false, pair: freshModel(props.user.id).pair });
        setNotice(intent.kind === 'pair' ? '配对请求已完成，请在设备列表核对电视名称。' : intent.kind === 'revoke' ? '已撤销这台电视。重新使用时需要重新配对。' : '这台电视已不在有效设备列表中。');
      }
    } catch (caught) {
      if (!current(ticket)) return;
      if (caught instanceof DeviceWriteRejected) {
        install({ unknown: null, checked: false, blocked: intent.kind === 'settings' && caught.status === 409 || live.current.blocked });
        setError(caught.status === 409 ? '设置或播放状态已变化，请读取最新状态核对。草稿保留，未自动重发。' : caught.message);
        if (intent.kind === 'playback') install({ blocked: true });
      } else {
        setError('操作结果尚不明确，请先核对当前状态。不会自动重发。');
        if (caught instanceof DeviceDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) failure(caught, ticket);
      }
    } finally { if (current(ticket)) setWorking(false); }
  }
  function saveSettings() {
    if (locked || model.blocked || !model.selected || !model.draft) return;
    try { void send({ kind: 'settings', deviceId: model.selected.id, path: '/devices/' + model.selected.id, method: 'PATCH', body: devicePayload(model.draft, model.selected, props.state.people) }); }
    catch (caught) { setError(errorText(caught)); }
  }
  function pair() {
    if (locked) return;
    try { void send({ kind: 'pair', path: '/pair/approve', method: 'POST', body: pairPayload(model.pair, props.state.people) }); }
    catch (caught) { setError(errorText(caught)); }
  }
  function control(action: PlaybackAction) {
    if (locked || model.blocked || !model.playback) return;
    try { void send({ kind: 'playback', deviceId: model.playback.deviceId, path: '/media-playback/devices/' + model.playback.deviceId, method: 'PUT', body: playbackPayload(model.playback, action, model.interval) }); }
    catch (caught) { setError(errorText(caught)); }
  }
  function recover() {
    if (!live.current.unknown) return;
    void readJob(async ticket => { await reload(ticket, true); if (current(ticket)) { install({ checked: true }); setNotice('这是当前保存状态，不能据此认定原请求未执行。请核对后再决定下一步。'); } });
  }
  function acknowledge() {
    if (!current() || working.current || !live.current.unknown || !live.current.checked) return;
    const paired = live.current.unknown.kind === 'pair';
    install({ unknown: null, checked: false, blocked: live.current.view === 'settings' && !!live.current.review,
      ...(paired ? { view: 'list' as const, pair: freshModel(props.user.id).pair } : {}) });
    setError(''); setNotice('已完成本次核对。任何后续修改仍需你明确操作。');
  }
  function chooseReview(keep: boolean) {
    if (!current() || locked || !model.review) return;
    install({ selected: model.review, draft: keep ? model.draft : deviceDraft(model.review), review: null, blocked: false });
    setError(''); setNotice(keep ? '草稿保留，请逐项核对后再次保存。' : '已采用当前设置。');
  }
  function updateLayout(job: (layout: DeviceDraft['layout']) => DeviceDraft['layout']) {
    if (!model.draft || locked) return;
    try { edit({ layout: job(model.draft.layout) }); } catch (caught) { setError(errorText(caught)); }
  }
  const button = (label: string, onPress: () => void, disabled = locked, mode: 'text' | 'outlined' | 'contained' = 'outlined') => {
    const copy = label.startsWith('显示设置：') ? '显示设置' : label.startsWith('播放控制：') ? '播放控制'
      : label.startsWith('上移：') ? '上移' : label.startsWith('下移：') ? '下移'
        : label === '保留我的草稿，使用最新版本' ? '保留我的草稿' : label;
    return <Button accessibilityLabel={label} disabled={disabled} mode={mode} onPress={onPress} style={styles.button} contentStyle={styles.buttonContent} labelStyle={styles.buttonLabel}>{copy}</Button>;
  };
  const generalFields = (draft: Pick<DeviceDraft, 'name' | 'focus' | 'calendarView'>, change: (patch: Partial<DeviceDraft>) => void) => <View style={styles.stack}>
    <TextInput mode="outlined" label="电视名称" accessibilityLabel="电视名称" value={draft.name} onChangeText={name => change({ name })} disabled={locked} outlineStyle={styles.inputOutline} />
    <View accessibilityRole="radiogroup" accessibilityLabel="侧重成员"><Text variant="titleSmall">侧重成员</Text>{people.map(person => <SelectionRow key={person.id} kind="radio" label={person.name} accessibilityLabel={'侧重成员：' + person.name} checked={draft.focus === person.id} disabled={locked} onPress={() => change({ focus: person.id })} />)}</View>
    <View accessibilityRole="radiogroup" accessibilityLabel="日程范围"><Text variant="titleSmall">日程范围</Text>{views.map(item => <SelectionRow key={item.id} kind="radio" label={item.name} accessibilityLabel={'日程范围：' + item.name} checked={draft.calendarView === item.id} disabled={locked} onPress={() => change({ calendarView: item.id })} />)}</View>
  </View>;
  if (!visible) return <View style={styles.page}>{busy ? <ActivityIndicator accessibilityLabel="正在核对设备" /> : <EmptyState title={online() && household.online ? '重新核对后继续' : '设备内容已隐藏'} description={error || '连接恢复后，会重新核对登录身份与设备。'} action={button('重新核对身份与设备', () => { if (!household.online) void household.refresh(); else enter(); }, busy || !online())} />}</View>;
  return <View style={styles.page} testID="devices-screen">
    <PageHeader title={model.view === 'settings' ? '电视显示设置' : model.view === 'playback' ? '电视播放控制' : model.view === 'pair' ? '连接电视' : '电视与播放'}
      description={model.selected?.name || '每块屏幕各有侧重，用手机轻松管理。'} action={model.view === 'list' ? button('连接电视', () => { install({ view: 'pair', pair: freshModel(props.user.id).pair }); setNotice(''); }, locked, 'contained') : button('返回设备列表', back)} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对设备" />}
    {!!model.unknown && <View testID="device-operation-unknown"><SectionCard title="先核对这次操作"><View style={styles.stack}>
      <Text>请求可能已经执行。请读取当前状态，再决定是否继续；不会自动重发配对、保存或翻页。</Text>
      {button('核对操作结果', recover, busy)}
      {model.checked && model.unknown.kind === 'pair' && <View testID="pair-current-devices" style={styles.stack}>
        <Text variant="titleSmall" accessibilityRole="header">当前已连接电视</Text>
        {model.devices.length ? model.devices.map(device => <View key={device.id} testID={'pair-current-device-' + device.id} style={styles.stack}>
          <Text variant="titleMedium">{device.name}</Text>
          <Text>{focusName(device.focus)} · {views.find(item => item.id === device.calendarView)?.name}</Text>
        </View>) : <Text>当前没有有效设备。上次请求仍可能正在处理，请同时核对电视画面。</Text>}
        <Text>这份列表不能证明某次配对是否执行。结束核对会清除本次配对草稿；再次连接需要重新输入电视上的配对码。</Text>
      </View>}
      {model.checked && button(model.unknown.kind === 'pair' ? '核对完成，返回设备列表' : '我已核对当前状态', acknowledge, busy, 'contained')}
    </View></SectionCard></View>}
    {model.view === 'list' && <View style={styles.stack}>
      {button('刷新设备列表', () => void readJob(ticket => reload(ticket)))}
      {!model.devices.length && <EmptyState title="连接你的第一块屏幕" description="在电视浏览器打开本站 /tv，屏幕会显示 8 位配对码。在这里输入即可连接。" />}
      {model.devices.map(device => <View key={device.id} testID={'device-' + device.id}><SectionCard title={device.name}><View style={styles.stack}>
        <Text>{focusName(device.focus)} · {views.find(item => item.id === device.calendarView)?.name} · {device.layout.order.filter(key => !device.layout.hidden.includes(key)).length} 张卡片</Text>
        <View style={styles.actions}>{button('显示设置：' + device.name, () => open(device.id, 'settings'))}{button('播放控制：' + device.name, () => open(device.id, 'playback'), locked, 'contained')}</View>
      </View></SectionCard></View>)}
      <Text style={styles.muted}>电视只读。侧重成员和隐藏卡片不会扩大或撤销数据权限。</Text>
      {button('管理照片与电视许可', () => props.onNavigate('photos'))}
    </View>}
    {model.view === 'pair' && <SectionCard title="输入电视上的配对码"><View style={styles.stack}>
      <Text>在电视浏览器打开本站 /tv。配对码有效期 10 分钟；连接后仍需单独选择可展示的照片。</Text>
      <TextInput mode="outlined" label="电视配对码" accessibilityLabel="电视配对码" value={model.pair.code} autoCapitalize="characters" autoCorrect={false} onChangeText={code => editPair({ code })} disabled={locked} outlineStyle={styles.inputOutline} />
      {generalFields(model.pair, editPair)}
      {button('确认连接电视', pair, locked, 'contained')}
    </View></SectionCard>}
    {model.view === 'settings' && model.draft && <View style={styles.stack}>
      {model.blocked && <SectionCard title="核对最新设置"><View style={styles.stack}>
        <Text>当前版本可能已经变化。先读取并对照，再选择采用最新设置，或保留草稿后再次明确保存。</Text>
        {button('读取最新设置', () => void readJob(ticket => reload(ticket, true)))}
        {model.review && <><Text testID="device-current-settings">当前：{model.review.name} · {focusName(model.review.focus)} · {views.find(item => item.id === model.review!.calendarView)?.name} · {themes.find(item => item.id === model.review!.layout.theme)?.name} · {densities.find(item => item.id === model.review!.layout.density)?.name}</Text>
          <Text>卡片顺序：{model.review.layout.order.map(key => deviceCardNames[key] + (model.review!.layout.hidden.includes(key) ? '（隐藏）' : '')).join('、')}</Text>
          {button('采用最新设置', () => chooseReview(false))}{button('保留我的草稿，使用最新版本', () => chooseReview(true))}</>}
      </View></SectionCard>}
      <SectionCard title="基本设置">{generalFields(model.draft, edit)}</SectionCard>
      <SectionCard title="电视上的卡片"><View style={styles.stack}>
        <Text>调整显示顺序，至少保留一张卡片。隐藏只影响画面，不会删除内容或收回数据权限。</Text>
        {model.draft.layout.order.map((key, index) => <View key={key} testID={'device-layout-' + key} style={styles.layoutRow}>
          <SelectionRow label={deviceCardNames[key]} accessibilityLabel={'显示卡片：' + deviceCardNames[key]} checked={!model.draft!.layout.hidden.includes(key)} disabled={locked} onPress={() => updateLayout(layout => toggleDeviceCard(layout, key))} />
          <View style={styles.actions}>{button('上移：' + deviceCardNames[key], () => updateLayout(layout => moveDeviceCard(layout, key, -1)), locked || index === 0)}{button('下移：' + deviceCardNames[key], () => updateLayout(layout => moveDeviceCard(layout, key, 1)), locked || index === 4)}</View>
        </View>)}
      </View></SectionCard>
      <SectionCard title="外观"><View style={styles.stack}>
        <View accessibilityRole="radiogroup" accessibilityLabel="电视主题">{themes.map(item => <SelectionRow key={item.id} kind="radio" label={item.name} accessibilityLabel={'电视主题：' + item.name} checked={model.draft!.layout.theme === item.id} disabled={locked} onPress={() => edit({ layout: { ...model.draft!.layout, theme: item.id } })} />)}</View>
        <View accessibilityRole="radiogroup" accessibilityLabel="显示密度">{densities.map(item => <SelectionRow key={item.id} kind="radio" label={item.name} accessibilityLabel={'显示密度：' + item.name} checked={model.draft!.layout.density === item.id} disabled={locked} onPress={() => edit({ layout: { ...model.draft!.layout, density: item.id } })} />)}</View>
        {button('恢复默认布局与外观', () => edit({ layout: defaultDeviceLayout() }))}
        {button('保存到这台电视', saveSettings, locked || model.blocked, 'contained')}
        <Text style={styles.muted}>保存后，电视下次成功刷新时应用。离线、休眠或后台可能延迟。</Text>
      </View></SectionCard>
      <Divider />{button('撤销这台电视', () => setDialog('revoke'))}
    </View>}
    {model.view === 'playback' && model.playback && <SectionCard title="照片播放"><View style={styles.stack}>
      <Text variant="headlineSmall">{model.playback.mode === 'dashboard' ? '正在显示家庭看板' : model.playback.paused ? '照片已暂停' : '正在轮播照片'}</Text>
      <Text testID="device-playback-status">{model.playback.photoCount} 张已授权照片{model.playback.mode === 'photos' && model.playback.photoCount ? ` · 当前第 ${model.playback.position + 1} 张` : ''} · 间隔 {model.playback.intervalSeconds} 秒</Text>
      <Text>只播放照片本人明确共享并允许这台电视展示的照片。开始播放不会增加照片权限。</Text>
      {model.blocked && <Text accessibilityRole="alert">播放状态已变化。请先刷新，再明确操作。</Text>}
      {button('刷新播放状态', () => void readJob(async ticket => { await reload(ticket); if (current(ticket)) install({ blocked: false }); }))}
      <View style={styles.actions}>{button('开始照片播放', () => control('start'), locked || model.blocked || !model.playback.canStart, 'contained')}{button('显示家庭看板', () => control('dashboard'), locked || model.blocked)}</View>
      {!model.playback.canStart && <EmptyState title="还没有可播放的照片" description="去相册保存照片、设置为家庭共享，再明确允许这台电视展示。配对本身不会授权相册。" />}
      {model.playback.mode === 'photos' && <View style={styles.actions}>{button(model.playback.paused ? '继续播放' : '暂停播放', () => control(model.playback!.paused ? 'resume' : 'pause'), locked || model.blocked)}{button('上一张照片', () => control('previous'), locked || model.blocked)}{button('下一张照片', () => control('next'), locked || model.blocked)}</View>}
      <TextInput mode="outlined" label="轮播间隔（秒）" accessibilityLabel="轮播间隔（秒）" keyboardType="number-pad" value={model.interval} onChangeText={interval => { if (!locked && current()) install({ interval }); }} disabled={locked} outlineStyle={styles.inputOutline} />
      {button('保存轮播间隔', () => control('interval'), locked || model.blocked)}
      {button('管理照片与电视许可', () => props.onNavigate('photos'), locked || dirty(model))}
      <Text style={styles.muted}>显示状态来自服务器，不证明实体电视当前画面；电视断网、休眠时可能尚未更新。</Text>
    </View></SectionCard>}
    <Portal><Dialog visible={!!dialog && visible} onDismiss={() => { if (!busy) setDialog(null); }} style={styles.dialog}>
      <Dialog.Title>{dialog === 'revoke' ? '撤销电视连接？' : '放弃未保存的修改？'}</Dialog.Title>
      <Dialog.ScrollArea><ScrollView><Text style={styles.dialogCopy}>{dialog === 'revoke' ? '这台电视将失去后续读取权限。重新使用需重新配对；无法抹去它此前已显示或缓存的画面。' : '尚未保存的草稿将被丢弃。已经保存的电视设置保持。'}</Text></ScrollView></Dialog.ScrollArea>
      <Dialog.Actions style={styles.dialogActions}>{button('继续编辑', () => setDialog(null), busy)}{dialog === 'revoke' ? button('确认撤销电视', () => { const id = live.current.selected?.id; setDialog(null); if (id) void send({ kind: 'revoke', deviceId: id, path: '/devices/' + id, method: 'DELETE', body: {} }); }, locked, 'contained') : button('放弃修改并返回', toList, busy, 'contained')}</Dialog.Actions>
    </Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({
  page: { gap: 16, paddingBottom: 28, minWidth: 0 }, stack: { gap: 16, minWidth: 0 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  button: { maxWidth: '100%', flexShrink: 1 }, buttonContent: { minHeight: 44 }, buttonLabel: { flexShrink: 1 }, inputOutline: { borderRadius: 8 }, layoutRow: { gap: 4, paddingBottom: 12 },
  muted: { opacity: 0.72 }, dialog: { borderRadius: 24, maxWidth: 560, width: '90%', alignSelf: 'center' },
  dialogCopy: { paddingVertical: 20 }, dialogActions: { flexWrap: 'wrap', gap: 8 },
});
