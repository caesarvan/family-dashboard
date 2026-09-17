import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Dialog, Divider, Portal, Text, TextInput } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { newKey } from '../lib/trips';
import { PlaceDiscarded, PlaceFence, emptyPlacePage, placeDraft, placeLabels, validatePlace, validatePlacePage, type MapView, type Place, type PlaceDraft, type PlacePage, type PlaceSession } from '../lib/places';
import { checkedPlaceMutation, destinationEditor, failedPlaceIntent, journeyPlacePayload, journeyPlaceView, placeReadbackNeedsConceal, PlaceWriteRejected, PlaceWriteUnverified, readJourneyPlaceSource, type JourneyPlaceEditor, type JourneyPlaceSource, type PlaceIntent } from '../lib/journeyPlaces';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = { journeyId: string; onOpenMap: (view: MapView) => void; onBack: () => void };
const online = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const message = (error: unknown) => error instanceof Error ? error.message : '暂时无法核对地点。';
export default function JourneyPlacesPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member') return <EmptyState title="请用成员账户查看旅行地点" />;
  if (!/^[a-f0-9]{24}$/.test(props.journeyId)) return <EmptyState title="旅行编号无法核对" action={<Button onPress={props.onBack}>返回旅行</Button>} />;
  return <Workspace key={household.identityKey + ':' + props.journeyId} {...props} identityKey={household.identityKey} />;
}
function Workspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), latest = useRef(household); latest.current = household;
  const alive = useRef(false), focused = useRef(false), active = useRef(false), working = useRef(false), epoch = useRef(0);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const fence = useRef(new PlaceFence(() => request<PlaceSession>('/me'), props.identityKey));
  const [visible, setVisible] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [source, setSource] = useState<JourneyPlaceSource | null>(null), [page, setPage] = useState<PlacePage>(emptyPlacePage);
  const [editor, setEditor] = useState<JourneyPlaceEditor | null>(null), [review, setReview] = useState<JourneyPlaceSource | null>(null);
  const [pending, setPending] = useState<PlaceIntent | null>(null), [saved, setSaved] = useState<Place | null>(null), [terminal, setTerminal] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const state = useRef({ source, page, editor, pending }); state.current = { source, page, editor, pending };
  const current = (ticket = epoch.current) => alive.current && active.current && focused.current && foreground.current && ticket === epoch.current
    && online() && latest.current.online && latest.current.identityKey === props.identityKey && (typeof document === 'undefined' || !document.hidden);
  const locked = busy || !!pending || !!review || !household.online;
  function conceal(clear = false) {
    active.current = false; ++epoch.current; fence.current.invalidate(); working.current = false; setBusy(false); setVisible(false); setLeaving(false);
    if (clear) { setSource(null); setPage(emptyPlacePage()); setEditor(null); setPending(null); setReview(null); setSaved(null); setNotice(''); }
  }
  function fail(failure: unknown, ticket: number) {
    if (!current(ticket)) return;
    if (failure instanceof PlaceDiscarded && failure.message !== 'identity') return;
    if (failure instanceof PlaceDiscarded || failure instanceof ApiError && [401, 403].includes(failure.status)) {
      conceal(true); setError('登录身份或权限已变化，请返回旅行重新打开。'); void latest.current.refresh(); return;
    }
    if (failure instanceof ApiError && [404, 410].includes(failure.status)) {
      if (state.current.pending?.uncertain) { setTerminal(true); setError('原记录已删除或关联已不可读取，请先返回核对；不会重新创建。'); return; }
      setSource(null); setPage(emptyPlacePage()); setEditor(null); setReview(null); setSaved(null); setTerminal(true);
    }
    setError(message(failure));
  }
  async function guarded<T>(job: (csrf: string) => Promise<T>, ticket: number) { return fence.current.run(job, () => current(ticket)); }
  async function getSource(ticket: number) { return readJourneyPlaceSource(await guarded(() => request<unknown>('/journeys/' + props.journeyId), ticket), props.journeyId); }
  async function getPage(offset: number, ticket: number) {
    const query = new URLSearchParams({ journeyId: props.journeyId, scope: 'visible', limit: '24', offset: String(offset) });
    return validatePlacePage(await guarded(() => request<PlacePage>('/journey-places?' + query), ticket), offset);
  }
  async function getPlace(id: string, ticket: number) {
    const value = validatePlace((await guarded(() => request<{ place: Place }>('/journey-places/' + id), ticket)).place);
    if (value.id !== id) throw new Error('地点返回结果无法核对。'); return value;
  }
  async function reload(ticket: number, offset = state.current.page.offset) {
    const fresh = await getSource(ticket), rows = await getPage(offset, ticket); if (!current(ticket)) return;
    setPage(rows);
    if (state.current.editor && state.current.editor.sourceRevision !== fresh.revision) setReview(fresh);
    else setSource(fresh);
  }
  async function readJob(job: (ticket: number) => Promise<void>) {
    if (!current() || working.current) return;
    working.current = true; setBusy(true); setError(''); const ticket = epoch.current;
    try { await job(ticket); } catch (failure) { fail(failure, ticket); }
    finally { if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function enter() {
    if (!alive.current || active.current || !focused.current || !foreground.current || !online() || !latest.current.online || typeof document !== 'undefined' && document.hidden) return;
    active.current = true; const ticket = epoch.current; working.current = true; setBusy(true);
    void (async () => {
      try {
        if (state.current.pending?.uncertain) await guarded(async () => true, ticket);
        else await reload(ticket);
        if (current(ticket)) setVisible(true);
      } catch (failure) { fail(failure, ticket); if (current(ticket)) conceal(); }
      finally { if (current(ticket)) { working.current = false; setBusy(false); } }
    })();
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(true); }; }, [props.identityKey, props.journeyId]));
  useEffect(() => {
    const visibility = () => { if (document.hidden) conceal(); else enter(); };
    const offline = () => { conceal(); setError('离线时隐藏旅行地点，联网后重新核对。'); }, connected = () => enter();
    const subscription = AppState.addEventListener('change', next => { foreground.current = next === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('offline', offline); window.addEventListener('online', connected); }
    return () => { subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility); if (typeof window !== 'undefined') { window.removeEventListener('offline', offline); window.removeEventListener('online', connected); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);
  useEffect(() => {
    const timer = setInterval(() => { if (visible && current() && !working.current && !state.current.pending) void readJob(ticket => reload(ticket)); }, 15000);
    return () => clearInterval(timer);
  }, [visible]);
  function back() { if (busy || pending && !terminal) return; conceal(true); props.onBack(); }
  function change(patch: Partial<PlaceDraft>) { if (!locked) setEditor(value => value ? { ...value, draft: { ...value.draft, ...patch, ...(!Object.hasOwn(patch, 'confirmed') ? { confirmed: false } : {}) } } : value); }
  function choose(key: string) {
    if (locked || editor || !source) return;
    void readJob(async ticket => { const fresh = await getSource(ticket); if (!current(ticket)) return; setSource(fresh); setEditor(destinationEditor(fresh, key)); setSaved(null); setReview(null); setNotice('核对文字与日期后再保存。尚未新增地点。'); });
  }
  function edit(id: string) {
    if (locked || editor) return;
    void readJob(async ticket => {
      const fresh = await getSource(ticket), place = await getPlace(id, ticket);
      if (!place.canManage || place.journeyId !== props.journeyId) throw new Error('这个地点已不能在本次旅行中编辑，请重新读取。');
      if (current(ticket)) { setSource(fresh); setEditor({ sourceRevision: fresh.revision, original: place, draft: placeDraft(place) }); setReview(null); setSaved(null); setNotice(''); }
    });
  }
  async function send(intent: PlaceIntent) {
    if (!current() || working.current) return;
    const ticket = epoch.current; working.current = true; setBusy(true); setError(''); setTerminal(false);
    // Before sending, the in-memory recovery state assumes the reply can be lost.
    setPending({ ...intent, state: 'unknown', uncertain: true });
    try {
      const response = await checkedPlaceMutation(action => guarded(action, ticket),
        csrf => request<{ place: Place; replayed?: boolean }>(intent.path, { method: intent.method, body: JSON.stringify(intent.body) }, csrf),
        failure => failure instanceof ApiError ? failure.status : undefined);
      const place = validatePlace(response.place); if (intent.id && intent.id !== place.id) throw new Error('地点保存结果无法核对。');
      if (!current(ticket)) return;
      setPending(null); setEditor(null); setReview(null); setSaved(place); setNotice(response.replayed ? '已核对原创建，没有重复添加。' : '地点已保存。');
      // A confirmed write is not made uncertain by a failing follow-up GET.
      try { await reload(ticket, 0); }
      catch (failure) {
        if (current(ticket)) {
          if (placeReadbackNeedsConceal(failure, failure instanceof PlaceDiscarded)) fail(failure, ticket);
          else setError('地点已保存；' + message(failure));
        }
      }
    } catch (failure) {
      if (!current(ticket)) return;
      const original = failure instanceof PlaceWriteUnverified ? failure.reason : failure;
      if (original instanceof PlaceDiscarded) { fail(original, ticket); return; }
      const nextPending = failedPlaceIntent(intent, failure);
      setPending(nextPending);
      if (failure instanceof PlaceWriteUnverified || original instanceof ApiError && [401, 403].includes(original.status)) {
        // Clear displayed snapshots, but keep the frozen input/intent hidden
        // until the SAME complete identity is verified again. A real identity
        // mismatch clears everything; it cannot hand this intent to a new user.
        conceal(); setSource(null); setPage(emptyPlacePage()); setSaved(null); setReview(null); setNotice(''); setPending(nextPending);
        setError('身份核对暂未完成，地点已隐藏。原操作标识仍保留；重新核对身份后才能恢复。');
        void latest.current.refresh(); return;
      }
      const status = failure instanceof PlaceWriteRejected ? failure.status : 0;
      if ([404, 410].includes(status)) { setTerminal(true); setError('地点或关联旅行已删除，不能自动重新创建。请返回旅行核对。'); }
      else setError(status === 409 ? '旅行或地点版本已变化。原输入仍保留，请核对最新版本。' : '保存尚未核实，请先核对原操作。');
    } finally { if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function save() {
    if (locked || !editor || !source) return;
    try {
      const body = journeyPlacePayload(editor, source), id = editor.original?.id;
      void send({ method: id ? 'PATCH' : 'POST', path: id ? '/journey-places/' + id : '/journey-places', body: id ? body : { ...body, requestId: newKey() }, id, state: 'unknown', uncertain: false });
    } catch (failure) { setError(message(failure)); }
  }
  function recover() {
    if (!pending || busy || terminal) return;
    if (pending.method === 'POST' && pending.uncertain) { void send(pending); return; }
    void readJob(async ticket => {
      const fresh = await getSource(ticket), place = pending.id ? await getPlace(pending.id, ticket) : null;
      if (place && (!place.canManage || place.journeyId !== props.journeyId)) throw new Error('地点归属或关联已变化，请返回核对。');
      if (!current(ticket)) return;
      setPending(null); setReview(fresh);
      if (place) setEditor(value => value ? { ...value, original: place, draft: { ...value.draft, confirmed: false } } : value);
      setNotice('已读取当前版本，原输入保留。请核对当前保存值与旅行计划，再明确继续。');
    });
  }
  function acceptReview() {
    if (busy || !review || !editor) return;
    if (editor.destinationKey && !review.destinations.some(row => row.key === editor.destinationKey)) { setError('原目的地已移出旅行。请先取消地点编辑，再选当前目的地。'); return; }
    setSource(review); setEditor({ ...editor, sourceRevision: review.revision, draft: { ...editor.draft, confirmed: false } }); setReview(null); setError('');
  }
  function openMap(id?: string) {
    if (locked || editor) return;
    void readJob(async ticket => {
      await getSource(ticket); const place = id ? await getPlace(id, ticket) : null;
      if (place && place.journeyId !== props.journeyId) throw new Error('地点关联已改变，请重新读取。');
      if (current(ticket)) { const view = journeyPlaceView(props.journeyId, place?.id, place && state.current.page.items.some(row => row.id === place.id) ? state.current.page.offset : 0); conceal(true); props.onOpenMap(view); }
    });
  }
  const field = (label: string, key: keyof PlaceDraft) => <TextInput key={key} mode="outlined" label={label} accessibilityLabel={label} value={String(editor?.draft[key] || '')} disabled={locked} onChangeText={value => change({ [key]: value })} style={key === 'name' ? { minWidth: 0 } : styles.field} />;
  if (!visible) return <View style={styles.page}><ActivityIndicator animating={busy} /><Text>{error || '正在核对旅行与地点权限…'}</Text><Button disabled={busy} onPress={back}>返回旅行</Button><Button disabled={busy || !household.online} onPress={enter}>重新读取旅行地点</Button></View>;
  return <View testID="journey-places-panel" style={styles.page}>
    <PageHeader title="旅行地点" description={source?.title} />
    <Button accessibilityLabel="返回旅行" disabled={busy || !!pending && !terminal} onPress={back}>返回旅行</Button>
    {!!error && <Text accessibilityRole="alert">{error}</Text>}{!!notice && <Text accessibilityLiveRegion="polite">{notice}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对旅行地点" />}
    {pending && <SectionCard title={pending.uncertain ? '先核对这次保存' : '请核对最新版本'}><Text>原输入与操作标识仍保留。未知创建只重试同一份内容；不会自动生成另一条地点。</Text><Button disabled={busy || terminal} onPress={recover}>{pending.method === 'POST' && pending.uncertain ? '核对原创建' : '核对最新版本'}</Button>{pending.uncertain && <Button disabled={busy} onPress={() => setLeaving(true)}>关闭并核对地点</Button>}</SectionCard>}
    {review && <SectionCard title="旅行计划已重新读取"><Text>{review.title} · 当前版本 {review.revision}</Text>{review.destinations.map(row => <Text key={row.key}>{row.country} · {row.city} · {row.arrival} — {row.departure}</Text>)}
      {editor?.original && <><Divider /><Text>地点当前保存值：{editor.original.name} · {editor.original.country} · {editor.original.city}</Text><Text>{editor.original.startDate} — {editor.original.endDate} · {placeLabels[editor.original.status]} · {editor.original.visibility === 'private' ? '仅本人' : '家庭共享'} · 版本 {editor.original.revision}</Text><Text>坐标：{editor.original.coordinates ? `${editor.original.coordinates.latitude}，${editor.original.coordinates.longitude}` : '未填写'} · 共享坐标：{editor.original.coordinateDisclosure}</Text></>}
      <Text>下方保留你的输入，核对后再继续；不会自动改成最新内容。</Text><Button disabled={busy} onPress={acceptReview}>已核对最新旅行</Button></SectionCard>}
    {editor ? <SectionCard title={editor.original ? '编辑旅行地点' : '确认一个目的地'}><View style={styles.page}>
      {field('地点名称', 'name')}<View style={styles.row}>{field('国家或地区', 'country')}{field('城市', 'city')}</View><View style={styles.row}>{field('开始日期', 'startDate')}{field('结束日期', 'endDate')}</View>
      <Text>状态：{placeLabels[editor.draft.status]}。日期与照片不会自动确认到访。</Text><Text>位置可不填；只记录你提供的坐标。</Text><View style={styles.row}>{field('纬度（可不填）', 'latitude')}{field('经度（可不填）', 'longitude')}</View>
      <SelectionRow label="向家庭共享这个地点" checked={editor.draft.visibility === 'shared'} disabled={locked} onPress={() => change({ visibility: editor.draft.visibility === 'shared' ? 'private' : 'shared' })} />
      {editor.draft.visibility === 'shared' && <><Text>共享名称、国家、城市和日期。隐藏坐标不会隐藏文字中的地址；不授权电视或照片。</Text><View accessibilityRole="radiogroup" accessibilityLabel="共享坐标精度">{(['hidden', 'coarse', 'exact'] as const).map((value, index) => <SelectionRow key={value} kind="radio" label={['隐藏坐标', '大致坐标', '精确坐标'][index]} checked={editor.draft.coordinateDisclosure === value} disabled={locked} onPress={() => change({ coordinateDisclosure: value })} />)}</View></>}
      {editor.draft.status === 'visited' && <SelectionRow label="我确认修改后的地点与日期确实到访" checked={editor.draft.confirmed} disabled={locked} onPress={() => change({ confirmed: !editor.draft.confirmed })} />}
      <Button mode="contained" disabled={locked} onPress={save}>{editor.original ? '保存地点修改' : '确认保存地点'}</Button>
      <Button disabled={busy || !!pending} onPress={() => { setEditor(null); setReview(null); setError(''); }}>取消地点编辑</Button>
      {!pending && <Button disabled={busy} onPress={() => void readJob(async ticket => { const value = await getSource(ticket); if (current(ticket)) setReview(value); })}>读取最新旅行</Button>}
    </View></SectionCard> : !pending && source && <>
      {saved && <SectionCard title="已保存的地点"><Text>{saved.name} · {placeLabels[saved.status]} · {saved.visibility === 'private' ? '仅本人' : '家庭共享'}</Text><Button mode="contained" onPress={() => openMap(saved.id)} disabled={busy}>在地图查看这个地点</Button></SectionCard>}
      <SectionCard title="从旅行目的地开始"><Text>点一项核对后再保存。可以跳过；已有相似地点请先在下方查看，列表每页 24 条，不作自动去重。</Text>{source.destinations.map(row => <View key={row.key} testID={'journey-destination-' + row.key} style={styles.stop}><Text>{row.country} · {row.city}</Text><Text>{row.arrival} — {row.departure}</Text><Button accessibilityLabel={'整理目的地：' + row.city} mode="outlined" disabled={busy} onPress={() => choose(row.key)}>整理这个目的地</Button></View>)}</SectionCard>
      <SectionCard title={`本次旅行的地点 · ${page.total}`}><Text>只显示本人及家人明确共享的地点，无坐标也会保留在列表。</Text>{page.items.map(place => <View key={place.id} testID={'journey-place-' + place.id} style={styles.stop}><Text variant="titleMedium">{place.name}</Text><Text>{place.country} · {place.city} · {placeLabels[place.status]} · {place.visibility === 'private' ? '仅本人' : '共享'}</Text><Text>{place.startDate} — {place.endDate}</Text><View style={styles.row}><Button disabled={busy} onPress={() => openMap(place.id)}>在地图查看</Button>{place.canManage ? <Button accessibilityLabel={'编辑地点：' + place.name} disabled={busy} onPress={() => edit(place.id)}>编辑地点</Button> : <Text>家人共享，只有创建者可以编辑。</Text>}</View></View>)}
        <View style={styles.row}><Button disabled={busy || !page.offset} onPress={() => void readJob(ticket => reload(ticket, Math.max(0, page.offset - 24)))}>上一页地点</Button><Text>第 {Math.floor(page.offset / 24) + 1} 页</Text><Button disabled={busy || !page.hasMore} onPress={() => void readJob(ticket => reload(ticket, page.offset + 24))}>下一页地点</Button></View>
      </SectionCard><Button disabled={busy} onPress={() => openMap()}>查看这趟旅行的地图</Button>
    </>}
    <Portal><Dialog visible={leaving} onDismiss={() => setLeaving(false)} style={{ maxWidth: 520, width: '92%', alignSelf: 'center' }}><Dialog.Title>关闭当前保存恢复？</Dialog.Title><Dialog.Content><Text>原请求可能已经保存。关闭后原操作标识不会跨页面保留；请先查看已有地点，确认前不要重新创建。</Text></Dialog.Content><Dialog.Actions><Button onPress={() => setLeaving(false)}>继续核对原操作</Button><Button disabled={busy} onPress={() => { conceal(true); props.onBack(); }}>关闭并返回旅行</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}
const styles = StyleSheet.create({ page: { gap: 16 }, row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12 }, field: { flexGrow: 1, flexBasis: 180, minWidth: 0 }, stop: { gap: 8, paddingVertical: 14 } });
