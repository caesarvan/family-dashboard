import React from 'react';
import { View } from 'react-native';
import { Button, Text, useTheme } from 'react-native-paper';
import { photoSourceLabel, type Photo } from '../lib/photos';
import { DUPLICATE_LABEL, duplicateCoverageText, type PhotoDuplicates } from '../lib/photoDuplicates';

type Props = {
  data: PhotoDuplicates | null; busy: boolean; dirty: boolean; blocked: boolean;
  load: (offset: number) => void; open: (item: Photo) => void;
  thumbnail: (item: Photo, label: string) => React.ReactNode;
};
// Results live in the parent's identity/lifetime fence. No mount, polling or
// render effect starts a scan; every scan is an explicit button action.
export default function PhotoDuplicateHints(props: Props) {
  const theme = useTheme(); const disabled = props.busy || props.dirty || props.blocked;
  const data = props.dirty || props.blocked ? null : props.data;
  return <View testID="photo-duplicate-hints" style={{ gap: 12, padding: 16, borderRadius: 12, backgroundColor: theme.colors.surfaceVariant }}>
    <Text variant="titleSmall">重复照片提示</Text>
    <Text variant="bodySmall">只核对本人已保存的不同来源照片，不会自动删除或合并。</Text>
    {(props.dirty || props.blocked) && <Text>请先保存或核对当前修改，再查找重复照片。</Text>}
    <Button icon="image-search-outline" mode="outlined" contentStyle={{ minHeight: 44 }} disabled={disabled}
      onPress={() => props.load(0)}>{data ? '重新查找重复照片' : '查找重复照片'}</Button>
    {data && <>
      <Text accessibilityLiveRegion="polite">{DUPLICATE_LABEL}</Text>
      <Text variant="bodySmall">{duplicateCoverageText(data)}</Text>
      <Text>{data.total ? `本次检查找到 ${data.total} 张展示副本一致的照片` : '本次检查未找到展示副本一致的照片'}</Text>
      {data.items.map(item => <View key={item.id} testID={`photo-duplicate-${item.id}`} style={{ gap: 6 }}>
        <View style={{ width: 88, height: 88, overflow: 'hidden', borderRadius: 8 }}>{props.thumbnail(item, item.caption || '重复提示照片预览')}</View>
        <Text>{item.caption || item.displayFilename || '未命名照片'}</Text>
        <Text variant="bodySmall">{photoSourceLabel(item.source)} · {item.visibility === 'private' ? '仅我自己' : '家庭共享'}</Text>
        <Button contentStyle={{ minHeight: 44 }} disabled={disabled} accessibilityLabel={`打开原照片 ${item.caption || item.displayFilename || item.id}`}
          onPress={() => props.open(item)}>打开原照片</Button>
      </View>)}
      {(data.offset > 0 || data.hasMore) && <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <Button disabled={disabled || data.offset === 0} onPress={() => props.load(data.offset - 20)}>上一页</Button>
        <Text>第 {data.offset / 20 + 1} 页</Text>
        <Button disabled={disabled || !data.hasMore} onPress={() => props.load(data.offset + 20)}>下一页</Button>
      </View>}
    </>}
  </View>;
}
