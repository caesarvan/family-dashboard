import React, { useEffect, useRef, useState } from 'react';
import { AppState, Platform, View } from 'react-native';
import { Button, Text } from 'react-native-paper';
import { request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { fetchMemberVideo, PhotoReadDiscarded, PhotoReadFence, validatePhoto, videoDescription, VideoReadBusy } from '../lib/photos';
import type { Photo, PhotoSession } from '../lib/photos';

type Props = { item: Photo; user: NonNullable<PhotoSession['user']>; identityKey?: string; enabled: boolean };
// Member pages only. No TV authorization, auto-save or automatic playback.
export default function MemberVideoPlayer(props: Props) {
  const household = useHousehold();
  const latest = useRef({ props, household }); latest.current = { props, household };
  const alive = useRef(false), generation = useRef(0), pending = useRef(false);
  const nativeActive = useRef(AppState.currentState === 'active');
  const video = useRef<HTMLVideoElement | null>(null), url = useRef('');
  // React clears DOM refs before passive effect cleanup. Pause the detached
  // element while it is still reachable; revoking a Blob alone is not pause.
  const attachVideo = useRef((element: HTMLVideoElement | null) => {
    if (!element && video.current) { video.current.pause(); video.current.removeAttribute('src'); video.current.load(); }
    video.current = element;
  }).current;
  const controllers = useRef(new Set<AbortController>());
  const [source, setSource] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [, redraw] = useState(0);
  const identity = props.identityKey;
  const mediaKey = props.item.id + ':' + props.item.revision;
  const visible = () => nativeActive.current && (typeof document === 'undefined' || !document.hidden)
    && (typeof navigator === 'undefined' || navigator.onLine !== false);
  const current = () => alive.current && visible() && latest.current.household.online && latest.current.props.enabled
    && latest.current.props.item.id + ':' + latest.current.props.item.revision === mediaKey
    && (!identity || latest.current.household.identityKey === identity);
  const fence = useRef(new PhotoReadFence(() => json<PhotoSession>('/me'), props.user, identity));

  async function json<T>(path: string): Promise<T> {
    const controller = new AbortController(); controllers.current.add(controller);
    const timer = setTimeout(() => controller.abort(), 20000);
    try { return await request<T>(path, { signal: controller.signal }); }
    finally { clearTimeout(timer); controllers.current.delete(controller); }
  }
  function stop(message = '') {
    ++generation.current; fence.current.invalidate(); pending.current = false;
    controllers.current.forEach(controller => controller.abort()); controllers.current.clear();
    const element = video.current;
    if (element) { element.pause(); element.removeAttribute('src'); element.load(); }
    if (url.current) { URL.revokeObjectURL(url.current); url.current = ''; }
    if (alive.current) { setSource(''); setBusy(false); setError(message); }
  }
  async function metadata() {
    const result = await json<{ item: Photo }>(`/media/items/${props.item.id}`);
    const item = validatePhoto(result.item);
    if (item.id !== props.item.id || item.revision !== props.item.revision || item.mediaType !== 'video'
      || item.videoUrl !== props.item.videoUrl) throw new Error('视频已更新或不再可见，请重新打开详情。');
  }
  async function play() {
    if (!current() || pending.current || Platform.OS !== 'web') return;
    stop(); const ticket = generation.current; pending.current = true; setBusy(true); setError('');
    const valid = () => current() && ticket === generation.current;
    const controller = new AbortController(); controllers.current.add(controller);
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      const blob = await fence.current.read(async () => {
        await metadata();
        const result = await fetchMemberVideo(props.item, controller.signal);
        await metadata(); return result;
      }, valid);
      if (!valid()) return;
      url.current = URL.createObjectURL(blob); setSource(url.current);
    } catch (caught) {
      if (ticket !== generation.current || !alive.current) return;
      stop(caught instanceof PhotoReadDiscarded ? '身份已变化，请重新打开相册。'
        : caught instanceof VideoReadBusy ? '视频正在读取，请稍后点击播放重试。'
          : '视频暂时无法播放，请重新打开详情核对后再试。');
    } finally {
      clearTimeout(timer); controllers.current.delete(controller);
      if (ticket === generation.current && alive.current) { pending.current = false; setBusy(false); }
    }
  }
  useEffect(() => {
    alive.current = true; redraw(value => value + 1);
    const changed = () => { if (!current()) stop('播放已停止；回到页面并联网后，请重新播放。'); redraw(value => value + 1); };
    const hide = () => stop();
    const native = AppState.addEventListener('change', state => { nativeActive.current = state === 'active'; changed(); });
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', changed);
    if (typeof window !== 'undefined') { window.addEventListener('offline', changed); window.addEventListener('online', changed); window.addEventListener('pagehide', hide); }
    let checking = false;
    const timer = setInterval(() => {
      if (!url.current || checking) return;
      if (!current()) { stop(); return; }
      const ticket = generation.current; checking = true;
      void fence.current.read(metadata, () => current() && ticket === generation.current).catch(() => {
        if (ticket === generation.current) stop('无法核对当前播放权限，已停止。请重新打开详情。');
      }).finally(() => { checking = false; });
    }, 5000);
    return () => {
      alive.current = false; stop(); native.remove(); clearInterval(timer);
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', changed);
      if (typeof window !== 'undefined') { window.removeEventListener('offline', changed); window.removeEventListener('online', changed); window.removeEventListener('pagehide', hide); }
    };
  }, [mediaKey, identity]);
  useEffect(() => { if (!current()) stop(); }, [props.enabled, household.online, household.identityKey]);
  if (Platform.OS !== 'web') return <Text>请在手机或电脑浏览器打开相册播放视频；当前应用仍可查看封面。</Text>;
  return <View style={{ gap: 10 }}>
    <Text variant="bodySmall">{videoDescription(props.item)}</Text>
    {!!source && current() && React.createElement('video', {
      ref: attachVideo, src: source, controls: true, playsInline: true, preload: 'none',
      disablePictureInPicture: true, disableRemotePlayback: true, controlsList: 'nodownload noremoteplayback',
      'aria-label': props.item.caption ? `播放视频：${props.item.caption}` : '相册视频',
      style: { width: '100%', maxHeight: 320, display: 'block', borderRadius: 8, background: '#000' },
      onError: () => stop('浏览器无法播放此视频，可关闭后重新读取。'),
    })}
    {!!error && <Text accessibilityRole="alert">{error}</Text>}
    {source ? <Button accessibilityLabel="停止播放" onPress={() => stop()}>停止播放</Button>
      : <Button accessibilityLabel="播放视频" mode="outlined" icon="play" loading={busy} disabled={busy || !current()} onPress={() => void play()}>播放视频</Button>}
    <Text variant="bodySmall">仅在本页播放。切换身份、离线或离开页面后停止；不会自动分享。</Text>
  </View>;
}
