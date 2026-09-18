"""Household-local membership domain; callers own authentication and transactions.

No platform connection, HTTP/cookie handling or commit lives here. Cross-database
callers lock platform before household and check captured credentials themselves.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
import secrets
import time

from werkzeug.security import check_password_hash, generate_password_hash


MAX_VERSION = 9007199254740991
MAX_ACTIVE_MEMBERS = 100
MAX_PENDING_INVITATIONS = 20
INVITATION_TTL = 7 * 24 * 60 * 60
TABLES = ('household_memberships', 'member_invitations', 'membership_operations')
SCHEMA_STATEMENTS = (
    """CREATE TABLE household_memberships(
        id TEXT PRIMARY KEY, member_id TEXT NOT NULL UNIQUE REFERENCES users(id),
        account_id TEXT UNIQUE, state TEXT NOT NULL CHECK(state IN ('active','left','removed')),
        revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991),
        created_at REAL NOT NULL, updated_at REAL NOT NULL)""",
    """CREATE TABLE member_invitations(
        id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
        creator_member_id TEXT NOT NULL REFERENCES users(id), creator_auth_version INTEGER NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','used','revoked')),
        revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991),
        created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL,
        used_at REAL, used_by_account_id TEXT)""",
    """CREATE TABLE membership_operations(
        subject TEXT NOT NULL, request_id TEXT NOT NULL, kind TEXT NOT NULL,
        intent_digest TEXT NOT NULL, member_id TEXT REFERENCES users(id),
        result_json TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY(subject,request_id))""",
)
HOUSEHOLD_MEMBERSHIPS_SCHEMA_SQL = ';\n'.join(SCHEMA_STATEMENTS) + ';'


class MembershipError(Exception):
    def __init__(self, message, status=400, code='invalid_membership_request'):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def _fail(message, status=409, code='membership_conflict'):
    raise MembershipError(message, status, code)


def _identifier(value, label='成员编号'):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        _fail(label + '格式不正确', 400, 'invalid_membership_request')
    return value


def _hex(value, size=32):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(size) + '}', value):
        _fail('操作或账户编号格式不正确', 400, 'invalid_membership_request')
    return value


def _version(value):
    if type(value) is not int or not 1 <= value <= MAX_VERSION:
        _fail('请提供有效版本', 400, 'invalid_membership_request')
    return value


def _now(value):
    value = time.time() if value is None else value
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253401696000:
        _fail('时间格式不正确', 400, 'invalid_membership_request')
    return value


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='seconds')


def _transaction(con):
    if not con.in_transaction:
        _fail('成员关系操作需要调用方事务', 503, 'membership_transaction_required')


@contextmanager
def _atomic(con):
    _transaction(con)
    name = 'membership_' + secrets.token_hex(8)
    con.execute('SAVEPOINT ' + name)
    try:
        yield
        con.execute('RELEASE SAVEPOINT ' + name)
    except BaseException:
        con.execute('ROLLBACK TO SAVEPOINT ' + name)
        con.execute('RELEASE SAVEPOINT ' + name)
        raise


def _row(con, sql, args=()):
    cursor = con.execute(sql, args)
    row = cursor.fetchone()
    return dict(zip((c[0] for c in cursor.description), row)) if row is not None else None


def _rows(con, sql, args=()):
    cursor = con.execute(sql, args)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor]


def _user(con, member_id):
    user = _row(con, 'SELECT id,name,password,auth_version,household_role FROM users WHERE id=?', (_identifier(member_id),))
    if user and (user['household_role'] not in ('admin', 'member') or type(user['auth_version']) is not int
                 or not 1 <= user['auth_version'] <= MAX_VERSION):
        _fail('成员资料无法核对', 503, 'membership_unavailable')
    return user


def schema_initialize(con, *, now=None):
    """Atomic first initialization inside caller transaction; never heal missing rows."""
    stamp = _now(now)
    with _atomic(con):
        present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} & set(TABLES)
        if present and present != set(TABLES):
            _fail('成员关系迁移不完整', 503, 'membership_schema_incomplete')
        if not present:
            users = _rows(con, 'SELECT id,household_role,auth_version FROM users ORDER BY id')
            for user in users:
                _user(con, user['id'])
            for sql in SCHEMA_STATEMENTS:
                con.execute(sql)
            for user in users:
                con.execute('INSERT INTO household_memberships VALUES(?,?,NULL,\'active\',1,?,?)',
                            (secrets.token_hex(16), user['id'], stamp, stamp))
        missing = con.execute('SELECT 1 FROM users u LEFT JOIN household_memberships m ON m.member_id=u.id '
                              'WHERE m.id IS NULL LIMIT 1').fetchone()
        if missing:
            _fail('成员关系缺失，请先核对迁移', 503, 'membership_missing')


def membership_record(con, *, member_id=None, account_id=None, membership_id=None):
    """Internal record only: account_id must not be exposed as a member DTO."""
    supplied = [(k, v) for k, v in (('member_id', member_id), ('account_id', account_id), ('id', membership_id)) if v is not None]
    if len(supplied) != 1:
        _fail('请按唯一成员关系条件读取', 400, 'invalid_membership_request')
    key, value = supplied[0]
    _identifier(value) if key == 'member_id' else _hex(value)
    return _row(con, 'SELECT * FROM household_memberships WHERE ' + key + '=?', (value,))


def active_member(con, member_id):
    _identifier(member_id)
    row = _row(con, "SELECT u.id,u.name,u.household_role AS householdRole,u.auth_version AS authVersion,"
               "m.id AS membershipId,m.revision AS membershipRevision FROM users u "
               "JOIN household_memberships m ON m.member_id=u.id WHERE u.id=? AND m.state='active'", (member_id,))
    if row and (row['householdRole'] not in ('admin', 'member') or type(row['authVersion']) is not int
                or not 1 <= row['authVersion'] <= MAX_VERSION or type(row['membershipRevision']) is not int
                or not 1 <= row['membershipRevision'] <= MAX_VERSION):
        _fail('成员资料无法核对', 503, 'membership_unavailable')
    return row


def active_members(con):
    result = [active_member(con, r[0]) for r in con.execute(
        "SELECT member_id FROM household_memberships WHERE state='active' ORDER BY member_id").fetchall()]
    if any(row is None for row in result):
        _fail('成员资料无法核对', 503, 'membership_unavailable')
    return result


def _actor(con, member_id, *, admin=False):
    user = active_member(con, member_id)
    if not user:
        _fail('成员关系已失效，请重新核对', 403, 'membership_inactive')
    if admin and user['householdRole'] != 'admin':
        _fail('只有家庭管理员可以执行此操作', 403, 'membership_admin_required')
    return user


def snapshot(con, household_id, member_id):
    _identifier(household_id, '家庭编号')
    relation, user = membership_record(con, member_id=member_id), _user(con, member_id)
    if not relation or not user:
        _fail('当前家庭没有此成员关系', 404, 'membership_not_found')
    return {'id': relation['id'], 'householdId': household_id, 'memberId': member_id,
            'memberName': user['name'], 'householdRole': user['household_role'],
            'state': relation['state'], 'revision': relation['revision']}


def list_memberships(con, household_id, actor_member_id, *, status='active'):
    if status not in ('active', 'all'):
        _fail('成员状态筛选不正确', 400, 'invalid_membership_request')
    _actor(con, actor_member_id, admin=status == 'all')
    rows = con.execute('SELECT member_id FROM household_memberships ' +
                       ("WHERE state='active' " if status == 'active' else '') + 'ORDER BY member_id').fetchall()
    return [snapshot(con, household_id, row[0]) for row in rows]


def _subject(subject):
    if not isinstance(subject, str) or ':' not in subject:
        _fail('操作主体格式不正确', 400, 'invalid_membership_request')
    kind, value = subject.split(':', 1)
    if kind == 'account':
        _hex(value)
    elif kind == 'member':
        _identifier(value)
    else:
        _fail('操作主体格式不正确', 400, 'invalid_membership_request')
    return kind, value


def operation(con, *, subject, request_id, intent_digest=None):
    """Internal recovery lookup; caller must authenticate this exact subject first."""
    _subject(subject)
    _hex(request_id)
    if intent_digest is not None:
        _hex(intent_digest, 64)
    row = _row(con, 'SELECT * FROM membership_operations WHERE subject=? AND request_id=?', (subject, request_id))
    if row and intent_digest is not None and not hmac.compare_digest(row['intent_digest'], intent_digest):
        _fail('同一操作编号不能用于不同内容', 409, 'membership_request_conflict')
    try:
        result = json.loads(row['result_json']) if row else None
    except (ValueError, TypeError):
        _fail('原操作回执无法核对', 503, 'membership_receipt_unavailable')
    return {'requestId': request_id, 'found': row is not None, 'state': 'completed' if row else None, 'result': result}


def member_operation(con, *, member_id, request_id):
    _actor(con, member_id)
    direct = operation(con, subject='member:' + member_id, request_id=request_id)
    relation = membership_record(con, member_id=member_id)
    if not relation['account_id']:
        return direct
    row = _row(con, 'SELECT subject FROM membership_operations WHERE subject=? AND request_id=? AND member_id=?',
               ('account:' + relation['account_id'], _hex(request_id), member_id))
    if row and direct['found']:
        _fail('操作编号对应多个主体，请按原账户操作核对', 409, 'membership_request_conflict')
    return operation(con, subject=row['subject'], request_id=request_id) if row else direct


def _existing(con, subject, request_id, intent_digest, kind):
    value = operation(con, subject=subject, request_id=request_id, intent_digest=_hex(intent_digest, 64))
    if value['found']:
        row = con.execute('SELECT kind FROM membership_operations WHERE subject=? AND request_id=?', (subject, request_id)).fetchone()
        if row[0] != kind:
            _fail('同一操作编号不能用于不同操作', 409, 'membership_request_conflict')
    return value


def _record(con, subject, request_id, intent_digest, kind, member_id, result, stamp):
    con.execute('INSERT INTO membership_operations VALUES(?,?,?,?,?,?,?)',
                (subject, request_id, kind, intent_digest, member_id,
                 json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False), stamp))
    return result


def _audit(con, actor, action, target, stamp):
    con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)',
                (actor, 'membership_' + action, target, _iso(stamp)))
    con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")


def _match_versions(user, relation, expected_auth_version, expected_revision):
    if user['auth_version'] != _version(expected_auth_version) or relation['revision'] != _version(expected_revision):
        _fail('成员状态已变化，请重新读取', 409, 'membership_stale')


def _bumpable(value):
    if value >= MAX_VERSION:
        _fail('成员版本已达上限', 409, 'membership_version_limit')


def _revoke_sessions(con, member_id, stamp):
    rows = _rows(con, 'SELECT DISTINCT b.browser_hash,b.generation FROM member_session_browsers b '
                 'JOIN member_sessions s ON s.browser_hash=b.browser_hash WHERE s.owner=?', (member_id,))
    for row in rows:
        _bumpable(row['generation'])
    con.execute('UPDATE member_sessions SET revoked_at=? WHERE owner=? AND revoked_at IS NULL', (stamp, member_id))
    for row in rows:
        con.execute('UPDATE member_session_browsers SET generation=generation+1 WHERE browser_hash=?', (row['browser_hash'],))


def _pause_cloud(con, member_id, stamp):
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'cloud_accounts' in tables:
        con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE owner=?', (member_id,))
    for table, states in (
        ('calendar_publications', ('pending', 'publishing', 'published', 'retry', 'needs_authorization')),
        ('task_publications', ('pending', 'publishing', 'published', 'retry', 'uncertain', 'needs_authorization')),
    ):
        if table in tables:
            placeholders = ','.join('?' for _ in states)
            owners, args = ['owner=?'], [member_id]
            if table == 'task_publications':
                owners.append('account_owner=?')
                args.append(member_id)
            if 'cloud_accounts' in tables:
                owners.append('account_id IN (SELECT id FROM cloud_accounts WHERE owner=?)')
                args.append(member_id)
            con.execute("UPDATE " + table + " SET status='paused',updated_at=? WHERE (" + ' OR '.join(owners)
                        + ') AND status IN (' + placeholders + ')', (_iso(stamp), *args, *states))
    # Media has no paused state. Runtime integration must fence inactive owners
    # and handle pending imports under its established lifecycle contract.


def bind_account(con, *, household_id, member_id, account_id, member_password,
                 expected_auth_version, expected_revision, request_id, intent_digest, now=None):
    _hex(account_id)
    _identifier(household_id, '家庭编号')
    _version(expected_auth_version); _version(expected_revision)
    stamp, subject = _now(now), 'account:' + account_id
    with _atomic(con):
        _actor(con, member_id)
        user = _user(con, member_id)
        if not isinstance(member_password, str) or not 1 <= len(member_password) <= 128 or not check_password_hash(user['password'], member_password):
            _fail('成员密码证明失败', 403, 'membership_password_required')
        old = _existing(con, subject, request_id, intent_digest, 'bind')
        if old['found']:
            return old['result']
        relation = membership_record(con, member_id=member_id)
        _match_versions(user, relation, expected_auth_version, expected_revision)
        other = membership_record(con, account_id=account_id)
        if (relation['account_id'] is not None and relation['account_id'] != account_id) or (other and other['id'] != relation['id']):
            _fail('此身份已经绑定其他关系', 409, 'membership_already_bound')
        if relation['account_id'] is None:
            _bumpable(relation['revision'])
            con.execute('UPDATE household_memberships SET account_id=?,revision=revision+1,updated_at=? WHERE id=?',
                        (account_id, stamp, relation['id']))
        result = snapshot(con, household_id, member_id)
        _audit(con, member_id, 'bind', relation['id'], stamp)
        return _record(con, subject, request_id, intent_digest, 'bind', member_id, result, stamp)


def _invitation(con, invitation_id):
    value = _row(con, 'SELECT * FROM member_invitations WHERE id=?', (_hex(invitation_id),))
    if not value:
        _fail('邀请不存在或不可用', 404, 'invitation_not_found')
    return value


def _inviter_valid(con, invitation):
    user = active_member(con, invitation['creator_member_id'])
    return bool(user and user['householdRole'] == 'admin' and user['authVersion'] == invitation['creator_auth_version'])


def _invitation_summary(con, invitation, stamp):
    state = invitation['state']
    if state == 'pending':
        state = 'expired' if invitation['expires_at'] <= stamp else 'pending' if _inviter_valid(con, invitation) else 'invalid'
    return {'id': invitation['id'], 'state': state, 'revision': invitation['revision'],
            'expiresAt': _iso(invitation['expires_at']), 'householdRole': 'member'}


def validate_invitation(con, *, invitation_id, expected_revision, now=None):
    invitation, stamp = _invitation(con, invitation_id), _now(now)
    if invitation['revision'] != _version(expected_revision):
        _fail('邀请状态已变化', 409, 'invitation_stale')
    result = _invitation_summary(con, invitation, stamp)
    if result['state'] != 'pending':
        _fail('邀请已失效，请重新取得邀请', 409, 'invitation_unavailable')
    return result


def inspect_invitation(con, token, *, now=None):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        _fail('邀请不存在或不可用', 404, 'invitation_not_found')
    value = _row(con, 'SELECT id,revision FROM member_invitations WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
    if not value:
        _fail('邀请不存在或不可用', 404, 'invitation_not_found')
    return validate_invitation(con, invitation_id=value['id'], expected_revision=value['revision'], now=now)


def list_invitations(con, household_id, actor_member_id, *, now=None):
    _identifier(household_id, '家庭编号')
    _actor(con, actor_member_id, admin=True)
    stamp = _now(now)
    return [_invitation_summary(con, row, stamp) for row in _rows(con, 'SELECT * FROM member_invitations ORDER BY created_at,id')]


def create_invitation(con, *, household_id, actor_member_id, expected_auth_version, request_id, intent_digest, now=None):
    _identifier(household_id, '家庭编号')
    _version(expected_auth_version)
    stamp, subject = _now(now), 'member:' + _identifier(actor_member_id)
    with _atomic(con):
        actor = _actor(con, actor_member_id, admin=True)
        old = _existing(con, subject, request_id, intent_digest, 'invite')
        if old['found']:
            return old['result']
        if actor['authVersion'] != _version(expected_auth_version):
            _fail('管理员版本已变化', 409, 'membership_stale')
        pending = _rows(con, "SELECT * FROM member_invitations WHERE state='pending' AND expires_at>?", (stamp,))
        if sum(_inviter_valid(con, row) for row in pending) >= MAX_PENDING_INVITATIONS:
            _fail('有效邀请已达上限', 409, 'invitation_limit')
        invitation_id, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        con.execute("INSERT INTO member_invitations VALUES(?,?,?,?, 'pending',1,?,?,NULL,NULL,NULL)",
                    (invitation_id, hashlib.sha256(token.encode()).hexdigest(), actor_member_id, actor['authVersion'], stamp, stamp + INVITATION_TTL))
        result = {'invitation': _invitation_summary(con, _invitation(con, invitation_id), stamp)}
        _audit(con, actor_member_id, 'invite', invitation_id, stamp)
        _record(con, subject, request_id, intent_digest, 'invite', actor_member_id, result, stamp)
        return {**result, 'token': token}


def revoke_invitation(con, *, household_id, actor_member_id, invitation_id, expected_revision, request_id, intent_digest, now=None):
    _identifier(household_id, '家庭编号')
    _hex(invitation_id); _version(expected_revision)
    stamp, subject = _now(now), 'member:' + _identifier(actor_member_id)
    with _atomic(con):
        _actor(con, actor_member_id, admin=True)
        old = _existing(con, subject, request_id, intent_digest, 'revoke_invitation')
        if old['found']:
            return old['result']
        invitation = _invitation(con, invitation_id)
        if invitation['revision'] != _version(expected_revision):
            _fail('邀请状态已变化', 409, 'invitation_stale')
        if invitation['state'] != 'pending':
            _fail('邀请已使用或撤销，请重新核对', 409, 'invitation_unavailable')
        _bumpable(invitation['revision'])
        con.execute("UPDATE member_invitations SET state='revoked',revision=revision+1,revoked_at=? WHERE id=?", (stamp, invitation_id))
        result = {'invitation': _invitation_summary(con, _invitation(con, invitation_id), stamp)}
        _audit(con, actor_member_id, 'revoke_invitation', invitation_id, stamp)
        return _record(con, subject, request_id, intent_digest, 'revoke_invitation', actor_member_id, result, stamp)


def accept_invitation(con, *, household_id, account_id, invitation_id, expected_revision, request_id, intent_digest, now=None):
    _identifier(household_id, '家庭编号')
    _hex(invitation_id); _version(expected_revision)
    stamp, subject = _now(now), 'account:' + _hex(account_id)
    with _atomic(con):
        old = _existing(con, subject, request_id, intent_digest, 'accept')
        if old['found']:
            return old['result']
        validate_invitation(con, invitation_id=invitation_id, expected_revision=expected_revision, now=stamp)
        relation = membership_record(con, account_id=account_id)
        if not relation or relation['state'] != 'active':
            if con.execute("SELECT count(*) FROM household_memberships WHERE state='active'").fetchone()[0] >= MAX_ACTIVE_MEMBERS:
                _fail('本户有效成员已达上限', 409, 'membership_limit')
        if not relation:
            member_id = 'm_' + secrets.token_hex(12)
            con.execute('INSERT INTO users(id,username,name,password,auth_version,household_role) VALUES(?,?,?,?,1,\'member\')',
                        (member_id, member_id, '新成员', generate_password_hash(secrets.token_urlsafe(48))))
            relation = {'id': secrets.token_hex(16), 'member_id': member_id}
            con.execute("INSERT INTO household_memberships VALUES(?,?,?,'active',1,?,?)", (relation['id'], member_id, account_id, stamp, stamp))
        elif relation['state'] != 'active':
            user = _user(con, relation['member_id'])
            _bumpable(relation['revision']); _bumpable(user['auth_version'])
            _revoke_sessions(con, relation['member_id'], stamp)
            con.execute("UPDATE users SET household_role='member',auth_version=auth_version+1 WHERE id=?", (relation['member_id'],))
            con.execute("UPDATE household_memberships SET state='active',revision=revision+1,updated_at=? WHERE id=?", (stamp, relation['id']))
        invitation = _invitation(con, invitation_id)
        _bumpable(invitation['revision'])
        con.execute("UPDATE member_invitations SET state='used',revision=revision+1,used_at=?,used_by_account_id=? WHERE id=?",
                    (stamp, account_id, invitation_id))
        result = snapshot(con, household_id, relation['member_id'])
        _audit(con, relation['member_id'], 'accept', invitation_id, stamp)
        return _record(con, subject, request_id, intent_digest, 'accept', relation['member_id'], result, stamp)


def _stop(con, household_id, member_id, expected_auth_version, expected_revision, state, stamp):
    relation, user = membership_record(con, member_id=member_id), _user(con, member_id)
    if not relation or not user:
        _fail('当前家庭没有此成员关系', 404, 'membership_not_found')
    if relation['state'] != 'active':
        _fail('成员关系已失效', 409, 'membership_inactive')
    _match_versions(user, relation, expected_auth_version, expected_revision)
    if user['household_role'] == 'admin':
        count = con.execute("SELECT count(*) FROM household_memberships m JOIN users u ON u.id=m.member_id "
                            "WHERE m.state='active' AND u.household_role='admin'").fetchone()[0]
        if count <= 1:
            _fail('家庭必须保留至少一位有效管理员', 409, 'membership_last_admin')
    _bumpable(relation['revision']); _bumpable(user['auth_version'])
    _revoke_sessions(con, member_id, stamp)
    _pause_cloud(con, member_id, stamp)
    con.execute('UPDATE users SET auth_version=auth_version+1 WHERE id=?', (member_id,))
    con.execute('UPDATE household_memberships SET state=?,revision=revision+1,updated_at=? WHERE id=?', (state, stamp, relation['id']))
    return snapshot(con, household_id, member_id)


def remove_membership(con, *, household_id, actor_member_id, member_id, expected_auth_version,
                      expected_revision, request_id, intent_digest, now=None):
    _identifier(household_id, '家庭编号'); _identifier(member_id)
    _version(expected_auth_version); _version(expected_revision)
    stamp, subject = _now(now), 'member:' + _identifier(actor_member_id)
    with _atomic(con):
        actor = _actor(con, actor_member_id, admin=True)
        if actor_member_id == member_id:
            _fail('请使用本人退出家庭操作', 403, 'membership_self_remove')
        old = _existing(con, subject, request_id, intent_digest, 'remove')
        if old['found']:
            return old['result']
        if actor['authVersion'] != expected_auth_version:
            _fail('管理员版本已变化', 409, 'membership_stale')
        target = _user(con, member_id)
        if not target:
            _fail('当前家庭没有此成员关系', 404, 'membership_not_found')
        result = _stop(con, household_id, member_id, target['auth_version'], expected_revision, 'removed', stamp)
        _audit(con, actor_member_id, 'remove', member_id, stamp)
        return _record(con, subject, request_id, intent_digest, 'remove', member_id, result, stamp)


def leave_membership(con, *, household_id, member_id, account_id, expected_auth_version,
                     expected_revision, request_id, intent_digest, now=None):
    _identifier(household_id, '家庭编号'); _identifier(member_id)
    _version(expected_auth_version); _version(expected_revision)
    stamp, subject = _now(now), 'account:' + _hex(account_id)
    with _atomic(con):
        relation = membership_record(con, member_id=member_id)
        if not relation or relation['account_id'] != account_id:
            _fail('请先明确绑定本人的家庭身份', 403, 'membership_binding_required')
        old = _existing(con, subject, request_id, intent_digest, 'leave')
        if old['found']:
            return old['result']
        result = _stop(con, household_id, member_id, expected_auth_version, expected_revision, 'left', stamp)
        _audit(con, member_id, 'leave', member_id, stamp)
        return _record(con, subject, request_id, intent_digest, 'leave', member_id, result, stamp)


def record_operation(con, *, subject, request_id, intent_digest, result, now=None):
    """Record only a bounded coordinator result in its existing household transaction."""
    subject_kind, account_id = _subject(subject)
    if subject_kind != 'account' or not isinstance(result, dict):
        _fail('协调回执格式不正确', 400, 'invalid_membership_request')
    summary_keys = {'id','householdId','memberId','memberName','householdRole','state','revision'}
    switch_keys = {'ok','householdId','memberId','entry'}
    if set(result) == switch_keys and result['ok'] is True and result['entry'] == '/app/home':
        kind = 'switch'
    elif set(result) == summary_keys:
        _version(result['revision'])
        kind = 'coordinated_membership'
    else:
        _fail('协调回执字段不正确', 400, 'invalid_membership_request')
    stamp = _now(now)
    with _atomic(con):
        old = _existing(con, subject, request_id, intent_digest, kind)
        if old['found']:
            return old['result']
        _identifier(result['householdId'], '家庭编号')
        relation = membership_record(con, member_id=result['memberId'])
        if not relation or relation['account_id'] != account_id:
            _fail('账户与成员关系不符', 403, 'membership_binding_required')
        if kind == 'switch':
            _actor(con, result['memberId'])
        elif result != snapshot(con, result['householdId'], result['memberId']):
            _fail('成员摘要已变化', 409, 'membership_stale')
        return _record(con, subject, request_id, intent_digest, kind, result['memberId'], result, stamp)
