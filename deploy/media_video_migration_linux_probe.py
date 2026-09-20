"""Prepare a closed Git fixture; rehearse synthetic 71/9 -> 73/9 in one app image.

No production paths, workers, decoder, Git or pytest inside the container.
The Linux run is a separate explicitly invoked operation, never part of prepare.
"""
import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import textwrap

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import membership_release_package as policy
from deploy import membership_release_build as build
from deploy.git_blobs import read_git_blobs
from deploy import steady_linux_rehearsal as previous
from deploy import journey_routes_linux_rehearsal as routes
from deploy import rehearse_restore as restore

need, sha, encoded = policy.need, policy.digest, policy.encoded
BASE = 'db3786666d293c9a473f519766fa4112816f2b04'
BASE_MAP_SHA = '4d6db69a743fc9f51a726e647d037373e1d2e51719a87e5cc0bdd660fb06018b'
HISTORY = '8d3e6376a606155ff66a0388e43d04cb7562fe9f'
SELF = 'deploy/media_video_migration_linux_probe.py'
ADDITIONS = {SELF, 'tests/test_media_video_migration_linux_probe.py', 'docs/MEDIA-VIDEO-MIGRATION-LINUX.md'}
FIXTURES = {'tests/test_membership_migration.py', 'tests/test_media_video_migration.py'}
DOCS = {'docs/DEPLOYMENT.md', 'docs/MEMBER-SESSIONS.md'}
STAGES = ('verify', 'seed', 'migrate', 'startup', 'check', 'rollback71', 'partial',
          'populate73', 'restart', 'restore73')


def hashes(blobs):
    return {n: sha(raw) for n, raw in sorted(blobs.items())}


def dml(raw, function=None):
    """Only reuse a single existing literal DML block, never copy table DDL."""
    tree = ast.parse(textwrap.dedent(raw.decode() if isinstance(raw, bytes) else raw))
    if function:
        found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function]
        need(len(found) == 1, 'fixture function changed'); tree = found[0]
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and
             ((isinstance(n.func, ast.Name) and n.func.id == 'execute') or
              (isinstance(n.func, ast.Attribute) and n.func.attr == 'executescript'))]
    need(len(calls) == 1, 'fixture SQL selection changed')
    sql = ast.literal_eval(calls[0].args[-1])
    need(isinstance(sql, str) and not any(word in sql.upper() for word in ('CREATE ', 'DROP ', 'ALTER ')),
         'fixture DDL forbidden')
    return sql


PREFIX = r'''
import hashlib,json,os,shutil,socket,sqlite3,sys
from contextlib import closing,redirect_stdout
from pathlib import Path
if sys.flags.optimize or not sys.dont_write_bytecode:raise RuntimeError('python -B without optimization required')
release=Path(os.environ['REHEARSAL_RELEASE']);history=Path(os.environ['REHEARSAL_HISTORY'])
base=Path(os.environ['REHEARSAL_DATA']);allproof=Path(os.environ['REHEARSAL_PROOF'])
runtime=Path(os.environ['REHEARSAL_RUNTIME']);root=base/'main';proof=allproof/'main'
contract_raw=(allproof/'contract.json').read_bytes()
if hashlib.sha256(contract_raw).hexdigest()!=os.environ['REHEARSAL_CONTRACT_SHA256']:raise RuntimeError('contract changed')
contract=json.loads(contract_raw);identity=contract['identity']
def check_tree(path,expected):
 actual={}
 for p in path.rglob('*'):
  if p.is_symlink():raise RuntimeError('linked source')
  if p.is_file():actual[p.relative_to(path).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
 if actual!=expected:raise RuntimeError('source bytes changed')
check_tree(release,identity['sourceHashes']);check_tree(history,contract['historyFiles'])
def no_network(*args,**kwargs):raise RuntimeError('synthetic rehearsal network forbidden')
socket.socket.connect=no_network;socket.create_connection=no_network
'''

BIND = r'''
sys.path[:0]=[str(runtime),str(release)]
from deploy import membership_release_data as data
from deploy import check_media_video_migration as migration
from deploy import media_video_release_data as current
observed={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime.glob('*.py')}
observed['requirements.txt']=hashlib.sha256((runtime/'requirements.txt').read_bytes()).hexdigest()
if observed!=identity['runtimeHashes']:raise RuntimeError('image runtime changed')
kwargs={'source_identity':identity,'plan_sha256':os.environ['REHEARSAL_CONTRACT_SHA256'],
 'marker_sha256':contract['syntheticMarkerSha256']}
def dump(name,value):data._write_new(proof/name,value)
def checkpoint(path):
 with closing(sqlite3.connect(path)) as con:
  assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
def clone_group(source,target):
 reference=migration.snapshot_baseline(source)
 original={n:data.migration.file_digest(source/n) for n in data.enumerate_databases(source)}
 target.mkdir(mode=0o700)
 for relative in original:
  destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
  # The app process has exited and snapshot_baseline rejected all sidecars.
  # Immutable read avoids creating an empty WAL pair on the stopped source.
  with closing(sqlite3.connect((source/relative).as_uri()+'?mode=ro&immutable=1',uri=True)) as old,closing(sqlite3.connect(destination)) as new:
   old.backup(new);new.execute('PRAGMA journal_mode=DELETE')
  destination.chmod(0o600)
 shutil.copyfile(source/data.ROOT_ATTEMPT,target/data.ROOT_ATTEMPT)
 assert all(data.migration.file_digest(source/n)==value for n,value in original.items())
 assert migration.snapshot_baseline(source)==reference
 assert data._logical(migration.snapshot_baseline(target))==data._logical(reference)
'''


def programs(blobs, source):
    video = blobs['tests/test_media_video_migration.py']
    # Existing seed uses the real login/invitation/redeem/task/role APIs.
    seed = routes.replace_once(previous.SEED_PROGRAM, 'len(tables)==61', 'len(tables)==71')
    seed = routes.replace_once(seed, "'householdTables':61", "'householdTables':71")
    sentinel = '\n'.join((dml(routes.POPULATE_FINANCE), dml(routes.POPULATE_ROUTES), dml(video, 'baseline71')))
    anchor = "  con.commit();assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0"
    seed = routes.replace_once(seed, anchor, '  con.executescript(' + repr(sentinel) + ')\n' + anchor)
    startup = previous.STARTUP_PROGRAM
    startup = routes.replace_once(startup, "Path('/app/app.py')", "runtime/'app.py'")
    original_restore = restore.documented_programs(source)[0]
    # Only the root literal changes; run the full documented restore verbatim.
    restored = routes.replace_once(original_restore, "root = Path('/data').resolve(strict=True)",
                                    "root = Path(os.environ['REHEARSAL_RESTORE_TARGET']).resolve(strict=True)")
    helper = routes.RESTORE_GROUP.replace("assert target_name in ('restored-old','restored-current')",
                                         "assert target_name in ('restored-old','restored-current','restored-partial')")
    helper = routes.replace_once(helper, 'captured=io.StringIO()',
                                  "os.environ['REHEARSAL_RESTORE_TARGET']=str(destination)\n captured=io.StringIO()")
    # The original program already imports os? Supply it explicitly either way.
    restored = 'import os\n' + restored
    codes = {'verify': PREFIX + BIND + "print(json.dumps({'verified':True,'uid':os.geteuid(),'runtime':observed}))\n",
             'seed': PREFIX + "sys.path.insert(0,str(history));runtime=history\n" + seed +
                "\n(root/'membership-release-attempt.json').write_bytes(" + repr(previous.SYNTHETIC_MARKER) + ")\n" +
                "(root/'membership-release-attempt.json').chmod(0o600)\n",
             'migrate': PREFIX + BIND + """
assert migration.snapshot_baseline(root)['households']==2
clone_group(root,base/'partial')
begun=migration.begin(root,proof,**kwargs)
result=migration.migrate(root,proof,**kwargs)
assert begun['databases']==result['databases']==3 and result['households']==2
print(json.dumps(result))
""",
             'startup': PREFIX + BIND + startup,
             'check': PREFIX + BIND + "print(json.dumps(migration.check_stopped(root,proof,**kwargs)))\n",
             'rollback71': PREFIX + BIND + helper + """
receipt=data._read_json(proof/'backup.json')
destination=restore_group(proof/'backup-group',receipt['manifest'],'restored-old',RESTORE)
result=migration.verify_rollback(proof,destination)
assert result['databases']==3 and result['completeGroupRestored']
dump('rollback71-result.json',result);print(json.dumps(result))
""",
             'partial': PREFIX + BIND + helper + """
root=base/'partial';proof=allproof/'partial';proof.mkdir(mode=0o700)
migration.begin(root,proof,**kwargs)
names=sorted(n for n in data.enumerate_databases(root) if n!='platform.sqlite3')
assert len(names)==2 and names[0]=='household.sqlite3'
blocked=root/names[1];blocked.chmod(0o400)
try:
 assert os.geteuid()==10001 and not os.access(blocked,os.W_OK),'readonly failure fixture is not effective'
 try:migration.migrate(root,proof,**kwargs)
 except sqlite3.OperationalError as error:
  assert (error.sqlite_errorcode & 255) in (sqlite3.SQLITE_READONLY,sqlite3.SQLITE_CANTOPEN)
  failure=type(error).__name__
 else:raise AssertionError('readonly second household did not fail')
finally:blocked.chmod(0o600)
counts={n:len([t for t in data.migration._read(root/n)['rows'] if not t.startswith('sqlite_')]) for n in names}
assert list(counts.values())==[73,71]
assert (proof/'migration-attempt.json').exists() and not (proof/'migration-result.json').exists()
try:migration.migrate(root,proof,**kwargs)
except (data.ReleaseDataError,data.migration.MigrationCheckError,FileExistsError):pass
else:raise AssertionError('partial migration replay accepted')
receipt=data._read_json(proof/'backup.json')
destination=restore_group(proof/'backup-group',receipt['manifest'],'restored-partial',RESTORE)
result=migration.verify_rollback(proof,destination)
assert result['databases']==3 and result['completeGroupRestored']
dump('partial-result.json',dict(result,failedWith=failure,partialTableCounts=counts,replayRejected=True))
print(json.dumps(dict(result,partialTableCounts=counts,replayRejected=True)))
""",
             'populate73': PREFIX + BIND + """
before=current.snapshot_current(root)
for relative in before['databases']:
 if relative=='platform.sqlite3':continue
 with closing(sqlite3.connect(root/relative)) as con:
  con.executescript(POPULATE)
 checkpoint(root/relative)
reference=current.snapshot_current(root)
for relative,old in before['databases'].items():
 new=reference['databases'][relative]
 if relative=='platform.sqlite3':assert new==old
 else:
  assert all(new['tables'][n]==value for n,value in old['tables'].items() if n not in migration.NEW_TABLES)
  assert all(new['tables'][n]['count']==2 for n in migration.NEW_TABLES)
dump('populated-reference.json',reference)
print(json.dumps({'populated':True,'households':2,'rowsPerNewTable':2,'opaqueSyntheticBytesNotVideo':True}))
""",
             'restart': PREFIX + BIND + startup.replace('app-startup.json', 'app-restart-populated.json'),
             'restore73': PREFIX + BIND + helper + """
reference=data._read_json(proof/'populated-reference.json')
kept=current.verify_restore(reference,root,marker_sha256=kwargs['marker_sha256'])
closed=proof/'populated-backup';closed.mkdir(mode=0o700)
current.begin(root,closed,**kwargs);current.check_stopped(root,closed,**kwargs)
receipt=data._read_json(closed/'backup.json')
destination=restore_group(closed/'backup-group',receipt['manifest'],'restored-current',RESTORE)
result=current.verify_restore(reference,destination,marker_sha256=kwargs['marker_sha256'])
assert result['logicalSha256']==kept['logicalSha256'] and result['databases']==3
dump('restored73-result.json',result);print(json.dumps(result))
"""}
    for name, code in codes.items():
        if name in ('rollback71', 'partial', 'restore73'):
            codes[name] = code.replace('RESTORE)', repr(restored) + ')')
        if name == 'populate73': codes[name] = code.replace('POPULATE)', repr(dml(video, 'populate')) + ')')
        ast.parse(codes[name])
    return codes, {'historicalSeedMethod': 'real fixed historical Flask source with candidate image dependencies',
                   'restoreOriginalSha256': sha(original_restore.encode()), 'restoreExecutedSha256': sha(restored.encode()),
                   'restoreChanges': ['prepend import os', 'replace only /data root with explicit isolated destination'],
                   'sessionsPreservedForExactComparison': True, 'restoredServicesStarted': False}


def prepare(repo, commit, output_dir):
    repo=Path(repo).absolute();tree=policy.identity(repo,commit)
    tracked=policy.tracked_files(repo,commit);baseline=policy.tracked_files(repo,BASE)
    old=read_git_blobs(repo,BASE,sorted(baseline));candidate=read_git_blobs(repo,commit,sorted(tracked))
    need(sha(encoded(hashes(old)))==BASE_MAP_SHA and set(candidate)==baseline|ADDITIONS and
         all(candidate[n]==raw for n,raw in old.items()), 'outside frozen base plus three tools')
    need(all(policy.plain(repo/n)==raw for n,raw in candidate.items()), 'working source differs')
    names={n for n in candidate if (n.endswith('.py') and '/' not in n) or
           (n.startswith('deploy/') and n.endswith('.py'))} | FIXTURES | DOCS | {'Dockerfile','requirements.txt'}
    release={n:candidate[n] for n in names}
    history_names={n for n in policy.tracked_files(repo,HISTORY) if n.endswith('.py') and '/' not in n}
    historical=read_git_blobs(repo,HISTORY,sorted(history_names))
    codes,binding=programs(release,repo)
    runtime=set()
    for line in old['Dockerfile'].decode().splitlines():
        if line.startswith('COPY '):runtime.update(n for n in line.split()[1:-1] if n.endswith('.py') or n=='requirements.txt')
    files={**{'release/'+n:raw for n,raw in release.items()},**{'history/'+n:raw for n,raw in historical.items()},
           **{'programs/'+n+'.py':code.encode() for n,code in codes.items()}}
    target=Path(output_dir).absolute()
    need(not repo.is_relative_to(target),'output overlaps repository')
    target=build.new_output(target,repo);target.chmod(0o755)
    for name,raw in files.items():build.save(target/name,raw)
    manifest={'kind':'media-video-migration-linux-input-v1','sourceHead':commit,'tree':tree,'runtimeSourceHead':BASE,
              'historicalHead':HISTORY,'historyFiles':hashes(historical),'sourceFiles':hashes(release),
              'runtimeFiles':{n:sha(candidate[n]) for n in sorted(runtime)},'files':hashes(files),'stages':list(STAGES),
              'binding':binding,'syntheticMarkerSha256':sha(previous.SYNTHETIC_MARKER),'productionOperations':False}
    need(policy.identity(repo,commit)==tree and all(policy.plain(repo/n)==raw for n,raw in candidate.items()),'source changed')
    raw=encoded(manifest);policy.write_new(target/'input.json',raw)
    verify(target,sha(raw))
    return {'inputSha256':sha(raw),'sourceHead':commit,'files':len(files),'outputDir':str(target),'dockerExecuted':False}


def verify(bundle, input_sha256):
    bundle=policy.checked(Path(bundle).absolute(),True)
    raw=policy.plain(bundle/'input.json',2_000_000)
    need(sha(raw)==policy.checksum(input_sha256),'input manifest hash differs')
    meta=policy.json_value(raw)
    need(meta['kind']=='media-video-migration-linux-input-v1' and meta['runtimeSourceHead']==BASE and
         meta['historicalHead']==HISTORY and meta['productionOperations'] is False and meta['stages']==list(STAGES),
         'input policy differs')
    policy.hash_map(meta['files']);need(build.tree_hashes(bundle)==dict(meta['files'],**{'input.json':sha(raw)}),'input bytes differ')
    need(meta['files']['release/'+SELF]==sha(policy.plain(Path(__file__).absolute())),'executed runner differs')
    need({n.removeprefix('release/'):v for n,v in meta['files'].items() if n.startswith('release/')}==meta['sourceFiles'] and
         {n.removeprefix('history/'):v for n,v in meta['files'].items() if n.startswith('history/')}==meta['historyFiles'],
         'source partition differs')
    return bundle,meta


def container_args(image,bundle,output,stage,contract_sha):
    need(stage in STAGES,'unknown stage');build.image_id(image)
    args=['create','--network','none','--read-only','--user','10001:10001','--cap-drop','ALL',
          '--security-opt','no-new-privileges:true','--memory','384m','--memory-swap','384m','--cpus','1',
          '--pids-limit','128','--no-healthcheck','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=134217728,mode=1777',
          '--workdir','/','--entrypoint','python']
    for path,target,readonly in ((bundle/'release','/release',True),(bundle/'history','/history',True),
                                 (bundle/'programs','/programs',True),(output/'data','/data',False),(output/'proof','/proof',False)):
        need(not any(c in str(path) for c in (',','\n','\r')),'unsafe mount path')
        args+=['--mount',f'type=bind,src={path},dst={target}'+(',readonly' if readonly else '')]
    env={**previous.SYNTHETIC_ENV,'DATA_DIR':'/data/main','REHEARSAL_DATA':'/data','REHEARSAL_PROOF':'/proof',
         'REHEARSAL_RELEASE':'/release','REHEARSAL_HISTORY':'/history','REHEARSAL_RUNTIME':'/app',
         'REHEARSAL_CONTRACT_SHA256':policy.checksum(contract_sha),'MEDIA_VIDEO_SOCKET':''}
    for name,value in env.items():args+=['--env',name+'='+value]
    return args+[image,'-B','-I','/programs/'+stage+'.py']


def run(bundle,input_sha256,image_id,output_dir):
    need(sys.platform=='linux' and os.geteuid()==0 and sys.dont_write_bytecode and not sys.flags.optimize,
         'Linux root python -B without optimization required')
    need(not any(n.upper().startswith(('DOCKER_','COMPOSE_')) for n in os.environ),'ambient Docker selector')
    bundle,meta=verify(bundle,input_sha256);build.image_id(image_id)
    need(not bundle.is_relative_to(Path(output_dir).absolute()),'output overlaps input')
    output=build.new_output(output_dir,bundle)
    for name in ('data','proof','data/main','proof/main'):
        path=output/name;path.mkdir(mode=0o700);os.chown(path,10001,10001)
    contract={'inputSha256':input_sha256,'historyFiles':meta['historyFiles'],'syntheticMarkerSha256':meta['syntheticMarkerSha256'],
              'identity':{'head':meta['sourceHead'],'tree':meta['tree'],'imageId':image_id,
                          'sourceHashes':meta['sourceFiles'],'runtimeHashes':meta['runtimeFiles']}}
    raw=encoded(contract);policy.write_new(output/'proof/contract.json',raw);os.chown(output/'proof/contract.json',10001,10001)
    docker=build.Executor(output);result={'passed':False,'inputSha256':input_sha256,'imageId':image_id,'stages':{},
                                        'syntheticOnly':True,'productionAccess':False,**meta['binding']}
    try:
        build.inspect_image(docker,image_id)
        for name in STAGES:
            identifier=build.must(docker(container_args(image_id,bundle,output,name,sha(raw))),'container create failed').decode().strip()
            need(len(identifier)==64 and all(c in '0123456789abcdef' for c in identifier),'invalid container id')
            try:
                execution=docker(['start','--attach',identifier],timeout=360)
                value=policy.json_value(build.must(execution,'phase failed: '+name))
                if name=='verify':need(value.get('verified') is True and value.get('uid')==10001,'runtime verification failed')
                result['stages'][name]=value
            finally:build.must(docker(['rm','--force',identifier]),'owned container cleanup failed')
        need(len(result['stages'])==len(STAGES) and verify(bundle,input_sha256)[1]==meta,'incomplete or changed input')
        result['passed']=True
    except Exception as error:
        result['errorType']=type(error).__name__;result['error']=str(error)
    finally:
        result['completedAt']=datetime.now(timezone.utc).isoformat()
        result['proofHashes']=build.tree_hashes(output/'proof')
        result['commands']=docker.records
        policy.write_new(output/'result.json',encoded(result))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='action',required=True)
    for name,options in {'prepare':('repo','commit','output-dir'),'verify':('bundle','input-sha256'),
                         'run':('bundle','input-sha256','image-id','output-dir')}.items():
        sub=commands.add_parser(name)
        for option in options:sub.add_argument('--'+option,required=True)
    args=vars(parser.parse_args(argv));action=args.pop('action')
    result=({'prepare':prepare,'run':run}[action](**args) if action!='verify' else {'verified':bool(verify(**args))})
    print(json.dumps(result));return 1 if result.get('passed') is False else 0


if __name__=='__main__':raise SystemExit(main())
