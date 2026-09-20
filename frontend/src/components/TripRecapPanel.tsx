import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Image, Platform, StyleSheet, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Divider, Text, useTheme } from 'react-native-paper';
import { useHousehold } from '../lib/household';
import { RecapDiscarded, RecapError, RecapFence, recapId, recapPagePath, recapRequest, readRecapJourney, readRecapPhoto, readRecapPhotos, readRecapPlaces,
  type RecapSession, type RecapSnapshot } from '../lib/tripRecap';
import { EmptyState, PageHeader, SectionCard } from '../ui/components';
import { useDisplayDensity } from '../ui/theme';

import TripTVRecapPanel from './TripTVRecapPanel';

type Props = { journeyId: string; onBack: () => void; initialTab?: Tab; backLabel?: string };
type Tab = 'journey' | 'places' | 'photos';
type Selection = { tab: Tab; places: number; photos: number; photoId: string };
const connected = () => typeof navigator === 'undefined' || navigator.onLine !== false;
const pageVisible = () => typeof document === 'undefined' || !document.hidden;
const tabs: [Tab, string][] = [['journey', '行程安排'], ['places', '关联地点'], ['photos', '旅行照片']];
const status = { visited: '已明确确认到访', planned: '已计划', wish: '想去' };

export default function TripRecapPanel(props: Props) {
  const household = useHousehold();
  if (household.user?.role !== 'member' || !recapId(props.journeyId)) return <EmptyState title="暂时无法打开旅行回顾" description="请用成员账户重新选择旅行。"
    action={<Button contentStyle={styles.touch} onPress={props.onBack}>{props.backLabel || '返回旅行详情'}</Button>} />;
  return <Workspace key={household.identityKey + ':' + props.journeyId} {...props} identityKey={household.identityKey} owner={household.user.id} />;
}

function Workspace(props: Props & { identityKey: string; owner: string }) {
  const household = useHousehold(), density = useDisplayDensity(), theme = useTheme();
  const latest = useRef({ household, props }); latest.current = { household, props };
  const [data, setData] = useState<RecapSnapshot | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>(props.initialTab || 'journey'), [eventPage, setEventPage] = useState(0), [photoUrl, setPhotoUrl] = useState('');
  const [television, setTelevision] = useState(false), inTelevision = useRef(false);
  const selection = useRef<Selection>({ tab: props.initialTab || 'journey', places: 0, photos: 0, photoId: '' });
  const alive = useRef(false), focused = useRef(false), active = useRef(false), departed = useRef(false), denied = useRef(false);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive'), pageHidden = useRef(false);
  const windowFocused = useRef(typeof document === 'undefined' || document.hasFocus());
  const epoch = useRef(0), working = useRef(false), flight = useRef<AbortController | null>(null), url = useRef('');
  const imageExpiry = useRef<ReturnType<typeof setTimeout> | null>(null), imageDeadline = useRef(0);
  const fence = useRef(new RecapFence(props.identityKey));
  const current = (ticket = epoch.current) => alive.current && focused.current && active.current && !inTelevision.current && !departed.current && !denied.current && !pageHidden.current
    && foreground.current && windowFocused.current && pageVisible() && connected() && latest.current.household.online && latest.current.household.identityKey === props.identityKey && ticket === epoch.current;

  function clearImage() {
    if (imageExpiry.current) clearTimeout(imageExpiry.current); imageExpiry.current = null; imageDeadline.current = 0;
    if (url.current) URL.revokeObjectURL(url.current); url.current = ''; setPhotoUrl('');
  }
  function clearData() { clearImage(); setData(null); }
  function conceal() {
    active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort(); flight.current = null; working.current = false;
    clearData(); setBusy(false); setError('');
  }
  function failure(caught: unknown) {
    clearData();
    // A missing selection must not make every later explicit gallery refresh fail.
    // Keep the same workflow, scope and page; do not broaden or automatically read.
    if (caught instanceof RecapError && [404, 410].includes(caught.status)) selection.current = { ...selection.current, photoId: '' };
    if (caught instanceof RecapDiscarded && caught.message === 'identity' || caught instanceof RecapError && [401, 403].includes(caught.status)) {
      denied.current = true; selection.current = { tab: 'journey', places: 0, photos: 0, photoId: '' }; conceal();
      setError('登录或查看权限已变化，请重新进入。'); void latest.current.household.refresh();
    } else if (!(caught instanceof RecapDiscarded)) setError(caught instanceof RecapError ? caught.message : '暂时无法核对回顾内容，旧内容已隐藏。请重新读取。');
  }
  async function load(next = selection.current) {
    if (!current() || working.current) return;
    const ids = { ...next }, ticket = ++epoch.current, controller = new AbortController();
    fence.current.invalidate(); flight.current = controller; working.current = true; selection.current = ids; setTab(ids.tab);
    clearData(); setBusy(true); setError('');
    const me = async () => await recapRequest('/me', controller.signal) as RecapSession;
    const guarded = <T,>(read: () => Promise<T>) => fence.current.run(me, read, () => current(ticket));
    try {
      const journey = await guarded(async () => readRecapJourney(await recapRequest(`/journeys/${props.journeyId}`, controller.signal), props.journeyId));
      const places = await guarded(async () => readRecapPlaces(await recapRequest(recapPagePath('places', props.journeyId, ids.places), controller.signal), journey, props.owner, ids.places));
      const photos = await guarded(async () => readRecapPhotos(await recapRequest(recapPagePath('photos', props.journeyId, ids.photos), controller.signal), journey, ids.photos));
      let photo: RecapSnapshot['photo'] = null, blob: Blob | null = null, expires = 0;
      if (ids.photoId) {
        if (!photos.items.some(p => p.id === ids.photoId)) throw new RecapError('这张照片已移除或不在本页，旧预览已隐藏。请重新选择。', 404);
        const result = await guarded(async () => {
          const before = readRecapPhoto(await recapRequest(`/media/items/${ids.photoId}`, controller.signal), journey, ids.photoId);
          // Preview bytes have their own authorization; no provider URL enters Image.
          const started = performance.now(), bytes = Platform.OS === 'web' ? await recapRequest(`/media/items/${ids.photoId}/preview`, controller.signal) as Blob : null;
          const after = readRecapPhoto(await recapRequest(`/media/items/${ids.photoId}`, controller.signal), journey, ids.photoId);
          if (JSON.stringify(before) !== JSON.stringify(after)) throw new RecapError('照片或查看范围已变化，请重新选择。');
          return { photo: after, blob: bytes, expires: started + 15000 };
        });
        photo = result.photo; blob = result.blob; expires = result.expires;
      }
      // Cross-resource reads are not a database snapshot; finish with a fresh member check.
      await guarded(async () => null);
      if (!current(ticket)) return;
      if (blob) {
        if (performance.now() >= expires) throw new RecapError('照片核对已超时，请重新打开。');
        url.current = URL.createObjectURL(blob); imageDeadline.current = expires; setPhotoUrl(url.current);
        imageExpiry.current = setTimeout(() => { if (!current(ticket)) return; clearImage(); void load(); }, Math.max(0, expires - performance.now()));
      }
      setData({ journey, places, photos, photo });
      setEventPage(value => Math.min(value, Math.max(0, Math.ceil(journey.events.length / 8) - 1)));
    } catch (caught) { if (current(ticket)) failure(caught); }
    finally { if (flight.current === controller) flight.current = null; if (current(ticket)) { working.current = false; setBusy(false); } }
  }
  function enter() {
    if (inTelevision.current || active.current || denied.current || departed.current || !alive.current || !focused.current || !foreground.current || !windowFocused.current || pageHidden.current || !pageVisible() || !connected() || !latest.current.household.online) return;
    active.current = true; void load();
  }
  function back() { departed.current = true; conceal(); latest.current.props.onBack(); }
  function refresh() { if (active.current) void load(); else enter(); }
  function change(next: Partial<Selection>) { if (!working.current && current()) void load({ ...selection.current, ...next }); }
  useEffect(() => { alive.current = true; return () => { alive.current = false; active.current = false; ++epoch.current; fence.current.invalidate(); flight.current?.abort();
    if (imageExpiry.current) clearTimeout(imageExpiry.current); if (url.current) URL.revokeObjectURL(url.current); }; }, []);
  useFocusEffect(useCallback(() => { focused.current = true; enter(); return () => { focused.current = false; conceal(); }; }, [props.identityKey, props.journeyId]));
  useEffect(() => {
    const visibility = () => { if (pageVisible()) enter(); else conceal(); }, online = () => enter(), offline = () => conceal();
    const blur = () => { windowFocused.current = false; conceal(); }, focus = () => { windowFocused.current = true; enter(); };
    const hide = () => { pageHidden.current = true; conceal(); }, show = (event: PageTransitionEvent) => { if (event.persisted || pageHidden.current) { pageHidden.current = false; conceal(); enter(); } };
    const subscription = AppState.addEventListener('change', value => { foreground.current = value === 'active'; if (foreground.current) enter(); else conceal(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('blur', blur); window.addEventListener('focus', focus); window.addEventListener('online', online); window.addEventListener('offline', offline); window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show); }
    const timer = setInterval(() => { if (current() && !working.current) void load(); }, 15000);
    return () => { clearInterval(timer); subscription.remove(); if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('blur', blur); window.removeEventListener('focus', focus); window.removeEventListener('online', online); window.removeEventListener('offline', offline); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show); } };
  }, []);
  useEffect(() => { if (!household.online) conceal(); else enter(); }, [household.online]);

  if (television) return <TripTVRecapPanel journeyId={props.journeyId} onBack={() => { inTelevision.current = false; setTelevision(false); enter(); }} />;

  const showData = current() && !!data, blocked = busy || !current();
  const button = (label: string, action: () => void, disabled = blocked, mode: 'text' | 'outlined' | 'contained' = 'outlined') =>
    <Button accessibilityLabel={label} contentStyle={styles.touch} style={styles.button} mode={mode} disabled={disabled} onPress={action}>{label}</Button>;
  const paging = (kind: 'places' | 'photos', page: RecapSnapshot['places'] | RecapSnapshot['photos']) => <View style={styles.actions}>
    <Text accessibilityLiveRegion="polite">共 {page.total} {kind === 'places' ? '处' : '张'} · 本页 {page.items.length} · 第 {Math.floor(page.offset / 24) + 1} 页</Text>
    {button(kind === 'places' ? '上一页地点' : '上一页照片', () => change({ [kind]: Math.max(0, page.offset - 24), photoId: '' }), blocked || !page.offset)}
    {button(kind === 'places' ? '下一页地点' : '下一页照片', () => change({ [kind]: page.offset + 24, photoId: '' }), blocked || !page.hasMore)}
    {!!page.offset && !page.items.length && button('回到' + (kind === 'places' ? '地点' : '照片') + '第一页', () => change({ [kind]: 0, photoId: '' }))}
  </View>;
  const ownerName = (owner: string) => owner === 'shared' ? '共同' : household.state?.people.find(p => p.id === owner)?.name || '成员';
  return <View testID="trip-recap-panel" style={{ gap: density.screenGap }}>
    <PageHeader title="旅行回顾" description="把这趟旅行的安排、地点和照片放在一起看。" action={button(props.backLabel || '返回旅行详情', back, false)} />
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {busy && <ActivityIndicator accessibilityLabel="正在核对旅行回顾" />}
    {!showData || !data ? <EmptyState title={busy ? '正在读取当前可见内容' : !connected() || !household.online ? '离线时隐藏旅行回顾' : '回顾内容已隐藏'}
      description="回到此页面或恢复联网后，会自动更新。"
      action={button('重新读取旅行回顾', refresh, busy || denied.current || !connected() || !household.online)} /> : <View testID="trip-recap-content" style={{ gap: density.screenGap }}>
      <SectionCard title={data.journey.title}><View style={{ gap: density.sectionGap }}>
        <Text variant="titleMedium">{data.journey.start} 至 {data.journey.end}</Text>
        <Text>当前关联日程 {data.journey.events.length} 项 · 可见地点 {data.places.total} 处 · 可见照片 {data.photos.total} 张</Text>
        {!data.journey.tripPresent && <Text>原旅行记录已缺失，以下为仍可读取的保存计划与关联记录。</Text>}
        {!!data.journey.note && <Text>{data.journey.note}</Text>}
        <Text style={{ color: theme.colors.onSurfaceVariant }}>地点的到访状态以你的记录为准。</Text>
      </View></SectionCard>
      <View style={styles.actions}>{tabs.map(([key, label]) => <Button key={key} contentStyle={styles.touch} accessibilityLabel={label} accessibilityState={{ selected: tab === key }}
        mode={tab === key ? 'contained' : 'outlined'} disabled={blocked} onPress={() => change({ tab: key, photoId: '' })}>{label}</Button>)}{button('刷新旅行回顾', refresh)}<Button testID="trip-tv-entry" accessibilityLabel="在电视回顾" contentStyle={styles.touch} mode="contained" disabled={blocked || !data.journey.tripPresent}
        onPress={() => { inTelevision.current = true; conceal(); setTelevision(true); }}>在电视回顾</Button></View>
      {tab === 'journey' && <>
        <SectionCard title="保存的城市安排"><View style={{ gap: density.sectionGap }}>
          <Text>按旅行计划排列。</Text>
          {data.journey.destinations.map((d, i) => <View key={d.id} style={{ gap: 4 }}><Text variant="titleMedium">{i + 1}. {d.city}{d.country ? ' · ' + d.country : ''}</Text>
            <Text>{d.arrival} 至 {d.departure}{d.timeZone ? ' · ' + d.timeZone : ''}</Text></View>)}
        </View></SectionCard>
        <SectionCard title="当前关联日程"><View testID="recap-events" style={{ gap: density.sectionGap }}>
          <Text>按开始时间排列，包含最新修改。</Text>
          {!data.journey.events.length && <Text>当前没有关联日程。已移除的事项不会从旧计划重新出现。</Text>}
          {data.journey.events.slice(eventPage * 8, eventPage * 8 + 8).map(e => <View key={e.id} style={{ gap: 6 }}>
            <Divider /><Text variant="titleMedium">{e.title}</Text><Text>{e.kind} · {ownerName(e.owner)}{e.booking ? ' · ' + e.booking : ''}</Text>
            {e.timing.map((line, i) => <Text key={i}>{line}</Text>)}{!!e.location && <Text>地点：{e.location}</Text>}{!!e.note && <Text>{e.note}</Text>}
          </View>)}
          {data.journey.events.length > 8 && <View style={styles.actions}><Text>第 {eventPage + 1} / {Math.ceil(data.journey.events.length / 8)} 页</Text>
            {button('上一页行程', () => setEventPage(p => p - 1), blocked || eventPage === 0)}{button('下一页行程', () => setEventPage(p => p + 1), blocked || (eventPage + 1) * 8 >= data.journey.events.length)}</View>}
        </View></SectionCard>
      </>}
      {tab === 'places' && <View testID="recap-places" style={{ gap: density.sectionGap }}>
        <Text>这趟旅行的地点，按最近更新排列。</Text>
        {paging('places', data.places)}
        {!data.places.items.length && <EmptyState title="这一页没有可见地点" description="未关联、已移除或不再共享的地点不会显示。" />}
        {data.places.items.map(p => <SectionCard key={p.id} title={p.name}><View style={{ gap: 6 }}>
          <Text>{status[p.status]} · {p.canManage ? '我记录的' : ownerName(p.owner) + '共享'}</Text>
          {!!(p.city || p.country) && <Text>{[p.city, p.country].filter(Boolean).join(' · ')}</Text>}
          <Text>{p.startDate ? p.startDate + (p.endDate ? ' 至 ' + p.endDate : '') : '未提供日期'}</Text>
          <Text>{p.coordinates ? `${p.coordinatePrecision === 'approximate' ? '大致位置' : '已记录坐标'}：${p.coordinates.latitude}，${p.coordinates.longitude}` : p.coordinatePrecision === 'hidden' ? '记录者未共享坐标' : '未提供坐标'}</Text>
        </View></SectionCard>)}
      </View>}
      {tab === 'photos' && <View testID="recap-photos" style={{ gap: density.sectionGap }}>
        <Text>你与家人为这趟旅行保存的可见照片。</Text>
        {paging('photos', data.photos)}
        {!!data.photo && <SectionCard title="照片详情"><View testID="recap-photo-detail" style={{ gap: density.sectionGap }}>
          {Platform.OS === 'web' && photoUrl && performance.now() < imageDeadline.current ? <Image testID="recap-photo-image" source={{ uri: photoUrl }} resizeMode="contain" accessibilityLabel={data.photo.caption || '旅行照片预览'} style={[styles.image, { backgroundColor: theme.colors.surfaceVariant }]}
            onError={() => { if (current()) { clearImage(); setError('照片暂时无法显示，请重新读取。'); } }} /> : <Text>{Platform.OS === 'web' ? '照片正在重新核对' : '照片预览请使用浏览器版本。'}</Text>}
          <Text>{data.photo.caption || '未添加说明'}</Text><Text>{data.photo.visibility === 'private' ? '仅我自己' : '家庭共享'}</Text>
          {button('关闭照片详情', () => change({ photoId: '' }))}
        </View></SectionCard>}
        {!data.photos.items.length && <EmptyState title="这一页没有可见照片" description="只有已保存并明确关联这趟旅行的授权照片才会显示。" />}
        {data.photos.items.map((p, i) => <SectionCard key={p.id} title={p.caption || `旅行照片 ${data.photos.offset + i + 1}`}><View style={{ gap: 8 }}>
          <Text>{p.visibility === 'private' ? '仅我自己' : '家庭共享'}</Text>{button('查看照片 ' + (data.photos.offset + i + 1), () => change({ photoId: p.id }))}
        </View></SectionCard>)}
      </View>}
      <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>联网时自动更新，仅显示你有权查看的内容。</Text>
    </View>}
  </View>;
}
const styles = StyleSheet.create({ touch: { minHeight: 44 }, button: { alignSelf: 'flex-start', maxWidth: '100%' }, actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, image: { width: '100%', height: 300, borderRadius: 20 } });
