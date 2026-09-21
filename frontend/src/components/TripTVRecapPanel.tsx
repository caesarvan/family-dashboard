import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, RadioButton, Text, TextInput, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { readDevices, readPlayback, playbackPayload, type Device, type Playback, type PlaybackAction } from '../lib/devices';
import { readRoutePage, type RoutePage } from '../lib/journeyRoutes';
import { forgetJourneyMarker, journeyActor, readJourneyOperation, readJourneyPreview, restoreJourneyMarker, TRIP_TV_STORAGE_KEY,
  TripTVDiscarded, TripTVError, TripTVFence, TripTVRejected, tripTVRequest,
  type JourneyMarker, type JourneyOperation, type JourneyPreview } from '../lib/tvTripRecap';
import type { IdentitySession } from '../lib/sessionIdentity';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';

type Props = { journeyId: string; onBack: () => void };
type State = { devices: Device[]; routes: RoutePage | null; preview: JourneyPreview | null; playback: Playback | null; operation: JourneyOperation | null };
const empty = (): State => ({ devices: [], routes: null, preview: null, playback: null, operation: null });
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const visiblePage = () => typeof document === 'undefined' || !document.hidden;
const storage = (): Storage | null => { try { return typeof sessionStorage === 'undefined' ? null : sessionStorage; } catch { return null; } };
const uuid = () => { const values = new Uint8Array(16); crypto.getRandomValues(values); return Array.from(values, n => n.toString(16).padStart(2, '0')).join(''); };
export default function TripTVRecapPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户管理电视回顾" action={<Button onPress={props.onBack}>返回旅行回顾</Button>} />;
  return <Workspace key={household.identityKey + props.journeyId} {...props} identity={household.identityKey} actor={journeyActor(household)} />;
}
function Workspace(props: Props & { identity: string; actor: string }) {
  const household = useHousehold(), theme = useTheme(), latest = useRef({ household, props }); latest.current = { household, props };
  const [state, setState] = useState<State>(empty), live = useRef(state);
  const [busy, setBusy] = useState(false), [shown, setShown] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [deviceId, setDeviceId] = useState(''), [routeId, setRouteId] = useState<string | null>(null), [interval, setIntervalText] = useState('10');
  const [pending, setPending] = useState<JourneyMarker | null>(() => restoreJourneyMarker(storage(), props.actor)), marker = useRef(pending);
  const startBody = useRef<{ requestId: string; previewToken: string; confirmStart: true } | null>(null);
  const [absent, setAbsent] = useState(false), absentVerified = useRef(false);
  const [controlUnknown, setControlUnknown] = useState(false), unknownControl = useRef(false);
  const choice = useRef({ deviceId: '', routeId: null as string | null, offset: 0 }), alive = useRef(false), focused = useRef(false), active = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), pageActive = useRef(true), epoch = useRef(0), working = useRef(false), denied = useRef(false);
  const flight = useRef<AbortController | null>(null);
  const request = (path: string, options: RequestInit = {}, csrf = '') => tripTVRequest(path, { ...options, signal: flight.current?.signal }, csrf);
  const fence = useRef(new TripTVFence(props.identity, () => request('/me') as Promise<IdentitySession>));
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && foreground.current && pageActive.current && !denied.current
    && online() && visiblePage() && latest.current.household.online && latest.current.household.identityKey === props.identity && ticket === epoch.current;
  function install(patch: Partial<State>) { live.current = { ...live.current, ...patch }; setState(live.current); }
  function setMarker(value: JourneyMarker | null) { marker.current = value; setPending(value); }
  function conceal() { active.current = false; ++epoch.current; flight.current?.abort(); flight.current = null; working.current = false;
    setBusy(false); setShown(false); absentVerified.current = false; setAbsent(false); live.current = empty(); setState(live.current); setNotice(''); setError(''); }
  function failure(caught: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (caught instanceof TripTVDiscarded && caught.message === 'identity') {
      forgetJourneyMarker(storage(), marker.current); setMarker(null); startBody.current = null; choice.current = { deviceId: '', routeId: null, offset: 0 };
      setDeviceId(''); setRouteId(null); denied.current = true; conceal(); setError('登录身份已变化，电视回顾内容已清除。请刷新后重新进入。');
      void latest.current.household.refresh(); return;
    }
    if (caught instanceof TripTVDiscarded) return;
    setShown(false); install({ preview: null, playback: null, operation: null, devices: [], routes: null });
    setError(caught instanceof TripTVError || caught instanceof TripTVRejected ? caught.message : '暂时无法核对。旧内容已隐藏，请重新核对身份和电视状态。');
  }
  async function job(body: (ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(); flight.current = controller; working.current = true; setBusy(true); setError('');
    const timer = setTimeout(() => controller.abort(), 20000);
    try { await body(ticket); } catch (caught) { failure(caught, ticket); }
    finally { clearTimeout(timer); if (flight.current === controller) flight.current = null; if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  const guard = <T,>(read: (csrf: string) => Promise<T>, ticket: number) => fence.current.run(read, () => current(ticket));
  async function playback(id: string, ticket: number) { return guard(async () => readPlayback(await request('/media-playback/devices/' + id), id), ticket); }
  async function outcome(ticket: number) {
    const original = marker.current; if (!original) return; absentVerified.current = false; setAbsent(false);
    const value = await guard(async () => {
      const raw = await request('/media-playback/operations/' + original.requestId) as Record<string, unknown>;
      if (raw.found === false) return null;
      if (raw.found !== true) throw new Error('Invalid receipt');
      return { operation: readJourneyOperation(raw.operation, original), playback: raw.playback === null ? null : readPlayback(raw.playback, original.deviceId) };
    }, ticket);
    if (!current(ticket)) return;
    choice.current.deviceId = original.deviceId; setDeviceId(original.deviceId);
    setShown(true);
    if (!value) {
      const play = await guard(async () => { try { return readPlayback(await request('/media-playback/devices/' + original.deviceId), original.deviceId); }
        catch (caught) { if (caught instanceof TripTVError && [404, 410].includes(caught.status)) return null; throw caught; } }, ticket);
      if (!current(ticket)) return;
      install({ playback: play }); absentVerified.current = true; setAbsent(true); setNotice('读取时尚无原操作回执；不能确认是否已开始。请继续核对，不会自动重复开始。'); return;
    }
    forgetJourneyMarker(storage(), original); setMarker(null); startBody.current = null; install({ ...value, preview: null });
    if (value.playback) setIntervalText(String(value.playback.intervalSeconds));
    setNotice(value.playback ? '已核对原开始回执。下方是这台电视当前保存的状态。' : '已核对原开始回执；这台电视当前不可读取，未恢复旧内容。');
  }
  async function load(ticket: number) {
    if (marker.current) { await outcome(ticket); return; }
    const result = await guard(async () => {
      const devices = readDevices(await request('/devices'));
      const routes = readRoutePage(await request(`/journey-routes?journeyId=${props.journeyId}&scope=shared&limit=24&offset=${choice.current.offset}`), props.journeyId, 'shared', choice.current.offset);
      return { devices, routes };
    }, ticket);
    let play: Playback | null = null;
    if (choice.current.deviceId && !result.devices.some(d => d.id === choice.current.deviceId)) { choice.current.deviceId = ''; setDeviceId(''); }
    if (choice.current.deviceId && result.devices.some(d => d.id === choice.current.deviceId)) play = await playback(choice.current.deviceId, ticket);
    if (!current(ticket)) return;
    install({ ...result, playback: play, preview: null }); setShown(true);
    if (play) setIntervalText(String(play.intervalSeconds));
  }
  function enter() { if (active.current || denied.current || !alive.current || !focused.current || !foreground.current || !pageActive.current || !visiblePage() || !online() || !latest.current.household.online) return;
    active.current = true; void job(load); }
  function refresh() { if (active.current) void job(load); else enter(); }
  function pickDevice(id: string) { if (busy || marker.current || unknownControl.current || !current()) return; choice.current.deviceId = id; setDeviceId(id); install({ preview: null, playback: null, operation: null }); setNotice(''); }
  function pickRoute(id: string | null) { if (busy || marker.current || unknownControl.current || !current()) return; choice.current.routeId = id; setRouteId(id); install({ preview: null }); setNotice(''); }
  async function readPreview(ticket: number) {
    const selection = { ...choice.current }, play = await playback(selection.deviceId, ticket);
    const value = await guard(async csrf => readJourneyPreview(await request(`/media-playback/devices/${selection.deviceId}/journey-preview`, {
      method: 'POST', body: JSON.stringify({ revision: play.revision, journeyId: props.journeyId, routeId: selection.routeId }) }, csrf), props.journeyId, selection.routeId, play.revision), ticket);
    if (current(ticket)) { install({ preview: value, playback: play, operation: null }); setShown(true); setNotice(''); }
  }
  async function preview() { await job(readPreview); }
  async function repreview() { await job(async ticket => {
    await outcome(ticket); const original = marker.current;
    if (!current(ticket) || !original || !absentVerified.current) return;
    // Explicitly leave local recovery, not a claim that the old request failed.
    forgetJourneyMarker(storage(), original); setMarker(null); startBody.current = null; absentVerified.current = false; setAbsent(false);
    await load(ticket); if (current(ticket) && live.current.playback) await readPreview(ticket);
    if (current(ticket)) setNotice('已重新预览；上次请求仍可能稍后完成。再次开始仍须明确确认，并由服务器核对播放版本。');
  }); }
  async function start(retry = false) {
    if (unknownControl.current || (retry ? !marker.current || !startBody.current : !live.current.preview || !!marker.current)) return;
    const before = live.current.preview, id = retry ? marker.current!.deviceId : choice.current.deviceId;
    await job(async ticket => {
      if (retry) { await outcome(ticket); if (!current(ticket) || !marker.current || !absentVerified.current || !startBody.current) return; }
      const original: JourneyMarker = retry ? marker.current! : { memberIdentity: props.actor, deviceId: id, requestId: uuid() };
      const body = retry ? startBody.current! : { requestId: original.requestId, previewToken: before!.previewToken, confirmStart: true as const };
      // Save only a non-secret recovery pointer before the first possible write.
      try { const saved = storage(); if (!saved) throw new Error('Storage unavailable'); saved.setItem(TRIP_TV_STORAGE_KEY, JSON.stringify(original)); } catch { throw new Error('Recovery storage unavailable'); }
      setMarker(original); startBody.current = body; absentVerified.current = false; setAbsent(false);
      try {
        const value = await guard(async csrf => {
          let raw: Record<string, unknown>;
          try { raw = await request(`/media-playback/devices/${id}/journey-start`, { method: 'POST', body: JSON.stringify(body) }, csrf) as Record<string, unknown>; }
          catch (caught) { if (caught instanceof TripTVError && [400, 403, 404, 409, 410, 429].includes(caught.status)) throw new TripTVRejected(caught.message); throw caught; }
          if (typeof raw.replayed !== 'boolean') throw new Error('Invalid start receipt');
          return { operation: readJourneyOperation(raw.operation, original), playback: readPlayback(raw.playback, id) };
        }, ticket);
        if (!current(ticket)) return;
        forgetJourneyMarker(storage(), original); setMarker(null); startBody.current = null; install({ ...value, preview: null }); setIntervalText(String(value.playback.intervalSeconds)); setShown(true);
        setNotice('开始回执已保存。电视会在联网核对后显示这趟旅行。');
      } catch (caught) {
        if (current(ticket) && caught instanceof TripTVRejected) { forgetJourneyMarker(storage(), original); setMarker(null); startBody.current = null; install({ preview: null }); }
        throw caught;
      }
    });
  }
  async function control(action: PlaybackAction) { if (marker.current || unknownControl.current) return;
    await job(async ticket => {
      const id = choice.current.deviceId, before = await playback(id, ticket), body = playbackPayload(before, action, interval);
      if (!current(ticket)) return;
      unknownControl.current = true; setControlUnknown(true);
      try {
        const after = await guard(async csrf => {
          try { return readPlayback(await request('/media-playback/devices/' + id, { method: 'PUT', body: JSON.stringify(body) }, csrf), id); }
          catch (caught) { if (caught instanceof TripTVError && [400, 403, 404, 409, 410, 429].includes(caught.status)) throw new TripTVRejected(caught.message); throw caught; }
        }, ticket);
        if (!current(ticket)) return;
        unknownControl.current = false; setControlUnknown(false); install({ playback: after, preview: null }); setShown(true);
        setNotice(action === 'dashboard' ? '已保存返回家庭看板。' : '控制已保存，电视联网后应用。');
      } catch (caught) { if (current(ticket) && caught instanceof TripTVRejected) { unknownControl.current = false; setControlUnknown(false); } throw caught; }
    });
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; ++epoch.current; flight.current?.abort(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, []));
  useEffect(() => {
    const hide = () => conceal(), show = () => enter(), visibility = () => visiblePage() ? show() : hide();
    const blur = () => { pageActive.current = false; hide(); }, focus = () => { pageActive.current = true; show(); };
    const sub = AppState.addEventListener('change', state => { foreground.current = state === 'active'; foreground.current ? show() : hide(); });
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focus); window.addEventListener('pagehide', blur); window.addEventListener('pageshow', focus); window.addEventListener('offline', hide); window.addEventListener('online', show); }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    const timer = setInterval(() => { if (current() && !marker.current && !working.current) void job(async ticket => {
      if (live.current.preview || !choice.current.deviceId) { await guard(async () => null, ticket); return; }
      const play = await playback(choice.current.deviceId, ticket); if (current(ticket)) { install({ playback: play }); setShown(true); }
    }); }, 5000);
    return () => { clearInterval(timer); sub.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focus); window.removeEventListener('pagehide', blur); window.removeEventListener('pageshow', focus); window.removeEventListener('offline', hide); window.removeEventListener('online', show); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  const showing = shown && current(), locked = busy || !current(), blocked = locked || !!pending || controlUnknown;
  const button = (id: string, label: string, action: () => void, disabled = blocked, primary = false) => <Button testID={id} accessibilityLabel={label} mode={primary ? 'contained' : 'outlined'} contentStyle={{ minHeight: 44 }} disabled={disabled} onPress={action}>{label}</Button>;
  const play = state.playback;
  return <View testID="trip-tv-panel" style={styles.stack}>
    <PageHeader title="在电视回顾" description="只展示这趟旅行仍获这台电视许可的内容。" action={button('trip-tv-back', '返回旅行回顾', props.onBack, busy)} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对电视回顾" />}
    {!!pending && <SectionCard title="开始结果尚未核对"><View testID="trip-tv-unknown" style={styles.stack}>
      <Text>保留原电视和操作标识，不会自动重复开始。刷新后先核对原回执。</Text>
      {showing && state.playback && <Text testID="trip-tv-unknown-current">当前保存状态：{state.playback.mode === 'dashboard' ? '家庭看板' : state.playback.scope === 'journey' ? state.playback.journeyReview?.journey?.title || '原旅行不可用' : '全部授权相册'} · {state.playback.photoCount} 项授权媒体。此状态不证明原操作失败。</Text>}
      {button('trip-tv-recheck', '核对原开始结果', refresh, busy || denied.current || !online() || !household.online)}
      {showing && absent && <>
        {startBody.current && button('trip-tv-retry', '重试本次开始', () => void start(true), locked)}
        <Text>当前仍未查到上次结果。你可以重新预览；这会结束本机的旧结果恢复，上次请求仍可能稍后完成。新预览不会自动开始。</Text>
        {button('trip-tv-repreview', '重新预览', () => void repreview(), locked)}
      </>}
    </View></SectionCard>}
    {!showing && <EmptyState title="电视回顾内容已隐藏" description="回到前台并联网后重新核对身份；未核实的内容不会显示。" action={button('trip-tv-refresh', '核对身份并继续', refresh, busy || denied.current || !online() || !household.online)} />}
    {showing && <>
      {!!notice && <Text testID="trip-tv-status" accessibilityLiveRegion="polite">{notice}</Text>}
      {!pending && !state.operation && <SectionCard title="选择电视与路线"><View style={styles.stack}>
        {!state.devices.length && <Text>没有已配对电视。请先在设备管理中配对，再回来核对。</Text>}
        {state.devices.map(d => <View key={d.id} testID={'trip-tv-device-' + d.id}><RadioButton.Item label={d.name} value={d.id} status={deviceId === d.id ? 'checked' : 'unchecked'} disabled={blocked} onPress={() => pickDevice(d.id)} /></View>)}
        <Text variant="titleMedium">可选的一条共享路线</Text>
        <View testID="trip-tv-route-none"><RadioButton.Item label="不显示路线" value="none" status={routeId === null ? 'checked' : 'unchecked'} disabled={blocked} onPress={() => pickRoute(null)} /></View>
        {state.routes?.items.map(r => <View key={r.id} testID={'trip-tv-route-' + r.id}><RadioButton.Item label={r.title + ' · ' + r.stopCount + ' 站'} value={r.id} status={routeId === r.id ? 'checked' : 'unchecked'} disabled={blocked} onPress={() => pickRoute(r.id)} /></View>)}
        {!!routeId && !state.routes?.items.some(r => r.id === routeId) && <Text>已保留其它页的路线选择；核对预览将再次确认权限。</Text>}
        {state.routes && <View style={styles.actions}><Text>第 {state.routes.offset / 24 + 1} 页 · 共 {state.routes.total} 条共享路线</Text>
          {button('trip-tv-routes-previous', '上一页路线', () => { choice.current.offset -= 24; refresh(); }, blocked || !state.routes.offset)}
          {button('trip-tv-routes-next', '下一页路线', () => { choice.current.offset += 24; refresh(); }, blocked || !state.routes.hasMore)}</View>}
        {button('trip-tv-preview', '核对电视内容', () => void preview(), blocked || !deviceId, true)}
      </View></SectionCard>}
      {!!state.preview && <SectionCard title="将在这台电视展示"><View testID="trip-tv-preview-content" style={styles.stack}>
        <Text variant="titleLarge">{state.preview.journey.title}</Text><Text>{state.preview.journey.start} 至 {state.preview.journey.end}</Text>
        <Text>{state.preview.mediaCount} 项已授权照片／视频 · {state.preview.route ? state.preview.route.title : '未选择路线'}</Text>
        {state.preview.route?.stops.map(s => <Text key={s.index}>{s.index + 1}. {s.state === 'available' ? s.place.name + (s.place.coordinatePrecision === 'approximate' ? ' · 大致位置' : s.place.coordinates ? '' : ' · 无共享坐标') : '此站不可展示'}</Text>)}
        <Text>开始会替换这台电视当前播放范围，不会增加共享或电视许可。照片不表示拍于当前路线站点。</Text>
        {!state.preview.canStart && <Text>没有可展示的媒体或路线站点，请调整选择或先管理原内容权限。</Text>}
        {button('trip-tv-start', '开始电视回顾', () => void start(), blocked || !state.preview.canStart, true)}
      </View></SectionCard>}
      {!!play && !pending && <SectionCard title="手机控制"><View testID="trip-tv-controls" style={styles.stack}>
        <Text>{play.mode === 'dashboard' ? '当前显示家庭看板' : play.scope === 'journey' ? play.journeyReview?.journey?.title || '原旅行已不可用' : '当前为全部授权相册'}</Text>
        <Text>{play.photoCount} 项授权媒体{play.paused ? ' · 已暂停' : ''}</Text>
        {play.journeyReview?.routeStatus === 'unavailable' && <Text>所选路线已不可用，旧路线不再显示。</Text>}
        {controlUnknown && <View testID="trip-tv-control-unknown" style={styles.stack}><Text>控制结果尚未确认。请核对当前状态；读取不能证明原操作未执行。</Text>
          {button('trip-tv-control-recheck', '核对当前播放', () => void job(async ticket => { const p = await playback(choice.current.deviceId, ticket); if (current(ticket)) { install({ playback: p }); setShown(true); setNotice('请核对下方当前状态，再明确继续。'); } }), locked)}
          {button('trip-tv-control-continue', '我已核对，继续', () => { unknownControl.current = false; setControlUnknown(false); }, locked)}</View>}
        {play.mode === 'photos' && <View style={styles.actions}>{button('trip-tv-' + (play.paused ? 'resume' : 'pause'), play.paused ? '继续回顾' : '暂停回顾', () => void control(play.paused ? 'resume' : 'pause'))}
          {play.photoCount > 0 && <>{button('trip-tv-previous', '上一项', () => void control('previous'))}{button('trip-tv-next', '下一项', () => void control('next'))}</>}</View>}
        <TextInput label="照片间隔（秒）" accessibilityLabel="照片间隔（秒）" mode="outlined" value={interval} onChangeText={setIntervalText} disabled={blocked} keyboardType="number-pad" />
        {button('trip-tv-interval', '保存照片间隔', () => void control('interval'))}
        {button('trip-tv-dashboard', '返回家庭看板', () => void control('dashboard'))}
        {button('trip-tv-current', '刷新播放状态', () => void job(async ticket => { const p = await playback(choice.current.deviceId, ticket); if (current(ticket)) { install({ playback: p }); setShown(true); } }), locked || !!pending)}
        {state.operation && button('trip-tv-select-again', '重新选择电视与路线', () => { install({ operation: null }); refresh(); }, blocked)}
        <Text>这是服务器保存的状态，不证明实体电视已经更新。离线、后台或休眠可能延迟显示。</Text>
      </View></SectionCard>}
      {state.operation && !play && button('trip-tv-select-again', '重新选择电视与路线', () => { install({ operation: null }); refresh(); }, blocked)}
    </>}
  </View>;
}
const styles = StyleSheet.create({ stack: { gap: 16, minWidth: 0 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 10 } });
