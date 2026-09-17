"""Private selected photo library: explicit registration, transactions and worker CAS.

No provider HTTP or file storage. All provider/decoder work happens outside this
engine's SQLite transactions, using the public claim/complete protocol.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import secrets
import time

from flask import Response, g, jsonify, request

from cloud_accounts import photos_allowed
from media_crypto import MediaCipher, MediaCryptoError
from media_images import Preview
from journey_time import TimeIssue, date_only, zone


CONSENT_VERSION = 'media-v1'
MAX_SELECTION = 20
OWNER_BYTES = 100 * 1024 * 1024
HOUSEHOLD_BYTES = 200 * 1024 * 1024
ITEM_RESERVATION = 3 * 1024 * 1024
LEASE_SECONDS = 600
ACTIVE = ('queued', 'creating', 'waiting_selection', 'listing', 'staging', 'awaiting_confirmation')
ITEM_VIEW = 'id,owner,account_id,import_id,source_key,state,visibility,journey_id,revision,metadata_cipher,preview_key,created_at,updated_at,confirmed_at,deleted_at,delete_revision'
ERRORS = {
    'invalid_input': (400, '媒体请求格式不正确'),
    'not_found': (404, '媒体记录不存在'),
    'forbidden': (403, '此操作仅限照片拥有者'),
    'unauthorized': (401, '登录状态已变化，请重新登录'),
    'conflict': (409, '记录已变化，请刷新核对后重试'),
    'gone': (410, '此操作已结束，请重新选择'),
    'quota': (429, '媒体数量或存储额度已达上限，请清理后重试'),
    'consent_required': (400, '请明确同意本次媒体用途'),
    'reauth': (409, '照片来源需要重新授权'),
    'api_disabled': (503, 'Google Photos Picker API 尚未启用。请联系应用维护者启用后，再重新选片；无需重复授权。'),
    'unavailable': (503, '媒体暂时无法读取，请稍后重试'),
    'worker_error': (503, '媒体处理暂时失败'),
    'timeout': (503, '媒体服务暂时未响应'),
    'rate_limited': (503, '媒体服务繁忙，请稍后重试'),
    'remote_error': (503, '媒体服务暂时不可用'),
    'bad_response': (502, '媒体服务响应无效'),
    'too_large': (422, '所选媒体超过处理上限'),
    'unsupported_media': (422, '此媒体格式暂不支持'),
    'unsupported_image': (422, '此照片无法安全生成展示副本'),
    'selection_changed': (409, '照片选择已变化，请重新开始'),
    'selection_limit': (422, '本次最多选择二十张照片'),
    'expired': (410, '本次照片选择已过期'),
    'not_ready': (409, '照片选择尚未完成'),
    'not_selected': (403, '照片不在本次选择范围内'),
    'cleanup_unknown': (503, '远端选择器清理结果尚不明确'),
    'network': (503, '媒体连接暂时中断'),
    'redirect': (502, '媒体服务返回了不支持的跳转'),
    'invalid_token': (409, '照片来源需要重新授权'),
    'create_unknown': (409, '选择器可能已创建，未自动重试；可明确开始新的选择'),
}
IMAGE_FAILURES = {
    'input_too_large': '输入图片超过 8 MiB 上限。',
    'unsupported_format': '图片格式不支持；当前支持内容与类型一致的 JPEG、PNG 和 WebP。',
    'invalid_image': '图片不完整或无法安全解码。',
    'multiple_frames': '暂不支持动图或多帧图片。',
    'too_many_pixels': '图片像素超过 2000 万像素上限。',
    'output_too_large': '净化后的展示图片超过 2 MiB 上限。',
    'unsafe_decoder_configuration': '当前解码配置无法安全处理图片。',
}
ERRORS.update({code:(422,message) for code,message in IMAGE_FAILURES.items()})
RESULT_MESSAGES = {code:message for code,(_status,message) in ERRORS.items()}
RESULT_MESSAGES.update(invalid_input='图片字节或媒体类型无效。',
    unsupported_type='本次仅处理照片，已跳过非照片媒体。',
    result_unknown='旧记录未保存此项的具体处理原因。')


class MediaError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'worker_error'
        self.status, self.message = ERRORS[self.code]
        super().__init__(self.message)


SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS media_imports(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
 account_id TEXT REFERENCES cloud_accounts(id) ON DELETE SET NULL,
 request_id TEXT NOT NULL, request_key TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('queued','creating','waiting_selection','listing','staging','awaiting_confirmation','confirmed','create_unknown','failed','cancelled','expired')),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
 created_at REAL NOT NULL, updated_at REAL NOT NULL, expires_at REAL NOT NULL,
 next_attempt_at REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 create_attempted INTEGER NOT NULL DEFAULT 0 CHECK(create_attempted IN (0,1)),
 lease_token TEXT, lease_until REAL, error_code TEXT,
 cleanup_state TEXT NOT NULL DEFAULT 'none' CHECK(cleanup_state IN ('none','pending','unknown','checking','done','unavailable')),
 context_cipher BLOB, session_cipher BLOB, manifest_cipher BLOB,
 confirm_request_id TEXT, confirm_key TEXT, cancel_revision INTEGER,
 reserved_bytes INTEGER NOT NULL DEFAULT 0 CHECK(reserved_bytes>=0),
 UNIQUE(owner,request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS media_confirm_receipt ON media_imports(owner,confirm_request_id) WHERE confirm_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS media_import_queue ON media_imports(state,next_attempt_at,lease_until);
CREATE INDEX IF NOT EXISTS media_import_account ON media_imports(account_id,state);
CREATE TABLE IF NOT EXISTS media_items(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
 account_id TEXT REFERENCES cloud_accounts(id) ON DELETE SET NULL,
 import_id TEXT NOT NULL REFERENCES media_imports(id), source_key TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('staged','ready','deleted')),
 visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','shared')),
 journey_id TEXT REFERENCES journey_workflows(id) ON DELETE SET NULL,
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
 metadata_cipher BLOB, preview_cipher BLOB, preview_key TEXT,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, confirmed_at REAL,
 deleted_at REAL, delete_revision INTEGER,
 CHECK(state!='staged' OR visibility='private'),
 CHECK(state!='ready' OR (confirmed_at IS NOT NULL AND metadata_cipher IS NOT NULL AND preview_cipher IS NOT NULL)),
 CHECK(state!='deleted' OR (metadata_cipher IS NULL AND preview_cipher IS NULL AND preview_key IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS media_source_live ON media_items(owner,source_key) WHERE state IN ('staged','ready');
CREATE INDEX IF NOT EXISTS media_item_owner ON media_items(owner,state,updated_at,id);
CREATE INDEX IF NOT EXISTS media_item_account ON media_items(account_id,state);
CREATE TABLE IF NOT EXISTS media_tv_grants(
 media_id TEXT NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
 device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 granted_by TEXT NOT NULL REFERENCES users(id), created_at REAL NOT NULL,
 PRIMARY KEY(media_id,device_id)
);
CREATE TRIGGER IF NOT EXISTS media_journey_unlink
AFTER UPDATE OF journey_id ON media_items
WHEN OLD.journey_id IS NOT NULL AND NEW.journey_id IS NULL AND NEW.state!='deleted'
BEGIN
 UPDATE media_items SET visibility='private',revision=CASE WHEN NEW.revision=OLD.revision THEN revision+1 ELSE revision END,
 updated_at=CAST(strftime('%s','now') AS REAL) WHERE id=NEW.id;
 DELETE FROM media_tv_grants WHERE media_id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS media_account_removed BEFORE DELETE ON cloud_accounts
BEGIN
 DELETE FROM media_tv_grants WHERE media_id IN (SELECT id FROM media_items WHERE account_id=OLD.id);
 UPDATE media_items SET state='deleted',visibility='private',revision=revision+1,
 delete_revision=revision,deleted_at=CAST(strftime('%s','now') AS REAL),metadata_cipher=NULL,preview_cipher=NULL,preview_key=NULL
 WHERE account_id=OLD.id AND state!='deleted';
 UPDATE media_imports SET state=CASE WHEN state='confirmed' THEN state ELSE 'cancelled' END,
 revision=revision+1,context_cipher=NULL,session_cipher=NULL,manifest_cipher=NULL,
 reserved_bytes=0,lease_token=NULL,lease_until=NULL,cleanup_state='unavailable' WHERE account_id=OLD.id;
END;
'''


def initialize_media_library(con):
    if con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise RuntimeError('Media initialization needs a clean foreign-key connection')
    expected = {'users', 'devices', 'cloud_accounts', 'journey_workflows'}
    actual = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not expected <= actual:
        raise RuntimeError('Media initialization requires existing household parents')
    try:
        con.executescript('BEGIN IMMEDIATE;\n' + SCHEMA_SQL + '\nCOMMIT;')
    except Exception:
        con.rollback()
        raise


def _fields(value, allowed, required=()):
    if type(value) is not dict or set(value) - set(allowed) or set(required) - set(value):
        raise MediaError('invalid_input')


def _id(value):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{24}', value):
        raise MediaError('invalid_input')
    return value


def _key(value):
    if type(value) is not str or not re.fullmatch('[A-Za-z0-9_-]{16,100}', value):
        raise MediaError('invalid_input')
    return value


def _account_id(value):
    # CloudAccounts uses token_hex(16); media and journey rows use 24 hex.
    if type(value) is not str or not re.fullmatch('[a-f0-9]{32}', value):
        raise MediaError('invalid_input')
    return value


def _revision(value):
    if type(value) is not int or value < 1:
        raise MediaError('invalid_input')
    return value


def _text(value, limit):
    if type(value) is not str or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise MediaError('invalid_input')
    valid = False
    try:
        valid = len(value.encode('utf-8')) <= limit
    except UnicodeError:
        pass
    if not valid:
        raise MediaError('invalid_input')
    return value


def _consent(value, field):
    if value.get('consentVersion') != CONSENT_VERSION or value.get(field) is not True:
        raise MediaError('consent_required')


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _timestamp(value):
    result = None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo:
            result = date.timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass
    if result is None:
        raise MediaError('bad_response')
    return result


def _source_time(value):
    """Picker creation instant, not local import time; keep its original precision."""
    if type(value) is not str or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _duration(value):
    if type(value) is not str or not re.fullmatch(r'\d+(?:\.\d{1,9})?s', value):
        raise MediaError('bad_response')
    return min(float(value[:-1]), 86400)


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def manifest_map(value):
    if type(value) is not list or len(value) > MAX_SELECTION:
        raise MediaError('selection_limit')
    result = {}
    for item in value:
        if type(item) is not dict or type(item.get('id')) is not str or item['id'] in result:
            raise MediaError('bad_response')
        _text(item['id'], 1024)
        if set(item) != {'id', 'createTime', 'type', 'mediaFile'} or item['type'] not in ('PHOTO', 'VIDEO'):
            raise MediaError('bad_response')
        if _source_time(item['createTime']) is None:
            raise MediaError('bad_response')
        file = item['mediaFile']
        if type(file) is not dict or set(file) != {'mimeType', 'filename', 'mediaFileMetadata'}:
            raise MediaError('bad_response')
        _text(file['filename'], 1024)
        _text(file['mimeType'], 100)
        result[item['id']] = item
    return result


class MediaLibrary:
    def __init__(self, app, *, clock=time.time):
        self.app, self.clock = app, clock
        self.sessions = app.extensions['member_sessions']
        self.accounts = app.extensions['cloud_accounts']
        self.household = app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')
        self.cipher = MediaCipher(app.secret_key, self.household)
        self._maintenance_cursor = ''

    @contextmanager
    def transaction(self, write=False):
        with self.sessions.db() as con:
            con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield con

    def _seal(self, purpose, row, value):
        return self.cipher.seal_json(purpose, {'id': row['id'], 'household': self.household,
            'owner': row['owner'], 'value': value})

    def _open(self, purpose, row, blob):
        value = None
        try:
            envelope = self.cipher.open_json(purpose, bytes(blob))
            if (envelope.get('id'), envelope.get('household'), envelope.get('owner')) == (row['id'], self.household, row['owner']):
                value = envelope.get('value')
        except (MediaCryptoError, TypeError):
            pass
        if type(value) is not dict:
            raise MediaError('unavailable')
        return value

    def _audit(self, con, owner, action, uid):
        con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)',
                    (owner, action, uid, _iso(self.clock())))
        con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def _receipt(self, owner, value):
        return self.cipher.source_key(owner, 'local-media-receipt/v1', _canonical(value))

    def _quota(self, con, owner):
        totals = con.execute('''SELECT owner,SUM(bytes) AS n FROM (
          SELECT owner,coalesce(length(context_cipher),0)+coalesce(length(session_cipher),0)+coalesce(length(manifest_cipher),0)+reserved_bytes bytes FROM media_imports
          UNION ALL SELECT owner,coalesce(length(metadata_cipher),0)+coalesce(length(preview_cipher),0) FROM media_items)
          GROUP BY owner''').fetchall()
        if sum(r['n'] for r in totals) > HOUSEHOLD_BYTES or sum(r['n'] for r in totals if r['owner'] == owner) > OWNER_BYTES:
            raise MediaError('quota')

    def _authority(self, con, account_id, owner, identity=None):
        row = con.execute('SELECT * FROM cloud_accounts WHERE id=? AND owner=?', (account_id, owner)).fetchone()
        if not row or row['provider'] != 'google' or row['needs_reauth']:
            return None
        client, secret = self.accounts.credentials('google')
        if not secret or client != row['client_id']:
            return None
        allowed = False
        try:
            allowed = photos_allowed('google', self.accounts.decrypt(row['tokens']).get('scope'))
        except Exception:
            pass
        if not allowed or identity and any(row[k] != identity.get(k) for k in ('subject', 'client_id', 'provider')):
            return None
        return row

    def _context_valid(self, con, row):
        if row['state'] not in ACTIVE or row['expires_at'] <= self.clock():
            return False
        valid = False
        try:
            context = self._open('import-context', row, row['context_cipher'])
            member = self.sessions.validate_context(con, context['member'], member=True)
            valid = member['owner'] == row['owner'] and self._authority(con, row['account_id'], row['owner'], context['account']) is not None
        except Exception:
            pass
        return valid

    def _member(self, con):
        if not getattr(g, 'actor', None) or g.actor.get('role') != 'member':
            raise MediaError('forbidden')
        current = self.sessions.current(con)
        if (current['owner'], current['auth_version'], self.household) != (g.actor['id'], g.actor.get('auth_version'), g.actor.get('householdId')):
            raise MediaError('unauthorized')
        return current['owner']

    @contextmanager
    def _suggestion_transaction(self, write=False):
        """Fence only owner suggestions/confirmation to the request's session."""
        actor = dict(getattr(g, 'actor', None) or {})
        original = dict(getattr(g, 'member_session', None) or {})
        if actor.get('role') != 'member':
            raise MediaError('forbidden')
        identity = (original.get('id'), actor.get('id'), actor.get('auth_version'), actor.get('householdId'))
        if (not identity[0] or original.get('owner') != identity[1]
                or original.get('auth_version') != identity[2] or identity[3] != self.household):
            raise MediaError('unauthorized')

        def check(con):
            current = self.sessions.current(con)
            if (current['id'], current['owner'], current['auth_version'], self.household) != identity:
                raise MediaError('unauthorized')

        with self.sessions.db() as con:
            try:
                if not write:
                    check(con)
                    # Legacy cookie resolution may start an implicit write. Do
                    # not keep it or its snapshot through the read-only query.
                    con.rollback()
                con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                if write:
                    check(con)  # Includes time spent waiting for another writer.
                yield con
                if not write:
                    con.rollback()
                check(con)  # Fresh after reads; after audit and before write commit.
                if not write:
                    con.rollback()  # Discard a legacy resolve's implicit update.
            except BaseException:
                con.rollback()
                raise

    def _import(self, con, uid, owner):
        row = con.execute('SELECT * FROM media_imports WHERE id=? AND owner=?', (_id(uid), owner)).fetchone()
        if not row:
            raise MediaError('not_found')
        return row

    def _manifest(self, row):
        return self._open('picker-manifest', row, row['manifest_cipher']) if row['manifest_cipher'] else {'media': [], 'slots': []}

    def _result_summary(self, row, saved=None):
        records = None
        if row['manifest_cipher']:
            records = [{'status':slot['status'], 'error':{'code':slot.get('error_code')}}
                       for slot in self._manifest(row)['slots']]
            saved = 0 if saved is None else saved
        elif row['context_cipher']:
            context = self._open('import-context',row,row['context_cipher'])
            summary = context.get('resultSummary')
            if isinstance(summary,dict) and summary.get('resultsState')=='known':
                records = summary.get('results')
                saved = summary.get('counts',{}).get('saved')
            elif row['state']=='confirmed':
                ids=context.get('itemIds')
                if (isinstance(ids,list) and len(ids)<=MAX_SELECTION and all(isinstance(i,str) and re.fullmatch(r'[a-f0-9]{24}',i) for i in ids)
                        and len(set(ids))==len(ids)):
                    saved=len(ids)  # Old receipt knows saved IDs, not why others were absent.
        if records is None:
            return {'resultsState':'unknown','results':[],
                'counts':{**dict.fromkeys(('selected','ready','skipped','failed','pending','unselected')), 'saved':saved}}
        if not isinstance(records,list) or len(records)>MAX_SELECTION:
            raise MediaError('unavailable')
        results=[]
        for position,record in enumerate(records,1):
            status=record.get('status')
            if status not in ('pending','successful','duplicate','skipped','failed'):
                raise MediaError('unavailable')
            result={'position':position,'status':status}
            if status in ('skipped','failed'):
                code=(record.get('error') or {}).get('code')
                code=code if isinstance(code,str) and code in RESULT_MESSAGES else 'unsupported_type' if status=='skipped' else 'result_unknown'
                result['error']={'code':code,'message':RESULT_MESSAGES[code]}
            results.append(result)
        ready=sum(item['status'] in ('successful','duplicate') for item in results)
        if saved is not None and (type(saved) is not int or not 0<=saved<=ready):
            raise MediaError('unavailable')
        return {'resultsState':'known','results':results,'counts':{'selected':len(results),'ready':ready,
            'skipped':sum(item['status']=='skipped' for item in results),
            'failed':sum(item['status']=='failed' for item in results),
            'pending':sum(item['status']=='pending' for item in results),'saved':saved,
            'unselected':ready-saved if row['state']=='confirmed' and saved is not None else None}}

    def _terminal_receipt(self, row):
        try:
            summary=self._result_summary(row)
            # Replace active authorization context with counts and fixed reasons only.
            return self._seal('import-context',row,{'resultSummary':summary}) if summary['resultsState']=='known' else None
        except (MediaError,MediaCryptoError,KeyError,TypeError,ValueError,AttributeError):
            # Diagnostics must never prevent cancellation or privacy cleanup.
            return None

    def _import_dto(self, row):
        result = {'id': row['id'], 'revision': row['revision'], 'state': row['state'],
            'createdAt': _iso(row['created_at']), 'expiresAt': _iso(row['expires_at']),
            'nextPollAt': _iso(row['next_attempt_at']) if row['next_attempt_at'] else None,
            **self._result_summary(row),
            'error': {'code': row['error_code'], 'message': ERRORS.get(row['error_code'], ERRORS['worker_error'])[1]} if row['error_code'] else None,
            'canConfirm': row['state'] == 'awaiting_confirmation' and row['expires_at'] > self.clock(),
            'cleanupPending': row['cleanup_state'] in ('pending', 'unknown', 'checking')}
        if row['state'] == 'waiting_selection' and row['session_cipher'] and row['expires_at'] > self.clock():
            result['pickerUri'] = self._open('picker-session', row, row['session_cipher'])['session'].get('pickerUri')
        return result

    def create_import(self, value):
        _fields(value, {'requestId','accountId','consentVersion','allowTemporaryProcessing','previousUnknownImportId','acknowledgePossibleExistingSession'},
                {'requestId','accountId','consentVersion','allowTemporaryProcessing'})
        _consent(value, 'allowTemporaryProcessing')
        request_id, account_id = _key(value['requestId']), _account_id(value['accountId'])
        if 'previousUnknownImportId' in value:
            _id(value['previousUnknownImportId'])
            if value.get('acknowledgePossibleExistingSession') is not True:
                raise MediaError('invalid_input')
        elif 'acknowledgePossibleExistingSession' in value:
            raise MediaError('invalid_input')
        context, _ = self.sessions.capture(claim=False, member=True)
        with self.transaction(True) as con:
            owner = self._member(con)
            digest = self._receipt(owner, value)
            row = con.execute('SELECT * FROM media_imports WHERE owner=? AND request_id=?', (owner, request_id)).fetchone()
            if row:
                if row['request_key'] != digest:
                    raise MediaError('conflict')
                return {'import': self._import_dto(row), 'replayed': True}
            self.sessions.validate_context(con, context, member=True)
            account = self._authority(con, account_id, owner)
            if account is None:
                raise MediaError('reauth')
            if 'previousUnknownImportId' in value:
                previous = self._import(con, value['previousUnknownImportId'], owner)
                if previous['state'] != 'create_unknown' or value.get('acknowledgePossibleExistingSession') is not True:
                    raise MediaError('conflict')
            elif 'acknowledgePossibleExistingSession' in value:
                raise MediaError('invalid_input')
            now = self.clock()
            rows = con.execute('SELECT state,created_at FROM media_imports WHERE owner=?', (owner,)).fetchall()
            if len(rows) >= 2000 or sum(r['state'] in ACTIVE for r in rows) >= 2 or sum(r['created_at'] > now-86400 for r in rows) >= 10:
                raise MediaError('quota')
            row = {'id': secrets.token_hex(12), 'owner': owner}
            protected = self._seal('import-context', row, {'member': context,
                'account': {k: account[k] for k in ('provider','subject','client_id')},
                'temporaryConsent': {'version': CONSENT_VERSION, 'at': now}})
            con.execute('''INSERT INTO media_imports(id,owner,account_id,request_id,request_key,state,created_at,updated_at,expires_at,context_cipher,reserved_bytes)
                VALUES(?,?,?,?,?,'queued',?,?,?,?,?)''',
                (row['id'], owner, account_id, request_id, digest, now, now, now+86400, protected, MAX_SELECTION*ITEM_RESERVATION))
            self._quota(con, owner)
            self._audit(con, owner, 'media_import_start', row['id'])
            return {'import': self._import_dto(self._import(con, row['id'], owner)), 'replayed': False}

    def _delete_item(self, con, row):
        con.execute('DELETE FROM media_tv_grants WHERE media_id=?', (row['id'],))
        con.execute('''UPDATE media_items SET state='deleted',visibility='private',delete_revision=revision,revision=revision+1,
          deleted_at=?,updated_at=?,metadata_cipher=NULL,preview_cipher=NULL,preview_key=NULL WHERE id=? AND state!='deleted' ''',
          (self.clock(), self.clock(), row['id']))

    def _terminate(self, con, row, state, code=None):
        receipt=self._terminal_receipt(row)
        for item in con.execute("SELECT id FROM media_items WHERE import_id=? AND state='staged'", (row['id'],)).fetchall():
            self._delete_item(con, item)
        con.execute('''UPDATE media_imports SET state=?,error_code=?,revision=revision+1,lease_token=NULL,lease_until=NULL,
          reserved_bytes=0,manifest_cipher=NULL,context_cipher=?,
          cleanup_state=CASE WHEN session_cipher IS NULL THEN 'done' ELSE 'pending' END WHERE id=?''', (state, code, receipt, row['id']))

    def maintenance(self):
        count = 0
        with self.transaction(True) as con:
            con.execute("UPDATE media_imports SET cleanup_state='unknown',lease_token=NULL,lease_until=NULL,revision=revision+1 WHERE id IN (SELECT id FROM media_imports WHERE cleanup_state='checking' AND lease_until<=? LIMIT 100)",(self.clock(),))
            query="SELECT * FROM media_imports WHERE state IN ('queued','creating','waiting_selection','listing','staging','awaiting_confirmation') AND id>? ORDER BY id LIMIT 100"
            rows=con.execute(query,(self._maintenance_cursor,)).fetchall()
            if not rows:
                self._maintenance_cursor=''
                rows=con.execute(query,('',)).fetchall()
            for row in rows:
                self._maintenance_cursor=row['id']
                if row['state'] in ACTIVE and (row['expires_at'] <= self.clock() or not self._context_valid(con, row)):
                    self._terminate(con, row, 'expired' if row['expires_at'] <= self.clock() else 'cancelled', 'expired' if row['expires_at'] <= self.clock() else 'unauthorized')
                    count += 1
                elif row['state'] == 'creating' and row['lease_until'] <= self.clock():
                    self._terminate(con, row, 'create_unknown', 'create_unknown')
                    count += 1
        return count

    def on_account_removed(self, con, account_id):
        if not con.in_transaction:
            raise RuntimeError('Media account hooks require the caller transaction')
        for row in con.execute('SELECT * FROM media_imports WHERE account_id=?', (account_id,)).fetchall():
            if row['state'] != 'confirmed':
                self._terminate(con, row, 'cancelled', 'reauth')
            con.execute("UPDATE media_imports SET session_cipher=NULL,context_cipher=NULL,manifest_cipher=NULL,cleanup_state='unavailable',reserved_bytes=0,lease_token=NULL,lease_until=NULL,revision=revision+1 WHERE id=?", (row['id'],))
        for row in con.execute("SELECT id FROM media_items WHERE account_id=? AND state!='deleted'", (account_id,)).fetchall():
            self._delete_item(con, row)

    def on_account_authority_changed(self, con, account_id, reason):
        if not con.in_transaction:
            raise RuntimeError('Media account hooks require the caller transaction')
        if reason in ('removed', 'scope_revoked', 'photos_revoked','identity_changed'):
            self.on_account_removed(con, account_id)
            return
        for row in con.execute('SELECT * FROM media_imports WHERE account_id=?', (account_id,)).fetchall():
            if row['state'] in ACTIVE:
                self._terminate(con, row, 'cancelled', 'reauth')
        con.execute('DELETE FROM media_tv_grants WHERE media_id IN (SELECT id FROM media_items WHERE account_id=?)', (account_id,))
        con.execute("UPDATE media_items SET visibility='private',revision=revision+1 WHERE account_id=? AND state='ready'", (account_id,))

    def claim_next(self):
        self.maintenance()
        now = self.clock()
        with self.transaction(True) as con:
            rows = con.execute("SELECT * FROM media_imports WHERE (state IN ('queued','waiting_selection','listing','staging') OR cleanup_state IN ('pending','unknown')) AND next_attempt_at<=? AND (lease_token IS NULL OR lease_until<=?) ORDER BY created_at,id LIMIT 100", (now, now)).fetchall()
            for row in rows:
                cleanup = row['cleanup_state'] in ('pending', 'unknown')
                if cleanup:
                    saved_session=self._open('picker-session',row,row['session_cipher']) if row['session_cipher'] else None
                    if not saved_session or not self._authority(con, row['account_id'], row['owner'],saved_session.get('account')):
                        con.execute("UPDATE media_imports SET cleanup_state='unavailable',session_cipher=NULL WHERE id=?", (row['id'],))
                        continue
                    action = 'cleanup'
                else:
                    action = {'queued':'create','waiting_selection':'poll','listing':'list','staging':'download'}.get(row['state'])
                    if not action or not self._context_valid(con, row):
                        continue
                lease = secrets.token_hex(16)
                state = 'creating' if action == 'create' else row['state']
                con.execute('''UPDATE media_imports SET state=?,lease_token=?,lease_until=?,revision=revision+1,
                    create_attempted=CASE WHEN ?='create' THEN 1 ELSE create_attempted END,
                    cleanup_state=CASE WHEN ?='cleanup' THEN 'checking' ELSE cleanup_state END WHERE id=?''',
                    (state, lease, now+LEASE_SECONDS, action, action, row['id']))
                current = self._import(con, row['id'], row['owner'])
                manifest = self._manifest(current)
                pending = next((s for s in manifest['slots'] if s['status'] == 'pending'), None)
                session = self._open('picker-session', current, current['session_cipher'])['session'] if current['session_cipher'] else None
                identity=saved_session.get('account') if cleanup else self._open('import-context',current,current['context_cipher'])['account']
                return {'id':row['id'], 'owner':row['owner'], 'accountId':row['account_id'], 'action':action,
                    'leaseToken':lease,'revision':current['revision'],'expiresAt':row['expires_at'], 'attempts':row['attempts'],
                    'cleanupUnknown':row['cleanup_state']=='unknown', 'accountIdentity':identity,'session':session,'manifest':manifest['media'] or None,
                    'media':next((m for m in manifest['media'] if pending and m['id']==pending['mediaId']), None)}
        return None

    def _job(self, con, job):
        row = con.execute('SELECT * FROM media_imports WHERE id=?', (job['id'],)).fetchone()
        if not row or (row['lease_token'],row['revision']) != (job['leaseToken'],job['revision']) or not row['lease_until'] or row['lease_until'] <= self.clock():
            return None
        if job['action'] == 'cleanup':
            saved=self._open('picker-session',row,row['session_cipher'])
            return row if self._authority(con, row['account_id'], row['owner'],saved.get('account')) else None
        if not self._context_valid(con, row):
            self._terminate(con, row, 'cancelled', 'unauthorized')
            return None
        if row['session_cipher']:
            session = self._open('picker-session', row, row['session_cipher'])
            until = min(session['deadline'],_timestamp(session['session']['expireTime']))
            if until <= self.clock():
                self._terminate(con,row,'expired','expired')
                return None
        return row

    def validate_job(self, job):
        with self.transaction(True) as con:
            return self._job(con, job) is not None

    def _session(self, row, result):
        if type(result) is not dict or type(result.get('mediaItemsSet')) is not bool or type(result.get('id')) is not str:
            raise MediaError('bad_response')
        if _timestamp(result.get('expireTime')) <= self.clock():
            raise MediaError('expired')
        previous = self._open('picker-session', row, row['session_cipher']) if row['session_cipher'] else None
        if previous and previous['session']['id'] != result['id']:
            raise MediaError('selection_changed')
        deadline = previous['deadline'] if previous else min(row['expires_at'], _timestamp(result['expireTime']))
        if not result['mediaItemsSet']:
            config = result.get('pollingConfig', {})
            interval = max(1, _duration(config.get('pollInterval')))
            if not previous:
                deadline = min(deadline, self.clock()+_duration(config.get('timeoutIn')))
            if deadline <= self.clock():
                raise MediaError('expired')
        else:
            interval = 0
        deadline = min(deadline, _timestamp(result['expireTime']))
        if deadline <= self.clock():
            raise MediaError('expired')
        identity=previous['account'] if previous else self._open('import-context',row,row['context_cipher'])['account']
        return self._seal('picker-session', row, {'session': result,'deadline':deadline,'account':identity}), self.clock()+interval

    def _finish_staging(self, con, row, manifest):
        pending = sum(s['status']=='pending' for s in manifest['slots'])
        successes = sum(s['status'] in ('successful','duplicate') for s in manifest['slots'])
        state = 'staging' if pending else 'awaiting_confirmation' if successes else 'failed'
        con.execute('''UPDATE media_imports SET state=?,manifest_cipher=?,reserved_bytes=?,cleanup_state=?,
            lease_token=NULL,lease_until=NULL,revision=revision+1,attempts=0,next_attempt_at=0,error_code=NULL WHERE id=?''',
            (state,self._seal('picker-manifest',row,manifest),pending*ITEM_RESERVATION,
             'none' if pending else 'pending',row['id']))
        self._quota(con, row['owner'])

    def complete(self, job, result):
        with self.transaction(True) as con:
            row = self._job(con, job)
            if row is None:
                # A completed CREATE may arrive after cancellation or a lease
                # expires. Keep only the known remote session for deletion;
                # never resurrect the import or expose its pickerUri.
                stale = con.execute('SELECT * FROM media_imports WHERE id=?', (job['id'],)).fetchone()
                if (job['action']=='create' and stale and stale['state']=='creating'
                    and stale['lease_token']==job['leaseToken'] and stale['lease_until']<=self.clock()):
                    self._terminate(con,stale,'create_unknown','create_unknown')
                    stale=con.execute('SELECT * FROM media_imports WHERE id=?',(job['id'],)).fetchone()
                if (job['action']=='create' and stale and stale['create_attempted']
                    and stale['state'] in ('cancelled','expired','create_unknown','failed')
                    and not stale['session_cipher'] and stale['account_id']==job['accountId']
                    and self._authority(con,stale['account_id'],stale['owner'],job.get('accountIdentity')) is not None
                    and type(result) is dict and type(result.get('id')) is str):
                    minimal = {k:result[k] for k in ('id','expireTime','mediaItemsSet')}
                    protected = self._seal('picker-session',stale,{'session':minimal,'deadline':_timestamp(result['expireTime']),'account':job['accountIdentity']})
                    con.execute("UPDATE media_imports SET session_cipher=?,cleanup_state='pending',revision=revision+1 WHERE id=?",(protected,stale['id']))
                return False
            action = job['action']
            if action == 'cleanup':
                con.execute("UPDATE media_imports SET cleanup_state='done',session_cipher=NULL,lease_token=NULL,lease_until=NULL,revision=revision+1 WHERE id=?", (row['id'],))
                if row['state'] in ('failed','cancelled','expired','create_unknown'):
                    con.execute('UPDATE media_imports SET context_cipher=?,manifest_cipher=NULL WHERE id=?',(self._terminal_receipt(row),row['id']))
                return True
            if action in ('create','poll'):
                session, due = self._session(row, result)
                con.execute('''UPDATE media_imports SET state=?,session_cipher=?,next_attempt_at=?,attempts=0,
                    lease_token=NULL,lease_until=NULL,revision=revision+1 WHERE id=?''',
                    ('listing' if result['mediaItemsSet'] else 'waiting_selection',session,due,row['id']))
            elif action == 'list':
                media = manifest_map(result)
                context = self._open('import-context', row, row['context_cipher'])
                slots = []
                for item in media.values():
                    key = self.cipher.source_key(row['owner'], context['account']['subject'], item['id'])
                    existing = con.execute("SELECT id,state FROM media_items WHERE owner=? AND source_key=? AND state!='deleted'", (row['owner'], key)).fetchone()
                    if existing and existing['state'] == 'staged':
                        raise MediaError('conflict')
                    slots.append({'mediaId':item['id'],'sourceKey':key,'itemId':existing['id'] if existing else secrets.token_hex(12),
                        'status':'duplicate' if existing else 'pending' if item['type']=='PHOTO' else 'skipped',
                        'error_code':'unsupported_type' if not existing and item['type']!='PHOTO' else None})
                self._finish_staging(con, row, {'media':list(media.values()), 'slots':slots})
            elif action == 'download':
                manifest = self._manifest(row)
                if manifest_map(result.get('manifest')) != manifest_map(manifest['media']):
                    raise MediaError('selection_changed')
                slot = next((s for s in manifest['slots'] if s['status']=='pending'), None)
                if not slot or slot['mediaId'] != result.get('mediaId'):
                    raise MediaError('selection_changed')
                preview = result.get('preview')
                if not isinstance(preview, Preview) or preview.content_type != 'image/jpeg' or not 0<len(preview.data)<=2*1024*1024 or not 0<preview.width<=1600 or not 0<preview.height<=1600:
                    raise MediaError('unsupported_image')
                if con.execute('SELECT COUNT(*) FROM media_items WHERE owner=?', (row['owner'],)).fetchone()[0] >= 4000:
                    raise MediaError('quota')
                media = next(m for m in manifest['media'] if m['id']==slot['mediaId'])
                item = {'id':slot['itemId'],'owner':row['owner']}
                preview_key = secrets.token_hex(12)
                metadata = {'accountId':row['account_id'],'sourceKey':slot['sourceKey'],'previewKey':preview_key,
                    'mediaId':media['id'],'displayFilename':media['mediaFile']['filename'],'caption':'',
                    'sourceCreatedAt':media['createTime'],
                    'width':preview.width,'height':preview.height,'contentType':'image/jpeg',
                    'sha256':hashlib.sha256(preview.data).hexdigest(),'bytes':len(preview.data)}
                con.execute('''INSERT INTO media_items(id,owner,account_id,import_id,source_key,state,metadata_cipher,preview_cipher,preview_key,created_at,updated_at)
                    VALUES(?,?,?,?,?,'staged',?,?,?,?,?)''',
                    (item['id'],row['owner'],row['account_id'],row['id'],slot['sourceKey'],self._seal('media-metadata',item,metadata),
                     self.cipher.seal_bytes('media-preview',preview.data),preview_key,self.clock(),self.clock()))
                slot['status'] = 'successful'
                self._finish_staging(con, row, manifest)
            else:
                raise MediaError('invalid_input')
            self._quota(con, row['owner'])
            return True

    def fail(self, job, code, *, retryable=False, outcome_unknown=False, reauth=False, retry_after=30):
        code = code if code in ERRORS else 'worker_error'
        with self.transaction(True) as con:
            row = self._job(con, job)
            if row is None:
                return False
            if job['action'] == 'cleanup':
                state = 'unavailable' if job['cleanupUnknown'] else 'unknown' if outcome_unknown else 'unavailable'
                con.execute('''UPDATE media_imports SET cleanup_state=?,lease_token=NULL,lease_until=NULL,revision=revision+1,
                    session_cipher=CASE WHEN ?='unavailable' THEN NULL ELSE session_cipher END WHERE id=?''', (state,state,row['id']))
                if row['state'] in ('failed','cancelled','expired','create_unknown'):
                    con.execute('UPDATE media_imports SET context_cipher=?,manifest_cipher=NULL WHERE id=?',(self._terminal_receipt(row),row['id']))
            elif reauth or code in ('reauth','forbidden','invalid_token'):
                if reauth or code in ('reauth','invalid_token'):
                    con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=? AND owner=?',(row['account_id'],row['owner']))
                self.on_account_authority_changed(con, row['account_id'], 'reauth')
            elif job['action'] == 'create':
                self._terminate(con, row, 'create_unknown' if outcome_unknown else 'failed', 'create_unknown' if outcome_unknown else code)
            elif retryable and row['attempts'] < 4:
                delay = max(30, min(float(retry_after), 900), 30*2**row['attempts'])
                con.execute('''UPDATE media_imports SET attempts=attempts+1,next_attempt_at=?,error_code=?,lease_token=NULL,lease_until=NULL,
                    revision=revision+1 WHERE id=?''', (self.clock()+delay,code,row['id']))
            elif job['action']=='download' and code in (set(IMAGE_FAILURES)|{'invalid_input','unsupported_media','unsupported_image','too_large'}):
                manifest = self._manifest(row)
                slot=next(s for s in manifest['slots'] if s['status']=='pending')
                slot.update(status='failed',error_code=code)
                self._finish_staging(con,row,manifest)
            else:
                self._terminate(con,row,'expired' if code=='expired' else 'failed',code)
            return True

    def _metadata(self, row):
        value = self._open('media-metadata',row,row['metadata_cipher'])
        if (value.get('accountId'),value.get('sourceKey'),value.get('previewKey')) != (row['account_id'],row['source_key'],row['preview_key']):
            raise MediaError('unavailable')
        return value

    def _item(self, con, uid, owner=None, *, manage=False, device=None):
        row = con.execute('SELECT * FROM media_items WHERE id=?',(_id(uid),)).fetchone()
        if not row or row['state']=='deleted' and row['owner'] != owner:
            raise MediaError('not_found')
        if row['state']=='deleted':
            raise MediaError('gone')
        if device is not None:
            if (row['state']!='ready' or row['visibility']!='shared' or not self._authority(con,row['account_id'],row['owner'])
                or not con.execute('SELECT 1 FROM media_tv_grants WHERE media_id=? AND device_id=?',(uid,device)).fetchone()):
                raise MediaError('not_found')
        elif row['owner']==owner:
            if row['state']=='staged':
                parent = self._import(con,row['import_id'],owner)
                if not self._context_valid(con,parent):
                    raise MediaError('gone')
        elif row['state']!='ready' or row['visibility']!='shared' or not self._authority(con,row['account_id'],row['owner']):
            raise MediaError('not_found')
        elif manage:
            raise MediaError('forbidden')
        return row

    def _item_dto(self, con, row, owner=None, *, television=False):
        meta = self._metadata(row)
        result = {'id':row['id'],'width':meta['width'],'height':meta['height'],
                  'previewUrl':('/api/media-tv/items/' if television else '/api/media/items/')+row['id']+'/preview'}
        if television:
            return result
        journey = con.execute("SELECT j.id,j.trip_id,e.data FROM journey_workflows j JOIN entities e ON e.id=j.trip_id AND e.kind='trips' WHERE j.id=?",(row['journey_id'],)).fetchone() if row['journey_id'] else None
        result.update(revision=row['revision'],caption=meta['caption'],contentType='image/jpeg',visibility=row['visibility'],
                      journey={'id':journey['id'],'tripId':journey['trip_id'],'title':json.loads(journey['data']).get('title','')} if journey else None,
                      createdAt=_iso(row['created_at']),canManage=row['owner']==owner)
        if row['owner']==owner:
            source_time = meta.get('sourceCreatedAt')
            known = _source_time(source_time) is not None
            result.update(accountId=row['account_id'],displayFilename=meta['displayFilename'],source='google-photos',
                          sourceCreatedAt=source_time if known else None,sourceTimeState='known' if known else 'unknown')
        return result

    def journey_suggestions(self, uid):
        """Read a current owner-only date match, never infer a visit or grant access."""
        with self._suggestion_transaction() as con:
            owner = g.actor['id']
            row = con.execute('SELECT '+ITEM_VIEW+' FROM media_items WHERE id=? AND owner=?',(_id(uid),owner)).fetchone()
            if not row:
                raise MediaError('not_found')
            if row['state']=='deleted':
                raise MediaError('gone')
            if row['state']!='ready' or row['confirmed_at'] is None:
                raise MediaError('not_ready')
            source = self._metadata(row).get('sourceCreatedAt')
            instant = _source_time(source)
            result = dict(photoId=row['id'],photoRevision=row['revision'],
                sourceTimeState='known' if instant else 'unknown',sourceCreatedAt=source if instant else None,
                currentJourneyId=row['journey_id'],suggestions=[],limit=20,hasMore=False)
            if instant is None:
                result['reason'] = dict(code='source_time_unknown',message='这张照片没有已记录的来源创建时间，无法按日期建议旅行。请手动核对关联。')
                return result
            rows = con.execute("""SELECT j.id,j.revision AS journey_revision,j.plan,
                e.revision AS trip_revision,e.data FROM journey_workflows j
                JOIN entities e ON e.id=j.trip_id AND e.kind='trips'
                ORDER BY json_extract(e.data,'$.start') DESC,j.id""")
            for journey in rows:
                plan, trip = json.loads(journey['plan']), json.loads(journey['data'])
                legacy = plan.get('schemaVersion',1)==1
                try:
                    tz = zone('Asia/Shanghai' if legacy else plan.get('referenceTimezone'),'referenceTimezone')
                    source_date = instant.astimezone(tz).date().isoformat()
                    start, end = date_only(trip.get('start'),'start'),date_only(trip.get('end'),'end')
                except (TimeIssue, ValueError, OverflowError):
                    continue
                if not start <= source_date <= end:
                    continue
                if len(result['suggestions'])==result['limit']:
                    result['hasMore'] = True
                    break
                result['suggestions'].append(dict(journeyId=journey['id'],journeyRevision=journey['journey_revision'],
                    tripRevision=journey['trip_revision'],title=trip.get('title',''),start=start,end=end,
                    referenceTimezone=tz.key,referenceTimezoneSource='legacy_default' if legacy else 'plan',
                    sourceDate=source_date,alreadyLinked=row['journey_id']==journey['id'],
                    reason=dict(code='date_overlap',message='来源创建时间在该参考时区的日期落在旅行起止日期内；这不证明拍摄地点或实际到访。')))
            result['reason'] = (dict(code='date_overlap',message='请核对来源日期和旅行，再明确确认关联。') if result['suggestions']
                else dict(code='no_matching_journeys',message='来源日期未与当前旅行日期匹配，可手动核对关联。'))
            return result

    def import_detail(self, uid):
        with self.transaction() as con:
            owner = self._member(con)
            row = self._import(con,uid,owner)
            result = {'import':self._import_dto(row),'items':[]}
            if row['state'] not in ('staging','awaiting_confirmation') or not self._context_valid(con,row):
                result['import'].pop('pickerUri',None) if row['state']=='waiting_selection' and not self._context_valid(con,row) else None
                result['import']['canConfirm']=False
                return result
            for slot in self._manifest(row)['slots']:
                if slot['status'] in ('successful','duplicate'):
                    item = con.execute("SELECT * FROM media_items WHERE id=? AND owner=? AND state!='deleted'",(slot['itemId'],owner)).fetchone()
                    if item:
                        result['items'].append({'id':item['id'],'status':slot['status'],'item':self._item_dto(con,item,owner)})
            return result

    def confirm_import(self, uid, value):
        _fields(value,{'revision','confirmRequestId','itemIds','consentVersion','persistSelected'},
                {'revision','confirmRequestId','itemIds','consentVersion','persistSelected'})
        _consent(value,'persistSelected')
        revision, request_id = _revision(value['revision']),_key(value['confirmRequestId'])
        ids = value['itemIds']
        if type(ids) is not list or not 1<=len(ids)<=MAX_SELECTION or any(type(i) is not str for i in ids) or len(set(ids))!=len(ids):
            raise MediaError('invalid_input')
        ids = sorted(_id(i) for i in ids)
        with self.transaction(True) as con:
            owner = self._member(con)
            row = self._import(con,uid,owner)
            digest = self._receipt(owner,{'kind':'confirm','importId':uid,'itemIds':ids,'consentVersion':CONSENT_VERSION})
            prior = con.execute('SELECT * FROM media_imports WHERE owner=? AND confirm_request_id=?',(owner,request_id)).fetchone()
            if prior:
                if prior['id']!=uid or prior['confirm_key']!=digest:
                    raise MediaError('conflict')
                existing = [r[0] for r in con.execute("SELECT id FROM media_items WHERE id IN ("+','.join('?'*len(ids))+") AND owner=? AND state='ready'",(*ids,owner))]
                return {'import':self._import_dto(row),'itemIds':existing,'goneItemIds':sorted(set(ids)-set(existing)),'replayed':True}
            if row['revision']!=revision:
                raise MediaError('conflict')
            if row['state']!='awaiting_confirmation' or not self._context_valid(con,row):
                raise MediaError('gone')
            manifest = self._manifest(row)
            available = {s['itemId'] for s in manifest['slots'] if s['status'] in ('successful','duplicate')}
            if not set(ids)<=available:
                raise MediaError('invalid_input')
            selected = [self._item(con,i,owner,manage=True) for i in ids]
            if any(r['state']=='staged' and r['import_id']!=uid for r in selected):
                raise MediaError('conflict')
            current = con.execute("SELECT COUNT(*) FROM media_items WHERE owner=? AND state='ready'",(owner,)).fetchone()[0]
            if current+sum(r['state']=='staged' for r in selected)>1000:
                raise MediaError('quota')
            for item in con.execute('SELECT '+ITEM_VIEW+" FROM media_items WHERE import_id=? AND state='staged'",(uid,)).fetchall():
                if item['id'] in ids:
                    meta=self._metadata(item)
                    meta['persistenceConsent']={'version':CONSENT_VERSION,'at':self.clock()}
                    con.execute("UPDATE media_items SET state='ready',confirmed_at=?,metadata_cipher=?,revision=revision+1 WHERE id=?",
                                (self.clock(),self._seal('media-metadata',item,meta),item['id']))
                else:
                    self._delete_item(con,item)
            summary=self._result_summary(row,saved=len(ids))
            summary['counts']['unselected']=summary['counts']['ready']-len(ids)
            receipt=self._seal('import-context',row,{'consentVersion':CONSENT_VERSION,'confirmedAt':self.clock(),
                'itemIds':ids,'resultSummary':summary})
            con.execute("UPDATE media_imports SET state='confirmed',confirm_request_id=?,confirm_key=?,context_cipher=?,manifest_cipher=NULL,reserved_bytes=0,revision=revision+1 WHERE id=?",
                        (request_id,digest,receipt,uid))
            self._quota(con,owner)
            self._audit(con,owner,'media_import_confirm',uid)
            return {'import':self._import_dto(self._import(con,uid,owner)),'itemIds':ids,'goneItemIds':[],'replayed':False}

    def cancel_import(self, uid, value):
        _fields(value,{'revision'},{'revision'})
        revision=_revision(value['revision'])
        with self.transaction(True) as con:
            owner=self._member(con)
            row=self._import(con,uid,owner)
            if row['state']=='cancelled' and row['cancel_revision']==revision:
                return {'cancelled':True,'cleanupPending':row['cleanup_state'] in ('pending','unknown'),'replayed':True}
            if row['revision']!=revision or row['state']=='confirmed':
                raise MediaError('conflict')
            self._terminate(con,row,'cancelled')
            con.execute('UPDATE media_imports SET cancel_revision=? WHERE id=?',(revision,uid))
            self._audit(con,owner,'media_import_cancel',uid)
            return {'cancelled':True,'cleanupPending':bool(row['session_cipher']),'replayed':False}

    def patch_item(self, uid, value):
        expected = {'expectedJourneyRevision','expectedTripRevision'}
        _fields(value,{'revision','caption','journeyId','visibility'}|expected,{'revision'})
        revision=_revision(value['revision'])
        if len(value)==1:
            raise MediaError('invalid_input')
        suggested = bool(expected & value.keys())
        if suggested:
            # The explicit suggestion confirmation changes only this association.
            _fields(value,{'revision','journeyId'}|expected,{'revision','journeyId'}|expected)
            _id(value['journeyId'])
            for name in expected:
                _revision(value[name])
        with (self._suggestion_transaction(True) if suggested else self.transaction(True)) as con:
            owner=self._member(con)
            row=self._item(con,uid,owner,manage=True)
            if row['state']!='ready' or row['revision']!=revision:
                raise MediaError('conflict')
            visibility=value.get('visibility',row['visibility'])
            if visibility not in ('private','shared'):
                raise MediaError('invalid_input')
            if visibility=='shared' and not self._authority(con,row['account_id'],owner):
                raise MediaError('reauth')
            journey=value.get('journeyId',row['journey_id'])
            if journey is not None:
                linked = con.execute("""SELECT j.revision AS journey_revision,e.revision AS trip_revision
                    FROM journey_workflows j JOIN entities e ON e.id=j.trip_id AND e.kind='trips' WHERE j.id=?""",(_id(journey),)).fetchone()
                if not linked:
                    raise MediaError('conflict' if suggested else 'not_found')
                if suggested and (linked['journey_revision'],linked['trip_revision']) != (value['expectedJourneyRevision'],value['expectedTripRevision']):
                    raise MediaError('conflict')
            meta=self._metadata(row)
            if 'caption' in value:
                meta['caption']=_text(value['caption'],500)
            if row['journey_id'] and journey is None:
                visibility='private'
            if visibility=='private':
                con.execute('DELETE FROM media_tv_grants WHERE media_id=?',(uid,))
            con.execute('UPDATE media_items SET visibility=?,journey_id=?,metadata_cipher=?,revision=revision+1,updated_at=? WHERE id=?',
                        (visibility,journey,self._seal('media-metadata',row,meta),self.clock(),uid))
            self._quota(con,owner)
            self._audit(con,owner,'media_item_update',uid)
            return {'item':self._item_dto(con,self._item(con,uid,owner),owner)}

    def delete_item(self, uid, value):
        _fields(value,{'revision'},{'revision'})
        revision=_revision(value['revision'])
        with self.transaction(True) as con:
            owner=self._member(con)
            row=con.execute('SELECT * FROM media_items WHERE id=? AND owner=?',(_id(uid),owner)).fetchone()
            if not row:
                raise MediaError('not_found')
            if row['state']=='deleted' and row['delete_revision']==revision:
                return {'deleted':True,'cleanupPending':False,'replayed':True}
            if row['revision']!=revision or row['state']=='deleted':
                raise MediaError('conflict')
            self._delete_item(con,row)
            self._audit(con,owner,'media_item_delete',uid)
            return {'deleted':True,'cleanupPending':False,'replayed':False}

    def tv_grants(self, uid, value=None):
        if value is not None:
            _fields(value,{'revision','deviceIds','consentVersion','allowTvDisplay'},{'revision','deviceIds'})
            _revision(value['revision'])
            devices=value['deviceIds']
            if type(devices) is not list or len(devices)>20 or any(type(d) is not str for d in devices) or len(set(devices))!=len(devices):
                raise MediaError('invalid_input')
            devices=[_id(d) for d in devices]
            if devices:
                _consent(value,'allowTvDisplay')
        with self.transaction(value is not None) as con:
            owner=self._member(con)
            row=self._item(con,uid,owner,manage=True)
            if value is not None:
                if row['revision']!=value['revision'] or row['state']!='ready' or devices and row['visibility']!='shared':
                    raise MediaError('conflict')
                if devices and not self._authority(con,row['account_id'],owner):
                    raise MediaError('reauth')
                for device in devices:
                    if not con.execute('SELECT 1 FROM devices WHERE id=? AND approved=1 AND expires>?',(device,self.clock())).fetchone():
                        raise MediaError('not_found')
                con.execute('DELETE FROM media_tv_grants WHERE media_id=?',(uid,))
                con.executemany('INSERT INTO media_tv_grants(media_id,device_id,granted_by,created_at) VALUES(?,?,?,?)',
                                [(uid,d,owner,self.clock()) for d in devices])
                con.execute('UPDATE media_items SET revision=revision+1,updated_at=? WHERE id=?',(self.clock(),uid))
                self._audit(con,owner,'media_tv_grant',uid)
            revision=con.execute('SELECT revision FROM media_items WHERE id=?',(uid,)).fetchone()[0]
            ids=[r[0] for r in con.execute('SELECT device_id FROM media_tv_grants WHERE media_id=? ORDER BY device_id',(uid,))]
            return {'revision':revision,'deviceIds':ids}

    def _tv(self, con):
        cookie=request.cookies.get('household_tv','')
        if not cookie or len(cookie)>4096:
            raise MediaError('unauthorized')
        digest=hashlib.sha256(cookie.encode()).hexdigest()
        row=con.execute('SELECT id FROM devices WHERE secret_hash=? AND approved=1 AND expires>?',(digest,self.clock())).fetchone()
        if not row:
            raise MediaError('unauthorized')
        return row['id']

    def preview(self, uid, television=False):
        with self.transaction() as con:
            actor=self._tv(con) if television else self._member(con)
            row=self._item(con,uid,device=actor) if television else self._item(con,uid,actor)
            revision=row['revision']
            meta=self._metadata(row)
            blob=bytes(row['preview_cipher'])
        raw=None
        try:
            raw=self.cipher.open_bytes('media-preview',blob)
        except MediaCryptoError:
            pass
        if raw is None or len(raw)!=meta['bytes'] or hashlib.sha256(raw).hexdigest()!=meta['sha256']:
            raise MediaError('unavailable')
        with self.transaction() as con:
            current=self._tv(con) if television else self._member(con)
            latest=self._item(con,uid,device=current) if television else self._item(con,uid,current)
            if current!=actor or latest['revision']!=revision:
                raise MediaError('conflict')
        return Response(raw,content_type='image/jpeg',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


def _request_object():
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:
                raise ValueError()
            result[key]=value
        return result
    def constant(_value):
        raise ValueError()
    def decimal(value):
        number=float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    value=None
    if request.content_length is not None and request.content_length>16384:
        raise MediaError('invalid_input')
    raw=request.stream.read(16385)
    if len(raw)>16384:
        raise MediaError('invalid_input')
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=constant,parse_float=decimal)
    except (ValueError,UnicodeError,RecursionError):
        pass
    if type(value) is not dict:
        raise MediaError('invalid_input')
    return value


def _query(allowed, default=50, maximum=100):
    if set(request.args)-set(allowed)-{'limit','offset'} or any(len(request.args.getlist(k))!=1 for k in request.args):
        raise MediaError('invalid_input')
    result=dict(request.args)
    for key,fallback,high in (('limit',default,maximum),('offset',0,4000)):
        text=result.get(key,str(fallback))
        if not re.fullmatch(r'\d{1,4}',text) or not (1 if key=='limit' else 0)<=int(text)<=high:
            raise MediaError('invalid_input')
        result[key]=int(text)
    return result


def register_media_library(app, db, Problem, body, require_member, audit):
    """Explicit root-owned wiring; the public engine owns its own connections."""
    with app.app_context():
        initialize_media_library(db())
    engine=MediaLibrary(app)
    app.extensions['household_media']=engine

    @app.errorhandler(MediaError)
    def media_error(error):
        return jsonify(error=error.message,code=error.code),error.status

    @app.route('/api/media/imports',methods=['GET','POST'])
    def media_imports():
        require_member()
        if request.method=='POST':
            result=engine.create_import(_request_object())
            return jsonify(result),200 if result['replayed'] else 202
        query=_query(set(),maximum=50)
        with engine.transaction() as con:
            owner=engine._member(con)
            rows=con.execute('SELECT * FROM media_imports WHERE owner=? ORDER BY created_at DESC,id',(owner,)).fetchall()
            selected=rows[query['offset']:query['offset']+query['limit']]
            items=[engine._import_dto(r) for r in selected]
            for item in items:
                item.pop('pickerUri',None)
            return jsonify(items=items,total=len(rows),limit=query['limit'],offset=query['offset'],hasMore=query['offset']+query['limit']<len(rows))

    @app.route('/api/media/imports/<uid>',methods=['GET','DELETE'])
    def media_import_detail(uid):
        require_member()
        return jsonify(engine.import_detail(uid) if request.method=='GET' else engine.cancel_import(uid,_request_object()))

    @app.post('/api/media/imports/<uid>/confirm')
    def media_import_confirm(uid):
        require_member()
        return jsonify(engine.confirm_import(uid,_request_object()))

    @app.get('/api/media/items')
    def media_items():
        require_member()
        query=_query({'scope','journeyId'})
        scope=query.get('scope','mine')
        if scope not in ('mine','visible','shared'):
            raise MediaError('invalid_input')
        with engine.transaction() as con:
            owner=engine._member(con)
            clause={'mine':'owner=?','visible':"(owner=? OR visibility='shared')",'shared':"owner!=? AND visibility='shared'"}[scope]
            params=[owner]
            if 'journeyId' in query:
                clause+=' AND journey_id=?'
                params.append(_id(query['journeyId']))
            rows=con.execute('SELECT '+ITEM_VIEW+" FROM media_items WHERE state='ready' AND "+clause+' ORDER BY updated_at DESC,id',params).fetchall()
            rows=[r for r in rows if r['owner']==owner or engine._authority(con,r['account_id'],r['owner'])]
            selected=rows[query['offset']:query['offset']+query['limit']]
            return jsonify(items=[engine._item_dto(con,r,owner) for r in selected],total=len(rows),limit=query['limit'],offset=query['offset'],hasMore=query['offset']+query['limit']<len(rows))

    @app.route('/api/media/items/<uid>',methods=['GET','PATCH','DELETE'])
    def media_item(uid):
        require_member()
        if request.method=='PATCH':
            return jsonify(engine.patch_item(uid,_request_object()))
        if request.method=='DELETE':
            return jsonify(engine.delete_item(uid,_request_object()))
        with engine.transaction() as con:
            owner=engine._member(con)
            return jsonify(item=engine._item_dto(con,engine._item(con,uid,owner),owner))

    @app.get('/api/media/items/<uid>/preview')
    def media_preview(uid):
        require_member()
        return engine.preview(uid)

    @app.get('/api/media/items/<uid>/journey-suggestions')
    def media_journey_suggestions(uid):
        require_member()
        if request.args:
            raise MediaError('invalid_input')
        return jsonify(engine.journey_suggestions(uid))

    @app.route('/api/media/items/<uid>/tv-grants',methods=['GET','PUT'])
    def media_tv_grants(uid):
        require_member()
        return jsonify(engine.tv_grants(uid,_request_object() if request.method=='PUT' else None))

    @app.get('/api/media-tv/items')
    def media_tv_items():
        query=_query(set())
        with engine.transaction() as con:
            device=engine._tv(con)
            columns=','.join('m.'+column for column in ITEM_VIEW.split(','))
            rows=con.execute('SELECT '+columns+" FROM media_items m JOIN media_tv_grants t ON t.media_id=m.id WHERE t.device_id=? AND m.state='ready' AND m.visibility='shared' ORDER BY m.updated_at DESC,m.id",(device,)).fetchall()
            rows=[r for r in rows if engine._authority(con,r['account_id'],r['owner'])]
            selected=rows[query['offset']:query['offset']+query['limit']]
            return jsonify(items=[engine._item_dto(con,r,television=True) for r in selected],limit=query['limit'],offset=query['offset'],hasMore=query['offset']+query['limit']<len(rows),validUntil=_iso(engine.clock()+15))

    @app.get('/api/media-tv/items/<uid>/preview')
    def media_tv_preview(uid):
        return engine.preview(uid,True)

    return engine
