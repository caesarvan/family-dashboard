"""Offline tool boundaries and actual synthetic SQLite; no Docker/SSH/Edge."""
import ast
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import sys

import pytest
from deploy import local_photo_controller_rehearsal as tool
from deploy import membership_release_data as core

ROOT = Path(__file__).resolve().parents[1]


def test_source_scope_accepts_only_explicit_build_fix_and_three_new_tools():
    before={'app.py':b'unchanged','deploy/membership_release_build.py':b'old'}
    after={**before,'deploy/membership_release_build.py':b'new'}
    assert tool.source_scope(before,after,tool.BUILD_FIX)==['deploy/membership_release_build.py']
    with pytest.raises(tool.control.ReleaseError): tool.source_scope(before,{**after,'app.py':b'changed'},tool.BUILD_FIX)
    with pytest.raises(tool.control.ReleaseError): tool.source_scope(before,{'app.py':b'unchanged'},tool.BUILD_FIX)
    assert len(tool.ADDITIONS)==len(tool.BUILD_FIX)==3


@pytest.mark.parametrize('candidate',[False,True])
def test_five_services_closed_limits_images_network_tls(candidate):
    images={'app':'sha256:'+'f'*64,'parent':tool.package.PARENT_IMAGE,'decoder':tool.package.DECODER_IMAGE,'web':tool.lifecycle.WEB_IMAGE}
    with tool.bindings([(tool.old,'IMAGES',images)]):
        value=tool.composition('fd-vcr-'+'a'*16+'-success',candidate,12345)
    assert set(value['services'])=={'app','sync','media','web','decoder'}
    assert value['networks']['default']['internal'] is True
    assert sum(tool.old.LIMITS.values())==960
    for name,limit in tool.old.LIMITS.items():
        service=value['services'][name]
        assert service['mem_limit']==service['memswap_limit']==str(limit)+'m'
        if name in ('app','sync','media'): assert service['image']==images['app' if candidate else 'parent']
    assert value['services']['decoder']['network_mode']=='none'
    assert value['services']['media']['environment']['MEDIA_VIDEO_SOCKET']==tool.lifecycle.SOCKET
    assert value['services']['web']['ports']==['127.0.0.1:12345:443']
    assert all(v.endswith(':ro') for v in value['services']['web']['volumes'])
    assert tool.old.BUDGET=={'preflightMiB':1088,'samples':3,'intervalSeconds':1,'abortBelowMiB':256,'monitorIntervalSeconds':.25,'maxLagSeconds':1}
    with pytest.raises(tool.control.ReleaseError): tool.composition('family-dashboard',True,12345)


def test_binding_restores_every_global_on_exception():
    prior=tool.old.IMAGES
    with pytest.raises(RuntimeError):
        with tool.bindings([(tool.old,'IMAGES',{'synthetic':True})]): raise RuntimeError('intentional')
    assert tool.old.IMAGES is prior


def test_real_synthetic_ca_validates_name_and_private_key(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    values=tool.tls_files()
    for name,raw in values.items():
        path=tmp_path/name;path.parent.mkdir(exist_ok=True);path.write_bytes(raw)
    cert=x509.load_pem_x509_certificate(values['deploy/rehearsal-cert.pem'])
    key=serialization.load_pem_private_key(values['deploy/rehearsal-key.pem'],password=None)
    assert cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)==[tool.HOST]
    assert key.public_key().public_numbers()==cert.public_key().public_numbers()
    server=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path/'deploy/rehearsal-cert.pem',tmp_path/'deploy/rehearsal-key.pem')
    client=ssl.create_default_context(cafile=str(tmp_path/'deploy/rehearsal-cert.pem'))
    # Actual OpenSSL MemoryBIO handshake: real certificate/name verification,
    # no mocked HTTP, network listener, Docker or claim about Nginx.
    ci,co,si,so=(ssl.MemoryBIO() for _ in range(4))
    c=client.wrap_bio(ci,co,server_hostname=tool.HOST);s=server.wrap_bio(si,so,server_side=True)
    done=set()
    for _ in range(20):
        for tag,obj in (('client',c),('server',s)):
            if tag not in done:
                try: obj.do_handshake();done.add(tag)
                except ssl.SSLWantReadError: pass
        if co.pending:si.write(co.read())
        if so.pending:ci.write(so.read())
        if len(done)==2:break
    assert done=={'client','server'} and c.getpeercert()['subjectAltName']==(('DNS',tool.HOST),)


def test_controller_methods_and_documented_restore_are_inherited():
    for name in tool.old.METHODS:
        assert getattr(tool.FixtureController,name) is getattr(tool.control.Controller,name)
    assert tool.old.restore_fixture.__module__=='deploy.media_video_controller_rehearsal'
    program=tool.marker_prefix(tool.control.DATA_PREFIX.replace('check_media_video_migration','media_video_release_data'))
    ast.parse(program)
    assert 'migrate(' not in program
    assert 'data.begin.__kwdefaults__' in program
    assert 'kwargs[' not in program


@pytest.fixture(scope='module')
def seeded(tmp_path_factory):
    folder=tmp_path_factory.mktemp('local-photo-real-seed');root=folder/'data';proof=folder/'proof'
    root.mkdir();proof.mkdir()
    code=tool.seed_program().replace("root=Path('/data');proof=Path('/proof');runtime=Path('/app')",
        f'root=Path({str(root)!r});proof=Path({str(proof)!r});runtime=Path({str(ROOT)!r})')
    env={k:v for k,v in os.environ.items() if k.upper() not in {'SECRET_KEY','DATA_DIR','PYTHONPATH','OPENAI_API_KEY','NVIDIA_API_KEY','GOOGLE_CLIENT_SECRET','MICROSOFT_CLIENT_SECRET'}}
    env.update(tool.old.seed.SYNTHETIC_ENV);env['DATA_DIR']=str(root)
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code],cwd=ROOT,env=env,capture_output=True,timeout=90)
    assert result.returncode==0,result.stderr.decode('utf8',errors='replace')
    actual=json.loads(result.stdout)
    assert actual['householdTables']==73 and actual['platformTables']==9 and len(actual['nonempty'])==2
    return root


def clone(source,target):
    target.mkdir()
    for name in core.enumerate_databases(source):
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(source/name)) as a,closing(sqlite3.connect(path)) as b:
            a.backup(b);b.execute('PRAGMA journal_mode=DELETE')
    (target/core.ROOT_ATTEMPT).write_bytes(tool.old.seed.SYNTHETIC_MARKER)


@pytest.mark.parametrize('fault',[False,True])
def test_real73_complete_group_check_and_documented_restore(seeded,tmp_path,monkeypatch,fault):
    root=tmp_path/'live';clone(seeded,root);proof=tmp_path/'proof';proof.mkdir()
    identity={'head':'a'*40,'tree':'b'*40,'imageId':'sha256:'+'c'*64,'sourceHashes':{'app.py':'d'*64},'runtimeHashes':{'app.py':'d'*64}}
    kwargs={'source_identity':identity,'plan_sha256':'e'*64,'marker_sha256':tool.MARKER}
    initial=tool.data.snapshot_current(root);tool.data.begin(root,proof,**kwargs)
    if fault:
        result=tool.inject_sentinel(root,tmp_path/'injected.json')
        assert len([n for n in result['before'] if result['before'][n]!=result['after'][n]])==1
        with pytest.raises(core.ReleaseDataError,match='assistant_database_drift'):tool.data.check_stopped(root,proof,**kwargs)
        assert not (proof/'result.json').exists()
    else:
        tool.data.check_stopped(root,proof,**kwargs)
        assert tool.preservation_summary(proof)['databases']==3
    with pytest.raises(FileExistsError):tool.data.begin(root,proof,**kwargs)
    receipt=tool.control.read(proof/'backup.json');saved=proof/'backup-group'
    manifest=tool.control.read(saved/'backups'/receipt['manifest'])
    # Real documented complete-group restore, at the original bound root.
    for name in ['backups/'+receipt['manifest'],*[r['path'] for r in manifest['snapshots']]]:
        target=root/name
        if target.exists(): assert target.read_bytes()==(saved/name).read_bytes()
        else:target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(saved/name,target)
    restore,_=tool.old.restore.documented_programs(ROOT)
    restore=restore.replace("root = Path('/data').resolve(strict=True)",f'root = Path({str(root)!r}).resolve(strict=True)')
    with monkeypatch.context() as context:
        context.setattr(sys,'argv',['documented-restore',receipt['manifest'],'platform','default'])
        exec(compile(restore,'<real-documented-synthetic-restore>','exec'),{'__name__':'__main__'})
        context.setattr(tool.data,'MEMBERSHIP_MARKER_SHA256',tool.MARKER)
        assert tool.entry.verify_restored_group(root,proof,**{k:v for k,v in kwargs.items() if k!='marker_sha256'})['completeGroupRestored']
    final=tool.data.snapshot_current(root)
    assert core._logical(initial)==core._logical(final)


@pytest.mark.parametrize('phase,has_fault',[('live',False),('app-only',False),('app-stopped',True)])
def test_fault_injection_requires_stopped_phase_and_single_attempt(tmp_path,phase,has_fault):
    from types import SimpleNamespace
    transport=object.__new__(tool.Transport);transport.scenario='failure'
    transport.controller=SimpleNamespace(lifecycle=SimpleNamespace(phase=phase),stopped=lambda:pytest.fail('must reject before stopped call'))
    transport.sentinel_fault={} if has_fault else None
    with pytest.raises(tool.control.ReleaseError,match='fault_requires_app_only_stopped'):
        transport([*tool.lifecycle.DOCKER,'create','value=data.check_stopped(root,proof,**kwargs)'])


def test_nonempty_sentinel_guard_does_not_accept_other_rows(seeded,tmp_path):
    root=tmp_path/'live';clone(seeded,root)
    target=next((root/'spaces').glob('*/household.sqlite3'))
    with closing(sqlite3.connect(target)) as con:
        con.execute('UPDATE settings SET data=? WHERE id=?',('{"different":true}',tool.SENTINEL));con.commit()
    before={n:tool.sha((root/n).read_bytes()) for n in core.enumerate_databases(root)}
    with pytest.raises(tool.control.ReleaseError,match='wrong_synthetic_sentinel'):tool.inject_sentinel(root,tmp_path/'fault.json')
    assert before=={n:tool.sha((root/n).read_bytes()) for n in before}
    assert not (tmp_path/'fault.json').exists()


@pytest.mark.parametrize('fault',[None,'runtime','extra','failed'])
def test_build_input_closed_set_and_actual_record_binding(tmp_path,fault):
    def write(name,value):
        raw=value if isinstance(value,bytes) else json.dumps(value).encode()
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        return tool.sha(raw)
    runtime={'app.py':write('context/runtime/app.py',b'synthetic fixture')}
    record={'arguments':['docker','image','inspect','synthetic'],'exitCode':0,
        'stdout':'commands/000.stdout','stderr':'commands/000.stderr'}
    write('commands/000.stdout',b'[]');write('commands/000.stderr',b'');write('commands/000.json',record)
    write('commands.json',{'commands':[record]});write('build.log',b'synthetic tool boundary')
    image='sha256:'+'e'*64;write('image-id',image.encode())
    recipe=write('context/Dockerfile',b'FROM synthetic\n')
    meta={'sourceHead':'a'*40,'tree':'b'*40,'manifestSha256':'c'*64,'runtimeFiles':runtime}
    built={'exitCode':0,'productionOperations':False,**{k:meta[k] for k in ('sourceHead','tree','manifestSha256')},
        'packageSha256':'d'*64,'parentImage':tool.package.PARENT_IMAGE,'addedLayers':2,'runtimeHashes':runtime,
        'parentConfig':{'User':'dashboard'},'imageId':image,'dockerfileSha256':recipe}
    if fault=='failed':built['exitCode']=1
    digest=write('build.json',built)
    if fault=='runtime':write('context/runtime/app.py',b'changed')
    if fault=='extra':write('unexpected.sqlite3',b'not permitted')
    if fault:
        with pytest.raises(tool.control.ReleaseError):tool.checked_build(tmp_path,digest,{'metadata':meta},'d'*64)
    else:assert tool.checked_build(tmp_path,digest,{'metadata':meta},'d'*64)==built
