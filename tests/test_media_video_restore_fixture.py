"""Exercise real fixture backup staging; does not run Docker or SQLite restore."""
import ast
import hashlib
import json
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
