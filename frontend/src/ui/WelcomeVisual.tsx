import React from 'react';
import { StyleSheet, View } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useTheme } from 'react-native-paper';

// Decorative only: no sample events, balances or account information.
export default function WelcomeVisual() {
  const theme = useTheme();
  const surface = { backgroundColor: theme.colors.surface, borderColor: theme.colors.outlineVariant };
  return <View accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" pointerEvents="none"
    style={[styles.canvas, { backgroundColor: theme.colors.surfaceVariant }]}>
    <View style={[styles.orbit, { borderColor: theme.colors.outlineVariant }]} />
    <View style={[styles.orbit, styles.orbitInner, { borderColor: theme.colors.outlineVariant }]} />
    <View style={[styles.home, surface]}><MaterialCommunityIcons name="home-outline" size={62} color={theme.colors.onSurface} /></View>
    <View style={[styles.tile, styles.calendar, surface]}>
      <MaterialCommunityIcons name="calendar-blank-outline" size={28} color={theme.colors.onSurface} />
      <View style={styles.dots}>{Array.from({ length: 6 }, (_, index) => <View key={index} style={[styles.dot, { backgroundColor: index === 3 ? theme.colors.onSurface : theme.colors.outlineVariant }]} />)}</View>
    </View>
    <View style={[styles.tile, styles.checklist, surface]}>{[0, 1, 2].map(index => <View key={index} style={styles.checkRow}>
      <MaterialCommunityIcons name={index === 0 ? 'checkbox-marked-circle' : 'checkbox-blank-circle-outline'} size={15} color={theme.colors.onSurface} />
      <View style={[styles.line, { backgroundColor: theme.colors.outlineVariant, width: index === 1 ? 30 : 42 }]} />
    </View>)}</View>
    <View style={[styles.photo, surface]}><MaterialCommunityIcons name="image-outline" size={27} color={theme.colors.onSurface} /></View>
  </View>;
}

const styles = StyleSheet.create({
  canvas: { height: 240, width: '100%', maxWidth: 480, borderRadius: 40, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  orbit: { position: 'absolute', width: 340, height: 340, borderRadius: 170, borderWidth: 1 },
  orbitInner: { width: 210, height: 210, borderRadius: 105 },
  home: { width: 112, height: 112, borderRadius: 32, borderWidth: 1, justifyContent: 'center', alignItems: 'center' },
  tile: { position: 'absolute', borderWidth: 1, borderRadius: 20, padding: 15 },
  calendar: { left: 24, top: 26, width: 91, gap: 10, transform: [{ rotate: '-8deg' }] },
  dots: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, width: 58 }, dot: { width: 12, height: 6, borderRadius: 3 },
  checklist: { right: 18, bottom: 22, gap: 10, transform: [{ rotate: '7deg' }] },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 9 }, line: { height: 5, borderRadius: 3 },
  photo: { position: 'absolute', right: 42, top: 25, width: 56, height: 56, borderWidth: 1, borderRadius: 17, justifyContent: 'center', alignItems: 'center', transform: [{ rotate: '-10deg' }] },
});
