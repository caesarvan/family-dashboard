import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Button, Text, useTheme } from 'react-native-paper';
import type { PhotoJourneySuggestions as Suggestions } from '../lib/photoJourneySuggestions';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';

type Props = {
  busy: boolean; dirty: boolean; blocked: boolean;
  load: () => Promise<Suggestions | null>;
  confirm: (suggestions: Suggestions, journeyId: string) => Promise<void>;
  cancelDraft: () => void;
};

// The parent keys this local view by photo, revision, filter and draft. It owns
// the shared write lock, session checks and readback; no payload lives here.
export default function PhotoJourneySuggestions(props: Props) {
  const theme = useTheme(), density = useDisplayDensity();
  const [data, setData] = useState<Suggestions | null>(null), [selected, setSelected] = useState('');
  const live = useRef(false), pending = useRef(false);
  const latest = useRef(props); latest.current = props;
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  async function load() {
    const current = latest.current;
    if (pending.current || current.busy || current.dirty || current.blocked) return;
    pending.current = true; setData(null); setSelected('');
    try {
      const result = await current.load();
      if (live.current && !latest.current.dirty && !latest.current.blocked) setData(result);
    } finally { pending.current = false; }
  }
  async function confirm() {
    const current = latest.current;
    if (pending.current || current.busy || current.dirty || current.blocked || !data || !selected) return;
    pending.current = true;
    try { await current.confirm(data, selected); }
    finally { if (live.current) { setData(null); setSelected(''); } pending.current = false; }
  }
  if (props.blocked) return null;
  const touch = { minHeight: density.touchTarget };
  return <View testID="photo-journey-suggestions" style={[styles.panel, { gap: density.tripGap, padding: density.detailPadding, backgroundColor: theme.colors.surfaceVariant }]}>
    <Text variant="titleMedium" accessibilityRole="header">照片与旅行</Text>
    {props.dirty ? <>
      <Text>请先保存或取消未保存的修改，再查看旅行建议。</Text>
      <Button contentStyle={touch} disabled={props.busy} onPress={props.cancelDraft}>取消未保存的修改</Button>
    </> : <>
      <Text variant="bodyMedium">按本人确认日期或已记录的来源时间，找一找日期相符的旅行。</Text>
      <Button contentStyle={touch} mode="outlined" disabled={props.busy} onPress={() => void load()}>查看旅行建议</Button>
      {data && <View style={{ gap: density.tripGap }}>
        {(data.version === 2 ? data.dateBasis === 'unknown' : data.sourceTimeState === 'unknown') ? <Text>这张照片没有可核对的日期。你仍可在上方手动关联旅行。</Text> : <>
          {data.dateBasis === 'userConfirmedDate' ? <><Text>按本人确认日期匹配，未换算时区</Text><Text>本人确认日期：{data.userConfirmedDate}</Text></>
            : <Text selectable variant="bodySmall" style={styles.wrap}>来源时间：{data.sourceCreatedAt}</Text>}
          {!data.suggestions.length && <Text>暂无日期相符的旅行。你仍可在上方手动关联。</Text>}
        </>}
        <View accessibilityRole="radiogroup" accessibilityLabel="日期相符的旅行" style={{ gap: density.tripGap }}>
        {data.suggestions.map(item => <View key={item.journeyId} testID={'photo-journey-suggestion-' + item.journeyId}
          style={[styles.option, { borderColor: theme.colors.outlineVariant, backgroundColor: theme.colors.surface }]}>
          <SelectionRow kind="radio" label={item.title || '未命名旅行'} accessibilityLabel={'选择旅行：' + (item.title || '未命名旅行')}
            checked={selected === item.journeyId} disabled={props.busy || item.alreadyLinked} onPress={() => setSelected(item.journeyId)} />
          <View style={styles.copy}>
            <Text>{item.start} 至 {item.end}</Text>
            <Text style={styles.wrap}>{data.dateBasis === 'userConfirmedDate' ? '本人确认日期' : '来源日期'}：{item.matchDate ?? item.sourceDate}</Text>
            <Text variant="bodySmall">旅行参考时区：{item.referenceTimezone}</Text>
            {data.dateBasis !== 'userConfirmedDate' && item.referenceTimezoneSource === 'legacy_default' && <Text variant="bodySmall">旧旅行按上海时区核对。</Text>}
            {item.alreadyLinked && <Text>当前已关联</Text>}
          </View>
        </View>)}
        </View>
        {data.hasMore && <Text>仅显示前 20 条匹配旅行；其他旅行可在上方手动选择。</Text>}
        {!!data.suggestions.length && <>
          <Text variant="bodySmall">日期相符不代表拍摄地点或实际到访。确认只更改旅行关联，共享和电视范围保持。</Text>
          <Button mode="contained" contentStyle={touch} disabled={props.busy || !selected} onPress={() => void confirm()}>确认关联所选旅行</Button>
        </>}
      </View>}
    </>}
  </View>;
}
const styles = StyleSheet.create({
  panel: { borderRadius: 16 }, option: { borderWidth: 1, borderRadius: 12, overflow: 'hidden' },
  copy: { paddingHorizontal: 14, paddingBottom: 12, gap: 6 }, wrap: { flexShrink: 1 },
});
