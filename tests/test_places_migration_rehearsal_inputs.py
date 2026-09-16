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


def test_map_static_additions_are_accepted_with_the_one_new_python_module():
    base = {'app.py':'a'*64, 'requirements.txt':'b'*64, 'static/app.js':'c'*64}
    candidate = {**base, 'app.py':'d'*64, 'journey_places.py':'e'*64,
                 'static/journey-map.js':'f'*64, 'static/journey-map.css':'1'*64,
                 'static/journey-map-land.geojson':'2'*64}
    M.validate_runtime_delta(base,candidate)


@pytest.mark.parametrize('change,label', [
    ('remove_static','runtime_removal'), ('remove_python','runtime_removal'),
    ('extra_python','runtime_delta'), ('missing_places','runtime_delta'),
    ('changed_requirements','runtime_dependencies'),
])
def test_static_additions_do_not_relax_other_runtime_boundaries(change,label):
    base = {'app.py':'a'*64, 'requirements.txt':'b'*64, 'static/app.js':'c'*64}
    candidate = {**base,'journey_places.py':'d'*64,'static/journey-map.js':'e'*64}
    if change=='remove_static': del candidate['static/app.js']
    elif change=='remove_python': del candidate['app.py']
    elif change=='extra_python': candidate['other.py']='f'*64
    elif change=='missing_places': del candidate['journey_places.py']
    else: candidate['requirements.txt']='0'*64
    with pytest.raises(RuntimeError,match=label): M.validate_runtime_delta(base,candidate)


def test_unlisted_cache_directory_symlink_is_rejected_without_following(tmp_path):
    root=tmp_path/'source';root.mkdir()
    outside=tmp_path/'external-cache';outside.mkdir()
    (root/'deploy').mkdir();(root/'app.py').write_bytes(b'original')
    digest=manifest(root,{'app.py':M.sha(b'original')})
    (root/'deploy'/'__pycache__').symlink_to(outside,target_is_directory=True)
    with pytest.raises(RuntimeError,match='source_link'):M.frozen(root,digest)
