"""Private in-app task acknowledgements; live references, never provider writes."""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from flask import jsonify, request

from finance_source_bridge import ImportSession
import task_dependencies

TIME_ZONE = 'Asia/Shanghai'
PAGE_SIZE = 40
MAX_REVISION = 9007199254740991
MAX_STATES = 20000
MAX_OPERATIONS = 40000
HEARTBEAT = 'task-reminders-worker'
SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS task_reminders(
    owner TEXT NOT NULL REFERENCES users(id), task_id TEXT NOT NULL, due TEXT NOT NULL,
    read_at TEXT, snoozed_until TEXT, revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(owner,task_id,due));
CREATE TABLE IF NOT EXISTS task_reminder_operations(
    owner TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
    intent_digest TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(owner,request_id));
'''


class ReminderError(ValueError):
    def __init__(self, message, status=400, code='invalid_reminder_request'):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def clock():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds')


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def occurrence(task_id, due):
    return hashlib.sha256(packed(['task-reminder-v1', task_id, due]).encode()).hexdigest()


def clear_member(con, owner):
    """Membership stop owns the transaction; never clear on ordinary logout."""
    if not con.in_transaction:
        raise RuntimeError('reminder_cleanup_requires_transaction')
    # Membership domain also supports a pre-reminder household during migration.
    existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ('task_reminders', 'task_reminder_operations'):
        if table in existing:
            con.execute('DELETE FROM ' + table + ' WHERE owner=?', (owner,))


def live_tasks(con, moment):
    """Current household shared task ACL plus narrower recipient routing.

    Selected task sources are explicitly shared by cloud_accounts.select().
    A cloud mirror also needs its actual source/item/account and active owner;
    stale or forged JSON sync data cannot grant reminder access.
    """
    members = {r[0] for r in con.execute("SELECT member_id FROM household_memberships WHERE state='active'")}
    cloud = {r['entity_id']: dict(r) for r in con.execute(
        "SELECT i.entity_id,i.source_id,i.remote_id,a.provider FROM cloud_items i "
        "JOIN cloud_sources s ON s.id=i.source_id JOIN cloud_accounts a ON a.id=s.account_id "
        "JOIN household_memberships m ON m.member_id=a.owner "
        "WHERE s.kind='tasks' AND s.owner='shared' AND m.state='active'")}
    graph = task_dependencies.task_graph(con)
    result = {}
    for row in con.execute("SELECT id,data,revision FROM entities WHERE kind='tasks'"):
        value = json.loads(row['data'])
        due = value.get('due')
        if value.get('done') is True or not isinstance(due, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', due):
            continue
        try:
            day = date.fromisoformat(due)
        except ValueError:
            continue
        if not 2000 <= day.year <= 2100:
            continue
        eligible = datetime.combine(day, time(9), ZoneInfo(TIME_ZONE))
        if moment < eligible:
            continue
        owner = value.get('owner')
        recipients = members if owner == 'shared' else ({owner} & members if isinstance(owner, str) else set())
        sync = value.get('sync')
        if sync:
            known = cloud.get(row['id'])
            if (not isinstance(sync, dict) or not known or owner != 'shared'
                    or any(sync.get(k) != known[v] for k, v in
                           (('sourceId', 'source_id'), ('remoteId', 'remote_id'), ('provider', 'provider')))):
                continue
        if not recipients:
            continue
        projected = task_dependencies.project(value, graph)
        task = {k: projected.get(k) for k in ('title', 'owner', 'due', 'dependsOn', 'blockedBy', 'dependencyStatus')}
        task.update(id=row['id'], revision=row['revision'])
        if sync:
            task['sync'] = {k: sync[k] for k in ('provider', 'sourceId', 'remoteId', 'version', 'readOnly') if k in sync}
        result[row['id']] = {'task': task, 'recipients': recipients, 'eligibleAt': iso(eligible),
                             'occurrence': occurrence(row['id'], due)}
    return result


def state_value(state, moment):
    read_at = state['read_at'] if state else None
    snooze = state['snoozed_until'] if state else None
    status = 'snoozed' if snooze and datetime.fromisoformat(snooze) > moment else 'read' if read_at else 'unread'
    return {'revision': state['revision'] if state else 0, 'readAt': read_at,
            'snoozedUntil': snooze, 'status': status}


def capacity(con, table, maximum):
    if con.execute('SELECT count(*) FROM ' + table).fetchone()[0] >= maximum:
        raise ReminderError('提醒历史已达上限，未删除已有记录，请稍后处理', 409, 'reminder_capacity')


class ReminderEngine:
    def __init__(self, app, db):
        self.app, self.db = app, db

    def tick(self):
        """Local transactional materialization, independent of HTTP identities."""
        with self.app.app_context():
            con = self.db()
            try:
                con.execute('BEGIN IMMEDIATE')
                moment = clock(); stamp = iso(moment)
                tasks = live_tasks(con, moment)
                # Inactive history is retained for same-date reopening. Removed
                # memberships are the only automatic destructive history cleanup.
                for table in ('task_reminders', 'task_reminder_operations'):
                    con.execute('DELETE FROM ' + table + " WHERE owner NOT IN (SELECT member_id FROM household_memberships WHERE state='active')")
                stored = {(r['owner'], r['task_id'], r['due']): r for r in con.execute('SELECT * FROM task_reminders')}
                for key, row in stored.items():
                    owner, uid, due = key
                    task = tasks.get(uid)
                    active = int(bool(task and owner in task['recipients'] and task['task']['due'] == due))
                    if row['active'] != active:
                        con.execute('UPDATE task_reminders SET active=?,updated_at=? WHERE owner=? AND task_id=? AND due=?',
                                    (active, stamp, *key))
                room = max(0, MAX_STATES - len(stored)); new = []; blocked = False
                # Bound new combinations by available capacity; never allocate
                # the full task x member cross product just to discard it.
                for uid, task in sorted(tasks.items()):
                    for owner in sorted(task['recipients']):
                        key = (owner, uid, task['task']['due'])
                        if key not in stored:
                            if len(new) >= room:
                                blocked = True
                                break
                            new.append(key)
                    if blocked: break
                for owner, uid, due in new:
                    con.execute('INSERT INTO task_reminders(owner,task_id,due,created_at,updated_at) VALUES(?,?,?,?,?)',
                                (owner, uid, due, stamp, stamp))
                heartbeat = {'lastCheckedAt': stamp, 'capacityBlocked': blocked}
                current = con.execute('SELECT data FROM settings WHERE id=?', (HEARTBEAT,)).fetchone()
                if not current or json.loads(current['data']) != heartbeat:
                    con.execute('INSERT INTO settings(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,revision=revision+1',
                                (HEARTBEAT, packed(heartbeat)))
                con.commit()
                return {'examined': len(tasks), 'generated': min(room, len(new)), **heartbeat}
            except BaseException:
                con.rollback()
                raise


def register_task_reminders(app, db, Problem, body, require_member):
    with app.app_context():
        con = db()
        try:
            con.executescript('BEGIN IMMEDIATE;\n' + SCHEMA_SQL + '\nCOMMIT;')
        except BaseException:
            con.rollback()
            raise
    app.extensions['task_reminders'] = ReminderEngine(app, db)

    @app.errorhandler(ReminderError)
    def reminder_error(error):
        return jsonify(error=error.message, code=error.code), error.status

    def session():
        return ImportSession(app, db, Problem, require_member)

    def hex_id(value, size):
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(size) + '}', value):
            raise ReminderError('提醒或操作编号格式不正确')
        return value

    @app.get('/api/task-reminders')
    def inbox():
        if set(request.args) - {'filter', 'page'} or any(len(request.args.getlist(k)) != 1 for k in request.args):
            raise ReminderError('提醒筛选参数不正确')
        mode, page = request.args.get('filter', 'unread'), request.args.get('page', '0')
        if mode not in ('unread', 'all') or not re.fullmatch(r'0|[1-9][0-9]{0,5}', page):
            raise ReminderError('提醒筛选参数不正确')
        page = int(page); access = session()
        with access.read() as con:
            moment = clock()
            states = {(r['task_id'], r['due']): r for r in con.execute('SELECT * FROM task_reminders WHERE owner=?', (access.owner,))}
            items = []
            for uid, value in live_tasks(con, moment).items():
                if access.owner not in value['recipients']:
                    continue
                items.append({k: value[k] for k in ('task', 'occurrence', 'eligibleAt')} |
                             state_value(states.get((uid, value['task']['due'])), moment))
            items.sort(key=lambda item: (item['task']['due'], item['task']['id']))
            unread = sum(item['status'] == 'unread' for item in items)
            if mode == 'unread': items = [item for item in items if item['status'] == 'unread']
            row = con.execute('SELECT data FROM settings WHERE id=?', (HEARTBEAT,)).fetchone()
            worker = json.loads(row['data']) if row else {'lastCheckedAt': None, 'capacityBlocked': False}
            last = worker['lastCheckedAt']
            worker['stale'] = last is None or not 0 <= (moment - datetime.fromisoformat(last)).total_seconds() <= 60
            result = {'items': items[page*PAGE_SIZE:(page+1)*PAGE_SIZE], 'page': page, 'pageSize': PAGE_SIZE,
                      'total': len(items), 'hasMore': (page+1)*PAGE_SIZE < len(items), 'unreadCount': unread,
                      'serverNow': iso(moment), 'timeZone': TIME_ZONE, 'worker': worker}
        return jsonify(result)

    def normalize(task_id, value):
        if not task_id or len(task_id) > 128 or any(ord(c) < 32 for c in task_id):
            raise ReminderError('任务编号不正确')
        required = {'requestId', 'occurrence', 'revision', 'action'}
        if not isinstance(value, dict) or set(value) not in (required, required | {'snoozedUntil'}):
            raise ReminderError('提醒操作字段不正确')
        hex_id(value['requestId'], 32); hex_id(value['occurrence'], 64)
        if type(value['revision']) is not int or not 0 <= value['revision'] < MAX_REVISION:
            raise ReminderError('提醒版本不正确')
        if value['action'] not in ('read', 'snooze'):
            raise ReminderError('提醒操作不正确')
        result = {**value, 'taskId': task_id}
        if value['action'] == 'read':
            if 'snoozedUntil' in value: raise ReminderError('已读操作不接受暂缓时间')
        else:
            try:
                until = value['snoozedUntil']
                if not isinstance(until, str) or len(until) > 40: raise ValueError()
                parsed = datetime.fromisoformat(until)
                if parsed.tzinfo is None: raise ValueError()
                result['snoozedUntil'] = iso(parsed)
            except (ValueError, KeyError, OverflowError):
                raise ReminderError('暂缓时间须为带时区的有效时间') from None
        return result

    @app.post('/api/task-reminders/<task_id>/actions')
    def action(task_id):
        access = session(); value = normalize(task_id, body())
        intent = hashlib.sha256(packed(value).encode()).hexdigest()
        with access.write() as con:
            old = con.execute('SELECT intent_digest,result FROM task_reminder_operations WHERE owner=? AND request_id=?',
                              (access.owner, value['requestId'])).fetchone()
            if old:
                if old['intent_digest'] != intent:
                    raise ReminderError('此操作编号已用于其他内容', 409, 'reminder_request_conflict')
                result = json.loads(old['result'])
            else:
                moment = clock(); stamp = iso(moment)
                live = live_tasks(con, moment).get(task_id)
                if not live or access.owner not in live['recipients']:
                    raise ReminderError('提醒已不适用，请重新读取', 409, 'reminder_unavailable')
                if live['occurrence'] != value['occurrence']:
                    raise ReminderError('任务截止日期已变化，请重新读取', 409, 'reminder_stale')
                due = live['task']['due']
                key = (access.owner, task_id, due)
                state = con.execute('SELECT * FROM task_reminders WHERE owner=? AND task_id=? AND due=?', key).fetchone()
                if (state['revision'] if state else 0) != value['revision']:
                    raise ReminderError('提醒已更新，请重新读取', 409, 'reminder_stale')
                snooze = value.get('snoozedUntil')
                if snooze and not moment < datetime.fromisoformat(snooze) <= moment + timedelta(days=30):
                    raise ReminderError('暂缓时间须在未来 30 天内')
                capacity(con, 'task_reminder_operations', MAX_OPERATIONS)
                if not state:
                    capacity(con, 'task_reminders', MAX_STATES)
                    con.execute('INSERT INTO task_reminders(owner,task_id,due,created_at,updated_at) VALUES(?,?,?,?,?)', (*key, stamp, stamp))
                read_at = stamp if value['action'] == 'read' else None
                con.execute('UPDATE task_reminders SET read_at=?,snoozed_until=?,revision=revision+1,active=1,updated_at=? '
                            'WHERE owner=? AND task_id=? AND due=?', (read_at, snooze, stamp, *key))
                result = {'requestId': value['requestId'], 'action': value['action'], 'taskId': task_id,
                          'occurrence': value['occurrence'], 'revision': value['revision']+1,
                          'readAt': read_at, 'snoozedUntil': snooze, 'committedAt': stamp}
                con.execute('INSERT INTO task_reminder_operations(owner,request_id,intent_digest,result,created_at) VALUES(?,?,?,?,?)',
                            (access.owner, value['requestId'], intent, packed(result), stamp))
        return jsonify(operation=result)

    @app.get('/api/task-reminders/operations/<request_id>')
    def operation(request_id):
        hex_id(request_id, 32); access = session()
        with access.read() as con:
            row = con.execute('SELECT result FROM task_reminder_operations WHERE owner=? AND request_id=?',
                              (access.owner, request_id)).fetchone()
            if not row:
                raise ReminderError('没有此操作回执', 404, 'reminder_operation_not_found')
            result = json.loads(row['result'])
        return jsonify(operation=result)
