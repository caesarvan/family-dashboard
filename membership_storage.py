"""Keep platform coordination ahead of every household transaction.

Connections remain ordinary SQLite connections. A short autocommit statement
borrows the platform guard; a transaction retains it until commit/rollback.
No guard is retained just because a connection or a network request is open.
The personal-account engine owns the reentrant, process-safe platform guard.
"""
from contextlib import contextmanager
import sqlite3
import threading
import time

from flask import current_app, has_request_context, request


_leases = threading.local()


@contextmanager
def connection_authority(engine):
    # Connections may commit in a different order from opening. Keep a single
    # engine context alive until every connection using it has released its
    # transaction, rather than nesting generator contexts in that order.
    active = getattr(_leases, 'active', None)
    if active is None:
        active = _leases.active = {}
    lease = active.get(engine)
    if lease is None:
        guard = engine.guard()
        guard.__enter__()
        lease = active[engine] = {'guard': guard, 'count': 0}
    lease['count'] += 1
    try:
        yield
    finally:
        lease['count'] -= 1
        if lease['count'] == 0:
            del active[engine]
            lease['guard'].__exit__(None, None, None)


class HouseholdCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        return self.connection._statement(super().execute, sql, parameters)

    def executemany(self, sql, parameters):
        return self.connection._statement(super().executemany, sql, parameters)

    def executescript(self, script):
        return self.connection._statement(super().executescript, script)


class HouseholdConnection(sqlite3.Connection):
    authority = None
    validate_actor = None
    _platform_guard = None
    _statement_depth = 0

    def _acquire(self):
        if self._platform_guard is None and self.authority is not None:
            engine = self.authority()
            if engine is not None:
                guard = connection_authority(engine)
                guard.__enter__()
                self._platform_guard = guard

    def _release(self):
        guard, self._platform_guard = self._platform_guard, None
        if guard is not None:
            guard.__exit__(None, None, None)

    def _statement(self, operation, *args):
        self._statement_depth += 1
        try:
            starting = self._platform_guard is None
            self._acquire()
            if starting and self._statement_depth == 1 and self.validate_actor is not None:
                self.validate_actor(self)
            return operation(*args)
        finally:
            self._statement_depth -= 1
            if self._statement_depth == 0 and not self.in_transaction:
                self._release()

    def cursor(self, factory=HouseholdCursor):
        if factory is not HouseholdCursor:
            raise ValueError('Household connections require the coordinated cursor')
        return super().cursor(factory)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters):
        return self.cursor().executemany(sql, parameters)

    def executescript(self, script):
        return self.cursor().executescript(script)

    def commit(self):
        try:
            return super().commit()
        finally:
            if not self.in_transaction:
                self._release()

    def rollback(self):
        try:
            return super().rollback()
        finally:
            if not self.in_transaction:
                self._release()

    def close(self):
        try:
            return super().close()
        finally:
            self._release()

    def __exit__(self, kind, value, traceback):
        # CPython's base context manager commits through C, bypassing our
        # Python commit override; always release its platform guard as well.
        try:
            return super().__exit__(kind, value, traceback)
        finally:
            if not self.in_transaction:
                self._release()


def personal_engine(app):
    platform = app.extensions.get('household_platform') or app.config.get('HOUSEHOLD_PLATFORM')
    return getattr(platform, 'personal_accounts', None)


def connect_household(app, path, **kwargs):
    con = sqlite3.connect(path, factory=HouseholdConnection, **kwargs)
    con.authority = lambda: personal_engine(app)
    def validate_actor(current):
        if not has_request_context() or current_app._get_current_object() is not app:
            return
        # Flask g belongs to the application context, which can outlive or be
        # shared by nested requests. Only enforce the proof captured for THIS
        # request; authentication itself must be able to establish a new proof.
        actor, captured = getattr(request, '_household_member_authority', (None, None))
        if not actor or actor.get('role') != 'member' or not captured:
            return
        sessions = app.extensions['member_sessions']
        live = sessions.live(current, captured['credential_hash'], time.time())
        if not live or (live['id'], live['owner'], live['auth_version']) != (captured['id'], actor['id'], actor['auth_version']):
            raise sessions.Problem('会话已失效，请重新登录', 401)
    con.validate_actor = validate_actor
    return con


@contextmanager
def authority_guard(app):
    engine = personal_engine(app)
    if engine is None:
        yield None
    else:
        with engine.guard() as con:
            yield con
