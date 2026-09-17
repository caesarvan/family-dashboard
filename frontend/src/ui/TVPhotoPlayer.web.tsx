import React, { useLayoutEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { ActivityIndicator, Text } from 'react-native-paper';
import { isTVPhotoId, readTVPlayback, TVPhotoIdentityChanged, TVPhotoLease, TV_PHOTO_MAX_BYTES,
  TV_PHOTO_POLL_MS, TV_PHOTO_TIMEOUT_MS, type TVPhotoPlayerProps } from './TVPhotoPlayer.model';
export type { TVPhotoPlayerProps } from './TVPhotoPlayer.model';

type Display = { deviceId: string; mode: 'unknown' | 'dashboard' | 'photos'; status: 'loading' | 'image' | 'empty' | 'error' | 'expired'; position: number; count: number; paused: boolean };
type Request = { controller: AbortController; ticket: number };
const blank = (deviceId: string): Display => ({ deviceId, mode: 'unknown', status: 'loading', position: 0, count: 0, paused: false });
class DisplayHttpError extends Error { status: number; constructor(status: number) { super('Display unavailable'); this.status = status; } }

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
    if (!total) throw new Error('Empty display response');
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
  if (!response.ok || response.redirected || response.url !== new URL(path, window.location.origin).href
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
  const image = useRef<HTMLImageElement>(null), paint = useRef<(() => void) | null>(null);
  const failImage = useRef<(() => void) | null>(null), props = useRef({ deviceId, active, onUnauthorized });
  props.current = { deviceId, active, onUnauthorized };
  const [view, setView] = useState<Display>(() => blank(deviceId));

  useLayoutEffect(() => {
    setView(blank(deviceId));
    if (!active || !isTVPhotoId(deviceId)) return;
    const lease = new TVPhotoLease(), urls = new Set<string>();
    let mounted = true, pageVisible = true, request: Request | null = null, next = 0;
    let frame: { url: string; key: string; ticket: number } | null = null;
    const available = () => mounted && props.current.active && props.current.deviceId === deviceId
      && pageVisible && !document.hidden && navigator.onLine !== false;
    const clearPixels = () => { if (image.current) { image.current.removeAttribute('src'); image.current.hidden = true; } };
    const clearFrame = () => { clearPixels(); frame = null; for (const url of urls) URL.revokeObjectURL(url); urls.clear(); };
    const invalidate = (status: Display['status']) => {
      lease.clear(); const previous = request; request = null; previous?.controller.abort(); clearFrame();
      next = performance.now() + TV_PHOTO_POLL_MS;
      if (mounted) setView(value => ({ ...value, status, position: 0, count: 0 }));
    };
    const paintFrame = () => {
      if (!image.current) return;
      if (!available() || !frame || !urls.has(frame.url) || !lease.valid(frame.ticket, performance.now())) { clearPixels(); return; }
      if (image.current.getAttribute('src') !== frame.url) image.current.src = frame.url;
      image.current.hidden = false;
    };
    paint.current = paintFrame;
    failImage.current = () => invalidate('error');

    async function poll() {
      if (request || !available()) return;
      const operation: Request = { controller: new AbortController(), ticket: lease.ticket() };
      request = operation;
      const started = performance.now(), signal = operation.controller.signal;
      const current = () => request === operation && lease.current(operation.ticket) && available() && !signal.aborted;
      const timer = setTimeout(() => { if (request === operation) invalidate('error'); }, TV_PHOTO_TIMEOUT_MS);
      let candidate: HTMLImageElement | null = null, pendingUrl: string | null = null;
      try {
        const response = await displayResponse('/api/media-tv/playback', 'application/json', signal);
        const raw = await bytes(response, 32768, signal);
        if (!current()) return;
        const value = readTVPlayback(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw)), deviceId);
        lease.accept(operation.ticket, value, started, performance.now());
        if (value.mode === 'dashboard') {
          clearFrame(); setView({ ...blank(deviceId), mode: 'dashboard' }); return;
        }
        setView({ deviceId, mode: 'photos', status: value.item ? 'loading' : 'empty', position: value.position, count: value.photoCount, paused: value.paused });
        if (!value.item) { clearFrame(); return; }
        const key = value.item.id + ':' + value.item.revision;
        if (frame?.key === key && urls.has(frame.url)) { setView(state => ({ ...state, status: 'image' })); paintFrame(); return; }
        clearFrame();
        const photo = await displayResponse(value.item.previewUrl, 'image/jpeg', signal);
        const body = await bytes(photo, TV_PHOTO_MAX_BYTES, signal);
        if (!current() || !lease.valid(operation.ticket, performance.now())) return;
        if (body[0] !== 0xff || body[1] !== 0xd8) throw new Error('Invalid JPEG');
        pendingUrl = URL.createObjectURL(new Blob([body], { type: 'image/jpeg' })); urls.add(pendingUrl);
        candidate = new Image(); candidate.src = pendingUrl;
        await decode(candidate, signal);
        if (!current() || !lease.valid(operation.ticket, performance.now())) return;
        if (candidate.naturalWidth !== value.item.width || candidate.naturalHeight !== value.item.height) throw new Error('Invalid image dimensions');
        frame = { url: pendingUrl, key, ticket: operation.ticket }; pendingUrl = null;
        setView(state => ({ ...state, status: 'image' })); paintFrame();
      } catch (error) {
        if (current()) {
          invalidate('error');
          if (error instanceof TVPhotoIdentityChanged || (error instanceof DisplayHttpError && [401, 403].includes(error.status))) props.current.onUnauthorized();
        }
      } finally {
        candidate?.removeAttribute('src');
        if (pendingUrl) { URL.revokeObjectURL(pendingUrl); urls.delete(pendingUrl); }
        clearTimeout(timer);
        if (request === operation) { request = null; next = performance.now() + TV_PHOTO_POLL_MS; }
      }
    }

    const watch = setInterval(() => {
      if (!available()) return;
      if (lease.expired(performance.now())) invalidate('expired');
      if (performance.now() >= next) void poll();
    }, 100);
    const hide = () => invalidate('error');
    const pagehide = () => { pageVisible = false; hide(); };
    const resume = () => { if (available()) { invalidate('loading'); next = 0; void poll(); } };
    const pageshow = () => { pageVisible = true; resume(); };
    const visibility = () => document.hidden ? hide() : resume();
    window.addEventListener('offline', hide); window.addEventListener('online', resume);
    window.addEventListener('pagehide', pagehide); window.addEventListener('pageshow', pageshow);
    document.addEventListener('visibilitychange', visibility);
    void poll();
    return () => {
      mounted = false; invalidate('error'); clearInterval(watch);
      window.removeEventListener('offline', hide); window.removeEventListener('online', resume);
      window.removeEventListener('pagehide', pagehide); window.removeEventListener('pageshow', pageshow);
      document.removeEventListener('visibilitychange', visibility);
      if (paint.current === paintFrame) { paint.current = null; failImage.current = null; }
    };
  }, [deviceId, active]);

  // No src is stored in React props. A deferred React commit must pass the live
  // epoch/deadline gate again before attaching any decoded object URL.
  useLayoutEffect(() => { paint.current?.(); });
  if (!active || view.deviceId !== deviceId || view.mode !== 'photos') return null;
  const message = view.status === 'empty' ? '还没有可播放的照片，请在手机上允许这台电视展示照片。'
    : view.status === 'expired' ? '照片显示授权已到期，正在重新核对。'
      : view.status === 'error' ? '连接或照片许可暂不可用，画面已清除。'
        : view.status === 'loading' ? '正在核对照片并加载…' : '';
  return <View testID="tv-photo-player" accessibilityLabel="已授权照片轮播" style={styles.overlay}>
    <img ref={image} data-testid="tv-photo-image" alt="已授权的家庭照片" hidden onError={() => failImage.current?.()}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }} />
    {!!message && <View style={styles.message}>
      {view.status === 'loading' && <ActivityIndicator color="#fff" size="large" />}
      <Text testID="tv-photo-status" accessibilityLiveRegion="polite" style={styles.text}>{message}</Text>
    </View>}
    {view.count > 0 && <Text testID="tv-photo-position" style={styles.position}>{view.position + 1} / {view.count}{view.paused ? ' · 已暂停' : ''}</Text>}
  </View>;
}
const styles = StyleSheet.create({
  overlay: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, zIndex: 30, backgroundColor: '#090b0e', alignItems: 'center', justifyContent: 'center' },
  message: { gap: 20, maxWidth: 840, padding: 32, alignItems: 'center' },
  text: { color: '#f4f4f5', textAlign: 'center', fontSize: 28, lineHeight: 40 },
  position: { position: 'absolute', bottom: 24, right: 24, paddingVertical: 10, paddingHorizontal: 18, borderRadius: 24, backgroundColor: '#090b0e', color: '#fff', fontSize: 20 },
});
