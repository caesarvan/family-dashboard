import { Platform } from 'react-native';
import { configureFonts, MD3DarkTheme, MD3LightTheme, useTheme, type MD3Theme } from 'react-native-paper';

// Current expo.dev reference: docs/EXPO-SITE-STYLE.md. Classic/TV palettes stay separate.
export const expoTokens = {
  canvas: '#ffffff', canvasSoft: '#f8f8fa', ink: '#1c2024', body: '#60646c',
  primary: '#000000', strong: '#f0f0f3', hairline: '#f0f0f3', outline: '#dcdee0',
  link: '#0d74ce', skyLight: '#cfe7ff', skyMid: '#a8c8e8',
  controlRadius: 8, buttonRadius: 999, cardRadius: 32, cardRadiusCompact: 24,
  contentMaxWidth: 1280, compactBreakpoint: 768,
} as const;
export type ColorMode = 'light' | 'dark';
export type DisplayDensity = 'comfortable' | 'compact';
export type AppTheme = MD3Theme & { displayDensity: DisplayDensity };

// Density changes space, never type size, breakpoints, card shape or hit targets.
// Narrow viewport values remain independent of the member's density preference.
export const displayDensities = {
  comfortable: {
    touchTarget: 44, cardPadding: 28, cardPaddingNarrow: 20, sectionGap: 18,
    pageGap: 16, pageGapNarrow: 12, pageBottom: 24, pageBottomNarrow: 16,
    headerHeight: 72, headerHeightNarrow: 64, contentTop: 32, contentTopNarrow: 20, contentBottom: 40,
    screenGap: 24, screenGapNarrow: 18, gridGap: 20, rowPadding: 10,
    heroTop: 20, heroBottom: 8, heroGap: 28, heroGapNarrow: 14,
    overviewGap: 32, overviewGapNarrow: 14, moneyPadding: 28, moneyPaddingNarrow: 18, detailPadding: 16, tripGap: 12,
  },
  compact: {
    touchTarget: 44, cardPadding: 20, cardPaddingNarrow: 16, sectionGap: 12,
    pageGap: 12, pageGapNarrow: 8, pageBottom: 16, pageBottomNarrow: 12,
    headerHeight: 64, headerHeightNarrow: 56, contentTop: 24, contentTopNarrow: 16, contentBottom: 28,
    screenGap: 16, screenGapNarrow: 12, gridGap: 12, rowPadding: 6,
    heroTop: 12, heroBottom: 4, heroGap: 20, heroGapNarrow: 10,
    overviewGap: 24, overviewGapNarrow: 10, moneyPadding: 20, moneyPaddingNarrow: 12, detailPadding: 10, tripGap: 8,
  },
} as const;
export function useDisplayDensity() {
  const theme = useTheme<AppTheme>();
  return displayDensities[theme.displayDensity === 'compact' ? 'compact' : 'comfortable'];
}
const darkTokens = {
  canvas: '#111113', canvasSoft: '#212225', surface: '#18191b', ink: '#f2f2f5', body: '#b4b6bf',
  primary: '#f2f2f5', strong: '#2b2d31', hairline: '#303238', outline: '#5b5f67',
} as const;
const fontFamily = Platform.select({
  web: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  ios: 'System', default: 'sans-serif',
});
const fonts = configureFonts({ config: { fontFamily, letterSpacing: 0, fontWeight: '400' } });

export function makeTheme(colorMode: ColorMode = 'light', density: DisplayDensity = 'comfortable'): AppTheme {
  const dark = colorMode === 'dark';
  const t = dark ? darkTokens : { ...expoTokens, surface: expoTokens.canvas };
  const base = dark ? MD3DarkTheme : MD3LightTheme;
  return {
    ...base,
    displayDensity: density === 'compact' ? 'compact' : 'comfortable',
    // MD3 Button uses x5 (25: a pill at its default 40px height). Its generic
    // Card uses x3 (15), not a giant radius; SectionCard and inputs stay explicit.
    roundness: 5,
    colors: {
      ...base.colors,
      primary: t.primary, onPrimary: t.canvas,
      primaryContainer: t.strong, onPrimaryContainer: t.ink,
      secondary: t.ink, onSecondary: t.canvas,
      secondaryContainer: t.strong, onSecondaryContainer: t.ink,
      tertiary: t.body, onTertiary: t.canvas,
      tertiaryContainer: t.strong, onTertiaryContainer: t.ink,
      background: t.canvas, onBackground: t.ink,
      surface: t.surface, onSurface: t.ink,
      surfaceVariant: t.canvasSoft, onSurfaceVariant: t.body,
      outline: t.outline, outlineVariant: t.hairline,
      surfaceDisabled: t.strong, onSurfaceDisabled: dark ? '#8b8d98' : '#767676',
      inverseSurface: t.ink, inverseOnSurface: t.canvas, inversePrimary: t.canvas,
      // The reference pale error is unsuitable as small text on white.
      error: dark ? '#ffb4b4' : '#b4232a', onError: dark ? '#440e12' : t.canvas,
      errorContainer: dark ? '#511d23' : '#fff0f0', onErrorContainer: dark ? '#ffdadb' : '#7d1a20',
      shadow: '#000000', scrim: '#000000', backdrop: dark ? 'rgba(0, 0, 0, 0.72)' : 'rgba(28, 32, 36, 0.4)',
      elevation: { level0: 'transparent', level1: t.surface, level2: t.surface, level3: t.canvasSoft, level4: t.canvasSoft, level5: t.canvasSoft },
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
