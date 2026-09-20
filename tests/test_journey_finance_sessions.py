"""Actual captured sessions and SQLite transaction boundaries; no auth stubs."""
from contextlib import closing
import sqlite3
from types import SimpleNamespace

from flask import request, g
import pytest
from werkzeug.datastructures import ImmutableMultiDict

from test_app import app, member
from test_household_spaces import create_space
from test_device_sessions import install_connection, invalidate, ConnectionProxy
from test_journey_finance import (P, setup, apply_plan, request_body, confirm, create, database,
                                  protected, listing, offline)


def snapshot(app):
    with database(app) as con:
        return {table: [tuple(r) for r in con.execute('SELECT * FROM '+table+' ORDER BY 1')]
                for table in ('hub_journey_allocations', 'hub_journey_allocation_operations', 'audit', 'settings')}


def endpoint(c, h, j, p, operation):
    payload = request_body(c, h, apply_plan(j, p))
    if operation == 'receipt':
        assert confirm(c, h, payload).status_code == 200
    return {'list': ('GET', P, None), 'payments': ('GET', P + '/payments?journeyId=' + j['id'], None),
        'preview': ('POST', P + '/preview', apply_plan(j, p)),
        'confirm': ('POST', P + '/confirm', payload),
        'receipt': ('GET', P + '/operations/' + payload['requestId'], None)}[operation]


@pytest.mark.parametrize('operation', ['list', 'payments', 'preview', 'confirm', 'receipt'])
def test_revoked_after_global_guard_never_reads_or_writes(app, operation):
    c, h, j, p = setup(app)
    method, path, payload = endpoint(c, h, j, p, operation)
    before = snapshot(app)
    def revoke():
        if request.path == path.split('?')[0]:
            assert g.actor['id'] == 'member1'
            with database(app) as con: invalidate(con)
    app.before_request_funcs[None].append(revoke)
    result = c.open(path, method=method, json=payload, headers=h)
    assert result.status_code == 401, result.json
    assert 'PRIVATE_SYNTHETIC_TRAVEL_PAYMENT' not in result.get_data(as_text=True)
    assert snapshot(app) == before


@pytest.mark.parametrize('operation', ['list', 'payments', 'preview'])
def test_revoked_during_snapshot_is_rechecked_after_release(app, operation):
    c, h, j, p = setup(app)
    method, path, payload = endpoint(c, h, j, p, operation)
    before, seen = snapshot(app), []
    def revoke(sql):
        if sql.startswith('SELECT id,data,revision FROM hub_transactions') and not seen:
            with database(app) as writer: invalidate(writer)
            seen.append(True)
    install_connection(app, path.split('?')[0], method, after=revoke)
    result = c.open(path, method=method, json=payload, headers=h)
    assert seen == [True] and result.status_code == 401
    assert snapshot(app) == before


def test_same_owner_cookie_swap_after_guard_rejected(app):
    c, h, j, p = setup(app)
    other, _ = member(app)
    cookie = other.get_cookie('session').value
    def swap():
        if request.path == P:
            request.__dict__['cookies'] = ImmutableMultiDict({**dict(request.cookies), 'session': cookie})
    app.before_request_funcs[None].append(swap)
    assert c.get(P).status_code == 401


def test_expiry_after_audit_rolls_back_allocation_receipt_and_audit(app, monkeypatch):
    import member_sessions
    c, h, j, p = setup(app)
    payload = request_body(c, h, apply_plan(j, p))
    before = snapshot(app)
    with database(app) as con:
        expires = con.execute('SELECT max(expires_at) FROM member_sessions').fetchone()[0]
    def expire(sql):
        if sql.startswith('UPDATE settings SET revision=revision+1'):
            monkeypatch.setattr(member_sessions, 'time', SimpleNamespace(time=lambda: expires + 1))
    install_connection(app, P + '/confirm', 'POST', after=expire)
    assert confirm(c, h, payload).status_code == 401
    assert snapshot(app) == before


def test_post_commit_revocation_returns_unknown_but_minimal_receipt_is_durable(app):
    c, h, j, p = setup(app)
    payload = request_body(c, h, apply_plan(j, p))
    seen = []
    class RevokeAfterCommit(ConnectionProxy):
        def commit(self):
            self.connection.commit()
            if not seen:
                with database(app) as writer: invalidate(writer)
                seen.append(True)
    def hook():
        if request.path == P + '/confirm':
            con = sqlite3.connect(str(__import__('pathlib').Path(app.config['DATA_DIR']) / 'household.sqlite3'))
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA foreign_keys=ON')
            previous = getattr(g, 'db', None)
            if previous is not None:
                previous.close()
            g.db = RevokeAfterCommit(con)
    app.before_request_funcs[None].append(hook)
    assert confirm(c, h, payload).status_code == 401
    app.before_request_funcs[None].remove(hook)
    again, ah = member(app)
    assert again.get(P + '/operations/' + payload['requestId']).json['found'] is True
    assert confirm(again, ah, payload).json['replayed'] is True
    with database(app) as con:
        assert con.execute('SELECT count(*) FROM hub_journey_allocations').fetchone()[0] == 1


def test_owner_tv_and_other_household_cannot_read_private_history(app):
    c, h, j, p = setup(app)
    receipt, payload = create(c, h, j, p)
    other, oh = member(app, 2)
    assert listing(other, journeyId=j['id'])['summary']['currentAllocatedCents'] == 0
    assert other.get(P + '/operations/' + payload['requestId']).json['found'] is False
    assert other.post(P + '/preview', json={'operation': 'revoke', 'allocationId': receipt['allocationId'], 'revision': 1}, headers=oh).status_code == 404
    assert other.post(P + '/preview', json=apply_plan(j, p), headers=oh).status_code == 404
    assert 'PRIVATE_SYNTHETIC_TRAVEL_PAYMENT' not in other.get('/api/journeys/' + j['id']).get_data(as_text=True)
    tv = app.test_client()
    pair = tv.post('/api/pair/start', json={}).json
    assert c.post('/api/pair/approve', json={'code': pair['code'], 'name': 'Synthetic Travel TV'}, headers=h).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).json['approved']
    for path in (P, P + '/payments?journeyId=' + j['id'], P + '/operations/' + payload['requestId']):
        assert tv.get(path).status_code == 403
    assert 'PRIVATE_SYNTHETIC_TRAVEL_PAYMENT' not in tv.get('/api/state').get_data(as_text=True)
    assert app.test_client().get(P).status_code == 401
    b, _, space = create_space(app)
    assert b.get(space['entry']).status_code == 303
    assert b.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    bh = {'X-CSRF-Token': b.get('/api/me').json['csrf']}
    assert listing(b)['allocations'] == []

    assert b.get(P + '/operations/' + payload['requestId']).json['found'] is False
    rejected = confirm(b, bh, payload)
    assert rejected.status_code == 400 and rejected.json['code'] == 'journey_finance_invalid_request'
    assert listing(b)['allocations'] == []


def test_write_lock_contention_is_recoverable_without_receipt_or_partial_write(app):
    c, h, j, p = setup(app)
    payload = request_body(c, h, apply_plan(j, p))
    before, acquired = snapshot(app), []
    with closing(sqlite3.connect(str(__import__('pathlib').Path(app.config['DATA_DIR']) / 'household.sqlite3'))) as writer:
        def lock(sql):
            if sql == 'BEGIN IMMEDIATE' and not acquired:
                writer.execute('BEGIN IMMEDIATE')
                acquired.append(True)
        install_connection(app, P + '/confirm', 'POST', before=lock)
        try:
            response = confirm(c, h, payload)
            assert response.status_code == 503 and response.json['code'] == 'journey_finance_unavailable'
        finally:
            writer.rollback()
    assert snapshot(app) == before
    assert c.get(P + '/operations/' + payload['requestId']).json['found'] is False
    assert confirm(c, h, payload).status_code == 200
