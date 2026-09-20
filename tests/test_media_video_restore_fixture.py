"""Exercise real fixture backup staging; does not run Docker or SQLite restore."""
import ast
from contextlib import closing
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path

import pytest

from deploy import media_video_controller_rehearsal as rehearsal


def staging_code():
    module = ast.parse(Path(rehearsal.__file__).read_text(encoding='utf-8'))
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'restore_fixture')
    assignment = next(node for node in function.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'code' for target in node.targets))
    return ast.literal_eval(assignment.value)


def prepare(tmp_path):
    proof = tmp_path/'proof'; root = tmp_path/'data'; group = proof/'backup-group'
    root.mkdir(); (group/'backups').mkdir(parents=True)
    names = ['backups/group.json', 'backups/platform.sqlite3', 'backups/default.sqlite3', 'backups/second.sqlite3']
    (proof/'backup.json').write_text(json.dumps({'manifest': 'group.json'}))
    (group/names[0]).write_text(json.dumps({'snapshots': [{'path': name} for name in names[1:]]}))
    for name in names[1:]: (group/name).write_bytes(('synthetic backup '+name).encode())
    restore = tmp_path/'restore.py'
    restore.write_text('from pathlib import Path\nPath('+repr(str(tmp_path/'called'))+').write_text("called")\n')
    code = staging_code().replace("Path('/proof')", 'Path('+repr(str(proof))+')')
    code = code.replace("Path('/data')", 'Path('+repr(str(root))+')')
    code = code.replace("Path('/restore.py')", 'Path('+repr(str(restore))+')')
    return group, root, names, code


@pytest.mark.parametrize('existing', [0, 2, 4])
def test_restore_staging_accepts_identical_existing_backups_without_rewriting(tmp_path, monkeypatch, existing):
    group, root, names, code = prepare(tmp_path); fingerprints = {}
    for name in names[:existing]:
        path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes((group/name).read_bytes())
        fingerprints[name] = (path.stat().st_ino, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr('sys.argv', ['test'])
    exec(compile(code, '<actual-fixture-restore-wrapper>', 'exec'), {})
    assert (tmp_path/'called').read_text() == 'called'
    for name in names: assert (root/name).read_bytes() == (group/name).read_bytes()
    for name, expected in fingerprints.items():
        path = root/name
        assert (path.stat().st_ino, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) == expected


@pytest.mark.parametrize('fault', ['different_bytes', 'directory'])
def test_restore_staging_rejects_conflict_before_copying_or_running_restore(tmp_path, fault):
    group, root, names, code = prepare(tmp_path)
    target = root/names[-1]; target.parent.mkdir(parents=True)
    if fault == 'different_bytes': target.write_bytes(b'preserve this conflict')
    else: target.mkdir()
    with pytest.raises(AssertionError): exec(compile(code, '<actual-fixture-restore-wrapper>', 'exec'), {})
    assert not (tmp_path/'called').exists()
    assert all(not (root/name).exists() for name in names[:-1])
    assert target.read_bytes() == b'preserve this conflict' if fault == 'different_bytes' else target.is_dir()


def partial_group(tmp_path):
    root = tmp_path/'data'; root.mkdir()
    child = root/'spaces'/'synthetic'/'household.sqlite3'; child.parent.mkdir(parents=True)
    # Generate the SHM with SQLite, then preserve its bytes after closing the
    # fixture connection. No live SQLite connection remains during observation.
    shm = None
    for path, count in ((root/'household.sqlite3',73),(root/'platform.sqlite3',9),(child,71)):
        with closing(sqlite3.connect(path)) as con:
            assert con.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
            for index in range(count): con.execute('CREATE TABLE t%d(value)' % index)
            con.execute("INSERT INTO t0 VALUES('preserved fixture row')");con.commit()
            con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if path==child:
                assert Path(str(path)+'-wal').stat().st_size==0
                shm = Path(str(path)+'-shm').read_bytes()
    assert len(shm)==32768
    Path(str(child)+'-wal').write_bytes(b'')
    Path(str(child)+'-shm').write_bytes(shm)
    for path in (child,Path(str(child)+'-wal'),Path(str(child)+'-shm')): path.chmod(0o400)
    return root, child


def allow_fixture_cleanup(root):
    # Restore test-owned readonly attributes so Windows pytest temp cleanup can
    # complete. This helper is not used by the production/rehearsal algorithm.
    for path in root.rglob('*'):
        if path.is_file(): path.chmod(0o600)


def test_partial_empty_wal_observation_is_real_immutable_sqlite_and_byte_preserving(tmp_path):
    root, child = partial_group(tmp_path)
    try:
        before = rehearsal.partial_files(root,child)[1]
        evidence = tmp_path/'partial.json'
        counts = rehearsal.partial_schema(root,injected=child,evidence=evidence)
        assert sorted(counts.values())==[9,71,73]
        proof = json.loads(evidence.read_bytes())
        assert proof['before']==proof['after']==before==rehearsal.partial_files(root,child)[1]
        assert proof['injected']=='spaces/synthetic/household.sqlite3'
        with closing(sqlite3.connect(child.as_uri()+'?mode=ro&immutable=1',uri=True)) as con:
            assert con.execute('SELECT * FROM t0').fetchall()==[('preserved fixture row',)]
        assert Path(str(child)+'-wal').exists() and Path(str(child)+'-shm').exists()
    finally: allow_fixture_cleanup(root)


@pytest.mark.parametrize('fault',['wal_data','rollback_journal','orphan_shm','other_database','shm_size','directory'])
def test_partial_observation_rejects_unproven_sidecars_without_deleting(tmp_path,fault):
    root, child = partial_group(tmp_path)
    wal,shm=Path(str(child)+'-wal'),Path(str(child)+'-shm')
    allow_fixture_cleanup(root)
    if fault=='wal_data':wal.write_bytes(b'committed frames must not be ignored')
    elif fault=='rollback_journal':Path(str(child)+'-journal').write_bytes(b'')
    elif fault=='orphan_shm':wal.unlink()
    elif fault=='other_database':Path(str(root/'household.sqlite3')+'-wal').write_bytes(b'')
    elif fault=='shm_size':shm.write_bytes(b'short')
    else:shm.unlink();shm.mkdir()
    before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(rehearsal.controller.ReleaseError,match='partial_group_not_stopped|partial_file_not_regular'):
        rehearsal.partial_schema(root,injected=child,evidence=tmp_path/'partial.json')
    assert not (tmp_path/'partial.json').exists()
    assert before=={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_partial_observation_rejects_source_change_during_read(tmp_path,monkeypatch):
    root,child=partial_group(tmp_path);allow_fixture_cleanup(root)
    original=sqlite3.connect
    class Reader:
        def __init__(self,con):self.con=con
        def close(self):self.con.close()
        def execute(self,*args):
            result=self.con.execute(*args)
            Path(str(child)+'-shm').write_bytes(b'z'*32768)
            return result
    monkeypatch.setattr(rehearsal.sqlite3,'connect',lambda *a,**k:Reader(original(*a,**k)))
    with pytest.raises(rehearsal.controller.ReleaseError,match='partial_read_changed_files'):
        rehearsal.partial_schema(root,injected=child,evidence=tmp_path/'partial.json')
    assert not (tmp_path/'partial.json').exists()


def permission_fixture(tmp_path):
    root,child=partial_group(tmp_path)
    evidence=tmp_path/'partial-sidecars.json'
    rehearsal.partial_schema(root,injected=child,evidence=evidence)
    transport=SimpleNamespace(root=tmp_path,data_path=root,injected=child,timer=False,
        partial_snapshot_sha=rehearsal.sha(evidence.read_bytes()))
    return root,child,transport


def test_restore_repairs_only_verified_injected_file_modes_then_real_sqlite_can_write(tmp_path):
    root,child,transport=permission_fixture(tmp_path);calls=[]
    try:
        before=rehearsal.partial_files(root,child)[1]
        rehearsal.restore_injected_permissions(SimpleNamespace(stopped=lambda:calls.append('stopped')),transport)
        receipt=json.loads((tmp_path/'restore-permissions.json').read_bytes())
        assert calls==['stopped','stopped'] and receipt['contentUnchanged'] and receipt['deletedFiles']==[]
        assert receipt['allowed']==['spaces/synthetic/household.sqlite3'+suffix for suffix in ('','-wal','-shm')]
        assert receipt['before']==before
        for name,info in before.items():
            after=receipt['after'][name]
            if info is not None and name in receipt['allowed']:
                assert {k:v for k,v in info.items() if k!='mode'}=={k:v for k,v in after.items() if k!='mode'}
            else:assert info==after
        with closing(sqlite3.connect(child)) as con:
            con.execute("INSERT INTO t0 VALUES('after permission repair')");con.commit()
            assert con.execute('SELECT count(*) FROM t0').fetchone()[0]==2
    finally:allow_fixture_cleanup(root)


@pytest.mark.parametrize('fault',['changed_bytes','wrong_injected'])
def test_restore_mode_repair_rejects_changed_proof_or_target_before_chmod(tmp_path,fault):
    root,child,transport=permission_fixture(tmp_path)
    try:
        if fault=='changed_bytes':
            shm=Path(str(child)+'-shm');shm.chmod(0o600);shm.write_bytes(b'x'*32768);shm.chmod(0o400)
        else:transport.injected=root/'household.sqlite3'
        before={p:p.stat().st_mode for p in root.rglob('*') if p.is_file()}
        with pytest.raises(rehearsal.controller.ReleaseError,match='partial_files_changed_before_restore|unexpected_partial_injection'):
            rehearsal.restore_injected_permissions(SimpleNamespace(stopped=lambda:None),transport)
        assert before=={p:p.stat().st_mode for p in before}
        assert not (tmp_path/'restore-permissions.started.json').exists()
    finally:allow_fixture_cleanup(root)


@pytest.mark.parametrize('fail_at',[1,2])
def test_restore_mode_repair_never_changes_permissions_with_active_writer(tmp_path,fail_at):
    root,child,transport=permission_fixture(tmp_path);calls=[]
    try:
        before={p:p.stat().st_mode for p in root.rglob('*') if p.is_file()}
        def stopped():
            calls.append(True)
            if len(calls)==fail_at:raise rehearsal.controller.ReleaseError('volume_still_running')
        with pytest.raises(rehearsal.controller.ReleaseError,match='volume_still_running'):
            rehearsal.restore_injected_permissions(SimpleNamespace(stopped=stopped),transport)
        assert before=={p:p.stat().st_mode for p in before}
        assert not (tmp_path/'restore-permissions.json').exists()
    finally:allow_fixture_cleanup(root)
