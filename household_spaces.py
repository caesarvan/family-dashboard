"""Invitation-only households with separate databases and signing/encryption keys.

The original household remains at /data/household.sqlite3. A routing cookie only
chooses a household; its separately signed session still has to authenticate.
"""
from collections import OrderedDict
from contextlib import contextmanager
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

from flask import g, jsonify, request
from itsdangerous import URLSafeSerializer, BadSignature
from werkzeug.wrappers import Request, Response


DEFAULT_PREFERENCES = {'theme': 'forest', 'density': 'comfortable', 'homeView': 'today'}


def register_preferences(app, db, Problem, body, require_member, audit):
    with app.app_context():
        db().execute('CREATE TABLE IF NOT EXISTS member_preferences '
                     '(owner TEXT PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL)')
        db().commit()

    @app.route('/api/preferences', methods=['GET', 'PUT'])
    def preferences():
        require_member()
        if request.method == 'GET':
            row = db().execute('SELECT data FROM member_preferences WHERE owner=?', (g.actor['id'],)).fetchone()
            return jsonify({**DEFAULT_PREFERENCES, **(json.loads(row['data']) if row else {})})
        value = body()
        choices = {'theme': {'forest', 'light', 'ocean'}, 'density': {'comfortable', 'compact'},
                   'homeView': {'today', 'week', 'around'}}
        if set(value) != set(choices) or any(not isinstance(value[k], str) or value[k] not in v for k, v in choices.items()):
            raise Problem('请选择有效的主题、密度和默认日程视图')
        db().execute('INSERT INTO member_preferences VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET data=excluded.data',
                     (g.actor['id'], json.dumps(value)))
        audit('preferences_update')
        db().commit()
        return jsonify(value)


class HouseholdPlatform:
    def __init__(self, app, factory):
        self.app, self.factory = app, factory
        self.root = Path(app.config['DATA_DIR'])
        self.path = self.root / 'platform.sqlite3'
        self.signer = URLSafeSerializer(app.secret_key, salt='household-routing-v1')
        self.main_wsgi = app.wsgi_app
        self.cache = OrderedDict()
        self.lock = threading.RLock()
        with self.db() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS households(
              id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS household_invitations(
              hash TEXT PRIMARY KEY, created_at REAL NOT NULL, expires REAL NOT NULL, used_at REAL);
            ''')
            con.execute('INSERT OR IGNORE INTO households VALUES(?,?,?,?)',
                        ('default', 'home', '我们的家', datetime.now(timezone.utc).isoformat()))
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def households(self):
        with self.db() as con:
            return [dict(r) for r in con.execute('SELECT * FROM households ORDER BY created_at')]

    def child(self, household, passwords=None):
        uid = household['id']
        if uid == 'default':
            return self.app
        if not re.fullmatch(r'[a-f0-9]{24}', uid):
            raise ValueError('Invalid household id')
        with self.lock:
            # A cached Flask app is not evidence that its storage still exists.
            # This improves routing recovery; member auth additionally opens
            # SQLite with mode=rw so a later removal cannot create an empty DB.
            if not passwords and not (self.root / 'spaces' / uid / 'household.sqlite3').is_file():
                raise RuntimeError('Household storage unavailable')
            if uid in self.cache:
                self.cache.move_to_end(uid)
                return self.cache[uid]
            config = {k: self.app.config[k] for k in (
                'TESTING', 'SESSION_COOKIE_SECURE', 'PERMANENT_SESSION_LIFETIME', 'PUBLIC_ORIGIN', 'MICROSOFT_CLIENT_ID',
                'MICROSOFT_CLIENT_SECRET', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
                'OPENAI_API_KEY', 'OPENAI_MODEL') if k in self.app.config}
            config.update(DATA_DIR=str(self.root / 'spaces' / uid), _HOUSEHOLD_CHILD=True,
                          HOUSEHOLD_INFO=dict(household), HOUSEHOLD_PLATFORM=self,
                          SECRET_KEY=hmac.new(self.app.secret_key.encode(), ('household|' + uid).encode(), hashlib.sha256).hexdigest())
            if passwords:
                config.update(passwords)
            else:
                # Never silently initialize a missing household with environment passwords.
                config.update(MEMBER1_PASSWORD='', MEMBER2_PASSWORD='')
                if not (Path(config['DATA_DIR']) / 'household.sqlite3').is_file():
                    raise RuntimeError('Household storage unavailable')
            child = self.factory(config)
            self.cache[uid] = child
            while len(self.cache) > 24:
                self.cache.popitem(last=False)
            return child

    def __call__(self, environ, start_response):
        incoming = Request(environ)
        def failure(message, status):
            headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'}
            if incoming.path.startswith('/api/'):
                response = Response(json.dumps({'error': message, 'recoveryUrl': '/space/home'}, ensure_ascii=False),
                                    status=status, content_type='application/json; charset=utf-8', headers=headers)
            else:
                from markupsafe import escape
                response = Response('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>家庭空间暂不可用</title><body style="background:#102019;color:#ecf1e6;font:18px/1.7 system-ui;margin:10vh auto;padding:24px;max-width:600px">'
                    '<h1>家庭空间暂不可用</h1><p>' + str(escape(message)) + '</p><a style="color:#b1d5ad" href="/space/home">返回家庭入口</a></body></html>',
                    status=status, content_type='text/html; charset=utf-8', headers=headers)
            return response(environ, start_response)
        if incoming.path.startswith('/space/'):
            if incoming.method != 'GET':
                return Response(status=405)(environ, start_response)
            slug = incoming.path[len('/space/'):]
            with self.db() as con:
                found = con.execute('SELECT id FROM households WHERE slug=?', (slug,)).fetchone()
            if not found:
                return failure('家庭空间不存在，请核对家庭地址', 404)
            original_cookie = incoming.cookies.get(self.app.config['SESSION_COOKIE_NAME'])
            if original_cookie:
                # A route change must revoke the credential in the ORIGINAL
                # household; the target household must never receive this cookie.
                original_id = 'default'
                original_route = incoming.cookies.get('household_space')
                if original_route:
                    try:
                        original_id = self.signer.loads(original_route)
                    except BadSignature:
                        original_id = None
                try:
                    if original_id == 'default':
                        original_app = self.app
                    else:
                        with self.db() as con:
                            original_household = con.execute('SELECT * FROM households WHERE id=?', (original_id,)).fetchone() if isinstance(original_id, str) else None
                        original_app = self.child(original_household) if original_household else None
                    if original_app:
                        original_app.extensions['member_sessions'].revoke_cookie(original_cookie)
                except (RuntimeError, sqlite3.DatabaseError, OSError):
                    return failure('原家庭会话暂无法安全退出，请稍后重试', 503)
            response = Response(status=303, headers={'Location': '/', 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
            response.set_cookie('household_space', self.signer.dumps(found['id']), httponly=True, samesite='Lax',
                                secure=self.app.config['SESSION_COOKIE_SECURE'], max_age=86400 * 365)
            response.delete_cookie(self.app.config['SESSION_COOKIE_NAME'])
            response.delete_cookie('household_tv')
            return response(environ, start_response)
        uid = 'default'
        raw = incoming.cookies.get('household_space')
        if raw:
            try:
                uid = self.signer.loads(raw)
            except BadSignature:
                return failure('家庭入口已失效，请返回家庭入口重新选择', 400)
        if uid == 'default':
            return self.main_wsgi(environ, start_response)
        with self.db() as con:
            household = con.execute('SELECT * FROM households WHERE id=?', (uid,)).fetchone() if isinstance(uid, str) else None
        if not household:
            return failure('家庭空间不可用，请核对家庭地址', 404)
        try:
            application = self.child(household)
        except (RuntimeError, sqlite3.DatabaseError, OSError):
            return failure('此家庭的数据暂不可用，请稍后再试或返回家庭入口', 503)
        return application.wsgi_app(environ, start_response)


def register_spaces(app, db, Problem, body, require_member, limited, factory):
    platform = app.config.get('HOUSEHOLD_PLATFORM') or HouseholdPlatform(app, factory)
    app.extensions['household_platform'] = platform
    info = app.config.get('HOUSEHOLD_INFO') or {'id': 'default', 'slug': 'home', 'name': '我们的家'}

    @app.get('/api/spaces/current')
    def current_space():
        return jsonify(id=info['id'], name=info['name'], slug=info['slug'], entry='/space/' + info['slug'],
                       canInvite=bool(g.actor and g.actor['role'] == 'member' and g.actor['id'] == 'member1' and info['id'] == 'default'))

    @app.post('/api/spaces/invitations')
    def invite_household():
        require_member()
        if info['id'] != 'default' or g.actor['id'] != 'member1':
            raise Problem('只有平台管理员可以邀请新家庭', 403)
        limited('space_invite', 10, 3600)
        token = secrets.token_urlsafe(32)
        with platform.db() as con:
            con.execute('DELETE FROM household_invitations WHERE expires<?', (time.time(),))
            con.execute('INSERT INTO household_invitations VALUES(?,?,?,NULL)',
                        (hashlib.sha256(token.encode()).hexdigest(), time.time(), time.time() + 7 * 86400))
        return jsonify(invitation=token, expiresIn=7 * 86400), 201

    @app.post('/api/spaces/redeem')
    def redeem_household():
        limited('space_redeem', 10, 3600)
        value = body()
        name, slug = value.get('name'), value.get('slug')
        token = value.get('invitation')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise Problem('家庭名称请填写 1～40 个字符')
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z][a-z0-9-]{2,31}', slug) or slug == 'home':
            raise Problem('家庭地址请填写 3～32 位小写字母、数字或连字符，以字母开头')
        if not isinstance(token, str) or len(token) > 100:
            raise Problem('邀请码无效或已过期', 403)
        passwords = {k: value.get(k) for k in ('MEMBER1_PASSWORD', 'MEMBER2_PASSWORD')}
        if any(not isinstance(p, str) or not 12 <= len(p) <= 128 for p in passwords.values()):
            raise Problem('两位成员的密码分别需要 12～128 个字符')
        household = {'id': secrets.token_hex(12), 'slug': slug, 'name': name.strip(),
                     'created_at': datetime.now(timezone.utc).isoformat()}
        with platform.db() as con:
            con.execute('BEGIN IMMEDIATE')
            invite = con.execute('SELECT * FROM household_invitations WHERE hash=? AND used_at IS NULL AND expires>?',
                                 (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            if not invite:
                raise Problem('邀请码无效、已使用或已过期', 403)
            if con.execute('SELECT 1 FROM households WHERE slug=?', (slug,)).fetchone():
                raise Problem('这个家庭地址已被使用', 409)
            if con.execute('SELECT count(*) FROM households').fetchone()[0] >= platform.app.config.get('MAX_HOUSEHOLDS', 30):
                raise Problem('当前服务器的家庭名额已满', 409)
            platform.child(household, passwords)
            con.execute('INSERT INTO households VALUES(:id,:slug,:name,:created_at)', household)
            con.execute('UPDATE household_invitations SET used_at=? WHERE hash=?', (time.time(), invite['hash']))
        return jsonify(ok=True, name=household['name'], entry='/space/' + slug), 201

    if not app.config.get('_HOUSEHOLD_CHILD'):
        app.wsgi_app = platform
