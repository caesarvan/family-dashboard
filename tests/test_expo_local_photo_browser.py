"""Offline source-reuse boundaries and genuine file/SQLite evidence helpers.

These checks do not launch a browser or claim the three user flows passed.
"""
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import sqlite3
import subprocess
from pathlib import Path
import tempfile
from unittest.mock import patch

from PIL import Image
import pytest
from scripts import check_expo_local_photo_browser as wrapper
from browser_expo_local_photo_check import Run, make_picture


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
    def change(name, text='synthetic changed input\n'):
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git('add', '--', name); git('commit', '--quiet', '-m', 'Synthetic delta')
        return git('rev-parse', 'HEAD')
    return git, head, evidence, change


def test_cases_exact_and_repeated_selection_deduplicated():
    assert wrapper.selected_cases(None) == wrapper.CASES
    assert len(wrapper.CASES) == 3 and list(wrapper.CASE_SCREENSHOTS.values()) == [3, 3, 3]
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


def reviewed_change(repo):
    git, head, evidence, change = repo
    for name in sorted(wrapper.REVIEWED_BACKEND_PATHS):
        reviewed = change(name, 'reviewed backend ' + name + '\n')
    return reviewed


def test_exact_reviewed_backend_ancestor_and_blobs_accept(repo):
    git, head, evidence, change = repo
    reviewed = reviewed_change(repo)
    candidate = change(wrapper.HARNESS)
    with patch.object(wrapper, 'REVIEWED_BACKEND_HEAD', reviewed):
        assert set(wrapper.build_source_delta(git, candidate, evidence, head)) == wrapper.REVIEWED_BACKEND_PATHS | {wrapper.HARNESS}


def test_changed_reviewed_backend_blob_rejected(repo):
    git, head, evidence, change = repo
    reviewed = reviewed_change(repo)
    candidate = change('home_assistant.py', 'unreviewed change\n')
    with patch.object(wrapper, 'REVIEWED_BACKEND_HEAD', reviewed), pytest.raises(AssertionError, match='bytes changed'):
        wrapper.build_source_delta(git, candidate, evidence, head)


def test_copying_reviewed_bytes_without_reviewed_ancestor_rejected(repo):
    git, head, evidence, change = repo
    reviewed = reviewed_change(repo)
    git('checkout', '--quiet', '-b', 'synthetic-independent-copy', head)
    # Exact same blobs, but without the reviewed commit in history.
    git('checkout', reviewed, '--', *sorted(wrapper.REVIEWED_BACKEND_PATHS))
    git('commit', '--quiet', '-m', 'Independent copy')
    candidate = git('rev-parse', 'HEAD')
    with patch.object(wrapper, 'REVIEWED_BACKEND_HEAD', reviewed), pytest.raises(AssertionError, match='ancestor'):
        wrapper.build_source_delta(git, candidate, evidence, head)


@pytest.mark.parametrize('kind', ['JPEG', 'PNG', 'WEBP'])
def test_picture_is_real_decodable_file_with_hash_and_exclusive_destination(tmp_path, kind):
    path = tmp_path / ('synthetic.' + kind.lower())
    proof = make_picture(path, kind, '#437562'); original = path.read_bytes()
    assert proof['bytes'] == len(original) and proof['sha256'] == hashlib.sha256(original).hexdigest()
    with Image.open(path) as image:
        image.load(); assert image.format == kind and image.size == (96, 64)
    with pytest.raises(AssertionError): make_picture(path, kind, '#000000')
    assert path.read_bytes() == original


@pytest.mark.parametrize('invalid_cipher', [False, True])
def test_database_evidence_closes_actual_sqlite_on_pass_and_assertion(tmp_path, invalid_cipher):
    database = tmp_path / 'synthetic.sqlite3'
    with closing(sqlite3.connect(database)) as con:
        con.executescript('''CREATE TABLE media_items(id TEXT,owner TEXT,account_id TEXT,state TEXT,
            revision INTEGER,visibility TEXT,confirmed_at INTEGER,preview_cipher BLOB,metadata_cipher BLOB);
            CREATE TABLE media_imports(id TEXT,owner TEXT,state TEXT,revision INTEGER);
            CREATE TABLE audit(action TEXT); CREATE TABLE cloud_accounts(id TEXT);''')
        con.execute('INSERT INTO media_items VALUES(?,?,?,?,?,?,?,?,?)', ('original-id', 'member1', None,
            'staged', 1, 'private', None, b'' if invalid_cipher else b'encrypted-preview', b'encrypted-metadata'))
        con.execute('INSERT INTO media_imports VALUES(?,?,?,?)', ('original-import', 'member1', 'staging', 1))
        con.execute('INSERT INTO audit VALUES(?)', ('media_local_import_start',)); con.commit()
    run = Run.__new__(Run); run.database, run.folder = database, tmp_path
    connect, held = sqlite3.connect, []
    def actual_connection(*args, **kwargs):
        con = connect(*args, **kwargs); held.append(con); return con
    with patch.object(sqlite3, 'connect', actual_connection):
        if invalid_cipher:
            with pytest.raises(AssertionError): run.database_proof()
        else:
            proof = run.database_proof()
            assert proof['items'][0]['id'] == 'original-id' and proof['accounts'] == 0
            assert proof['audit'] == {'media_local_import_start': 1}
            assert 'preview_cipher' not in proof['items'][0]
    assert len(held) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'): held[0].execute('SELECT 1')
    database.unlink()  # Real Windows handle closure, no GC/sleep/retry.


def test_actual_fixture_initialization_and_thread_cleanup_without_browser(tmp_path):
    bundle = tmp_path / 'synthetic-unused-export'; bundle.mkdir()
    (bundle / 'index.html').write_text('<!doctype html><title>Not browser acceptance</title>')
    out = tmp_path / 'output'; out.mkdir()
    report = {'unexpectedProviderAttempts': []}
    with ExitStack() as lifecycle:
        folder = Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='lp-init-', dir=tmp_path)))
        run = Run(wrapper.ROOT, bundle, folder, report, out, lifecycle)
        assert run.database_proof()['items'] == [] and run.database_proof()['accounts'] == 0
        assert run.server is not None and run.thread.is_alive()
        assert len(report['fixtureHashes']) >= 14 and not report['unexpectedProviderAttempts']
    assert run.server is None and not run.thread.is_alive() and not folder.exists()
