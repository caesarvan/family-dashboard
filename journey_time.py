"""Travel wall-clock validation and deterministic event projections (no I/O)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TimeIssue(ValueError):
    def __init__(self, message, field, code='invalid_travel_time', choices=None):
        super().__init__(message)
        self.field, self.code, self.choices = field, code, choices or []


def zone(value, field):
    if not isinstance(value, str) or len(value) > 100 or not value or value.startswith(('/', '.')):
        raise TimeIssue('请选择有效的 IANA 时区', field, 'invalid_timezone')
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise TimeIssue('请选择有效的 IANA 时区', field, 'invalid_timezone')


def date_only(value, field):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        parsed = date.fromisoformat(value)
        if not 2000 <= parsed.year <= 2100:
            raise ValueError()
        return parsed.isoformat()
    except ValueError:
        raise TimeIssue('日期须为 2000 至 2100 年的 YYYY-MM-DD', field)


def point(raw, field):
    if not isinstance(raw, dict):
        raise TimeIssue('请填写当地时间和 IANA 时区', field)
    local = raw.get('local')
    if not isinstance(local, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?', local):
        raise TimeIssue('当地时间须为不带偏移的 YYYY-MM-DDTHH:mm[:ss]', field + '.local')
    try:
        wall = datetime.fromisoformat(local)
        date_only(wall.date().isoformat(), field + '.local')
    except ValueError:
        raise TimeIssue('当地时间无效', field + '.local')
    tz = zone(raw.get('timeZone'), field + '.timeZone')
    candidates = {}
    for fold in (0, 1):
        aware = wall.replace(tzinfo=tz, fold=fold)
        instant = aware.astimezone(timezone.utc)
        if instant.astimezone(tz).replace(tzinfo=None) == wall:
            offset = int(aware.utcoffset().total_seconds() // 60)
            candidates[offset] = {'offsetMinutes': offset, 'instant': instant.isoformat(timespec='seconds').replace('+00:00', 'Z')}
    choices = list(candidates.values())
    if not choices:
        raise TimeIssue('夏令时切换使这个当地时间不存在，请选择其他时间', field, 'nonexistent_local_time')
    offset = raw.get('offsetMinutes')
    if offset is not None and (type(offset) is not int or offset not in candidates):
        raise TimeIssue('偏移与当地时间的 IANA 时区规则不一致，请重新选择', field, 'offset_mismatch', choices)
    if len(choices) > 1 and offset is None:
        raise TimeIssue('这个当地时间出现两次，请明确选择 UTC 偏移', field, 'ambiguous_local_time', choices)
    chosen = candidates[offset] if offset is not None else choices[0]
    if raw.get('instant') is not None and raw['instant'] != chosen['instant']:
        raise TimeIssue('UTC 时刻与当地时间不一致，请重新预览', field, 'instant_mismatch', choices)
    return {'local': wall.isoformat(timespec='seconds'), 'timeZone': tz.key, **chosen}


def normalize_segment(raw, index, text, item_key):
    path = f'segments[{index}]'
    kind = raw.get('kind', 'legacy_day')
    if kind not in ('flight', 'stay', 'activity', 'legacy_day'):
        raise TimeIssue('不支持的行程类型', path + '.kind')
    booking = raw.get('bookingState', 'idea')
    if booking not in ('idea', 'booked', 'cancelled'):
        raise TimeIssue('预订状态应为 idea、booked 或 cancelled', path + '.bookingState')
    policy = raw.get('datePolicy', 'fixed' if kind == 'flight' or booking == 'booked' else 'shift_with_trip')
    if policy not in ('fixed', 'shift_with_trip'):
        raise TimeIssue('日期策略应为 fixed 或 shift_with_trip', path + '.datePolicy')
    row = {'key': item_key(raw.get('key'), f'segment-{index + 1}'), 'kind': kind,
           'title': text(raw.get('title'), '行程标题'), 'location': text(raw.get('location', ''), '行程地点', 200, True),
           'note': text(raw.get('note', ''), '行程备注', 500, True), 'bookingState': booking, 'datePolicy': policy}
    if raw.get('destinationKey'):
        row['destinationKey'] = item_key(raw['destinationKey'], '')
    if kind == 'flight':
        for endpoint in ('departure', 'arrival'):
            value = raw.get(endpoint)
            row[endpoint] = point(value, path + '.' + endpoint)
            row[endpoint].update(airport=text(value.get('airport', ''), '机场', 80, True), city=text(value.get('city', ''), '城市', 80, True))
        row['flightNumber'] = text(raw.get('flightNumber', ''), '航班号', 40, True)
        if row['arrival']['instant'] <= row['departure']['instant']:
            raise TimeIssue('抵达真实时刻须晚于起飞时刻；请分别核对两端时区', path, 'nonpositive_duration')
    elif kind == 'stay':
        row.update(propertyName=text(raw.get('propertyName', ''), '住宿名称', 150, True),
                   address=text(raw.get('address', ''), '住宿地址', 300, True), timeZone=zone(raw.get('timeZone'), path + '.timeZone').key,
                   checkInDate=date_only(raw.get('checkInDate'), path + '.checkInDate'),
                   checkOutDate=date_only(raw.get('checkOutDate'), path + '.checkOutDate'))
        if row['checkOutDate'] <= row['checkInDate']:
            raise TimeIssue('退房日期须晚于入住日期，退房日不计住宿晚数', path, 'nonpositive_stay')
        row['nights'] = (date.fromisoformat(row['checkOutDate']) - date.fromisoformat(row['checkInDate'])).days
        for prefix in ('checkIn', 'checkOut'):
            clock = raw.get(prefix + 'Time', '')
            if clock is None:
                clock = ''
            if not isinstance(clock, str) or (clock and not re.fullmatch(r'\d{2}:\d{2}', clock)):
                raise TimeIssue('已知入住或退房时间须为 HH:mm；未知请留空', path + '.' + prefix + 'Time')
            row[prefix + 'Time'] = clock
            if clock:
                timepoint = {'local': row[prefix + 'Date'] + 'T' + clock, 'timeZone': row['timeZone']}
                if raw.get(prefix + 'OffsetMinutes') is not None:
                    timepoint['offsetMinutes'] = raw[prefix + 'OffsetMinutes']
                parsed = point(timepoint, path + '.' + prefix + 'Time')
                row[prefix + 'OffsetMinutes'] = parsed['offsetMinutes']
                row[prefix + 'Instant'] = parsed['instant']
    elif kind == 'activity':
        if 'dateRange' in raw:
            if raw.get('start') is not None or raw.get('end') is not None or not isinstance(raw['dateRange'], dict):
                raise TimeIssue('活动须选择明确时段或全天日期，不能同时填写', path)
            dr = raw['dateRange']
            row['dateRange'] = {'startDate': date_only(dr.get('startDate'), path + '.dateRange.startDate'),
                                'endDateExclusive': date_only(dr.get('endDateExclusive'), path + '.dateRange.endDateExclusive')}
            if row['dateRange']['endDateExclusive'] <= row['dateRange']['startDate']:
                raise TimeIssue('全天活动排除结束日期须晚于开始日期', path)
            row['timeZone'] = zone(raw.get('timeZone'), path + '.timeZone').key
        else:
            row['start'], row['end'] = point(raw.get('start'), path + '.start'), point(raw.get('end'), path + '.end')
            if row['end']['instant'] <= row['start']['instant']:
                raise TimeIssue('活动结束真实时刻须晚于开始', path, 'nonpositive_duration')
    else:
        row['start'] = date_only(raw.get('start'), path + '.start')
        row['end'] = date_only(raw.get('end', row['start']), path + '.end')
        if row['end'] < row['start']:
            raise TimeIssue('原日期段结束不得早于开始', path)
    return row


def project(row):
    """The +08 all-day timestamps are compatibility dates, never hotel clocks."""
    kind = row['kind']
    timing = {'schemaVersion': 2, 'kind': kind, 'segmentKey': row['key'],
              'bookingState': row['bookingState'], 'datePolicy': row['datePolicy']}
    note = '\n'.join(filter(None, [row['note'], '人工标记已取消；此记录保留用于行程历史，未向预订平台执行取消。' if row['bookingState'] == 'cancelled' else '']))
    if kind == 'flight' or kind == 'activity' and 'dateRange' not in row:
        begin, end = (row['departure'], row['arrival']) if kind == 'flight' else (row['start'], row['end'])
        timing.update(startLocal=begin['local'], endLocal=end['local'], startTimeZone=begin['timeZone'], endTimeZone=end['timeZone'],
                      startOffsetMinutes=begin['offsetMinutes'], endOffsetMinutes=end['offsetMinutes'])
        note = '\n'.join(filter(None, [note, f"当地时间：{begin['local']} ({begin['timeZone']}) → {end['local']} ({end['timeZone']})"]))
        if kind == 'flight':
            timing.update(departure=begin, arrival=end, flightNumber=row['flightNumber'])
            note += '\n' + ' → '.join(' '.join(filter(None, [p.get('airport'), p.get('city')])) for p in (begin, end))
        return {'start': begin['instant'], 'end': end['instant'], 'allDay': False, 'travelTiming': timing, 'note': note}
    if kind == 'stay':
        begin, end = row['checkInDate'], row['checkOutDate']
        timing.update(timeZone=row['timeZone'], nights=row['nights'], propertyName=row['propertyName'], address=row['address'],
                      checkInTime=row['checkInTime'], checkOutTime=row['checkOutTime'])
        note = '\n'.join(filter(None, [note, f"住宿：{row['propertyName']}；{begin} 入住，{end} 退房（{row['nights']} 晚）；{row['timeZone']}",
            '地址：' + row['address'] if row['address'] else '',
            '已知入住时间：' + row['checkInTime'] if row['checkInTime'] else '',
            '已知退房时间：' + row['checkOutTime'] if row['checkOutTime'] else '']))
    elif kind == 'activity':
        begin, end = row['dateRange']['startDate'], row['dateRange']['endDateExclusive']
        timing['timeZone'] = row['timeZone']
        note = '\n'.join(filter(None, [note, f"全天日期：{begin} 至 {end}（结束日不含）；{row['timeZone']}"]))
    else:
        begin, end = row['start'], (date.fromisoformat(row['end']) + timedelta(days=1)).isoformat()
    timing.update(startDate=begin, endDateExclusive=end)
    return {'start': begin + 'T00:00:00+08:00', 'end': end + 'T00:00:00+08:00', 'allDay': True,
            'startDate': begin, 'endDateExclusive': end, 'travelTiming': timing, 'note': note}


def warnings(plan, old=None):
    result = []
    if plan.get('schemaVersion', 1) != 2:
        return result
    ref = zone(plan['referenceTimezone'], 'referenceTimezone')
    old_segments = {row['key']: row for row in (old or {}).get('segments', [])}
    for row in plan['segments']:
        projected = project(row)
        if projected['allDay']:
            begin = projected['startDate']
            end = (date.fromisoformat(projected['endDateExclusive']) - timedelta(days=1)).isoformat()
        else:
            begin = datetime.fromisoformat(projected['start']).astimezone(ref).date().isoformat()
            end = datetime.fromisoformat(projected['end']).astimezone(ref).date().isoformat()
        if begin < plan['start'] or end > plan['end']:
            result.append({'code': 'outside_trip_dates', 'itemKey': 'segment:' + row['key'], 'startDate': begin, 'endDate': end,
                           'message': '此段超出旅行概览日期；请核对参考时区和总日期，确认后仍可保留。'})
        previous = old_segments.get(row['key'])
        if previous and old['start'] != plan['start']:
            if previous.get('kind'):
                prior_projection = project(previous)
            else:
                prior_projection = {'start': previous['start'] + 'T00:00:00+08:00',
                                    'end': (date.fromisoformat(previous['end']) + timedelta(days=1)).isoformat() + 'T00:00:00+08:00', 'allDay': True}
            moved = any(prior_projection.get(field) != projected.get(field) for field in ('start', 'end', 'allDay'))
            result.append({'code': 'reschedule_moved' if moved else 'reschedule_preserved', 'itemKey': 'segment:' + row['key'],
                           'bookingState': row['bookingState'], 'datePolicy': row['datePolicy'],
                           'message': '按提交的最终日期调整。' if moved else '保留原段日期，没有自动随总日期移动。'})
    for dest in plan['destinations']:
        if dest['arrival'] < plan['start'] or dest['departure'] > plan['end']:
            result.append({'code': 'destination_outside_trip_dates', 'itemKey': 'destination:' + dest['key'],
                           'message': '目的地当地日期超出旅行概览日期，请核对当地时区与总日期。'})
    for previous, following in zip(plan['destinations'], plan['destinations'][1:]):
        gap = (date.fromisoformat(following['arrival']) - date.fromisoformat(previous['departure'])).days
        if gap:
            result.append({'code': 'destination_overlap' if gap < 0 else 'destination_gap', 'itemKey': 'destination:' + following['key'],
                           'days': abs(gap), 'message': '相邻目的地当地日期有重叠或空档；跨时区可合理出现，请人工核对行程衔接。'})
    flights = [row for row in plan['segments'] if row['kind'] == 'flight' and row['bookingState'] != 'cancelled']
    for previous, following in zip(flights, flights[1:]):
        gap = (datetime.fromisoformat(following['departure']['instant']) - datetime.fromisoformat(previous['arrival']['instant'])).total_seconds() / 60
        result.append({'code': 'flight_connection', 'itemKey': 'segment:' + following['key'], 'gapMinutes': int(gap),
                       'airportChanged': previous['arrival']['airport'] != following['departure']['airport'],
                       'message': '按列表顺序计算起降间隔；不代表已满足转机、入境或机场最短衔接要求。'})
    return result
