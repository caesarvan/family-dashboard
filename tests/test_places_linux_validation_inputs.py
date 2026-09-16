"""Synthetic inputs and Docker command/state doubles only; never Docker or SSH."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location('places_linux_runner', Path(__file__).with_name('run_places_linux_validation.py'))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
IMAGE = 'sha256:'+'b'*64
FILES = {'tests/test_alpha.py':'a'*64, 'tests/test_beta.py':'b'*64}


@pytest.fixture(autouse=True)
def no_commands(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError('No real subprocess/Docker in input tests')
    monkeypatch.setattr(M.subprocess, 'run', blocked)


def config(**changes):
    group = dict(name='backend', scripts=['tests/test_alpha.py'], expectedCount=3)
    group.update(changes)
    return {'groups':[group]}


def test_groups_only_reviewed_scripts_and_bounded_counts():
    assert M.groups(config(), FILES) == [dict(name='backend',scripts=['tests/test_alpha.py'],expectedCount=3,timeoutSeconds=600)]
    value = config(); value['groups'].append(dict(name='tools',scripts=['tests/test_beta.py'],expectedCount=4,timeoutSeconds=1800))
    assert len(M.groups(value, FILES)) == 2


@pytest.mark.parametrize('value', [
    config(scripts=['tests/test_alpha.py; touch /data/x']), config(scripts=['../test_alpha.py']),
    config(scripts=['/tests/test_alpha.py']), config(scripts=['tests/test_missing.py']),
    config(scripts=['tests/test_alpha.py','tests/test_alpha.py']), config(scripts=[]),
    config(scripts=['tests/browser_check.py']), config(expectedCount=True), config(expectedCount=0),
    config(timeoutSeconds=1801), config(timeoutSeconds=0), config(name='../escape'),
    {'groups':[config()['groups'][0]]*3}, {'groups':[], 'command':'anything'},
    {'groups':[dict(**config()['groups'][0], command=['sh','-c','anything'])]},
    {'groups':[config()['groups'][0],dict(name='second',scripts=['tests/test_alpha.py'],expectedCount=3)]},
])
def test_untrusted_group_shapes_cannot_form_commands(value):
    with pytest.raises(RuntimeError): M.groups(value, FILES)


def test_checked_json_hash_and_duplicate_keys(tmp_path):
    path = tmp_path/'groups.json'; raw = b'{"groups":[],"groups":[]}'
    path.write_bytes(raw)
    with pytest.raises(RuntimeError, match='json_identity'): M.checked_json(path,'0'*64)
    with pytest.raises(RuntimeError, match='duplicate_json_key'): M.checked_json(path,hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize('name', ['../x','/x','x//y','x/./y','C:/x','x\\y'])
def test_manifest_names_cannot_escape(name):
    with pytest.raises(RuntimeError, match='file_entry'): M.names({name:'a'*64})


def test_fixture_copy_excludes_all_image_runtime(tmp_path):
    source, fixture = tmp_path/'candidate', tmp_path/'fixtures'; source.mkdir()
    payloads = {'app.py':b'runtime', 'requirements.txt':b'runtime', 'static/app.js':b'runtime',
                'tests/test_alpha.py':b'test', 'deploy/check.py':b'helper','docs/README.md':b'doc',
                'DESIGN.md':b'design', 'tools/inference_orchestrator/client.py':b'tool',
                'tools/unreviewed.py':b'outside allowlist'}
    for name, raw in payloads.items():
        p = source/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
    hashes = {n:M.sha(source/n) for n in payloads}
    M.copy_support(source,fixture,M.support(hashes))
    assert set(M.tree(fixture)) == {'tests/test_alpha.py','deploy/check.py','docs/README.md','DESIGN.md','tools/inference_orchestrator/client.py'}
    assert set(M.runtime(hashes)) == {'app.py','requirements.txt','static/app.js'}
    assert not (fixture/'app.py').exists() and not (fixture/'static').exists()


@pytest.mark.parametrize('name', ['deploy/__pycache__/helper.cpython-312.pyc', 'tests/old.pyo'])
def test_unlisted_source_cache_rejected_but_exact_dependency_cache_can_be_hashed(tmp_path,name):
    path = tmp_path/name; path.parent.mkdir(parents=True);path.write_bytes(b'synthetic cache')
    with pytest.raises(RuntimeError, match='tree_bytecode'): M.tree(tmp_path)
    assert M.tree(tmp_path,bytecode=True) == {name:M.sha(path)}


def test_unlisted_cache_directory_link_rejected_without_traversal(tmp_path):
    root, outside = tmp_path/'source',tmp_path/'outside';root.mkdir();outside.mkdir()
    (root/'__pycache__').symlink_to(outside,target_is_directory=True)
    with pytest.raises(RuntimeError,match='tree_link'):M.tree(root)
    with pytest.raises(RuntimeError,match='tree_link'):M.tree(root,bytecode=True)


def test_junit_reports_observed_failures_and_checks_script_coverage(tmp_path):
    path = tmp_path/'targeted.xml'
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_alpha" name="a"/>'
                    '<testcase classname="tests.test_alpha" name="b"><failure/></testcase>'
                    '<testcase classname="tests.test_other" name="c"><skipped/></testcase></testsuite></testsuites>')
    value = M.junit(path,config()['groups'][0])
    assert value == dict(tests=3,passed=1,failures=1,errors=0,skipped=1,scriptsMatched=False)
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_alpha" name="a"/></testsuite></testsuites>')
    assert M.junit(path,config()['groups'][0])['scriptsMatched'] is True


class FakeDocker(M.Docker):
    def __init__(self):
        super().__init__('a'*32);self.commands=[];self.info={};self.bad_identity=False;self.bad_mount=False
    def call(self,args,**_kwargs):
        self.commands.append(list(args))
        if args[:2] == ['container','ls']:
            name = args[-1].removeprefix('name=^/').removesuffix('$')
            return SimpleNamespace(stdout=name if name in self.info else '')
        if args[:2] == ['container','create']:
            name = args[args.index('--name')+1]; mounts=[]
            for index,value in enumerate(args):
                if value == '--mount':
                    fields=args[index+1].split(','); values=dict(x.split('=',1) for x in fields if '=' in x)
                    mounts.append(dict(Type='bind',Source=values['src'],Destination=values['dst'],RW='readonly' not in fields))
            if self.bad_mount:mounts.append(dict(Type='volume',Name='forbidden-production',Destination='/data',RW=True))
            self.info[name]={'Name':'/'+name,'Image':IMAGE,'Config':{'User':'10001:10001','Labels':{M.LABEL:'foreign' if self.bad_identity else self.run_id}},
                'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'Privileged':False,'PortBindings':None},
                'Mounts':mounts,'State':{'Running':False,'OOMKilled':False,'ExitCode':0}}
            return SimpleNamespace(stdout=name)
        if args[:2] == ['container','inspect']:return SimpleNamespace(stdout=json.dumps([self.info[args[-1]]]))
        if args[0] == 'stop':self.info[args[-1]]['State']['Running']=False;return SimpleNamespace(stdout='')
        if args[:2] == ['container','rm']:del self.info[args[-1]];return SimpleNamespace(stdout='')
        raise AssertionError(args)


def test_container_has_only_explicit_test_mounts_and_is_inspected_before_start(tmp_path,monkeypatch):
    docker=FakeDocker(); starts=[]
    def start(args,**kwargs):
        starts.append(args);assert docker.commands[-1][:2]==['container','inspect']
        kwargs['stdout'].write(b'synthetic log');return SimpleNamespace(returncode=0)
    monkeypatch.setattr(M.subprocess,'run',start)
    assert docker.execute(IMAGE,{'mode':'python'},[(tmp_path,'/tmp',False)],tmp_path/'log',60)==0
    command=next(c for c in docker.commands if c[:2]==['container','create'])
    assert command[command.index('--network')+1]=='none' and '--read-only' in command
    assert command[command.index('--user')+1]=='10001:10001' and '--pull' in command
    assert command[-4:-2]==['-B','-c'] and command[-2]==M.PROGRAM
    assert starts[0][:3]==['docker','--host','unix:///var/run/docker.sock']
    assert docker.cleanup()['passed'] and not docker.info


@pytest.mark.parametrize('bad', ['bad_identity','bad_mount'])
def test_bad_container_identity_or_mount_never_starts(tmp_path,bad):
    docker=FakeDocker();setattr(docker,bad,True)
    with pytest.raises(RuntimeError):docker.execute(IMAGE,{'mode':'python'},[],tmp_path/'log',60)
    result=docker.cleanup()
    assert result['passed'] == (bad=='bad_mount')
    if bad=='bad_identity':assert not any(c[0]=='stop' or c[:2]==['container','rm'] for c in docker.commands)


def test_timeout_does_not_restart_and_preserves_partial_log_before_owned_cleanup(tmp_path,monkeypatch):
    docker=FakeDocker();starts=[]
    def timeout(args,**kwargs):
        starts.append(args);kwargs['stdout'].write(b'partial original log')
        docker.info[args[-1]]['State']['Running']=True
        raise subprocess.TimeoutExpired(args,600)
    monkeypatch.setattr(M.subprocess,'run',timeout)
    log=tmp_path/'log'
    with pytest.raises(subprocess.TimeoutExpired):docker.execute(IMAGE,{'mode':'tests'},[],log,600)
    assert log.read_bytes()==b'partial original log'
    assert docker.cleanup()['passed'] and not docker.info and len(starts)==1
    assert len([c for c in docker.commands if c[0]=='stop'])==1


def test_runtime_program_compiles_and_uses_full_runtime_collection():
    compile(M.PROGRAM,'<image-program>','exec')
    assert "actual==cfg['runtime']" in M.PROGRAM
    assert "root.glob('*.py')" in M.PROGRAM and "root/'static'" in M.PROGRAM
    assert "proof['after']=verify()" in M.PROGRAM
