import React from 'react';
import { View } from 'react-native';
import { Button, Text, TextInput, useTheme } from 'react-native-paper';
import { isConfirmedDate } from '../lib/photoConfirmedDate';

type Props = {
  value: string; saved: string | null; busy: boolean; blocked: boolean; otherDraft: boolean;
  needsCheck: boolean; message: string; change: (value: string) => void;
  save: (value: string | null) => void; recheck: () => void; discardOther: () => void; cancel: () => void;
};
export default function PhotoConfirmedDate(props: Props) {
  const theme = useTheme();
  const disabled = props.busy || props.blocked || props.otherDraft;
  return <View testID="photo-confirmed-date" style={{ gap: 8, padding: 12, borderRadius: 12, backgroundColor: theme.colors.surfaceVariant }}>
    <Text variant="titleMedium">本人确认日期</Text>
    <Text variant="bodySmall">用于旅行建议和那年今日，不代表来源拍摄时刻。</Text>
    <Text variant="bodySmall">当前日期：{props.saved || '尚未确认'}</Text>
    <TextInput testID="photo-confirmed-date-input" mode="outlined" label="本人确认日期（YYYY-MM-DD）"
      accessibilityLabel="本人确认日期（YYYY-MM-DD）" value={props.value} maxLength={10}
      autoCapitalize="none" disabled={disabled} onChangeText={props.change} />
    {props.otherDraft && <><Text>请先保存其他照片修改，或明确放弃这些修改，再单独保存日期。</Text>
      <Button disabled={props.busy || props.blocked} onPress={props.discardOther}>放弃其他未保存修改</Button></>}
    <Text testID="photo-confirmed-date-status" accessibilityLiveRegion="polite">{props.message || '日期单独保存，不会连带提交照片说明、共享或旅行修改。'}</Text>
    {props.needsCheck ? <Button testID="photo-confirmed-date-recheck" disabled={props.busy} onPress={props.recheck}>核对当前照片日期</Button> : <>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 4 }}>
        <Button testID="photo-confirmed-date-save" mode="outlined" contentStyle={{ minHeight: 44 }}
          disabled={disabled || !isConfirmedDate(props.value)} onPress={() => props.save(props.value)}>保存照片日期</Button>
        <Button testID="photo-confirmed-date-clear" contentStyle={{ minHeight: 44 }}
          disabled={disabled || props.saved === null} onPress={() => props.save(null)}>清除照片日期</Button>
      </View>
      {props.value !== (props.saved || '') && <Button disabled={props.busy || props.blocked} onPress={props.cancel}>取消日期输入</Button>}
    </>}
  </View>;
}
