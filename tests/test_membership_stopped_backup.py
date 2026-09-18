"""Synthetic native SQLite sidecars at the stopped backup/warm boundary."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from deploy import membership_release_data as data
from deploy import membership_release_controller as controller
from deploy import membership_migration as migration
from deploy.backup import backup_all
from test_membership_migration import historical, clone_databases


@pytest.fixture
def stopped(historical, tmp_path):
    root = tmp_path / 'data'
    clone_databases(historical['before'], root)
    paths = data.enumerate_databases(root)
    for name in paths:
        if name == 'platform.sqlite3':
            continue  # Real parent registry uses DELETE; household databases use WAL.
        with closing(sqlite3.connect(root / name)) as con:
            assert con.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    before = data.snapshot(root)
    receipt = backup_all(root)
    return root, before, root / 'backups' / receipt['manifest']


def leave_native_sidecars(path, *, write=False):
    # A real readonly SQLite connection can leave this same empty pair on Linux.
    # _exit also makes the artifact deterministic on Windows without unlinking it.
    code = '''
import os, sqlite3, sys
from pathlib import Path
path=Path(sys.argv[1])
con=sqlite3.connect(path.as_uri()+'?mode='+sys.argv[2], uri=True)
con.execute('SELECT count(*) FROM sqlite_master').fetchone()
if sys.argv[2]=='rw':
 con.execute("UPDATE users SET name='Synthetic concurrent writer' WHERE id='member1'")
 con.commit()
os._exit(0)
'''
    run = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code, str(path), 'rw' if write else 'ro'],
                         capture_output=True, timeout=15)
    assert run.returncode == 0 and run.stderr == b''
    assert Path(str(path) + '-wal').is_file() and Path(str(path) + '-shm').stat().st_size == 32768
    assert (Path(str(path) + '-wal').stat().st_size > 0) == write


def finish(stopped):
    return data.finish_stopped_backup(*stopped)


def test_native_empty_pairs_still_block_reader_then_finish_exact_group(stopped):
    root, before, manifest = stopped
    for relative in before['databases']:
        if relative != 'platform.sqlite3':
            leave_native_sidecars(root / relative)
    with pytest.raises(migration.MigrationCheckError, match='sqlite_sidecar_present'):
        data.snapshot(root)
    backup_hash = migration.file_digest(manifest)
    result = finish(stopped)
    assert result['verified'] and result['emptyWalPairsClosed'] == 2
    assert data.snapshot(root) == before
    assert migration.file_digest(manifest) == backup_hash
    assert data.validate_backup(root, before, manifest) == result['backup']
    assert not (root / data.ROOT_ATTEMPT).exists()


def test_clean_finished_backup_is_readonly_noop(stopped):
    root, before, _ = stopped
    # The local SQLite build may already close its empty readonly-backup pairs.
    first = finish(stopped)
    assert first['verified']
    again = finish(stopped)
    assert again['emptyWalPairsClosed'] == 0 and data.snapshot(root) == before


@pytest.mark.parametrize('kind', ['nonempty_wal', 'journal', 'orphan_shm', 'wrong_shm_size', 'source_drift', 'backup_drift'])
def test_group_preflight_rejects_before_any_cleanup(stopped, kind):
    root, before, manifest = stopped
    # A later bad household must reject before the first household is cleaned.
    first = root / 'household.sqlite3'
    target = next(root.glob('spaces/*/household.sqlite3'))
    leave_native_sidecars(first)
    leave_native_sidecars(target, write=kind == 'nonempty_wal')
    if kind == 'journal':
        Path(str(target) + '-journal').write_bytes(b'synthetic journal')
    elif kind == 'orphan_shm':
        Path(str(target) + '-wal').rename(Path(str(target) + '-saved-wal'))
    elif kind == 'wrong_shm_size':
        with Path(str(target) + '-shm').open('ab') as stream:
            stream.write(b'x')
    elif kind == 'source_drift':
        with target.open('ab') as stream:
            stream.write(b'synthetic drift')
    elif kind == 'backup_drift':
        entry = json.loads(manifest.read_text())['snapshots'][0]
        with (root / entry['path']).open('ab') as stream:
            stream.write(b'synthetic drift')
    hashes = {str(p): migration.file_digest(p) for p in root.rglob('*') if p.is_file()}
    with pytest.raises((data.ReleaseDataError, migration.MigrationCheckError)):
        finish(stopped)
    assert {str(p): migration.file_digest(p) for p in root.rglob('*') if p.is_file()} == hashes
    assert not (root / data.ROOT_ATTEMPT).exists()


def test_live_reader_prevents_finishing(stopped):
    root, _, _ = stopped
    target = root / 'household.sqlite3'
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('BEGIN')
        con.execute('SELECT count(*) FROM users').fetchone()
        with pytest.raises((data.ReleaseDataError, migration.MigrationCheckError)):
            finish(stopped)
    assert not (root / data.ROOT_ATTEMPT).exists()


def test_actual_backup_program_closes_native_pairs_and_retains_exact_group(stopped, tmp_path, capsys):
    root, before, _ = stopped
    finish(stopped)
    proof = tmp_path / 'proof'
    proof.mkdir()
    exec(controller.BACKUP_PROGRAM, {'data': data, 'root': root, 'proof': proof, 'json': json, 'shutil': shutil})
    result = json.loads(capsys.readouterr().out)
    assert result['verified'] and result['databases'] == 3
    assert json.loads((proof / 'before.json').read_text()) == before == data.snapshot(root)
    receipt = json.loads((proof / 'backup.json').read_text())
    retained = proof / 'backup-group/backups' / receipt['manifest']
    assert data.validate_backup(root, before, retained)['verified']
    assert json.loads((proof / 'backup-finish.json').read_text())['verified']
    assert not (proof / 'attempt').exists() and not (root / data.ROOT_ATTEMPT).exists()
