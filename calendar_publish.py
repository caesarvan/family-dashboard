"""Consent-bound durable publication of local journeys to owned cloud calendars.

One process-safe account lock covers token refresh, reads and conditional writes.
Deterministic provider keys recover uncertain creates; pending snapshots recover
uncertain updates. No attendee, invitation, or remote deletion is generated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import ExitStack, contextmanager
import hashlib
import json
import secrets
import time

from flask import g, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from cloud_accounts import AccountBusy, calendar_write_allowed
from cloud_providers import ProviderError


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(pack(value).encode()).hexdigest()


def binding_snapshot(row):
    """Bind delayed work and explicit reviews to one durable queue generation."""
    return digest({key: row[key] for key in ('owner', 'account_id', 'source_id', 'entity_id', 'journey_id',
        'provider', 'calendar_id', 'status', 'review_required', 'remote_id', 'etag', 'last_hash',
        'pending_hash', 'pending_revision', 'pending_data', 'attempts')})


def event_snapshot(value):
    """Only explicitly managed fields can leave the household server."""
    from cloud_providers import _datetime, _iso, _day
    output = {}
    for key, maximum in [('title', 2048), ('location', 2048), ('note', 8000)]:
        item = value.get(key, '')
        if not isinstance(item, str) or len(item) > maximum:
            raise ProviderError('本地日程字段无效，请先编辑日程', 400)
        output[key] = item.strip()
    if not output['title']:
        raise ProviderError('本地日程缺少标题', 400)
    if value.get('allDay') is True and ('startDate' in value or 'endDateExclusive' in value):
        begin, end = _datetime(_day(value.get('startDate'))), _datetime(_day(value.get('endDateExclusive')))
    else:
        begin, end = _datetime(value.get('start')), _datetime(value.get('end'))
    if end <= begin:
        raise ProviderError('本地日程起止日期不正确', 400)
    output.update(start=_iso(begin), end=_iso(end), allDay=value.get('allDay') is True)
    return output


def _local_changes_pending(current, last_hash):
    """Report local divergence, never expose the confirmed event digest."""
    if (not isinstance(current, dict) or not isinstance(last_hash, str) or
            len(last_hash) != 64 or any(char not in '0123456789abcdef' for char in last_hash)):
        return None
    try:
        return digest(event_snapshot(current)) != last_hash
    except (ProviderError, TypeError, ValueError):
        return None


def initialize_publications(con):
    # No FK cascade: removing a local journey/account must leave an auditable
    # publication record, never imply that a remote event was deleted.
    con.executescript('''
    CREATE TABLE IF NOT EXISTS calendar_publications(
      id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), journey_id TEXT NOT NULL,
      entity_id TEXT NOT NULL, source_id TEXT NOT NULL, account_id TEXT NOT NULL,
      provider TEXT NOT NULL, calendar_id TEXT NOT NULL,
      remote_id TEXT NOT NULL DEFAULT '', etag TEXT NOT NULL DEFAULT '',
      last_hash TEXT NOT NULL DEFAULT '', local_revision INTEGER NOT NULL DEFAULT 0,
      pending_data TEXT, pending_hash TEXT NOT NULL DEFAULT '', pending_revision INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
      attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS calendar_publications_due ON calendar_publications(status,next_attempt);
    CREATE INDEX IF NOT EXISTS calendar_publications_owner ON calendar_publications(owner,journey_id);
    CREATE INDEX IF NOT EXISTS calendar_publications_remote ON calendar_publications(source_id,remote_id);
    ''')
    # Separate app/worker processes can initialize the same household at once.
    # Acquire the SQLite writer lock before checking the schema so the second
    # process observes the first migration, rather than issuing duplicate ALTERs.
    con.execute('BEGIN IMMEDIATE')
    try:
        columns = {row[1] for row in con.execute('PRAGMA table_info(calendar_publications)')}
        if 'review_required' not in columns:
            con.execute('ALTER TABLE calendar_publications ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0')
        con.execute("INSERT OR IGNORE INTO settings(id,data) VALUES('calendar_publication_namespace',?)", (pack(secrets.token_hex(24)),))
        con.commit()
    except BaseException:
        con.rollback()
        raise


class CalendarPublicationQueue:
    def __init__(self, app):
        self.app = app
        self.accounts = app.extensions['cloud_accounts']
        with self.accounts.db() as con:
            initialize_publications(con)
            self.namespace = json.loads(con.execute("SELECT data FROM settings WHERE id='calendar_publication_namespace'").fetchone()[0])

    def source(self, con, source_id, owner):
        row = con.execute('SELECT s.* FROM cloud_sources s JOIN cloud_accounts a ON a.id=s.account_id '
                          "WHERE s.id=? AND a.owner=? AND s.kind='calendar'", (source_id, owner)).fetchone()
        if not row:
            raise ProviderError('日历不存在或不属于当前成员，请先在账户设置中选择日历', 404)
        return dict(row)

    def key(self, account, source, entity_id):
        return digest([self.namespace, account['provider'], account['client_id'], account['subject'], source['remote_id'], entity_id])

    def target_digest(self, account, source):
        return digest([account['provider'], account['client_id'], account['subject'], source['remote_id']])

    def journey_events(self, con, journey_id):
        if not con.execute('SELECT 1 FROM journey_workflows WHERE id=?', (journey_id,)).fetchone():
            raise ProviderError('旅行计划不存在', 404)
        rows = con.execute("SELECT e.* FROM journey_links l JOIN entities e ON e.id=l.entity_id WHERE l.journey_id=? AND l.kind='events' ORDER BY e.id", (journey_id,)).fetchall()
        if not rows or len(rows) > 101:
            raise ProviderError('旅行须有 1 至 101 项有效日程（含概览）', 400)
        return [{'id': row['id'], 'revision': row['revision'], **event_snapshot(json.loads(row['data']))} for row in rows]

    def state(self, journey_id, owner):
        with self.accounts.db() as con:
            con.execute('BEGIN')  # Local events and publication hashes must share a snapshot.
            events = self.journey_events(con, journey_id)
            by_id = {event['id']: event for event in events}
            sources = []
            for row in con.execute("SELECT s.*,a.provider,a.name AS account_name,a.tokens,a.needs_reauth FROM cloud_sources s JOIN cloud_accounts a ON a.id=s.account_id WHERE a.owner=? AND s.kind='calendar' ORDER BY a.provider,s.name", (owner,)):
                try:
                    granted = calendar_write_allowed(row['provider'], self.accounts.decrypt(row['tokens']).get('scope'))
                except ProviderError:
                    granted = False
                sources.append({'id': row['id'], 'name': row['name'], 'accountId': row['account_id'], 'provider': row['provider'],
                                'accountName': row['account_name'], 'writeAuthorized': granted and not row['needs_reauth']})
            rows = con.execute('SELECT id,entity_id AS entityId,source_id AS sourceId,provider,status,error,review_required AS reviewRequired,local_revision AS localRevision,updated_at AS updatedAt,last_hash '
                               'FROM calendar_publications WHERE owner=? AND journey_id=? ORDER BY created_at,id', (owner, journey_id)).fetchall()
            records = []
            for row in rows:
                record = dict(row)
                record['localChangesPending'] = _local_changes_pending(by_id.get(record['entityId']), record.pop('last_hash'))
                records.append(record)
        return {'journeyId': journey_id, 'events': events, 'sources': sources, 'publications': records,
                'mode': 'durable_queue', 'note': '确认后持续发布本地日程修改。云端修改冲突会暂停；删除本地计划不会自动删除云端事项。'}

    def _set_error(self, rid, error, attempts):
        if isinstance(error, AccountBusy):
            return
        with self.accounts.db() as con:
            initial = con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone()
        if not initial:
            return
        try:
            with self.accounts.lock(initial['account_id']), self.accounts.db() as con:
                con.execute('BEGIN IMMEDIATE')
                row = con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone()
                if not row or binding_snapshot(row) != binding_snapshot(initial):
                    return
                self._set_error_locked(con, rid, error, attempts, initial['account_id'])
        except AccountBusy:
            return

    def _set_error_locked(self, con, rid, error, attempts, account_id):
        code = error.status
        status = 'needs_authorization' if error.reauth or code == 401 else 'permission_denied' if code == 403 else 'conflict' if code in {404, 409, 412} else 'retry'
        if status == 'retry' and attempts >= 12:
            status = 'error'
        updated = con.execute("UPDATE calendar_publications SET status=?,error=?,attempts=?,next_attempt=?,updated_at=? WHERE id=? AND account_id=? AND review_required=0 AND status IN ('pending','publishing','published','retry','needs_authorization')",
                        (status, error.message[:400], attempts, time.time() + min(3600, 15 * 2 ** min(attempts, 8)), stamp(), rid, account_id))
        if updated.rowcount:
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def process(self, rid):
        with self.accounts.db() as con:
            initial = con.execute('SELECT account_id,attempts FROM calendar_publications WHERE id=?', (rid,)).fetchone()
        if not initial:
            return
        attempts = initial['attempts']
        # Error recording belongs to the same critical section as the failed
        # request. A rebind/review must never race a late error after lock release.
        with ExitStack() as held:
            acquired = False
            try:
                held.enter_context(self.accounts.lock(initial['account_id']))
                acquired = True
                with self.accounts.db() as con:
                    row = con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone()
                    if not row or row['account_id'] != initial['account_id'] or row['review_required'] or row['status'] in {'paused', 'conflict', 'permission_denied', 'error', 'local_deleted', 'needs_review'}:
                        return
                    row = dict(row)
                    attempts = row['attempts']
                    source = self.source(con, row['source_id'], row['owner'])
                    if source['account_id'] != row['account_id']:
                        raise ProviderError('日历绑定已变化，请重新预览', 409)
                    linked = con.execute("SELECT e.* FROM entities e JOIN journey_links l ON l.entity_id=e.id WHERE e.id=? AND l.journey_id=? AND l.kind='events'", (row['entity_id'], row['journey_id'])).fetchone()
                    if not linked:
                        con.execute("UPDATE calendar_publications SET status='local_deleted',error=?,updated_at=? WHERE id=?",
                                    ('本地日程已删除；云端原事项保留，请在日历中核对。', stamp(), rid))
                        return
                    current = event_snapshot(json.loads(linked['data']))
                    check_only = not row['pending_data'] and row['last_hash'] == digest(current)
                    if not row['pending_data'] and not check_only:
                        row.update(pending_data=pack(current), pending_hash=digest(current), pending_revision=linked['revision'])
                        con.execute("UPDATE calendar_publications SET pending_data=?,pending_hash=?,pending_revision=?,status='pending' WHERE id=?",
                                    (row['pending_data'], row['pending_hash'], row['pending_revision'], rid))
                account = self.accounts.account(source['account_id'], row['owner'])
                if self.key(account, source, row['entity_id']) != rid:
                    raise ProviderError('日历身份与原发布不一致，请重新选择目标并预览', 409)
                if not calendar_write_allowed(account['provider'], self.accounts.decrypt(account['tokens']).get('scope')):
                    raise ProviderError('需要本人单独授权日历写入；原有读取同步仍可继续', 401)
                adapter = self.accounts.active_provider(account)
                account = self.accounts.account(source['account_id'], row['owner'])
                if not calendar_write_allowed(account['provider'], self.accounts.decrypt(account['tokens']).get('scope')):
                    raise ProviderError('刷新后的授权未包含日历写权限，请重新授权', 401)
                src = self.accounts.adapter_source(source)
                if check_only:
                    # A stable local revision does not prove the remote event
                    # still exists. Verify it even if polling suppressed its
                    # duplicate mirror or a process restarted between edits.
                    if not row['remote_id']:
                        raise ProviderError('发布记录缺少远端标识，请核对', 409)
                    remote = adapter.get_calendar_publication(src, row['remote_id'])
                    if remote is None:
                        raise ProviderError('云端原事项已删除，持续发布已暂停，请在日历中核对', 409)
                    if remote['key'] != rid or remote['etag'] != row['etag'] or remote['digest'] != row['last_hash'] or event_snapshot(remote['managed']) != current:
                        raise ProviderError('云端事项已变化，持续发布已暂停，请核对两边内容', 409)
                    with self.accounts.db() as con:
                        con.execute("UPDATE calendar_publications SET local_revision=?,next_attempt=?,status='published',error='' WHERE id=?", (linked['revision'], time.time() + 60, rid))
                    return
                if not adapter.calendar_access(src):
                    raise ProviderError('该日历没有编辑权限，请选择本人可编辑的日历', 403)
                with self.accounts.db() as con:
                    con.execute("UPDATE calendar_publications SET status='publishing',next_attempt=?,updated_at=? WHERE id=?", (time.time() + 60, stamp(), rid))
                pending = json.loads(row['pending_data'])
                remote = adapter.get_calendar_publication(src, row['remote_id']) if row['remote_id'] else adapter.find_calendar_publication(src, rid)
                if remote is None and row['remote_id']:
                    raise ProviderError('云端原事项已删除，已暂停更新，不会自动重新创建', 409)
                if remote:
                    if remote['key'] != rid:
                        raise ProviderError('远端标识与本地发布不一致，已暂停以避免覆盖其他事项', 409)
                    if remote['digest'] == row['pending_hash'] and event_snapshot(remote['managed']) == pending:
                        result = remote  # Recover an acknowledged-but-not-recorded write.
                    else:
                        if not row['remote_id'] or not row['etag'] or remote['etag'] != row['etag']:
                            raise ProviderError('云端事项已被修改，已暂停发布；不会覆盖云端内容', 409)
                        result = adapter.update_calendar_publication(src, pending, rid, row['pending_hash'], row['remote_id'], row['etag'])
                else:
                    result = adapter.create_calendar_publication(src, pending, rid, row['pending_hash'])
                if result['key'] != rid or result['digest'] != row['pending_hash'] or event_snapshot(result['managed']) != pending:
                    raise ProviderError('云端返回内容与计划不一致，已暂停，请核对日历', 409)
                with self.accounts.db() as con:
                    con.execute("UPDATE calendar_publications SET remote_id=?,etag=?,last_hash=?,local_revision=?,pending_data=NULL,pending_hash='',pending_revision=0,"
                                "status='published',error='',attempts=0,next_attempt=?,updated_at=? WHERE id=?",
                                (result['id'], result['etag'], row['pending_hash'], row['pending_revision'], time.time() + 30, stamp(), rid))
                    # Remove a mirror that a previous poll materialized before
                    # the successful publication ID was durably recorded.
                    old = con.execute('SELECT entity_id FROM cloud_items WHERE source_id=? AND remote_id=?', (source['id'], result['id'])).fetchone()
                    if old:
                        con.execute('DELETE FROM entities WHERE id=?', (old['entity_id'],))
                    con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
            except ProviderError as exc:
                if acquired and not isinstance(exc, AccountBusy):
                    with self.accounts.db() as con:
                        self._set_error_locked(con, rid, exc, attempts + 1, initial['account_id'])

    def tick(self):
        with self.accounts.db() as con:
            rows = con.execute("SELECT id FROM calendar_publications WHERE status IN ('pending','publishing','published','retry','needs_authorization') AND next_attempt<=? ORDER BY next_attempt,id LIMIT 2", (time.time(),)).fetchall()
        for row in rows:
            self.process(row['id'])
        return len(rows)


def register_calendar_publish(app, db, Problem, body, require_member, audit):
    engine = CalendarPublicationQueue(app)
    app.extensions['calendar_publish'] = engine
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='calendar-publish-v1-' + engine.namespace)

    @contextmanager
    def locked_publication(rid, transaction=False):
        """Never use a freshly rebound row under its previous account's lock."""
        with engine.accounts.db() as con:
            initial = con.execute('SELECT * FROM calendar_publications WHERE id=? AND owner=?', (rid, g.actor['id'])).fetchone()
        if not initial:
            raise Problem('发布记录不存在', 404)
        with engine.accounts.lock(initial['account_id']), engine.accounts.db() as con:
            if transaction:
                con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM calendar_publications WHERE id=? AND owner=?', (rid, g.actor['id'])).fetchone()
            if not row or binding_snapshot(row) != binding_snapshot(initial):
                raise Problem('发布绑定或状态已变化，请刷新后重试', 409)
            yield con, row

    @app.get('/api/calendar-publish/journeys/<journey_id>')
    def publication_state(journey_id):
        require_member()
        return jsonify(engine.state(journey_id, g.actor['id']))

    @app.post('/api/calendar-publish/authorize')
    def publication_authorize():
        require_member()
        account_id = body().get('accountId')
        if not isinstance(account_id, str) or len(account_id) > 100:
            raise Problem('请选择要升级的已绑定账户')
        account = engine.accounts.account(account_id, g.actor['id'])
        if request.host_url.rstrip('/') != engine.accounts.origin:
            raise Problem('请通过 ' + engine.accounts.origin + ' 打开看板后授权')
        return jsonify(url=engine.accounts.authorize(account['provider'], 'bind', g.actor, calendar_write=True, account_id=account_id))

    def preview_payload(payload):
        journey_id, source_id = payload.get('journeyId'), payload.get('sourceId')
        if not isinstance(journey_id, str) or not isinstance(source_id, str) or len(journey_id) > 100 or len(source_id) > 100:
            raise Problem('请选择旅行与日历')
        with engine.accounts.db() as con:
            source = engine.source(con, source_id, g.actor['id'])
            events = engine.journey_events(con, journey_id)
        account = engine.accounts.account(source['account_id'], g.actor['id'])
        return source, {'owner': g.actor['id'], 'journeyId': journey_id, 'sourceId': source_id,
                        'targetDigest': engine.target_digest(account, source), 'eventsDigest': digest(events)}

    @app.post('/api/calendar-publish/preview')
    def publication_preview():
        require_member()
        source, value = preview_payload(body())
        state = engine.state(value['journeyId'], g.actor['id'])
        selected = next(s for s in state['sources'] if s['id'] == source['id'])
        return jsonify(events=state['events'], source=selected, previewToken=signer.dumps(value), expiresInSeconds=900,
                       note='确认将发布这些日程，并持续同步后续本地修改。不添加参与者或发送邀请。云端权限会在执行时再次检查。')

    @app.post('/api/calendar-publish/confirm')
    def publication_confirm():
        require_member()
        payload = body()
        token = payload.get('previewToken')
        if not isinstance(token, str) or len(token) > 3000:
            raise Problem('请先预览待发布的日程')
        try:
            signed = signer.loads(token, max_age=900)
        except BadSignature:
            raise Problem('预览已失效，请重新预览') from None
        source, value = preview_payload(payload)
        if signed != value:
            raise Problem('旅行、日历或当前账户已变化，请重新预览', 409)
        account = engine.accounts.account(source['account_id'], g.actor['id'])
        # A same-identity reconnect changes opaque account/source IDs while the
        # publication key and all uncertainty/review evidence stay stable. Lock
        # both generations, in the same sorted order as travel apply.
        with engine.accounts.db() as con:
            events = engine.journey_events(con, value['journeyId'])
            candidate_ids = [engine.key(account, source, event['id']) for event in events]
            old_accounts = {row['account_id'] for rid in candidate_ids for row in con.execute('SELECT account_id FROM calendar_publications WHERE id=?', (rid,))}
        account_ids = old_accounts | {account['id']}
        with ExitStack() as locks:
            for account_id in sorted(account_ids):
                locks.enter_context(engine.accounts.lock(account_id))
            with engine.accounts.db() as con:
                return confirm_locked(con, account, source, value, account_ids)

    def confirm_locked(con, account, source, value, account_ids):
        con.execute('BEGIN IMMEDIATE')
        # Recheck the signed revision snapshot after acquiring the lock.
        source = engine.source(con, source['id'], g.actor['id'])
        if source['account_id'] != account['id']:
            raise Problem('日历账户已变化，请重新预览', 409)
        fresh_account = engine.accounts.account(source['account_id'], g.actor['id'])
        if any(fresh_account[key] != account[key] for key in ('id', 'provider', 'client_id', 'subject', 'owner')):
            raise Problem('日历账户身份已变化，请重新预览', 409)
        account = fresh_account
        if engine.target_digest(account, source) != value['targetDigest']:
            raise Problem('所选日历目标已变化，请重新预览', 409)
        granted = calendar_write_allowed(account['provider'], engine.accounts.decrypt(account['tokens']).get('scope')) and not account['needs_reauth']
        events = engine.journey_events(con, value['journeyId'])
        if digest(events) != value['eventsDigest']:
            raise Problem('旅行已变化，请重新预览', 409)
        keys = []
        for event in events:
            rid = engine.key(account, source, event['id'])
            keys.append(rid)
            existing = con.execute('SELECT * FROM calendar_publications WHERE id=?', (rid,)).fetchone()
            if existing:
                if existing['owner'] != g.actor['id']:
                    raise Problem('这条云端发布属于另一成员，不能接管其绑定', 409)
                if existing['account_id'] not in account_ids:
                    raise Problem('日历绑定刚刚变化，请重新预览', 409)
                if existing['provider'] != account['provider'] or existing['calendar_id'] != source['remote_id']:
                    raise Problem('所选日历与原发布目标不同，不会迁移原事项', 409)
                # In particular, reselecting a source must not strand a
                # needs_review/paused/conflict row on the deleted source ID.
                con.execute('UPDATE calendar_publications SET source_id=?,account_id=?,next_attempt=CASE WHEN review_required=1 OR status IN (\'conflict\',\'paused\',\'local_deleted\',\'needs_review\') THEN next_attempt ELSE 0 END WHERE id=?',
                            (source['id'], account['id'], rid))
                # A poll on the new source may have created a mirror before
                # explicit reconnection; preserve the original local event.
                if existing['remote_id']:
                    mirrors = con.execute('SELECT entity_id FROM cloud_items WHERE source_id=? AND remote_id=?', (source['id'], existing['remote_id'])).fetchall()
                    for mirror in mirrors:
                        if mirror['entity_id'] != existing['entity_id']:
                            con.execute('DELETE FROM entities WHERE id=?', (mirror['entity_id'],))
                continue
            snapshot = event_snapshot(event)
            con.execute('INSERT INTO calendar_publications(id,owner,journey_id,entity_id,source_id,account_id,provider,calendar_id,pending_data,pending_hash,pending_revision,status,created_at,updated_at) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (rid, g.actor['id'], value['journeyId'], event['id'], source['id'], account['id'], account['provider'], source['remote_id'],
                         pack(snapshot), digest(snapshot), event['revision'], 'pending' if granted else 'needs_authorization', stamp(), stamp()))
        con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
        con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)', (g.actor['id'], 'calendar.publication.confirm', value['journeyId'], stamp()))
        return jsonify(queued=True, publicationIds=keys, needsAuthorization=not granted)

    @app.post('/api/calendar-publish/publications/<rid>/retry')
    def publication_retry(rid):
        require_member()
        with locked_publication(rid, transaction=True) as (con, row):
            if row['review_required'] or row['status'] in {'conflict', 'local_deleted', 'paused', 'needs_review'}:
                raise Problem('这条发布已暂停，需要先核对本地与云端，不会自动覆盖远端修改', 409)
            con.execute("UPDATE calendar_publications SET status='pending',next_attempt=0,attempts=0,error='' WHERE id=?", (rid,))
        return jsonify(queued=True)

    @app.post('/api/calendar-publish/publications/<rid>/pause')
    def publication_pause(rid):
        require_member()
        with locked_publication(rid, transaction=True) as (con, row):
            con.execute("UPDATE calendar_publications SET status='paused',error='',updated_at=? WHERE id=? AND owner=?", (stamp(), rid, g.actor['id']))
        return jsonify(paused=True, note='已停止后续发布，云端已创建的事项保留。')

    @app.post('/api/calendar-publish/publications/<rid>/resume')
    def publication_resume(rid):
        require_member()
        with locked_publication(rid, transaction=True) as (con, row):
            updated = con.execute("UPDATE calendar_publications SET status='pending',next_attempt=0,error='',updated_at=? WHERE id=? AND owner=? AND status='paused' AND review_required=0", (stamp(), rid, g.actor['id']))
            if updated.rowcount != 1:
                raise Problem('仅已停止的发布可以恢复，请刷新状态', 409)
        return jsonify(queued=True, note='已恢复持续发布；云端若已改变仍会暂停核对。')

    @app.post('/api/calendar-publish/publications/<rid>/conflict-preview')
    def publication_conflict_preview(rid):
        require_member()
        with locked_publication(rid) as (con, row):
            if row['status'] != 'conflict' or row['review_required']:
                raise Problem('当前记录没有需要核对的云端冲突', 409)
            source = engine.source(con, row['source_id'], g.actor['id'])
            if source['account_id'] != row['account_id']:
                raise Problem('日历绑定已变化，请重新预览', 409)
            local = con.execute("SELECT e.* FROM entities e JOIN journey_links l ON l.entity_id=e.id WHERE e.id=? AND l.journey_id=? AND l.kind='events'", (row['entity_id'], row['journey_id'])).fetchone()
            if not local:
                raise Problem('本地日程已移除，请在云端核对原事项', 409)
            snapshot = event_snapshot(json.loads(local['data']))
            account = engine.accounts.account(row['account_id'], g.actor['id'])
            adapter = engine.accounts.active_provider(account)
            remote = adapter.get_calendar_publication(engine.accounts.adapter_source(source), row['remote_id']) if row['remote_id'] else adapter.find_calendar_publication(engine.accounts.adapter_source(source), rid)
            if not remote or remote['key'] != rid:
                raise Problem('无法确认这是本平台创建的原事项，请保留云端并停止发布', 409)
            value = {'owner': g.actor['id'], 'publicationId': rid, 'localRevision': local['revision'], 'localDigest': digest(snapshot),
                     'queueBinding': binding_snapshot(row), 'remoteId': remote['id'], 'remoteEtag': remote['etag'], 'remoteDigest': digest(remote['managed'])}
        return jsonify(local=snapshot, remote=remote['managed'], previewToken=signer.dumps(value),
                       note='确认后以这里的本地内容更新该云端事项。若云端再次变化，更新会被拒绝。也可以停止同步并保留云端内容。')

    @app.post('/api/calendar-publish/publications/<rid>/conflict-confirm')
    def publication_conflict_confirm(rid):
        require_member()
        token = body().get('previewToken')
        if not isinstance(token, str) or len(token) > 6000:
            raise Problem('请先核对两边内容')
        try:
            signed = signer.loads(token, max_age=900)
        except BadSignature:
            raise Problem('冲突预览已失效，请重新核对') from None
        if signed.get('owner') != g.actor['id'] or signed.get('publicationId') != rid:
            raise Problem('预览与当前成员或发布记录不匹配', 409)
        with locked_publication(rid, transaction=True) as (con, row):
            if row['status'] != 'conflict' or row['review_required'] or binding_snapshot(row) != signed.get('queueBinding'):
                raise Problem('发布状态已变化，请重新核对', 409)
            source = engine.source(con, row['source_id'], g.actor['id'])
            if source['account_id'] != row['account_id']:
                raise Problem('日历绑定已变化，请重新预览', 409)
            local = con.execute("SELECT e.* FROM entities e JOIN journey_links l ON l.entity_id=e.id WHERE e.id=? AND l.journey_id=? AND l.kind='events'", (row['entity_id'], row['journey_id'])).fetchone()
            if not local or local['revision'] != signed['localRevision']:
                raise Problem('本地日程已变化，请重新核对', 409)
            snapshot = event_snapshot(json.loads(local['data']))
            if digest(snapshot) != signed['localDigest']:
                raise Problem('本地日程已变化，请重新核对', 409)
            con.execute("UPDATE calendar_publications SET remote_id=?,etag=?,pending_data=?,pending_hash=?,pending_revision=?,status='pending',error='',attempts=0,next_attempt=0,updated_at=? WHERE id=?",
                        (signed['remoteId'], signed['remoteEtag'], pack(snapshot), digest(snapshot), local['revision'], stamp(), rid))
            con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)', (g.actor['id'], 'calendar.conflict.confirm', rid, stamp()))
        return jsonify(queued=True)

    def review_binding(row):
        return binding_snapshot(row)

    @app.post('/api/calendar-publish/publications/<rid>/review-preview')
    def publication_review_preview(rid):
        require_member()
        with locked_publication(rid) as (con, row):
            if not row['review_required'] or row['status'] == 'local_deleted':
                raise Problem('发布状态已变化，请重新读取旅行日程', 409)
            source = engine.source(con, row['source_id'], g.actor['id'])
            if source['account_id'] != row['account_id']:
                raise Problem('日历绑定已变化，请重新预览', 409)
            local = con.execute("SELECT e.* FROM entities e JOIN journey_links l ON l.entity_id=e.id WHERE e.id=? AND l.journey_id=? AND l.kind='events'", (row['entity_id'], row['journey_id'])).fetchone()
            if not local:
                raise Problem('本地日程已移除，请在云端核对原事项', 409)
            snapshot = event_snapshot(json.loads(local['data']))
            binding = review_binding(row)
            previous = json.loads(row['pending_data']) if row['pending_data'] else None
            account = engine.accounts.account(row['account_id'], g.actor['id'])
            adapter = engine.accounts.active_provider(account)
            remote = adapter.get_calendar_publication(engine.accounts.adapter_source(source), row['remote_id']) if row['remote_id'] else adapter.find_calendar_publication(engine.accounts.adapter_source(source), rid)
            if remote and remote['key'] != rid:
                raise Problem('远端标识与原发布不一致，请保留云端并停止发布', 409)
            claims = {'owner': g.actor['id'], 'publicationId': rid, 'queueBinding': binding,
                      'localRevision': local['revision'], 'localDigest': digest(snapshot),
                      'remoteId': remote['id'] if remote else '', 'remoteEtag': remote['etag'] if remote else '',
                      'remoteDigest': digest(remote['managed']) if remote else None}
        return jsonify(local=snapshot, previous=previous, remote=remote['managed'] if remote else None,
                       previewToken=signer.dumps(claims), expiresInSeconds=900,
                       note='旅行时间或类型已变化。确认后才恢复发布；云端若再次变化会暂停。未找到云端事项时，将用原发布标识核对后创建。')

    @app.post('/api/calendar-publish/publications/<rid>/review-confirm')
    def publication_review_confirm(rid):
        require_member()
        token = body().get('previewToken')
        if not isinstance(token, str) or len(token) > 6000:
            raise Problem('请先核对旅行时间变化')
        try:
            signed = signer.loads(token, max_age=900)
        except BadSignature:
            raise Problem('时间变化预览已失效，请重新核对') from None
        if signed.get('owner') != g.actor['id'] or signed.get('publicationId') != rid:
            raise Problem('预览与当前成员或发布记录不匹配', 409)
        with locked_publication(rid, transaction=True) as (con, row):
            if not row['review_required'] or row['status'] == 'local_deleted' or review_binding(row) != signed.get('queueBinding'):
                raise Problem('发布状态已变化，请重新核对', 409)
            source = engine.source(con, row['source_id'], g.actor['id'])
            if source['account_id'] != row['account_id']:
                raise Problem('日历绑定已变化，请重新预览', 409)
            local = con.execute("SELECT e.* FROM entities e JOIN journey_links l ON l.entity_id=e.id WHERE e.id=? AND l.journey_id=? AND l.kind='events'", (row['entity_id'], row['journey_id'])).fetchone()
            if not local or local['revision'] != signed.get('localRevision'):
                raise Problem('本地日程已变化，请重新核对', 409)
            snapshot = event_snapshot(json.loads(local['data']))
            if digest(snapshot) != signed.get('localDigest'):
                raise Problem('本地日程已变化，请重新核对', 409)
            con.execute("UPDATE calendar_publications SET remote_id=?,etag=?,pending_data=?,pending_hash=?,pending_revision=?,review_required=0,status='pending',error='',attempts=0,next_attempt=0,updated_at=? WHERE id=?",
                        (signed['remoteId'], signed['remoteEtag'], pack(snapshot), digest(snapshot), local['revision'], stamp(), rid))
            con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)', (g.actor['id'], 'calendar.timing.confirm', rid, stamp()))
        return jsonify(queued=True)
