import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Button, Text, TextInput, useTheme } from 'react-native-paper';
import { newSegment, updateStayTiming, updateTimePoint, type Segment, type TimePoint } from '../lib/journeySegments';
import { SelectionRow } from '../ui/SelectionRow';
import { useDisplayDensity } from '../ui/theme';

export const segmentKindNames = { flight: '航班', stay: '住宿', activity: '活动', legacy_day: '原日期段' };
export const bookingNames = { idea: '计划中', booked: '已预订', cancelled: '人工标记取消' };
export function SegmentInput({ label, value, onChange, disabled, multiline = false, placeholder }: {
  label: string; value: string; onChange: (value: string) => void; disabled?: boolean; multiline?: boolean; placeholder?: string;
}) {
  const theme = useTheme();
  return <TextInput mode="outlined" label={label} accessibilityLabel={label} value={value} onChangeText={onChange}
    disabled={disabled} multiline={multiline} placeholder={placeholder} outlineStyle={{ borderRadius: 8 }}
    style={{ minWidth: 0, backgroundColor: theme.colors.surface }} />;
}
function TimeFields({ label, value, onChange, disabled }: {
  label: string; value: TimePoint; onChange: (point: TimePoint) => void; disabled: boolean;
}) {
  return <View style={styles.fields}>
    <Text variant="titleSmall">{label}</Text>
    <SegmentInput label={`${label}当地时间`} value={value.local} onChange={local => onChange(updateTimePoint(value, { local }))} disabled={disabled} placeholder="YYYY-MM-DDTHH:mm" />
    <SegmentInput label={`${label}时区`} value={value.timeZone} onChange={timeZone => onChange(updateTimePoint(value, { timeZone }))} disabled={disabled} placeholder="例如 Asia/Shanghai" />
    <Text>填写此地的钟表时间与 IANA 时区。夏令时歧义会在预览时要求你选择，不自动猜测。</Text>
  </View>;
}
export function SegmentFields({ segment: row, disabled, onChange }: { segment: Segment; disabled: boolean; onChange: (value: Segment) => void }) {
  const density = useDisplayDensity();
  const input = (label: string, value: string, onChangeValue: (value: string) => void, placeholder?: string, multiline = false) =>
    <SegmentInput {...{ label, value, disabled, placeholder, multiline }} onChange={onChangeValue} />;
  const transform = (kind: 'flight' | 'stay' | 'activity', allDay = false) => {
    let next = newSegment(kind, row.key);
    if (next.kind === 'activity' && !allDay) {
      const { dateRange: _range, timeZone: _zone, ...rest } = next;
      next = { ...rest, start: { local: '', timeZone: '' }, end: { local: '', timeZone: '' } };
    }
    onChange({ ...next, title: row.title, location: row.location, note: row.note, bookingState: row.bookingState,
      datePolicy: kind === 'flight' ? 'fixed' : row.datePolicy, ...(row.destinationKey ? { destinationKey: row.destinationKey } : {}) });
  };
  return <View style={{ gap: density.pageGap }} testID="journey-segment-fields">
    {input('分段标题', row.title, title => onChange({ ...row, title }))}
    {row.kind === 'flight' && <>
      {input('航班号（可留空）', row.flightNumber, flightNumber => onChange({ ...row, flightNumber }))}
      <TimeFields label="起飞" value={row.departure} disabled={disabled} onChange={point => onChange({ ...row, departure: { ...point, airport: row.departure.airport, city: row.departure.city } })} />
      {input('起飞机场（可留空）', row.departure.airport, airport => onChange({ ...row, departure: { ...row.departure, airport } }))}
      {input('起飞城市（可留空）', row.departure.city, city => onChange({ ...row, departure: { ...row.departure, city } }))}
      <TimeFields label="抵达" value={row.arrival} disabled={disabled} onChange={point => onChange({ ...row, arrival: { ...point, airport: row.arrival.airport, city: row.arrival.city } })} />
      {input('抵达机场（可留空）', row.arrival.airport, airport => onChange({ ...row, arrival: { ...row.arrival, airport } }))}
      {input('抵达城市（可留空）', row.arrival.city, city => onChange({ ...row, arrival: { ...row.arrival, city } }))}
    </>}
    {row.kind === 'stay' && <>
      {input('住宿名称（可留空）', row.propertyName, propertyName => onChange({ ...row, propertyName }))}
      {input('住宿地址（可留空）', row.address, address => onChange({ ...row, address }), undefined, true)}
      {input('住宿时区', row.timeZone, timeZone => onChange(updateStayTiming(row, { timeZone })), '例如 Asia/Shanghai')}
      {input('入住日期', row.checkInDate, checkInDate => onChange(updateStayTiming(row, { checkInDate })), 'YYYY-MM-DD')}
      {input('退房日期（不含当天）', row.checkOutDate, checkOutDate => onChange(updateStayTiming(row, { checkOutDate })), 'YYYY-MM-DD')}
      {input('入住时间（未知留空）', row.checkInTime, checkInTime => onChange(updateStayTiming(row, { checkInTime })), 'HH:mm')}
      {input('退房时间（未知留空）', row.checkOutTime, checkOutTime => onChange(updateStayTiming(row, { checkOutTime })), 'HH:mm')}
      <Text>住宿按当地日期计晚数，退房日不计入。未知时刻留空，预览不会替你补成午夜。</Text>
    </>}
    {row.kind === 'activity' && <>
      <View accessibilityRole="radiogroup" accessibilityLabel="活动时间方式">
        <SelectionRow kind="radio" label="明确起止时刻" checked={!row.dateRange} disabled={disabled} onPress={() => { if (row.dateRange) transform('activity'); }} />
        <SelectionRow kind="radio" label="仅知道日期" checked={!!row.dateRange} disabled={disabled} onPress={() => { if (!row.dateRange) transform('activity', true); }} />
      </View>
      <Text>切换时间方式会清空本段的旧时间，请按实际资料重新填写。</Text>
      {row.dateRange ? <>
        {input('活动开始日期', row.dateRange.startDate, startDate => onChange({ ...row, dateRange: { ...row.dateRange, startDate } }), 'YYYY-MM-DD')}
        {input('活动结束日期（不含当天）', row.dateRange.endDateExclusive, endDateExclusive => onChange({ ...row, dateRange: { ...row.dateRange, endDateExclusive } }), 'YYYY-MM-DD')}
        {input('活动时区', row.timeZone, timeZone => onChange({ ...row, timeZone }), '例如 Asia/Shanghai')}
      </> : <><TimeFields label="活动开始" value={row.start} disabled={disabled} onChange={start => onChange({ ...row, start })} />
        <TimeFields label="活动结束" value={row.end} disabled={disabled} onChange={end => onChange({ ...row, end })} /></>}
    </>}
    {row.kind === 'legacy_day' && <>
      {input('原日期段开始日期', row.start, start => onChange({ ...row, start }), 'YYYY-MM-DD')}
      {input('原日期段结束日期（包含当天）', row.end, end => onChange({ ...row, end }), 'YYYY-MM-DD')}
      <Text>这是沿用的日期分段，不推定为住宿或航班。转换类型会保留标题、备注与关联，再由你填写时刻。</Text>
      <View style={styles.actions}>{(['flight', 'stay', 'activity'] as const).map(kind => <Button key={kind} mode="outlined" contentStyle={styles.touch} disabled={disabled}
        accessibilityLabel={`将原日期段转换为${segmentKindNames[kind]}`} onPress={() => transform(kind)}>改为{segmentKindNames[kind]}</Button>)}</View>
    </>}
    {input('日历地点（可留空）', row.location, location => onChange({ ...row, location }), undefined, true)}
    {input('分段备注（可留空）', row.note, note => onChange({ ...row, note }), undefined, true)}
    <Text variant="titleSmall">预订标记</Text>
    <View accessibilityRole="radiogroup" accessibilityLabel="分段预订标记">{(['idea', 'booked', 'cancelled'] as const).map(bookingState =>
      <SelectionRow key={bookingState} kind="radio" label={bookingNames[bookingState]} checked={row.bookingState === bookingState} disabled={disabled}
        onPress={() => onChange({ ...row, bookingState })} />)}</View>
    <Text>标记来自你的确认。取消仅记录计划变化，不会向航司、酒店或云日历发起取消。</Text>
    <View accessibilityRole="radiogroup" accessibilityLabel="分段日期规则">
      <SelectionRow kind="radio" label="保持固定日期" checked={row.datePolicy === 'fixed'} disabled={disabled} onPress={() => onChange({ ...row, datePolicy: 'fixed' })} />
      <SelectionRow kind="radio" label="允许在调整旅行日期时选择联动" checked={row.datePolicy === 'shift_with_trip'} disabled={disabled} onPress={() => onChange({ ...row, datePolicy: 'shift_with_trip' })} />
    </View><Text>此处不平移日期；已预订、已取消和已完成历史不会因此自动变动。</Text>
  </View>;
}
export function clockText(point: TimePoint) {
  const offset = point.offsetMinutes === undefined ? '' : ` · UTC${point.offsetMinutes < 0 ? '−' : '+'}${String(Math.floor(Math.abs(point.offsetMinutes) / 60)).padStart(2, '0')}:${String(Math.abs(point.offsetMinutes) % 60).padStart(2, '0')}`;
  return `${point.local || '未填时间'} · ${point.timeZone || '未填时区'}${offset}${point.instant ? ` · ${point.instant}` : ''}`;
}
export function segmentText(row: Segment) {
  if (row.kind === 'flight') return `起飞 ${clockText(row.departure)}\n${[row.departure.airport, row.departure.city].filter(Boolean).join(' · ')}\n抵达 ${clockText(row.arrival)}\n${[row.arrival.airport, row.arrival.city].filter(Boolean).join(' · ')}${row.flightNumber ? '\n航班 ' + row.flightNumber : ''}`;
  if (row.kind === 'stay') return `${row.propertyName}${row.address ? '\n' + row.address : ''}\n${row.checkInDate} ${row.checkInTime || '时间未知'} 入住 → ${row.checkOutDate} ${row.checkOutTime || '时间未知'} 退房（不含退房日）\n${row.timeZone}${row.nights !== undefined ? ' · ' + row.nights + ' 晚' : ''}${row.checkInOffsetMinutes !== undefined ? '\n入住 UTC 偏移 ' + row.checkInOffsetMinutes + ' 分钟' : ''}${row.checkOutOffsetMinutes !== undefined ? '\n退房 UTC 偏移 ' + row.checkOutOffsetMinutes + ' 分钟' : ''}${row.checkInInstant ? '\n入住 UTC ' + row.checkInInstant : ''}${row.checkOutInstant ? '\n退房 UTC ' + row.checkOutInstant : ''}`;
  if (row.kind === 'activity') return row.dateRange ? `${row.dateRange.startDate} → ${row.dateRange.endDateExclusive}（不含结束日） · ${row.timeZone}` : `${clockText(row.start)}\n→ ${clockText(row.end)}`;
  return `${row.start} → ${row.end}（包含结束日）`;
}
const styles = StyleSheet.create({ fields: { gap: 10 }, actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, touch: { minHeight: 44 } });
