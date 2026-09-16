"""Input and executable-probe checks; these never claim a Docker rehearsal."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('migration_rehearsal', Path(__file__).with_name('rehearse_journey_places_migration.py'))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)


def manifest(root, files):
    raw = json.dumps({'files':files}).encode()
    (root/'RELEASE-MANIFEST.json').write_bytes(raw)
    return M.sha(raw)


def test_frozen_manifest_detects_late_source_and_manifest_changes(tmp_path):
    (tmp_path/'app.py').write_bytes(b'original')
    files = {'app.py':M.sha(b'original')}; digest = manifest(tmp_path, files)
    assert M.frozen(tmp_path,digest)==files
    (tmp_path/'app.py').write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='source_changed'):M.frozen(tmp_path,digest)
    (tmp_path/'app.py').write_bytes(b'original')
    (tmp_path/'RELEASE-MANIFEST.json').write_bytes(b'{}')
    with pytest.raises(RuntimeError,match='manifest_changed'):M.frozen(tmp_path,digest)


@pytest.mark.parametrize('name',['../outside.py','/app.py','x//app.py','x/./app.py','C:/app.py','x\\app.py'])
def test_manifest_cannot_resolve_unsafe_names(tmp_path,name):
    digest=manifest(tmp_path,{name:'0'*64})
    with pytest.raises(RuntimeError,match='source_name'):M.frozen(tmp_path,digest)


def test_host_selectors_fail_before_source_read_or_docker(monkeypatch):
    monkeypatch.setattr(M.os,'name','posix')
    monkeypatch.setenv('DOCKER_HOST','tcp://unexpected.invalid')
    with pytest.raises(RuntimeError,match='host_selector'):M.run(SimpleNamespace())


@pytest.mark.parametrize('name',['deploy/__pycache__/rehearse_restore.cpython-314.pyc','tests/unchecked.pyo'])
def test_unlisted_import_cache_is_rejected_even_with_valid_source_manifest(tmp_path,name):
    (tmp_path/'app.py').write_bytes(b'original')
    digest=manifest(tmp_path,{'app.py':M.sha(b'original')})
    cache=tmp_path/name;cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(b'cached-code')
    with pytest.raises(RuntimeError,match='source_bytecode'):M.frozen(tmp_path,digest)


def test_embedded_programs_are_valid_python():
    for name in ('PROBE','CHECK','WRITE','READBACK'):
        compile(getattr(M,name),name,'exec')
    # The actual runtime test performs network isolation and source validation;
    # this check only catches embedded-program syntax before a Docker invocation.
