"""HTTP adapters for personal accounts and household membership commands."""
from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path

from flask import jsonify, request
from itsdangerous import BadSignature
from werkzeug.security import check_password_hash

import household_memberships as memberships
from membership_storage import personal_engine


def install_personal_accounts(platform, Problem):
    from personal_accounts import PersonalAccounts

    def application(platform_con, household_id):
        info = platform_con.execute('SELECT * FROM households WHERE id=?', (household_id,)).fetchone()
        if not info:
            raise PersonalAccounts.Error('家庭暂不可用，请重新读取', 404)
        # Check before child() enters a nested transaction guard. A missing
        # household is an unavailable list entry, not a failed personal login.
        if not household_available(household_id):
            raise PersonalAccounts.Error('家庭资料暂不可用', 503)
        return platform.child(dict(info))

    def household_path(household_id):
        return (Path(platform.root) if household_id == 'default' else
                Path(platform.root) / 'spaces' / household_id) / 'household.sqlite3'

    def household_available(household_id):
        # Restoring the file does not turn a recovery-only app into a loaded
        # household. Keep account errors controlled until an explicit restart.
        return (not (household_id == 'default' and platform.app.config.get('_HOUSEHOLD_RECOVERY_ONLY'))
                and household_path(household_id).is_file())

    def routed_id():
        raw = request.cookies.get('household_space')
        try:
            value = platform.signer.loads(raw) if raw else 'default'
        except BadSignature:
            raise Problem('家庭入口已变化，请重新读取', 401) from None
        if not isinstance(value, str):
            raise Problem('家庭入口已变化，请重新读取', 401)
        return value

    @contextmanager
    def household(household_id):
        engine = platform.personal_accounts
        if engine.guard_con is None:
            raise RuntimeError('Open the platform guard before a household')
        app = application(engine.guard_con, household_id)
        with app.extensions['member_sessions'].db() as con:
            yield con

    def member_proof(platform_con, password, *, household_con=None, check_csrf=True):
        household_id = routed_id()
        app = application(platform_con, household_id)
        sessions = app.extensions['member_sessions']
        signed = sessions.signed(request.cookies.get(app.config['SESSION_COOKIE_NAME']))
        header = 'X-Member-CSRF-Token' if request.path.startswith('/api/account/') else 'X-CSRF-Token'
        csrf = request.headers.get(header, '')
        if not signed or (check_csrf and (not csrf or not secrets.compare_digest(csrf, signed[0].get('csrf', '')))):
            raise Problem('家庭登录已变化，请刷新后重试', 403)
        with (nullcontext(household_con) if household_con is not None else sessions.db()) as con:
            if household_con is None:
                con.execute('BEGIN IMMEDIATE')
            row = sessions.resolve(con, signed, time.time())
            if not row:
                raise Problem('请先登录原来的家庭账号', 401)
            if password is not None:
                user = con.execute('SELECT password FROM users WHERE id=?', (row['owner'],)).fetchone()
                if not isinstance(password, str) or not 12 <= len(password) <= 128 or not check_password_hash(user['password'], password):
                    raise Problem('原家庭账号密码不正确', 403)
            return {'householdId': household_id, 'memberId': row['owner'], 'authVersion': row['auth_version'],
                    'sessionId': row['id'],
                    'membershipRevision': row['membership_revision']}

    def validate_member_proof(platform_con, proof, *, household_con=None):
        actual = member_proof(platform_con, None, household_con=household_con, check_csrf=False)
        if not isinstance(proof, dict) or any(actual.get(key) != value for key, value in proof.items()):
            raise Problem('原家庭身份已变化，请重新验证', 401)
        return actual

    def install_member(platform_con, household_con, personal_identity, summary):
        target_id = summary['householdId']
        target = application(platform_con, target_id)
        target_sessions = target.extensions['member_sessions']
        # Revoke the original cookie before switching the routing cookie. The
        # platform guard serializes household order; reuse the target writer.
        try:
            original_id = routed_id()
        except Problem:
            original_id = None
        original_info = platform_con.execute('SELECT id FROM households WHERE id=?', (original_id,)).fetchone()
        # Rotating the personal browser already invalidates every old derived
        # cookie. Independent account recovery also works with an invalid old
        # route or unavailable old household; no missing DB is recreated.
        original = (application(platform_con, original_id)
                    if original_info and household_available(original_id) else None)
        original_sessions = original.extensions['member_sessions'] if original else None
        raw = request.cookies.get(original.config['SESSION_COOKIE_NAME']) if original else None
        if raw and original_sessions:
            def revoke(con):
                row = original_sessions.resolve(con, original_sessions.signed(raw), time.time())
                if row:
                    original_sessions.revoke_browser(con, row['browser_hash'], time.time())
            if original_id == target_id:
                revoke(household_con)
            else:
                with original_sessions.db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    revoke(con)
        value = target_sessions.create_derived(household_con, summary['memberId'], personal_identity)
        encoded = target.session_interface.get_signing_serializer(target).dumps(value)

        def decorate(response):
            secure = platform.app.config['SESSION_COOKIE_SECURE']
            response.set_cookie(target.config['SESSION_COOKIE_NAME'], encoded, httponly=True,
                                secure=secure, samesite='Lax', max_age=target_sessions.ttl)
            response.set_cookie('household_space', platform.signer.dumps(target_id), httponly=True,
                                secure=secure, samesite='Lax', max_age=86400*365)
            response.delete_cookie('household_tv', secure=secure, samesite='Lax')
            return response
        return decorate

    def is_tv():
        if request.headers.get('X-Display-Mode') == 'tv':
            return True
        raw = request.cookies.get('household_tv')
        if not raw or len(raw) > 4096:
            return False
        try:
            with platform.personal_accounts.guard() as platform_con:
                selected = application(platform_con, routed_id())
                sessions = selected.extensions['member_sessions']
                with sessions.db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    signed = sessions.signed(request.cookies.get(selected.config['SESSION_COOKIE_NAME']))
                    if sessions.resolve(con, signed, time.time()):
                        return False
                    return con.execute('SELECT 1 FROM devices WHERE secret_hash=? AND approved=1 AND expires>?',
                        (hashlib.sha256(raw.encode()).hexdigest(), time.time())).fetchone() is not None
        except (Problem, PersonalAccounts.Error, OSError, sqlite3.DatabaseError):
            # Missing old household storage must not prevent independent
            # account recovery. Its TV credential grants no account authority.
            return False

    engine = PersonalAccounts(platform, {
        'membership': memberships, 'household': household, 'member_proof': member_proof,
        'validate_member_proof': validate_member_proof, 'install_member': install_member,
        'is_tv': is_tv,
    })
    # Callback errors are deliberately sanitized and retain their HTTP status.
    @engine.app.errorhandler(Problem)
    def member_problem(error):
        return jsonify(error=error.message), error.status
    platform.personal_accounts = engine
    return engine


def register_membership_routes(app, db, Problem, require_member):
    from personal_accounts import PersonalAccountError
    sessions = app.extensions['member_sessions']
    household_id = app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')

    @app.errorhandler(memberships.MembershipError)
    @app.errorhandler(PersonalAccountError)
    def membership_problem(error):
        return jsonify(error=error.message, code=error.code), error.status

    def payload(fields):
        if request.args:
            raise Problem('此操作不接受查询参数')
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('duplicate field')
                value[key] = item
            return value
        try:
            value = json.loads(request.get_data(), object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise Problem('请提交无重复字段的有效 JSON') from None
        if not isinstance(value, dict) or set(value) != set(fields):
            raise Problem('请求字段不正确，请刷新后重试')
        return value

    @contextmanager
    def transaction():
        require_member()
        con = db()
        con.rollback()
        try:
            con.execute('BEGIN IMMEDIATE')
            current = sessions.current(con)
            yield con, current
            sessions.current(con)
            con.commit()
        finally:
            con.rollback()

    def intent(value):
        canonical = json.dumps([request.path, value], sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        return hmac.new(app.secret_key.encode(), ('membership-intent|' + canonical).encode(), hashlib.sha256).hexdigest()

    @app.get('/api/memberships')
    def membership_list():
        if set(request.args) - {'status'} or len(request.args.getlist('status')) > 1:
            raise Problem('查询字段不正确')
        with transaction() as (con, member):
            result = memberships.list_memberships(con, household_id, member['owner'], status=request.args.get('status', 'active'))
        return jsonify(memberships=result)

    @app.get('/api/member-invitations')
    def invitation_list():
        if request.args:
            raise Problem('此操作不接受查询参数')
        with transaction() as (con, member):
            result = memberships.list_invitations(con, household_id, member['owner'])
        return jsonify(invitations=result)

    @app.post('/api/member-invitations')
    def invitation_create():
        value = payload({'requestId', 'expectedAuthVersion'})
        with transaction() as (con, member):
            result = memberships.create_invitation(con, household_id=household_id, actor_member_id=member['owner'],
                expected_auth_version=value['expectedAuthVersion'], request_id=value['requestId'], intent_digest=intent(value))
        return jsonify(result)

    @app.post('/api/member-invitations/<invitation_id>/revoke')
    def invitation_revoke(invitation_id):
        value = payload({'requestId', 'expectedRevision'})
        with transaction() as (con, member):
            result = memberships.revoke_invitation(con, household_id=household_id, actor_member_id=member['owner'],
                invitation_id=invitation_id, expected_revision=value['expectedRevision'], request_id=value['requestId'], intent_digest=intent(value))
        return jsonify(result)

    @app.post('/api/memberships/<member_id>/remove')
    def membership_remove(member_id):
        value = payload({'requestId', 'expectedRevision', 'expectedAuthVersion'})
        with transaction() as (con, member):
            result = memberships.remove_membership(con, household_id=household_id, actor_member_id=member['owner'], member_id=member_id,
                expected_auth_version=value['expectedAuthVersion'], expected_revision=value['expectedRevision'],
                request_id=value['requestId'], intent_digest=intent(value))
        return jsonify(result)

    @app.get('/api/membership-operations/<request_id>')
    def membership_operation(request_id):
        if request.args:
            raise Problem('此操作不接受查询参数')
        with transaction() as (con, member):
            result = memberships.member_operation(con, member_id=member['owner'], request_id=request_id)
        return jsonify(result)

    @app.post('/api/membership-links')
    def membership_bind():
        value = payload({'requestId', 'memberPassword', 'expectedAuthVersion', 'expectedRevision'})
        return personal_engine(app).handle_bind(value)

    @app.post('/api/memberships/self/leave')
    def membership_leave():
        value = payload({'requestId', 'expectedAuthVersion', 'expectedRevision'})
        return personal_engine(app).handle_leave(value)
