"""Pure date-only journey rescheduling. No database, auth or cloud I/O."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json

from journey_time import TimeIssue, date_only, normalize_segment, project, zone


class RescheduleError(ValueError):
    def __init__(self, message, code='invalid_reschedule', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def shifted(value, days):
    if value is None or value == '':
        return value
    try:
        return date_only((date.fromisoformat(value) + timedelta(days=days)).isoformat(), 'date')
    except (ValueError, OverflowError):
        raise RescheduleError('调整后的日期须介于 2000 至 2100 年') from None


def event_day(value, end=False):
    day = value['end' if end else 'start'][:10]
    return shifted(day, -1) if end and value.get('allDay') else day


def live_segment(row, event, version):
    """Use the current entity's times, retaining the plan's non-date metadata."""
    value = deepcopy(row)
    if version == 1 or row.get('kind') == 'legacy_day':
        value.update(start=event_day(event), end=event_day(event, True))
    elif row['kind'] == 'stay':
        value.update(checkInDate=event['start'][:10], checkOutDate=event['end'][:10])
    elif row['kind'] == 'activity' and 'dateRange' in row:
        value['dateRange'] = {'startDate': event['start'][:10], 'endDateExclusive': event['end'][:10]}
    else:
        for side, field in (('start', 'departure' if row['kind'] == 'flight' else 'start'),
                            ('end', 'arrival' if row['kind'] == 'flight' else 'end')):
            point = value[field]
            point['local'] = datetime.fromisoformat(event[side]).astimezone(zone(point['timeZone'], field)).replace(tzinfo=None).isoformat(timespec='seconds')
            point.pop('instant', None)
            point.pop('offsetMinutes', None)
            point['offsetMinutes'] = int(datetime.fromisoformat(event[side]).astimezone(zone(point['timeZone'], field)).utcoffset().total_seconds() // 60)
    return value


def dates(row, version):
    if version == 1 or row.get('kind') == 'legacy_day':
        return {'start': row['start'], 'end': row['end']}, False
    if row['kind'] == 'stay':
        return {'start': row['checkInDate'], 'end': row['checkOutDate']}, True
    if row['kind'] == 'activity' and 'dateRange' in row:
        return {'start': row['dateRange']['startDate'], 'end': row['dateRange']['endDateExclusive']}, True
    begin, finish = ('departure', 'arrival') if row['kind'] == 'flight' else ('start', 'end')
    return {'start': row[begin]['local'][:10], 'end': row[finish]['local'][:10]}, False


def clocks(row):
    """Exact local clocks accompany date labels for an informed DST correction."""
    kind = row.get('kind')
    if kind == 'flight' or kind == 'activity' and 'dateRange' not in row:
        return {side: {name: row[field][name] for name in ('local', 'timeZone', 'offsetMinutes') if name in row[field]}
                for side, field in (('start', 'departure' if kind == 'flight' else 'start'),
                                    ('end', 'arrival' if kind == 'flight' else 'end'))}
    if kind == 'stay':
        return {side: {'local': row[prefix + 'Date'] + 'T' + row[prefix + 'Time'], 'timeZone': row['timeZone'],
                       **({'offsetMinutes': row[prefix + 'OffsetMinutes']} if prefix + 'OffsetMinutes' in row else {})}
                for side, prefix in (('start', 'checkIn'), ('end', 'checkOut')) if row.get(prefix + 'Time')}
    return {}


def items_for(plan, records, places):
    result = []
    def add(key, kind, title, begin=None, end=None, reason=None, exclusive=False):
        result.append({'key': key, 'kind': kind, 'title': title, 'before': {'start': begin, 'end': end},
                       'eligible': reason is None, 'reason': reason, 'endExclusive': exclusive})
    trip = json.loads(records['trip']['data'])
    add('trip', 'overview', trip['title'], trip['start'], trip['end'], 'always_updated')
    for row in plan['destinations']:
        add('destination:' + row['key'], 'destination', row['city'], row['arrival'], row['departure'])
    for row in plan['segments']:
        key = 'segment:' + row['key']
        event = json.loads(records[key]['data']) if key in records else None
        reason = 'missing_event' if event is None else None
        if row.get('bookingState') in ('booked', 'cancelled'):
            reason = row['bookingState']
        elif row.get('datePolicy') == 'fixed':
            reason = 'fixed'
        if event and (event.get('sync') or event.get('imported')):
            reason = 'cloud_managed'
        if event and plan.get('schemaVersion', 1) == 2:
            projected = project(row)
            fields = ('schemaVersion', 'kind', 'startTimeZone', 'endTimeZone', 'timeZone')
            actual_timing = event.get('travelTiming') or {}
            if (bool(event.get('allDay')) != bool(projected['allDay']) or
                    any(actual_timing.get(field) != projected['travelTiming'].get(field) for field in fields)):
                reason = 'timing_changed'
        value = live_segment(row, event, plan.get('schemaVersion', 1)) if event else row
        bounds, exclusive = dates(value, plan.get('schemaVersion', 1))
        add(key, 'segment', (event or row)['title'], bounds['start'], bounds['end'], reason, exclusive)
        if plan.get('schemaVersion', 1) == 2:
            result[-1]['timeBefore'] = clocks(value)
    for key, entry in records.items():
        value = json.loads(entry['data'])
        if entry['kind'] == 'tasks':
            reason = 'completed' if value.get('done') else 'cloud_managed' if value.get('sync') else 'no_date' if not value.get('due') else None
            add(key, 'task', value['title'], value.get('due') or None, value.get('due') or None, reason)
        elif entry['kind'] == 'shopping':
            add(key, 'shopping', value['title'], reason='no_date')
    for row in places:
        reason = 'not_planned' if row['status'] != 'planned' else 'no_date' if not row['start_date'] else None
        add('place:' + row['id'], 'place', row['name'], row['start_date'], row['end_date'], reason)
    return result


def move_segment(row, days, overrides, index, text, item_key):
    value = deepcopy(row)
    kind = value.get('kind', 'legacy_day')
    if kind == 'legacy_day':
        if overrides:
            raise RescheduleError('日期段不接受时刻覆盖')
        value['start'], value['end'] = shifted(value['start'], days), shifted(value['end'], days)
    elif kind == 'stay':
        value['checkInDate'], value['checkOutDate'] = shifted(value['checkInDate'], days), shifted(value['checkOutDate'], days)
        for side, prefix in (('start', 'checkIn'), ('end', 'checkOut')):
            value.pop(prefix + 'OffsetMinutes', None)
            value.pop(prefix + 'Instant', None)
            if side in overrides:
                correction = overrides[side]
                value[prefix + 'Date'], clock = correction['local'].split('T', 1)
                if len(clock) != 5:
                    raise RescheduleError('住宿时间覆盖须精确到分钟')
                value[prefix + 'Time'] = clock
                if 'offsetMinutes' in correction:
                    value[prefix + 'OffsetMinutes'] = correction['offsetMinutes']
    elif kind == 'activity' and 'dateRange' in value:
        if overrides:
            raise RescheduleError('全天活动不接受时刻覆盖')
        value['dateRange'] = {key: shifted(day, days) for key, day in value['dateRange'].items()}
    else:
        for side, field in (('start', 'departure' if kind == 'flight' else 'start'),
                            ('end', 'arrival' if kind == 'flight' else 'end')):
            point = value[field]
            point['local'] = shifted(point['local'][:10], days) + point['local'][10:]
            point.pop('instant', None)
            point.pop('offsetMinutes', None)
            point.update(overrides.get(side, {}))
    try:
        return normalize_segment(value, index, text, item_key), None
    except TimeIssue as exc:
        side = 'end' if any(part in exc.field for part in ('.end', '.arrival', '.checkOut')) else 'start'
        if kind == 'stay':
            prefix = 'checkIn' if side == 'start' else 'checkOut'
            local = value[prefix + 'Date'] + 'T' + value.get(prefix + 'Time', '')
            timezone = value['timeZone']
        elif kind in ('flight', 'activity') and 'dateRange' not in value:
            field = ('departure' if side == 'start' else 'arrival') if kind == 'flight' else side
            local, timezone = value[field]['local'], value[field]['timeZone']
        else:
            local, timezone = None, None
        return None, {'code': exc.code, 'key': 'segment:' + row['key'], 'message': str(exc),
                      'field': side, 'local': local, 'timeZone': timezone, 'choices': exc.choices}


def prepare(plan, records, places, start, end, selected, overrides, text, item_key):
    """Return a signed-candidate payload; only callers may persist its patches."""
    start, end = date_only(start, 'start'), date_only(end, 'end')
    if not 0 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 366:
        raise RescheduleError('返程不得早于出发，单次行程最多 367 天')
    items = items_for(plan, records, places)
    index = {row['key']: row for row in items}
    if (not isinstance(selected, list) or len(selected) > len(items) or any(not isinstance(key, str) for key in selected)
            or len(selected) != len(set(selected)) or any(key not in index or not index[key]['eligible'] for key in selected)):
        raise RescheduleError('只能明确选择本次快照中允许调整的项目')
    if not isinstance(overrides, dict) or len(overrides) > 100 or any(key not in selected or not key.startswith('segment:') for key in overrides):
        raise RescheduleError('时间覆盖只能用于已选分段')
    for values in overrides.values():
        if not isinstance(values, dict) or not values or set(values) - {'start', 'end'}:
            raise RescheduleError('时间覆盖只接受 start 和 end')
        for point in values.values():
            if (not isinstance(point, dict) or set(point) - {'local', 'offsetMinutes'} or not isinstance(point.get('local'), str)
                    or len(point['local']) > 19 or 'T' not in point['local'] or
                    'offsetMinutes' in point and type(point['offsetMinutes']) is not int):
                raise RescheduleError('请提交当地时间及可选的整数 UTC 偏移')
    days = (date.fromisoformat(start) - date.fromisoformat(items[0]['before']['start'])).days
    updated = deepcopy(plan)
    updated.update(start=start, end=end)
    actual_trip = json.loads(records['trip']['data'])
    # Keep the editable plan aligned with independent edits already made to its
    # linked records, without writing those records or inventing missing values.
    for field in ('title', 'budget', 'saved', 'paid', 'note'):
        if field in actual_trip:
            updated[field] = actual_trip[field]
    for collection, prefix, fields in (
            ('checklist', 'task:', ('title', 'owner', 'due', 'note')),
            ('shopping', 'shopping:', ('title', 'owner', 'quantity', 'budget', 'note'))):
        for row in updated[collection]:
            entry = records.get(prefix + row['key'])
            if entry:
                actual = json.loads(entry['data'])
                row.update({field: actual[field] for field in fields if field in actual})
                if collection == 'checklist' and row.get('due'):
                    row['dueOffsetDays'] = (date.fromisoformat(row['due']) - date.fromisoformat(start)).days
    patches, place_patches, issues = {}, {}, []
    warnings = [
        {'code': 'financial_data_preserved', 'key': None, 'message': '预算、预留、已付和采购金额保持不变；请自行核对改签及取消费用。'},
        {'code': 'shopping_no_due', 'key': None, 'message': '采购没有截止日期字段，采购记录保持不变。'},
        {'code': 'bookings_not_changed', 'key': None, 'message': '不会改签或取消真实预订，也不会修改旅行资料或共享权限。'},
        {'code': 'calendar_async', 'key': None, 'message': '既有日历关联保留，日期更新由原同步队列处理；本地保存不代表云端已成功。'}]
    patches['trip'] = {**json.loads(records['trip']['data']), 'start': start, 'end': end}
    overview = records.get('event:overview')
    if overview:
        value = json.loads(overview['data'])
        if value.get('sync') or value.get('imported'):
            issues.append({'code': 'cloud_managed', 'key': 'trip', 'message': '旅行概览已由其他来源管理，不能直接改期。'})
        else:
            value['start'] = start + value['start'][10:]
            value['end'] = shifted(end, 1 if value.get('allDay') else 0) + value['end'][10:]
            if 'startDate' in value:
                value['startDate'] = start
            if 'endDateExclusive' in value:
                value['endDateExclusive'] = shifted(end, 1)
            if value['end'] <= value['start']:
                issues.append({'code': 'nonpositive_duration', 'key': 'trip', 'message': '旅行概览结束时刻须晚于开始时刻。'})
            patches['event:overview'] = value
    else:
        issues.append({'code': 'missing_event', 'key': 'trip', 'message': '旅行概览日程已删除，请先修复关联。'})
    for item in items:
        item.update(selected=item['key'] == 'trip' or item['key'] in selected, after=dict(item['before']))
        if 'timeBefore' in item:
            item['timeAfter'] = deepcopy(item['timeBefore'])
        if item['key'] == 'trip':
            item['after'] = {'start': start, 'end': end}
        elif item['key'] in selected:
            item['after'] = {name: shifted(day, days) for name, day in item['before'].items()}
    for row in updated['destinations']:
        key = 'destination:' + row['key']
        if key in selected:
            row['arrival'], row['departure'] = index[key]['after']['start'], index[key]['after']['end']
    for i, row in enumerate(updated['segments']):
        key = 'segment:' + row['key']
        if key not in selected:
            continue
        current = json.loads(records[key]['data'])
        live = live_segment(row, current, plan.get('schemaVersion', 1))
        if plan.get('schemaVersion', 1) == 1:
            live['start'], live['end'] = index[key]['after']['start'], index[key]['after']['end']
            if overrides.get(key):
                raise RescheduleError('v1 日期段不接受时刻覆盖')
            value = dict(current)
            for field in ('start', 'end'):
                value[field] = shifted(current[field][:10], days) + current[field][10:]
        else:
            live, issue = move_segment(live, days, overrides.get(key, {}), i, text, item_key)
            if issue:
                issues.append(issue)
                continue
            value = {**current, **{field: val for field, val in project(live).items() if field != 'note'}}
            # Only refresh our own generated explanation, never an independently edited note.
            if current.get('note') == project(row).get('note'):
                value['note'] = project(live)['note']
            index[key]['after'], _ = dates(live, 2)
            index[key]['timeAfter'] = clocks(live)
        updated['segments'][i] = live
        patches[key] = value
    task_rows = {row['key']: row for row in updated['checklist']}
    for key in selected:
        if index[key]['kind'] == 'task':
            current = json.loads(records[key]['data'])
            patches[key] = {**current, 'due': index[key]['after']['start']}
            row = task_rows.get(key.removeprefix('task:'))
            if row is not None:
                row.update(due=patches[key]['due'], dueOffsetDays=(date.fromisoformat(patches[key]['due']) - date.fromisoformat(start)).days)
        elif index[key]['kind'] == 'place':
            place_patches[key.removeprefix('place:')] = index[key]['after']
    for item in items:
        bounds = item['after']
        finish = shifted(bounds['end'], -1) if bounds['end'] and item['endExclusive'] else bounds['end']
        if ((item['kind'] in ('destination', 'segment', 'place') and bounds['start'] and bounds['start'] < start)
                or finish and finish > end):
            warnings.append({'code': 'outside_trip_dates', 'key': item['key'], 'message': '此项保留或调整后的日期超出旅行概览，请核对。'})
        if item['reason'] in ('booked', 'cancelled', 'fixed', 'completed', 'not_planned', 'timing_changed'):
            warnings.append({'code': item['reason'], 'key': item['key'], 'message': '此项受保护，日期保持不变。'})
    changed_keys = {item['key'] for item in items if item['selected'] and
                    (item['before'] != item['after'] or item.get('timeBefore') != item.get('timeAfter'))}
    for key, payload in patches.items():
        if payload != json.loads(records[key]['data']):
            changed_keys.add('trip' if key == 'event:overview' else key)
    for collection, prefix in (('destinations', 'destination:'), ('segments', 'segment:')):
        previous = {row['key']: row for row in plan[collection]}
        for row in updated[collection]:
            if prefix + row['key'] in selected and row != previous[row['key']]:
                changed_keys.add(prefix + row['key'])
    if (start, end) != (plan['start'], plan['end']):
        changed_keys.add('trip')
    return {'plan': updated, 'entityPatches': patches, 'placePatches': place_patches,
            'items': items, 'warnings': warnings, 'blockingIssues': issues,
            'changedKeys': [item['key'] for item in items if item['key'] in changed_keys]}
