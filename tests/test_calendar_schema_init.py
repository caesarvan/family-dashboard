"""Concurrent schema initialization uses actual spawn processes and one old DB."""
from contextlib import closing
import json
import multiprocessing
import os
import sqlite3

import pytest

from calendar_publish import initialize_publications


LEGACY_SCHEMA = '''
CREATE TABLE users(id TEXT PRIMARY KEY);
CREATE TABLE settings(id TEXT PRIMARY KEY,data TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE calendar_publications(
  id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), journey_id TEXT NOT NULL,
  entity_id TEXT NOT NULL, source_id TEXT NOT NULL, account_id TEXT NOT NULL,
  provider TEXT NOT NULL, calendar_id TEXT NOT NULL,
  remote_id TEXT NOT NULL DEFAULT '', etag TEXT NOT NULL DEFAULT '',
  last_hash TEXT NOT NULL DEFAULT '', local_revision INTEGER NOT NULL DEFAULT 0,
  pending_data TEXT, pending_hash TEXT NOT NULL DEFAULT '', pending_revision INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX calendar_publications_due ON calendar_publications(status,next_attempt);
CREATE INDEX calendar_publications_owner ON calendar_publications(owner,journey_id);
CREATE INDEX calendar_publications_remote ON calendar_publications(source_id,remote_id);
'''


def legacy_database(path):
    with closing(sqlite3.connect(path)) as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript(LEGACY_SCHEMA)
        con.execute("INSERT INTO users VALUES('member1')")
        con.execute("INSERT INTO settings(id,data) VALUES('calendar_publication_namespace',?)", (json.dumps('existing-namespace'),))
        con.execute("INSERT INTO calendar_publications(id,owner,journey_id,entity_id,source_id,account_id,provider,calendar_id,remote_id,etag,last_hash,local_revision,pending_data,pending_hash,pending_revision,status,error,attempts,next_attempt,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ('publication-example', 'member1', 'journey-example', 'event-example', 'source-example', 'account-example', 'google',
                     'calendar-example', 'remote-example', 'etag-original', 'last-hash-original', 4,
                     json.dumps({'title': 'Synthetic pending write'}), 'pending-hash-original', 5,
                     'publishing', 'synthetic prior error', 3, 12345.0, 'created-original', 'updated-original'))
        con.commit()
    return snapshot(path)


def snapshot(path):
    with closing(sqlite3.connect(path)) as con:
        con.row_factory = sqlite3.Row
        return {'row': dict(con.execute('SELECT * FROM calendar_publications').fetchone()),
                'settings': [tuple(row) for row in con.execute('SELECT * FROM settings ORDER BY id')],
                'columns': [row[1] for row in con.execute('PRAGMA table_info(calendar_publications)')]}


def initialize_in_process(path, started, finished, output, paused=None, release=None):
    """Only the first process pauses immediately before its migration DDL.

    With the old implementation the second process adds the column during this
    pause, making the first ALTER fail. With a transaction the second initializer
    must wait and then see the existing column. No mocked SQLite result is used.
    """
    class PausingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if paused is not None and sql.startswith('ALTER TABLE calendar_publications ADD COLUMN review_required'):
                paused.set()
                if not release.wait(15):
                    raise RuntimeError('Synthetic migration gate timed out')
            return super().execute(sql, parameters)

    started.set()
    try:
        with closing(sqlite3.connect(path, timeout=10, factory=PausingConnection)) as con:
            con.execute('PRAGMA foreign_keys=ON')
            initialize_publications(con)
        output.put({'pid': os.getpid(), 'ok': True})
    except BaseException as error:
        output.put({'pid': os.getpid(), 'ok': False, 'error': type(error).__name__})
    finally:
        finished.set()


def stop_children(processes, release=None):
    if release is not None:
        release.set()
    for process in processes:
        process.join(12)
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_two_processes_migrate_old_table_once_and_preserve_pending_data(tmp_path):
    path = tmp_path / 'old-household.sqlite3'
    before = legacy_database(path)
    ctx = multiprocessing.get_context('spawn')
    output = ctx.Queue()
    paused, release = ctx.Event(), ctx.Event()
    started = [ctx.Event(), ctx.Event()]
    finished = [ctx.Event(), ctx.Event()]
    first = ctx.Process(target=initialize_in_process, args=(str(path), started[0], finished[0], output, paused, release))
    second = ctx.Process(target=initialize_in_process, args=(str(path), started[1], finished[1], output))
    processes = []
    try:
        first.start(); processes.append(first)
        assert paused.wait(10), 'First initializer never reached old-schema migration'
        second.start(); processes.append(second)
        assert started[1].wait(10)
        # The first migration has not committed. A competing initializer cannot
        # complete against this schema until the first writer releases its lock.
        assert not finished[1].wait(0.5)
        release.set()
        assert all(event.wait(12) for event in finished)
        results = [output.get(timeout=5), output.get(timeout=5)]
        assert all(result['ok'] for result in results), results
        assert len({result['pid'] for result in results}) == 2
        assert all(result['pid'] != os.getpid() for result in results)
    finally:
        stop_children(processes, release)
        output.close()
        output.join_thread()
    after = snapshot(path)
    assert after['columns'].count('review_required') == 1
    assert after['row'].pop('review_required') == 0
    assert after['row'] == before['row']
    assert after['settings'] == before['settings']


def test_existing_review_flag_and_namespace_survive_repeated_initialization(tmp_path):
    path = tmp_path / 'current-household.sqlite3'
    legacy_database(path)
    with closing(sqlite3.connect(path)) as con:
        con.execute('ALTER TABLE calendar_publications ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0')
        con.execute("UPDATE calendar_publications SET review_required=1,status='needs_review'")
        con.commit()
    before = snapshot(path)
    for _ in range(3):
        with closing(sqlite3.connect(path)) as con:
            initialize_publications(con)
    assert snapshot(path) == before


def test_failed_namespace_write_rolls_back_column_and_can_retry(tmp_path):
    path = tmp_path / 'failed-migration.sqlite3'
    before = legacy_database(path)
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TRIGGER reject_namespace BEFORE INSERT ON settings WHEN NEW.id='calendar_publication_namespace' BEGIN SELECT RAISE(ABORT,'synthetic namespace failure'); END")
        con.commit()
        with pytest.raises(sqlite3.IntegrityError):
            initialize_publications(con)
        assert not con.in_transaction
        assert 'review_required' not in [row[1] for row in con.execute('PRAGMA table_info(calendar_publications)')]
        con.execute('DROP TRIGGER reject_namespace')
        initialize_publications(con)
    after = snapshot(path)
    assert after['row'].pop('review_required') == 0
    assert after['row'] == before['row']
    assert after['settings'] == before['settings']


def test_two_processes_accept_already_migrated_schema_without_resetting_flag(tmp_path):
    path = tmp_path / 'already-migrated.sqlite3'
    legacy_database(path)
    with closing(sqlite3.connect(path)) as con:
        initialize_publications(con)
        con.execute("UPDATE calendar_publications SET review_required=1,status='paused'")
        con.commit()
    before = snapshot(path)
    ctx = multiprocessing.get_context('spawn')
    output = ctx.Queue()
    started, finished = [ctx.Event(), ctx.Event()], [ctx.Event(), ctx.Event()]
    processes = [ctx.Process(target=initialize_in_process, args=(str(path), started[i], finished[i], output)) for i in range(2)]
    try:
        for process in processes:
            process.start()
        assert all(event.wait(12) for event in finished)
        results = [output.get(timeout=5), output.get(timeout=5)]
        assert all(result['ok'] for result in results), results
        assert len({result['pid'] for result in results}) == 2
    finally:
        stop_children(processes)
        output.close()
        output.join_thread()
    assert snapshot(path) == before
