"""Offline caller checks only: no Docker, SSH, FFmpeg or product tests run here."""
import ast
from pathlib import Path
import subprocess
import sys

import pytest

from deploy import media_video_linux_probe as probe


@pytest.fixture
def output(tmp_path, monkeypatch):
    root = tmp_path/'dedicated'; root.mkdir()
    monkeypatch.setattr(probe, 'REMOTE_ROOT', root)
    proof = root/'run'/'proof'; proof.mkdir(parents=True)
    return proof


def test_only_exact_selected_core_nodes_match_real_source():
    tree = ast.parse((Path(__file__).parent/'test_media_videos.py').read_text(encoding='utf8'))
    actual = []
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith('test_'): continue
        parameters = []
        for decorator in function.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == 'parametrize':
                parameters = ast.literal_eval(decorator.args[1])
        actual.extend([function.name+'['+p+']' for p in parameters] if parameters else [function.name])
    assert tuple(actual) == probe.CORE_NAMES
    assert len(set(actual)) == 16


@pytest.mark.parametrize('profile', probe.PROFILES)
def test_run_is_single_immutable_candidate_no_network_credentials_or_production_mount(output, profile):
    image = 'sha256:'+'1'*64
    args = probe.run_args(image, output, 768, profile)
    assert args[0] == 'create' and args.count(image) == 1
    for flag in ['--network=none', '--read-only', '--user=10001:10001', '--cap-drop=ALL',
                 '--security-opt=no-new-privileges:true', '--cpus=1', '--memory=768m', '--memory-swap=768m', '--pids-limit=128']:
        assert flag in args
    assert [a for a in args if a.startswith('--mount=')] == ['--mount=type=bind,src='+str(output)+',dst=/proof']
    assert not any(a.startswith(('--env-file', '--privileged', '--volume', '--publish', '--name')) for a in args)
    assert '-i' in args and args[args.index('--profile')+1] == profile
    assert '/data' not in ' '.join(args) and 'SECRET_KEY' not in ' '.join(args)


@pytest.mark.parametrize('image,memory,profile', [(probe.PARENT,768,'core'),('family-dashboard:latest',768,'core'),
    ('sha256:'+'1'*64,2048,'resources'),('sha256:'+'1'*64,768,'everything')])
def test_run_rejects_parent_mutable_image_expansion_and_unreviewed_matrix(output, image, memory, profile):
    with pytest.raises(RuntimeError): probe.run_args(image, output, memory, profile)


def test_output_must_be_new_and_within_dedicated_root(output):
    with pytest.raises(RuntimeError): probe.safe_path(output)
    with pytest.raises(RuntimeError): probe.safe_path(output.parent.parent.parent, existing=True, remote=True)
    with pytest.raises(RuntimeError): probe.safe_path(str(output)+',dst=/data', remote=True)
    new = output.parent/'new-run'
    assert probe.safe_path(new, remote=True) == new


def test_dockerfile_has_fixed_parent_exact_package_and_no_live_app_start():
    content = (Path(__file__).parents[1]/'deploy/Dockerfile.media-video-probe').read_text()
    assert content.startswith('FROM '+probe.PARENT+'\n')
    assert '"ffmpeg=$FFMPEG_VERSION"' in content and 'pytest==9.0.2' in content
    assert 'toolchain.json' in content and 'USER 10001:10001' in content
    assert 'gunicorn' not in content and 'app:create_app' not in content and 'COPY . ' not in content
    assert 'COPY runtime ./runtime' in content and 'COPY fixtures ./fixtures' in content
    assert set(probe.SOURCE_FILES.values()) == {
        *('runtime/'+name for name in probe.RUNTIME_FILES),
        *('fixtures/'+Path(name).name for name in probe.FIXTURE_FILES),
        'tests/test_media_videos.py', 'probe.py', 'Dockerfile'}
    assert 'crypto64' not in probe.PROFILES


def test_cli_help_is_real_offline_and_exposes_separate_phases():
    result = subprocess.run([sys.executable, '-B', probe.__file__, '--help'], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0
    assert '{prepare,build,run,fingerprint,inside}' in result.stdout


def test_runtime_and_fixture_python_imports_are_closed_over_explicit_inputs():
    root = Path(__file__).parents[1]
    explicit = set(probe.RUNTIME_FILES)
    assert len(explicit) == len(probe.RUNTIME_FILES) == 56
    assert set(probe.FIXTURE_FILES) == {'tests/test_household_media.py',
        'tests/test_journey_documents.py', 'tests/test_google_photos_picker.py'}
    for name in [*(p for p in explicit if p.endswith('.py')), *probe.FIXTURE_FILES]:
        tree = ast.parse((root/name).read_text(encoding='utf8'))
        for node in ast.walk(tree):
            modules = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                       else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                top = module.split('.')[0]
                if (root/(top+'.py')).is_file():
                    assert top+'.py' in explicit, (name, module)
                if (root/'tests'/(top+'.py')).is_file():
                    assert 'tests/'+top+'.py' in probe.FIXTURE_FILES, (name, module)


def test_file_transport_reads_bounded_actual_bytes_and_closes(tmp_path):
    path = tmp_path/'synthetic.bin'; path.write_bytes(bytes(range(256))*513)
    response = probe.FileMediaResponse(path)
    with pytest.raises(RuntimeError): response.read1(65537)
    got = bytearray()
    while chunk := response.read1(65536): got.extend(chunk)
    response.close()
    assert bytes(got) == path.read_bytes() and response.bytes_read == path.stat().st_size
    assert response.closed and response.stream.closed
    assert response.headers['Content-Length'] == str(path.stat().st_size)


def test_padding_preserves_source_and_writes_one_exact_free_box(tmp_path):
    # Box construction only; this is deliberately not decoder/video proof.
    path = tmp_path/'box.bin'; original = b'synthetic-existing-boxes'; path.write_bytes(original)
    probe.padded_mp4(path, len(original)+1024)
    value = path.read_bytes()
    assert value[:len(original)] == original
    assert value[len(original):len(original)+8] == (1024).to_bytes(4,'big')+b'free'
    assert len(value) == len(original)+1024 and set(value[len(original)+8:]) == {0}
    with pytest.raises(RuntimeError): probe.padded_mp4(path, len(value)+7)
    assert probe.file_digest(path) == probe.digest(value)
