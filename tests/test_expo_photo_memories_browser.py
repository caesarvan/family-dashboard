"""Offline harness boundaries with real Git and Flask/SQLite photo fixtures.

These checks do not launch Edge or prove the three browser flows passed.
"""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
from unittest.mock import patch

import pytest
from scripts import check_expo_photo_memories_browser as wrapper
from browser_expo_photo_memories_check import MemoryClock, Run, URL, revoke_member_sessions
from test_household_media import env, offline
import test_household_media as media_fixture
from test_journey_documents import login
import media_images


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Synthetic Harness Test',
            '-c', 'user.email=synthetic@example.invalid', *args], cwd=tmp_path).decode().strip()
    git('init', '--quiet')
    path = tmp_path / 'frontend' / 'app.tsx'; path.parent.mkdir(); path.write_text('synthetic input\n')
    git('add', '--', 'frontend/app.tsx'); git('commit', '--quiet', '-m', 'Synthetic source')
    head = git('rev-parse', 'HEAD')
    evidence = {'sourceHead': head, 'sourceTree': git('rev-parse', head + '^{tree}')}
    def change(name):
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('synthetic changed input\n')
        git('add', '--', name); git('commit', '--quiet', '-m', 'Synthetic delta')
        return git('rev-parse', 'HEAD')
    return git, head, evidence, change


def test_cases_exact_and_repeated_selection_deduplicated():
    assert wrapper.selected_cases(None) == wrapper.CASES
    assert len(wrapper.CASES) == 3 and sum(wrapper.CASE_SCREENSHOTS.values()) == 8
    assert wrapper.selected_cases([wrapper.CASES[2], wrapper.CASES[0], wrapper.CASES[2]]) == (wrapper.CASES[2], wrapper.CASES[0])
    for value in ([], ['unknown'], [wrapper.CASES[0], 'unknown']):
        with pytest.raises(ValueError): wrapper.selected_cases(value)


def test_output_keeps_original_failure(tmp_path):
    with patch.object(wrapper, 'datetime') as clock:
        clock.now.return_value = datetime(2027, 10, 13, tzinfo=timezone.utc)
        out = wrapper.exclusive_output(tmp_path)
        original = out / 'failure.txt'; original.write_text('original failure')
        with pytest.raises(FileExistsError): wrapper.exclusive_output(tmp_path)
        assert original.read_text() == 'original failure'


def test_build_reuse_accepts_only_exact_own_paths(repo):
    git, head, evidence, change = repo
    assert wrapper.build_source_delta(git, head, evidence, head) == []
    assert len(wrapper.BUILD_REUSE_PATHS) == 4
    for path in sorted(wrapper.BUILD_REUSE_PATHS):
        assert path in wrapper.build_source_delta(git, change(path), evidence, head)


@pytest.mark.parametrize('path', ['frontend/app.tsx', 'frontend/new.tsx', 'household_media.py', 'app.py', 'docs/OTHER.md'])
def test_build_reuse_rejects_unrelated_or_business_changes(repo, path):
    git, head, evidence, change = repo
    with pytest.raises(AssertionError): wrapper.build_source_delta(git, change(path), evidence, head)


def test_build_reuse_requires_original_head_tree_ancestry(repo):
    git, head, evidence, change = repo
    with pytest.raises(AssertionError): wrapper.build_source_delta(git, head, {**evidence, 'sourceTree': '0' * 40}, head)
    with pytest.raises(AssertionError): wrapper.build_source_delta(git, head, evidence, '0' * 40)
    later = change(wrapper.HARNESS)
    later_evidence = {'sourceHead': later, 'sourceTree': git('rev-parse', later + '^{tree}')}
    with pytest.raises(AssertionError, match='ancestor'): wrapper.build_source_delta(git, head, later_evidence, later)


def actual_fixture(env):
    app, engine, _, accounts = env
    client, headers = login(app)
    run = Run.__new__(Run)
    run.engine, run.media_fixture, run.images, run.synthetic_accounts = engine, media_fixture, media_images, accounts
    run.memory_clock = MemoryClock()
    def get(ctx, path, status=200):
        response = ctx.get(path); assert response.status_code == status, response.json
        return response.json
    def write(ctx, method, path, body, status=200):
        response = ctx.open(path, method=method, json=body, headers=headers)
        assert response.status_code == status, response.json
        return response.json
    run.get, run.write = get, write
    return run, client


def test_actual_batch_fixture_confirm_cleanup_unknown_and_original_ids(env):
    run, client = actual_fixture(env)
    saved = run.seed_photos(client, [('2025-09-19T16:00:00Z', f'Synthetic photo {n}') for n in range(25)] + [(None, 'Synthetic unknown')])
    assert len(saved) == 26 and len({row['id'] for row in saved}) == 26
    run.set_day()
    first = client.get(Run.path()).json; second = client.get(Run.path(24)).json
    assert first['total'] == 25 and first['unknownSourceTimeCount'] == 1
    assert len(first['items']) == 24 and len(second['items']) == 1
    assert {r['item']['id'] for r in first['items'] + second['items']} == {r['id'] for r in saved if r['sourceCreatedAt']}
    with run.engine.transaction() as con:
        imports = con.execute('SELECT state,cleanup_state FROM media_imports').fetchall()
        assert len(imports) == 2 and all(tuple(row) == ('confirmed', 'done') for row in imports)
        assert con.execute("SELECT COUNT(*) FROM media_items WHERE state='ready' AND confirmed_at IS NOT NULL").fetchone()[0] == 26


def test_real_server_clock_midnight_changes_selection_without_response_stubs(env):
    run, client = actual_fixture(env)
    photos = run.seed_photos(client, [('2025-09-19T00:00:00Z', 'Day19'), ('2025-09-20T00:00:00Z', 'Day20')])
    run.set_day('2026-09-19T15:59:59+00:00')
    first = client.get(URL).json
    run.set_day('2026-09-19T16:00:00+00:00')
    second = client.get(URL).json
    assert first['referenceDate'] == '2026-09-19' and second['referenceDate'] == '2026-09-20'
    assert first['items'][0]['item']['id'] == photos[0]['id'] and second['items'][0]['item']['id'] == photos[1]['id']
    with pytest.raises(AssertionError): run.memory_clock.set('2026-09-20T00:00:00')


def test_revocation_fixture_rejects_outside_root_and_real_session(env):
    run, client = actual_fixture(env)
    folder = Path(env[0].config['DATA_DIR']); database = folder / 'household.sqlite3'
    assert client.get(URL).status_code == 200
    with pytest.raises(AssertionError): revoke_member_sessions(database, folder / 'not-the-db-root')
    assert client.get(URL).status_code == 200
    assert revoke_member_sessions(database, folder) > 0
    assert client.get(URL).status_code == 401


@pytest.mark.parametrize('outcome', ['commit', 'assertion', 'sql-error'])
def test_revocation_connection_closed_without_gc_on_success_and_errors(tmp_path, outcome):
    database = tmp_path / 'household.sqlite3'
    connect = sqlite3.connect
    with closing(connect(database)) as con:
        if outcome != 'sql-error':
            con.execute('CREATE TABLE member_sessions(owner TEXT, revoked_at INTEGER)')
            con.execute('INSERT INTO member_sessions VALUES(?, NULL)', ('member1' if outcome == 'commit' else 'member2',))
            con.commit()
    held = []
    def actual_connection(*args, **kwargs):
        con = connect(*args, **kwargs); held.append(con)
        return con
    # Retain a strong reference so garbage collection cannot hide a missing
    # explicit close. SQL/transactions and connections are genuine SQLite.
    with patch.object(sqlite3, 'connect', actual_connection):
        if outcome == 'commit':
            assert revoke_member_sessions(database, tmp_path) == 1
        else:
            with pytest.raises(AssertionError if outcome == 'assertion' else sqlite3.OperationalError):
                revoke_member_sessions(database, tmp_path)
    assert len(held) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        held[0].execute('SELECT 1')
    with closing(connect(database)) as con:
        if outcome != 'sql-error':
            assert con.execute('SELECT revoked_at FROM member_sessions').fetchone()[0] == (1 if outcome == 'commit' else None)
    # Windows requires closed handles. No sleep, retry or forced GC is used.
    database.unlink()
    assert not database.exists()
