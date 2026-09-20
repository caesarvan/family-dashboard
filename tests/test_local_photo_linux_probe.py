"""Offline preparation/policy tests; never Docker, HTTP workload or Linux PASS."""
import hashlib
import json
from pathlib import Path
import re
import pytest

from deploy import local_photo_linux_probe as probe

ROOT = Path(__file__).resolve().parents[1]


def test_actual_docker_copy_closure_includes_local_upload_and_static():
    names = ['Dockerfile', *[p.name for p in ROOT.glob('*.py')], 'requirements.txt',
             *[p.relative_to(ROOT).as_posix() for p in (ROOT/'static').rglob('*') if p.is_file()]]
    blobs = {n:(ROOT/n).read_bytes() for n in names}
    found = probe.runtime_names(blobs)
    assert 'media_local_upload.py' in found and 'home_assistant.py' in found and 'static/app.js' in found
    assert not any(n.startswith(('test-results/', '.env', 'tests/')) for n in found)


@pytest.mark.parametrize('text', ['COPY --from=builder /data /app', 'COPY absent/ /app/', 'COPY app.py ./'])
def test_incomplete_or_unreviewed_copy_fails(text):
    with pytest.raises(RuntimeError):probe.runtime_names({'Dockerfile':text.encode(),'app.py':b''})


def test_nginx_adaptation_keeps_both_exact_raw_locations():
    original=(ROOT/'deploy/nginx.conf').read_bytes()
    new=probe.adapted_nginx(original).decode()
    pattern=r'location ~ "\^/api/media/local-imports/.*?\n    }'
    assert re.findall(pattern,new,re.S)==re.findall(pattern,original.decode(),re.S)
    assert new.count('listen 8443 ssl')==2 and 'listen 8080;' in new
    assert 'home.caesarcharles.world' not in new and '/etc/letsencrypt/' not in new
    assert 'client_body_temp_path /cache/client;' in new and 'proxy_temp_path /cache/proxy;' in new
    assert 'proxy_pass http://app:8000;' in new


@pytest.mark.parametrize('role', ['app','web','client'])
def test_container_limits_and_isolation_no_production_names(tmp_path,role):
    args=probe.container_args(role,'a'*64,'lp-'+'1'*16,tmp_path/'input',tmp_path/'output','nginx_raw')
    assert '--read-only' in args and '--cap-drop=ALL' in args and '--user=10001:10001' in args
    assert '--pull=never' in args
    assert f'--memory={probe.LIMITS[role]}m' in args and f'--memory-swap={probe.LIMITS[role]}m' in args
    assert '--network' in args and not any(x in args for x in ['--privileged','-p','--publish','--network=host','/var/run/docker.sock'])
    assert not any('/opt/family-dashboard' in x for x in args)
    if role=='web':assert probe.WEB_IMAGE in args and '/usr/sbin/nginx' in args
    else:assert probe.APP_IMAGE in args and '-i' in args and 'COOKIE_SECURE=1' in args
    if role!='app':assert not any('dst=/data' in x for x in args)


@pytest.mark.parametrize('role,token,profile',[('other','lp-'+'1'*16,'image_overlap'),('app','production','image_overlap'),('app','lp-'+'1'*16,'all')])
def test_unknown_role_scope_or_profile_rejected(tmp_path,role,token,profile):
    with pytest.raises(RuntimeError):probe.container_args(role,'a'*64,token,tmp_path,tmp_path,profile)


@pytest.fixture(scope='module')
def images(tmp_path_factory):
    folder=tmp_path_factory.mktemp('local-photo-probe-synthetic');return folder,probe.make_images(folder)


def test_actual_pillow_synthetic_inputs_have_exact_limits(images):
    from PIL import Image
    folder, records=images
    assert len(records)==5 and records[-1]['bytes']==8*1024**2
    for row in records:
        path=folder/row['filename'];assert path.stat().st_size==row['bytes'] and probe.sha(path)==row['sha256']
        with Image.open(path) as image:
            image.load(); assert image.width*image.height==row['pixels']
            if row['filename']=='orientation.jpg':assert image.getexif()[274]==6
            if row['filename'].startswith('alpha'):assert image.mode=='RGBA'


def test_exact8_jpeg_runs_actual_sanitizer_without_mock(images):
    from media_images import sanitize_media_preview
    folder,_=images
    result=sanitize_media_preview((folder/'exact8.jpg').read_bytes(),'image/jpeg')
    assert result.width==96 and result.height==64 and result.content_type=='image/jpeg'
    assert len(result.data)<2*1024**2 and hashlib.sha256(result.data).hexdigest()==result.sha256


def test_host_policy_is_separate_from_old_1280_admission():
    from deploy import media_video_ipc_resource_probe as common
    original=dict(common.HOST_BUDGET)
    try:
        probe.common_module()
        assert common.HOST_BUDGET==probe.BUDGET and probe.BUDGET['preflightMiB']==sum(probe.LIMITS.values())+128
        assert probe.BUDGET['preflightSamples']==3 and probe.BUDGET['preflightIntervalSeconds']==1
        assert probe.BUDGET['sampleIntervalSeconds']==.25 and probe.BUDGET['abortBelowMiB']==256
    finally:common.HOST_BUDGET=original


def test_preflight_failure_retains_all_three_samples_without_starting_work(tmp_path):
    from deploy import media_video_ipc_resource_probe as common
    original=dict(common.HOST_BUDGET)
    try:
        probe.common_module();values=iter([700*1024,671*1024,900*1024]);sleeps=[]
        receipt=common.host_preflight(tmp_path,reader=lambda:next(values),sleeper=sleeps.append)
        assert receipt['status']=='preflight_blocked' and len(receipt['samples'])==3 and sleeps==[1,1]
        assert json.loads((tmp_path/'preflight.json').read_text())==receipt
    finally:common.HOST_BUDGET=original


def test_inspect_requires_exact_owned_id_label_and_name():
    cid='b'*64;token='lp-'+'a'*16
    class ReadOnly:
        info={'Id':cid,'Config':{'Labels':{'local-photo-probe':token}},'Name':'/'+token+'-app'}
        def call(self,args):
            assert args==['inspect','--format','{{json .}}',cid]
            return 0,json.dumps(self.info).encode()
    ex=ReadOnly();assert probe.inspect_owned(ex,cid,'app',token)['Id']==cid
    ex.info={**ex.info,'Name':'/production-app'}
    with pytest.raises(RuntimeError):probe.inspect_owned(ex,cid,'app',token)


def test_output_path_scope_and_existence(tmp_path):
    with pytest.raises(RuntimeError):probe.safe(tmp_path,exists=False)
    with pytest.raises(RuntimeError):probe.safe(tmp_path,remote=True)
    with pytest.raises(RuntimeError):probe.safe(Path('relative'))
    with pytest.raises(RuntimeError):probe.safe(tmp_path/'..'/'other',exists=False)


def test_database_proof_detects_duplicate_rows_and_revision(tmp_path):
    import sqlite3
    con=sqlite3.connect(tmp_path/'household.sqlite3')
    con.executescript('CREATE TABLE media_items(id,state,visibility,revision,confirmed_at,preview_cipher,metadata_cipher);CREATE TABLE audit(action);')
    con.execute('INSERT INTO media_items VALUES(?,?,?,?,?,?,?)',('photo','ready','private',2,1,b'cipher',b'cipher'))
    con.execute('INSERT INTO media_items VALUES(?,?,?,?,?,?,?)',('video','ready','private',2,1,b'cipher',b'cipher'))
    con.executemany('INSERT INTO audit VALUES(?)',[('media_import_confirm',)]*2);con.commit();con.close()
    result=probe.database_proof(tmp_path,{'checks':[{'id':'photo','revision':2}]},'image_overlap');assert len(result)==1
    with pytest.raises(RuntimeError):probe.database_proof(tmp_path,{'checks':[{'id':'photo','revision':1}]},'image_overlap')
    with pytest.raises(RuntimeError):probe.database_proof(tmp_path,{'checks':[]},'image_overlap')


def test_tls_uses_actual_selected_server_name_on_private_transport(monkeypatch):
    import http.client, ssl
    observed=[]
    class Socket:
        def setsockopt(self,*args):observed.append(('socket',args))
    class Connection:
        def __init__(self,host,port,**kwargs):observed.append(('transport',host,port));self.sock=Socket()
        def connect(self):observed.append(('connect',))
    class Context:
        def wrap_socket(self,sock,server_hostname):observed.append(('tls',server_hostname));return sock
    def context(**kwargs):
        assert kwargs=={'cafile':'/input/tls/cert.pem'}
        return Context()
    monkeypatch.setattr(http.client,'HTTPConnection',Connection);monkeypatch.setattr(ssl,'create_default_context',context)
    probe.HTTP(tls=True,host='probe-default.invalid').connect()
    assert observed[:3]==[('transport','web',8443),('connect',),('tls','probe-default.invalid')]


def test_direct_script_help_needs_no_pythonpath_or_docker(tmp_path):
    import os,subprocess,sys
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    result=subprocess.run([sys.executable,'-B',str(ROOT/probe.SELF),'--help'],cwd=tmp_path,env=env,capture_output=True,timeout=15)
    assert result.returncode==0 and b'prepare' in result.stdout and b'run' in result.stdout
