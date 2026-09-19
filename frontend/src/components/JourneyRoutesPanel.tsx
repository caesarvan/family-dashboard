import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Divider, Text, TextInput, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { newKey } from '../lib/trips';
import { PlaceDiscarded, PlaceFence, validatePlacePage, type Place, type PlacePage, type PlaceSession } from '../lib/places';
import { PlaceWriteRejected, PlaceWriteUnverified, readJourneyPlaceSource, type JourneyPlaceSource } from '../lib/journeyPlaces';
import { adjacentRouteSegments, draftRouteStops, publicRoutePlace, readRouteDetail, readRoutePage, readRoutePlace, readRouteReceipt, routeDeleteIntent, routeDraft,
  routeGeometry, routeIntentUnknown, routeOrigin, routeWriteIntent, sendRouteIntent, type RouteDetail, type RouteDraft, type RouteIntent, type RoutePage, type RouteReceipt, type RouteStop } from '../lib/journeyRoutes';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';
import WorldMap from '../ui/WorldMap';
import TripRecapPanel from './TripRecapPanel';

type Props = { journeyId: string; onBack: () => void; onPlaces: () => void };
type Selection = { scope: 'mine' | 'shared'; offset: number; id: string; placeOffset: number };
type Data = { journey: JourneyPlaceSource; list: RoutePage; detail: RouteDetail | null; candidates: PlacePage | null; places: Map<string, Place> };
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const pageVisible = () => typeof document === 'undefined' || !document.hidden;
const explanation = (p: Place) => p.coordinatePrecision === 'hidden' ? '坐标隐藏' : p.coordinatePrecision === 'none' ? '未提供坐标' : p.coordinatePrecision === 'approximate' ? '大致位置（约 0.1°）' : '精确坐标';

export default function JourneyRoutesPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member' || !/^[a-f0-9]{24}$/.test(props.journeyId)) return <EmptyState title="请用成员账户重新选择旅行" action={<Button onPress={props.onBack}>返回旅行详情</Button>} />;
  return <Workspace key={household.identityKey + ':' + props.journeyId} {...props} identityKey={household.identityKey} />;
}

function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), latest = useRef(household); latest.current = household;
  const [data, setData] = useState<Data | null>(null), [draft, setDraft] = useState<RouteDraft | null>(null), [pending, setPending] = useState<RouteIntent | null>(null);
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false), [shareChecked, setShareChecked] = useState(false), [deleting, setDeleting] = useState(false), [notFound, setNotFound] = useState(false);
  const [photos, setPhotos] = useState(false), [selectedStop, setSelectedStop] = useState(0), [showPicker, setShowPicker] = useState(false);
  const state = useRef({ data, draft, pending, photos }); state.current = { data, draft, pending, photos };
  const selection = useRef<Selection>({ scope: 'mine', offset: 0, id: '', placeOffset: 0 });
  const alive = useRef(false), focused = useRef(false), active = useRef(false), denied = useRef(false), departed = useRef(false), working = useRef(false), epoch = useRef(0);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const windowFocused = useRef(typeof document === 'undefined' || document.hasFocus()), pageHidden = useRef(false), flight = useRef<AbortController | null>(null);
  const fence = useRef(new PlaceFence(() => request<PlaceSession>('/me', { signal: flight.current?.signal }), props.identityKey));
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && !denied.current && !departed.current && !state.current.photos
    && foreground.current && windowFocused.current && !pageHidden.current && pageVisible() && connected() && latest.current.online
    && latest.current.identityKey === props.identityKey && epoch.current === ticket;
  function draftState(value: RouteDraft | null) { state.current.draft = value; setDraft(value); setShareChecked(false); }
  function intentState(value: RouteIntent | null) { state.current.pending = value; setPending(value); setNotFound(false); }
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null; working.current = false;
    setVisible(false); setBusy(false); setData(null); state.current.data = null; setShareChecked(false); setDeleting(false); setError(''); setNotice('');
    if (clear) { draftState(null); intentState(null); selection.current = { scope: 'mine', offset: 0, id: '', placeOffset: 0 }; }
  }
  function fail(caught: unknown, ticket: number) {
    if (!current(ticket)) return;
    const underlying = caught instanceof PlaceWriteUnverified ? caught.reason : caught;
    if (underlying instanceof PlaceDiscarded && underlying.message === 'identity' || underlying instanceof ApiError && [401, 403].includes(underlying.status)) {
      denied.current = true; conceal(true); setError('登录或查看权限已变化，请返回旅行重新进入。'); void latest.current.refresh(); return;
    }
    if (underlying instanceof PlaceDiscarded) return;
    setError(underlying instanceof ApiError && [404, 410].includes(underlying.status) ? '路线、地点或旅行已不可读取。请返回列表重新核对。' : '暂时无法核对路线，请重新读取。');
  }
  async function guard<T>(job: (csrf: string) => Promise<T>, ticket: number) { return fence.current.run(job, () => current(ticket)); }
  async function get(path: string): Promise<unknown> { return request(path, { signal: flight.current?.signal }); }
  async function reload(ticket: number) {
    const ids = { ...selection.current }, editor = state.current.draft;
    const next = await guard(async () => {
      const journey = readJourneyPlaceSource(await get('/journeys/' + props.journeyId), props.journeyId);
      const query = new URLSearchParams({ scope: ids.scope, journeyId: props.journeyId, limit: '24', offset: String(ids.offset) });
      let list = readRoutePage(await get('/journey-routes?' + query), props.journeyId, ids.scope, ids.offset);
      if (!list.items.length && ids.offset > 0) {
        ids.offset = Math.max(0, Math.floor(Math.max(0, list.total - 1) / 24) * 24); query.set('offset', String(ids.offset));
        list = readRoutePage(await get('/journey-routes?' + query), props.journeyId, ids.scope, ids.offset);
      }
      const detail = ids.id ? readRouteDetail(await get('/journey-routes/' + ids.id), props.journeyId, ids.id) : null;
      let candidates: PlacePage | null = null; const places = new Map<string, Place>();
      detail?.route.stops.forEach(s => { if (s.state === 'available') places.set(s.place.id, s.place); });
      if (editor) {
        const q = new URLSearchParams({ scope: 'visible', journeyId: props.journeyId, limit: '24', offset: String(ids.placeOffset) });
        const page = validatePlacePage(await get('/journey-places?' + q) as PlacePage, ids.placeOffset);
        candidates = { ...page, items: page.items.map(p => readRoutePlace(p, props.journeyId)) };
        candidates.items.forEach(p => places.set(p.id, p));
        const idsToRead = Array.from(new Set(editor.stops.flatMap(s => 'placeId' in s ? [s.placeId] : [])));
        for (const id of idsToRead) {
          try { const raw = await get('/journey-places/' + id) as { place: unknown }; const p = readRoutePlace(raw.place, props.journeyId); if (p.id !== id) throw new Error(); places.set(id, p); }
          catch (e) { if (e instanceof ApiError && [404, 410].includes(e.status)) places.delete(id); else throw e; }
        }
      }
      return { journey, list, detail, candidates, places };
    }, ticket);
    if (!current(ticket)) return;
    selection.current = ids; state.current.data = next; setData(next); setVisible(true);
    if (editor) {
      const changed = editor.expectedJourneyRevision !== next.journey.revision || !!editor.original && (!next.detail || editor.original.sourceVersion !== next.detail.route.sourceVersion)
        || editor.stops.some(s => 'placeId' in s && next.places.get(s.placeId)?.revision !== s.expectedRevision);
      setConflict(changed); if (changed) setShareChecked(false);
    }
  }
  async function readJob(job: (ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000); flight.current = controller; working.current = true; setBusy(true); setError('');
    try { await job(ticket); }
    catch (caught) { if (current(ticket)) { setData(null); state.current.data = null; fail(caught, ticket); } }
    finally { clearTimeout(timer); if (flight.current === controller) flight.current = null; if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function enter() {
    if (active.current || !alive.current || !focused.current || denied.current || departed.current || state.current.photos || !foreground.current || !windowFocused.current || pageHidden.current || !pageVisible() || !connected() || !latest.current.online) return;
    active.current = true;
    void readJob(async ticket => {
      // Recovery must still work when the source journey has since been deleted.
      if (state.current.pending) { await guard(async () => true, ticket); if (current(ticket)) setVisible(true); }
      else await reload(ticket);
    });
  }
  function refresh() { if (active.current) void readJob(reload); else enter(); }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey, props.journeyId]));
  useEffect(() => {
    const visibility = () => { if (pageVisible()) enter(); else conceal(); }, online = () => enter(), offline = () => conceal();
    const blur = () => { windowFocused.current = false; conceal(); }, focus = () => { windowFocused.current = true; enter(); };
    const hide = () => { pageHidden.current = true; conceal(); }, show = () => { pageHidden.current = false; enter(); };
    const sub = AppState.addEventListener('change', v => { foreground.current = v === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focus); window.addEventListener('offline', offline); window.addEventListener('online', online); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); }
    const timer = setInterval(() => { if (current() && !working.current && !state.current.pending) void readJob(reload); }, 15000);
    return () => { clearInterval(timer); sub.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focus); window.removeEventListener('offline', offline); window.removeEventListener('online', online); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  useEffect(() => { if (!photos) enter(); }, [photos]);

  function navigate(action: () => void) { if (working.current || state.current.pending || state.current.draft || latest.current.identityKey !== props.identityKey) return; departed.current = true; conceal(true); action(); }
  function open(id: string) { if (locked || draft) return; selection.current.id = id; setSelectedStop(0); setDeleting(false); void readJob(reload); }
  function chooseScope(scope: 'mine' | 'shared') { if (locked || draft) return; selection.current = { scope, offset: 0, id: '', placeOffset: 0 }; void readJob(reload); }
  function begin(edit: boolean) {
    if (locked || !data || draft) return; if (edit && !data.detail?.route.canManage) return;
    if (!edit) selection.current.id = '';
    draftState(routeDraft(edit ? data.detail!.route : null, data.journey.revision)); setConflict(false); setShowPicker(true); setNotice(''); void readJob(reload);
  }
  function cancelDraft() { if (working.current || state.current.pending) return; draftState(null); setConflict(false); setShowPicker(false); if (!state.current.data) selection.current.id = ''; refresh(); }
  function change(patch: Partial<RouteDraft>) { if (locked || !draft) return; draftState({ ...draft, ...patch }); setNotice(''); }
  function move(index: number, by: number) { if (!draft || locked || index + by < 0 || index + by >= draft.stops.length) return; const stops = [...draft.stops]; [stops[index], stops[index + by]] = [stops[index + by], stops[index]]; change({ stops }); setSelectedStop(index + by); }
  function rebase() {
    if (locked || !draft || !data) return;
    const original = draft.original ? data.detail?.route : null;
    if (draft.original && (!original || !original.canManage)) { setError('当前路线已不能编辑，请返回列表。'); return; }
    // Unavailable indices are tied to the old source, never silently remap them.
    if (draft.stops.some(s => 'keepUnavailableIndex' in s) && draft.original?.sourceVersion !== original?.sourceVersion) { setError('旧缺口无法对应当前路线，请先明确移除缺口，或取消编辑后重新打开。'); return; }
    const stops = draft.stops.map(s => { if (!('placeId' in s)) return s; const p = data.places.get(s.placeId);
      if (!p || draft.visibility === 'shared' && !publicRoutePlace(p)) throw new Error('请先移除不可用或未共享的地点。'); return { placeId: p.id, expectedRevision: p.revision }; });
    draftState({ ...draft, original: original ? routeOrigin(original) : null, expectedJourneyRevision: data.journey.revision, stops }); setConflict(false); setNotice('已按当前地点核对草稿，请检查顺序后保存。');
  }
  async function applyReceipt(receipt: RouteReceipt, ticket: number) {
    intentState(null); draftState(null); setDeleting(false); setConflict(false);
    selection.current.id = receipt.current?.route.id || ''; selection.current.offset = 0;
    setNotice(receipt.operation.kind === 'delete' ? '路线已删除。' : receipt.current ? '已确认保存；以下为当前可见路线。' : '已确认原操作完成，路线现已删除或不可查看。');
    // Receipt is confirmed even if its separate, currently authorized read fails.
    try { await reload(ticket); } catch (caught) { if (current(ticket)) { setData(null); state.current.data = null; fail(caught, ticket); } }
  }
  async function send(intent: RouteIntent) {
    if (!current() || working.current) return;
    const ticket = epoch.current, controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000); flight.current = controller;
    working.current = true; setBusy(true); setError(''); intentState({ ...intent, uncertain: true }); setShareChecked(false);
    try { const receipt = await sendRouteIntent(intent, job => guard(job, ticket), props.journeyId, controller.signal); if (current(ticket)) await applyReceipt(receipt, ticket); }
    catch (caught) {
      if (!current(ticket)) return;
      if (routeIntentUnknown(intent, caught)) { intentState({ ...intent, uncertain: true }); setError('保存结果尚未核实，请核对原操作。'); }
      else { intentState(null); setConflict(caught instanceof PlaceWriteRejected && caught.status === 409); setDeleting(false);
        setError(caught instanceof PlaceWriteRejected && caught.status === 409 ? '路线或地点已变化，草稿保留。请读取最新内容并重新核对。' : '保存未被接受，草稿保留。请核对选择与权限。'); }
      const underlying = caught instanceof PlaceWriteUnverified ? caught.reason : caught;
      if (caught instanceof PlaceWriteRejected && caught.status === 403) fail(new ApiError('身份或权限已变化', 403), ticket);
      else if (underlying instanceof PlaceDiscarded && underlying.message === 'identity' || underlying instanceof ApiError && [401, 403].includes(underlying.status)) fail(caught, ticket);
      else if (caught instanceof PlaceWriteUnverified) { conceal(); setError('身份核对暂未完成，内容已隐藏。重新核对身份后可查询原操作。'); }
    } finally { clearTimeout(timer); if (flight.current === controller) flight.current = null; if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function save() {
    if (locked || conflict || !draft || !data || draft.visibility === 'shared' && !shareChecked) return;
    try {
      if (draft.stops.some(s => 'placeId' in s && (!data.places.has(s.placeId) || draft.visibility === 'shared' && !publicRoutePlace(data.places.get(s.placeId)!)))) throw new Error('请先移除不可用或未共享的地点。');
      void send(routeWriteIntent(draft, props.journeyId, newKey()));
    } catch (caught) { setError(caught instanceof Error ? caught.message : '请核对路线。'); }
  }
  function recover() {
    const intent = state.current.pending; if (!intent || busy) return;
    void readJob(async ticket => {
      try {
        // /me failures must never masquerade as an absent operation.
        const outcome = await guard(async () => { try { return { found: true as const, raw: await get('/journey-routes/operations/' + intent.requestId) }; }
          catch (caught) { if (caught instanceof ApiError && caught.status === 404) return { found: false as const }; throw caught; } }, ticket);
        if (!outcome.found) { if (current(ticket)) { setNotFound(true); setNotice('尚未找到原操作回执。可稍后核对，或按原内容与原编号重试。'); } return; }
        const receipt = readRouteReceipt(outcome.raw, intent, props.journeyId);
        if (!receipt.replayed) throw new Error(); if (current(ticket)) await applyReceipt(receipt, ticket); }
      catch (caught) { throw caught; }
    });
  }
  const locked = busy || !visible || !current() || !!pending;
  const button = (label: string, action: () => void, disabled = locked, mode: 'text' | 'outlined' | 'contained' = 'outlined') => <Button accessibilityLabel={label} contentStyle={styles.touch} style={styles.button} mode={mode} disabled={disabled} onPress={action}>{label}</Button>;
  const show = visible && current(), route = data?.detail?.route;
  const stops: RouteStop[] = draft && data ? draftRouteStops(draft, data.places) : route?.stops || [];
  const map = routeGeometry(stops, draft ? adjacentRouteSegments(stops) : data?.detail?.segments || []);
  if (photos) return <TripRecapPanel journeyId={props.journeyId} initialTab="photos" backLabel="返回旅行路线" onBack={() => { state.current.photos = false; setPhotos(false); }} />;
  return <View testID="journey-routes-panel" style={styles.page}>
    <PageHeader title="旅行路线" description="安排站点顺序，把这一趟旅行串起来。" action={button('返回旅行详情', () => navigate(props.onBack), busy || !!draft || !!pending)} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}{!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对路线" />}
    {!data && draft && !pending && button('取消编辑', cancelDraft, busy)}
    {!show ? <EmptyState title={!connected() || !household.online ? '离线时隐藏路线' : '路线内容已隐藏'} description="回到前台并联网后，重新核对身份与当前内容。"
      action={button('重新读取路线', refresh, busy || denied.current || !connected() || !household.online)} /> : <>
      {pending && <SectionCard title="核对保存结果"><View testID="journey-route-recovery" style={styles.page}><Text>原操作尚未确认。不会另建一条路线。</Text>
        <Text selectable>原操作编号：{pending.requestId}</Text>{button('核对原操作', recover, busy)}
        {notFound && button('按原内容重试', () => void send(pending), busy)}
      </View></SectionCard>}
      {!data ? <EmptyState title="暂时无法读取当前路线" action={<View style={styles.actions}>{button('重新读取路线', refresh, busy)}{button('返回路线列表', () => { selection.current.id = ''; void readJob(reload); }, busy || !!draft || !!pending)}</View>} /> : <>
        <Text variant="titleMedium">{data.journey.title}</Text>
        {!draft && !route && <>
          <View style={styles.actions}>{(['mine', 'shared'] as const).map(scope => <Button key={scope} accessibilityLabel={scope === 'mine' ? '我的路线' : '家庭共享路线'} accessibilityState={{ selected: selection.current.scope === scope }} mode={selection.current.scope === scope ? 'contained' : 'outlined'} contentStyle={styles.touch} disabled={locked} onPress={() => chooseScope(scope)}>{scope === 'mine' ? '我的路线' : '家庭共享'}</Button>)}{button('新建路线', () => begin(false), locked, 'contained')}{button('刷新路线', refresh)}</View>
          {!data.list.items.length && <EmptyState title={selection.current.scope === 'mine' ? '还没有路线' : '暂无家庭共享路线'} description="先添加旅行地点，再按自己的计划安排顺序。" action={button('前往旅行地点添加', () => navigate(props.onPlaces))} />}
          {data.list.items.map(item => <SectionCard key={item.id} title={item.title}><View style={styles.page}><Text>{item.visibility === 'private' ? '仅我自己' : '家庭共享'} · {item.stopCount} 站{item.unavailableCount ? ` · ${item.unavailableCount} 处缺口` : ''}{!item.canManage ? ' · 只读' : ''}</Text>{button('查看路线 ' + item.title, () => open(item.id))}</View></SectionCard>)}
          {data.list.total > 24 && <View style={styles.actions}><Text>第 {data.list.offset / 24 + 1} 页 · 共 {data.list.total} 条</Text>{button('上一页路线', () => { selection.current.offset -= 24; void readJob(reload); }, locked || !data.list.offset)}{button('下一页路线', () => { selection.current.offset += 24; void readJob(reload); }, locked || !data.list.hasMore)}</View>}
        </>}
        {(route || draft) && <>
          {draft ? <SectionCard title={draft.original ? '编辑路线' : '新建路线'}><View testID="journey-route-editor" style={styles.page}>
            <TextInput label="路线名称" accessibilityLabel="路线名称" value={draft.title} maxLength={160} mode="outlined" outlineStyle={{ borderRadius: 8 }} disabled={locked} onChangeText={title => change({ title })} />
            <View accessibilityRole="radiogroup"><SelectionRow kind="radio" label="仅我自己" checked={draft.visibility === 'private'} disabled={locked} onPress={() => change({ visibility: 'private' })} /><SelectionRow kind="radio" label="家庭共享" checked={draft.visibility === 'shared'} disabled={locked} onPress={() => change({ visibility: 'shared' })} /></View>
            {conflict && <View style={styles.page}><Text>草稿与当前资料版本不同。原顺序保留，请核对最新名称与共享范围。</Text><View style={styles.actions}>{button('读取最新内容', refresh)}{button('按当前地点核对草稿', () => { try { rebase(); } catch (e) { setError(e instanceof Error ? e.message : '请重新核对。'); } })}</View></View>}
            <View style={styles.actions}>{button(showPicker ? '收起地点选择' : '添加站点', () => setShowPicker(!showPicker))}<Text>{draft.stops.length} / 100 站 · 同一地点可再次添加</Text></View>
            {showPicker && data.candidates && <View testID="journey-route-picker" style={styles.page}>
              {!data.candidates.items.length && <Text>本页没有可选地点。可先取消编辑，再前往旅行地点添加。</Text>}
              {data.candidates.items.map(p => <View key={p.id} style={styles.page}><Text>{p.name} · {p.visibility === 'shared' ? explanation(publicRoutePlace(p) || p) : '私人地点'}</Text>
                {button('添加站点 ' + p.name, () => change({ stops: [...draft.stops, { placeId: p.id, expectedRevision: p.revision }] }), locked || draft.stops.length >= 100 || draft.visibility === 'shared' && !publicRoutePlace(p))}</View>)}
              <View style={styles.actions}>{button('上一页地点', () => { selection.current.placeOffset -= 24; void readJob(reload); }, locked || !data.candidates.offset)}{button('下一页地点', () => { selection.current.placeOffset += 24; void readJob(reload); }, locked || !data.candidates.hasMore)}</View>
            </View>}
          </View></SectionCard> : <SectionCard title={route!.title}><View style={styles.page}><Text>{route!.visibility === 'private' ? '仅我自己' : '家庭共享'} · {route!.stops.length} 站{!route!.canManage ? ' · 只读，只有作者可以编辑' : ''}</Text>
            <View style={styles.actions}>{button('返回路线列表', () => open(''))}{route!.canManage && button('编辑路线', () => begin(true))}{button('查看旅行照片', () => { if (locked) return; conceal(); state.current.photos = true; setPhotos(true); })}{button('刷新路线', refresh)}</View>
          </View></SectionCard>}
          <SectionCard title="路线顺序示意"><View testID="journey-route-map"><WorldMap places={[]} routeMap={map} selectedRouteIndex={selectedStop} onRouteSelect={setSelectedStop} disabled={locked} onSelect={() => {}} onPick={() => {}} /></View></SectionCard>
          <View testID="journey-route-stops" style={styles.page}>
            {!stops.length && <Text>从上方添加第一站。</Text>}
            {stops.map((stop, index) => <SectionCard key={index} title={`${index + 1}. ${stop.state === 'available' ? stop.place.name : '地点已不可用'}`}><View style={styles.page}>
              {stop.state === 'available' ? <><Text>{[stop.place.city, stop.place.country].filter(Boolean).join(' · ')}{stop.place.city || stop.place.country ? ' · ' : ''}{explanation(stop.place)}</Text>
                <Text>{stop.place.status === 'visited' ? '已明确确认到访' : stop.place.status === 'planned' ? '已计划' : '想去'}{selectedStop === index ? ' · 当前站' : ''}</Text></> : <Text>保留原位置形成缺口，不推断地点名称或位置。</Text>}
              <View style={styles.actions}>{button('选中第 ' + (index + 1) + ' 站', () => setSelectedStop(index))}{draft && <>{button('上移第 ' + (index + 1) + ' 站', () => move(index, -1), locked || index === 0)}{button('下移第 ' + (index + 1) + ' 站', () => move(index, 1), locked || index + 1 === stops.length)}{button('移除第 ' + (index + 1) + ' 站', () => change({ stops: draft.stops.filter((_, i) => i !== index) }))}</>}</View>
            </View></SectionCard>)}
          </View>
          {draft && <SectionCard title="保存路线"><View style={styles.page}>
            {draft.visibility === 'shared' && <View testID="journey-route-share-review" style={styles.page}><Text>家庭成员会看到路线名称、顺序以及上方可用地点的名称和共享坐标。上方地图已按共享范围显示；私人地点不能加入共享路线。</Text>
              <SelectionRow label="已核对地点名称与坐标共享范围" checked={shareChecked} disabled={locked || conflict} onPress={() => setShareChecked(!shareChecked)} /></View>}
            <View style={styles.actions}>{button('保存路线', save, locked || conflict || !draft.stops.length || draft.visibility === 'shared' && !shareChecked, 'contained')}{button('取消编辑', cancelDraft)}</View>
          </View></SectionCard>}
          {!draft && route?.canManage && <View style={styles.page}><Divider />{!deleting ? button('删除路线', () => setDeleting(true)) : <><Text>确认删除这条路线？地点、到访状态和照片不会删除。</Text><View style={styles.actions}>{button('确认删除路线', () => void send(routeDeleteIntent(route, newKey())))}{button('保留路线', () => setDeleting(false))}</View></>}</View>}
          <Text variant="bodySmall">路线只表示安排顺序，不会自动确认到访。旅行照片按原许可读取，不推断属于某一站，也不增加电视许可。</Text>
        </>}
      </>}
    </>}
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16 }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, touch: { minHeight: 44 }, button: { alignSelf: 'flex-start', maxWidth: '100%' } });
