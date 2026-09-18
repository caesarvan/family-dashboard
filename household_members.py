"""Household-local administration, without changing member/TV authentication."""
from contextlib import contextmanager
import json
import re
import time

from flask import g, jsonify, request
import household_memberships


MAX_AUTH_VERSION = 9007199254740991
HOUSEHOLD_ROLE_COLUMN_SQL = (
    "ALTER TABLE users ADD COLUMN household_role TEXT NOT NULL DEFAULT 'member' "
    "CHECK(household_role IN ('admin','member'))"
)


def init_schema(con):
    """One atomic compatibility migration; existing roles are never reset."""
    if con.in_transaction:
        raise RuntimeError('Role migration requires an independent transaction')
    con.execute('BEGIN IMMEDIATE')
    try:
        columns = {row[1] for row in con.execute('PRAGMA table_info(users)')}
        if 'household_role' not in columns:
            con.execute(HOUSEHOLD_ROLE_COLUMN_SQL)
            con.execute("UPDATE users SET household_role='admin' WHERE id IN ('member1','member2')")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def register_members(app, db, Problem, body, require_member, audit):
    with app.app_context():
        init_schema(db())
        con = db()
        con.execute('BEGIN IMMEDIATE')
        try:
            marker = con.execute("SELECT data FROM settings WHERE id='membership_schema_v1'").fetchone()
            present = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if marker is not None and (marker[0] != '{"version":1}' or not set(household_memberships.TABLES).issubset(present)):
                raise Problem('成员关系存储不完整，请先恢复备份', 503)
            household_memberships.schema_initialize(con)
            for expected in household_memberships.SCHEMA_STATEMENTS:
                name = expected.split('(')[0].split()[-1]
                actual = con.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?', ('table', name)).fetchone()
                if not actual or ' '.join(actual[0].split()).lower() != ' '.join(expected.split()).lower():
                    raise Problem('成员关系结构无法核对，请先检查迁移', 503)
            con.execute("INSERT OR IGNORE INTO settings(id,data) VALUES('membership_schema_v1','{\"version\":1}')")
            con.commit()
        except BaseException:
            con.rollback()
            raise
    sessions = app.extensions['member_sessions']

    def capture():
        require_member()
        original = getattr(g, 'member_session', {})
        identity = (original.get('id'), g.actor.get('id'), g.actor.get('auth_version'), g.actor.get('householdId'))
        if (not identity[0] or original.get('owner') != identity[1]
                or original.get('auth_version') != identity[2]
                or identity[3] != app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')):
            raise Problem('会话已失效，请重新登录', 401)
        return identity

    def current(con, identity, admin=False):
        if capture() != identity:
            raise Problem('会话已变化，请重新登录', 401)
        actual = sessions.current(con)
        if (actual['id'], actual['owner'], actual['auth_version']) != identity[:3]:
            raise Problem('会话已变化，请重新登录', 401)
        row = con.execute('SELECT household_role FROM users WHERE id=?', (identity[1],)).fetchone()
        if not row or row['household_role'] not in ('admin', 'member'):
            raise Problem('家庭角色暂时无法核对', 503)
        if admin and row['household_role'] != 'admin':
            raise Problem('只有家庭管理员可以执行此操作', 403)
        return row['household_role']

    @contextmanager
    def transaction(write=False):
        identity, con = capture(), db()
        con.rollback()
        try:
            if not write:
                # Legacy credential resolution can make an implicit write.
                # Initial registration has already committed in actor().
                role = current(con, identity)
                con.rollback()
            con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if write:
                role = current(con, identity, admin=True)
            yield con, identity, role
            if not write:
                con.rollback()
            fresh_role = current(con, identity, admin=write)
            if fresh_role != role:
                raise Problem('家庭角色已变化，请重新读取', 403)
            if write:
                con.commit()
        finally:
            con.rollback()

    def no_query():
        if request.args:
            raise Problem('此操作不接受查询参数')

    def payload(role_change):
        no_query()
        body()  # Preserve the injected application's JSON-object contract.

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON key')
                result[key] = value
            return result

        try:
            value = json.loads(request.get_data(), object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise Problem('请提交无重复字段的有效 JSON') from None
        expected = {'expectedAuthVersion', 'householdRole'} if role_change else {'expectedAuthVersion'}
        if not isinstance(value, dict) or set(value) != expected:
            raise Problem('请只提交目标版本和本次允许修改的字段')
        version = value['expectedAuthVersion']
        if type(version) is not int or not 1 <= version <= MAX_AUTH_VERSION:
            raise Problem('请提供有效的成员版本')
        if role_change:
            if not isinstance(value['householdRole'], str):
                raise Problem('家庭角色格式不正确')
            if value['householdRole'] not in ('admin', 'member'):
                raise Problem('不允许设置此家庭角色', 403)
        return value

    @app.get('/api/members')
    def household_members_list():
        no_query()
        with transaction() as (con, identity, role):
            stamp = time.time()
            rows = con.execute("SELECT u.id,u.name,u.household_role,u.auth_version FROM users u JOIN household_memberships m ON m.member_id=u.id AND m.state='active' ORDER BY u.id").fetchall()
            members = []
            for row in rows:
                if row['household_role'] not in ('admin', 'member') or type(row['auth_version']) is not int or not 1 <= row['auth_version'] <= MAX_AUTH_VERSION:
                    raise Problem('家庭成员信息暂时无法核对', 503)
                count = None
                if role == 'admin':
                    count = con.execute('SELECT count(*) FROM member_sessions WHERE owner=? AND auth_version=? '
                                        'AND revoked_at IS NULL AND expires_at>?', (row['id'], row['auth_version'], stamp)).fetchone()[0]
                allowed = role == 'admin' and row['id'] != identity[1]
                members.append({'id': row['id'], 'name': row['name'], 'householdRole': row['household_role'],
                    'authVersion': row['auth_version'], 'activeSessionCount': count,
                    'capabilities': {'changeRole': allowed, 'revokeSessions': allowed}})
            result = {'currentMemberId': identity[1], 'members': members}
        return jsonify(result)

    def change(member_id, role_change):
        value = payload(role_change)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', member_id):
            raise Problem('成员编号格式不正确')
        with transaction(write=True) as (con, identity, _):
            if member_id == identity[1]:
                raise Problem('请使用本人账户设置，不能在此操作自己', 403)
            target = con.execute("SELECT u.id,u.household_role,u.auth_version FROM users u JOIN household_memberships m ON m.member_id=u.id AND m.state='active' WHERE u.id=?", (member_id,)).fetchone()
            if not target:
                raise Problem('当前家庭中没有这位成员', 404)
            if (target['household_role'] not in ('admin', 'member') or type(target['auth_version']) is not int
                    or not 1 <= target['auth_version'] <= MAX_AUTH_VERSION):
                raise Problem('家庭角色暂时无法核对', 503)
            if target['auth_version'] != value['expectedAuthVersion']:
                raise Problem('成员状态已变化，请重新读取后核对', 409)
            next_role = value['householdRole'] if role_change else target['household_role']
            if role_change and next_role == target['household_role']:
                raise Problem('该成员已是此角色，请重新读取', 409)
            if role_change and next_role == 'member' and target['household_role'] == 'admin':
                if con.execute("SELECT count(*) FROM users u JOIN household_memberships m ON m.member_id=u.id AND m.state='active' WHERE u.household_role='admin'").fetchone()[0] <= 1:
                    raise Problem('家庭必须保留至少一位管理员', 409)
            if target['auth_version'] >= MAX_AUTH_VERSION:
                raise Problem('成员版本已达上限，请联系管理员核对', 409)
            stamp = time.time()
            rows = con.execute('SELECT browser_hash,auth_version,expires_at FROM member_sessions WHERE owner=? '
                               'AND revoked_at IS NULL', (member_id,)).fetchall()
            revoked = sum(row['auth_version'] == target['auth_version'] and row['expires_at'] > stamp for row in rows)
            changed = con.execute('UPDATE users SET household_role=?,auth_version=auth_version+1 WHERE id=? AND auth_version=?',
                                  (next_role, member_id, target['auth_version'])).rowcount
            if changed != 1:
                raise Problem('成员状态已变化，请重新读取后核对', 409)
            con.execute('UPDATE member_sessions SET revoked_at=? WHERE owner=? AND revoked_at IS NULL', (stamp, member_id))
            sessions.advance(con, [row['browser_hash'] for row in rows], stamp)
            # Token ownership rows stay intact. Existing member-bound OAuth
            # contexts are invalidated; a fresh login remains permitted.
            audit('household_member_role' if role_change else 'household_member_sessions_revoke', member_id)
            result = {'ok': True, 'member': {'id': member_id, 'householdRole': next_role,
                      'authVersion': target['auth_version'] + 1}, 'revoked': revoked}
        return jsonify(result)

    @app.patch('/api/members/<member_id>/role')
    def household_member_role(member_id):
        return change(member_id, True)

    @app.post('/api/members/<member_id>/revoke-sessions')
    def household_member_revoke(member_id):
        return change(member_id, False)
