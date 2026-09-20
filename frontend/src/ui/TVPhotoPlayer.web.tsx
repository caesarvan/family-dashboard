import React, { useLayoutEffect, useRef, useState } from 'react';
import { StyleSheet, View, useWindowDimensions } from 'react-native';
import { ActivityIndicator, Button, Text } from 'react-native-paper';
import { isTVPhotoId, readTVPlayback, TVPhotoIdentityChanged, TVPhotoLease, TV_PHOTO_MAX_BYTES,
  TV_PHOTO_POLL_MS, TV_PHOTO_TIMEOUT_MS, TV_VIDEO_MAX_BYTES, TVMediaClock, progressIntent, reportResolved,
  type TVPlayback, type TVProgressEvent, type TVProgressIntent, type TVPhotoPlayerProps } from './TVPhotoPlayer.model';
export type { TVPhotoPlayerProps } from './TVPhotoPlayer.model';

type Display = { deviceId: string; mode: 'unknown' | 'dashboard' | 'photos'; status: 'loading' | 'image' | 'empty' | 'error' | 'expired' | 'blocked' | 'pending' | 'busy'; position: number; count: number; paused: boolean };
type Request = { controller: AbortController; ticket: number };
const blank = (deviceId: string): Display => ({ deviceId, mode: 'unknown', status: 'loading', position: 0, count: 0, paused: false });
class DisplayHttpError extends Error { status: number; constructor(status: number) { super('Display unavailable'); this.status = status; } }
class DisplayVideoBusy extends Error {}

async function bytes(response: Response, limit: number, signal: AbortSignal) {
  const declared = response.headers.get('Content-Length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > limit)) throw new Error('Oversized display response');
  if (!response.body) throw new Error('Empty display response');
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let total = 0;
  try {
    while (true) {
      if (signal.aborted) throw new Error('Display request cancelled');
      const result = await reader.read();
      if (signal.aborted) throw new Error('Display request cancelled');
      if (result.done) break;
      total += result.value.byteLength;
      if (total > limit) throw new Error('Oversized display response');
      chunks.push(result.value);
    }
    if (!total || declared !== null && total !== Number(declared)) throw new Error('Incomplete display response');
    const body = new Uint8Array(total); let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    return body;
  } catch (error) { void reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
}

async function displayResponse(path: string, type: string, signal: AbortSignal) {
  const response = await fetch(path, { method: 'GET', mode: 'same-origin', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal,
    headers: { 'X-Display-Mode': 'tv', Accept: type } });
  if (response.status === 401 || response.status === 403) throw new DisplayHttpError(response.status);
  if (type === 'video/mp4' && response.status === 503 && !response.redirected
    && response.url === new URL(path, window.location.origin).href
    && response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() === 'application/json'
    && response.headers.get('Retry-After') === '1') {
    const data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(await bytes(response, 1024, signal)));
    if (data?.code === 'video_busy') throw new DisplayVideoBusy('Video read busy');
  }
  if (response.status !== 200 || response.redirected || response.url !== new URL(path, window.location.origin).href
    || response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== type) throw new Error('Invalid display response');
  return response;
}

function decode(image: HTMLImageElement, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => { image.removeAttribute('src'); reject(new Error('Display decode cancelled')); };
    if (signal.aborted) { abort(); return; }
    signal.addEventListener('abort', abort, { once: true });
    image.decode().then(() => { signal.removeEventListener('abort', abort); resolve(); }, error => {
      signal.removeEventListener('abort', abort); reject(error);
    });
  });
}

export default function TVPhotoPlayer({ deviceId, active, onUnauthorized }: TVPhotoPlayerProps) {
  const size = useWindowDimensions(), scale = Math.max(0.65, Math.min(size.width / 1920, size.height / 1080));
  const image = useRef<HTMLImageElement>(null), video = useRef<HTMLVideoElement>(null);
  const paint = useRef<(() => void) | null>(null), ended = useRef<(() => void) | null>(null);
  const retry = useRef<(() => void) | null>(null), mediaError = useRef<(() => void) | null>(null);
  const props = useRef({ deviceId, active, onUnauthorized }); props.current = { deviceId, active, onUnauthorized };
  const [view, setView] = useState<Display>(() => blank(deviceId));

  useLayoutEffect(() => {
    setView(blank(deviceId));
    if (!active || !isTVPhotoId(deviceId)) return;
    const lease = new TVPhotoLease(), clock = new TVMediaClock();
    let mounted = true, pageVisible = true, state: TVPlayback | null = null, nextPoll = 0, lastCheckpoint = 0, acceptedStarted = -1;
    let polling: Promise<void> | null = null, pollRequest: Request | null = null, assetRequest: Request | null = null;
    let reportRequest: Request | null = null, assetKey = '', failedKey = '', unknown: TVProgressIntent | null = null;
    let failedStatus: 'error' | 'busy' = 'error';
    let sending: TVProgressIntent | null = null;
    type Frame = { url: string; key: string; ticket: number; kind: 'photo' | 'video'; ready: boolean; preparing: boolean;
      blocked: boolean; playPending: boolean; positioned: boolean; pauseRevision: number };
    let frame: Frame | null = null;
    const available = () => mounted && props.current.active && props.current.deviceId === deviceId
      && pageVisible && !document.hidden && navigator.onLine !== false;
    const keyOf = (value: TVPlayback) => value.item && value.progress
      ? value.item.id + ':' + value.item.revision + ':' + value.progress.playId : '';
    const clearFrame = () => {
      if (image.current) { image.current.removeAttribute('src'); image.current.hidden = true; }
      if (video.current) { video.current.pause(); video.current.removeAttribute('src'); video.current.load(); video.current.hidden = true; }
      if (frame) URL.revokeObjectURL(frame.url);
      frame = null; clock.reset();
    };
    const cancelAsset = () => { const old = assetRequest; assetRequest = null; assetKey = ''; old?.controller.abort(); };
    const invalidate = (status: Display['status']) => {
      if (sending) unknown = sending;
      lease.clear(); pollRequest?.controller.abort(); reportRequest?.controller.abort(); cancelAsset(); clearFrame();
      nextPoll = performance.now() + TV_PHOTO_POLL_MS;
      if (mounted) setView(value => ({ ...value, status, position: 0, count: 0 }));
    };
    function actualPosition(): number {
      const duration = state?.progress?.durationMs || 1;
      if (frame?.kind === 'video') return Math.min(duration, Math.max(0, Math.floor((video.current?.currentTime || 0) * 1000)));
      return clock.sample(performance.now(), !!frame?.ready && !state?.paused && available() && lease.valid(frame.ticket, performance.now()), duration);
    }
    function paintFrame() {
      if (!available() || !frame || !state || keyOf(state) !== frame.key || !lease.valid(frame.ticket, performance.now())) {
        if (image.current) image.current.hidden = true;
        if (video.current) { video.current.pause(); video.current.hidden = true; }
        return;
      }
      if (frame.kind === 'photo') {
        if (video.current) { video.current.pause(); video.current.hidden = true; }
        if (image.current) { if (image.current.src !== frame.url) image.current.src = frame.url; image.current.hidden = false; }
        if (!frame.ready && !frame.preparing) void send('ready', state.progress!.positionMs);
      } else if (video.current) {
        const element = video.current;
        if (image.current) image.current.hidden = true;
        if (element.src !== frame.url) { element.muted = true; element.src = frame.url; element.load(); }
        if (element.readyState < 1) return;
        if (!frame.positioned) { element.currentTime = state.progress!.positionMs / 1000; frame.positioned = true; }
        element.hidden = false;
        if (!frame.ready && !frame.preparing && element.readyState >= 2) void send('ready', state.progress!.positionMs);
        if (state.paused || !frame.ready || unknown) element.pause();
        else if (element.paused && !element.ended && !frame.blocked && !frame.playPending) {
          const target = frame; target.playPending = true;
          void element.play().catch(() => {
            if (frame === target && available()) { target.blocked = true; setView(value => ({ ...value, status: 'blocked' })); }
          }).finally(() => { target.playPending = false; });
        }
      }
    }
    function apply(value: TVPlayback, started: number) {
      if (started < acceptedStarted || state && value.revision < state.revision) return;
      lease.accept(lease.ticket(), value, started, performance.now());
      acceptedStarted = started;
      if (value.protocol !== 2) throw new Error('Playback protocol needs update');
      if (state?.progress && value.progress?.playId === state.progress.playId && value.progress.sequence < state.progress.sequence) {
        value = { ...value, progress: state.progress };
      }
      if (unknown && reportResolved(unknown, value)) unknown = null;
      state = value;
      if (value.mode === 'dashboard') { cancelAsset(); clearFrame(); setView({ ...blank(deviceId), mode: 'dashboard' }); return; }
      const key = keyOf(value);
      setView({ deviceId, mode: 'photos', status: unknown ? 'pending' : !value.item ? 'empty' : frame?.key === key
        ? frame.blocked ? 'blocked' : 'image' : failedKey === key ? failedStatus : 'loading',
        position: value.position, count: value.photoCount, paused: value.paused });
      if (unknown || !value.item) { cancelAsset(); clearFrame(); return; }
      if (frame?.key === key) {
        paintFrame();
        if (value.paused && frame.ready && frame.pauseRevision !== value.revision && !reportRequest) {
          frame.pauseRevision = value.revision; void send('paused', actualPosition());
        }
      } else if (assetKey !== key && failedKey !== key) { cancelAsset(); clearFrame(); void loadAsset(value); }
    }
    function poll(): Promise<void> {
      if (polling) return polling;
      if (!available()) return Promise.resolve();
      const operation: Request = { controller: new AbortController(), ticket: lease.ticket() };
      pollRequest = operation;
      const started = performance.now(), signal = operation.controller.signal;
      const current = () => pollRequest === operation && lease.current(operation.ticket) && available() && !signal.aborted;
      const timer = setTimeout(() => operation.controller.abort(), TV_PHOTO_TIMEOUT_MS);
      polling = (async () => {
        try {
          const response = await displayResponse('/api/media-tv/playback', 'application/json', signal);
          const raw = await bytes(response, 32768, signal);
          if (!current()) return;
          apply(readTVPlayback(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw)), deviceId), started);
        } catch (error) {
          if (pollRequest === operation && available()) {
            invalidate('error');
            if (error instanceof TVPhotoIdentityChanged || error instanceof DisplayHttpError && [401, 403].includes(error.status)) props.current.onUnauthorized();
          }
        } finally {
          clearTimeout(timer);
          if (pollRequest === operation) pollRequest = null;
          polling = null; nextPoll = performance.now() + TV_PHOTO_POLL_MS;
        }
      })();
      return polling;
    }
    async function loadAsset(value: TVPlayback) {
      const item = value.item!, key = keyOf(value), kind = item.mediaType === 'video' ? 'video' : 'photo';
      const operation: Request = { controller: new AbortController(), ticket: lease.ticket() };
      assetRequest = operation; assetKey = key;
      const current = () => assetRequest === operation && available() && !operation.controller.signal.aborted
        && lease.current(operation.ticket) && !!state && keyOf(state) === key && !unknown;
      let objectUrl: string | null = null, candidate: HTMLImageElement | HTMLVideoElement | null = null;
      const timer = setTimeout(() => operation.controller.abort(), kind === 'video' ? 120000 : TV_PHOTO_TIMEOUT_MS);
      try {
        const type = kind === 'video' ? 'video/mp4' : 'image/jpeg';
        const response = await displayResponse(kind === 'video' ? item.videoUrl! : item.previewUrl, type, operation.controller.signal);
        const body = await bytes(response, kind === 'video' ? TV_VIDEO_MAX_BYTES : TV_PHOTO_MAX_BYTES, operation.controller.signal);
        if (!current()) return;
        objectUrl = URL.createObjectURL(new Blob([body], { type }));
        if (kind === 'photo') {
          if (body[0] !== 0xff || body[1] !== 0xd8) throw new Error('Invalid JPEG');
          const picture = new Image(); candidate = picture; picture.src = objectUrl;
          await decode(picture, operation.controller.signal);
          if (picture.naturalWidth !== item.width || picture.naturalHeight !== item.height) throw new Error('Invalid photo dimensions');
        } else {
          const movie = document.createElement('video'); candidate = movie; movie.muted = true; movie.preload = 'metadata';
          await new Promise<void>((resolve, reject) => {
            const abort = () => finish(new Error('Video cancelled'));
            const finish = (error?: Error) => { movie.onloadedmetadata = null; movie.onerror = null; operation.controller.signal.removeEventListener('abort', abort); error ? reject(error) : resolve(); };
            movie.onloadedmetadata = () => finish(); movie.onerror = () => finish(new Error('Video unsupported'));
            operation.controller.signal.addEventListener('abort', abort, { once: true }); movie.src = objectUrl!; movie.load();
          });
          if (movie.videoWidth !== item.width || movie.videoHeight !== item.height || !Number.isFinite(movie.duration)
            || Math.abs(movie.duration * 1000 - item.durationMs!) > 500) throw new Error('Invalid video metadata');
        }
        // Long byte reads do not hold the polling slot. Obtain fresh permission
        // after bytes/metadata before attaching a playable Blob.
        if (polling) await polling;
        await poll();
        if (!current() || !lease.valid(operation.ticket, performance.now())) return;
        frame = { url: objectUrl, key, ticket: operation.ticket, kind, ready: false, preparing: false,
          blocked: false, playPending: false, positioned: false, pauseRevision: -1 };
        objectUrl = null; clock.reset(state!.progress!.positionMs); setView(view => ({ ...view, status: 'image' })); paintFrame();
      } catch (error) {
        if (assetRequest === operation && available() && state && keyOf(state) === key) {
          failedKey = key; failedStatus = error instanceof DisplayVideoBusy ? 'busy' : 'error';
          clearFrame(); setView(view => ({ ...view, status: failedStatus }));
        }
      } finally {
        candidate?.removeAttribute('src'); if (candidate instanceof HTMLVideoElement) candidate.load();
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        clearTimeout(timer); if (assetRequest === operation) { assetRequest = null; assetKey = ''; }
      }
    }
    async function send(event: TVProgressEvent, position: number) {
      if (reportRequest || unknown || !state?.item || !state.progress || !frame || !available() || !lease.valid(frame.ticket, performance.now())) return;
      const before = state, target = frame;
      if (event === 'ready') target.preparing = true;
      const intent = progressIntent(before, event, Math.min(before.progress!.durationMs, Math.max(before.progress!.positionMs, position)));
      const operation: Request = { controller: new AbortController(), ticket: lease.ticket() };
      reportRequest = operation; sending = intent;
      const started = performance.now(), timer = setTimeout(() => operation.controller.abort(), TV_PHOTO_TIMEOUT_MS);
      try {
        const response = await fetch('/api/media-tv/playback/progress', { method: 'POST', credentials: 'same-origin', mode: 'same-origin',
          cache: 'no-store', redirect: 'error', signal: operation.controller.signal,
          headers: { 'Content-Type': 'application/json', 'X-Display-Mode': 'tv', 'X-TV-Playback-CSRF': before.playbackCsrf! }, body: JSON.stringify(intent) });
        if (!response.ok) throw new DisplayHttpError(response.status);
        if (response.redirected || response.url !== new URL('/api/media-tv/playback/progress', window.location.origin).href
          || !response.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) throw new Error('Unknown progress response');
        const body = await bytes(response, 32768, operation.controller.signal);
        if (!lease.current(operation.ticket) || !available()) return;
        const value = readTVPlayback(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body)), deviceId);
        if (!state || value.revision >= state.revision) apply(value, started);
        if (frame === target) { target.preparing = false; if (event === 'ready') { target.ready = true; clock.reset(value.progress!.positionMs); } paintFrame(); }
        lastCheckpoint = performance.now();
      } catch (error) {
        if (lease.current(operation.ticket) && available()) {
          target.preparing = false;
          if (error instanceof DisplayHttpError && [400, 401, 403, 404, 409, 410, 413, 415, 429].includes(error.status)) {
            if ([401, 403].includes(error.status)) { sending = null; invalidate('error'); props.current.onUnauthorized(); }
            else { sending = null; clearFrame(); cancelAsset(); }
          } else { unknown = intent; clearFrame(); cancelAsset(); setView(value => ({ ...value, status: 'pending' })); }
          nextPoll = 0;
        }
      } finally {
        clearTimeout(timer); if (reportRequest === operation) { reportRequest = null; sending = null; }
      }
    }
    paint.current = paintFrame;
    ended.current = () => { if (frame?.kind === 'video' && frame.ready && !state?.paused && video.current?.ended) void send('ended', actualPosition()); };
    mediaError.current = () => {
      if (!frame || (frame.kind === 'photo' ? image.current?.src : video.current?.src) !== frame.url) return;
      if (state) failedKey = keyOf(state); failedStatus = 'error'; clearFrame(); cancelAsset(); setView(value => ({ ...value, status: 'error' }));
    };
    retry.current = () => {
      if (frame?.blocked) { frame.blocked = false; paintFrame(); return; }
      failedKey = ''; nextPoll = 0; void poll();
    };
    const watch = setInterval(() => {
      if (!available()) return;
      const now = performance.now();
      if (lease.expired(now)) invalidate('expired');
      if (now >= nextPoll) void poll();
      if (!frame?.ready || !state?.progress || unknown || !lease.valid(frame.ticket, now)) return;
      const offset = actualPosition();
      // Native ended may fire while a checkpoint is awaiting its response.
      // Recheck the current element after that slot clears; never infer video end from time.
      if (!state.paused && (frame.kind === 'photo' ? offset >= state.progress.durationMs : video.current?.ended)) void send('ended', offset);
      else if (!state.paused && now - lastCheckpoint >= 5000 && (frame.kind === 'photo' || !video.current?.paused && !video.current?.seeking)) void send('checkpoint', offset);
    }, 100);
    const hide = () => invalidate('error');
    const pagehide = () => { pageVisible = false; hide(); };
    const resume = () => { if (available()) { failedKey = ''; invalidate('loading'); nextPoll = 0; void poll(); } };
    const pageshow = () => { pageVisible = true; resume(); };
    const visibility = () => document.hidden ? hide() : resume();
    window.addEventListener('offline', hide); window.addEventListener('online', resume);
    window.addEventListener('pagehide', pagehide); window.addEventListener('pageshow', pageshow);
    document.addEventListener('visibilitychange', visibility); void poll();
    return () => {
      mounted = false; invalidate('error'); clearInterval(watch);
      window.removeEventListener('offline', hide); window.removeEventListener('online', resume);
      window.removeEventListener('pagehide', pagehide); window.removeEventListener('pageshow', pageshow);
      document.removeEventListener('visibilitychange', visibility);
      paint.current = null; ended.current = null; retry.current = null; mediaError.current = null;
    };
  }, [deviceId, active]);
  useLayoutEffect(() => { paint.current?.(); });
  if (!active || view.deviceId !== deviceId || view.mode !== 'photos') return null;
  const message = view.status === 'empty' ? '还没有可播放的媒体，请在手机上允许这台电视展示。'
    : view.status === 'expired' ? '显示授权已到期，正在重新核对。'
      : view.status === 'pending' ? '播放进度的提交结果尚未核对，已停止播放。可在手机暂停或继续后重新核对。'
        : view.status === 'blocked' ? '浏览器尚未允许静音播放，请在电视上确认。手机操作不能开启电视声音。'
          : view.status === 'busy' ? '视频正在读取，请稍后重试。当前项目已保留，显示权限仍会持续核对。'
            : view.status === 'error' ? '连接、媒体或许可暂不可用，画面已清除。'
            : view.status === 'loading' ? '正在核对媒体并加载…' : '';
  return <View testID="tv-photo-player" accessibilityLabel="已授权家庭媒体播放" style={styles.overlay}>
    <img ref={image} data-testid="tv-photo-image" alt="已授权的家庭照片" hidden onError={() => mediaError.current?.()}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }} />
    <video ref={video} data-testid="tv-media-video" aria-label="已授权的家庭视频（静音）" hidden muted playsInline
      onLoadedMetadata={() => paint.current?.()} onCanPlay={() => paint.current?.()} onEnded={() => ended.current?.()} onError={() => mediaError.current?.()}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }} />
    {!!message && <View style={[styles.message, { gap: 20 * scale, maxWidth: 840 * scale, padding: 32 * scale }]}>
      {view.status === 'loading' && <ActivityIndicator color="#fff" size={36 * scale} />}
      <Text testID="tv-photo-status" accessibilityLiveRegion="polite" style={[styles.text, { fontSize: 28 * scale, lineHeight: 40 * scale }]}>{message}</Text>
      {['blocked', 'error', 'pending', 'busy'].includes(view.status) && <Button mode="contained" onPress={() => retry.current?.()}>
        {view.status === 'blocked' ? '重试静音播放' : '重新核对播放'}</Button>}
    </View>}
    {view.count > 0 && <Text testID="tv-photo-position" style={[styles.position, { bottom: 24 * scale, right: 24 * scale,
      paddingVertical: 10 * scale, paddingHorizontal: 18 * scale, borderRadius: 24 * scale,
      fontSize: 20 * scale, lineHeight: 28 * scale }]}>{view.position + 1} / {view.count}{view.paused ? ' · 已暂停' : ''}</Text>}
  </View>;
}
const styles = StyleSheet.create({
  overlay: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, zIndex: 30, backgroundColor: '#090b0e', alignItems: 'center', justifyContent: 'center' },
  message: { alignItems: 'center' }, text: { color: '#f4f4f5', textAlign: 'center' },
  position: { position: 'absolute', backgroundColor: '#090b0e', color: '#fff' },
});
