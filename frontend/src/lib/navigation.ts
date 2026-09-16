import { Linking, Platform } from 'react-native';
import { syncAuthorizeUrl, type SyncProvider } from './authNavigation';

/** Start the existing same-tab authorization; acceptance is not binding success. */
export function openSyncProvider(raw: string, provider: SyncProvider): boolean {
  const web = Platform.OS === 'web' && typeof window !== 'undefined';
  const origin = web ? window.location.origin : (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
  const target = syncAuthorizeUrl(raw, provider, origin);
  if (!target) return false;
  if (web) window.location.assign(target);
  else void Linking.openURL(target);
  return true;
}

/** Controlled same-origin application destinations only; never a new browser tab. */
export function openLocal(path: string) {
  if (!/^\/(?:classic(?:#[a-z]+)?|tv|space\/[a-z0-9-]+|auth\/(?:microsoft|google)\/login)$/.test(path)) return;
  if (Platform.OS === 'web' && typeof window !== 'undefined') window.location.assign(path);
  else {
    const origin = (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
    if (origin) void Linking.openURL(origin+path);
  }
}

/** Returns URL acceptance, not confirmation that the browser opened a tab. */
export function openPhotosProvider(raw: string, kind: 'authorize' | 'picker'): boolean {
  let url: URL;
  try { url = new URL(raw); } catch { return false; }
  if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return false;
  if (kind === 'authorize'
    ? url.hostname !== 'accounts.google.com' || url.pathname !== '/o/oauth2/v2/auth'
    : url.hostname !== 'photos.google.com') return false;
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    if (kind === 'authorize') window.location.assign(url.href);
    else {
      // Keep the import status page open while Google handles the selection.
      window.open(url.href, '_blank', 'noopener,noreferrer');
    }
    return true;
  }
  void Linking.openURL(url.href);
  return true;
}
