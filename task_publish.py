"""Explicit local-task publication with conservative uncertain-create recovery.

The local entity is canonical for ownership/workflow linkage. No cloud mirror is
created for a linked task. Remote completion alone flows back; other changes are
reviewed. A POST which might have succeeded is never blindly repeated.
"""
from __future__ import annotations

from datetime import date
from contextlib import ExitStack
import json
import secrets
import time

from flask import g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from calendar_publish import digest, pack, stamp, publication_capture, publication_current, publication_requests
from cloud_accounts import AccountBusy, task_write_allowed
from cloud_providers import ProviderError

ACTIVE = {'pending', 'publishing', 'published', 'retry', 'uncertain'}
NOTE = ('仅同步本次勾选的待办，确认后持续同步标题、截止日期、备注及完成状态。'
        '负责人和旅行关联保留在看板；不会在云端指派他人。云端仅完成状态变化会自动回流，'
        '其他云端修改先暂停并对比。断开来源或删除任一端，另一端内容保留。'
        '云端备注末尾包含恢复关联标识，请保留该标识。')


def task_snapshot(value):
    output = {}
    for key, maximum in [('title', 100), ('note', 500)]:
        text = value.get(key, '')
        if not isinstance(text, str) or len(text) > maximum:
            raise ProviderError('待办标题最多 100 字，备注最多 500 字，请先调整', 400)
        output[key] = text.strip()
    due = value.get('due', '')
    if not isinstance(due, str):
        raise ProviderError('截止日期无效', 400)
    if due:
        try:
            if date.fromisoformat(due).isoformat() != due:
                raise ValueError()
        except ValueError:
            raise ProviderError('截止日期须为 YYYY-MM-DD', 400) from None
    if not output['title'] or not isinstance(value.get('done', False), bool):
        raise ProviderError('待办标题或完成状态无效', 400)
    output.update(due=due, done=value.get('done', False))
    return output


def _local_changes_pending(current_data, baseline_data):
    """Compare managed fields only; invalid/missing evidence is not equality."""
    try:
        current, baseline = json.loads(current_data), json.loads(baseline_data)
        if (not isinstance(current, dict) or current.get('sync') or
                not isinstance(baseline, dict) or
                not {'title', 'note', 'due', 'done'} <= baseline.keys()):
            return None
        return task_snapshot(current) != task_snapshot(baseline)
    except (ProviderError, TypeError, ValueError):
        return None


def ids_checked(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 100 or
            any(not isinstance(i, str) or not 1 <= len(i) <= 128 for i in value) or len(set(value)) != len(value)):
        raise ProviderError('请明确选择 1 至 100 项不同的本地待办', 400)
    return sorted(value)


class TaskPublicationQueue:
    def __init__(self, app):
        self.app, self.accounts = app, app.extensions['cloud_accounts']
        with self.accounts.db() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS task_publications(
              id TEXT PRIMARY KEY, entity_id TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
              source_id TEXT NOT NULL, account_id TEXT NOT NULL, account_owner TEXT NOT NULL,
              provider TEXT NOT NULL, list_id TEXT NOT NULL, journey_id TEXT NOT NULL DEFAULT '',
              target_key TEXT NOT NULL DEFAULT '', previous_status TEXT NOT NULL DEFAULT '',
              remote_id TEXT NOT NULL DEFAULT '', etag TEXT NOT NULL DEFAULT '',
              baseline_data TEXT, pending_data TEXT, pending_revision INTEGER NOT NULL DEFAULT 0,
              attempted INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
              error TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS task_publications_due ON task_publications(status,next_attempt);
            CREATE INDEX IF NOT EXISTS task_publications_remote ON task_publications(source_id,remote_id);
            ''')
            columns = {r[1] for r in con.execute('PRAGMA table_info(task_publications)')}
            for column in ('target_key', 'previous_status'):
                if column not in columns:
                    con.execute(f"ALTER TABLE task_publications ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            con.execute("INSERT OR IGNORE INTO settings(id,data) VALUES('task_publication_namespace',?)", (pack(secrets.token_hex(24)),))
            self.namespace = json.loads(con.execute("SELECT data FROM settings WHERE id='task_publication_namespace'").fetchone()[0])

    def worker_capture(self, con, rid):
        return publication_capture(con, con.execute('SELECT * FROM task_publications WHERE id=?', (rid,)).fetchone(), 'task')

    def worker_ready(self, row):
        with self.accounts.db() as con:
            con.execute('BEGIN')
            return publication_current(con, row, 'task')

    def source(self, con, sid, actor):
        if not isinstance(sid, str) or len(sid) > 128:
            raise ProviderError('请选择本人清单或家庭主清单', 400)
        row = con.execute("SELECT s.*,a.owner AS account_owner,a.provider,a.client_id,a.subject,a.name AS account_name,a.tokens,a.needs_reauth "
                          "FROM cloud_sources s JOIN cloud_accounts a ON a.id=s.account_id "
                          "WHERE s.id=? AND s.kind='tasks' AND (a.owner=? OR s.is_primary=1)", (sid, actor)).fetchone()
        if not row:
            raise ProviderError('来源已断开、家庭主清单授权已撤回，或该清单不属于本人', 404)
        return dict(row)

    @staticmethod
    def target_key(source):
        return digest([source['provider'], source['client_id'], source['subject'], source['remote_id']])

    def review_tasks(self, con, ids, source, actor):
        tasks = self.tasks(con, ids)
        for task in tasks:
            old = con.execute('SELECT * FROM task_publications WHERE entity_id=?', (task['id'],)).fetchone()
            reconnect = bool(old and old['status'] == 'disconnected' and old['target_key'] == self.target_key(source))
            if old and old['target_key'] and old['target_key'] != self.target_key(source):
                raise ProviderError('待办绑定的原授权账户或清单与当前目标不同，不能重连到其他目标', 409)
            if old and old['source_id'] != source['id'] and not reconnect:
                raise ProviderError('有待办已连接另一份清单；只可重新连接原授权账户的同一清单', 409)
            if reconnect and actor not in {old['owner'], old['account_owner'], source['account_owner']}:
                raise ProviderError('请由原确认成员或账户拥有者重新连接', 403)
            task['reconnect'] = reconnect
        return tasks

    def source_view(self, row):
        try:
            granted = task_write_allowed(row['provider'], self.accounts.decrypt(row['tokens']).get('scope')) and not row['needs_reauth']
        except ProviderError:
            granted = False
        return {'id': row['id'], 'name': row['name'], 'provider': row['provider'], 'accountName': row['account_name'],
                'accountOwner': row['account_owner'], 'primary': bool(row['is_primary']), 'writeAuthorized': granted}

    def tasks(self, con, ids):
        output = []
        for uid in ids_checked(ids):
            row = con.execute("SELECT * FROM entities WHERE id=? AND kind='tasks'", (uid,)).fetchone()
            if not row or json.loads(row['data']).get('sync'):
                raise ProviderError('所选待办已移除或已是云端清单任务，请刷新后重新选择', 409)
            value = json.loads(row['data'])
            output.append({'id': uid, 'revision': row['revision'], 'owner': value.get('owner', 'shared'),
                           'tripId': value.get('tripId', ''), 'journeyId': value.get('journeyId', ''), **task_snapshot(value)})
        return output

    def state(self, actor, journey_id='', ids=None):
        show_all = not journey_id and ids is None
        with self.accounts.db() as con:
            con.execute('BEGIN')  # One read snapshot for local items and confirmed baselines.
            if journey_id:
                if len(journey_id) > 128 or not con.execute('SELECT 1 FROM journey_workflows WHERE id=?', (journey_id,)).fetchone():
                    raise ProviderError('旅行计划不存在', 404)
                ids = [r[0] for r in con.execute("SELECT entity_id FROM journey_links WHERE journey_id=? AND kind='tasks' ORDER BY entity_id", (journey_id,))]
            elif ids is None:
                ids = [r['id'] for r in con.execute("SELECT id,data FROM entities WHERE kind='tasks' ORDER BY updated_at DESC LIMIT 500") if not json.loads(r['data']).get('sync')][:100]
            tasks = self.tasks(con, ids) if ids else []
            source_rows = list(con.execute("SELECT s.*,a.owner AS account_owner,a.provider,a.client_id,a.subject,a.name AS account_name,a.tokens,a.needs_reauth "
                       "FROM cloud_sources s JOIN cloud_accounts a ON a.id=s.account_id WHERE s.kind='tasks' AND (a.owner=? OR s.is_primary=1) ORDER BY s.is_primary DESC,s.name", (actor,)))
            sources = [self.source_view(r) for r in source_rows]
            records = [dict(r) for r in con.execute("SELECT p.id,p.entity_id AS entityId,p.source_id AS sourceId,p.provider,p.status,p.error,p.owner,p.target_key,p.account_owner AS accountOwner,p.updated_at AS updatedAt,p.baseline_data,e.data AS current_data FROM task_publications p LEFT JOIN entities e ON e.id=p.entity_id AND e.kind='tasks' ORDER BY p.created_at DESC LIMIT 2000")]
            for record in records:
                record['localChangesPending'] = _local_changes_pending(record.pop('current_data'), record.pop('baseline_data'))
                record['reconnectSourceIds'] = [s['id'] for s in source_rows if record['status'] == 'disconnected' and record['target_key'] == self.target_key(s) and actor in {record['owner'], record['accountOwner'], s['account_owner']}]
                del record['target_key']
            selected = {r['id'] for r in tasks}
            records = [r | {'canManage': actor in {r['owner'], r['accountOwner']}} for r in records if show_all or r['entityId'] in selected]
        return {'tasks': tasks, 'sources': sources, 'publications': records, 'journeyId': journey_id, 'note': NOTE, 'intervalSeconds': 30}

    def observe(self, con, source, record):
        """Suppress mirrors even when a create response was lost before storing ID."""
        row = con.execute('SELECT * FROM task_publications WHERE source_id=? AND (remote_id=? OR id=?)',
                          (source['id'], record['id'], record.get('publicationKey', ''))).fetchone()
        if not row:
            return None
        if publication_capture(con, row, 'task') is None:
            # Preserve suppression of the old mirror without accepting any
            # publication or local-entity mutation for an inactive principal.
            return row['entity_id'], False
        # A local deletion must not resurrect a cloud mirror on the next poll.
        old = con.execute('SELECT entity_id FROM cloud_items WHERE source_id=? AND remote_id=?', (source['id'], record['id'])).fetchone()
        if old and old['entity_id'] != row['entity_id']:
            con.execute('DELETE FROM entities WHERE id=?', (old['entity_id'],))
        if row['status'] == 'published' and record['version'] != row['etag']:
            con.execute('UPDATE task_publications SET next_attempt=0 WHERE id=?', (row['id'],))
        return row['entity_id'], bool(old)

    def set_status(self, rid, status, message='', delay=30, captured=None):
        with self.accounts.db() as con:
            con.execute('BEGIN IMMEDIATE')
            current = self.worker_capture(con, rid)
            if not current or current['status'] not in ACTIVE or (captured and not publication_current(con, captured, 'task')):
                return
            con.execute('UPDATE task_publications SET status=?,error=?,next_attempt=?,updated_at=? WHERE id=?',
                        (status, message[:400], time.time() + delay, stamp(), rid))
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def fail(self, rid, error, captured=None):
        if isinstance(error, AccountBusy):
            return
        with self.accounts.db() as con:
            con.execute('BEGIN')
            original = captured or self.worker_capture(con, rid)
        if not original:
            return
        try:
            with self.accounts.lock(original['account_id']):
                self._fail_locked(rid, error, original['account_id'], original)
        except AccountBusy:
            return

    def _fail_locked(self, rid, error, account_id, captured):
        with self.accounts.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM task_publications WHERE id=?', (rid,)).fetchone()
            # An explicit pause/disconnect that won the lock after the failed
            # request must not be resurrected by its late error handler.
            if not publication_current(con, captured, 'task') or row['status'] not in ACTIVE or row['account_id'] != account_id:
                return
            attempts = row['attempts'] + 1
            con.execute('UPDATE task_publications SET attempts=? WHERE id=?', (attempts, rid))
            if getattr(error, 'create_rejected', False) and not row['remote_id']:
                con.execute('UPDATE task_publications SET attempted=0 WHERE id=?', (rid,))
            code = getattr(error, 'upstream_status', error.status)
            status = ('needs_authorization' if error.reauth or code == 401 else 'permission_denied' if code == 403 else
                      ('remote_deleted' if row['remote_id'] else 'permission_denied') if code == 404 else 'conflict' if code in {409, 412} else
                      'uncertain' if row['attempted'] and not row['remote_id'] else 'retry')
            if attempts >= 12 and status in {'retry', 'uncertain'}:
                status = 'needs_review'
            con.execute('UPDATE task_publications SET status=?,error=?,next_attempt=?,updated_at=? WHERE id=?',
                        (status, error.message[:400], time.time() + min(1800, 15 * 2 ** min(attempts, 7)), stamp(), rid))
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def accept(self, row, result, pending, revision):
        if result['key'] != row['id'] or result['managed'] != pending:
            raise ProviderError('云端回读与本次待办内容不一致，请核对两边内容', 409)
        with self.accounts.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if not publication_current(con, row, 'task'):
                return
            con.execute("UPDATE task_publications SET remote_id=?,etag=?,baseline_data=?,pending_data=NULL,pending_revision=0,status='published',error='',attempts=0,next_attempt=?,updated_at=? WHERE id=?",
                        (result['id'], result['etag'], pack(pending), time.time() + 30, stamp(), row['id']))
            old = con.execute('SELECT entity_id FROM cloud_items WHERE source_id=? AND remote_id=?', (row['source_id'], result['id'])).fetchone()
            if old and old['entity_id'] != row['entity_id']:
                con.execute('DELETE FROM entities WHERE id=?', (old['entity_id'],))
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def adapter(self, source):
        account = self.accounts.account(source['account_id'], source['account_owner'])
        if not task_write_allowed(account['provider'], self.accounts.decrypt(account['tokens']).get('scope')):
            raise ProviderError('账户缺少待办写权限，请由账户拥有者在设置中重新绑定', 401)
        adapter = self.accounts.active_provider(account)
        fresh = self.accounts.account(source['account_id'], source['account_owner'])
        if not task_write_allowed(fresh['provider'], self.accounts.decrypt(fresh['tokens']).get('scope')):
            raise ProviderError('刷新后的授权缺少待办写权限，请重新绑定', 401)
        return adapter

    def process(self, rid):
        with self.accounts.db() as con:
            con.execute('BEGIN')
            initial = self.worker_capture(con, rid)
        if not initial:
            return
        captured = initial
        try:
            with self.accounts.lock(initial['account_id']), ExitStack() as held:
                with self.accounts.db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    if not publication_current(con, initial, 'task'):
                        return
                    row = dict(con.execute('SELECT * FROM task_publications WHERE id=?', (rid,)).fetchone())
                    if row['status'] not in ACTIVE:
                        return
                    try:
                        source = self.source(con, row['source_id'], row['owner'])
                        if row['target_key'] and row['target_key'] != self.target_key(source):
                            raise ProviderError('原清单身份已变化', 409)
                    except ProviderError:
                        con.execute("UPDATE task_publications SET previous_status=status,status='disconnected',error='来源已断开或主清单共享已撤回，本地任务保留' WHERE id=?", (rid,))
                        return
                    local = con.execute("SELECT * FROM entities WHERE id=? AND kind='tasks'", (row['entity_id'],)).fetchone()
                    if not local:
                        con.execute("UPDATE task_publications SET status='local_deleted',error='本地任务已删除，云端原任务保留' WHERE id=?", (rid,))
                        return
                    current = task_snapshot(json.loads(local['data']))
                if not self.worker_ready(captured):
                    return
                adapter, src = self.adapter(source), self.accounts.adapter_source(source)
                held.enter_context(publication_requests(adapter, lambda: self.worker_ready(captured)))
                if not self.worker_ready(captured):
                    return
                remote = adapter.get_task_publication(src, row['remote_id']) if row['remote_id'] else adapter.find_task_publication(src, rid)
                pending = json.loads(row['pending_data']) if row['pending_data'] else None
                if not remote:
                    if row['attempted']:
                        # A timeout does not prove non-creation. Recovery only;
                        # explicit retry still must not send another POST.
                        raise ProviderError('创建结果尚不确定，正在按关联标识核对；不会重复创建。请在原清单检查，稍后可再次核对。', 502)
                    pending = pending or current
                    with self.accounts.db() as con:
                        con.execute('BEGIN IMMEDIATE')
                        if not publication_current(con, captured, 'task'):
                            return
                        con.execute("UPDATE task_publications SET attempted=1,pending_data=?,pending_revision=?,status='publishing' WHERE id=?", (pack(pending), local['revision'], rid))
                        captured = self.worker_capture(con, rid)
                    if not self.worker_ready(captured):
                        return
                    result = adapter.create_task_publication(src, pending, rid)
                    self.accept(captured, result, pending, local['revision'])
                    return
                if remote['key'] != rid:
                    raise ProviderError('云端关联标识已更改，请核对；不会覆盖此任务', 409)
                if pending and remote['managed'] == pending:
                    self.accept(captured, remote, pending, local['revision'])
                    return
                if not row['baseline_data']:
                    # Found the uncertain POST, but the remote changed before
                    # acknowledgement. Record identity so conflict UI can read it.
                    with self.accounts.db() as con:
                        con.execute('BEGIN IMMEDIATE')
                        if not publication_current(con, captured, 'task'):
                            return
                        con.execute('UPDATE task_publications SET remote_id=?,etag=? WHERE id=?', (remote['id'], remote['etag'], rid))
                        captured = self.worker_capture(con, rid)
                    raise ProviderError('已找回云端任务，但内容已变化，请对比确认', 409)
                baseline = json.loads(row['baseline_data'])
                if pending:
                    # Pending update has an explicit captured ETag, also used by
                    # conflict-confirm. A different ETag must never be rebased.
                    if remote['etag'] != row['etag']:
                        raise ProviderError('云端再次变更，已暂停更新，请重新对比', 409)
                elif remote['managed'] != baseline:
                    remote_value = remote['managed']
                    only_done = all(remote_value[k] == baseline[k] for k in ('title', 'due', 'note'))
                    if only_done and current == baseline:
                        with self.accounts.db() as con:
                            con.execute('BEGIN IMMEDIATE')
                            if not publication_current(con, captured, 'task'):
                                return
                            fresh = con.execute('SELECT * FROM entities WHERE id=?', (row['entity_id'],)).fetchone()
                            if not fresh or fresh['revision'] != local['revision']:
                                raise ProviderError('本地与云端同时修改，请对比后处理', 409)
                            value = json.loads(fresh['data']); value['done'] = remote_value['done']
                            changed = con.execute('UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?', (pack(value), stamp(), row['entity_id'], fresh['revision']))
                            if changed.rowcount != 1:
                                raise ProviderError('本地与云端同时修改，请对比后处理', 409)
                            con.execute("UPDATE task_publications SET remote_id=?,etag=?,baseline_data=?,pending_data=NULL,pending_revision=0,status='published',error='',attempts=0,next_attempt=?,updated_at=? WHERE id=?",
                                        (remote['id'], remote['etag'], pack(remote_value), time.time() + 30, stamp(), rid))
                            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
                        return
                    raise ProviderError('云端标题、日期或备注已变更，或两边同时修改，请对比后处理', 409)
                elif current == baseline:
                    self.accept(captured, remote, baseline, local['revision'])
                    return
                else:
                    pending = current
                    with self.accounts.db() as con:
                        con.execute('BEGIN IMMEDIATE')
                        if not publication_current(con, captured, 'task'):
                            return
                        con.execute("UPDATE task_publications SET pending_data=?,pending_revision=?,etag=?,status='publishing' WHERE id=?", (pack(pending), local['revision'], remote['etag'], rid))
                        captured = self.worker_capture(con, rid)
                    row['etag'] = remote['etag']
                if not self.worker_ready(captured):
                    return
                result = adapter.update_task_publication(src, pending, rid, remote['id'], row['etag'])
                self.accept(captured, result, pending, local['revision'])
        except ProviderError as error:
            self.fail(rid, error, captured)
        except Exception:
            self.app.logger.error('Task publication failed; provider payload omitted')
            self.fail(rid, ProviderError('待办同步响应异常，保留原内容并等待核对', 502), captured)

    def tick(self):
        with self.accounts.db() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM task_publications WHERE status IN ('pending','publishing','published','retry','uncertain') AND next_attempt<=? ORDER BY next_attempt LIMIT 24", (time.time(),))]
        for rid in ids:
            self.process(rid)


def register_task_publish(app, db, Problem, body, require_member, audit):
    engine = TaskPublicationQueue(app)
    app.extensions['task_publish'] = engine
    signer = URLSafeTimedSerializer(app.secret_key, salt='task-publication-v1|' + engine.namespace)

    def signed(value, purpose):
        token = value.get('previewToken')
        if not isinstance(token, str) or len(token) > 16000:
            raise Problem('请先预览并确认待办')
        try:
            result = signer.loads(token, max_age=900)
        except BadSignature:
            raise Problem('预览已过期，请重新预览') from None
        if not isinstance(result, dict) or result.get('owner') != g.actor['id'] or result.get('purpose') != purpose:
            raise Problem('预览不属于当前成员或操作', 409)
        return result

    def publication(con, rid):
        row = con.execute('SELECT * FROM task_publications WHERE id=? AND (owner=? OR account_owner=?)', (rid, g.actor['id'], g.actor['id'])).fetchone()
        if not row:
            raise Problem('发布记录不存在或不属于本人', 404)
        return dict(row)

    @app.get('/api/task-publish/state')
    def task_publication_state():
        require_member()
        ids = request.args.get('entityIds')
        return jsonify(engine.state(g.actor['id'], request.args.get('journeyId', ''), ids.split(',') if ids else None))

    @app.post('/api/task-publish/preview')
    def task_publication_preview():
        require_member(); value = body()
        with engine.accounts.db() as con:
            source = engine.source(con, value.get('sourceId'), g.actor['id'])
            tasks = engine.review_tasks(con, value.get('entityIds'), source, g.actor['id'])
            token = signer.dumps({'purpose': 'publish', 'owner': g.actor['id'], 'sourceId': source['id'],
                                  'accountId': source['account_id'], 'taskIds': [t['id'] for t in tasks], 'digest': digest([{k: v for k, v in t.items() if k != 'reconnect'} for t in tasks])})
        return jsonify(tasks=tasks, source=engine.source_view(source), previewToken=token, note=NOTE)

    @app.post('/api/task-publish/confirm')
    def task_publication_confirm():
        require_member(); value = signed(body(), 'publish')
        with engine.accounts.db() as con:
            source = engine.source(con, value['sourceId'], g.actor['id'])
        with engine.accounts.lock(source['account_id']), engine.accounts.db() as con:
            con.execute('BEGIN IMMEDIATE')
            source = engine.source(con, value['sourceId'], g.actor['id'])
            tasks = engine.review_tasks(con, value['taskIds'], source, g.actor['id'])
            if source['account_id'] != value['accountId'] or digest([{k: v for k, v in t.items() if k != 'reconnect'} for t in tasks]) != value['digest']:
                raise Problem('待办或来源已改变，请重新预览', 409)
            granted = engine.source_view(source)['writeAuthorized']; ids = []
            for task in tasks:
                rid = digest([engine.namespace, task['id']])
                old = con.execute('SELECT * FROM task_publications WHERE entity_id=?', (task['id'],)).fetchone()
                if old:
                    if task['reconnect']:
                        restored = old['previous_status'] if old['previous_status'] in {'conflict', 'remote_deleted', 'local_deleted', 'paused'} else ('pending' if granted else 'needs_authorization')
                        con.execute('UPDATE task_publications SET source_id=?,account_id=?,account_owner=?,owner=?,status=?,previous_status=?,error=?,next_attempt=0,updated_at=? WHERE id=?',
                                    (source['id'], source['account_id'], source['account_owner'], g.actor['id'], restored, '', '原清单已重连，请继续核对之前的冲突或暂停状态' if restored not in {'pending', 'needs_authorization'} else '', stamp(), old['id']))
                    ids.append(old['id']); continue
                con.execute('INSERT INTO task_publications(id,entity_id,owner,source_id,account_id,account_owner,provider,list_id,journey_id,target_key,pending_data,pending_revision,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (rid, task['id'], g.actor['id'], source['id'], source['account_id'], source['account_owner'], source['provider'], source['remote_id'], task['journeyId'], engine.target_key(source), pack(task_snapshot(task)), task['revision'], 'pending' if granted else 'needs_authorization', stamp(), stamp()))
                ids.append(rid)
            con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)', (g.actor['id'], 'tasks.publish.confirm', source['id'], stamp()))
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
        return jsonify(queued=True, publicationIds=ids, needsAuthorization=not granted)

    @app.post('/api/task-publish/publications/<rid>/<action>')
    def task_publication_action(rid, action):
        require_member()
        if action not in {'pause', 'resume', 'retry', 'conflict-preview', 'conflict-confirm'}:
            raise Problem('操作不存在', 404)
        value = body()
        with engine.accounts.db() as con:
            con.execute('BEGIN')
            row = publication(con, rid)
            captured = publication_capture(con, row, 'task')
            if not captured:
                raise Problem('发布成员或云账户已不可用，请重新核对', 409)
        locked_account = row['account_id']
        with engine.accounts.lock(locked_account):
            with engine.accounts.db() as con:
                con.execute('BEGIN IMMEDIATE')
                row = publication(con, rid)
                if row['account_id'] != locked_account or not publication_current(con, captured, 'task'):
                    raise Problem('原账户已重新连接，请刷新后再操作', 409)
                if action == 'pause':
                    if row['status'] in {'disconnected', 'remote_deleted', 'local_deleted'}:
                        raise Problem('此绑定已断开或有删除，请先核对原清单', 409)
                    con.execute("UPDATE task_publications SET status='paused',error='',updated_at=? WHERE id=?", (stamp(), rid))
                    return jsonify(paused=True)
                if action in {'resume', 'retry'}:
                    permitted = {'paused'} if action == 'resume' else {'retry', 'uncertain', 'needs_review', 'needs_authorization', 'permission_denied', 'disconnected'}
                    if row['status'] not in permitted:
                        raise Problem('当前状态须先核对冲突，不能直接重新发布', 409)
                    engine.source(con, row['source_id'], row['owner'])
                    con.execute("UPDATE task_publications SET status='pending',attempts=0,error='',next_attempt=0,updated_at=? WHERE id=?", (stamp(), rid))
                    return jsonify(queued=True)
                if row['status'] != 'conflict':
                    raise Problem('当前没有需要核对的冲突', 409)
                source = engine.source(con, row['source_id'], row['owner'])
                local = con.execute('SELECT * FROM entities WHERE id=?', (row['entity_id'],)).fetchone()
                if not local:
                    raise Problem('本地任务已删除，云端任务仍保留', 409)
                current = task_snapshot(json.loads(local['data']))
            adapter = engine.adapter(source)
            with publication_requests(adapter, lambda: engine.worker_ready(captured)):
                remote = adapter.get_task_publication(engine.accounts.adapter_source(source), row['remote_id']) if row['remote_id'] else adapter.find_task_publication(engine.accounts.adapter_source(source), rid)
            if not engine.worker_ready(captured):
                raise Problem('发布绑定或成员状态已变化，请重新核对', 409)
            if not remote or remote['key'] != rid:
                raise Problem('无法确认云端关联任务，请停止同步并在原清单核对', 409)
            binding = {'purpose': 'conflict', 'owner': g.actor['id'], 'publicationId': rid, 'localRevision': local['revision'],
                       'localDigest': digest(current), 'remoteDigest': digest(remote['managed']), 'remoteEtag': remote['etag'], 'remoteId': remote['id']}
            if action == 'conflict-preview':
                return jsonify(local=current, remote=remote['managed'], previewToken=signer.dumps(binding))
            confirmed = signed(value, 'conflict')
            if confirmed != binding:
                raise Problem('本地或云端已再次修改，请重新对比', 409)
            resolution = value.get('resolution')
            if resolution not in {'local', 'remote'}:
                raise Problem('请选择保留本地或采用云端内容')
            with engine.accounts.db() as con:
                con.execute('BEGIN IMMEDIATE')
                if not publication_current(con, captured, 'task'):
                    raise Problem('发布绑定或成员状态已变化，请重新核对', 409)
                fresh = con.execute('SELECT * FROM entities WHERE id=?', (row['entity_id'],)).fetchone()
                if not fresh or fresh['revision'] != local['revision']:
                    raise Problem('本地任务已改变，请重新对比', 409)
                if resolution == 'remote':
                    adopted = task_snapshot(remote['managed'])
                    original = json.loads(fresh['data']); original.update(adopted)
                    con.execute('UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=?', (pack(original), stamp(), row['entity_id']))
                    con.execute("UPDATE task_publications SET remote_id=?,etag=?,baseline_data=?,pending_data=NULL,status='published',error='',next_attempt=?,updated_at=? WHERE id=?", (remote['id'], remote['etag'], pack(adopted), time.time() + 30, stamp(), rid))
                else:
                    con.execute("UPDATE task_publications SET remote_id=?,etag=?,baseline_data=?,pending_data=?,pending_revision=?,status='pending',error='',next_attempt=0,updated_at=? WHERE id=?", (remote['id'], remote['etag'], pack(remote['managed']), pack(current), local['revision'], stamp(), rid))
                con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)', (g.actor['id'], 'tasks.conflict.' + resolution, rid, stamp()))
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
            return jsonify(queued=resolution == 'local', adopted=resolution == 'remote')
