import { Linking, Platform } from 'react-native';

/** Controlled same-origin application destinations only; never a new browser tab. */
export function openLocal(path: string) {
  if (!/^\/(?:classic(?:#[a-z]+)?|tv|space\/[a-z0-9-]+|auth\/(?:microsoft|google)\/login)$/.test(path)) return;
  if (Platform.OS === 'web' && typeof window !== 'undefined') window.location.assign(path);
  else {
    const origin = (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
    if (origin) void Linking.openURL(origin+path);
  }
}
