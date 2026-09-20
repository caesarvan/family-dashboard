"""Offline preparation and real local subprocess seams, never Docker or production."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from deploy import media_video_migration_linux_probe as probe

ROOT=Path(__file__).resolve().parents[1]
IMAGE='sha256:'+'a'*64


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    base=tmp_path_factory.mktemp('migration-probe');repo=base/'repo'
    probe.policy.git(ROOT,'clone','--quiet','--shared','--no-checkout',str(ROOT),str(repo))
    probe.policy.git(repo,'config','core.autocrlf','false');probe.policy.git(repo,'config','core.longpaths','true')
    probe.policy.git(repo,'checkout','--quiet','--detach',probe.BASE)
    for name in probe.ADDITIONS:(repo/name).write_bytes((ROOT/name).read_bytes())
    probe.policy.git(repo,'add','--all')
    probe.policy.git(repo,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','synthetic tool inputs')
    head=probe.policy.git(repo,'rev-parse','HEAD').decode().strip()
    result=probe.prepare(repo,head,base/'bundle')
    return base,result


def test_prepared_history_programs_and_source_are_complete_and_closed(prepared):
    base,result=prepared;bundle,meta=probe.verify(base/'bundle',result['inputSha256'])
    assert meta['historicalHead']==probe.HISTORY and meta['runtimeSourceHead']==probe.BASE
    assert {'app.py','media_crypto.py','task_reminders.py'}<=meta['historyFiles'].keys()
    assert not {'media_video_storage.py','media_playback_progress.py'}&meta['historyFiles'].keys()
    assert {'media_video_storage.py','media_playback_progress.py','requirements.txt'}<=meta['runtimeFiles'].keys()
    assert set(meta['files'])=={'release/'+n for n in meta['sourceFiles']}|{'history/'+n for n in meta['historyFiles']}|{
        'programs/'+n+'.py' for n in probe.STAGES}
    assert not any('.sqlite' in n or '/.env' in n or 'test-results' in n or 'node_modules' in n for n in meta['files'])
    for stage in probe.STAGES:
        code=(bundle/'programs'/f'{stage}.py').read_text(encoding='utf8');ast.parse(code)
        assert 'import pytest' not in code and 'subprocess' not in code and 'monkeypatch' not in code
    partial=(bundle/'programs/partial.py').read_text(encoding='utf8')
    assert 'blocked.chmod(0o400)' in partial and 'except sqlite3.OperationalError' in partial
    assert "list(counts.values())==[73,71]" in partial and 'migration.verify_rollback' in partial
    with pytest.raises(ValueError,match='new output'):
        probe.prepare(base/'repo',result['sourceHead'],bundle)


@pytest.mark.parametrize('fault',['history','program','extra','manifest'])
def test_tampered_or_expanded_inputs_are_refused(prepared,tmp_path,fault):
    base,result=prepared;target=tmp_path/'bundle';shutil.copytree(base/'bundle',target)
    name={'history':'history/app.py','program':'programs/migrate.py','extra':'release/unreviewed.py','manifest':'input.json'}[fault]
    (target/name).write_bytes(b'changed')
    with pytest.raises(ValueError):probe.verify(target,result['inputSha256'])


def test_container_policy_has_only_bound_synthetic_mounts_and_no_worker_start(tmp_path):
    bundle=tmp_path/'bundle';output=tmp_path/'output'
    for stage in probe.STAGES:
        args=probe.container_args(IMAGE,bundle,output,stage,'b'*64)
        assert args[:3]==['create','--network','none']
        for key,value in [('--user','10001:10001'),('--memory','384m'),('--memory-swap','384m'),('--cpus','1'),('--pids-limit','128')]:
            assert args[args.index(key)+1]==value
        assert '--read-only' in args and '--no-healthcheck' in args
        mounts=[args[n+1] for n,x in enumerate(args) if x=='--mount']
        assert len(mounts)==5 and sum(x.endswith(',readonly') for x in mounts)==3
        assert all(str(bundle) in x or str(output) in x for x in mounts)
        assert args[-4:]==[IMAGE,'-B','-I','/programs/'+stage+'.py']
        assert not any(x in args for x in ('compose','--env-file','--network=host','--privileged','-p'))
    with pytest.raises(ValueError):probe.container_args('app:latest',bundle,output,'seed','b'*64)
    with pytest.raises(ValueError):probe.container_args(IMAGE,bundle,output,'worker','b'*64)


def test_real_local_closed_migration_app_startup_and_full_restores(prepared,tmp_path):
    """Eight real programs; path adaptation isn't a Linux image/permission claim."""
    base,result=prepared;bundle,meta=probe.verify(base/'bundle',result['inputSha256'])
    data=tmp_path/'data';proof=tmp_path/'proof'
    (data/'main').mkdir(parents=True);(proof/'main').mkdir(parents=True)
    release=bundle/'release'
    # On Windows the real app runs from the identical prepared source directory,
    # which also holds helper modules absent from the minimal Docker COPY set.
    # No initializer, migration function, connection or result is replaced.
    runtime={p.name:probe.sha(p.read_bytes()) for p in release.glob('*.py')}
    runtime['requirements.txt']=probe.sha((release/'requirements.txt').read_bytes())
    contract={'historyFiles':meta['historyFiles'],'syntheticMarkerSha256':meta['syntheticMarkerSha256'],
              'identity':{'head':meta['sourceHead'],'tree':meta['tree'],'imageId':IMAGE,
                          'sourceHashes':meta['sourceFiles'],'runtimeHashes':runtime}}
    raw=probe.encoded(contract);(proof/'contract.json').write_bytes(raw)
    env={k:os.environ[k] for k in ('SystemRoot','PATH','TEMP','TMP') if k in os.environ}
    env.update(probe.previous.SYNTHETIC_ENV)
    env.update(DATA_DIR=str(data/'main'),REHEARSAL_DATA=str(data),REHEARSAL_PROOF=str(proof),
               REHEARSAL_RELEASE=str(release),REHEARSAL_HISTORY=str(bundle/'history'),REHEARSAL_RUNTIME=str(release),
               REHEARSAL_CONTRACT_SHA256=probe.sha(raw),MEDIA_VIDEO_SOCKET='')
    stages=[n for n in probe.STAGES if n not in ('verify','partial')]
    outcomes={}
    for stage in stages:
        p=subprocess.run([sys.executable,'-B','-I',str(bundle/'programs'/f'{stage}.py')],
                         cwd=release,env=env,capture_output=True,timeout=90)
        (proof/(stage+'.stdout')).write_bytes(p.stdout);(proof/(stage+'.stderr')).write_bytes(p.stderr)
        assert p.returncode==0,(stage,p.stderr.decode('utf8',errors='replace'))
        outcomes[stage]=json.loads(p.stdout)
    assert len(outcomes)==8 and outcomes['seed']['households']==2 and outcomes['seed']['householdTables']==71
    assert outcomes['migrate']['databases']==3 and outcomes['check']['logicalSha256']==outcomes['migrate']['logicalSha256']
    assert outcomes['startup']['initialized'] and outcomes['restart']['initialized']
    assert outcomes['rollback71']['completeGroupRestored'] and outcomes['restore73']['completeGroupRestored']
    assert outcomes['populate73']['rowsPerNewTable']==2
    (proof/'local-results.json').write_bytes(probe.encoded({'linux':False,'docker':False,'stages':outcomes}))
    # Byte stability is checked after the actual subprocess app factories.
    probe.verify(bundle,result['inputSha256'])
