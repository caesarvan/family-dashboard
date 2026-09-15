"""Revocable, household-local member sessions; no raw credentials/device headers.

The signed cookie transports a credential, not authority. Authentication also
requires a live row and the user's current auth_version. Browser generations
serialize authentication decisions, not HTTP delivery: a late cookie can still
replace a newer cookie in a browser, but its revoked credential cannot log in.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time

from flask import g, jsonify, request, session
from itsdangerous import BadSignature


LAST_SEEN_INTERVAL = 300
MAX_ACTIVE = 16
LEGACY_SETTING = 'member_sessions_legacy_v1'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='seconds')


def device_label(value):
    """Only return a finite vocabulary; never persist arbitrary User-Agent/IP."""
    value = value or ''
    browser = ('Edge' if any(x in value for x in ('Edg/', 'EdgA/', 'EdgiOS/')) else
               'Firefox' if 'Firefox/' in value or 'FxiOS/' in value else
               'Chrome' if 'Chrome/' in value or 'CriOS/' in value else
               'Safari' if 'Safari/' in value else '浏览器')
    platform = ('iOS' if 'iPhone' in value or 'iPad' in value else 'Android' if 'Android' in value else
                'Windows' if 'Windows' in value else 'macOS' if 'Macintosh' in value else
                'Linux' if 'Linux' in value else '未知设备')
    return browser + ' · ' + platform


class MemberSessions:
    def __init__(self, app, path, Problem):
        self.app, self.path, self.Problem = app, str(path), Problem
        self.ttl = int(app.permanent_session_lifetime.total_seconds())
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            con.execute('''CREATE TABLE IF NOT EXISTS member_session_browsers(
                browser_hash TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL)''')
            con.execute('''CREATE TABLE IF NOT EXISTS member_sessions(
                id TEXT PRIMARY KEY, credential_hash TEXT UNIQUE NOT NULL,
                owner TEXT NOT NULL REFERENCES users(id), auth_version INTEGER NOT NULL,
                browser_hash TEXT NOT NULL, device TEXT NOT NULL,
                created_at REAL NOT NULL, last_seen_at REAL NOT NULL, expires_at REAL NOT NULL,
                revoked_at REAL, legacy INTEGER NOT NULL DEFAULT 0, retain_until REAL NOT NULL)''')
            con.execute('CREATE INDEX IF NOT EXISTS member_sessions_owner ON member_sessions(owner)')
            con.execute('CREATE INDEX IF NOT EXISTS member_sessions_browser ON member_sessions(browser_hash)')
            con.execute('INSERT OR IGNORE INTO settings(id,data) VALUES(?,?)',
                        (LEGACY_SETTING, json.dumps({'cutoff': int(time.time()), 'maxTtl': self.ttl})))
            policy = json.loads(con.execute('SELECT data FROM settings WHERE id=?', (LEGACY_SETTING,)).fetchone()[0])
            self.legacy_cutoff = policy['cutoff']
            # Restart/configuration changes must not move the legacy horizon.
            self.legacy_ttl = policy['maxTtl']
            self.legacy_until = self.legacy_cutoff + self.legacy_ttl + 1

    @contextmanager
    def db(self):
        # app.initialize() creates the household DB before this engine. Auth
        # must never silently recreate a removed database, including after a
        # prior path existence check raced with a filesystem change.
        uri = Path(self.path).resolve().as_uri() + '?mode=rw'
        con = sqlite3.connect(uri, timeout=15, uri=True)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def signed(self, raw):
        if not isinstance(raw, str) or not raw:
            return None
        try:
            value, stamp = self.app.session_interface.get_signing_serializer(self.app).loads(
                raw, max_age=self.ttl, return_timestamp=True)
        except (BadSignature, ValueError, TypeError):
            return None
        if not isinstance(value, dict):
            return None
        return value, stamp.timestamp()

    def request_signed(self):
        return self.signed(request.cookies.get(self.app.config['SESSION_COOKIE_NAME']))

    def browser_token(self, value):
        raw = value.get('browser_id')
        if isinstance(raw, str) and 20 <= len(raw) <= 200:
            return raw
        # Stable bridge for old credentials which predate anonymous bootstrap.
        csrf = value.get('csrf')
        if value.get('uid') and isinstance(csrf, str) and 20 <= len(csrf) <= 200:
            return hmac.new(self.app.secret_key.encode(), ('legacy-browser|' + csrf).encode(), hashlib.sha256).hexdigest()
        return None

    def clean(self, con, now):
        con.execute('DELETE FROM member_sessions WHERE expires_at<=? AND retain_until<=?', (now, now))
        con.execute('DELETE FROM member_session_browsers WHERE expires_at<=? AND NOT EXISTS '
                    '(SELECT 1 FROM member_sessions s WHERE s.browser_hash=member_session_browsers.browser_hash)', (now,))

    def ensure_browser(self, con, token, now):
        key = digest(token)
        con.execute('INSERT INTO member_session_browsers VALUES(?,0,?,?) '
                    'ON CONFLICT(browser_hash) DO UPDATE SET expires_at=max(expires_at,excluded.expires_at)',
                    (key, now, now + self.ttl + 600))
        return key

    def live(self, con, credential, now):
        return con.execute('''SELECT s.*,u.username,u.name FROM member_sessions s JOIN users u ON u.id=s.owner
            WHERE s.credential_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
              AND s.auth_version=u.auth_version''', (credential, now)).fetchone()

    def resolve(self, con, signed, now, ua=''):
        if not signed:
            return None
        value, issued = signed
        uid, av, csrf = value.get('uid'), value.get('av'), value.get('csrf')
        if not isinstance(uid, str) or type(av) is not int or not isinstance(csrf, str) or not 20 <= len(csrf) <= 200:
            return None
        key = digest(csrf)
        if type(value.get('session_v')) is not int or value.get('session_v') != 1:
            if 'session_v' in value or issued > self.legacy_cutoff or issued + self.legacy_ttl <= now:
                return None
            old = con.execute('SELECT * FROM member_sessions WHERE credential_hash=?', (key,)).fetchone()
            if not old:
                user = con.execute('SELECT auth_version FROM users WHERE id=?', (uid,)).fetchone()
                if not user or user['auth_version'] != av:
                    return None
                browser = self.ensure_browser(con, self.browser_token(value), now)
                con.execute('''INSERT OR IGNORE INTO member_sessions
                    (id,credential_hash,owner,auth_version,browser_hash,device,created_at,last_seen_at,expires_at,legacy,retain_until)
                    VALUES(?,?,?,?,?,?,?,?,?,1,?)''',
                    (secrets.token_hex(16), key, uid, av, browser, device_label(ua), issued, now,
                     issued + self.legacy_ttl, self.legacy_until))
                self.cap(con, uid, key, now)
            else:
                # A later legitimate pre-cutoff signature can extend an active
                # legacy row, but a tombstone is never resurrected by re-signing.
                con.execute('UPDATE member_sessions SET expires_at=max(expires_at,?) '
                            'WHERE credential_hash=? AND legacy=1 AND revoked_at IS NULL',
                            (issued + self.legacy_ttl, key))
        row = self.live(con, key, now)
        if not row or row['owner'] != uid or row['auth_version'] != av:
            return None
        token = self.browser_token(value)
        if not token or not secrets.compare_digest(row['browser_hash'], digest(token)):
            return None
        return row

    def actor(self):
        now = time.time()
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row = self.resolve(con, self.request_signed(), now, request.headers.get('User-Agent', ''))
            if not row:
                return None
            con.execute('UPDATE member_sessions SET last_seen_at=? WHERE id=? AND last_seen_at<=?',
                        (now, row['id'], now - LAST_SEEN_INTERVAL))
            g.member_session = dict(row)
            return {'id': row['owner'], 'username': row['username'], 'name': row['name'],
                    'auth_version': row['auth_version'], 'role': 'member',
                    'householdId': self.app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default')}

    def bootstrap(self):
        token = session.get('browser_id')
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            # This is deliberately the only anonymous GET bootstrap. A stale
            # bootstrap response can still discard a later login; it grants no member access.
            session.clear()
            session['browser_id'] = secrets.token_urlsafe(32)
            session.permanent = True

    def current(self, con):
        row = self.resolve(con, self.request_signed(), time.time(), request.headers.get('User-Agent', ''))
        if not row:
            raise self.Problem('会话已失效，请重新登录', 401)
        return row

    def capture(self, claim=False, member=False):
        now = time.time()
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            self.clean(con, now)
            signed = self.request_signed()
            row = self.resolve(con, signed, now, request.headers.get('User-Agent', ''))
            if member and not row:
                raise self.Problem('会话已失效，请重新登录', 401)
            token = self.browser_token(session) or secrets.token_urlsafe(32)
            key = self.ensure_browser(con, token, now)
            if claim:
                con.execute('UPDATE member_session_browsers SET generation=generation+1 WHERE browser_hash=?', (key,))
            generation = con.execute('SELECT generation FROM member_session_browsers WHERE browser_hash=?', (key,)).fetchone()[0]
            context = {'browserHash': key, 'generation': generation,
                       'credentialHash': row['credential_hash'] if row else None,
                       'owner': row['owner'] if row else None, 'av': row['auth_version'] if row else None}
        return context, token

    def validate_context(self, con, context, member=False):
        if not isinstance(context, dict) or type(context.get('generation')) is not int or not isinstance(context.get('browserHash'), str):
            raise self.Problem('认证请求已失效，请重新开始', 401)
        now = time.time()
        browser = con.execute('SELECT generation,expires_at FROM member_session_browsers WHERE browser_hash=?',
                              (context['browserHash'],)).fetchone()
        if not browser or browser['generation'] != context['generation'] or browser['expires_at'] <= now:
            raise self.Problem('认证请求已被更新，请重新开始', 409)
        credential = context.get('credentialHash')
        row = self.live(con, credential, now) if credential else None
        if credential and (not row or row['browser_hash'] != context['browserHash'] or row['owner'] != context.get('owner') or row['auth_version'] != context.get('av')):
            raise self.Problem('发起认证的会话已失效，请重新开始', 401)
        if member and not row:
            raise self.Problem('请重新登录后授权', 401)
        return row

    def advance(self, con, keys, now):
        for key in set(keys):
            con.execute('UPDATE member_session_browsers SET generation=generation+1,expires_at=max(expires_at,?) '
                        'WHERE browser_hash=?', (now + self.ttl + 600, key))

    def revoke_browser(self, con, key, now):
        con.execute('UPDATE member_sessions SET revoked_at=? WHERE browser_hash=? AND revoked_at IS NULL', (now, key))
        self.advance(con, [key], now)

    def cap(self, con, owner, keep, now):
        rows = con.execute('SELECT id,browser_hash FROM member_sessions WHERE owner=? AND revoked_at IS NULL AND expires_at>? '
                           'AND credential_hash<>? ORDER BY created_at DESC,id DESC', (owner, now, keep)).fetchall()
        for row in rows[MAX_ACTIVE-1:]:
            con.execute('UPDATE member_sessions SET revoked_at=? WHERE id=?', (now, row['id']))
            self.advance(con, [row['browser_hash']], now)

    def complete_login(self, con, user, context, token):
        self.validate_context(con, context)
        fresh = con.execute('SELECT auth_version FROM users WHERE id=?', (user['id'],)).fetchone()
        if not fresh or fresh['auth_version'] != user['auth_version'] or digest(token) != context['browserHash']:
            raise self.Problem('账号已更新，请重新登录', 409)
        now = time.time()
        self.revoke_browser(con, context['browserHash'], now)
        csrf = secrets.token_urlsafe(32)
        con.execute('''INSERT INTO member_sessions
            (id,credential_hash,owner,auth_version,browser_hash,device,created_at,last_seen_at,expires_at,retain_until)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (secrets.token_hex(16), digest(csrf), user['id'], user['auth_version'], context['browserHash'],
             device_label(request.headers.get('User-Agent', '')), now, now, now+self.ttl, now+self.ttl))
        self.cap(con, user['id'], digest(csrf), now)
        return {'uid': user['id'], 'av': user['auth_version'], 'csrf': csrf, 'session_v': 1, 'browser_id': token}

    def install(self, value):
        session.clear()
        session.update(value)
        session.permanent = True

    def anonymous(self, token=None):
        token = token or self.browser_token(session)
        session.clear()
        if token:
            session['browser_id'] = token
            session.permanent = True

    def oauth_context(self, mode):
        context, token = self.capture(claim=True, member=mode != 'login')
        # Explicit authentication starts may mutate the cookie. Upgrade a live
        # legacy credential first so a post-cutoff nonce signature is not rejected.
        if session.get('browser_id') != token:
            session['browser_id'] = token
        if context['credentialHash'] and session.get('session_v') != 1:
            session['session_v'] = 1
        if not session.permanent:
            session.permanent = True
        return context

    def oauth_context_from_state(self, state):
        try:
            context = json.loads(state.get('auth_context') or 'null')
        except (TypeError, ValueError):
            context = None
        token = self.browser_token(session)
        if not token or not isinstance(context, dict) or context.get('browserHash') != digest(token):
            raise self.Problem('认证请求已失效，请重新开始', 401)
        return context, token

    def revoke_cookie(self, raw):
        """WSGI switch: verify only the original household's signed cookie."""
        signed = self.signed(raw)
        if not signed:
            return
        token = self.browser_token(signed[0])
        if not token:
            return
        now = time.time()
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row = self.resolve(con, signed, now)
            if row:
                self.revoke_browser(con, row['browser_hash'], now)
            elif not signed[0].get('uid'):
                # A stale member or anonymous cookie must not revoke a newer
                # member in that browser. Anonymous starts can only be cancelled
                # while this browser still has no live member session.
                live = con.execute('SELECT 1 FROM member_sessions s JOIN users u ON u.id=s.owner '
                                   'WHERE s.browser_hash=? AND s.revoked_at IS NULL AND s.expires_at>? '
                                   'AND s.auth_version=u.auth_version', (digest(token), now)).fetchone()
                if not live:
                    self.advance(con, [digest(token)], now)


def register_sessions(app, engine, Problem, body, require_member):
    @app.get('/api/sessions')
    def sessions_list():
        require_member()
        with engine.db() as con:
            con.execute('BEGIN IMMEDIATE')
            current = engine.current(con)
            rows = con.execute('SELECT s.* FROM member_sessions s JOIN users u ON u.id=s.owner '
                               'WHERE s.owner=? AND s.revoked_at IS NULL AND s.expires_at>? AND s.auth_version=u.auth_version '
                               'ORDER BY s.last_seen_at DESC,s.created_at DESC', (current['owner'], time.time())).fetchall()
            result = [{'id': r['id'], 'device': r['device'], 'createdAt': iso(r['created_at']),
                       'lastSeenAt': iso(r['last_seen_at']), 'expiresAt': iso(r['expires_at']),
                       'current': r['id'] == current['id']} for r in rows]
        return jsonify(sessions=result, lastSeenIntervalSeconds=LAST_SEEN_INTERVAL)

    @app.delete('/api/sessions/<session_id>')
    def session_delete(session_id):
        require_member()
        if body() != {}:
            raise Problem('请提交空的 JSON 对象')
        now = time.time()
        with engine.db() as con:
            con.execute('BEGIN IMMEDIATE')
            current = engine.current(con)
            row = con.execute('SELECT * FROM member_sessions WHERE id=? AND owner=? AND revoked_at IS NULL AND expires_at>? '
                              'AND auth_version=?', (session_id, current['owner'], now, current['auth_version'])).fetchone()
            if not row:
                raise Problem('会话不存在或已失效', 404)
            is_current = row['id'] == current['id']
            engine.revoke_browser(con, row['browser_hash'], now)
        if is_current:
            engine.anonymous()
        return jsonify(ok=True, current=is_current)

    @app.post('/api/sessions/revoke-others')
    def sessions_revoke_others():
        require_member()
        if body() != {}:
            raise Problem('请提交空的 JSON 对象')
        with engine.db() as con:
            con.execute('BEGIN IMMEDIATE')
            current = engine.current(con)
            now = time.time()
            rows = con.execute('SELECT id,browser_hash FROM member_sessions WHERE owner=? AND id<>? AND revoked_at IS NULL '
                               'AND expires_at>? AND auth_version=?',
                               (current['owner'], current['id'], now, current['auth_version'])).fetchall()
            for row in rows:
                con.execute('UPDATE member_sessions SET revoked_at=? WHERE id=?', (now, row['id']))
            engine.advance(con, [r['browser_hash'] for r in rows], now)
        return jsonify(ok=True, revoked=len(rows))
