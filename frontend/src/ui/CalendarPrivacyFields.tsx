import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';
import type { CalendarEvent, Member } from '../lib/types';
import { calendarPrivacy, type CalendarVisibility } from '../lib/calendarPrivacy';
import { SelectionRow } from './SelectionRow';

export default function CalendarPrivacyFields({ event, user, value, onChange, disabled = false }: {
  event?: CalendarEvent; user?: Member | null; value: CalendarVisibility;
  onChange: (value: CalendarVisibility) => void; disabled?: boolean;
}) {
  const scope = calendarPrivacy(event, user);
  return <View style={styles.field}>
    <Text variant="labelMedium">谁可以看到</Text>
    {scope.canChange ? <View accessibilityRole="radiogroup" accessibilityLabel="日程可见范围" style={styles.options}>
      {([{ value: 'private', label: '仅自己' }, { value: 'shared', label: '家庭共享' }] as const).map(option =>
        <View key={option.value} style={styles.option}><SelectionRow kind="radio" label={option.label}
          accessibilityLabel={'日程可见范围：' + option.label} checked={value === option.value} disabled={disabled}
          onPress={() => { if (!disabled) onChange(option.value); }} /></View>)}
    </View> : <Text variant="bodyMedium">{scope.visibility === 'private' ? '仅自己' : scope.visibility === 'shared' ? '家庭共享' : '可见范围待核对'}</Text>}
    <Text variant="bodySmall">{scope.canChange
      ? value === 'private' ? '仅你可见，其他家庭成员和电视不可见。' : '家庭成员和电视可见；共享后可共同编辑。'
      : scope.notice}</Text>
  </View>;
}
const styles = StyleSheet.create({ field: { gap: 6 }, options: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  option: { flexGrow: 1, flexBasis: 160, minWidth: 0 } });
