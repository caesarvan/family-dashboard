import { Platform } from 'react-native';
import { configureFonts, MD3DarkTheme, MD3LightTheme, type MD3Theme } from 'react-native-paper';
import type { ThemeName } from '../lib/types';

// Expo DESIGN: quiet surfaces, neutral primary actions, readable Chinese text.
// Use system fallbacks; no remote font request is needed to open the application.
const fontFamily = Platform.select({
  web: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  ios: 'System',
  default: 'sans-serif',
});
const fonts = configureFonts({ config: { fontFamily, letterSpacing: 0 } });

export function makeTheme(name: ThemeName): MD3Theme {
  const light = name === 'light';
  const ocean = name === 'ocean';
  const base = light ? MD3LightTheme : MD3DarkTheme;
  const surface = light ? '#ffffff' : ocean ? '#192a38' : '#1a2925';
  const background = light ? '#f7f8fa' : ocean ? '#111e2b' : '#111d19';
  const soft = light ? '#eff2f4' : ocean ? '#233b4a' : '#263b31';
  const accent = light ? '#416750' : ocean ? '#a4d3df' : '#b7d7bc';
  const ink = light ? '#171b1e' : '#f1f5f3';
  const muted = light ? '#58646b' : ocean ? '#b6c7d2' : '#b8c9be';
  return {
    ...base,
    // Paper MD3 buttons use 5 × roundness; cards set their explicit 12px radius.
    roundness: 1.6,
    colors: {
      ...base.colors,
      primary: light ? '#000000' : '#f1f5f3',
      onPrimary: light ? '#ffffff' : '#111917',
      primaryContainer: soft,
      onPrimaryContainer: ink,
      secondary: accent,
      onSecondary: light ? '#ffffff' : '#13221d',
      secondaryContainer: soft,
      onSecondaryContainer: ink,
      tertiary: accent,
      onTertiary: light ? '#ffffff' : '#13221d',
      tertiaryContainer: soft,
      onTertiaryContainer: ink,
      background,
      onBackground: ink,
      surface,
      onSurface: ink,
      surfaceVariant: soft,
      onSurfaceVariant: muted,
      outline: light ? '#78858d' : '#82948c',
      outlineVariant: light ? '#dce2e6' : ocean ? '#3c5260' : '#354b3e',
      surfaceDisabled: light ? '#e4e7e9' : '#34453e',
      onSurfaceDisabled: light ? '#687279' : '#99aaa1',
      inverseSurface: light ? '#24332c' : '#f1f5f3',
      inverseOnSurface: light ? '#f1f5f3' : '#1a2925',
      inversePrimary: light ? '#b7d7bc' : '#416750',
      elevation: { level0: 'transparent', level1: surface, level2: surface, level3: soft, level4: soft, level5: soft },
    },
    fonts: {
      ...fonts,
      headlineLarge: { ...fonts.headlineLarge, fontSize: 30, lineHeight: 38, fontWeight: '600' },
      headlineMedium: { ...fonts.headlineMedium, fontSize: 26, lineHeight: 34, fontWeight: '600' },
      headlineSmall: { ...fonts.headlineSmall, fontSize: 24, lineHeight: 32, fontWeight: '600' },
      titleLarge: { ...fonts.titleLarge, fontSize: 20, lineHeight: 28, fontWeight: '600' },
      titleMedium: { ...fonts.titleMedium, fontSize: 17, lineHeight: 25, fontWeight: '600' },
      titleSmall: { ...fonts.titleSmall, fontSize: 15, lineHeight: 22, fontWeight: '600' },
      bodyLarge: { ...fonts.bodyLarge, fontSize: 16, lineHeight: 25 },
      bodyMedium: { ...fonts.bodyMedium, fontSize: 14, lineHeight: 22 },
      bodySmall: { ...fonts.bodySmall, fontSize: 13, lineHeight: 20 },
      labelLarge: { ...fonts.labelLarge, fontSize: 14, lineHeight: 20, fontWeight: '500' },
      labelMedium: { ...fonts.labelMedium, fontSize: 13, lineHeight: 19, fontWeight: '500' },
      labelSmall: { ...fonts.labelSmall, fontSize: 12, lineHeight: 18, fontWeight: '500' },
    },
  };
}
