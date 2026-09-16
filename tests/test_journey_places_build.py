"""Command stubs plus real local build-context files; no actual Docker build."""
from copy import deepcopy
import json
import pathlib
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from deploy import build_journey_places_release as B
from tests.test_journey_places_release import Fixture as ReleaseFixture, IMAGE


@pytest.fixture(autouse=True)
def no_external_process_or_network(monkeypatch):
    def deny(*a,**k): raise AssertionError('Actual Docker/network forbidden in build unit test')
    monkeypatch.setattr(subprocess,'run',deny); monkeypatch.setattr(socket.socket,'connect',deny)


class Fixture:
    def __init__(self,path):
        self.release=ReleaseFixture(path); self.source=self.release.candidate; self.output=path/'build-output'
        self.parent=self.release.previous; self.calls=[]; self.change=None; self.on_build=None
        config={'User':'10001','Env':['DATA_DIR=/data','PYTHONDONTWRITEBYTECODE=1'],'Cmd':['gunicorn'],
                'Entrypoint':None,'WorkingDir':'/app'}
        self.images={self.parent:{'Id':self.parent,'Config':config,'RootFS':{'Type':'layers','Layers':['sha256:'+'a'*64]}},
                     IMAGE:{'Id':IMAGE,'Config':deepcopy(config),'RootFS':{'Type':'layers','Layers':['sha256:'+'a'*64,'sha256:'+'b'*64]}}}

    def runner(self,args,**kwargs):
        self.calls.append(args)
        if args[:3]==['docker','image','inspect']: return json.dumps([self.images[args[-1]]])
        if args[:2]==['docker','run']:
            assert args[args.index('--network')+1]=='none' and '--mount' not in args and '--read-only' in args
            parent=args[args.index('--entrypoint')+2]==self.parent
            if args[-1].startswith(B.C.RUNTIME_BOUNDARY):
                if self.change=='bytecode' and not parent: raise RuntimeError('synthetic stale pyc')
                return json.dumps({'runtimeBoundaryVerified':True})
            assert args[-2]==B.B.PROBE
            names=json.loads(args[-1]); hashes=self.release.ready['baseHashes'] if parent else self.release.hashes
            value={'hashes':{n:hashes[n] for n in names},'backendFiles':sorted(B.C.backend_hashes(hashes)),
                   'staticFiles':sorted(B.C.static_hashes(hashes))}
            if self.change==('parent-bytes' if parent else 'child-bytes'): value['hashes']['app.py']='0'*64
            if self.change==('parent-extra' if parent else 'child-extra'): value['backendFiles'].append('unexpected.py')
            if self.change=='stale-static' and not parent:value['staticFiles'].append('static/unlisted.js')
            return json.dumps(value)
        if args[:2]==['docker','build']:
            assert '--pull=false' in args and args[args.index('--network')+1]=='none'
            context=Path(args[-1]); assert (context/'Dockerfile').read_text()==f'FROM {self.parent}\nCOPY --chown=10001:10001 app/ /app/\n'
            names={p.relative_to(context).as_posix() for p in context.rglob('*') if p.is_file()}
            expected={'app/'+n for n in self.release.hashes if n.startswith('static/') or '/' not in n and n.endswith('.py')}
            assert names==expected|{'Dockerfile'}
            assert not any('/tools/' in n or n.endswith('DESIGN.md') or '/deploy/' in n or '/tests/' in n for n in names)
            if self.on_build:self.on_build(context)
            Path(args[args.index('--iidfile')+1]).write_text(IMAGE)
            return 'synthetic build output'
        raise AssertionError(args)

    def run(self):
        return B.build(self.source,self.parent,self.release.ready['manifestSha256'],self.release.ready['baseManifestSha256'],self.output,runner=self.runner)


@pytest.fixture
def f(tmp_path):return Fixture(tmp_path)


def test_build_proves_complete_parent_and_candidate_runtime_without_development_package(f):
    value=f.run()
    assert value['status']=='built' and value['image']==IMAGE
    assert value['parentRuntimeHashes']=={**B.C.backend_hashes(f.release.ready['baseHashes']),**B.C.static_hashes(f.release.ready['baseHashes'])}
    assert value['candidateRuntimeHashes']['journey_places.py']==f.release.hashes['journey_places.py']
    assert value['parentConfigSha256']==value['childConfigSha256'] and value['bytecodeExcluded']
    assert not value['productionOperations'] and not value['pipExecuted']
    assert not any('compose' in args or 'tag' in args for args in f.calls)


@pytest.mark.parametrize('change',['parent-bytes','parent-extra','unbound-source','existing-output','extra-python','tools-path'])
def test_preflight_failure_never_builds(f,change):
    f.change=change
    if change=='unbound-source':(f.source/'app.py').write_bytes(b'changed')
    if change=='existing-output':f.output.mkdir()
    if change in ('extra-python','tools-path'):
        f.release.values['extra.py' if change=='extra-python' else 'tools/unexpected.py']=b'no'
        f.release.refreeze_source()
    with pytest.raises(RuntimeError):f.run()
    assert not any(args[:2]==['docker','build'] for args in f.calls)


@pytest.mark.parametrize('change',['child-bytes','child-extra','stale-static','bytecode','config','parent-layer','extra-layer'])
def test_child_mismatch_preserves_failed_receipt(f,change):
    f.change=change
    if change=='config':f.images[IMAGE]['Config']['Env'].append('CHANGED=1')
    if change=='parent-layer':f.images[IMAGE]['RootFS']['Layers'][0]='sha256:'+'c'*64
    if change=='extra-layer':f.images[IMAGE]['RootFS']['Layers'].append('sha256:'+'c'*64)
    with pytest.raises(RuntimeError,match='places_build_failed'):f.run()
    assert json.loads((f.output/'build.json').read_bytes())['status']=='failed'


@pytest.mark.parametrize('change',['recipe','context','payload','source','base-manifest','manifest','private-error'])
def test_changes_during_build_cannot_produce_success(f,change):
    def mutate(context):
        if change=='recipe':(context/'Dockerfile').write_text('FROM bad\nRUN bad\n')
        if change=='context':(context/'private.env').write_text('synthetic=1')
        if change=='payload':(context/'app/journey_places.py').write_text('changed')
        if change=='source':(f.source/'app.py').write_text('changed')
        if change=='base-manifest':(f.source/'BASE-MANIFEST.json').write_text('{}')
        if change=='manifest':(f.source/'RELEASE-MANIFEST.json').write_text('{}')
        if change=='private-error':raise RuntimeError('do-not-print-synthetic-private-output')
    f.on_build=mutate
    with pytest.raises(RuntimeError,match='places_build_failed') as error:f.run()
    value=(f.output/'build.json').read_text()
    assert 'do-not-print-synthetic-private-output' not in value+str(error.value)
    assert json.loads(value)['status']=='failed'


@pytest.mark.parametrize('name',['COMPOSE_FILE','docker_host'])
def test_builder_rejects_host_selectors_before_any_command(f,monkeypatch,name):
    monkeypatch.setenv(name,'synthetic-override')
    with pytest.raises(RuntimeError,match='host_docker_compose_environment'):f.run()
    assert not f.calls


def test_one_frozen_environment_is_used_for_every_build_command(f,monkeypatch):
    monkeypatch.setenv('SYNTHETIC_PLACES_INPUT','before'); supplied=[]
    def runner(args,**kwargs):
        supplied.append(kwargs['env']);monkeypatch.setenv('SYNTHETIC_PLACES_INPUT','after')
        return f.runner(args,**kwargs)
    result=B.build(f.source,f.parent,f.release.ready['manifestSha256'],f.release.ready['baseManifestSha256'],f.output,runner=runner)
    assert result['status']=='built' and len(supplied)>2
    assert all(e['SYNTHETIC_PLACES_INPUT']=='before' for e in supplied)


@pytest.mark.parametrize('extra',['none','tools','DESIGN.md','stale.pyc'])
def test_actual_runtime_guard_rejects_development_source_and_bytecode(tmp_path,monkeypatch,extra):
    application=tmp_path/'app';application.mkdir()
    if extra=='tools':(application/extra).mkdir()
    elif extra!='none':(application/extra).write_bytes(b'synthetic')
    original=pathlib.Path
    def mapped(path):return application if path=='/app' else original(path)
    with monkeypatch.context() as patch:
        patch.setattr(pathlib,'Path',mapped)
        patch.setattr(sys,'dont_write_bytecode',True);patch.setattr(sys,'pycache_prefix',None)
        if extra=='none':exec(compile(B.C.RUNTIME_BOUNDARY,'<actual-runtime-boundary>','exec'),{})
        else:
            with pytest.raises(RuntimeError):exec(compile(B.C.RUNTIME_BOUNDARY,'<actual-runtime-boundary>','exec'),{})
