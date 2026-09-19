"""Private reminder exports through real sessions/SQLite/ZIP, without network."""
from contextlib import closing
from datetime import timedelta
import json
import socket

import pytest

import data_portability as portability
import task_reminders
from test_data_portability import unpack
from test_household_spaces import create_space
from test_task_reminders import app, member, db, create, item, value, act


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Network forbidden in reminder export checks')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)


def reminder_rows(app):
    with closing(db(app)) as con:
        return {table: [tuple(r) for r in con.execute('SELECT * FROM '+table+' ORDER BY owner,rowid')]
                for table in ('task_reminders', 'task_reminder_operations')}


def export(c, h, shared=False):
    return c.post('/api/portability/export', json={'includeShared': shared}, headers=h)


def saved(app):
    own, headers = member(app); peer, ph = member(app, 2)
    uid = create(own, headers, title='DELETED_REMINDER_TITLE')
    read = act(own, headers, uid, value(item(own, uid)))
    assert read.status_code == 200
    snooze = act(peer, ph, uid, value(item(peer, uid), 'b', 'snooze',
        snoozedUntil=task_reminders.iso(app.test_clock[0]+timedelta(hours=1))))
    assert snooze.status_code == 200
    task = next(t for t in own.get('/api/state').json['tasks'] if t['id'] == uid)
    assert own.delete('/api/items/tasks/'+uid, json={'revision': task['revision']}, headers=headers).status_code == 200
    untouched = create(own, headers, title='ELIGIBLE_BUT_NOT_MATERIALIZED')
    # Future receipt extensions and internal DB fields must not widen an export.
    with closing(db(app)) as con, con:
        row = con.execute("SELECT result FROM task_reminder_operations WHERE owner='member1'").fetchone()
        receipt = json.loads(row['result'])
        receipt.update(title='HISTORICAL_TITLE_SECRET', token='TOKEN_SECRET',
                       payload={'credential': 'NESTED_SECRET'}, intentDigest='DIGEST_SECRET')
        con.execute("UPDATE task_reminder_operations SET result=?,intent_digest='RAW_DIGEST_SECRET' WHERE owner='member1'",
                    (json.dumps(receipt),))
    return own, headers, peer, ph, uid, untouched


@pytest.mark.parametrize('include_shared', [False, True])
def test_only_owner_persisted_history_with_explicit_allowlists(app, include_shared):
    own, h, peer, ph, uid, untouched = saved(app)
    before = reminder_rows(app)
    summary = own.get('/api/portability/summary')
    assert summary.status_code == 200
    assert summary.json['personal']['taskReminderStates'] == 1
    assert summary.json['personal']['taskReminderOperations'] == 1
    assert not any('reminder' in key.lower() for key in summary.json['shared'])
    data, files = unpack(export(own, h, include_shared))
    assert data['schemaVersion'] == 1
    reminder = data['personal']['taskReminders']
    assert set(reminder) == {'states', 'operations'}
    assert len(reminder['states']) == len(reminder['operations']) == 1
    assert reminder['states'][0]['taskId'] == uid
    assert set(reminder['states'][0]) == {'taskId', 'due', 'readAt', 'snoozedUntil', 'revision', 'createdAt', 'updatedAt'}
    assert reminder['states'][0]['readAt'] is not None and reminder['states'][0]['snoozedUntil'] is None
    operation = reminder['operations'][0]
    assert set(operation) == set(portability.REMINDER_OPERATION_FIELDS)
    assert operation['taskId'] == uid and operation['action'] == 'read'
    assert operation['revision'] == 1 and operation['readAt'] is not None and operation['snoozedUntil'] is None
    assert data['coverage']['taskReminders'] == 'owner_state_and_minimal_operation_history_without_task_content'
    assert 'taskReminders' not in data.get('shared', {})
    content = b''.join(files.values())
    for secret in ('DELETED_REMINDER_TITLE', 'HISTORICAL_TITLE_SECRET', 'TOKEN_SECRET', 'NESTED_SECRET',
                   'DIGEST_SECRET', 'RAW_DIGEST_SECRET', 'a'*32, 'b'*32):
        assert secret.encode() not in content
    assert 'requestId' not in json.dumps(reminder) and 'intent_digest' not in json.dumps(reminder)
    assert len(files) == 5 and 'personal.taskReminders' in files['README.txt'].decode()
    peer_data, _ = unpack(export(peer, ph, include_shared))
    peer_state = peer_data['personal']['taskReminders']['states'][0]
    assert peer_state['readAt'] is None and peer_state['snoozedUntil'] is not None
    assert peer_data['personal']['taskReminders']['operations'][0]['action'] == 'snooze'
    assert reminder_rows(app) == before  # No backfill for untouched or inactive history cleanup.
    with closing(db(app)) as con:
        assert con.execute('SELECT count(*) FROM task_reminders WHERE task_id=?', (untouched,)).fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM audit WHERE action='personal_data_export'").fetchone()[0] == 2


def test_future_receipt_fields_and_wrong_types_are_not_copied(app):
    own, h = member(app)
    with closing(db(app)) as con, con:
        con.execute('INSERT INTO task_reminder_operations VALUES(?,?,?,?,?)',
            ('member1', 'c'*32, 'NOT_AN_EXPORT_DIGEST', json.dumps({'requestId': 'c'*32,
             'taskId': {'private': 'NESTED_TASK_SECRET'}, 'occurrence': ['SECRET'], 'revision': True,
             'action': 'read', 'readAt': None, 'snoozedUntil': {'secret': 'NESTED_TIME_SECRET'},
             'committedAt': 'synthetic', 'title': 'TITLE_SECRET'}), 'synthetic'))
    before = reminder_rows(app)
    data, _ = unpack(export(own, h))
    assert data['personal']['taskReminders']['operations'] == [{'action': 'read', 'readAt': None, 'committedAt': 'synthetic'}]
    assert reminder_rows(app) == before


def test_legacy_household_without_tables_is_empty_without_schema_writes(app):
    own, h = member(app)
    with closing(db(app)) as con, con:
        con.execute('DROP TABLE task_reminder_operations')
        con.execute('DROP TABLE task_reminders')
    summary = own.get('/api/portability/summary').json
    assert summary['personal']['taskReminderStates'] == summary['personal']['taskReminderOperations'] == 0
    data, _ = unpack(export(own, h, True))
    assert data['personal']['taskReminders'] == {'states': [], 'operations': []}
    with closing(db(app)) as con:
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name LIKE 'task_reminder%'").fetchone()[0] == 0


def test_other_household_and_tv_cannot_export_member_reminder_history(app):
    own, h, _, _, uid, _ = saved(app)
    child, _, space = create_space(app)
    child.get(space['entry'])
    assert child.post('/api/login', json={'username': 'member1', 'password': 'second-home-password-one'}).status_code == 200
    ch = {'X-CSRF-Token': child.get('/api/me').json['csrf']}
    data, files = unpack(export(child, ch, True))
    assert data['personal']['taskReminders'] == {'states': [], 'operations': []}
    assert uid.encode() not in b''.join(files.values())
    tv = app.test_client(); pair = tv.post('/api/pair/start', json={}).json
    assert own.post('/api/pair/approve', json={'code': pair['code']}, headers=h).status_code == 200
    assert tv.post('/api/pair/poll', json={'secret': pair['secret']}).status_code == 200
    assert tv.get('/api/portability/summary').status_code == 403
    assert export(tv, h).status_code == 403
    assert own.post('/api/portability/export', json={'owner': 'member2'}, headers=h).status_code == 400


@pytest.mark.parametrize('phase', ['summary', 'zip'])
@pytest.mark.parametrize('change', ['revoke', 'replace_id'])
def test_final_fresh_identity_discards_snapshot_without_partial_output(app, monkeypatch, phase, change):
    own, h, _, _, _, _ = saved(app)
    calls = []
    before = reminder_rows(app)
    def changed():
        if calls:
            return
        calls.append(True)
        with closing(db(app)) as con, con:
            if change == 'revoke':
                con.execute("UPDATE member_sessions SET revoked_at=1 WHERE owner='member1'")
            else:
                # The credential, owner and auth_version still match. The exact
                # captured session ID must also survive the response boundary.
                con.execute("UPDATE member_sessions SET id=? WHERE owner='member1'", ('d'*32,))
    if phase == 'summary':
        real = portability.exported_places
        def project(*args, **kwargs):
            result = real(*args, **kwargs)
            changed()
            return result
        monkeypatch.setattr(portability, 'exported_places', project)
        response = own.get('/api/portability/summary')
    else:
        real = portability.ZipFile
        class Zip(real):
            def close(self):
                super().close()
                if self.mode == 'w': changed()
        monkeypatch.setattr(portability, 'ZipFile', Zip)
        response = export(own, h)
    assert calls == [True]
    assert response.status_code == 401 and response.mimetype == 'application/json'
    assert 'Content-Disposition' not in response.headers and 'personal' not in response.json
    assert reminder_rows(app) == before
    with closing(db(app)) as con:
        assert con.execute("SELECT count(*) FROM audit WHERE action='personal_data_export'").fetchone()[0] == 0
    assert portability.EXPORT_SLOT.acquire(blocking=False)
    portability.EXPORT_SLOT.release()
