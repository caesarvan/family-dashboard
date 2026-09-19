import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Button, Divider, HelperText, Text, TextInput } from 'react-native-paper';
import { briefOwnerOptions, briefPreparationDate, briefPurchaseDate, type BriefForm, type BriefItem, type BriefPreparation, type BriefPurchase } from '../lib/journeyBrief';
import type { Person } from '../lib/types';
import { SectionCard } from '../ui/components';
import { SelectionRow } from '../ui/SelectionRow';

type Props = { form: BriefForm; people: Person[]; actorId: string; disabled: boolean; extractEpoch: number;
  onChange: (patch: Partial<BriefForm>) => void; onAddPreparation: () => void; onAddPurchase: () => void };
export default function JourneyBriefItems({ form, people, actorId, disabled, extractEpoch, onChange, onAddPreparation, onAddPurchase }: Props) {
  const [tasksOpen, setTasksOpen] = useState(form.checklist.length > 0), [purchasesOpen, setPurchasesOpen] = useState(form.shopping.length > 0);
  const [ownerOpen, setOwnerOpen] = useState('');
  useEffect(() => { setTasksOpen(form.checklist.length > 0); setPurchasesOpen(form.shopping.length > 0); setOwnerOpen(''); }, [extractEpoch]);
  const options = briefOwnerOptions(people, actorId);
  const task = (index: number, patch: Partial<BriefPreparation>) => onChange({ checklist: form.checklist.map((row, i) => i === index ? { ...row, ...patch } : row) });
  const purchase = (index: number, patch: Partial<BriefPurchase>) => onChange({ shopping: form.shopping.map((row, i) => i === index ? { ...row, ...patch } : row) });
  const field = (label: string, value: string, change: (value: string) => void, max = 100, placeholder?: string) => <TextInput
    mode="outlined" dense outlineStyle={{ borderRadius: 8 }} label={label} accessibilityLabel={label} value={value} onChangeText={change}
    disabled={disabled} maxLength={max * 2} placeholder={placeholder} style={styles.input} />;
  function owner(row: BriefItem, label: string, change: (owner: string) => void) {
    const selected = options.find(option => option.id === row.owner && !option.disabled);
    return <View style={styles.fields}>
      <Button mode="outlined" disabled={disabled} accessibilityLabel={label} onPress={() => setOwnerOpen(ownerOpen === row.key ? '' : row.key)}>{selected ? '负责人：' + selected.label : '选择负责人'}</Button>
      {!selected && <HelperText type="error">负责人待核对{row.assigneeText ? '：' + row.assigneeText : '，请明确选择'}</HelperText>}
      {ownerOpen === row.key && <View accessibilityRole="radiogroup" accessibilityLabel={label + '选项'} style={styles.fields}>
        {options.map(option => <SelectionRow key={option.id} kind="radio" label={option.label} accessibilityLabel={option.label}
          checked={row.owner === option.id} disabled={disabled || option.disabled} onPress={() => { if (disabled || option.disabled) return; change(option.id); setOwnerOpen(''); }} />)}
        {options.some(option => option.disabled) && <Text>同名成员暂无法区分，请先明确选择一起或本人；也可删除此行后稍后分工。</Text>}
      </View>}
    </View>;
  }
  function dateNote(row: BriefPreparation) {
    try { return '截止：' + briefPreparationDate(row, form.start) + (row.dueMode === 'offset' ? '，随出发日期调整' : ''); }
    catch { return '截止日期待核对'; }
  }
  function purchaseDateNote(row: BriefPurchase) {
    try {
      const due = briefPurchaseDate(row, form.start);
      return due ? '截止：' + due + (due > form.end ? '（返程后，请核对）' : '') : '未设截止日期';
    } catch { return '采购截止日期待核对'; }
  }
  return <>
    <SectionCard title={`准备事项 · ${form.checklist.length || (form.useDefaultChecklist ? '默认清单' : '无')}`} action={<Button disabled={disabled}
      accessibilityLabel={tasksOpen ? '收起准备事项' : '展开准备事项'} onPress={() => setTasksOpen(!tasksOpen)}>{tasksOpen ? '收起' : '展开'}</Button>}>
      <View testID="journey-brief-checklist" style={styles.fields}>
        {tasksOpen ? <>
          {!form.checklist.length && <SelectionRow label="使用默认准备清单" checked={form.useDefaultChecklist} disabled={disabled} onPress={() => onChange({ useDefaultChecklist: !form.useDefaultChecklist })} />}
          {form.checklist.map((row, index) => <View key={row.key} testID={`journey-brief-task-${index + 1}`} style={styles.fields}>
            <Text variant="titleSmall">准备 {index + 1}</Text>
            {field(`准备事项标题 ${index + 1}`, row.title, title => task(index, { title }))}
            {owner(row, `准备负责人 ${index + 1}`, value => task(index, { owner: value }))}
            <View accessibilityRole="radiogroup" accessibilityLabel={`准备截止方式 ${index + 1}`} style={styles.row}>
              <SelectionRow kind="radio" label="固定日期" accessibilityLabel={`固定截止日期 ${index + 1}`} checked={row.dueMode === 'date'} disabled={disabled}
                onPress={() => row.dueMode !== 'date' && task(index, { dueMode: 'date', due: '', dueOffsetDays: '' })} />
              <SelectionRow kind="radio" label="随出发日期调整" accessibilityLabel={`随出发日期调整 ${index + 1}`} checked={row.dueMode === 'offset'} disabled={disabled}
                onPress={() => row.dueMode !== 'offset' && task(index, { dueMode: 'offset', due: '', dueOffsetDays: '' })} />
            </View>
            {row.dueMode === 'date' ? field(`准备截止日期 ${index + 1}`, row.due, due => task(index, { due }), 10, 'YYYY-MM-DD')
              : field(`距出发天数 ${index + 1}`, row.dueOffsetDays, dueOffsetDays => task(index, { dueOffsetDays }), 4, '-3 表示出发前三天，0 表示当天')}
            <Text accessibilityLiveRegion="polite">{dateNote(row)}</Text>
            {field(`准备备注 ${index + 1}`, row.note, note => task(index, { note }), 500)}
            <Button disabled={disabled} accessibilityLabel={`移除准备事项 ${index + 1}`} onPress={() => onChange({ checklist: form.checklist.filter((_, i) => i !== index) })}>移除准备事项</Button><Divider />
          </View>)}
          <Button mode="outlined" icon="plus" disabled={disabled || form.checklist.length >= 100} onPress={() => { setTasksOpen(true); onAddPreparation(); }}>添加准备事项</Button>
        </> : <Text>{form.checklist.length ? `${form.checklist.length} 项准备，展开核对负责人和截止日期。` : form.useDefaultChecklist ? '继续后带入国内或境外默认准备清单，也可展开添加自己的事项。' : '本次不添加准备事项。'}</Text>}
      </View>
    </SectionCard>
    <SectionCard title={`采购清单 · ${form.shopping.length}`} action={<Button disabled={disabled} accessibilityLabel={purchasesOpen ? '收起采购清单' : '展开采购清单'} onPress={() => setPurchasesOpen(!purchasesOpen)}>{purchasesOpen ? '收起' : '展开'}</Button>}>
      <View testID="journey-brief-shopping" style={styles.fields}>
        {purchasesOpen ? <>
          <Text>预算可留空表示待确认，0 表示明确零预算。截止日期可不设；相对天数只用于当前草案计算，保存后改期需另行勾选确认。</Text>
          {form.shopping.map((row, index) => <View key={row.key} testID={`journey-brief-purchase-${index + 1}`} style={styles.fields}>
            <Text variant="titleSmall">采购 {index + 1}</Text>
            {field(`采购名称 ${index + 1}`, row.title, title => purchase(index, { title }))}
            {owner(row, `采购负责人 ${index + 1}`, value => purchase(index, { owner: value }))}
            <View style={styles.row}><View style={styles.column}>{field(`采购数量 ${index + 1}`, row.quantity, quantity => purchase(index, { quantity }), 30, '如：两只')}</View>
              <View style={styles.column}>{field(`采购预算（元）${index + 1}`, row.budget, budget => purchase(index, { budget }), 14, '待确认')}</View></View>
            <View accessibilityRole="radiogroup" accessibilityLabel={`采购截止方式 ${index + 1}`} style={styles.row}>
              {([['none', '不设截止'], ['date', '固定日期'], ['offset', '距出发天数']] as const).map(([mode, label]) => <SelectionRow key={mode} kind="radio" label={label}
                accessibilityLabel={`采购${mode === 'offset' ? '使用相对天数' : label} ${index + 1}`} checked={row.dueMode === mode} disabled={disabled}
                onPress={() => row.dueMode !== mode && purchase(index, { dueMode: mode, due: '', dueOffsetDays: '' })} />)}
            </View>
            {row.dueMode === 'date' && field(`采购截止日期 ${index + 1}`, row.due, due => purchase(index, { due }), 10, 'YYYY-MM-DD')}
            {row.dueMode === 'offset' && field(`采购距出发天数 ${index + 1}`, row.dueOffsetDays, dueOffsetDays => purchase(index, { dueOffsetDays }), 4, '-3 表示出发前三天')}
            <Text accessibilityLiveRegion="polite">{purchaseDateNote(row)}</Text>
            <View accessibilityRole="radiogroup" accessibilityLabel={`采购优先级 ${index + 1}`} style={styles.row}>
              {([['normal', '普通'], ['high', '高'], ['low', '低']] as const).map(([priority, label]) => <SelectionRow key={priority} kind="radio" label={label}
                accessibilityLabel={`采购优先级${label} ${index + 1}`} checked={row.priority === priority} disabled={disabled}
                onPress={() => purchase(index, { priority })} />)}
            </View>
            {field(`采购备注 ${index + 1}`, row.note, note => purchase(index, { note }), 500)}
            <Button disabled={disabled} accessibilityLabel={`移除采购 ${index + 1}`} onPress={() => onChange({ shopping: form.shopping.filter((_, i) => i !== index) })}>移除采购</Button><Divider />
          </View>)}
          <Button mode="outlined" icon="plus" disabled={disabled || form.shopping.length >= 100} onPress={() => { setPurchasesOpen(true); onAddPurchase(); }}>添加采购</Button>
        </> : <Text>{form.shopping.length ? `${form.shopping.length} 项采购，展开核对数量、负责人和预算。` : '尚未添加采购，可展开补充。'}</Text>}
      </View>
    </SectionCard>
  </>;
}
const styles = StyleSheet.create({ fields: { gap: 12 }, input: { width: '100%' }, row: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, column: { flexGrow: 1, flexBasis: 220, minWidth: 0 } });
