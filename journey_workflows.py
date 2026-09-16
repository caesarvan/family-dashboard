"""Previewed, transactional travel plans linking tasks, purchases and calendars.

No external policy is inferred and no remote calendar write is claimed here. Each
household's ``db()`` owns its own namespace, including signed preview isolation.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import secrets

from flask import Response, g, jsonify
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from journey_time import TimeIssue, normalize_segment, project, warnings as time_warnings, zone


POLICY_NOTICE = '准备事项是规划建议，不代表已核实的签证、入境或健康要求；请按出行人证件、目的地和日期向官方渠道核对。'
MAX_ITEMS = 100


def initialize_journeys(con):
    """Safe for a new household database after core tables have been initialized."""
    con.executescript('''
    CREATE TABLE IF NOT EXISTS journey_workflows(
      id TEXT PRIMARY KEY, trip_id TEXT NOT NULL UNIQUE REFERENCES entities(id) ON DELETE CASCADE,
      plan TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
      created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS journey_links(
      journey_id TEXT NOT NULL REFERENCES journey_workflows(id) ON DELETE CASCADE,
      item_key TEXT NOT NULL, entity_id TEXT NOT NULL UNIQUE REFERENCES entities(id) ON DELETE CASCADE,
      kind TEXT NOT NULL, PRIMARY KEY(journey_id,item_key));
    CREATE INDEX IF NOT EXISTS journey_links_workflow ON journey_links(journey_id,kind);
    CREATE TABLE IF NOT EXISTS journey_actions(
      actor TEXT NOT NULL REFERENCES users(id), action_key TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE,
      digest TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(actor,action_key));
    ''')
    con.execute("INSERT OR IGNORE INTO settings(id,data) VALUES('journey_namespace',?)",
                (json.dumps(secrets.token_hex(24)),))
    con.commit()


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def register_journeys(app, db, Problem, body, require_member, audit):
    with app.app_context():
        initialize_journeys(db())
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='household-journey-preview-v1')

    @app.errorhandler(TimeIssue)
    def journey_time_error(exc):
        return jsonify(error=str(exc), code=exc.code, field=exc.field, choices=exc.choices), 400

    def ready():
        con = db()
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='journey_workflows'").fetchone():
            initialize_journeys(con)
        return con

    def text(value, label, limit=100, optional=False):
        if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
            raise Problem(f'{label}应为 1～{limit} 个字符' if not optional else f'{label}格式不正确')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise Problem(f'{label}包含无效字符')
        return value.strip()

    def date_value(value, label):
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise Problem(f'{label}应为 YYYY-MM-DD')
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise Problem(f'{label}不是有效日期')
        if not 2000 <= parsed.year <= 2100:
            raise Problem(f'{label}须介于 2000 至 2100 年')
        return parsed.isoformat()

    def amount(value, label, optional=False):
        if optional and value is None:
            return None
        if type(value) is not int or not 0 <= value <= 100_000_000_000:
            raise Problem(f'{label}须为非负整数分')
        return value

    def sequence(value, label, maximum=MAX_ITEMS):
        if not isinstance(value, list) or len(value) > maximum or any(not isinstance(row, dict) for row in value):
            raise Problem(f'{label}最多 {maximum} 项，且每项应为对象')
        return value

    def owner(value, members):
        if not isinstance(value, str) or value not in ['shared', *members]:
            raise Problem('负责人须是本家庭成员或共同负责')
        return value

    def item_key(value, fallback):
        value = value or fallback
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
            raise Problem('事项 key 只能包含字母、数字、下划线及短横线，最多 64 位')
        return value

    def defaults(international):
        entries = [
            ('confirm-transport', '确认往返交通与取消规则', -30, '核对姓名、时间、行李额度和改退条件。'),
            ('confirm-stay', '确认住宿与抵达方式', -21, '保存预订信息，安排从机场或车站到住处的交通。'),
            ('budget-check', '核对预算与近期付款', -14, '核对已支付、待付款与可取消项目，避免重复计入。'),
            ('home-preparation', '安排出行期间的家务与照看', -5, '按需安排保洁、宠物、植物及快递。'),
            ('packing', '核对行李与预订资料', -2, '检查证件、充电设备、常用物品和离线行程。'),
        ]
        if international:
            entries[0:0] = [
                ('verify-entry', '核对证件、签证与入境材料', -45, POLICY_NOTICE),
                ('verify-cover', '核对保障、通信与付款准备', -14, '按实际目的地核对旅行保障范围、通信方案和支付方式；不预设购买要求。'),
            ]
        return [{'key': key, 'title': title, 'dueOffsetDays': offset, 'owner': 'shared',
                 'note': note, 'category': 'preparation'} for key, title, offset, note in entries]

    def normalize(raw, con):
        if not isinstance(raw, dict):
            raise Problem('plan 应为对象')
        version = raw.get('schemaVersion', 1)
        if type(version) is not int or version not in (1, 2):
            raise Problem('旅行计划版本不支持，请升级服务或保留原版本')
        people = [row['id'] for row in con.execute('SELECT id FROM users ORDER BY id')]
        members = raw.get('memberIds', people)
        if not isinstance(members, list) or not members or len(members) > len(people) or any(
                not isinstance(uid, str) or uid not in people for uid in members) or len(set(members)) != len(members):
            raise Problem('请选择有效的出行成员')
        start = date_value(raw.get('start'), '出发日期')
        end = date_value(raw.get('end'), '返程日期')
        if not 0 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 366:
            raise Problem('返程不得早于出发，单次行程最多 367 天')
        international = raw.get('international', False)
        if type(international) is not bool:
            raise Problem('international 应为布尔值')
        plan = {'title': text(raw.get('title'), '旅行名称'), 'start': start, 'end': end,
                'international': international, 'memberIds': members,
                'budget': amount(raw.get('budget', 0), '旅行预算'),
                'saved': amount(raw.get('saved', 0), '已预留金额'),
                'paid': amount(raw.get('paid', 0), '已付款'),
                'note': text(raw.get('note', ''), '旅行备注', 2000, True),
                'destinations': [], 'checklist': [], 'shopping': [], 'segments': []}
        if version == 2:
            plan['schemaVersion'] = 2
            plan['referenceTimezone'] = zone(raw.get('referenceTimezone'), 'referenceTimezone').key
        for index, dest in enumerate(sequence(raw.get('destinations', []), '目的地', 20)):
            arrive = date_value(dest.get('arrival', start), '抵达日期')
            leave = date_value(dest.get('departure', end), '离开日期')
            if arrive > leave or version == 1 and not start <= arrive <= leave <= end:
                raise Problem('每个目的地的日期须落在旅行日期内')
            plan['destinations'].append({'key': item_key(dest.get('key'), f'destination-{index + 1}'),
                                         'country': text(dest.get('country', ''), '国家或地区', 60, True),
                                         'city': text(dest.get('city'), '目的地城市', 80),
                                         'arrival': arrive, 'departure': leave})
            if version == 2:
                plan['destinations'][-1]['timeZone'] = zone(dest.get('timeZone'), f'destinations[{index}].timeZone').key
        if not plan['destinations']:
            raise Problem('至少填写一个目的地')
        checklist = raw.get('checklist', defaults(international))
        for index, row in enumerate(sequence(checklist, '准备清单')):
            offset = row.get('dueOffsetDays', -7)
            if type(offset) is not int or not -730 <= offset <= 366:
                raise Problem('相对截止天数须介于 -730 至 366 天')
            due = date_value(row['due'], '截止日期') if row.get('due') else (date.fromisoformat(start) + timedelta(days=offset)).isoformat()
            if due > end:
                raise Problem('准备事项截止日期不得晚于旅行结束')
            plan['checklist'].append({'key': item_key(row.get('key'), f'task-{index + 1}'),
                                      'title': text(row.get('title'), '准备事项'),
                                      'owner': owner(row.get('owner', 'shared'), people),
                                      'dueOffsetDays': (date.fromisoformat(due) - date.fromisoformat(start)).days,
                                      'due': due, 'note': text(row.get('note', ''), '准备事项备注', 500, True),
                                      'category': text(row.get('category', 'preparation'), '事项分类', 40)})
        for index, row in enumerate(sequence(raw.get('shopping', []), '采购清单')):
            plan['shopping'].append({'key': item_key(row.get('key'), f'purchase-{index + 1}'),
                                     'title': text(row.get('title'), '采购名称'),
                                     'quantity': text(row.get('quantity', '1 件'), '采购数量', 30),
                                     'owner': owner(row.get('owner', 'shared'), people),
                                     'budget': amount(row.get('budget'), '采购预算', True),
                                     'note': text(row.get('note', ''), '采购备注', 500, True)})
        segments = raw.get('segments', [
            {'key': dest['key'], 'title': dest['city'] + ' · 停留', 'start': dest['arrival'],
             'end': dest['departure'], 'location': ' · '.join(filter(None, [dest['country'], dest['city']]))}
            for dest in plan['destinations']])
        for index, row in enumerate(sequence(segments, '分段行程')):
            if version == 2:
                normalized = normalize_segment(row, index, text, item_key)
                if normalized.get('destinationKey') and normalized['destinationKey'] not in {dest['key'] for dest in plan['destinations']}:
                    raise Problem('分段关联的目的地不存在')
                plan['segments'].append(normalized)
                continue
            begin = date_value(row.get('start'), '行程开始日期')
            finish = date_value(row.get('end', begin), '行程结束日期')
            if not start <= begin <= finish <= end:
                raise Problem('分段行程日期须落在旅行日期内')
            plan['segments'].append({'key': item_key(row.get('key'), f'segment-{index + 1}'),
                                     'title': text(row.get('title'), '行程标题'), 'start': begin, 'end': finish,
                                     'location': text(row.get('location', ''), '行程地点', 200, True),
                                     'note': text(row.get('note', ''), '行程备注', 500, True)})
        for collection in ('destinations', 'checklist', 'shopping', 'segments'):
            keys = [row['key'] for row in plan[collection]]
            if len(keys) != len(set(keys)):
                raise Problem(f'{collection} 的 key 不能重复')
        return plan

    def find_workflow(con, uid):
        row = con.execute('SELECT * FROM journey_workflows WHERE id=?', (uid,)).fetchone()
        if not row:
            raise Problem('旅行工作流不存在，可能已被删除', 404)
        return row

    def linked(con, uid):
        return {row['item_key']: row for row in con.execute(
            '''SELECT l.item_key,l.kind,e.id,e.data,e.revision FROM journey_links l
            JOIN entities e ON e.id=l.entity_id WHERE l.journey_id=?''', (uid,))}

    def materialize(plan, journey_id, trip_id):
        place = ' → '.join(dest['city'] for dest in plan['destinations'])
        shared = {'journeyId': journey_id, 'tripId': trip_id}
        rows = {'trip': ('trips', {'title': plan['title'], 'destination': place[:80], 'start': plan['start'],
                                 'end': plan['end'], 'budget': plan['budget'], 'saved': plan['saved'], 'paid': plan['paid'],
                                 'note': plan['note'], 'journeyId': journey_id})}
        for row in plan['checklist']:
            rows['task:' + row['key']] = ('tasks', {**shared, 'title': row['title'], 'owner': row['owner'],
                'due': row['due'], 'note': row['note'], 'done': False})
        for row in plan['shopping']:
            rows['shopping:' + row['key']] = ('shopping', {**shared, 'title': row['title'], 'owner': row['owner'],
                'quantity': row['quantity'], 'budget': row['budget'], 'actual': None, 'note': row['note'],
                'done': False, 'photoIds': []})
        segments = [{'key': 'overview', 'title': plan['title'], 'start': plan['start'], 'end': plan['end'],
                     'location': place, 'note': plan['note']}, *plan['segments']]
        for index, row in enumerate(segments):
            key = 'event:overview' if index == 0 else 'segment:' + row['key']
            if index and plan.get('schemaVersion') == 2:
                # A cancellation is a visible planning marker. Preserve its stable
                # event/link identity and never infer a remote cancellation action.
                rows[key] = ('events', {**shared, 'title': ('[已取消] ' if row.get('bookingState') == 'cancelled' else '') + row['title'], 'owner': 'shared',
                    'location': (row.get('location') or row.get('address') or row.get('propertyName') or '')[:200],
                    'source': '旅行计划', 'imported': False, **project(row)})
                continue
            rows[key] = ('events', {**shared, 'title': row['title'], 'owner': 'shared',
                'start': row['start'] + 'T00:00:00+08:00',
                'end': (date.fromisoformat(row['end']) + timedelta(days=1)).isoformat() + 'T00:00:00+08:00',
                'location': row['location'][:200], 'note': row['note'], 'allDay': True,
                'source': '旅行计划', 'imported': False})
        return rows

    EVENT_GROUPS = {'timing': ('start', 'end', 'allDay', 'travelTiming', 'startDate', 'endDateExclusive'),
                    'title': ('title',), 'location': ('location',), 'note': ('note',), 'owner': ('owner',)}

    def semantic_timing(payload):
        timing = payload.get('travelTiming') or {}
        # Date changes are ordinary continuous sync; reinterpretations need review.
        return {key: timing.get(key) for key in ('schemaVersion', 'kind', 'startTimeZone', 'endTimeZone', 'timeZone')}, bool(payload.get('allDay')), timing.get('bookingState') == 'cancelled'

    def merge_events(baseline, existing, desired, resolutions):
        if not isinstance(resolutions, dict):
            raise Problem('conflictResolutions 应为对象')
        conflicts, preserved, resolved, effective, holds, used = [], [], [], {}, [], set()
        for key, (kind, proposed) in desired.items():
            if kind != 'events' or key not in existing or key not in baseline:
                continue
            base = baseline[key][1]
            current = json.loads(existing[key]['data'])
            merged = dict(proposed)
            choices = resolutions.get(key, {})
            if not isinstance(choices, dict):
                raise Problem('每项冲突选择应为对象')
            groups = dict(EVENT_GROUPS)
            time_fields = groups['timing']
            if ({name: base.get(name) for name in time_fields} != {name: proposed.get(name) for name in time_fields}):
                # The generated note describes local clocks/zones. Keeping old
                # timing with a new timed description would misrepresent the event.
                groups['timing'] = (*time_fields, 'note')
                groups.pop('note')
            for group, fields in groups.items():
                snapshots = [{name: item[name] for name in fields if name in item} for item in (base, current, proposed)]
                before, now, after = snapshots
                if before == now or now == after:
                    continue
                issue = {'itemKey': key, 'entityId': existing[key]['id'], 'fieldGroup': group,
                         'base': before, 'current': now, 'proposed': after, 'choices': ['current', 'plan']}
                if after == before:
                    selection = 'current'
                    preserved.append(issue)
                else:
                    selection = choices.get(group)
                    if selection not in ('current', 'plan'):
                        conflicts.append(issue)
                        continue
                    used.add((key, group))
                    resolved.append({**issue, 'resolution': selection})
                if selection == 'current':
                    for field in fields:
                        merged.pop(field, None)
                    merged.update(now)
            effective[key] = merged
            if semantic_timing(current) != semantic_timing(merged):
                holds.append({'itemKey': key, 'entityId': existing[key]['id'], 'message': '时间类型或时区语义变化；已有云日历绑定须重新预览确认。'})
        for key, groups in resolutions.items():
            if not isinstance(groups, dict) or any((key, group) not in used for group in groups):
                raise Problem('冲突选择已失效或包含未知字段，请重新预览', 409)
        return effective, conflicts, preserved, resolved, holds

    def entity_snapshot(con, uid):
        return {row['id']: row['revision'] for row in linked(con, uid).values()}

    def detail(con, uid):
        row = find_workflow(con, uid)
        records = linked(con, uid)
        grouped = {kind: [] for kind in ('trips', 'tasks', 'shopping', 'events')}
        for key, entry in records.items():
            grouped[entry['kind']].append({**json.loads(entry['data']), 'id': entry['id'], 'revision': entry['revision'], 'workflowKey': key})
        tasks, purchases = grouped['tasks'], grouped['shopping']
        original = json.loads(row['plan'])
        trip = grouped['trips'][0] if grouped['trips'] else None
        purchase_budget = sum(item.get('budget') or 0 for item in purchases)
        purchase_actual = sum(item.get('actual') or 0 for item in purchases if item.get('done'))
        return {'id': uid, 'revision': row['revision'], 'tripId': row['trip_id'], 'plan': original,
                'trip': trip, 'tasks': tasks, 'shopping': purchases, 'events': grouped['events'],
                'progress': {'done': sum(bool(item.get('done')) for item in tasks), 'total': len(tasks),
                             'purchased': sum(bool(item.get('done')) for item in purchases), 'purchaseCount': len(purchases)},
                'budget': {'total': (trip or original)['budget'], 'paid': (trip or original)['paid'],
                           'reserved': (trip or original)['saved'], 'purchaseBudget': purchase_budget,
                           'purchaseActual': purchase_actual, 'unknownPurchaseBudgets': sum(item.get('budget') is None for item in purchases),
                           'unknownPurchaseActuals': sum(item.get('done') and item.get('actual') is None for item in purchases),
                           'note': '采购金额是旅行预算内的规划，不与已付金额重复相加；不会自动记为财务支出。'},
                'calendar': {'local': 'created', 'eventIds': [entry['id'] for entry in grouped['events']],
                             'cloud': 'not_requested', 'icsUrl': f'/api/journeys/{uid}/calendar.ics'},
                'policyNotice': POLICY_NOTICE, 'updatedAt': row['updated_at']}

    @app.get('/api/journeys/templates')
    def journey_templates():
        require_member()
        return jsonify(version=1, supportedSchemaVersions=[1, 2], policyNotice=POLICY_NOTICE,
                       templates=[{'id': 'domestic', 'name': '国内旅行', 'checklist': defaults(False)},
                                  {'id': 'international', 'name': '境外旅行', 'checklist': defaults(True)}])

    @app.get('/api/journeys')
    def journey_list():
        con = ready()
        rows = con.execute('SELECT id FROM journey_workflows ORDER BY updated_at DESC').fetchall()
        return jsonify(journeys=[detail(con, row['id']) for row in rows], capabilities={'schemaVersions': [1, 2]})

    @app.get('/api/journeys/<uid>')
    def journey_detail(uid):
        return jsonify(detail(ready(), uid))

    @app.post('/api/journeys/preview')
    def journey_preview():
        require_member()
        con = ready()
        value = body()
        plan = normalize(value.get('plan'), con)
        uid, trip_id = value.get('journeyId'), value.get('tripId')
        if uid is not None and not isinstance(uid, str) or trip_id is not None and not isinstance(trip_id, str):
            raise Problem('旅行标识格式不正确')
        revisions = {}
        adoptions = {}
        expected_revision = None
        existing = {}
        old_plan = None
        if uid:
            current = find_workflow(con, uid)
            expected_revision = value.get('revision')
            if type(expected_revision) is not int or expected_revision != current['revision']:
                raise Problem('旅行计划已更新，请重新打开后预览', 409)
            trip_id = current['trip_id']
            revisions = entity_snapshot(con, uid)
            existing = linked(con, uid)
            old_plan = json.loads(current['plan'])
            if old_plan.get('schemaVersion', 1) == 2 and plan.get('schemaVersion', 1) != 2:
                raise Problem('旅行已使用 v2 时间结构，不能降级丢弃航班与时区信息', 409)
        elif trip_id:
            trip = con.execute("SELECT * FROM entities WHERE id=? AND kind='trips'", (trip_id,)).fetchone()
            if not trip:
                raise Problem('原旅行不存在', 404)
            if con.execute('SELECT 1 FROM journey_workflows WHERE trip_id=?', (trip_id,)).fetchone():
                raise Problem('这趟旅行已有工作流，请打开现有工作流', 409)
            if type(value.get('tripRevision')) is not int or value['tripRevision'] != trip['revision']:
                raise Problem('原旅行已更新，请刷新', 409)
            revisions = {trip_id: trip['revision']}
            existing = {'trip': {**dict(trip), 'kind': 'trips'}}
            # Upgrade explicitly selected existing preparation without duplicating it.
            selected = {'task:' + item['key'] for item in plan['checklist']}
            for task in con.execute("SELECT * FROM entities WHERE kind='tasks'"):
                item_key_ = 'task:existing-' + task['id']
                if item_key_ in selected and json.loads(task['data']).get('tripId') == trip_id:
                    if json.loads(task['data']).get('sync'):
                        raise Problem('云清单事项不能直接改为本地工作流事项')
                    existing[item_key_] = task
                    adoptions[item_key_] = task['id']
                    revisions[task['id']] = task['revision']
        new_id = uid or secrets.token_hex(12)
        trip_id = trip_id or secrets.token_hex(12)
        desired = materialize(plan, new_id, trip_id)
        baseline = materialize(old_plan, new_id, trip_id) if old_plan else {}
        effective, conflicts, preserved, resolved, holds = merge_events(baseline, existing, desired, value.get('conflictResolutions', {}))
        removed = [key for key in existing if key not in desired]
        summary = {'create': dict(Counter(kind for key, (kind, _) in desired.items() if key not in existing)),
                   'update': dict(Counter(kind for key, (kind, _) in desired.items() if key in existing)),
                   'detach': len(removed), 'policyNotice': POLICY_NOTICE,
                   'calendar': '定时段保存 UTC 时刻；住宿/全天段保留日期且不含排除结束日；既有云端时间语义变化须再确认。',
                   'conflicts': conflicts, 'preserved': preserved, 'resolved': resolved, 'cloudReviews': holds,
                   'warnings': time_warnings(plan, old_plan),
                   'removedItems': '移出计划的已有事项保留为独立记录，完成状态和照片不会删除。'}
        claims = {'v': 1, 'actor': g.actor['id'],
                  'household': json.loads(con.execute("SELECT data FROM settings WHERE id='journey_namespace'").fetchone()[0]),
                  'operationId': secrets.token_hex(16), 'journeyId': new_id, 'tripId': trip_id,
                  'existing': bool(uid), 'revision': expected_revision, 'entities': revisions,
                  'adoptions': adoptions, 'plan': plan, 'effectiveEvents': effective, 'cloudReviews': holds}
        return jsonify(plan=plan, summary=summary, canApply=not conflicts,
                       previewToken=signer.dumps(claims) if not conflicts else None, expiresIn=1800)

    @app.post('/api/journeys/apply')
    def journey_apply():
        require_member()
        con = ready()
        value = body()
        token = value.get('previewToken')
        key = value.get('idempotencyKey')
        if not isinstance(token, str) or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', key):
            raise Problem('请提交预览凭证和 8～80 位幂等键')
        try:
            claims = signer.loads(token, max_age=1800)
        except SignatureExpired:
            raise Problem('预览已过期，请重新预览', 409)
        except BadSignature:
            raise Problem('预览凭证无效，请重新预览', 400)
        namespace = json.loads(con.execute("SELECT data FROM settings WHERE id='journey_namespace'").fetchone()[0])
        if claims.get('actor') != g.actor['id'] or claims.get('household') != namespace:
            raise Problem('此预览属于其他成员或家庭，请在当前账户重新预览', 403)
        digest = hashlib.sha256(pack(claims).encode()).hexdigest()
        # Match the cloud worker's lock order before acquiring a SQLite write lock.
        # Recheck the binding set inside the transaction: a concurrent new publish
        # must cause a retry instead of operating without its account lock.
        engine = app.extensions.get('cloud_accounts')
        has_publications = bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calendar_publications'").fetchone())
        def accounts():
            return {row[0] for row in con.execute('SELECT DISTINCT account_id FROM calendar_publications WHERE journey_id=?', (claims['journeyId'],))} if has_publications else set()
        account_ids = accounts()
        locks = ExitStack()
        try:
            if engine:
                for account_id in sorted(account_ids):
                    locks.enter_context(engine.lock(account_id))
            con.execute('BEGIN IMMEDIATE')
            # Cookie authentication may have been revoked while waiting for
            # account locks. Check it under the same lock as writes and replay.
            member = app.extensions['member_sessions'].current(con)
            if (member['owner'] != g.actor['id']
                    or member['auth_version'] != g.actor['auth_version']
                    or g.actor.get('householdId', 'default') != app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')):
                raise Problem('登录状态已变化，请重新登录', 401)
            if accounts() != account_ids:
                raise Problem('云日历绑定已变化，请重新预览', 409)
            previous = con.execute('SELECT * FROM journey_actions WHERE actor=? AND action_key=?', (g.actor['id'], key)).fetchone()
            if previous:
                if previous['digest'] != digest:
                    raise Problem('该幂等键已用于其他预览，请重新预览', 409)
                con.rollback()
                return jsonify(**json.loads(previous['result']), replayed=True)
            previous = con.execute('SELECT * FROM journey_actions WHERE operation_id=?', (claims['operationId'],)).fetchone()
            if previous:
                con.rollback()
                return jsonify(**json.loads(previous['result']), replayed=True)
            uid, trip_id, plan = claims['journeyId'], claims['tripId'], claims['plan']
            current = find_workflow(con, uid) if claims['existing'] else None
            if current and current['revision'] != claims['revision']:
                raise Problem('旅行计划已更新，请重新预览', 409)
            if not current and con.execute('SELECT 1 FROM journey_workflows WHERE trip_id=?', (trip_id,)).fetchone():
                raise Problem('旅行已有工作流，请重新打开', 409)
            for entity_id, revision in claims['entities'].items():
                actual = con.execute('SELECT revision FROM entities WHERE id=?', (entity_id,)).fetchone()
                if not actual or actual['revision'] != revision:
                    raise Problem('旅行或关联事项已被修改，请重新预览以保留最新状态', 409)
            existing = linked(con, uid) if current else {}
            if not current and trip_id in claims['entities']:
                existing['trip'] = con.execute('SELECT * FROM entities WHERE id=?', (trip_id,)).fetchone()
            if not current:
                for item_key_, entity_id in claims.get('adoptions', {}).items():
                    existing[item_key_] = con.execute('SELECT * FROM entities WHERE id=?', (entity_id,)).fetchone()
            desired = materialize(plan, uid, trip_id)
            for item_key_, payload in claims.get('effectiveEvents', {}).items():
                if item_key_ in desired and desired[item_key_][0] == 'events':
                    desired[item_key_] = ('events', payload)
            counts = Counter(row['kind'] for row in con.execute('SELECT kind FROM entities'))
            for item_key_, (kind, _) in desired.items():
                if item_key_ not in existing:
                    counts[kind] += 1
            if any(number > 2500 for number in counts.values()):
                raise Problem('生成后记录将超过上限，请先整理旧记录')
            changed_at = stamp()
            # Insert the trip first to satisfy the workflow foreign key.
            if 'trip' not in existing:
                con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,'trips',?,?)",
                            (trip_id, pack(desired['trip'][1]), changed_at))
            if not current:
                con.execute('INSERT INTO journey_workflows(id,trip_id,plan,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                            (uid, trip_id, pack(plan), g.actor['id'], changed_at, changed_at))
            for item_key_, (kind, payload) in desired.items():
                old = existing.get(item_key_)
                entity_id = old['id'] if old else trip_id if item_key_ == 'trip' else secrets.token_hex(12)
                if old:
                    old_data = json.loads(old['data'])
                    for preserved in ('done', 'actual', 'photoIds'):
                        if preserved in old_data:
                            payload[preserved] = old_data[preserved]
                    con.execute('UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=?',
                                (pack(payload), changed_at, entity_id))
                    if kind == 'events' and has_publications and semantic_timing(old_data) != semantic_timing(payload):
                        # Keep pending write/recovery evidence and stable remote identity.
                        con.execute("UPDATE calendar_publications SET status='needs_review',review_required=1,error=?,updated_at=? WHERE entity_id=?",
                                    ('旅行时间类型或时区语义已变化，请预览并确认新的云日程；旧的待处理写入已暂停。', changed_at, entity_id))
                elif item_key_ != 'trip':
                    con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)',
                                (entity_id, kind, pack(payload), changed_at))
                con.execute('INSERT OR IGNORE INTO journey_links(journey_id,item_key,entity_id,kind) VALUES(?,?,?,?)',
                            (uid, item_key_, entity_id, kind))
            # Removal from a plan is detachment, not destructive record deletion.
            for item_key_, old in existing.items():
                if item_key_ in desired:
                    continue
                payload = json.loads(old['data'])
                payload.pop('journeyId', None)
                payload['tripId'] = ''
                con.execute('UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=?',
                            (pack(payload), changed_at, old['id']))
                con.execute('DELETE FROM journey_links WHERE journey_id=? AND item_key=?', (uid, item_key_))
            if current:
                con.execute('UPDATE journey_workflows SET plan=?,revision=revision+1,updated_at=? WHERE id=?',
                            (pack(plan), changed_at, uid))
            audit('journey_apply', uid)
            revision = current['revision'] + 1 if current else 1
            result = {'id': uid, 'tripId': trip_id, 'revision': revision,
                      'calendar': {'local': 'created', 'cloud': 'not_requested', 'icsUrl': f'/api/journeys/{uid}/calendar.ics'}}
            con.execute('INSERT INTO journey_actions(actor,action_key,operation_id,digest,result,created_at) VALUES(?,?,?,?,?,?)',
                        (g.actor['id'], key, claims['operationId'], digest, pack(result), changed_at))
            con.commit()
            return jsonify(**result, replayed=False), (200 if current else 201)
        except Exception:
            con.rollback()
            raise
        finally:
            locks.close()

    @app.get('/api/journeys/<uid>/calendar')
    def journey_calendar(uid):
        require_member()
        result = detail(ready(), uid)
        return jsonify(journeyId=uid, revision=result['revision'], events=result['events'],
                       localStatus='created', cloudStatus='not_requested',
                       writeRequirement='由成员选择具有写权限的云日历后，使用 event.id 作为外部幂等键并持久化远端标识。',
                       icsUrl=result['calendar']['icsUrl'])

    @app.get('/api/journeys/<uid>/calendar.ics')
    def journey_calendar_ics(uid):
        require_member()
        result = detail(ready(), uid)
        def escaped(value):
            return str(value or '').replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')
        def fold(value):
            # RFC 5545 content lines are limited to 75 octets, not characters.
            chunks, current, size = [], '', 0
            for char in value:
                width = len(char.encode('utf-8'))
                if size + width > 75:
                    chunks.append(current)
                    current, size = ' ', 1
                current += char
                size += width
            return '\r\n'.join([*chunks, current])
        lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Household Hub//Journeys//ZH-CN', 'CALSCALE:GREGORIAN']
        for event in result['events']:
            if event.get('allDay'):
                date_lines = ['DTSTART;VALUE=DATE:' + event.get('startDate', event['start'][:10]).replace('-', ''),
                              'DTEND;VALUE=DATE:' + event.get('endDateExclusive', event['end'][:10]).replace('-', '')]
            else:
                date_lines = [name + ':' + datetime.fromisoformat(event[field]).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                              for name, field in (('DTSTART', 'start'), ('DTEND', 'end'))]
            lines += ['BEGIN:VEVENT', 'UID:' + event['id'] + '@household-journey',
                      'DTSTAMP:' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
                      'SEQUENCE:' + str(event['revision']),
                      *date_lines,
                      'SUMMARY:' + escaped(event['title']), 'LOCATION:' + escaped(event.get('location')),
                      'DESCRIPTION:' + escaped(event.get('note')), 'END:VEVENT']
        lines += ['END:VCALENDAR']
        return Response('\r\n'.join(fold(line) for line in lines) + '\r\n', mimetype='text/calendar',
                        headers={'Content-Disposition': f'attachment; filename="journey-{uid}.ics"', 'Cache-Control': 'no-store'})

    app.extensions['journeys'] = {'initialize': initialize_journeys, 'detail': detail, 'normalize': normalize}
