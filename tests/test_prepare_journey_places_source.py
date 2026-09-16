"""Archive roundtrip with synthetic source only; missing fixed inputs fail shut."""
import hashlib
import json
from pathlib import Path
import tarfile

import pytest

from deploy import prepare_release as P


EXTRA={'journey_places.py','DESIGN.md',*[f'tools/inference_orchestrator/{name}.py' for name in ('__init__','__main__','client','runner')]}


@pytest.fixture
def source(tmp_path):
    root=tmp_path/'source';root.mkdir()
    for name in P.FILES:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# synthetic '+name+'\n',encoding='utf-8')
    for name in P.FOLDERS:
        path=root/name;path.mkdir();(path/'sample.txt').write_text('synthetic source')
    return root,tmp_path/'access'


def test_archive_contains_only_fixed_development_package_and_design(source):
    root,access=source
    extras=['tools/unrelated.py','tools/inference_orchestrator/plan.json','tools/inference_orchestrator/jobs.sqlite3',
            'tools/inference_orchestrator/.env','test-results/private.txt']
    for name in extras:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('excluded synthetic data')
    result=P.prepare(root,access)
    with tarfile.open(result['archive']) as archive:
        names=set(archive.getnames());manifest=json.load(archive.extractfile('RELEASE-MANIFEST.json'))
        assert EXTRA <= names and not set(extras)&names
        assert {n for n in names if n.startswith('tools/')} == EXTRA-{'journey_places.py','DESIGN.md'}
        assert set(manifest['files']) == names-{'RELEASE-MANIFEST.json'}
        assert all(hashlib.sha256(archive.extractfile(n).read()).hexdigest()==h for n,h in manifest['files'].items())
    assert 'tools' not in P.FOLDERS and result['credentialsTouched'] is False


@pytest.mark.parametrize('missing',sorted(EXTRA))
def test_missing_new_required_source_keeps_previous_archive(source,missing):
    root,access=source;access.mkdir();(access/'release.tar.gz').write_bytes(b'previous known archive')
    (root/missing).unlink()
    with pytest.raises(FileNotFoundError):P.prepare(root,access)
    assert (access/'release.tar.gz').read_bytes()==b'previous known archive'


def test_runtime_database_under_recursive_source_folder_fails_shut(source):
    root,access=source;(root/'docs/private.sqlite3').write_bytes(b'synthetic')
    with pytest.raises(RuntimeError,match='Private runtime file'):P.prepare(root,access)
    assert not (access/'release.tar.gz').exists()
