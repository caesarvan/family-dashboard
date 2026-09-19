"""Household-only OAuth identities and explicitly selected cloud sources.

No public registration. Provider identity comes from its authenticated UserInfo
endpoint after a browser-bound authorization-code exchange with PKCE. ID tokens
are never decoded as a shortcut to identity verification.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from cryptography.fernet import Fernet, InvalidToken
from flask import g, jsonify, redirect, request, session

from cloud_providers import CloudProvider, ProviderError
from sync_health import household_health

PROVIDERS = {
    'microsoft': {
        'name': 'Microsoft',
        'authorize': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        'token': 'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        'basic': ['openid', 'profile', 'email'],
        'sync': ['offline_access', 'User.Read', 'Calendars.Read', 'Calendars.Read.Shared', 'Tasks.ReadWrite'],
        # Shared-calendar access is optional. A personal account can return only
        # Calendars.Read even after being asked for Calendars.Read.Shared.
        'required_sync': ['User.Read', 'Calendars.Read', 'Tasks.ReadWrite'],
    },
    'google': {
        'name': 'Google',
        'authorize': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://oauth2.googleapis.com/token',
        'basic': ['openid', 'email', 'profile'],
        'sync': ['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/tasks'],
    },
}

GOOGLE_PHOTOS_SCOPE = 'https://www.googleapis.com/auth/photospicker.mediaitems.readonly'
_UNVERSIONED = object()


def photos_allowed(provider, scope):
    """Only a recorded, explicit Picker grant enables the photos capability."""
    return provider == 'google' and isinstance(scope, str) and GOOGLE_PHOTOS_SCOPE in scope.split()


def google_sync_capabilities(scope):
    """Permissions whose loss would break an existing Google sync connection."""
    missing = missing_sync_permissions('google', scope)
    return {
        'calendar_read': 'https://www.googleapis.com/auth/calendar.readonly' not in missing,
        'calendar_write': calendar_write_allowed('google', scope),
        'tasks': task_write_allowed('google', scope),
    }


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def missing_sync_permissions(provider, scope):
    """Compare permissions, accepting Graph's documented encoded scope URLs.

    A shared-calendar read grant covers the user's own calendars too. Never
    infer permissions from foreign resource names or a .default scope.
    """
    needed = {s.lower() for s in PROVIDERS[provider].get('required_sync', PROVIDERS[provider]['sync']) if s != 'offline_access'}
    if not isinstance(scope, str):
        return sorted(needed)
    if provider == 'microsoft':
        scope = unquote(scope)
        granted = {s.lower().removeprefix('https://graph.microsoft.com/') for s in scope.split()}
        if 'calendars.read.shared' in granted:
            granted.add('calendars.read')
        if 'calendars.readwrite' in granted or 'calendars.readwrite.shared' in granted:
            granted.add('calendars.read')
    else:
        granted = set(scope.lower().split())
        if 'https://www.googleapis.com/auth/calendar' in granted:
            granted.add('https://www.googleapis.com/auth/calendar.readonly')
    return sorted(needed - granted)


def calendar_write_allowed(provider, scope):
    """Only explicit granted calendar-write scope enables outbound publication."""
    if not isinstance(scope, str):
        return False
    if provider == 'microsoft':
        granted = {s.lower().removeprefix('https://graph.microsoft.com/') for s in unquote(scope).split()}
        return bool(granted & {'calendars.readwrite', 'calendars.readwrite.shared'})
    if provider != 'google':
        return False
    granted = set(scope.lower().split())
    return bool(granted & {'https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/calendar'})


def task_write_allowed(provider, scope):
    if not isinstance(scope, str):
        return False
    if provider == 'microsoft':
        return 'tasks.readwrite' in {s.lower().removeprefix('https://graph.microsoft.com/') for s in unquote(scope).split()}
    return provider == 'google' and 'https://www.googleapis.com/auth/tasks' in scope.lower().split()


class OAuthFailure(ProviderError):
    """Allowlisted provider diagnostics, never raw response text or credentials."""
    def __init__(self, payload, status=502):
        payload = payload if isinstance(payload, dict) else {}
        allowed = {'invalid_client', 'invalid_grant', 'invalid_request', 'invalid_scope', 'unauthorized_client',
                   'access_denied', 'interaction_required', 'consent_required', 'temporarily_unavailable',
                   'server_error', 'invalid_resource', 'unsupported_grant_type'}
        code = payload.get('error')
        self.oauth_error = code if isinstance(code, str) and code in allowed else 'unknown'
        codes = payload.get('error_codes', [])
        self.aadsts_codes = [c for c in codes if type(c) is int and 0 < c < 10_000_000_000][:5] if isinstance(codes, list) else []
        # Extract only numeric STS identifiers for diagnostics, never log descriptions.
        description = payload.get('error_description')
        if not self.aadsts_codes and isinstance(description, str):
            self.aadsts_codes = [int(c) for c in re.findall(r'\bAADSTS(\d{4,10})\b', description[:10000])][:5]
        self.upstream_status = status
        reauth = self.oauth_error in {'invalid_grant', 'interaction_required', 'consent_required'}
        super().__init__('授权已失效，请重新绑定' if reauth else '授权请求未完成，请根据页面提示处理',
                         401 if reauth else 502, reauth=reauth)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AccountBusy(ProviderError):
    def __init__(self):
        super().__init__('此账号正在同步，请稍后重试', 409)


class SelectionConflict(ProviderError):
    def __init__(self):
        super().__init__('来源选择已被更新，请重新读取后确认保存', 409)


class CloudAccounts:
    def __init__(self, app, path):
        self.app, self.path = app, str(path)
        self.origin = app.config.get('PUBLIC_ORIGIN', 'https://home.caesarcharles.world').rstrip('/')
        parsed = urlsplit(self.origin)
        if (parsed.scheme != 'https' and not (app.testing and self.origin == 'http://localhost')) or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise RuntimeError('PUBLIC_ORIGIN must be an HTTPS origin')
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256((app.secret_key + '|cloud-accounts-v1').encode()).digest()))
        self.lock_dir = Path(path).parent / 'cloud-locks'
        self.lock_dir.mkdir(mode=0o700, exist_ok=True)
        with self.db() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS cloud_accounts(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), provider TEXT NOT NULL,
              client_id TEXT NOT NULL, subject TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL,
              tokens TEXT NOT NULL, needs_reauth INTEGER NOT NULL DEFAULT 0,
              UNIQUE(provider,client_id,subject));
            CREATE TABLE IF NOT EXISTS cloud_sources(
              id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES cloud_accounts(id) ON DELETE CASCADE,
              remote_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, owner TEXT NOT NULL,
              is_primary INTEGER NOT NULL DEFAULT 0, last_success TEXT NOT NULL DEFAULT '',
              next_attempt REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', failures INTEGER NOT NULL DEFAULT 0,
              UNIQUE(account_id,kind,remote_id));
            CREATE UNIQUE INDEX IF NOT EXISTS cloud_one_primary ON cloud_sources(is_primary) WHERE is_primary=1;
            CREATE TABLE IF NOT EXISTS cloud_items(
              entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
              source_id TEXT NOT NULL REFERENCES cloud_sources(id) ON DELETE CASCADE, remote_id TEXT NOT NULL,
              UNIQUE(source_id,remote_id));
            CREATE TABLE IF NOT EXISTS cloud_writes(
              source_id TEXT NOT NULL REFERENCES cloud_sources(id) ON DELETE CASCADE, remote_id TEXT NOT NULL,
              record TEXT NOT NULL, expires REAL NOT NULL, PRIMARY KEY(source_id,remote_id));
            CREATE TABLE IF NOT EXISTS cloud_oauth_states(
              state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, provider TEXT NOT NULL,
              mode TEXT NOT NULL, owner TEXT, auth_version INTEGER, verifier TEXT NOT NULL,
              client_id TEXT NOT NULL, expires REAL NOT NULL);
            ''')
            con.execute('BEGIN IMMEDIATE')
            if 'auth_context' not in {r[1] for r in con.execute('PRAGMA table_info(cloud_oauth_states)')}:
                con.execute("ALTER TABLE cloud_oauth_states ADD COLUMN auth_context TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def db(self):
        from membership_storage import connect_household
        con = connect_household(self.app, self.path, timeout=15)
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

    @contextmanager
    def lock(self, account_id):
        """Process-safe locks serialize polling, writes, refresh and disconnect.

        OS releases locks on process death; no expiring lease can be stolen while
        a slow remote request is still in progress. Never wait on a web worker.
        """
        name = hashlib.sha256(account_id.encode()).hexdigest()
        handle = open(self.lock_dir / name, 'a+b')
        acquired = False
        try:
            if os.name == 'nt':
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise AccountBusy()
            else:
                import fcntl
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AccountBusy()
            acquired = True
            yield
        finally:
            if acquired:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value).encode()).decode()

    def decrypt(self, value):
        try:
            return json.loads(self.cipher.decrypt(value.encode()))
        except (InvalidToken, ValueError, TypeError):
            raise ProviderError('授权凭证不可读取，请重新绑定账号', 401, reauth=True)

    def credentials(self, provider):
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise ProviderError('不支持的账号平台', 404)
        return tuple(self.app.config.get(provider.upper() + suffix, '') for suffix in ('_CLIENT_ID', '_CLIENT_SECRET'))

    def provider_status(self):
        return [{'id': p, 'name': cfg['name'], 'configured': all(self.credentials(p)),
                 'loginUrl': f'/auth/{p}/login', 'callbackUrl': self.origin + f'/auth/{p}/callback'}
                for p, cfg in PROVIDERS.items()]

    def authorize(self, provider, mode, user=None, calendar_write=False, account_id=None, photos=False):
        client_id, secret = self.credentials(provider)
        if not client_id or not secret:
            raise ProviderError('该平台等待管理员配置，请查看账号接入指南', 503)
        if calendar_write:
            if mode != 'bind' or not user or not account_id:
                raise ProviderError('请从已绑定账户升级日历权限', 400)
            account = self.account(account_id, user['id'])
            if account['provider'] != provider:
                raise ProviderError('账户平台不匹配', 400)
        target = None
        if photos:
            if provider != 'google' or mode != 'bind' or not user or calendar_write:
                raise ProviderError('请单独发起 Google 照片授权', 400)
            if account_id is not None:
                target = self.account(account_id, user['id'])
                if target['provider'] != provider or target['client_id'] != client_id:
                    raise ProviderError('请使用当前应用的本人 Google 账户', 400)
        verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        auth_context = self.app.extensions['member_sessions'].oauth_context(mode)
        browser = session.setdefault('oauth_browser', secrets.token_urlsafe(32))
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            self.app.extensions['member_sessions'].validate_context(con, auth_context, member=mode != 'login')
            auth_context['accounts'] = [dict(r) for r in con.execute(
                'SELECT id,owner,provider,client_id,subject FROM cloud_accounts WHERE provider=? AND client_id=?', (provider, client_id))]
            if target:
                expected = {k: target[k] for k in ('id', 'owner', 'provider', 'client_id', 'subject')}
                if expected not in auth_context['accounts']:
                    raise ProviderError('账户已变更，请重新发起照片授权', 409)
                auth_context['photosAccount'] = expected
            con.execute('DELETE FROM cloud_oauth_states WHERE expires<?', (time.time(),))
            if calendar_write and con.execute("SELECT count(*) FROM cloud_oauth_states WHERE owner=? AND mode LIKE 'bind_write:%'", (user['id'],)).fetchone()[0] >= 20:
                raise ProviderError('授权请求过多，请完成已有授权或稍后再试', 429)
            if photos and con.execute("SELECT count(*) FROM cloud_oauth_states WHERE owner=? AND mode LIKE 'bind_photos%'", (user['id'],)).fetchone()[0] >= 20:
                raise ProviderError('授权请求过多，请完成已有授权或稍后再试', 429)
            state_mode = 'bind_write:' + account_id if calendar_write else mode
            if photos:
                state_mode = 'bind_photos' + (':' + account_id if account_id else '')
            con.execute('INSERT INTO cloud_oauth_states '
                        '(state_hash,browser_hash,provider,mode,owner,auth_version,verifier,client_id,expires,auth_context) '
                        'VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (hashlib.sha256(state.encode()).hexdigest(), hashlib.sha256(browser.encode()).hexdigest(), provider,
                         state_mode, user['id'] if user else None, user['auth_version'] if user else None,
                         self.encrypt(verifier), client_id, time.time()+600, json.dumps(auth_context)))
        cfg = PROVIDERS[provider]
        scopes = cfg['basic'] + ([GOOGLE_PHOTOS_SCOPE] if photos else cfg['sync'] if mode == 'bind' else [])
        if calendar_write:
            scopes = scopes + (['Calendars.ReadWrite'] if provider == 'microsoft' else ['https://www.googleapis.com/auth/calendar.events'])
        params = {'client_id': client_id, 'redirect_uri': self.origin + f'/auth/{provider}/callback',
                  'response_type': 'code', 'scope': ' '.join(scopes), 'state': state,
                  'code_challenge_method': 'S256',
                  'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
        if provider == 'google':
            params.update(prompt='consent' if mode == 'bind' else 'select_account')
            if mode == 'bind':
                params.update(access_type='offline', include_granted_scopes='true')
        else:
            params.update(response_mode='query', prompt='select_account')
        return cfg['authorize'] + '?' + urlencode(params)

    def consume_state(self, provider, state):
        if not isinstance(state, str) or not 20 <= len(state) <= 200:
            return None
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        browser_hash = hashlib.sha256(session.get('oauth_browser', '').encode()).hexdigest()
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM cloud_oauth_states WHERE state_hash=?', (state_hash,)).fetchone()
            if not row or row['provider'] != provider or row['expires'] < time.time() or not secrets.compare_digest(row['browser_hash'], browser_hash):
                return None
            con.execute('DELETE FROM cloud_oauth_states WHERE state_hash=?', (state_hash,))
            return dict(row)

    def token_request(self, provider, params):
        endpoint = PROVIDERS[provider]['token']
        transport = self.app.config.get('OAUTH_TRANSPORT')
        try:
            if transport:
                value = transport(provider, dict(params))
            else:
                req = Request(endpoint, data=urlencode(params).encode(), method='POST',
                              headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
                with build_opener(NoRedirect()).open(req, timeout=15) as result:
                    raw = result.read(1_000_001)
                    if len(raw) > 1_000_000:
                        raise ProviderError('授权服务器响应过大', 502)
                    value = json.loads(raw)
        except HTTPError as error:
            # Provider error text can include credentials or personal data.
            try:
                payload = json.loads(error.read(10000))
            except (ValueError, UnicodeError):
                payload = {}
            raise OAuthFailure(payload, error.code) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ProviderError('授权服务暂时无法连接，请稍后重试', 502) from None
        if isinstance(value, dict) and value.get('error'):
            raise OAuthFailure(value)
        if not isinstance(value, dict) or not isinstance(value.get('access_token'), str) or not value['access_token']:
            raise ProviderError('授权响应无效，请重新授权', 502)
        if value.get('token_type', 'Bearer').lower() != 'bearer':
            raise ProviderError('授权类型不受支持', 502)
        try:
            expires = max(60, min(int(value.get('expires_in', 3600)), 86400))
        except (ValueError, TypeError):
            raise ProviderError('授权有效期无效', 502)
        return {key: value[key] for key in ('access_token', 'refresh_token', 'scope') if key in value} | {'expires_at': time.time()+expires}

    def provider(self, name, access_token):
        factory = self.app.config.get('CLOUD_PROVIDER_FACTORY', CloudProvider)
        return factory(name, access_token, transport=self.app.config.get('CLOUD_TRANSPORT'))

    def account(self, account_id, owner=None):
        with self.db() as con:
            row = con.execute('SELECT * FROM cloud_accounts WHERE id=?', (account_id,)).fetchone()
            if not row or (owner and row['owner'] != owner):
                raise ProviderError('账号不存在或不属于当前成员', 404)
            self.active_owner(con, row['owner'])
            return dict(row)

    @staticmethod
    def active_owner(con, owner):
        if not con.execute("SELECT 1 FROM household_memberships WHERE member_id=? AND state='active'", (owner,)).fetchone():
            raise ProviderError('成员已退出家庭，同步已停止', 403)

    def media_account_transition(self, con, before, *, tokens=None, identity=None, reauth=False):
        """Media withdrawal shares the account writer's existing transaction.

        A normal refresh retains omitted scope on the same grant. An explicit
        new grant without Picker permission is different from a transient API
        failure. This hook never performs network I/O or commits caller work.
        """
        media = self.app.extensions.get('household_media')
        if media is None or before is None:
            return
        if not con.in_transaction:
            raise RuntimeError('Account media transition requires a transaction')
        reason = None
        if identity is not None and any(before[key] != identity.get(key) for key in ('owner','provider','client_id','subject')):
            reason = 'identity_changed'
        elif tokens is not None:
            previous_scope = None
            readable = True
            try:
                previous_scope = self.decrypt(before['tokens']).get('scope')
            except ProviderError:
                readable = False
            if not readable:
                reason = 'reauth'
            elif photos_allowed(before['provider'], previous_scope) and not photos_allowed(before['provider'], tokens.get('scope')):
                reason = 'scope_revoked' if isinstance(tokens.get('scope'), str) else 'reauth'
        if reason is None and reauth:
            reason = 'reauth'
        if reason:
            media.on_account_authority_changed(con, before['id'], reason)
            con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def request_account(self, con, account_id, owner, auth_context=None):
        """Validate an HTTP caller in the same transaction as its final read/write."""
        self.active_owner(con, owner)
        if auth_context is not None:
            current = self.app.extensions['member_sessions'].validate_context(con, auth_context, member=True)
            if current['owner'] != owner:
                raise ProviderError('登录状态已变化，请重新登录', 401)
        current = con.execute('SELECT * FROM cloud_accounts WHERE id=? AND owner=?', (account_id, owner)).fetchone()
        if not current:
            raise ProviderError('账号不存在或不属于当前成员', 404)
        return current

    def active_provider(self, account, *, auth_context=None):
        # Re-check before decrypting or refreshing a stored cloud credential.
        fresh_account = self.account(account['id'], account['owner'])
        if any(fresh_account[k] != account[k] for k in ('provider', 'client_id', 'subject', 'tokens', 'needs_reauth')):
            raise ProviderError('账户授权已变化，请重新读取', 409)
        client_id, secret = self.credentials(account['provider'])
        if not secret or client_id != account['client_id']:
            raise ProviderError('应用配置已变更，请重新绑定账号', 401, reauth=True)
        if account['needs_reauth']:
            raise ProviderError('账号需要重新授权', 401, reauth=True)
        tokens = self.decrypt(account['tokens'])
        if tokens.get('expires_at', 0) < time.time()+60:
            if not tokens.get('refresh_token'):
                raise ProviderError('缺少离线授权，请重新绑定', 401, reauth=True)
            fresh = self.token_request(account['provider'], {'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'],
                                                           'client_id': client_id, 'client_secret': secret})
            tokens.update(fresh)
            with self.db() as con:
                con.execute('BEGIN IMMEDIATE')
                self.active_owner(con, account['owner'])
                current = (self.request_account(con, account['id'], account['owner'], auth_context)
                           if auth_context is not None else con.execute('SELECT * FROM cloud_accounts WHERE id=?', (account['id'],)).fetchone())
                if not current or any(current[k] != account[k] for k in ('owner','provider','client_id','subject','tokens','needs_reauth')):
                    raise ProviderError('账户授权已变更，请重试', 409)
                self.media_account_transition(con, current, tokens=tokens)
                con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=?', (self.encrypt(tokens), account['id']))
        return self.provider(account['provider'], tokens['access_token'])

    def photos_access_token(self, account_id, owner):
        """Server-only credential access; caller must authorize its own operation.

        The caller supplies the authenticated owner in this household. This
        lock/ownership check is not a member-session or media-write transaction.
        Never serialize the returned credential in an HTTP response or log.
        """
        if not isinstance(owner, str) or not owner or not isinstance(account_id, str) or not account_id:
            raise ProviderError('账号不存在或不属于当前成员', 404)
        self.account(account_id, owner)
        with self.lock(account_id):
            account = self.account(account_id, owner)
            client_id, secret = self.credentials('google')
            if account['provider'] != 'google':
                raise ProviderError('此账户不支持 Google 照片', 403)
            if not secret or account['client_id'] != client_id or account['needs_reauth']:
                raise ProviderError('账号需要重新授权', 401, reauth=True)
            tokens = self.decrypt(account['tokens'])
            if not photos_allowed('google', tokens.get('scope')):
                raise ProviderError('请先明确授权 Google 照片选择器', 403)
            fresh = None
            if tokens.get('expires_at', 0) < time.time()+60:
                refresh = tokens.get('refresh_token')
                if not isinstance(refresh, str) or not refresh:
                    raise ProviderError('缺少离线授权，请重新绑定', 401, reauth=True)
                # No scope is requested: RFC 6749 sections 5.1/6 permit an
                # omitted response scope to retain this same grant's scope.
                fresh = self.token_request('google', {'grant_type': 'refresh_token', 'refresh_token': refresh,
                                                      'client_id': client_id, 'client_secret': secret})
                if 'refresh_token' in fresh and (not isinstance(fresh['refresh_token'], str) or not fresh['refresh_token']):
                    raise ProviderError('授权响应无效，请重新授权', 502)
            with self.db() as con:
                con.execute('BEGIN IMMEDIATE')
                self.active_owner(con, owner)
                current = con.execute('SELECT * FROM cloud_accounts WHERE id=?', (account_id,)).fetchone()
                if not current or current['owner'] != owner:
                    raise ProviderError('账号不存在或不属于当前成员', 404)
                # Also reject out-of-band replacement/revocation while the
                # refresh HTTP request was in flight, even if a writer ignored
                # the account lock. Ciphertext equality binds the refresh grant.
                if any(current[k] != account[k] for k in ('provider', 'client_id', 'subject', 'tokens', 'needs_reauth')) or self.credentials('google') != (client_id, secret):
                    raise ProviderError('账户授权已变更，请重试', 409)
                if fresh is not None:
                    tokens.update(fresh)
                    self.media_account_transition(con, current, tokens=tokens)
                    con.execute('UPDATE cloud_accounts SET tokens=? WHERE id=? AND owner=?',
                                (self.encrypt(tokens), account_id, owner))
            # Persist an explicitly reduced grant before rejecting use, so the
            # public capability cannot continue to claim a revoked permission.
            if not photos_allowed('google', tokens.get('scope')):
                raise ProviderError('照片权限未获授权，请重新连接照片', 403)
            return tokens['access_token']

    def sync_provider(self, account, *, auth_context=None):
        """Do not present a photo-only grant as calendar/task authorization."""
        def check(current):
            if current['provider'] == 'google':
                tokens = self.decrypt(current['tokens'])
                if 'scope' in tokens and missing_sync_permissions('google', tokens['scope']):
                    raise ProviderError('请单独授权日历和待办后再选择同步来源', 403)
        check(account)
        provider = self.active_provider(account, auth_context=auth_context) if auth_context is not None else self.active_provider(account)
        check(self.account(account['id'], account['owner']))
        return provider

    @staticmethod
    def source_json(row):
        return {'id': row['id'], 'remoteId': row['remote_id'], 'kind': row['kind'], 'name': row['name'],
                'owner': row['owner'], 'primary': bool(row['is_primary']), 'lastSuccess': row['last_success'], 'error': row['error']}

    @staticmethod
    def adapter_source(row):
        return {'id': row['remote_id'], 'kind': row['kind'], 'name': row['name'], 'owner': row['owner']}

    @staticmethod
    def selection_version(con, account_id):
        # Local IDs distinguish removal/recreation of the same remote source.
        # Sync progress and provider display-name changes are not user choices.
        rows = [list(row) for row in con.execute(
            'SELECT id,kind,remote_id,owner,is_primary FROM cloud_sources WHERE account_id=? ORDER BY id',
            (account_id,))]
        value = json.dumps([account_id, rows], ensure_ascii=True, separators=(',', ':'))
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def accounts_json(self, owner, *, auth_context=None):
        with self.db() as con:
            con.execute('BEGIN')
            if auth_context is not None:
                current = self.app.extensions['member_sessions'].validate_context(con, auth_context, member=True)
                if current['owner'] != owner:
                    raise ProviderError('登录状态已变化，请重新登录', 401)
            result = []
            for a in con.execute('SELECT * FROM cloud_accounts WHERE owner=? ORDER BY provider,name', (owner,)):
                unreadable = False
                try:
                    tokens = self.decrypt(a['tokens'])
                    photos = photos_allowed(a['provider'], tokens.get('scope'))
                    # Legacy grants without a recorded scope retain discovery;
                    # explicit photo-only grants never masquerade as sync.
                    sync = 'scope' not in tokens or not missing_sync_permissions(a['provider'], tokens.get('scope'))
                except ProviderError:
                    photos, sync, unreadable = False, False, True
                result.append({'id': a['id'], 'provider': a['provider'], 'name': a['name'], 'email': a['email'],
                               'needsReauth': bool(unreadable or a['needs_reauth'] or self.credentials(a['provider'])[0] != a['client_id']),
                               'capabilities': {'photos': photos, 'sync': sync},
                               'selectionVersion': self.selection_version(con, a['id']),
                               'sources': [self.source_json(s) for s in con.execute('SELECT * FROM cloud_sources WHERE account_id=?', (a['id'],))]})
            return result

    def summary(self):
        with self.db() as con:
            # Counts, legacy timestamps and freshness describe one read snapshot.
            con.execute('BEGIN')
            sources = con.execute('SELECT s.*,a.provider FROM cloud_sources s JOIN cloud_accounts a ON a.id=s.account_id').fetchall()
            primary = next(({'id': s['id'], 'name': s['name']} for s in sources if s['is_primary']), None)
            return {'mode': 'polling', 'taskIntervalSeconds': 30, 'calendarIntervalSeconds': 60,
                    'health': household_health(con, {p: self.credentials(p)[0] for p in PROVIDERS}),
                    'configured': any(p['configured'] for p in self.provider_status()),
                    'connectedAccounts': con.execute('SELECT COUNT(*) FROM cloud_accounts').fetchone()[0],
                    'selectedSources': len(sources), 'lastSuccess': max((s['last_success'] for s in sources), default=''),
                    'error': next((s['error'] for s in sources if s['error']), ''), 'primaryTaskSource': primary,
                    'taskSources': [{'id': s['id'], 'name': s['name'], 'provider': s['provider'], 'writable': True} for s in sources if s['kind'] == 'tasks']}

    def discovered_sources(self, account, auth_context=None):
        """Called under the account lock; stale HTTP failures cannot revoke grants."""
        try:
            provider = self.sync_provider(account, auth_context=auth_context)
            account = self.account(account['id'], account['owner'])
            return provider.list_sources()
        except ProviderError as error:
            if error.reauth and auth_context is not None:
                self.failure(account['id'], error, auth_context=auth_context,
                             owner=account['owner'], expected_account=account)
            raise

    def discovery(self, account_id, owner, *, auth_context=None):
        self.account(account_id, owner)
        with self.lock(account_id):
            account = self.account(account_id, owner)
            sources = self.discovered_sources(account, auth_context)
            with self.db() as con:
                con.execute('BEGIN')
                self.request_account(con, account_id, owner, auth_context)
                selected = [self.source_json(s) for s in con.execute('SELECT * FROM cloud_sources WHERE account_id=?', (account_id,))]
                version = self.selection_version(con, account_id)
            return {'sources': sources, 'selected': selected, 'selectionVersion': version}

    @staticmethod
    def remove_source(con, source_id):
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_publications'").fetchone():
            con.execute("UPDATE task_publications SET previous_status=CASE WHEN status='disconnected' THEN previous_status ELSE status END,status='disconnected',error='来源已断开；本地任务和云端原任务均保留',updated_at=? WHERE source_id=?", (stamp(), source_id))
            con.execute('DELETE FROM cloud_items WHERE source_id=? AND entity_id IN (SELECT entity_id FROM task_publications)', (source_id,))
        con.execute('DELETE FROM entities WHERE id IN (SELECT entity_id FROM cloud_items WHERE source_id=?)', (source_id,))
        con.execute('DELETE FROM cloud_sources WHERE id=?', (source_id,))

    def select_sources(self, account_id, owner, chosen, *, selection_version=_UNVERSIONED, auth_context=None):
        if not isinstance(chosen, list) or len(chosen) > 12:
            raise ProviderError('每个账号最多选择 12 个日历或清单', 400)
        if selection_version is not _UNVERSIONED and (not isinstance(selection_version, str) or not re.fullmatch(r'[0-9a-f]{64}', selection_version)):
            raise ProviderError('来源选择版本无效，请重新读取列表', 400)
        self.account(account_id, owner)
        with self.lock(account_id):
            account = self.account(account_id, owner)
            # A valid member may remove stale mirrors even after cloud grant revocation.
            discovered = self.discovered_sources(account, auth_context) if chosen else []
            available = {(s['kind'], s['id']): s for s in discovered}
            validated, seen = [], set()
            for entry in chosen:
                if not isinstance(entry, dict) or not isinstance(entry.get('remoteId'), str) or not isinstance(entry.get('kind'), str):
                    raise ProviderError('来源选择格式不正确', 400)
                key = (entry['kind'], entry['remoteId'])
                found = available.get(key)
                if not found or key in seen:
                    raise ProviderError('所选来源不可用或重复，请重新读取列表', 400)
                seen.add(key)
                scope = entry.get('owner', owner if entry['kind'] == 'calendar' else 'shared')
                if not isinstance(scope, str) or (entry['kind'] == 'tasks' and scope != 'shared'):
                    raise ProviderError('日历归属无效；清单作为家庭共同清单共享', 400)
                primary = entry.get('primary', False)
                if not isinstance(primary, bool) or (primary and entry['kind'] != 'tasks'):
                    raise ProviderError('共同主清单必须是 Microsoft To Do 或 Google Tasks 清单', 400)
                if entry['kind'] == 'tasks' and not found.get('writable', False):
                    raise ProviderError('所选清单没有写入权限', 400)
                validated.append((key, found, scope, int(primary)))
            if sum(v[3] for v in validated) > 1:
                raise ProviderError('只能设置一份共同主清单', 400)
            with self.db() as con:
                con.execute('BEGIN IMMEDIATE')
                self.request_account(con, account_id, owner, auth_context)
                for _, _, scope, _ in validated:
                    if scope != 'shared':
                        self.active_owner(con, scope)
                if selection_version is not _UNVERSIONED and not secrets.compare_digest(selection_version, self.selection_version(con, account_id)):
                    raise SelectionConflict()
                total = con.execute('SELECT count(*) FROM cloud_sources WHERE account_id<>?', (account_id,)).fetchone()[0]
                if total + len(validated) > 24:
                    raise ProviderError('家庭最多同步 24 个来源，请先取消不需要的来源', 400)
                old = {(s['kind'], s['remote_id']): s for s in con.execute('SELECT * FROM cloud_sources WHERE account_id=?', (account_id,))}
                if any(v[3] for v in validated):
                    other_primary = con.execute('SELECT account_id FROM cloud_sources WHERE is_primary=1 AND account_id<>?', (account_id,)).fetchone()
                    if other_primary:
                        raise ProviderError('已有共同主清单，请由该账号的拥有者先取消主清单设置', 409)
                con.execute('UPDATE cloud_sources SET is_primary=0 WHERE account_id=?', (account_id,))
                for key, row in old.items():
                    if key not in seen:
                        self.remove_source(con, row['id'])
                for key, found, scope, primary in validated:
                    source_id = old[key]['id'] if key in old else secrets.token_hex(16)
                    con.execute('''INSERT INTO cloud_sources(id,account_id,remote_id,kind,name,owner,is_primary)
                                VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                                name=excluded.name,owner=excluded.owner,is_primary=excluded.is_primary,next_attempt=0''',
                                (source_id, account_id, key[1], key[0], str(found['name'])[:200], scope, primary))
                    # A changed calendar label takes effect immediately, without a remote request.
                    for entity in con.execute('SELECT e.* FROM entities e JOIN cloud_items i ON e.id=i.entity_id WHERE i.source_id=?', (source_id,)).fetchall():
                        value = json.loads(entity['data'])
                        if value.get('owner') != scope:
                            value['owner'] = scope
                            con.execute('UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=?', (json.dumps(value), stamp(), entity['id']))
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
                version = self.selection_version(con, account_id)
            return {'ok': True, 'queued': bool(validated), 'selectionVersion': version}

    def queue_sync(self, account_id, owner, *, auth_context=None):
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            self.request_account(con, account_id, owner, auth_context)
            queued = con.execute('UPDATE cloud_sources SET next_attempt=0 WHERE account_id=?', (account_id,)).rowcount
        return {'ok': True, 'queued': bool(queued)}

    def disconnect(self, account_id, owner, auth_context=None):
        self.account(account_id, owner)
        with self.lock(account_id):
            self.account(account_id, owner)
            with self.db() as con:
                con.execute('BEGIN IMMEDIATE')
                if auth_context is not None:
                    current = self.app.extensions['member_sessions'].validate_context(con, auth_context, member=True)
                    if current['owner'] != owner:
                        raise ProviderError('登录状态已变化，请重新登录', 401)
                account = con.execute('SELECT * FROM cloud_accounts WHERE id=? AND owner=?', (account_id, owner)).fetchone()
                if not account:
                    raise ProviderError('账号不存在或不属于当前成员', 404)
                media = self.app.extensions.get('household_media')
                if media is not None:
                    media.on_account_removed(con, account_id)
                for s in con.execute('SELECT id FROM cloud_sources WHERE account_id=?', (account_id,)).fetchall():
                    self.remove_source(con, s['id'])
                con.execute('DELETE FROM cloud_accounts WHERE id=?', (account_id,))
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def save_record(self, con, source, account, record):
        self.active_owner(con, account['owner'])
        remote_id = record['id']
        if source['kind'] == 'tasks' and self.app.extensions.get('task_publish'):
            linked = self.app.extensions['task_publish'].observe(con, source, record)
            if linked:
                return linked
        # The local journey entity remains the displayed record. Polling an
        # event created by our publication queue must not create a second copy.
        if source['kind'] == 'calendar' and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calendar_publications'").fetchone():
            publication = con.execute('SELECT * FROM calendar_publications WHERE source_id=? AND remote_id=?',
                                      (source['id'], remote_id)).fetchone()
            if publication and con.execute('SELECT 1 FROM entities WHERE id=?', (publication['entity_id'],)).fetchone():
                if publication['status'] == 'published' and publication['etag'] and publication['etag'] != record['version']:
                    con.execute("UPDATE calendar_publications SET status='conflict',error=?,updated_at=? WHERE id=?",
                                ('云端事项已修改，持续发布已暂停，请核对两边内容。', stamp(), publication['id']))
                old = con.execute('SELECT entity_id FROM cloud_items WHERE source_id=? AND remote_id=?', (source['id'], remote_id)).fetchone()
                if old:
                    con.execute('DELETE FROM entities WHERE id=?', (old['entity_id'],))
                return publication['entity_id'], bool(old)
        entity_id = 'cloud-' + hashlib.sha256((source['id']+'|'+remote_id).encode()).hexdigest()[:32]
        data = dict(record['data'])
        data['owner'] = source['owner']
        data['sync'] = {'provider': account['provider'], 'sourceId': source['id'], 'remoteId': remote_id,
                        'version': record['version'], 'readOnly': source['kind'] == 'calendar'}
        kind = 'events' if source['kind'] == 'calendar' else 'tasks'
        encoded = json.dumps(data, sort_keys=True)
        old = con.execute('SELECT * FROM entities WHERE id=?', (entity_id,)).fetchone()
        if not old:
            con.execute('INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)', (entity_id, kind, encoded, stamp()))
        elif json.loads(old['data']) != data:
            con.execute('UPDATE entities SET data=?,revision=revision+1,updated_at=? WHERE id=?', (encoded, stamp(), entity_id))
        con.execute('INSERT OR IGNORE INTO cloud_items VALUES(?,?,?)', (entity_id, source['id'], remote_id))
        return entity_id, not old or json.loads(old['data']) != data

    def publish(self, source, account, records):
        if len(records) > 2500 or len({r['id'] for r in records}) != len(records):
            raise ProviderError('来源内容过多或包含重复记录，同步未发布', 502)
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            self.active_owner(con, account['owner'])
            if not con.execute('SELECT 1 FROM cloud_sources WHERE id=?', (source['id'],)).fetchone():
                return
            incoming = {r['id']: r for r in records}
            con.execute('DELETE FROM cloud_writes WHERE expires<?', (time.time(),))
            for write in con.execute('SELECT * FROM cloud_writes WHERE source_id=?', (source['id'],)).fetchall():
                expected = json.loads(write['record'])
                seen = incoming.get(write['remote_id'])
                if seen and seen['data'] == expected['data']:
                    con.execute('DELETE FROM cloud_writes WHERE source_id=? AND remote_id=?', (source['id'], write['remote_id']))
                else:
                    # Some providers briefly return old snapshots after accepting a write.
                    incoming[write['remote_id']] = expected
            other_count = con.execute('SELECT count(*) FROM cloud_items WHERE source_id<>?', (source['id'],)).fetchone()[0]
            if other_count + len(incoming) > 20000:
                raise ProviderError('同步记录已达家庭上限，请缩小同步范围', 400)
            changed = bool(source['error']) or not source['last_success']
            for record in incoming.values():
                _, updated = self.save_record(con, source, account, record)
                changed = changed or updated
            for old in con.execute('SELECT * FROM cloud_items WHERE source_id=?', (source['id'],)).fetchall():
                if old['remote_id'] not in incoming:
                    con.execute('DELETE FROM entities WHERE id=?', (old['entity_id'],))
                    changed = True
            interval = 30 if source['kind'] == 'tasks' else 60
            con.execute("UPDATE cloud_sources SET last_success=?,error='',failures=0,next_attempt=? WHERE id=?", (stamp(), time.time()+interval, source['id']))
            if changed:
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def failure(self, account_id, error, source_id=None, *, auth_context=None, owner=None, expected_account=None):
        # Only local, sanitized error messages enter the shared state.
        message = '授权已失效，请账号拥有者重新绑定' if error.reauth else '同步暂时失败，保留上次内容并自动重试'
        with self.db() as con:
            con.execute('BEGIN IMMEDIATE')
            if auth_context is not None:
                account = self.request_account(con, account_id, owner, auth_context)
                if expected_account is not None and any(account[k] != expected_account[k] for k in ('owner', 'provider', 'client_id', 'subject', 'tokens', 'needs_reauth')):
                    raise ProviderError('账户授权已变更，请重试', 409)
            if error.reauth:
                account = con.execute('SELECT * FROM cloud_accounts WHERE id=?', (account_id,)).fetchone()
                self.media_account_transition(con, account, reauth=True)
                con.execute('UPDATE cloud_accounts SET needs_reauth=1 WHERE id=?', (account_id,))
            rows = con.execute('SELECT * FROM cloud_sources WHERE account_id=?', (account_id,)).fetchall()
            changed = False
            for row in rows:
                if source_id and row['id'] != source_id and not error.reauth:
                    continue
                changed = changed or row['error'] != message
                delay = min(900, 30 * 2 ** min(row['failures'], 5))
                con.execute('UPDATE cloud_sources SET error=?,failures=failures+1,next_attempt=? WHERE id=?', (message, time.time()+delay, row['id']))
            if changed:
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")

    def tick(self):
        with self.db() as con:
            # Round-robin by due time prevents a busy source from starving others.
            due = con.execute('SELECT * FROM cloud_sources WHERE next_attempt<=? ORDER BY next_attempt LIMIT 24', (time.time(),)).fetchall()
        for original in due:
            aid = original['account_id']
            try:
                with self.lock(aid):
                    with self.db() as con:
                        fresh = con.execute('SELECT * FROM cloud_sources WHERE id=? AND next_attempt<=?', (original['id'], time.time())).fetchone()
                    if not fresh:
                        continue
                    source = dict(fresh)
                    account = self.account(aid)
                    provider = self.active_provider(account)
                    current = datetime.now(timezone.utc)
                    records = provider.snapshot(self.adapter_source(source), current-timedelta(days=30), current+timedelta(days=365))
                    self.publish(source, account, records)
            except AccountBusy:
                continue
            except ProviderError as error:
                self.failure(aid, error, original['id'])
            except Exception:
                self.failure(aid, ProviderError('同步响应异常'), original['id'])
                self.app.logger.error('Cloud synchronization failed; provider payload omitted')
        # Also maintained with no connected sources so stale authorizations expire.
        with self.db() as con:
            con.execute('DELETE FROM cloud_oauth_states WHERE expires<?', (time.time(),))

    def task_write(self, payload, source_id=None, existing=None):
        if existing:
            mirrored = json.loads(existing['data'])
            source_id = mirrored['sync']['sourceId']
            if set(payload) - {'revision', 'done'} or not isinstance(payload.get('done'), bool):
                raise ProviderError('同步任务目前支持勾选与恢复，其他修改请在原清单完成', 400)
        with self.db() as con:
            if source_id is None:
                row = con.execute('SELECT * FROM cloud_sources WHERE is_primary=1').fetchone()
            else:
                row = con.execute('SELECT * FROM cloud_sources WHERE id=?', (source_id,)).fetchone()
            if not row:
                if source_id in (None, '') and not existing:
                    return None
                raise ProviderError('同步来源已断开，请刷新页面', 409)
            source = dict(row)
        if source['kind'] != 'tasks':
            raise ProviderError('日程为只读同步，请在原日历中修改', 403)
        if not existing and payload.get('dependsOn'):
            raise ProviderError('云端清单不支持前置事项，请选择看板本地任务后保存', 400)
        if not existing and (payload.get('owner', 'shared') != 'shared' or payload.get('tripId')):
            raise ProviderError('云端任务使用共同归属；旅行准备可选择看板本地清单', 400)
        aid = source['account_id']
        with self.lock(aid):
            account = self.account(aid)
            with self.db() as con:
                if not con.execute('SELECT 1 FROM cloud_sources WHERE id=?', (source['id'],)).fetchone():
                    raise ProviderError('同步来源已变更，请刷新页面', 409)
                if existing:
                    latest = con.execute('SELECT revision FROM entities WHERE id=?', (existing['id'],)).fetchone()
                    if not latest or latest['revision'] != payload.get('revision'):
                        raise ProviderError('任务已变更，请刷新后重试', 409)
            try:
                provider = self.active_provider(account)
                record = provider.write_task(self.adapter_source(source), payload,
                                             remote_id=mirrored['sync']['remoteId'] if existing else None,
                                             version=mirrored['sync']['version'] if existing else None)
            except ProviderError as error:
                if error.reauth:
                    self.failure(aid, error)
                raise
            with self.db() as con:
                con.execute('BEGIN IMMEDIATE')
                entity_id, _ = self.save_record(con, source, account, record)
                con.execute('INSERT OR REPLACE INTO cloud_writes VALUES(?,?,?,?)', (source['id'], record['id'], json.dumps(record), time.time()+120))
                con.execute('UPDATE cloud_sources SET next_attempt=0 WHERE id=?', (source['id'],))
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
                revision = con.execute('SELECT revision FROM entities WHERE id=?', (entity_id,)).fetchone()[0]
            return {'ok': True, 'id': entity_id, 'revision': revision}


def register_accounts(app, db, Problem, body, require_member, limited):
    engine = CloudAccounts(app, Path(app.config['DATA_DIR']) / 'household.sqlite3')
    members = app.extensions['member_sessions']
    app.extensions['cloud_accounts'] = engine

    @app.errorhandler(ProviderError)
    def provider_problem(error):
        if isinstance(error, SelectionConflict):
            return jsonify(error=error.message, code='selection_conflict'), error.status
        return jsonify(error=error.message), error.status

    def request_context():
        require_member()
        context, _ = members.capture(claim=False, member=True)
        g.account_request_context = context
        return context

    @app.after_request
    def account_response_fence(response):
        # Discovery may take seconds. Do not release a successful private DTO
        # after this browser was revoked or replaced while serializing it.
        context = getattr(g, 'account_request_context', None)
        if context is not None and 200 <= response.status_code < 300:
            try:
                with engine.db() as con:
                    con.execute('BEGIN')
                    members.validate_context(con, context, member=True)
            except (Problem, ProviderError) as error:
                response = jsonify(error=error.message)
                response.status_code = error.status
        return response

    @app.get('/api/auth/providers')
    def providers():
        return jsonify(providers=engine.provider_status(), origin=engine.origin)

    @app.get('/auth/<provider>/login')
    def external_login(provider):
        if request.host_url.rstrip('/') != engine.origin:
            if provider not in PROVIDERS:
                return redirect(engine.origin + '/?auth=error&reason=not_configured')
            return redirect(engine.origin + f'/auth/{provider}/login')
        limited('oauth_start', 30)
        try:
            url = engine.authorize(provider, 'login')
        except ProviderError:
            return redirect(engine.origin + '/?auth=error&reason=not_configured')
        return redirect(url)

    @app.get('/api/accounts')
    def accounts():
        context = request_context()
        return jsonify(accounts=engine.accounts_json(g.actor['id'], auth_context=context), providers=engine.provider_status())

    @app.post('/api/accounts/bind')
    def bind():
        if request.host_url.rstrip('/') != engine.origin:
            raise Problem('请通过 ' + engine.origin + ' 登录后绑定账号', 400)
        limited('oauth_bind', 20)
        return jsonify(url=engine.authorize(body().get('provider'), 'bind', g.actor))

    @app.post('/api/accounts/google-photos/bind')
    def bind_google_photos():
        require_member()
        if request.host_url.rstrip('/') != engine.origin:
            raise Problem('请通过 ' + engine.origin + ' 登录后连接照片', 400)
        value = body()
        if set(value) - {'accountId'} or ('accountId' in value and
                (not isinstance(value['accountId'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['accountId']))):
            raise Problem('照片授权仅接受可选的本人 accountId', 400)
        limited('oauth_bind', 20)
        return jsonify(url=engine.authorize('google', 'bind', g.actor, account_id=value.get('accountId'), photos=True))

    @app.get('/auth/<provider>/callback')
    def callback(provider):
        stage = 'state_validation'
        def fail(reason, error=None, missing=None):
            app.logger.warning('OAuth callback failed provider=%s stage=%s reason=%s status=%s oauth=%s aadsts=%s missing=%s',
                               provider if provider in PROVIDERS else 'unknown', stage, reason,
                               getattr(error, 'upstream_status', getattr(error, 'status', 0)),
                               getattr(error, 'oauth_error', 'none'), getattr(error, 'aadsts_codes', []), missing or [])
            return redirect(engine.origin + '/?auth=error&reason=' + reason)
        state = engine.consume_state(provider, request.args.get('state'))
        if not state:
            return fail('invalid_state')
        photos = state['mode'] == 'bind_photos' or state['mode'].startswith('bind_photos:')
        if request.args.get('error'):
            stage = 'authorization_return'
            return fail('provider_denied', OAuthFailure({'error': request.args.get('error'),
                        'error_description': request.args.get('error_description', '')}, 0))
        if state['mode'].startswith('bind') and (not g.actor or g.actor['role'] != 'member' or
                g.actor['id'] != state['owner'] or g.actor['auth_version'] != state['auth_version']):
            return fail('bind_session_changed')
        try:
            auth_context, browser_token = members.oauth_context_from_state(state)
            with engine.db() as con:
                members.validate_context(con, auth_context, member=state['mode'] != 'login')
        except Problem:
            return fail('session_changed')
        code = request.args.get('code', '')
        if not code or len(code) > 12000:
            return fail('provider_error')
        try:
            client_id, secret = engine.credentials(provider)
            if not secret or client_id != state['client_id']:
                return fail('not_configured')
            stage = 'token_exchange'
            tokens = engine.token_request(provider, {'grant_type': 'authorization_code', 'code': code,
                       'redirect_uri': engine.origin + f'/auth/{provider}/callback', 'client_id': client_id,
                       'client_secret': secret, 'code_verifier': engine.decrypt(state['verifier'])})
            stage = 'identity_lookup'
            identity = engine.provider(provider, tokens['access_token']).identity()
            subject = identity.get('subject')
            if not isinstance(subject, str) or not subject or len(subject) > 512:
                return fail('identity_failed')
            stage = 'account_lookup'
            with engine.db() as con:
                existing = con.execute('SELECT * FROM cloud_accounts WHERE provider=? AND client_id=? AND subject=?', (provider, client_id, subject)).fetchone()
            if state['mode'].startswith('bind_write:') and (not existing or existing['id'] != state['mode'].split(':', 1)[1]):
                return fail('provider_error')
            photos_target = auth_context.get('photosAccount') if photos else None
            if photos and (provider != 'google' or (state['mode'].startswith('bind_photos:') and
                    (not photos_target or not existing or existing['id'] != state['mode'].split(':', 1)[1] or
                     any(existing[k] != photos_target.get(k) for k in ('id', 'owner', 'provider', 'client_id', 'subject'))))):
                return fail('provider_error')
            if state['mode'] == 'login':
                if not existing:
                    return fail('unbound_account')
                with engine.lock(existing['id']), engine.db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    members.validate_context(con, auth_context)
                    fresh_account = con.execute('SELECT * FROM cloud_accounts WHERE id=?', (existing['id'],)).fetchone()
                    expected = next((x for x in auth_context.get('accounts', []) if x.get('id') == existing['id']), None)
                    if not fresh_account or not expected or any(fresh_account[k] != expected.get(k) for k in ('id','owner','provider','client_id','subject')):
                        return fail('unbound_account')
                    user = con.execute('SELECT id,auth_version FROM users WHERE id=?', (fresh_account['owner'],)).fetchone()
                    if not user:
                        return fail('unbound_account')
                    cookie = members.complete_login(con, user, auth_context, browser_token)
                members.install(cookie)
                return redirect(engine.origin + '/?auth=signed-in')
            account_id = existing['id'] if existing else secrets.token_hex(16)
            # A stable identity lock also prevents simultaneous first-time binds.
            identity_lock = 'identity|' + provider + '|' + client_id + '|' + subject
            stage = 'account_binding'
            with engine.lock(identity_lock), engine.lock(account_id), engine.db() as con:
                con.execute('BEGIN IMMEDIATE')
                initiator = members.validate_context(con, auth_context, member=True)
                if initiator['owner'] != state['owner'] or initiator['auth_version'] != state['auth_version']:
                    return fail('bind_session_changed')
                user = con.execute('SELECT auth_version FROM users WHERE id=?', (state['owner'],)).fetchone()
                if not user or user['auth_version'] != state['auth_version']:
                    return fail('bind_session_changed')
                existing = con.execute('SELECT * FROM cloud_accounts WHERE provider=? AND client_id=? AND subject=?', (provider, client_id, subject)).fetchone()
                previous = next((x for x in auth_context.get('accounts', []) if x.get('provider') == provider and x.get('client_id') == client_id and x.get('subject') == subject), None)
                if previous and (not existing or any(existing[k] != previous.get(k) for k in ('id','owner','provider','client_id','subject'))):
                    return fail('bind_session_changed')
                if existing and existing['owner'] != state['owner']:
                    return fail('already_bound')
                if existing and existing['id'] != account_id:
                    return fail('provider_error')
                if photos_target and (not existing or any(existing[k] != photos_target.get(k) for k in ('id', 'owner', 'provider', 'client_id', 'subject'))):
                    return fail('bind_session_changed')
                if not existing and con.execute('SELECT count(*) FROM cloud_accounts WHERE owner=?', (state['owner'],)).fetchone()[0] >= 4:
                    return fail('account_limit')
                if existing and not tokens.get('refresh_token'):
                    tokens['refresh_token'] = engine.decrypt(existing['tokens']).get('refresh_token')
                stage = 'offline_permission'
                if not tokens.get('refresh_token'):
                    return fail('missing_refresh_token')
                if photos and not isinstance(tokens['refresh_token'], str):
                    return fail('missing_refresh_token')
                stage = 'scope_validation'
                if photos:
                    if not photos_allowed(provider, tokens.get('scope')):
                        return fail('insufficient_permissions', missing=['photos_picker'])
                    if existing:
                        previous_scope = engine.decrypt(existing['tokens']).get('scope')
                        required = google_sync_capabilities(previous_scope)
                        for source in con.execute('SELECT kind FROM cloud_sources WHERE account_id=?', (account_id,)):
                            required['calendar_read' if source['kind'] == 'calendar' else 'tasks'] = True
                        granted = google_sync_capabilities(tokens.get('scope'))
                        lost = sorted(k for k in required if required[k] and not granted[k])
                        if lost:
                            return fail('insufficient_permissions', missing=lost)
                elif 'scope' in tokens:
                    missing = missing_sync_permissions(provider, tokens['scope'])
                    if missing:
                        return fail('insufficient_permissions', missing=missing)
                if state['mode'].startswith('bind_write:') and not calendar_write_allowed(provider, tokens.get('scope')):
                    return fail('insufficient_permissions', missing=['calendar_write'])
                stage = 'account_save'
                engine.media_account_transition(con, existing, tokens=tokens,
                    identity={'owner':state['owner'],'provider':provider,'client_id':client_id,'subject':subject})
                con.execute('''INSERT INTO cloud_accounts(id,owner,provider,client_id,subject,name,email,tokens)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,email=excluded.email,tokens=excluded.tokens,needs_reauth=0''',
                    (account_id, state['owner'], provider, client_id, subject, str(identity.get('name') or PROVIDERS[provider]['name'])[:200],
                     str(identity.get('email') or '')[:254], engine.encrypt(tokens)))
                if not photos:
                    con.execute("UPDATE cloud_sources SET next_attempt=0,error='',failures=0 WHERE account_id=?", (account_id,))
                con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'")
            return redirect(engine.origin + '/?auth=' + ('photos-connected' if photos else 'connected'))
        except Problem:
            return fail('session_changed')
        except ProviderError as error:
            code = getattr(error, 'oauth_error', '')
            if code in {'invalid_client', 'invalid_grant'}:
                reason = code
            elif code == 'invalid_scope':
                reason = 'insufficient_permissions'
            else:
                reason = {'token_exchange': 'token_failed', 'identity_lookup': 'identity_failed'}.get(stage, 'provider_error')
            return fail(reason, error)

    @app.route('/api/accounts/<account_id>/sources', methods=['GET', 'POST'])
    def sources(account_id):
        context = request_context()
        if request.method == 'GET':
            return jsonify(engine.discovery(account_id, g.actor['id'], auth_context=context))
        data = body()
        return jsonify(engine.select_sources(account_id, g.actor['id'], data.get('sources'),
            selection_version=data.get('selectionVersion', _UNVERSIONED), auth_context=context))

    @app.post('/api/accounts/<account_id>/sync')
    def sync_now(account_id):
        context = request_context()
        engine.account(account_id, g.actor['id'])
        limited('sync_now', 10, 60)
        return jsonify(engine.queue_sync(account_id, g.actor['id'], auth_context=context))

    @app.delete('/api/accounts/<account_id>')
    def disconnect(account_id):
        require_member()
        context, _ = members.capture(claim=False, member=True)
        engine.disconnect(account_id, g.actor['id'], auth_context=context)
        return jsonify(ok=True)

    return engine
