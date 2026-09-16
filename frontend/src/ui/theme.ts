import { Platform } from 'react-native';
import { configureFonts, MD3LightTheme, type MD3Theme } from 'react-native-paper';

// Current expo.dev reference: docs/EXPO-SITE-STYLE.md. Classic/TV palettes stay separate.
export const expoTokens = {
  canvas: '#ffffff', canvasSoft: '#f8f8fa', ink: '#1c2024', body: '#60646c',
  primary: '#000000', strong: '#f0f0f3', hairline: '#f0f0f3', outline: '#dcdee0',
  link: '#0d74ce', skyLight: '#cfe7ff', skyMid: '#a8c8e8',
  controlRadius: 8, buttonRadius: 999, cardRadius: 32, cardRadiusCompact: 24,
  contentMaxWidth: 1280, compactBreakpoint: 768,
} as const;
const fontFamily = Platform.select({
  web: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  ios: 'System', default: 'sans-serif',
});
const fonts = configureFonts({ config: { fontFamily, letterSpacing: 0, fontWeight: '400' } });

export function makeTheme(): MD3Theme {
  const t = expoTokens;
  return {
    ...MD3LightTheme,
    // MD3 Button uses x5 (25: a pill at its default 40px height). Its generic
    // Card uses x3 (15), not a giant radius; SectionCard and inputs stay explicit.
    roundness: 5,
    colors: {
      ...MD3LightTheme.colors,
      primary: t.primary, onPrimary: t.canvas,
      primaryContainer: t.strong, onPrimaryContainer: t.ink,
      secondary: t.ink, onSecondary: t.canvas,
      secondaryContainer: t.strong, onSecondaryContainer: t.ink,
      tertiary: t.body, onTertiary: t.canvas,
      tertiaryContainer: t.strong, onTertiaryContainer: t.ink,
      background: t.canvas, onBackground: t.ink,
      surface: t.canvas, onSurface: t.ink,
      surfaceVariant: t.canvasSoft, onSurfaceVariant: t.body,
      outline: t.outline, outlineVariant: t.hairline,
      surfaceDisabled: t.strong, onSurfaceDisabled: '#767676',
      inverseSurface: t.ink, inverseOnSurface: t.canvas, inversePrimary: t.canvas,
      // The reference pale error is unsuitable as small text on white.
      error: '#b4232a', onError: t.canvas, errorContainer: '#fff0f0', onErrorContainer: '#7d1a20',
      elevation: { level0: 'transparent', level1: t.canvas, level2: t.canvas, level3: t.canvasSoft, level4: t.canvasSoft, level5: t.canvasSoft },
    },
    fonts: {
      ...fonts,
      displayLarge: { ...fonts.displayLarge, fontSize: 64, lineHeight: 70.4, fontWeight: '600', letterSpacing: -3 },
      displayMedium: { ...fonts.displayMedium, fontSize: 48, lineHeight: 52.8, fontWeight: '600', letterSpacing: -1.2 },
      displaySmall: { ...fonts.displaySmall, fontSize: 36, lineHeight: 40, fontWeight: '600', letterSpacing: -0.9 },
      headlineLarge: { ...fonts.headlineLarge, fontSize: 36, lineHeight: 40, fontWeight: '600', letterSpacing: -0.9 },
      headlineMedium: { ...fonts.headlineMedium, fontSize: 28, lineHeight: 36, fontWeight: '600' },
      headlineSmall: { ...fonts.headlineSmall, fontSize: 28, lineHeight: 32, fontWeight: '600', letterSpacing: -0.5 },
      titleLarge: { ...fonts.titleLarge, fontSize: 22, lineHeight: 30, fontWeight: '600' },
      titleMedium: { ...fonts.titleMedium, fontSize: 18, lineHeight: 26, fontWeight: '600' },
      titleSmall: { ...fonts.titleSmall, fontSize: 16, lineHeight: 24, fontWeight: '600' },
      bodyLarge: { ...fonts.bodyLarge, fontSize: 16, lineHeight: 24 },
      bodyMedium: { ...fonts.bodyMedium, fontSize: 14, lineHeight: 22 },
      bodySmall: { ...fonts.bodySmall, fontSize: 13, lineHeight: 20 },
      labelLarge: { ...fonts.labelLarge, fontSize: 14, lineHeight: 20, fontWeight: '600' },
      labelMedium: { ...fonts.labelMedium, fontSize: 13, lineHeight: 19, fontWeight: '500' },
      labelSmall: { ...fonts.labelSmall, fontSize: 12, lineHeight: 18, fontWeight: '500' },
    },
  };
}
