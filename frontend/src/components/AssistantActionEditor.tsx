import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Button, HelperText, Text, TextInput } from 'react-native-paper';
import type { Action } from '../lib/assistant';
import type { ActionDraft } from '../lib/assistantList';
import type { Person } from '../lib/types';
import { SelectionRow } from '../ui/SelectionRow';
import { shoppingPriorityLabel } from '../lib/trips';

export default function AssistantActionEditor({ kind, draft, people, disabled, error, onChange, onSave, onCancel }: {
  kind: Action['kind']; draft: ActionDraft; people: Person[]; disabled: boolean; error: string;
  onChange: (patch: Partial<ActionDraft>) => void; onSave: () => void; onCancel: () => void;
}) {
  const field = (key: 'title' | 'due' | 'note' | 'quantity' | 'budget', label: string, maxLength: number) => <TextInput
    testID={'action-' + key} accessibilityLabel={label} label={label} mode="outlined" outlineStyle={{ borderRadius: 8 }}
    value={draft[key]} onChangeText={value => onChange({ [key]: value })} disabled={disabled} maxLength={maxLength}
    multiline={key === 'note'} keyboardType={key === 'budget' ? 'decimal-pad' : 'default'} />;
  return <View testID="assistant-action-editor" style={styles.form}>
    <Text variant="titleMedium">调整{kind === 'tasks' ? '待办' : '采购'}</Text>
    {field('title', '名称', 100)}
    <Text variant="titleSmall">负责人</Text>
    <View accessibilityRole="radiogroup" accessibilityLabel="负责人" style={styles.choices}>
      {[{ id: 'shared', name: '一起' }, ...people].map(person => <View key={person.id} testID={'action-owner-' + person.id}>
        <SelectionRow kind="radio" label={person.name} accessibilityLabel={'负责人：' + person.name} checked={draft.owner === person.id}
          disabled={disabled} onPress={() => onChange({ owner: person.id })} />
      </View>)}
    </View>
    {field('due', '截止日期（YYYY-MM-DD，可选）', 10)}{field('note', '备注（可选）', 500)}
    {kind === 'shopping' && <>
      {field('quantity', '数量', 30)}{field('budget', '采购预算（元，可选）', 14)}
      <Text variant="bodySmall">留空是不设预算；0 表示明确零预算。</Text>
      <View accessibilityRole="radiogroup" accessibilityLabel="优先级" style={styles.choices}>
        {(['low', 'normal', 'high'] as const).map(priority => <View key={priority} testID={'action-priority-' + priority}>
          <SelectionRow kind="radio" label={shoppingPriorityLabel(priority)} checked={draft.priority === priority}
            disabled={disabled} onPress={() => onChange({ priority })} />
        </View>)}
      </View>
    </>}
    {!!error && <HelperText type="error" accessibilityRole="alert">{error}</HelperText>}
    <View style={styles.choices}>
      <Button testID="action-edit-save" mode="contained" disabled={disabled} onPress={onSave}>保留调整</Button>
      <Button testID="action-edit-cancel" disabled={disabled} onPress={onCancel}>取消调整</Button>
    </View>
    <Text variant="bodySmall">目前只改本页草稿，最后确认才会保存到家庭清单。</Text>
  </View>;
}
const styles = StyleSheet.create({ form: { gap: 12, paddingVertical: 12 }, choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 } });
