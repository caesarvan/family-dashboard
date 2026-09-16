import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Image, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { ActivityIndicator, Button, Card, Dialog, Portal, Text, useTheme } from 'react-native-paper';
import { ApiError, request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { PhotoReadDiscarded, PhotoReadFence, isMediaId, previewPath } from '../lib/photos';
import type { Photo, PhotoSession } from '../lib/photos';
import { readTripPhoto, readTripPhotoJourney, readTripPhotoPage, tripPhotoQuery } from '../lib/tripPhotos';
import type { TripPhotoJourney, TripPhotoPage, TripPhotoScope } from '../lib/tripPhotos';
import type { ScreenProps } from '../lib/types';
import { EmptyState, PageHeader } from '../ui/components';

type Props = ScreenProps & { journeyId: string; onBack: () => void };
type ViewIds = { scope: TripPhotoScope; offset: number; detailId: string };
type Snapshot = { journey: TripPhotoJourney; page: TripPhotoPage; detail: Photo | null };
const scopes: { value: TripPhotoScope; label: string }[] = [
  { value: 'visible', label: '我能查看的' }, { value: 'mine', label: '我的照片' }, { value: 'shared', label: '家人共享' },
];
const origin = (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
const imageUri = (item: Photo) => (Platform.OS === 'web' ? '' : origin) + previewPath(item);
const environmentVisible = () => typeof document === 'undefined' || !document.hidden;
const environmentOnline = () => typeof navigator === 'undefined' || navigator.onLine !== false;

export default function TripPhotosScreen(props: Props) {
  const household = useHousehold();
  if (props.user.role !== 'member' || !isMediaId(props.journeyId)) return <View style={styles.page}>
    <Button icon="arrow-left" onPress={props.onBack}>返回地图</Button>
    <EmptyState title="暂时无法打开旅行相册" description="请返回地图，重新选择当前可以查看的旅行。" />
  </View>;
  return <TripPhotoWorkspace key={household.identityKey + ':' + props.journeyId} {...props} identityKey={household.identityKey} />;
}

function TripPhotoWorkspace(props: Props & { identityKey: string }) {
  const household = useHousehold(), theme = useTheme(), { width, height } = useWindowDimensions();
  const latest = useRef(household); latest.current = household;
  const alive = useRef(false), active = useRef(false), routeFocused = useRef(false), denied = useRef(false);
  const nativeActive = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const generation = useRef(0), working = useRef(false);
  const fence = useRef(new PhotoReadFence(() => request<PhotoSession>('/me'), props.user, props.identityKey));
  // These are the only values retained while hidden/offline. No photo DTO,
  // travel title or preview is restored without a fresh permission check.
  const view = useRef<ViewIds>({ scope: 'visible', offset: 0, detailId: '' });
  const [scope, setScope] = useState<TripPhotoScope>('visible');
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const snapshotRef = useRef(snapshot); snapshotRef.current = snapshot;
  const [loading, setLoading] = useState(false), [error, setError] = useState('');
  const current = () => alive.current && active.current && routeFocused.current && nativeActive.current
    && !denied.current && latest.current.online && environmentVisible() && environmentOnline();

  function clearDisplayed() { snapshotRef.current = null; setSnapshot(null); }
  function suspend() {
    active.current = false; ++generation.current; fence.current.invalidate(); working.current = false;
    clearDisplayed(); setLoading(false); setError('');
  }
  function identityChanged() {
    suspend(); denied.current = true; view.current = { scope: 'visible', offset: 0, detailId: '' };
    setScope('visible'); setError('登录身份已变化，正在重新读取。'); void latest.current.refresh();
  }
  function failed(caught: unknown) {
    if (!current()) return;
    if (caught instanceof PhotoReadDiscarded) { if (caught.message === 'identity') identityChanged(); return; }
    clearDisplayed();
    if (caught instanceof ApiError && [401, 403].includes(caught.status)) { identityChanged(); return; }
    view.current.detailId = '';
    setError(caught instanceof ApiError && [404, 410].includes(caught.status)
      ? '旅行或照片已移除，或不再对你可见。请刷新或返回地图。'
      : '暂时无法读取旅行相册，旧照片已隐藏。请稍后刷新。');
  }
  async function read<T>(path: string, ticket: number): Promise<T> {
    return fence.current.read(() => request<T>(path), () => current() && ticket === generation.current);
  }
  async function reload(next = view.current) {
    if (!current()) return;
    const ids = { ...next }, ticket = ++generation.current;
    if (ids.scope !== view.current.scope || ids.offset !== view.current.offset) clearDisplayed();
    fence.current.invalidate(); working.current = true; view.current = ids;
    setScope(ids.scope); setLoading(true); setError('');
    try {
      const journey = readTripPhotoJourney(await read<unknown>(`/journeys/${props.journeyId}`, ticket), props.journeyId);
      const page = readTripPhotoPage(await read<unknown>(tripPhotoQuery(props.journeyId, ids.scope, ids.offset), ticket), props.journeyId, ids.offset);
      let detail: Photo | null = null;
      if (ids.detailId) {
        if (!page.items.some(item => item.id === ids.detailId)) throw new ApiError('照片已变化', 404);
        const result = await read<{ item: unknown }>(`/media/items/${ids.detailId}`, ticket);
        detail = readTripPhoto(result.item, props.journeyId, ids.detailId);
      }
      if (page.items.some(item => item.journey?.tripId !== journey.tripId) || detail && detail.journey?.tripId !== journey.tripId) throw new Error('旅行关联已变化');
      if (!current() || ticket !== generation.current) return;
      const result = { journey, page, detail }; snapshotRef.current = result; setSnapshot(result);
    } catch (caught) { if (ticket === generation.current) failed(caught); }
    finally { if (ticket === generation.current) { working.current = false; if (alive.current) setLoading(false); } }
  }
  function enter() {
    if (!alive.current || !routeFocused.current || denied.current || !latest.current.online || !nativeActive.current || !environmentVisible() || !environmentOnline()) return;
    if (active.current) return;
    active.current = true; void reload();
  }
  function leave() { suspend(); props.onBack(); }
  function closeDetail() {
    ++generation.current; fence.current.invalidate(); working.current = false; view.current.detailId = '';
    setLoading(false); setSnapshot(value => value ? { ...value, detail: null } : null);
    if (snapshotRef.current) snapshotRef.current = { ...snapshotRef.current, detail: null };
  }
  function previewFailed(id: string) {
    if (!current() || !snapshotRef.current?.page.items.some(item => item.id === id)) return;
    ++generation.current; fence.current.invalidate(); working.current = false; clearDisplayed(); setLoading(false);
    view.current.detailId = ''; setError('照片暂时无法显示，已隐藏旧预览。请刷新相册。');
  }

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; active.current = false; ++generation.current; fence.current.invalidate(); };
  }, []);
  useFocusEffect(useCallback(() => {
    routeFocused.current = true; enter();
    return () => { routeFocused.current = false; suspend(); };
  }, [props.identityKey, props.journeyId]));
  useEffect(() => {
    const visibility = () => { if (environmentVisible()) enter(); else suspend(); };
    const online = () => enter();
    const offline = () => { suspend(); setError('网络已断开，照片已隐藏。重新联网后会重新读取。'); };
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', visibility);
    if (typeof window !== 'undefined') { window.addEventListener('online', online); window.addEventListener('offline', offline); }
    const subscription = AppState.addEventListener('change', value => {
      nativeActive.current = value === 'active'; if (nativeActive.current) enter(); else suspend();
    });
    const timer = setInterval(() => { if (current() && !working.current) void reload(); }, 15000);
    return () => {
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', visibility);
      if (typeof window !== 'undefined') { window.removeEventListener('online', online); window.removeEventListener('offline', offline); }
      subscription.remove(); clearInterval(timer);
    };
  }, [props.identityKey, props.journeyId]);
  useEffect(() => {
    if (!household.online) { suspend(); setError('暂时无法核对连接，照片已隐藏。恢复后会重新读取。'); }
    else enter();
  }, [household.online]);

  const page = snapshot?.page, detail = snapshot?.detail;
  const columns = width < 540 ? 2 : width < 960 ? 3 : 4;
  const cardWidth = `${100 / columns - 1.6}%` as `${number}%`;
  const controlsDisabled = loading || !current();
  const renderPhoto = (item: Photo, large = false) => <Image key={item.id + ':' + item.revision}
    accessibilityLabel={item.caption || (large ? '照片详情预览' : '旅行照片')}
    source={{ uri: imageUri(item) }} onError={() => previewFailed(item.id)}
    resizeMode={large ? 'contain' : 'cover'} style={large ? styles.detailImage : styles.thumbnail} />;
  return <View style={styles.page}>
    <View style={styles.backRow}><Button icon="arrow-left" onPress={leave}>返回地图</Button></View>
    <PageHeader title="旅行相册" description={snapshot?.journey.title || '回看这趟旅行中，你当前可以查看的照片。'}
      action={<Button mode="outlined" icon="refresh" disabled={loading || denied.current || !environmentOnline()} onPress={() => { if (!active.current) enter(); else void reload(); }}>刷新相册</Button>} />
    <View style={styles.scopeRow}>{scopes.map(option => <Button key={option.value}
      mode={scope === option.value ? 'contained' : 'outlined'} disabled={controlsDisabled}
      accessibilityLabel={option.label + (scope === option.value ? '，当前范围' : '')}
      compact onPress={() => void reload({ scope: option.value, offset: 0, detailId: '' })}>{option.label}</Button>)}</View>
    <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>这里只查看照片。照片与地点关联同一趟旅行，不代表照片拍摄于该地点。</Text>
    {!!error && <Text accessibilityRole="alert" style={{ color: theme.colors.error }}>{error}</Text>}
    {loading && <ActivityIndicator accessibilityLabel="正在读取旅行相册" />}
    {!!page && (page.items.length ? <View style={styles.grid}>{page.items.map(item => <Card key={item.id} mode="contained"
      accessibilityLabel={'查看照片：' + (item.caption || '未添加说明')} disabled={controlsDisabled}
      onPress={() => { if (!working.current && current()) void reload({ ...view.current, detailId: item.id }); }}
      style={[styles.photoCard, { width: cardWidth, backgroundColor: theme.colors.surfaceVariant }]}>
      {renderPhoto(item)}<Card.Content style={styles.photoCopy}>
        <Text variant="bodyMedium">{item.caption || '未添加说明'}</Text>
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>{item.visibility === 'private' ? '仅我自己' : '家庭共享'}</Text>
      </Card.Content>
    </Card>)}</View> : <EmptyState title={page.total ? '这一页没有照片了' : '这次旅行还没有可见照片'}
      description={page.total ? '照片列表已变化，可以返回上一页或重新读取第一页。' : '已保存并关联这趟旅行的照片，会按各自的查看权限显示在这里。'}
      action={page.offset ? <Button onPress={() => void reload({ ...view.current, offset: 0, detailId: '' })}>回到第一页</Button> : undefined} />)}
    {!!page && <View style={styles.pagination}>
      <Text variant="bodySmall" accessibilityLiveRegion="polite">共 {page.total} 张 · 第 {Math.floor(page.offset / 24) + 1} 页</Text>
      <View style={styles.pageButtons}>
        <Button disabled={!page.offset || controlsDisabled} onPress={() => void reload({ ...view.current, offset: Math.max(0, page.offset - 24), detailId: '' })}>上一页</Button>
        <Button disabled={!page.hasMore || page.offset + 24 > 4000 || controlsDisabled} onPress={() => void reload({ ...view.current, offset: page.offset + 24, detailId: '' })}>下一页</Button>
      </View>
    </View>}
    <Portal><Dialog visible={!!detail} onDismiss={closeDetail} style={[styles.dialog, { maxHeight: height - 40 }]}>
      <Dialog.Title>照片详情</Dialog.Title>
      <Dialog.ScrollArea style={styles.dialogScroll}><ScrollView contentContainerStyle={styles.detailContent}>
        {!!detail && <>{renderPhoto(detail, true)}<Text variant="titleMedium">{detail.caption || '未添加说明'}</Text>
          <Text variant="bodyMedium">{detail.visibility === 'private' ? '仅我自己' : '家庭共享'} · {snapshot?.journey.title}</Text>
          <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>此处仅供回看。管理照片请从普通相册入口进入。</Text></>}
      </ScrollView></Dialog.ScrollArea>
      <Dialog.Actions><Button onPress={closeDetail}>关闭</Button></Dialog.Actions>
    </Dialog></Portal>
  </View>;
}

const styles = StyleSheet.create({
  page: { gap: 16 }, backRow: { alignItems: 'flex-start' }, scopeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 18 },
  photoCard: { borderRadius: 24, overflow: 'hidden' }, thumbnail: { width: '100%', aspectRatio: 1, backgroundColor: '#f0f0f3' },
  photoCopy: { paddingHorizontal: 12, paddingVertical: 14, gap: 6 },
  pagination: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center', justifyContent: 'space-between' },
  pageButtons: { flexDirection: 'row', flexWrap: 'wrap', gap: 4 },
  dialog: { width: '92%', maxWidth: 720, alignSelf: 'center', borderRadius: 24 },
  dialogScroll: { paddingHorizontal: 0, flexShrink: 1 }, detailContent: { padding: 20, gap: 16 },
  detailImage: { width: '100%', height: 300, borderRadius: 16, backgroundColor: '#f0f0f3' },
});
