import React from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { Icon, Text, TouchableRipple, useTheme } from 'react-native-paper';

/** Paper surface with matching visual, native and web selection state. */
export function SelectionRow({ kind = 'checkbox', label, accessibilityLabel = label, checked, disabled = false, onPress }: {
  kind?: 'radio' | 'checkbox'; label: string; accessibilityLabel?: string;
  checked: boolean; disabled?: boolean; onPress: () => void;
}) {
  const theme = useTheme();
  const color = disabled ? theme.colors.onSurfaceDisabled : checked ? theme.colors.primary : theme.colors.onSurfaceVariant;
  // The installed Paper Item components do not forward ARIA state to their
  // outer control. Use the same Paper composition as our account/inventory UI.
  const keyboard = Platform.OS === 'web' ? { onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === ' ' || event.key === 'Spacebar') {
      event.preventDefault(); event.stopPropagation();
      if (!disabled && !event.repeat) onPress();
    } else if (kind === 'radio' && !disabled && ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(event.key)) {
      const group = event.currentTarget.closest('[role="radiogroup"]');
      const controls = Array.from(group?.querySelectorAll<HTMLElement>('[role="radio"]') || []).filter(control => control.getAttribute('aria-disabled') !== 'true');
      const index = controls.indexOf(event.currentTarget);
      if (index >= 0 && controls.length) {
        event.preventDefault(); event.stopPropagation();
        const direction = ['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1;
        const next = controls[(index + direction + controls.length) % controls.length];
        next.focus(); next.click();
      }
    }
  } } : {};
  return <TouchableRipple {...keyboard} accessible accessibilityRole={kind} accessibilityLabel={accessibilityLabel}
    accessibilityState={{ checked, disabled }} aria-checked={checked} aria-disabled={disabled}
    disabled={disabled} onPress={() => { if (!disabled) onPress(); }}
    style={state => [styles.row, { borderColor: state.focused ? theme.colors.primary : 'transparent' }]}>
    <View style={styles.content} pointerEvents="none" aria-hidden accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Icon source={kind === 'radio' ? checked ? 'radiobox-marked' : 'radiobox-blank' : checked ? 'checkbox-marked' : 'checkbox-blank-outline'} size={24} color={color} />
      <Text variant="bodyMedium" style={[styles.label, { color: disabled ? theme.colors.onSurfaceDisabled : theme.colors.onSurface }]}>{label}</Text>
    </View>
  </TouchableRipple>;
}
const styles = StyleSheet.create({
  row: { minHeight: 48, borderWidth: 2, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8 },
  content: { flexDirection: 'row', alignItems: 'center', gap: 12 }, label: { flex: 1, minWidth: 0 },
});
