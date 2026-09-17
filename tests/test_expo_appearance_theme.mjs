import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { test } from 'node:test';

// Run the real theme factory without a DOM/native runtime. Only the external
// framework defaults/font configurator are stubbed; no product colours or
// density values are duplicated here. Component rendering is a browser check.
const variants = ['displayLarge', 'displayMedium', 'displaySmall', 'headlineLarge', 'headlineMedium', 'headlineSmall',
  'titleLarge', 'titleMedium', 'titleSmall', 'bodyLarge', 'bodyMedium', 'bodySmall', 'labelLarge', 'labelMedium', 'labelSmall'];
const modules = {
  'react-native': `export const Platform={select:choices=>choices.web};`,
  'react-native-paper': `export const MD3LightTheme={dark:false,version:3,isV3:true,colors:{}};
    export const MD3DarkTheme={...MD3LightTheme,dark:true};
    export const configureFonts=({config})=>Object.fromEntries(${JSON.stringify(variants)}.map(key=>[key,{...config}]));
    export const useTheme=()=>globalThis.appearanceTestTheme || MD3LightTheme;`,
};
const hooks = registerHooks({ resolve(specifier, context, next) {
  return modules[specifier] ? { url: 'data:text/javascript,' + encodeURIComponent(modules[specifier]), shortCircuit: true } : next(specifier, context);
} });
const { makeTheme, displayDensities, useDisplayDensity, expoTokens } = await import('../frontend/src/ui/theme.ts');
hooks.deregister();

function luminance(hex) {
  assert.match(hex, /^#[0-9a-f]{6}$/i);
  const rgb = [1, 3, 5].map(at => parseInt(hex.slice(at, at + 2), 16) / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
}
function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (values[0] + 0.05) / (values[1] + 0.05);
}
test('no-argument theme retains the Expo white/black default independently of legacy forest themes', () => {
  const theme = makeTheme();
  assert.equal(theme.dark, false); assert.equal(theme.displayDensity, 'comfortable');
  assert.equal(theme.colors.background, '#ffffff'); assert.equal(theme.colors.primary, '#000000');
  assert.deepEqual(theme, makeTheme('light', 'comfortable'));
  assert.equal(expoTokens.contentMaxWidth, 1280); assert.equal(expoTokens.cardRadius, 32);
});
for (const mode of ['light', 'dark']) test(`${mode}: small foreground text has at least 4.5:1 contrast on its semantic surface`, () => {
  const { colors: c } = makeTheme(mode);
  const pairs = [['onBackground', 'background'], ['onSurface', 'surface'], ['onSurfaceVariant', 'surfaceVariant'],
    ['onPrimary', 'primary'], ['onPrimaryContainer', 'primaryContainer'], ['onSecondary', 'secondary'],
    ['onSecondaryContainer', 'secondaryContainer'], ['onTertiary', 'tertiary'], ['onTertiaryContainer', 'tertiaryContainer'],
    ['onError', 'error'], ['onErrorContainer', 'errorContainer'], ['inverseOnSurface', 'inverseSurface']];
  for (const [foreground, background] of pairs) assert(contrast(c[foreground], c[background]) >= 4.5, `${mode} ${foreground}/${background}`);
  // Error text and explanatory copy are also used directly on page/card/dialog surfaces.
  for (const surface of ['background', 'surface', 'surfaceVariant', 'secondaryContainer']) {
    for (const ink of ['onSurface', 'onSurfaceVariant', 'error']) assert(contrast(c[ink], c[surface]) >= 4.5, `${mode} ${ink}/${surface}`);
  }
});
test('dark surfaces are charcoal with opaque tonal elevations and reversed button ink', () => {
  const theme = makeTheme('dark'); assert.equal(theme.dark, true);
  assert(luminance(theme.colors.background) < 0.02); assert(luminance(theme.colors.onSurface) > 0.8);
  for (const [name, colour] of Object.entries(theme.colors.elevation)) {
    if (name !== 'level0') assert(contrast(theme.colors.onSurface, colour) >= 4.5, name);
  }
});
test('compact changes only whitespace: fonts, roundness and all semantic colours stay equal', () => {
  for (const mode of ['light', 'dark']) {
    const comfortable = makeTheme(mode), compact = makeTheme(mode, 'compact');
    assert.deepEqual(compact.fonts, comfortable.fonts); assert.deepEqual(compact.colors, comfortable.colors);
    assert.equal(compact.roundness, comfortable.roundness);
    assert.equal(compact.fonts.bodyLarge.fontSize, 16); assert.equal(compact.fonts.bodyLarge.lineHeight, 24);
  }
  assert.deepEqual(makeTheme('dark').fonts, makeTheme('light').fonts);
});
test('density reduces whitespace on both viewport sizes while preserving 44px targets', () => {
  const { comfortable, compact } = displayDensities;
  assert.deepEqual(Object.keys(compact), Object.keys(comfortable));
  for (const key of Object.keys(comfortable)) {
    assert(compact[key] > 0 && compact[key] <= comfortable[key], key);
  }
  for (const density of Object.values(displayDensities)) {
    assert(density.touchTarget >= 44);
    assert(density.headerHeightNarrow >= density.touchTarget);
    assert(density.headerHeight >= density.touchTarget);
    assert(density.cardPaddingNarrow >= 16);
  }
  assert(compact.rowPadding < comfortable.rowPadding); assert(compact.gridGap < comfortable.gridGap);
});
test('unknown preferences and a plain Paper provider fall back to light/comfortable', () => {
  assert.deepEqual(makeTheme('forest', 'tiny'), makeTheme());
  try {
    globalThis.appearanceTestTheme = makeTheme('dark', 'compact');
    assert.equal(useDisplayDensity(), displayDensities.compact);
    globalThis.appearanceTestTheme = { dark: true };
    assert.equal(useDisplayDensity(), displayDensities.comfortable);
  } finally { delete globalThis.appearanceTestTheme; }
});
