import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Icon, List, Portal, Text, TextInput, TouchableRipple, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { newKey } from '../lib/trips';
import type { ScreenProps } from '../lib/types';
import { PlaceDiscarded, PlaceFence, emptyFilters, emptyPlacePage, isPlaceId, placeDraft, placeLabels, placePayload, placeQuery, safeMapView, validatePlace, validatePlacePage,
  type Coordinates, type MapFilters, type MapView, type Place, type PlaceDraft, type PlacePage, type PlaceSession } from '../lib/places';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import WorldMap from '../ui/WorldMap';

type JourneyLink = { id: string; tripId: string };
type Props = ScreenProps & { initialView?: MapView; onBack?: () => void; backLabel?: string; onOpenTrip: (journey: JourneyLink, view: MapView) => void; onOpenPhotos: (journey: JourneyLink, view: MapView) => void };
type JourneyOption = JourneyLink & { title: string };
type Intent = { method: 'POST' | 'PATCH' | 'DELETE'; path: string; body: Record<string, unknown>; id?: string; state: 'unknown' | 'rejected' };
type Choice = { title: string; options: { value: string; label: string }[]; selected: string; choose: (value: string) => void };
const message = (error: unknown) => error instanceof Error ? error.message : '暂时无法完成操作，请稍后再试。';
const scopeLabels: Record<string, string> = { visible: '全部可见', mine: '仅我的', shared: '已共享' };
const disclosureLabels = { hidden: '隐藏坐标', coarse: '大致位置（约 0.1°）', exact: '精确坐标' };
const browserOnline = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const offlineNotice = '网络已断开，地点已隐藏。重新联网后会重新读取。';

function VisitConfirmation({ checked, disabled, onPress }: { checked: boolean; disabled: boolean; onPress: () => void }) {
  const theme = useTheme();
  const keyboard = Platform.OS === 'web' ? { onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === ' ' || event.key === 'Spacebar') { event.preventDefault(); event.stopPropagation(); if (!disabled && !event.repeat) onPress(); }
  } } : {};
  return <TouchableRipple {...keyboard} accessible accessibilityRole="checkbox" accessibilityLabel="我确认实际到访" accessibilityState={{ checked, disabled }} aria-checked={checked} aria-disabled={disabled}
    disabled={disabled} onPress={onPress} style={state => [styles.confirmation, { borderColor: state.focused ? theme.colors.primary : theme.colors.outlineVariant }]}>
    <View style={styles.row} pointerEvents="none" aria-hidden accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Icon source={checked ? 'checkbox-marked' : 'checkbox-blank-outline'} size={24} color={theme.colors.primary} />
      <Text style={styles.flex}>我确认实际到访</Text>
    </View>
  </TouchableRipple>;
}

export default function MapScreen(props: Props) {
  const household = useHousehold();
  if (props.user.role !== 'member') return <EmptyState title="请用成员账户查看足迹" description="电视不读取地点详情。" />;
  return <MapWorkspace key={household.identityKey} {...props} identityKey={household.identityKey} />;
}

function MapWorkspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), wide = useWindowDimensions().width >= 1040;
  const latest = useRef(household); latest.current = household;
  const initial = useRef(safeMapView(props.initialView));
  const alive = useRef(false), active = useRef(false), focused = useRef(false), working = useRef(false), generation = useRef(0);
  const appActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PlaceFence(() => request<PlaceSession>('/me'), props.identityKey));
  const [visible, setVisible] = useState(false), [denied, setDenied] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [filters, setFilters] = useState(initial.current.filters), [filterDraft, setFilterDraft] = useState(initial.current.filters), [filterOpen, setFilterOpen] = useState(false);
  const [page, setPage] = useState<PlacePage>({ ...emptyPlacePage(), offset: initial.current.offset });
  const [selected, setSelected] = useState(initial.current.selected), [place, setPlace] = useState<Place | null>(null), [journeys, setJourneys] = useState<JourneyOption[]>([]);
  const [draft, setDraft] = useState<PlaceDraft | null>(null), [pending, setPending] = useState<Intent | null>(null), [picking, setPicking] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null), [decision, setDecision] = useState<'discard' | 'delete' | null>(null);
  const state = useRef({ filters, page, selected, place, draft, pending }); state.current = { filters, page, selected, place, draft, pending };
  const current = () => alive.current && active.current && appActive.current && browserOnline() && latest.current.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  const locked = busy || !!pending || !household.online;
  const navigationLocked = locked || !!draft;

  function clearPrivate() {
    setPage(emptyPlacePage()); setSelected(undefined); setPlace(null); setJourneys([]); setDraft(null); setPending(null); setChoice(null); setDecision(null); setPicking(false);
    setFilters(emptyFilters()); setFilterDraft(emptyFilters()); setFilterOpen(false); setError(''); setNotice('');
    state.current = { filters: emptyFilters(), page: emptyPlacePage(), selected: undefined, place: null, draft: null, pending: null };
  }
  function conceal(clear = false) {
    active.current = false; ++generation.current; fence.current.invalidate(); setVisible(false); setBusy(false); working.current = false;
    setChoice(null); setDecision(null); if (clear) clearPrivate();
  }
  function fail(caught: unknown) {
    if (!current()) return;
    if (caught instanceof PlaceDiscarded && caught.message !== 'identity') return;
    if (caught instanceof PlaceDiscarded || caught instanceof ApiError && [401, 403].includes(caught.status)) {
      conceal(true); setDenied(true); void latest.current.refresh(); return;
    }
    if (caught instanceof ApiError && [404, 410].includes(caught.status)) {
      clearPrivate(); setError('地点或关联旅行已移除，或不再对你可见。旧详情和草稿已清空。'); return;
    }
    setError(message(caught));
  }
  async function read<T>(path: string): Promise<T> { return fence.current.run(() => request<T>(path), current); }
  async function readPlace(id: string): Promise<Place> {
    if (!isPlaceId(id)) throw new Error('地点编号无效。');
    const value = validatePlace((await read<{ place: Place }>(`/journey-places/${id}`)).place);
    if (value.id !== id) throw new Error('地点已变化，请重新打开。'); return value;
  }
  async function readPage(nextFilters: MapFilters, offset: number) {
    return validatePlacePage(await read<PlacePage>(`/journey-places?${placeQuery(nextFilters, offset)}`), offset);
  }
  async function readJourneys() {
    const value = await read<{ journeys: { id: string; tripId: string; trip?: { title?: string }; plan?: { title?: string } }[] }>('/journeys');
    if (!value || !Array.isArray(value.journeys) || value.journeys.some(row => !isPlaceId(row.id) || !isPlaceId(row.tripId) || typeof (row.trip?.title || row.plan?.title) !== 'string')) throw new Error('旅行列表暂时无法核对。');
    return value.journeys.map(row => ({ id: row.id, tripId: row.tripId, title: row.trip?.title || row.plan?.title || '' }));
  }
  async function refreshView(nextFilters = state.current.filters, offset = state.current.page.offset, target = state.current.selected) {
    const values = await readPage(nextFilters, offset), options = await readJourneys();
    // A search/deep-link target may be outside this page. Only the freshly
    // authorized original-ID endpoint decides whether its detail is visible.
    const id = isPlaceId(target) ? target : undefined;
    const detail = id ? await readPlace(id) : null;
    if (!current()) return;
    setPage(values); setFilters(nextFilters);
    // A same-filter refresh must not overwrite unfinished filter input.
    if (nextFilters !== state.current.filters) setFilterDraft(nextFilters);
    setJourneys(options); setSelected(id); setPlace(detail);
  }
  async function checkDraft() {
    await fence.current.run(async () => true, current);
    const saved = state.current;
    if (saved.pending?.method === 'DELETE' && saved.pending.state === 'unknown') return;
    const id = saved.draft?.id || saved.pending?.id;
    if (id && !(await readPlace(id)).canManage) throw new PlaceDiscarded('identity');
    const values = await readPage(saved.filters, saved.page.offset), options = await readJourneys();
    if (current()) { setPage(values); setJourneys(options); }
    // Never adopt a newer revision while checking a preserved draft.
  }
  function enter() {
    if (!alive.current || active.current || !focused.current || !appActive.current || !browserOnline() || !latest.current.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; working.current = true; setBusy(true); setDenied(false);
    fence.current = new PlaceFence(() => request<PlaceSession>('/me'), props.identityKey);
    const ticket = generation.current;
    void (async () => {
      try {
        if (state.current.draft || state.current.pending) { await checkDraft(); if (current()) setNotice('已重新核对身份与权限，原输入仍保留。'); }
        else await refreshView();
        if (current() && ticket === generation.current) setVisible(true);
      } catch (caught) { fail(caught); if (current() && ticket === generation.current) { active.current = false; } }
      finally { if (ticket === generation.current) { working.current = false; if (alive.current) setBusy(false); } }
    })();
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++generation.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(true); }; }, [props.identityKey]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); };
    const offline = () => { conceal(); setError(offlineNotice); };
    const online = () => { setError(previous => previous === offlineNotice ? '' : previous); enter(); };
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', online); }
    const subscription = AppState.addEventListener('change', value => { appActive.current = value === 'active'; if (appActive.current) enter(); else conceal(); });
    return () => {
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', online); }
      subscription.remove();
    };
  }, [props.identityKey]);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  useEffect(() => {
    if (!visible || denied) return;
    const timer = setInterval(() => {
      if (!current() || working.current) return;
      void runRead(async () => { if (state.current.draft || state.current.pending) await checkDraft(); else await refreshView(); }, false);
    }, 15000);
    return () => clearInterval(timer);
  }, [visible, denied]);
  async function runRead(job: () => Promise<void>, showBusy = true) {
    if (!current() || working.current) return;
    working.current = true; const ticket = generation.current; if (showBusy) { setBusy(true); setError(''); }
    try { await job(); } catch (caught) { fail(caught); }
    finally { if (ticket === generation.current) { working.current = false; if (current() && showBusy) setBusy(false); } }
  }
  function change(patch: Partial<PlaceDraft>) {
    // Permission polling keeps its request lock but never replaces the draft.
    // Allow normal input while that background read is in flight.
    if (locked) return;
    setDraft(value => value ? { ...value, ...patch, ...(['name', 'country', 'city', 'latitude', 'longitude', 'startDate', 'endDate', 'journeyId', 'status'].some(key => key in patch) ? { confirmed: false } : {}) } : null);
  }
  function begin(placeToEdit?: Place) {
    if (navigationLocked || working.current) return;
    setDraft(placeDraft(placeToEdit)); setPicking(false); setError(''); setNotice(''); setFilterOpen(false);
  }
  async function openPlace(id: string) {
    if (navigationLocked) return;
    await runRead(async () => { const value = await readPlace(id); if (current()) { setSelected(id); setPlace(value); setNotice(''); } });
  }
  async function navigate(kind: 'trip' | 'photos') {
    if (navigationLocked || !place?.journeyId) return;
    await runRead(async () => {
      const saved = state.current, detail = await readPlace(place.id);
      if (!current() || state.current.draft || state.current.pending || saved.selected !== state.current.selected) return;
      if (!detail.journey || detail.journeyId !== detail.journey.id) { setPlace(detail); setNotice('这个地点已不再关联旅行。'); return; }
      const view: MapView = { filters: { ...saved.filters }, offset: saved.page.offset, selected: detail.id };
      (kind === 'trip' ? props.onOpenTrip : props.onOpenPhotos)({ id: detail.journey.id, tripId: detail.journey.tripId }, view);
    });
  }
  async function accept(result: { place?: Place; deleted?: boolean; id?: string; replayed?: boolean }, intent: Intent) {
    if (intent.method === 'DELETE') {
      if (result.deleted !== true || result.id !== intent.id) throw new Error('删除结果暂时无法核对。');
    } else if (!result.place || validatePlace(result.place).id !== (intent.id || result.place.id)) throw new Error('保存结果暂时无法核对。');
    if (!current()) return;
    setPending(null); setDraft(null); setDecision(null); setPicking(false); setError('');
    const next = result.place || null; setPlace(next); setSelected(next?.id);
    setNotice(intent.method === 'DELETE' ? '地点已删除，关联旅行和照片保持原样。' : result.replayed ? '已核对原创建，没有重复添加。' : '地点已保存。');
    // Confirmed writes stay confirmed even if the following list refresh fails.
    try {
      const values = await readPage(state.current.filters, 0);
      if (current()) setPage(values);
    } catch (caught) { fail(caught); }
    void latest.current.refresh();
  }
  async function send(intent: Intent) {
    if (!current() || working.current) return;
    working.current = true; const ticket = generation.current; setBusy(true); setError(''); setPending(intent);
    try {
      const result = await fence.current.run(csrf => request<{ place?: Place; deleted?: boolean; id?: string; replayed?: boolean }>(intent.path, { method: intent.method, body: JSON.stringify(intent.body) }, csrf), current);
      await accept(result, intent);
    } catch (caught) {
      if (!current()) return;
      if (caught instanceof PlaceDiscarded || caught instanceof ApiError && [401, 403, 404, 410].includes(caught.status)) { fail(caught); return; }
      const rejected = caught instanceof ApiError && caught.status >= 400 && caught.status < 500;
      setPending({ ...intent, state: rejected ? 'rejected' : 'unknown' });
      setError(rejected ? message(caught) + ' 输入仍保留，请核对后再确认。' : '保存结果尚未确定。请先核对原操作，避免重复添加。');
    } finally { if (ticket === generation.current) { working.current = false; if (current()) setBusy(false); } }
  }
  function save() {
    if (!draft || locked || working.current) return;
    try {
      const body = placePayload(draft, draft.id ? place : null);
      if (draft.id) {
        if (!place?.canManage || place.id !== draft.id) throw new Error('请重新打开本人地点后编辑。');
        void send({ path: `/journey-places/${place.id}`, method: 'PATCH', id: place.id, body: { ...body, revision: place.revision }, state: 'unknown' });
      } else void send({ path: '/journey-places', method: 'POST', body: { ...body, requestId: newKey() }, state: 'unknown' });
    } catch (caught) { setError(message(caught)); }
  }
  async function recover() {
    if (!pending || busy || working.current || !household.online) return;
    if (pending.state === 'unknown' && ['POST', 'DELETE'].includes(pending.method)) { await send(pending); return; }
    await runRead(async () => {
      const intent = pending;
      if (intent.id) {
        const value = await readPlace(intent.id);
        if (!value.canManage) throw new PlaceDiscarded('identity');
        if (!current()) return;
        setPlace(value);
        // A fresh version is shown for explicit reconfirmation, never auto-saved.
        setDraft(previous => previous ? { ...previous, confirmed: false } : previous);
      } else await fence.current.run(async () => true, current);
      if (!current()) return;
      setPending(null); setDecision(null); setNotice('最新版本已读取，原输入仍保留。请核对后再次保存。');
    });
  }
  function pick(point: Coordinates) { change({ latitude: String(point.latitude), longitude: String(point.longitude) }); }
  function options(title: string, rows: { value: string; label: string }[], selectedValue: string, choose: (value: string) => void) {
    if (locked || working.current) return; setChoice({ title, options: rows, selected: selectedValue, choose });
  }
  const journeyOptions = [{ value: '', label: '不关联旅行' }, ...journeys.map(journey => ({ value: journey.id, label: journey.title }))];
  const field = (label: string, key: keyof PlaceDraft, extra: object = {}) => <TextInput mode="outlined" label={label} accessibilityLabel={label} value={String(draft?.[key] || '')} disabled={locked} onChangeText={value => change({ [key]: value })} style={styles.field} {...extra} />;
  const disclosure = place?.coordinatePrecision === 'approximate' ? '大致位置，已按 0.1° 网格粗化' : place?.coordinatePrecision === 'hidden' ? '创建者已隐藏坐标' : place?.coordinates ? '已记录位置' : '未填写坐标';

  const back = props.onBack ? <Button icon="arrow-left" disabled={busy || !!draft || !!pending} onPress={() => {
    if (alive.current && focused.current && !draft && !pending && !working.current) props.onBack?.();
  }}>{props.backLabel || '返回旅行'}</Button> : null;
  if (!visible) return <View style={styles.loading}>{back}<ActivityIndicator animating={busy} /><Text>{denied ? '登录身份或权限已变化，请重新打开地图。' : error || '正在核对身份和地点访问权限…'}</Text><Button disabled={busy || !household.online} onPress={enter}>重新读取地图</Button></View>;
  return <>
    {back}
    <PageHeader title="足迹地图" description="想去哪里，去过哪里。把地点、旅行和照片放在一起。" action={<Button mode="contained" icon="plus" disabled={navigationLocked} onPress={() => begin()}>添加地点</Button>} />
    {error ? <Text accessibilityRole="alert" style={{ color: theme.colors.error, marginBottom: 14 }}>{error}</Text> : null}
    {notice ? <Text accessibilityLiveRegion="polite" style={styles.notice}>{notice}</Text> : null}
    {pending ? <SectionCard title={pending.state === 'unknown' ? '先核对这次操作' : '请核对最新版本'} style={styles.bottom}>
      <Text>{pending.state === 'unknown' ? '原输入与操作标识已保留。创建会用同一份内容和标识核对，修改会先读取最新结果。' : '保存没有完成，原输入仍保留。读取新版本后由你再次确认。'}</Text>
      <Button mode="contained" style={styles.top} disabled={busy || !household.online} onPress={() => void recover()}>{pending.state === 'unknown' && pending.method === 'POST' ? '核对原创建' : pending.state === 'unknown' && pending.method === 'DELETE' ? '核对原删除' : '核对最新版本'}</Button>
    </SectionCard> : null}
    {draft ? <SectionCard title={draft.id ? '编辑地点' : '添加一个地点'}>
      <View style={styles.form}>
        {draft.id && place && notice.startsWith('最新版本已读取') ? <View style={styles.form}><Text variant="titleSmall">当前保存的版本 {place.revision}</Text><Text>{place.name} · {placeLabels[place.status]} · {[place.country, place.city].filter(Boolean).join(' / ') || '未填城市'}</Text><Text>{place.startDate || '未填日期'}{place.endDate ? ' 至 ' + place.endDate : ''} · {place.journey?.title || '未关联旅行'}</Text><Text>{place.coordinates ? `${place.coordinates.latitude}，${place.coordinates.longitude}` : '未填坐标'} · {place.visibility === 'private' ? '仅本人' : `家庭共享 / ${disclosureLabels[place.coordinateDisclosure]}`}</Text><Text variant="bodySmall">下方保留你的输入，请逐项核对后保存。</Text><Divider /></View> : null}
        {field('地点名称', 'name', { maxLength: 160, style: { minWidth: 0 } })}
        <View style={styles.fields}>{field('国家或地区', 'country', { maxLength: 100 })}{field('城市', 'city', { maxLength: 100 })}</View>
        <Button mode="outlined" disabled={locked} onPress={() => options('地点状态', Object.entries(placeLabels).map(([value, label]) => ({ value, label })), draft.status, value => change({ status: value as Place['status'] }))}>状态：{placeLabels[draft.status]}</Button>
        <View style={styles.fields}>{field('开始日期', 'startDate', { placeholder: 'YYYY-MM-DD' })}{field('结束日期', 'endDate', { placeholder: 'YYYY-MM-DD' })}</View>
        <Button mode="outlined" disabled={locked} onPress={() => options('关联旅行', journeyOptions, draft.journeyId, value => change({ journeyId: value }))}>旅行：{journeys.find(row => row.id === draft.journeyId)?.title || '不关联旅行'}</Button>
        <Text variant="titleSmall">位置（可选）</Text>
        <View style={styles.fields}>{field('纬度', 'latitude', { inputMode: 'decimal' })}{field('经度', 'longitude', { inputMode: 'decimal' })}</View>
        <Button mode="text" disabled={locked} icon="map-marker-outline" onPress={() => setPicking(value => !value)}>{picking ? '收起地图选点' : '在地图上选点'}</Button>
        {picking ? <WorldMap places={[]} picking disabled={locked} picked={draft.latitude && draft.longitude ? { latitude: Number(draft.latitude), longitude: Number(draft.longitude) } : null} onSelect={() => {}} onPick={pick} /> : null}
        <Divider />
        <Text variant="titleSmall">谁可以看到</Text>
        <Button mode="outlined" disabled={locked} onPress={() => options('共享范围', [{ value: 'private', label: '仅本人' }, { value: 'shared', label: '家庭共享' }], draft.visibility, value => change({ visibility: value as Place['visibility'] }))}>可见范围：{draft.visibility === 'private' ? '仅本人' : '家庭共享'}</Button>
        {draft.visibility === 'shared' ? <><Button mode="outlined" disabled={locked} onPress={() => options('共享坐标精度', Object.entries(disclosureLabels).map(([value, label]) => ({ value, label })), draft.coordinateDisclosure, value => change({ coordinateDisclosure: value as Place['coordinateDisclosure'] }))}>{disclosureLabels[draft.coordinateDisclosure]}</Button><Text variant="bodySmall">名称、城市和日期会共同可见，可能透露具体地点；隐藏坐标不会隐藏这些文字。电视许可另行管理。</Text></> : null}
        {draft.status === 'visited' ? <><VisitConfirmation checked={draft.confirmed} disabled={locked} onPress={() => change({ confirmed: !draft.confirmed })} /><Text variant="bodySmall">请根据实际经历确认。修改地点、日期或旅行后需要重新确认。</Text></> : null}
        <View style={styles.actions}><Button mode="contained" disabled={locked} loading={busy} onPress={save}>保存地点</Button><Button disabled={busy || !!pending} onPress={() => setDecision('discard')}>取消编辑</Button></View>
      </View>
    </SectionCard> : <>
      <View style={[styles.row, styles.bottom]}><Button mode="outlined" icon="filter-variant" disabled={navigationLocked} onPress={() => setFilterOpen(value => !value)}>筛选地点</Button><Button icon="refresh" disabled={navigationLocked} onPress={() => void runRead(() => refreshView())}>刷新地点</Button>{busy ? <ActivityIndicator size="small" /> : null}</View>
      {filterOpen ? <SectionCard title="筛选地点" style={styles.bottom}><View style={styles.form}>
        <View style={styles.actions}>
          <Button mode="outlined" disabled={navigationLocked} onPress={() => options('可见范围', Object.entries(scopeLabels).map(([value, label]) => ({ value, label })), filterDraft.scope, value => setFilterDraft(previous => ({ ...previous, scope: value })))}>范围：{scopeLabels[filterDraft.scope]}</Button>
          <Button mode="outlined" disabled={navigationLocked} onPress={() => options('地点状态', [{ value: '', label: '全部状态' }, ...Object.entries(placeLabels).map(([value, label]) => ({ value, label }))], filterDraft.status, value => setFilterDraft(previous => ({ ...previous, status: value })))}>状态：{placeLabels[filterDraft.status as Place['status']] || '全部状态'}</Button>
        </View>
        <TextInput mode="outlined" label="年份" accessibilityLabel="年份" value={filterDraft.year} maxLength={4} inputMode="numeric" disabled={navigationLocked} onChangeText={year => setFilterDraft(previous => ({ ...previous, year }))} placeholder="例如 2026；留空看全部" />
        <Button mode="outlined" disabled={navigationLocked} onPress={() => options('按成员筛选', [{ value: '', label: '全部成员' }, ...props.state.people.map(person => ({ value: person.id, label: person.name }))], filterDraft.owner, value => setFilterDraft(previous => ({ ...previous, owner: value })))}>成员：{props.state.people.find(person => person.id === filterDraft.owner)?.name || '全部成员'}</Button>
        <Button mode="outlined" disabled={navigationLocked} onPress={() => options('按旅行筛选', [{ value: '', label: '全部旅行' }, ...journeys.map(journey => ({ value: journey.id, label: journey.title }))], filterDraft.journeyId, value => setFilterDraft(previous => ({ ...previous, journeyId: value })))}>旅行：{journeys.find(journey => journey.id === filterDraft.journeyId)?.title || '全部旅行'}</Button>
        <View style={styles.actions}><Button mode="contained" disabled={navigationLocked} onPress={() => {
          if (filterDraft.year && (!/^\d{4}$/.test(filterDraft.year) || Number(filterDraft.year) < 1)) { setError('年份请填四位数字，或留空。'); return; }
          void runRead(() => refreshView({ ...filterDraft }, 0, undefined));
        }}>应用筛选</Button><Button disabled={navigationLocked} onPress={() => void runRead(() => refreshView(emptyFilters(), 0, undefined))}>重置筛选</Button></View>
      </View></SectionCard> : null}
      <SectionCard title="世界概览" style={styles.bottom}><WorldMap places={place && !page.items.some(row => row.id === place.id) ? [...page.items, place] : page.items} selected={selected} disabled={navigationLocked} onSelect={id => void openPlace(id)} onPick={() => {}} /><Text variant="bodySmall" style={styles.top}>共 {page.total} 个地点 · 本页 {page.items.length} 个 · {page.items.filter(row => !row.coordinates).length} 个无可显示坐标</Text></SectionCard>
      <View style={[styles.panels, wide && styles.panelsWide]}>
        <SectionCard title="地点" style={[styles.panel, wide && styles.widePanel, wide && styles.listPanel]}>
          {page.items.length ? page.items.map(row => <List.Item key={row.id} title={row.name} titleNumberOfLines={2} description={`${placeLabels[row.status]} · ${[row.country, row.city].filter(Boolean).join(' / ') || '未填城市'} · ${row.visibility === 'private' ? '仅本人' : '共享'}`} descriptionNumberOfLines={2} accessible accessibilityRole="button" accessibilityLabel={`打开地点：${row.name}`} onPress={() => void openPlace(row.id)} disabled={navigationLocked}
            left={iconProps => <List.Icon {...iconProps} icon={row.status === 'visited' ? 'map-marker-check-outline' : row.status === 'planned' ? 'calendar-outline' : 'heart-outline'} />} style={row.id === selected ? { backgroundColor: theme.colors.surface, borderRadius: 16 } : undefined} />) : <EmptyState title="这里还没有地点" description="添加一个想去的地方，或调整筛选。" />}
          <View style={[styles.actions, styles.top]}><Button disabled={navigationLocked || page.offset === 0} onPress={() => void runRead(() => refreshView(filters, Math.max(0, page.offset - 24), undefined))}>上一页</Button><Text>第 {Math.floor(page.offset / 24) + 1} 页</Text><Button disabled={navigationLocked || !page.hasMore} onPress={() => void runRead(() => refreshView(filters, page.offset + 24, undefined))}>下一页</Button></View>
        </SectionCard>
        <SectionCard title={place?.name || '地点详情'} style={[styles.panel, wide && styles.widePanel]}>
          {place ? <View style={styles.form}>
            <Text variant="labelLarge">{placeLabels[place.status]} · {place.visibility === 'private' ? '仅本人可见' : '家庭共享'}</Text>
            <Text>{[place.country, place.city].filter(Boolean).join(' / ') || '尚未填写国家和城市'}</Text>
            <Text>{place.startDate ? `${place.startDate}${place.endDate ? ' 至 ' + place.endDate : ''}` : '尚未填写日期'}</Text>
            <Text>{disclosure}{place.coordinates ? `：${place.coordinates.latitude}，${place.coordinates.longitude}` : ''}</Text>
            {place.canManage && place.visibility === 'shared' ? <Text variant="bodySmall">向家人共享：{disclosureLabels[place.coordinateDisclosure]}。以上为你自己的位置。</Text> : null}
            {place.status === 'visited' ? <Text variant="bodySmall">创建者已明确确认到访</Text> : null}
            {place.journey ? <><Divider /><Text variant="titleSmall">关联旅行：{place.journey.title}</Text><View style={styles.actions}><Button mode="contained" disabled={navigationLocked} onPress={() => void navigate('trip')}>查看旅行</Button><Button mode="outlined" disabled={navigationLocked} onPress={() => void navigate('photos')}>查看旅行照片</Button></View><Text variant="bodySmall">只显示当前可查看的照片；地点共享不会同时共享相册。</Text></> : <Text variant="bodySmall">尚未关联旅行</Text>}
            {place.canManage ? <View style={styles.actions}><Button mode="outlined" disabled={navigationLocked} onPress={() => begin(place)}>编辑地点</Button><Button textColor={theme.colors.error} disabled={navigationLocked} onPress={() => setDecision('delete')}>删除地点</Button></View> : <Text variant="bodySmall">这是家人共享的地点，只有创建者可以编辑。</Text>}
          </View> : <EmptyState title="选一个地点看看" description="点地图标记或左侧列表，查看旅行与照片。" />}
        </SectionCard>
      </View>
    </>}
    <Portal>
      <Dialog visible={!!choice} onDismiss={() => setChoice(null)} style={styles.dialog}><Dialog.Title>{choice?.title}</Dialog.Title><Dialog.ScrollArea style={{ maxHeight: 360 }}><ScrollView><List.Section>{choice?.options.map(row => <Button key={row.value} mode={row.value === choice.selected ? 'contained-tonal' : 'text'} accessibilityLabel={row.label} disabled={locked} onPress={() => { choice.choose(row.value); setChoice(null); }} style={styles.option}>{row.label}</Button>)}</List.Section></ScrollView></Dialog.ScrollArea><Dialog.Actions><Button onPress={() => setChoice(null)}>关闭选择</Button></Dialog.Actions></Dialog>
      <Dialog visible={!!decision} onDismiss={() => { if (!busy) setDecision(null); }} style={styles.dialog}><Dialog.Title>{decision === 'delete' ? '删除这个地点？' : '放弃这次编辑？'}</Dialog.Title><Dialog.Content><Text>{decision === 'delete' ? '只删除地点记录，旅行和照片保持原样。' : '尚未保存的输入将被清空。'}</Text></Dialog.Content><Dialog.Actions><Button disabled={busy} onPress={() => setDecision(null)}>继续保留</Button><Button disabled={busy || !!pending} onPress={() => {
        if (decision === 'discard') { setDraft(null); setPicking(false); setDecision(null); setError(''); }
        else if (place?.canManage) { setDecision(null); void send({ path: `/journey-places/${place.id}`, method: 'DELETE', id: place.id, body: { revision: place.revision }, state: 'unknown' }); }
      }}>{decision === 'delete' ? '确认删除地点' : '放弃编辑'}</Button></Dialog.Actions></Dialog>
    </Portal>
  </>;
}

const styles = StyleSheet.create({
  loading: { alignItems: 'center', gap: 16, padding: 28 }, flex: { flex: 1, minWidth: 0 }, row: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 10 },
  form: { gap: 16 }, fields: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, field: { flexGrow: 1, flexBasis: 140, minWidth: 0 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, bottom: { marginBottom: 20 }, top: { marginTop: 14 }, notice: { marginBottom: 14 },
  panels: { gap: 20 }, panelsWide: { flexDirection: 'row', alignItems: 'flex-start' }, panel: { minWidth: 0 }, widePanel: { flexGrow: 1, flexBasis: 0 }, listPanel: { maxWidth: '48%' },
  confirmation: { padding: 14, borderWidth: 1, borderRadius: 12 }, dialog: { maxWidth: 560, width: '92%', alignSelf: 'center' }, option: { marginVertical: 4 },
});
