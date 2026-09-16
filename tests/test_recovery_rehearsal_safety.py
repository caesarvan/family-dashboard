"""Safety boundaries of the synthetic Docker rehearsal; never invoke Docker."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


SPEC = importlib.util.spec_from_file_location('synthetic_recovery', Path(__file__).parents[1] / 'deploy/rehearse_restore.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
IMAGE = 'sha256:' + 'a' * 64


@pytest.mark.parametrize('image', ['family-dashboard-app', 'latest', 'sha256:abc', 'a' * 64, IMAGE + '\n'])
def test_mutable_or_malformed_image_rejected(tmp_path, image):
    with pytest.raises(ValueError):
        module.Rehearsal(tmp_path, image, tmp_path / 'report')


@pytest.mark.parametrize('kind', ['volume', 'container'])
def test_ownership_requires_exact_name_label_and_run(kind):
    run = 'a' * 32
    name = 'fd-rehearsal-' + run + '-source-1'
    info = {'Name': name, 'Labels': {module.LABEL: run}, 'Config': {'Labels': {module.LABEL: run}}}
    assert module.owned_resource(info, kind, run, name)
    assert not module.owned_resource(info, kind, 'b' * 32, name)
    info['Name'] = 'family-dashboard_household-data'
    assert not module.owned_resource(info, kind, run, name)
    info['Name'] = name
    info['Labels'] = info['Config']['Labels'] = {module.LABEL: 'b' * 32}
    assert not module.owned_resource(info, kind, run, name)


def test_preexisting_volume_is_never_created_or_removed(tmp_path, monkeypatch):
    obj = module.Rehearsal(tmp_path, IMAGE, tmp_path / 'report')
    calls = []
    def fake(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '[]', '')
    monkeypatch.setattr(obj, 'docker', fake)
    with pytest.raises(RuntimeError, match='existing volume'):
        obj.volume('source')
    assert len(calls) == 1 and calls[0][:2] == ['volume', 'inspect']
    assert not obj.resources


@pytest.mark.parametrize('kind', ['volume', 'container'])
def test_cleanup_refuses_changed_ownership(tmp_path, monkeypatch, kind):
    obj = module.Rehearsal(tmp_path, IMAGE, tmp_path / 'report')
    name = obj.name('resource')
    obj.resources = [(kind, name)]
    monkeypatch.setattr(obj, 'inspect', lambda *_: {'Name': name, 'Labels': {}, 'Config': {'Labels': {}}})
    calls = []
    def fake(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, name, '')
    monkeypatch.setattr(obj, 'docker', fake)
    obj.cleanup()
    assert len(calls) == 1 and calls[0][:2] == [kind, 'ls']
    assert not obj.report['cleanup']['passed']
    assert obj.report['cleanup']['failures'][0]['name'] == name


def test_existing_evidence_directory_is_untouched(tmp_path, monkeypatch):
    # This helper tests existing-output protection under the required CLI mode.
    monkeypatch.setattr(module.sys, 'dont_write_bytecode', True)
    monkeypatch.setattr(module.sys, 'pycache_prefix', None)
    output = tmp_path / 'existing'
    output.mkdir()
    marker = output / 'marker'
    marker.write_text('preserve')
    def forbidden(*args, **kwargs):
        raise AssertionError('Docker must not run when output exists')
    monkeypatch.setattr(module.Rehearsal, 'docker', forbidden)
    assert module.main(['--image', IMAGE, '--output', str(output), '--source-root', str(tmp_path)]) == 1
    assert list(output.iterdir()) == [marker]
    assert marker.read_text() == 'preserve'


def test_ambiguous_documented_restore_program_fails_closed(tmp_path):
    docs = tmp_path / 'docs'
    docs.mkdir()
    body = "<<'PY'\nfrom contextlib import ExitStack\nroot = Path('/data').resolve(strict=True)\nPY\n"
    (docs / 'DEPLOYMENT.md').write_text(body + body)
    with pytest.raises(ValueError, match='one documented restore'):
        module.documented_programs(tmp_path)


def test_uncertain_volume_creation_is_tracked_and_cleaned(tmp_path, monkeypatch):
    obj = module.Rehearsal(tmp_path, IMAGE, tmp_path / 'report')
    state = {'name': None}
    mutations = []
    def fake(args, **kwargs):
        if args[:2] == ['volume', 'create']:
            state['name'] = args[-1]
            raise subprocess.TimeoutExpired('docker', 90)
        if args[:2] == ['volume', 'ls']:
            return subprocess.CompletedProcess(args, 0, state['name'] or '', '')
        if args[:2] == ['volume', 'rm']:
            mutations.append(args[-1]); state['name'] = None
            return subprocess.CompletedProcess(args, 0, '', '')
        return subprocess.CompletedProcess(args, 1, '', '')
    monkeypatch.setattr(obj, 'docker', fake)
    monkeypatch.setattr(obj, 'inspect', lambda *_: {'Name': state['name'], 'Labels': {module.LABEL: obj.run_id}})
    with pytest.raises(subprocess.TimeoutExpired):
        obj.volume('source')
    assert len(obj.resources) == 1
    obj.cleanup()
    assert mutations == [obj.resources[0][1]]
    assert obj.report['cleanup']['passed']
