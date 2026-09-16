"""Real 43 -> 44 Docker rehearsal using new labeled volumes and synthetic data.

No production path, Compose project, credentials or existing data volume is read.
Requires the reviewed places checker and legacy43 restore fixture in --source.
This proves migration/readback, not the production activation controller itself.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys


HERE = Path(__file__).resolve()
SELF = 'tests/rehearse_journey_places_migration.py'


def need(value, label):
    if not value:
        raise RuntimeError(label)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def frozen(root, manifest_sha, name='RELEASE-MANIFEST.json'):
    need(root.is_absolute() and root.resolve(strict=True) == root, 'source_path')
    # -B prevents writes, not reads of pre-existing import caches. Helpers on
    # the host and /rehearsal must therefore contain source bytes only.
    for path in root.rglob('*'):
        need(not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'source_link')
        need(path.suffix not in ('.pyc', '.pyo'), 'source_bytecode')
    manifest = root / name
    need(not manifest.is_symlink(), 'manifest_symlink')
    raw = manifest.read_bytes()
    need(re.fullmatch('[a-f0-9]{64}', manifest_sha) and sha(raw) == manifest_sha, 'manifest_changed')
    files = json.loads(raw)['files']
    need(isinstance(files, dict) and files, 'manifest_files')
    for name, digest in files.items():
        need(isinstance(name, str) and name and '\\' not in name and ':' not in name
             and not name.startswith('/') and all(p not in ('', '.', '..') for p in name.split('/')), 'source_name')
        path = root / name
        need(not path.is_symlink() and path.resolve(strict=True) == path
             and path.is_file() and sha(path.read_bytes()) == digest, 'source_changed')
    return files


def runtime(files):
    return {n: d for n, d in files.items() if n == 'requirements.txt' or n.startswith('static/')
            or '/' not in n and n.endswith('.py')}


PROBE = r'''
import hashlib,json,pathlib,sys
root=pathlib.Path('/app'); expected=json.loads(sys.argv[1])
actual={p.name for p in root.glob('*.py')}|{'requirements.txt'}
actual.update(p.relative_to(root).as_posix() for p in (root/'static').rglob('*') if p.is_file())
assert actual==set(expected)
assert sys.dont_write_bytecode and not sys.pycache_prefix
assert not any(p.suffix in ('.pyc','.pyo') for p in root.rglob('*'))
assert all(not (root/n).is_symlink() and hashlib.sha256((root/n).read_bytes()).hexdigest()==d for n,d in expected.items())
print('verified')
'''

# The checker is mounted from the reviewed source. Its schema literal is read
# from /app, whose exact runtime bytes are independently verified in both images.
CHECK = r'''
import hashlib,importlib.util,json,pathlib,sys
path=pathlib.Path('/rehearsal/deploy/check_journey_places_migration.py')
assert hashlib.sha256(path.read_bytes()).hexdigest()==sys.argv[2]
spec=importlib.util.spec_from_file_location('places_check',path)
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
M.SOURCE_ROOT=pathlib.Path('/app')
inputs=pathlib.Path('/proof/migration');inputs.mkdir(mode=0o700,exist_ok=True)
if sys.argv[1]=='definition':
 value=M.schema_definition()
else:
 value=M.run(sys.argv[1],pathlib.Path('/data'),inputs)
print(json.dumps(value,sort_keys=True))
'''

WRITE = r'''
import json,pathlib,sys
name=sys.argv[1]
assert name in ('schema.json','before.json','backup.json','backup-verification.json')
p=pathlib.Path('/proof/migration')/name;p.parent.mkdir(mode=0o700,exist_ok=True)
raw=sys.stdin.read();json.loads(raw)
with p.open('x',encoding='utf-8') as f:f.write(raw)
p.chmod(0o600)
print('saved')
'''

READBACK = r'''
import json,os,pathlib,sys
sys.path.insert(0,'/rehearsal/tests')
import restore_rehearsal_fixture as F
expected=json.loads(pathlib.Path('/proof/expected.json').read_bytes())
assert expected['runId']==os.environ['REHEARSAL_RUN_ID']
root=pathlib.Path('/data');houses=F.registry(root);assert len(houses)==2
before={h['id']:F.snapshot(F.database_path(root,h['id'])) for h in houses}
registry=F.snapshot(root/'platform.sqlite3');audit=F.Audit('places-migration');downloads=members=0
with F.only_loopback(audit):
 for h in expected['households']:
  for uid,member in h['members'].items():
   c=F.Client('http://127.0.0.1:8000',audit,member['cookies'])
   me=c.request('GET','/api/me');assert me['user']['id']==uid and me['user']['householdId']==h['id'];members+=1
   result=c.request('GET','/api/journey-places');assert result['items']==[] and result['total']==0
   for item in h['documents']:
    if item['metadata']['owner']!=uid:continue
    raw=c.request('GET','/api/journey-documents/'+item['metadata']['id']+'/file',raw=True)
    assert F.digest(raw)==item['sha256'];downloads+=1
  tv=F.Client('http://127.0.0.1:8000',audit,h['tv']['cookies'])
  tv.request('GET','/api/journey-places',status=403)
assert not audit.external and members==4 and downloads==8
assert F.snapshot(root/'platform.sqlite3')==registry
for h in houses:
 old,new=before[h['id']],F.snapshot(F.database_path(root,h['id']))
 assert old['schema']==new['schema'] and set(old['tables'])==set(new['tables'])
 for name,value in old['tables'].items():
  if name!='member_sessions':assert value==new['tables'][name];continue
  # Authenticated GET can update only the known last_seen_at timestamp.
  a,b=F.row_objects(value),F.row_objects(new['tables'][name]);assert len(a)==len(b)
  a={x['id']:x for x in a};b={x['id']:x for x in b};assert set(a)==set(b)
  for key,row in a.items():
   assert b[key]['last_seen_at']>=row['last_seen_at']
   assert {k:v for k,v in row.items() if k!='last_seen_at'}=={k:v for k,v in b[key].items() if k!='last_seen_at'}
print(json.dumps({'passed':True,'households':2,'householdTables':44,'retainedMembers':members,
 'documentDownloads':downloads,'tvRejected':2,'externalRequests':0,'businessDataPreserved':True,
 'authenticationChangeAllowed':'last_seen_at monotonic only'}))
'''


def run(args):
    need(os.name == 'posix', 'linux_required')
    need(not any(k.upper().startswith(('DOCKER_', 'COMPOSE_')) for k in os.environ), 'host_selector')
    need(sys.dont_write_bytecode and sys.pycache_prefix is None, 'host_bytecode')
    root = args.source
    files = frozen(root, args.manifest_sha)
    need(files.get(SELF) == sha(HERE.read_bytes()), 'runner_source_mismatch')
    base = json.loads((root / 'BASE-MANIFEST.json').read_bytes())
    need(sha((root / 'BASE-MANIFEST.json').read_bytes()) == args.base_manifest_sha, 'base_manifest')
    need(set(runtime(files)) - set(runtime(base['files'])) == {'journey_places.py'}, 'runtime_delta')
    need(all(re.fullmatch(r'sha256:[a-f0-9]{64}', i) for i in (args.parent, args.image))
         and args.parent != args.image, 'immutable_images')
    need(args.output.is_absolute() and args.output.parent.resolve(strict=True) == args.output.parent
         and not args.output.exists() and not args.output.is_symlink()
         and not args.output.is_relative_to(root) and not root.is_relative_to(args.output), 'new_output_required')
    need({'deploy/rehearse_restore.py','deploy/check_journey_places_migration.py','deploy/backup.py',
          'tests/restore_rehearsal_fixture.py'} <= set(files), 'missing_dependencies')
    spec = importlib.util.spec_from_file_location('restore_harness', root / 'deploy/rehearse_restore.py')
    R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
    harness = R.Rehearsal(root, args.parent, args.output, profile='legacy43')
    harness.env.update(NVIDIA_API_KEY='', NVIDIA_MODEL='')
    harness.report.update(scope='real Docker synthetic 43-to-44 migration only', productionWrites=0,
        sourceHashes=files, manifestSha256=args.manifest_sha, baseManifestSha256=args.base_manifest_sha,
        parentImage=args.parent, image=args.image, realDocker=True)
    try:
        args.output.mkdir(mode=0o700, parents=False, exist_ok=False); harness.output_created = True
        for image, expected in ((args.parent, runtime(base['files'])), (args.image, runtime(files))):
            harness.image = image
            info = harness.inspect('image', image)
            harness.check('immutable_linux_' + ('parent' if image == args.parent else 'child'), info['Id'] == image and info['Os'] == 'linux')
            harness.ephemeral(['python', '-c', PROBE, json.dumps(expected)])
        harness.image = args.parent
        source, proof = harness.volume('source'), harness.volume('proof')
        app = harness.start_app(source, proof); harness.fixture(app, 'seed')
        harness.require_owned('container', app); harness.docker(['stop', '--time', '20', app], timeout=40)
        state = harness.require_owned('container', app)['State']
        harness.check('parent_clean_stop', not state['Running'] and not state['OOMKilled'] and state['ExitCode'] == 0)
        harness.check('no_writers', not harness.docker(['ps', '-q', '--filter', 'volume=' + source]).stdout.strip())
        harness.image = args.image
        mounts = [(source, '/data', False), (proof, '/proof', False)]
        def execute(action):
            frozen(root, args.manifest_sha); harness.phase = action
            result = harness.ephemeral(['python', '-c', CHECK, action, files['deploy/check_journey_places_migration.py']], mounts)
            return json.loads(result.stdout.strip().splitlines()[-1])
        def save(name, value):
            harness.ephemeral(['python', '-c', WRITE, name], [(proof, '/proof', False)], data=json.dumps(value))
        definition = execute('definition'); save('schema.json', definition)
        harness.report['schemaSha256'] = definition['sha256']
        before = execute('snapshot'); save('before.json', before)
        harness.check('two_old_households', len(before['households']) == 2)
        result = harness.ephemeral(['python', '/rehearsal/deploy/backup.py'], [(source, '/data', False)])
        backup = json.loads(result.stdout.strip().splitlines()[-1]); save('backup.json', backup)
        verified = execute('validate-backup'); save('backup-verification.json', verified)
        harness.check('three_backup_databases', verified['databases'] == 3 and verified['groupVerified'])
        harness.report['migration'] = execute('warm')
        harness.report['beforeStartup'] = execute('check')
        child = harness.start_app(source, proof)
        harness.report['afterStartup'] = execute('check')
        for result in (harness.report['migration'], harness.report['beforeStartup'], harness.report['afterStartup']):
            harness.check('all_original_tables_and_empty_addition', result['originalTablesPreserved'] == 43
                and result['newTables'] == 1 and result['newTableEmpty'] and result['households'] == 2
                and result['allOriginalRowsAndSequencesPreserved'] and result['backup'] == verified)
        result = harness.docker(['exec', child, 'python', '-c', READBACK], timeout=180)
        harness.report['authenticatedReadback'] = json.loads(result.stdout.strip().splitlines()[-1])
        harness.check('retained_auth_and_files', harness.report['authenticatedReadback'].get('passed') is True)
        frozen(root, args.manifest_sha)
        harness.report.update(passed=True, households=2, originalTablesPreserved=43, newTables=1,
                              newTableEmpty=True, restorePerformed=False, controllerActivationPerformed=False)
    except BaseException as error:
        harness.report.update(passed=False, failure={'phase':harness.phase,'errorType':type(error).__name__})
    finally:
        harness.cleanup()
    harness.report['completedAt'] = datetime.now(timezone.utc).isoformat()
    if harness.output_created:
        path = args.output / ('migration-' + harness.run_id + '.json')
        with path.open('x', encoding='utf-8') as f: json.dump(harness.report, f, ensure_ascii=False, indent=2)
        path.chmod(0o600)
    print(json.dumps({'passed':harness.report['passed'], 'runId':harness.run_id, 'output':str(args.output)}))
    return 0 if harness.report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','output'): parser.add_argument('--'+name, type=Path, required=True)
    for name in ('parent','image','manifest-sha','base-manifest-sha'): parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    def interrupted(*_): raise RuntimeError('rehearsal_interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, interrupted)
    raise SystemExit(run(args))


if __name__ == '__main__':
    main()
