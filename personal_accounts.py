"""Personal authentication and platform-first membership coordination.

Household users remain the sole business owners. This module is not installed by
importing it: Root wires the separate Flask application before household routing.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from flask import Flask, has_request_context, jsonify, request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash


MAX_VERSION = 9007199254740991
ID = re.compile(r'[0-9a-f]{32}')
SCHEMA = (
    """CREATE TABLE personal_accounts(
      id TEXT PRIMARY KEY, login TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
      auth_version INTEGER NOT NULL CHECK(auth_version>0), created_at REAL NOT NULL)""",
    """CREATE TABLE personal_browsers(
      browser_hash TEXT PRIMARY KEY, generation INTEGER NOT NULL,
      csrf_hash TEXT NOT NULL, expires_at REAL NOT NULL)""",
    """CREATE TABLE personal_sessions(
      id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES personal_accounts(id),
      credential_hash TEXT UNIQUE NOT NULL, csrf_hash TEXT NOT NULL,
      browser_hash TEXT NOT NULL REFERENCES personal_browsers(browser_hash),
      generation INTEGER NOT NULL, auth_version INTEGER NOT NULL,
      created_at REAL NOT NULL, expires_at REAL NOT NULL, verified_at REAL NOT NULL,
      revoked_at REAL)""",
    """CREATE TABLE account_memberships(
      membership_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES personal_accounts(id),
      household_id TEXT NOT NULL REFERENCES households(id), member_id TEXT NOT NULL,
      UNIQUE(account_id,household_id), UNIQUE(household_id,member_id))""",
    """CREATE TABLE account_operations(
      subject TEXT NOT NULL, request_id TEXT NOT NULL, account_id TEXT,
      browser_hash TEXT NOT NULL, browser_generation INTEGER NOT NULL,
      browser_csrf_hash TEXT NOT NULL, kind TEXT NOT NULL, household_id TEXT,
      intent_digest TEXT NOT NULL, details TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('pending','completed','not_committed')),
      result TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
      PRIMARY KEY(subject,request_id), UNIQUE(account_id,request_id))""",
    """CREATE TABLE account_qualifications(
      token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('member','invitation')),
      browser_hash TEXT NOT NULL, generation INTEGER NOT NULL, account_id TEXT,
      proof TEXT NOT NULL, expires_at REAL NOT NULL, used_request TEXT, used_account TEXT)""",
    """CREATE TABLE personal_limits(
      id TEXT PRIMARY KEY, window INTEGER NOT NULL, attempts INTEGER NOT NULL)""",
)
TABLES = {'personal_accounts', 'personal_browsers', 'personal_sessions',
          'account_memberships', 'account_operations', 'account_qualifications', 'personal_limits'}


class PersonalAccountError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def init_schema(con):
    """Called during controlled initialization, never by an authenticated request."""
    if con.in_transaction:
        raise RuntimeError('Personal schema requires an independent transaction')
    con.execute('BEGIN IMMEDIATE')
    try:
        present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} & TABLES
        version = con.execute('PRAGMA user_version').fetchone()[0]
        if (version, len(present)) not in ((0, 0), (1, len(TABLES))):
            raise PersonalAccountError('个人账户结构不完整', 503)
        if not present:
            for sql in SCHEMA:
                con.execute(sql)
            con.execute('PRAGMA user_version=1')
        con.commit()
    except BaseException:
        con.rollback()
        raise


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def request_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise PersonalAccountError('请提供有效的操作编号')
    return value


def positive(value):
    if type(value) is not int or not 1 <= value <= MAX_VERSION:
        raise PersonalAccountError('请提供有效的版本')
    return value


@dataclass(frozen=True)
class Identity:
    browser_hash: str
    generation: int
    csrf_hash: str
    session_id: str | None = None
    account_id: str | None = None
    auth_version: int | None = None
    credential_hash: str | None = None


class PersonalAccounts:
    COOKIE = 'personal_account'
    Error = PersonalAccountError

    def __init__(self, platform, callbacks):
        self.platform, self.callbacks = platform, dict(callbacks)
        self.path = Path(platform.path).resolve()
        self.secret = str(platform.app.secret_key).encode('utf-8')
        self.signer = URLSafeTimedSerializer(platform.app.secret_key, salt='personal-account-v1')
        self.ttl = int(platform.app.permanent_session_lifetime.total_seconds())
        self.secure = bool(platform.app.config.get('SESSION_COOKIE_SECURE', True))
        self.origin = platform.app.config.get('PUBLIC_ORIGIN')
        self.local = threading.local()
        self.dummy_password = generate_password_hash(secrets.token_urlsafe(32))
        with self.connection() as con:
            init_schema(con)
        self.app = Flask(__name__ + '.personal')
        self.app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
        self._routes()

    @property
    def guard_con(self):
        state = getattr(self.local, 'guard', None)
        return state['con'] if state else None

    @staticmethod
    def identity_dict(identity):
        return dict(zip(('browserHash','generation','csrfHash','sessionId','accountId','authVersion','credentialHash'),
                        (identity.browser_hash,identity.generation,identity.csrf_hash,identity.session_id,
                         identity.account_id,identity.auth_version,identity.credential_hash)))

    @staticmethod
    def _coerce(identity):
        if isinstance(identity, dict):
            keys = ('browserHash','generation','csrfHash','sessionId','accountId','authVersion','credentialHash')
            if set(identity) != set(keys):
                raise PersonalAccountError('个人会话格式不正确', 401)
            identity = Identity(*(identity[k] for k in keys))
        if (not isinstance(identity, Identity) or type(identity.generation) is not int
                or not 0 <= identity.generation <= MAX_VERSION
                or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v)
                       for v in (identity.browser_hash,identity.csrf_hash))
                or (identity.session_id is None and any(v is not None for v in
                     (identity.account_id,identity.auth_version,identity.credential_hash)))
                or (identity.session_id is not None and
                    (any(not isinstance(v,str) or not ID.fullmatch(v) for v in (identity.session_id,identity.account_id))
                     or type(identity.auth_version) is not int or not 1 <= identity.auth_version <= MAX_VERSION
                     or not isinstance(identity.credential_hash,str) or not re.fullmatch('[0-9a-f]{64}',identity.credential_hash)))):
            raise PersonalAccountError('个人会话格式不正确', 401)
        return identity

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            yield con
        finally:
            con.rollback()
            con.close()

    @contextmanager
    def guard(self, identity=None, *, require=False, recent=False):
        """Reentrant platform write guard; acquire BEFORE any household lock.

        Nested users share the same connection. An exception in any nested scope
        poisons the outer transaction even if a caller catches that exception.
        """
        state = getattr(self.local, 'guard', None)
        if state is not None:
            try:
                if identity is not None:
                    self.current(state['con'], identity, require=require, recent=recent)
                yield state['con']
            except BaseException:
                state['failed'] = True
                raise
            return
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            state = {'con': con, 'failed': False}
            self.local.guard = state
            try:
                if identity is not None:
                    self.current(con, identity, require=require, recent=recent)
                yield con
                if state['failed']:
                    raise PersonalAccountError('账户操作未完成，请核对当前状态', 503)
                con.commit()
            finally:
                self.local.guard = None
                con.rollback()

    def current(self, con, identity, *, require=False, recent=False):
        identity = self._coerce(identity)
        now = time.time()
        browser = con.execute('SELECT * FROM personal_browsers WHERE browser_hash=?',
                              (identity.browser_hash,)).fetchone()
        if (not browser or browser['expires_at'] <= now or browser['generation'] != identity.generation
                or browser['csrf_hash'] != identity.csrf_hash):
            raise PersonalAccountError('个人会话已变化，请重新核对', 401)
        if identity.session_id is None:
            if require or recent:
                raise PersonalAccountError('请先登录个人账户', 401)
            return None
        row = con.execute('''SELECT s.*,a.login,a.auth_version AS current_version
            FROM personal_sessions s JOIN personal_accounts a ON a.id=s.account_id WHERE s.id=?''',
                          (identity.session_id,)).fetchone()
        if (not row or row['revoked_at'] is not None or row['expires_at'] <= now
                or row['current_version'] != row['auth_version']
                or (row['account_id'], row['auth_version'], row['credential_hash'], row['csrf_hash'],
                    row['browser_hash'], row['generation']) !=
                (identity.account_id, identity.auth_version, identity.credential_hash, identity.csrf_hash,
                 identity.browser_hash, identity.generation)):
            raise PersonalAccountError('个人会话已失效，请重新登录', 401)
        if recent and not 0 <= now - row['verified_at'] <= 300:
            raise PersonalAccountError('请重新输入个人账户密码后绑定', 401)
        return dict(row) | {'accountId': row['account_id']}

    def signed(self, raw):
        try:
            value = self.signer.loads(raw, max_age=self.ttl)
        except (BadSignature, TypeError, ValueError):
            return None
        if (not isinstance(value, dict) or set(value) != {'browser', 'csrf', 'credential', 'generation'}
                or type(value['generation']) is not int or not 0 <= value['generation'] <= MAX_VERSION
                or any(not isinstance(value[k], str) or not 32 <= len(value[k]) <= 128 for k in ('browser', 'csrf'))
                or (value['credential'] is not None and
                    (not isinstance(value['credential'], str) or not 32 <= len(value['credential']) <= 128))):
            return None
        return value

    def _identity(self, con, value):
        if value is None:
            raise PersonalAccountError('请先读取个人账户状态', 401)
        args = (digest(value['browser']), value['generation'], digest(value['csrf']))
        if value['credential'] is None:
            return Identity(*args)
        row = con.execute('SELECT * FROM personal_sessions WHERE credential_hash=?',
                          (digest(value['credential']),)).fetchone()
        if not row:
            raise PersonalAccountError('个人会话已失效，请重新登录', 401)
        return Identity(*args, row['id'], row['account_id'], row['auth_version'], row['credential_hash'])

    def capture(self, raw_cookie=None, *, require=True, csrf=False, recent=False, csrf_header='X-CSRF-Token'):
        value = self.signed(raw_cookie if raw_cookie is not None else
                            request.cookies.get(self.COOKIE) if has_request_context() else None)
        if csrf:
            self._csrf(value, csrf_header)
        with self.guard() as con:
            identity = self._identity(con, value)
            self.current(con, identity, require=require, recent=recent)
            return identity

    def _csrf(self, value, header='X-CSRF-Token'):
        origin = request.headers.get('Origin')
        expected = self.origin or request.host_url.rstrip('/')
        if origin and origin != expected:
            raise PersonalAccountError('不允许跨站操作', 403)
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise PersonalAccountError('不允许跨站操作', 403)
        supplied = request.headers.get(header, '')
        if not value or not supplied or not hmac.compare_digest(supplied, value['csrf']):
            raise PersonalAccountError('请重新读取个人账户状态', 403)

    def _cookie(self, response, value):
        response.set_cookie(self.COOKIE, self.signer.dumps(value), max_age=self.ttl,
                            httponly=True, secure=self.secure, samesite='Lax', path='/')
        return response

    def _callback(self, name):
        value = self.callbacks.get(name)
        if value is None:
            raise PersonalAccountError('账户接线暂未就绪', 503)
        return value

    def _limit(self, bucket, maximum=20):
        key = self.intent_digest({'limit': bucket, 'remote': request.remote_addr or 'local'})
        window = int(time.time() // 60)
        with self.guard() as con:
            con.execute('''INSERT INTO personal_limits VALUES(?,?,1) ON CONFLICT(id) DO UPDATE SET
                attempts=CASE WHEN window=excluded.window THEN attempts+1 ELSE 1 END,window=excluded.window''',
                        (key, window))
            count = con.execute('SELECT attempts FROM personal_limits WHERE id=?', (key,)).fetchone()[0]
        if count > maximum:
            raise PersonalAccountError('操作过于频繁，请稍后再试', 429)

    def intent_digest(self, value):
        return hmac.new(self.secret, b'personal-intent-v1\0' + canonical(value).encode(), hashlib.sha256).hexdigest()

    def _body(self, fields):
        if request.args:
            raise PersonalAccountError('不接受查询参数')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate')
                result[key] = value
            return result
        try:
            value = json.loads(request.get_data(), object_pairs_hook=unique,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))
        except (ValueError, UnicodeError):
            raise PersonalAccountError('请提交无重复字段的 JSON 对象') from None
        if not isinstance(value, dict) or set(value) != set(fields):
            raise PersonalAccountError('请只提交本操作允许的字段')
        return value

    @contextmanager
    def household(self, platform_con, household_id, *, write=False):
        if not getattr(self.local, 'guard', None) or self.local.guard['con'] is not platform_con:
            raise RuntimeError('Platform guard must precede household access')
        if not platform_con.execute('SELECT 1 FROM households WHERE id=?', (household_id,)).fetchone():
            raise PersonalAccountError('家庭不存在', 404)
        with self._callback('household')(household_id) as con:
            if con.in_transaction:
                raise RuntimeError('Household callback must supply an idle connection')
            con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield con
                if write:
                    con.commit()
            finally:
                con.rollback()

    def _rotate(self, con, identity, account=None, *, verified_at=None):
        self.current(con, identity)
        if identity.generation >= MAX_VERSION:
            raise PersonalAccountError('浏览器认证版本已达上限，请使用新浏览器会话', 409)
        now, generation, csrf = time.time(), identity.generation + 1, secrets.token_urlsafe(32)
        con.execute('UPDATE personal_sessions SET revoked_at=? WHERE browser_hash=? AND revoked_at IS NULL',
                    (now, identity.browser_hash))
        con.execute('UPDATE personal_browsers SET generation=?,csrf_hash=?,expires_at=? WHERE browser_hash=?',
                    (generation, digest(csrf), now + self.ttl, identity.browser_hash))
        credential = secrets.token_urlsafe(32) if account else None
        if account:
            con.execute('INSERT INTO personal_sessions VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',
                        (secrets.token_hex(16), account['id'], digest(credential), digest(csrf),
                         identity.browser_hash, generation, account['auth_version'], now, now + self.ttl,
                         now if verified_at is None else verified_at))
        raw = self.signed(request.cookies.get(self.COOKIE))
        if raw is None or digest(raw['browser']) != identity.browser_hash:
            raise PersonalAccountError('浏览器身份已变化', 401)
        return {'browser': raw['browser'], 'csrf': csrf, 'credential': credential, 'generation': generation}

    def _qualification(self, con, identity, raw, *, kind=None):
        if not isinstance(raw, str) or not 32 <= len(raw) <= 128:
            raise PersonalAccountError('注册或加入资格已失效', 409)
        row = con.execute('SELECT * FROM account_qualifications WHERE token_hash=?', (digest(raw),)).fetchone()
        if (not row or row['expires_at'] <= time.time() or row['used_request'] is not None
                or (row['browser_hash'], row['generation'], row['account_id']) !=
                (identity.browser_hash, identity.generation, identity.account_id)
                or (kind is not None and row['kind'] != kind)):
            raise PersonalAccountError('注册或加入资格已失效，请重新核对', 409)
        return dict(row), json.loads(row['proof'])

    def _issue(self, con, identity, kind, proof):
        raw, expires = secrets.token_urlsafe(32), time.time() + 300
        con.execute('INSERT INTO account_qualifications VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                    (digest(raw), kind, identity.browser_hash, identity.generation, identity.account_id,
                     canonical(proof), expires))
        return raw, stamp(expires)

    def _validate_proof(self, con, kind, proof):
        if kind == 'member':
            self._callback('validate_member_proof')(con, proof)
        else:
            with self.household(con, proof['householdId']) as household:
                self._callback('membership').validate_invitation(household,
                    invitation_id=proof['invitationId'], expected_revision=proof['revision'])

    @staticmethod
    def _operation(row):
        return {'requestId': row['request_id'], 'found': True, 'state': row['state'],
                'result': json.loads(row['result']) if row['state'] == 'completed' else None}

    def _operation_row(self, con, identity, rid):
        return con.execute('SELECT * FROM account_operations WHERE account_id=? AND request_id=?',
                           (identity.account_id, rid)).fetchone()

    def _insert_operation(self, con, identity, rid, kind, household_id, intent, details,
                          *, subject=None, state='pending', result=None, account_id=None):
        now = time.time()
        con.execute('INSERT INTO account_operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (subject or 'account:' + identity.account_id, rid, account_id or identity.account_id,
                     identity.browser_hash, identity.generation, identity.csrf_hash, kind, household_id,
                     intent, canonical(details), state, canonical(result) if result is not None else None, now, now))

    def _finish(self, con, row, result):
        if row['kind'] in ('bind', 'accept', 'leave'):
            fields = {'id', 'householdId', 'memberId', 'memberName', 'householdRole', 'state', 'revision'}
            if not isinstance(result, dict) or set(result) != fields or result['householdId'] != row['household_id']:
                raise PersonalAccountError('成员回执格式无法核对', 503)
            expected=(result['id'],row['account_id'],result['householdId'],result['memberId'])
            existing=con.execute('SELECT * FROM account_memberships WHERE membership_id=?',(result['id'],)).fetchone()
            if existing and tuple(existing)!=expected:
                raise PersonalAccountError('家庭关系索引与原归属不一致',503)
            if not existing:
                con.execute('INSERT INTO account_memberships VALUES(?,?,?,?)',expected)
        details = json.loads(row['details'])
        if 'qualificationHash' in details:
            con.execute('UPDATE account_qualifications SET used_request=?,used_account=? WHERE token_hash=?',
                        (row['request_id'], row['account_id'], details['qualificationHash']))
        con.execute("UPDATE account_operations SET state='completed',result=?,updated_at=? WHERE subject=? AND request_id=?",
                    (canonical(result), time.time(), row['subject'], row['request_id']))

    def coordinate(self, identity, rid, kind, household_id, intent, perform, *, details=None, recent=False, completion=None):
        """Persist pending, then platform -> household; never replay a pending write.

        perform(platform_con, household_con, operation) must record its result in
        the SAME household transaction via the domain's account operation receipt.
        Secrets participate only in intent_digest; details holds only a ticket hash.
        """
        request_id(rid)
        identity = self._coerce(identity)
        completion = completion if completion is not None else {}
        if getattr(self.local, 'guard', None) is not None:
            raise RuntimeError('Pending must commit before entering the coordination guard')
        if kind not in ('bind', 'accept', 'leave', 'switch'):
            raise PersonalAccountError('不支持此账户操作')
        details = details or {}
        if set(details) - {'qualificationHash'} or any(not re.fullmatch('[0-9a-f]{64}', v) for v in details.values()):
            raise ValueError('Only a non-secret qualification hash is persisted')
        intent_hash = self.intent_digest({'kind': kind, 'householdId': household_id, 'intent': intent})
        with self.guard(identity, require=True, recent=recent) as con:
            previous = self._operation_row(con, identity, rid)
            if previous:
                if previous['intent_digest'] != intent_hash:
                    raise PersonalAccountError('操作编号已用于不同意图', 409)
                return self._operation(previous)
            self._insert_operation(con, identity, rid, kind, household_id, intent_hash, details)
        self._hook('pending_committed')
        with self.guard(identity, require=True, recent=recent) as con:
            row = self._operation_row(con, identity, rid)
            if row['state'] != 'pending':
                return self._operation(row)
            with self.household(con, household_id, write=True) as household:
                result = perform(con, household, dict(row))
                self.current(con, completion.get('identity',identity), require=True, recent=recent)
            self._hook('household_committed')
            self._finish(con, row, result)
            self.current(con, completion.get('identity',identity), require=True, recent=recent)
            return {'requestId': rid, 'found': True, 'state': 'completed', 'result': result}

    def _hook(self, name):
        # Optional deterministic test/host crash boundary, never a network action.
        hook = self.callbacks.get('boundary')
        if hook:
            hook(name)

    def _member_change(self, body, *, leave):
        fields = {'requestId','expectedAuthVersion','expectedRevision'} | (set() if leave else {'memberPassword'})
        if not isinstance(body,dict) or set(body)!=fields:
            raise PersonalAccountError('请只提交成员操作允许的字段')
        request_id(body['requestId']); positive(body['expectedAuthVersion']); positive(body['expectedRevision'])
        if not leave and (not isinstance(body['memberPassword'],str) or not 1<=len(body['memberPassword'])<=128):
            raise PersonalAccountError('请提供有效的家庭密码')
        identity = self.capture(csrf=True,csrf_header='X-Account-CSRF-Token')
        with self.guard(identity,require=True) as con:
            previous=self._operation_row(con,identity,body['requestId'])
            if previous:
                expected=self.intent_digest({'kind':'leave' if leave else 'bind','householdId':previous['household_id'],
                    'intent':{k:v for k,v in body.items() if k!='requestId'}})
                if previous['intent_digest']!=expected:
                    raise PersonalAccountError('操作编号已用于不同意图',409)
                state=self._operation(previous)
                return state['result'] if state['state']=='completed' else state
            self.current(con,identity,require=True,recent=not leave)
            proof = self._callback('member_proof')(con,None if leave else body['memberPassword'])
            if proof['authVersion']!=body['expectedAuthVersion'] or proof['membershipRevision']!=body['expectedRevision']:
                raise PersonalAccountError('当前家庭身份已变化，请重新核对',409)
        def perform(con, household, operation):
            self._callback('validate_member_proof')(con,proof,household_con=household)
            common = dict(household_id=proof['householdId'],member_id=proof['memberId'],account_id=identity.account_id,
                expected_auth_version=body['expectedAuthVersion'],expected_revision=body['expectedRevision'],
                request_id=body['requestId'],intent_digest=operation['intent_digest'])
            domain = self._callback('membership')
            if leave:
                return domain.leave_membership(household,**common)
            count=con.execute('SELECT count(*) FROM account_memberships WHERE account_id=?',(identity.account_id,)).fetchone()[0]
            if count>=30 and not con.execute('SELECT 1 FROM account_memberships WHERE account_id=? AND household_id=?',
                                             (identity.account_id,proof['householdId'])).fetchone():
                raise PersonalAccountError('所属家庭数量已达上限',409)
            return domain.bind_account(household,member_password=body['memberPassword'],**common)
        state=self.coordinate(identity,body['requestId'],'leave' if leave else 'bind',proof['householdId'],
                              {k:v for k,v in body.items() if k!='requestId'},perform,recent=not leave)
        return state['result'] if state['state']=='completed' else state

    def handle_bind(self, body):
        """Root verifies household CSRF before calling; personal CSRF is distinct."""
        return self._member_change(body,leave=False)

    def handle_leave(self, body):
        """Expected self-revocation does not revoke the independent personal proof."""
        return self._member_change(body,leave=True)

    def resume(self, identity, rid):
        identity = self._coerce(identity)
        request_id(rid)
        with self.guard(identity, require=True) as con:
            row = self._operation_row(con, identity, rid)
            if not row:
                return {'requestId': rid, 'found': False, 'state': None, 'result': None}
            if row['state'] != 'pending':
                return self._operation(row)
            try:
                with self.household(con, row['household_id'], write=True) as household:
                    receipt = self._callback('membership').operation(household,
                        subject=row['subject'], request_id=rid, intent_digest=row['intent_digest'])
                    self.current(con, identity, require=True)
                    if receipt['found']:
                        if receipt['state'] != 'completed':
                            return self._operation(row)
                        self._finish(con, row, receipt['result'])
                    else:
                        con.execute("UPDATE account_operations SET state='not_committed',updated_at=? WHERE subject=? AND request_id=?",
                                    (time.time(), row['subject'], rid))
            except (sqlite3.OperationalError, OSError):
                return self._operation(row)
            self.current(con, identity, require=True)
            return self._operation(self._operation_row(con, identity, rid))

    def _routes(self):
        app = self.app

        @app.before_request
        def no_tv():
            if self._callback('is_tv')():
                raise PersonalAccountError('电视不能操作个人账户', 403)

        domain = self.callbacks.get('membership')
        if domain is not None:
            app.register_error_handler(domain.MembershipError,
                lambda exc: (jsonify(error=str(exc), **({'code':exc.code} if exc.code else {})), exc.status))

        @app.after_request
        def private(response):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response

        @app.errorhandler(PersonalAccountError)
        def error(exc):
            value = {'error': exc.message}
            if exc.code:
                value['code'] = exc.code
            return jsonify(value), exc.status

        @app.errorhandler(sqlite3.Error)
        @app.errorhandler(OSError)
        def storage_error(exc):
            return jsonify(error='账户资料暂不可用，请稍后核对'),503

        @app.get('/api/account/me')
        def me():
            if request.args:
                raise PersonalAccountError('不接受查询参数')
            value, row = self.signed(request.cookies.get(self.COOKIE)), None
            with self.guard() as con:
                try:
                    identity = self._identity(con, value)
                    row = self.current(con, identity)
                except PersonalAccountError:
                    value = {'browser': secrets.token_urlsafe(32), 'csrf': secrets.token_urlsafe(32),
                             'credential': None, 'generation': 0}
                    con.execute('INSERT INTO personal_browsers VALUES(?,?,?,?)',
                                (digest(value['browser']), 0, digest(value['csrf']), time.time() + self.ttl))
                result = {'account': {'id': row['account_id'], 'login': row['login']} if row else None,
                          'csrf': value['csrf'], 'authVersion': row['auth_version'] if row else None,
                          'authenticationGeneration': value['generation']}
            return self._cookie(jsonify(result), value)

        @app.post('/api/account/eligibility')
        def eligibility():
            body = self._body({'memberPassword'})
            self._limit('eligibility')
            identity = self.capture(require=False, csrf=True)
            if not isinstance(body['memberPassword'], str) or not 1 <= len(body['memberPassword']) <= 128:
                raise PersonalAccountError('请提供有效的家庭密码')
            with self.guard(identity) as con:
                proof = self._callback('member_proof')(con, body['memberPassword'])
                if not isinstance(proof, dict) or set(proof) != {'householdId','memberId','authVersion','sessionId','membershipRevision'}:
                    raise PersonalAccountError('家庭资格无法核对', 503)
                raw, expires = self._issue(con, identity, 'member', proof)
                self.current(con, identity)
            return jsonify(eligibilityToken=raw, expiresAt=expires)

        @app.post('/api/account/invitations/inspect')
        def inspect_invitation():
            body = self._body({'householdSlug', 'token'})
            self._limit('invitation-inspect')
            identity = self.capture(require=False, csrf=True)
            if not isinstance(body['householdSlug'], str) or not re.fullmatch(r'[a-z0-9-]{1,64}', body['householdSlug']):
                raise PersonalAccountError('请提供有效家庭地址')
            if not isinstance(body['token'], str) or not 32 <= len(body['token']) <= 256:
                raise PersonalAccountError('邀请无效', 404)
            with self.guard(identity) as con:
                target = con.execute('SELECT * FROM households WHERE slug=?', (body['householdSlug'],)).fetchone()
                if not target:
                    raise PersonalAccountError('邀请无效', 404)
                with self.household(con, target['id']) as household:
                    invite = self._callback('membership').inspect_invitation(household, body['token'])
                proof = {'householdId': target['id'], 'invitationId': invite['id'], 'revision': invite['revision']}
                raw, expires = self._issue(con, identity, 'invitation', proof)
                self.current(con, identity)
            return jsonify(household={'id': target['id'], 'name': target['name'], 'slug': target['slug']}, householdRole='member',
                           joinTicket=raw, eligibilityToken=raw, expiresAt=expires)

        @app.post('/api/account/register')
        def register():
            body = self._body({'requestId', 'login', 'password', 'eligibilityToken'})
            self._limit('register', 10)
            rid = request_id(body['requestId'])
            login, password = self._login_input(body)
            value = self.signed(request.cookies.get(self.COOKIE))
            self._csrf(value)
            intent = self.intent_digest({'login': login, 'password': password, 'eligibilityToken': body['eligibilityToken']})
            with self.guard() as con:
                previous = self._registration_receipt(con, value, rid)
                if previous:
                    if previous['intent_digest'] != intent:
                        raise PersonalAccountError('操作编号已用于不同注册内容', 409)
                    return jsonify(json.loads(previous['result']))
                identity = self._identity(con, value)
                self.current(con, identity)
                if identity.account_id is not None:
                    raise PersonalAccountError('请先退出当前个人账户', 409)
                qualification, proof = self._qualification(con, identity, body['eligibilityToken'])
                self._validate_proof(con, qualification['kind'], proof)
                if con.execute('SELECT 1 FROM personal_accounts WHERE login=?', (login,)).fetchone():
                    raise PersonalAccountError('该登录名暂不可用，请核对已有账户', 409)
                account = {'id': secrets.token_hex(16), 'login': login, 'auth_version': 1}
                con.execute('INSERT INTO personal_accounts VALUES(?,?,?,?,?)',
                            (account['id'], login, generate_password_hash(password), 1, time.time()))
                # Hashing may cross the 300s boundary; recheck both proofs before committing.
                self._qualification(con, identity, body['eligibilityToken'])
                self._validate_proof(con, qualification['kind'], proof)
                self.current(con, identity)
                result = {'account': {'id': account['id'], 'login': login}}
                self._insert_operation(con, identity, rid, 'register', None, intent, {},
                    subject='browser:' + identity.browser_hash, state='completed', result=result, account_id=account['id'])
                con.execute('UPDATE account_qualifications SET used_request=?,used_account=? WHERE token_hash=?',
                            (rid, account['id'], qualification['token_hash']))
                new_cookie = self._rotate(con, identity, account)
            return self._cookie(jsonify(result), new_cookie), 201

        @app.post('/api/account/login')
        def login():
            body = self._body({'login', 'password'})
            self._limit('login')
            login_name, password = self._login_input(body)
            identity = self.capture(require=False, csrf=True)
            with self.guard(identity) as con:
                account = con.execute('SELECT * FROM personal_accounts WHERE login=?', (login_name,)).fetchone()
                valid = check_password_hash(account['password'] if account else self.dummy_password, password)
                if not account or not valid:
                    raise PersonalAccountError('登录名或密码不正确', 401)
                cookie = self._rotate(con, identity, account)
                result = {'account': {'id': account['id'], 'login': account['login']}}
            return self._cookie(jsonify(result), cookie)

        @app.post('/api/account/logout')
        def logout():
            body = self._body({'requestId'}); rid = request_id(body['requestId'])
            identity = self.capture(csrf=True)
            with self.guard(identity, require=True) as con:
                row = self._operation_row(con, identity, rid)
                intent = self.intent_digest({'kind': 'logout'})
                if row:
                    if row['intent_digest'] != intent:
                        raise PersonalAccountError('操作编号已用于不同意图', 409)
                    return jsonify(self._operation(row)['result'])
                self._insert_operation(con, identity, rid, 'logout', None, intent, {}, state='completed', result={'ok': True})
                cookie = self._rotate(con, identity)
            return self._cookie(jsonify(ok=True), cookie)

        @app.get('/api/account/operations/<rid>')
        def operations(rid):
            request_id(rid)
            if request.args:
                raise PersonalAccountError('不接受查询参数')
            value = self.signed(request.cookies.get(self.COOKIE))
            with self.guard() as con:
                registered = self._registration_receipt(con, value, rid)
                if registered:
                    return jsonify(self._operation(registered))
                identity = self._identity(con, value)
                self.current(con, identity, require=True)
                row = con.execute('SELECT * FROM account_operations WHERE request_id=? AND account_id=?',
                                  (rid, identity.account_id)).fetchone()
                result = self._operation(row) if row else {'requestId': rid, 'found': False, 'state': None, 'result': None}
                self.current(con, identity, require=True)
            return jsonify(result)

        @app.post('/api/account/operations/<rid>/resume')
        def resume(rid):
            self._body(set())
            return jsonify(self.resume(self.capture(csrf=True), rid))

        @app.get('/api/account/households')
        def households():
            if request.args:
                raise PersonalAccountError('不接受查询参数')
            return jsonify(self.households(self.capture()))

        @app.post('/api/account/invitations/accept')
        def accept():
            body = self._body({'requestId', 'joinTicket'})
            identity = self.capture(csrf=True)
            with self.guard(identity, require=True) as con:
                previous = self._operation_row(con, identity, request_id(body['requestId']))
                if previous:
                    expected = self.intent_digest({'kind':'accept','householdId':previous['household_id'],
                                                   'intent':{'joinTicket':body['joinTicket']}})
                    if previous['intent_digest'] != expected:
                        raise PersonalAccountError('操作编号已用于不同意图', 409)
                    state = self._operation(previous)
                    return jsonify(state['result'] if state['state']=='completed' else state)
                qualification, proof = self._qualification(con, identity, body['joinTicket'], kind='invitation')
            def perform(con, household, operation):
                self._qualification(con, identity, body['joinTicket'], kind='invitation')
                count = con.execute('SELECT count(*) FROM account_memberships WHERE account_id=?', (identity.account_id,)).fetchone()[0]
                if count >= 30 and not con.execute('SELECT 1 FROM account_memberships WHERE account_id=? AND household_id=?', (identity.account_id,proof['householdId'])).fetchone():
                    raise PersonalAccountError('所属家庭数量已达上限', 409)
                return self._callback('membership').accept_invitation(household, household_id=proof['householdId'],
                    account_id=identity.account_id, invitation_id=proof['invitationId'], expected_revision=proof['revision'],
                    request_id=body['requestId'], intent_digest=operation['intent_digest'])
            result = self.coordinate(identity, body['requestId'], 'accept', proof['householdId'],
                                     {'joinTicket': body['joinTicket']}, perform,
                                     details={'qualificationHash': qualification['token_hash']})
            return jsonify(result['result'] if result['state'] == 'completed' else result)

        @app.post('/api/account/switch-household')
        def switch():
            body = self._body({'requestId','membershipId','expectedRevision'})
            request_id(body['membershipId']); positive(body['expectedRevision'])
            identity = self.capture(csrf=True)
            with self.guard(identity,require=True) as con:
                row = con.execute('SELECT * FROM account_memberships WHERE membership_id=? AND account_id=?',
                                  (body['membershipId'],identity.account_id)).fetchone()
                if not row:
                    raise PersonalAccountError('当前账户没有这个家庭关系',404)
                household_id = row['household_id']
            completion = {}
            def perform(con, household, operation):
                member = self._callback('membership').membership_record(household,membership_id=body['membershipId'])
                if (not member or member['account_id']!=identity.account_id or member['member_id']!=row['member_id']
                        or member['state']!='active' or member['revision']!=body['expectedRevision']):
                    raise PersonalAccountError('家庭成员关系已变化，请重新核对',409)
                summary = self._callback('membership').snapshot(household,household_id,row['member_id'])
                current = self.current(con,identity,require=True)
                account = {'id':identity.account_id,'auth_version':identity.auth_version}
                cookie = self._rotate(con,identity,account,verified_at=current['verified_at'])
                new_identity = self._identity(con,cookie)
                installer = self._callback('install_member')(con,household,new_identity,summary)
                if not callable(installer):
                    raise PersonalAccountError('家庭会话安装器不可用',503)
                result = {'ok':True,'householdId':household_id,'memberId':row['member_id'],'entry':'/app/home'}
                self._callback('membership').record_operation(household,subject=operation['subject'],
                    request_id=operation['request_id'],intent_digest=operation['intent_digest'],result=result)
                completion.update(identity=new_identity,cookie=cookie,installer=installer)
                return result
            state = self.coordinate(identity,body['requestId'],'switch',household_id,
                {'membershipId':body['membershipId'],'expectedRevision':body['expectedRevision']},perform,completion=completion)
            response = jsonify(state['result'] if state['state']=='completed' else state)
            if 'cookie' in completion:
                response = completion['installer'](self._cookie(response,completion['cookie']))
            return response

    @staticmethod
    def _login_input(body):
        login, password = body['login'], body['password']
        if not isinstance(login, str) or not re.fullmatch(r'[a-z0-9._-]{3,64}', login):
            raise PersonalAccountError('登录名须为 3–64 位小写字母、数字或 ._-')
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise PersonalAccountError('密码须为 12–128 个字符')
        return login, password

    def _registration_receipt(self, con, value, rid):
        if not value or value['credential'] is not None:
            return None
        key = digest(value['browser'])
        browser = con.execute('SELECT * FROM personal_browsers WHERE browser_hash=?', (key,)).fetchone()
        row = con.execute("SELECT * FROM account_operations WHERE subject=? AND request_id=? AND kind='register'",
                          ('browser:' + key, rid)).fetchone()
        if (row and browser and browser['expires_at'] > time.time()
                and browser['generation'] == value['generation'] + 1
                and row['browser_generation'] == value['generation']
                and row['browser_csrf_hash'] == digest(value['csrf'])):
            return row
        return None

    def households(self, identity):
        identity = self._coerce(identity)
        memberships, unavailable = [], []
        with self.guard(identity, require=True) as con:
            rows = con.execute('''SELECT m.*,h.name,h.slug FROM account_memberships m
                JOIN households h ON h.id=m.household_id WHERE m.account_id=? ORDER BY m.household_id''',
                               (identity.account_id,)).fetchall()
            for row in rows:
                try:
                    with self.household(con, row['household_id']) as household:
                        item = self._callback('membership').membership_record(household, membership_id=row['membership_id'])
                        if not item or item['account_id'] != identity.account_id or item['member_id'] != row['member_id']:
                            raise PersonalAccountError('家庭关系索引无法核对', 503)
                        if item['state'] == 'active':
                            summary = self._callback('membership').snapshot(household, row['household_id'], row['member_id'])
                            memberships.append({k:v for k,v in summary.items() if k != 'state'} | {'name':row['name'], 'slug':row['slug']})
                except (OSError, sqlite3.DatabaseError, PersonalAccountError):
                    unavailable.append({'householdId':row['household_id'], 'code':'temporarily_unavailable'})
            self.current(con, identity, require=True)
        return {'memberships':memberships, 'unavailable':unavailable}
