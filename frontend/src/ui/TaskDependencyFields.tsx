import React, { useState } from 'react';
import { View } from 'react-native';
import { Button, List, Text, TextInput } from 'react-native-paper';
import type { ListItem } from '../lib/types';
import { unavailableDependencyIds, dependencyLimit } from '../lib/taskDependencies';
import { SelectionRow } from './SelectionRow';

export default function TaskDependencyFields({ tasks, currentId, value, disabled, cloud, onChange }: {
  tasks: ListItem[]; currentId?: string; value: string[]; disabled: boolean; cloud: boolean; onChange: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState('');
  const byId = new Map(tasks.map(task => [task.id, task]));
  const unavailable = unavailableDependencyIds(currentId, tasks);
  const available = tasks.filter(task => task.id !== currentId && !task.sync && !value.includes(task.id)
    && !unavailable.has(task.id)
    && task.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const change = (ids: string[]) => { if (!disabled && !cloud) onChange(ids); };
  return <List.Accordion title={value.length ? `前置事项 · ${value.length} 项` : '前置事项（可选）'}>
    <View style={{ gap: 10, paddingVertical: 8 }}>
      <Text variant="bodySmall">先完成选中的事项，才能完成这项待办。</Text>
      {cloud && <Text accessibilityLiveRegion="polite">同步清单暂不支持前置事项。请选择看板本地待办，或先清空已选前置事项。</Text>}
      {value.map(id => <SelectionRow key={id} label={(byId.get(id)?.title || '已失效的前置事项') + (byId.get(id)?.done ? ' · 已完成' : '')}
        accessibilityLabel={'取消前置事项：' + (byId.get(id)?.title || '已失效的前置事项')}
        checked disabled={disabled || cloud} onPress={() => change(value.filter(valueId => valueId !== id))} />)}
      {!!value.length && <Button disabled={disabled} onPress={() => { if (!disabled) onChange([]); }}>清空前置事项</Button>}
      {!cloud && <><TextInput mode="outlined" dense label="搜索前置事项" accessibilityLabel="搜索前置事项" value={query}
        disabled={disabled} onChangeText={setQuery} maxLength={100} />
        {available.slice(0, 20).map(task => <SelectionRow key={task.id} label={task.title + (task.done ? ' · 已完成' : '')}
          accessibilityLabel={'选择前置事项：' + task.title} checked={false} disabled={disabled || value.length >= dependencyLimit}
          onPress={() => { if (value.length < dependencyLimit) change([...value, task.id]); }} />)}
        <Text variant="bodySmall">{value.length >= dependencyLimit ? '最多选择 20 项。' : available.length > 20 ? '还有更多事项，请输入关键词缩小范围。' : !available.length ? '没有更多可选的本地待办。' : '仅列出不会相互等待的本地待办。'}</Text>
      </>}
    </View>
  </List.Accordion>;
}
