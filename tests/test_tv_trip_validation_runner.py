"""Recording Docker boundary tests only; these do not prove Linux capacity."""
import copy
import json
import subprocess

import pytest

from deploy import tv_trip_validation_runner as tool

IMAGE = 'sha256:' + 'a' * 64
CONTAINER = 'b' * 64


def arguments():
    return ['create', '--network', 'none', '--read-only', '--user', '10001:10001',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--memory', '1024m', '--pids-limit', '256', '--workdir', '/app',
            '--entrypoint', 'python', '--tmpfs', '/tmp:rw,size=805306368,mode=1777',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', IMAGE, '-B', '-c', tool.PROGRAM]


@pytest.fixture
def recording(monkeypatch):
    calls = []
    inspection = {'Id': CONTAINER, 'Image': IMAGE, 'Config': {'User': '10001:10001'},
                  'State': {'Running': False}, 'HostConfig': {
                      'Memory': tool.LIMIT, 'MemorySwap': tool.LIMIT, 'NetworkMode': 'none',
                      'ReadonlyRootfs': True, 'PidsLimit': 256, 'CapDrop': ['ALL'],
                      'SecurityOpt': ['no-new-privileges:true']}}
    def execute(self, args, **kwargs):
        calls.append(list(args))
        raw = (CONTAINER.encode() if args[0] == 'create' else
               json.dumps([inspection]).encode() if args[0] == 'inspect' else b'')
        return subprocess.CompletedProcess(args, 0, raw, b'')
    monkeypatch.setattr(tool.builder.Executor, '__call__', execute)
    return calls, inspection


def test_exact_validation_memory_transform_retains_original_and_inspects_before_start(tmp_path, recording):
    calls, _ = recording
    runner = tool.BoundedValidationExecutor(tmp_path, IMAGE)
    original = arguments()
    retained = original.copy()
    result = runner(original)
    assert result.returncode == 0 and original == retained
    expected = retained.copy()
    i = expected.index('--memory')
    expected[i:i+2] = ['--memory', '384m', '--memory-swap', '384m']
    assert calls == [expected, ['inspect', CONTAINER]]
    assert runner.transforms[0]['originalArguments'] == retained
    assert runner.transforms[0]['executedArguments'] == expected
    assert runner.transforms[0]['verifiedBeforeStart'] is True
    runner(['start', '--attach', CONTAINER])
    assert calls[-1] == ['start', '--attach', CONTAINER]


@pytest.mark.parametrize('change', ['program', 'image', 'network', 'memory', 'swap', 'second'])
def test_unexpected_create_rejected_without_new_container(tmp_path, recording, change):
    calls, _ = recording
    runner = tool.BoundedValidationExecutor(tmp_path, IMAGE)
    args = arguments()
    if change == 'program': args[-1] = 'print(1)'
    if change == 'image': args[-4] = 'sha256:'+'c'*64
    if change == 'network': args[2] = 'host'
    if change == 'memory': args[args.index('--memory')+1] = '2048m'
    if change == 'swap': args[3:3] = ['--memory-swap', '2048m']
    if change == 'second': runner(args)
    before = copy.deepcopy(calls)
    with pytest.raises(ValueError): runner(args)
    assert calls == before


@pytest.mark.parametrize('field,value', [('Memory', 1024**3), ('MemorySwap', -1),
                                      ('NetworkMode', 'host'), ('ReadonlyRootfs', False)])
def test_actual_limit_mismatch_cleans_only_just_created_container(tmp_path, recording, field, value):
    calls, inspection = recording
    inspection['HostConfig'][field] = value
    runner = tool.BoundedValidationExecutor(tmp_path, IMAGE)
    with pytest.raises(ValueError): runner(arguments())
    assert [args[0] for args in calls] == ['create', 'inspect', 'rm']
    assert calls[-1] == ['rm', '--force', CONTAINER]
    assert runner.transforms[0]['verifiedBeforeStart'] is False


def test_missing_create_cannot_leave_a_successful_memory_receipt(tmp_path, monkeypatch):
    output = tmp_path / 'validation'
    monkeypatch.setattr(tool.profile, 'verify_package', lambda *args: {
        'blobs': {tool.SELF: tool.profile.package.plain(tool.Path(tool.__file__))}})
    def incomplete(**kwargs):
        output.mkdir()
        return {'allPassed': True}
    monkeypatch.setattr(tool.profile, 'validate', incomplete)
    with pytest.raises(ValueError):
        tool.validate(package_dir=tmp_path/'package', package_sha256='c'*64,
                      image_id=IMAGE, selection=tmp_path/'selection.json',
                      selection_sha256='d'*64, output_dir=output)
    proof = json.loads((output/'memory-contract.json').read_bytes())
    assert proof['allPassed'] is False and proof['validationCompleted'] is True
    assert proof['transforms'] == []
    assert json.loads((output/'commands.json').read_bytes()) == {'commands': []}


def test_interrupted_inspect_cleans_owned_container_before_propagating(tmp_path, recording, monkeypatch):
    calls, _ = recording
    original = tool.builder.Executor.__call__
    def interrupted(self, args, **kwargs):
        result = original(self, args, **kwargs)
        if args[0] == 'inspect':
            raise KeyboardInterrupt()
        return result
    monkeypatch.setattr(tool.builder.Executor, '__call__', interrupted)
    runner = tool.BoundedValidationExecutor(tmp_path, IMAGE)
    with pytest.raises(KeyboardInterrupt): runner(arguments())
    assert [args[0] for args in calls] == ['create', 'inspect', 'rm']
    assert calls[-1] == ['rm', '--force', CONTAINER]
    assert runner.transforms[0]['verifiedBeforeStart'] is False
