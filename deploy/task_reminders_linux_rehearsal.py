"""Isolated synthetic 69/9 -> 71/9 Linux migration, restart and group restore.

Run with python -B and a reviewed immutable candidate. Never mounts production.
Restores preserve sessions for exact database comparison; restored services are
never started. This is not the complete production recovery procedure.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_task_reminders_release as profile
from deploy import membership_release_package as policy
from deploy import membership_release_build as build
from deploy import steady_linux_rehearsal as previous
from deploy import journey_routes_linux_rehearsal as routes
from deploy import rehearse_restore as restore

SELF = 'deploy/task_reminders_linux_rehearsal.py'
need, sha, encoded = policy.need, policy.digest, policy.encoded
FINANCE_TABLES = routes.FINANCE_TABLES
ROUTE_COUNTS = {'journey_routes': 2, 'journey_route_stops': 1, 'journey_route_operations': 2}

# Create real state and idempotent receipts via local authenticated Flask APIs.
# Only after strict app-only preservation has succeeded may this phase write
# tasks, session/audit rows and reminder state. It never ticks a worker.
POPULATE_REMINDERS = '''
from contextlib import closing
from datetime import datetime,timedelta
import socket,sqlite3
def no_network(*args,**kwargs):raise RuntimeError('populate_network_forbidden')
socket.socket.connect=no_network
import app
assert Path(app.__file__).resolve()==Path('/app/app.py')
application=app.create_app()
platform=application.extensions['household_platform']
origin=os.environ['PUBLIC_ORIGIN']
receipts={}
def request(client,method,path,**kwargs):return client.open(path,method=method,base_url=origin,**kwargs)
for household in platform.households():
 child=platform.child(household)
 client=child.test_client()
 password=os.environ['MEMBER1_PASSWORD'] if household['id']=='default' else 'synthetic-child-password-one'
 login=request(client,'POST','/api/login',json={'username':'member1','password':password},headers={'Origin':origin})
 assert login.status_code==200,login.status_code
 me=request(client,'GET','/api/me');assert me.status_code==200
 headers={'X-CSRF-Token':me.json['csrf'],'Origin':origin}
 saved=[]
 for index,action in enumerate(('read','snooze')):
  created=request(client,'POST','/api/items/tasks',json={'title':'Synthetic reminder '+action,
   'owner':'member1' if action=='read' else 'shared','due':'2000-01-01','sourceId':''},headers=headers)
  assert created.status_code==201,created.status_code
  task_id=created.json['id']
  page=request(client,'GET','/api/task-reminders?filter=all&page=0');assert page.status_code==200
  entry=next(value for value in page.json['items'] if value['task']['id']==task_id)
  assert entry['status']=='unread' and entry['revision']==0
  intent={'requestId':('a' if index==0 else 'b')*32,'occurrence':entry['occurrence'],
   'revision':entry['revision'],'action':action}
  if action=='snooze':intent['snoozedUntil']=(datetime.fromisoformat(page.json['serverNow'])+timedelta(hours=1)).isoformat()
  response=request(client,'POST','/api/task-reminders/'+task_id+'/actions',json=intent,headers=headers)
  assert response.status_code==200,response.status_code
  operation=response.json['operation']
  assert operation['action']==action and operation['taskId']==task_id and operation['revision']==1
  assert bool(operation['readAt'])==(action=='read') and bool(operation['snoozedUntil'])==(action=='snooze')
  recovered=request(client,'GET','/api/task-reminders/operations/'+intent['requestId'])
  assert recovered.status_code==200 and recovered.json==response.json
  replay=request(client,'POST','/api/task-reminders/'+task_id+'/actions',json=intent,headers=headers)
  assert replay.status_code==200 and replay.json==response.json
  saved.append(operation)
 page=request(client,'GET','/api/task-reminders?filter=all&page=0');assert page.status_code==200
 assert {x['status'] for x in page.json['items']}=={'read','snoozed'}
 assert page.json['worker']['lastCheckedAt'] is None
 relative='household.sqlite3' if household['id']=='default' else 'spaces/'+household['id']+'/household.sqlite3'
 with closing(sqlite3.connect(data._relative(root,relative))) as con:
  assert con.execute("SELECT count(*) FROM settings WHERE id='task-reminders-worker'").fetchone()[0]==0
  assert con.execute('SELECT count(*) FROM task_reminders').fetchone()[0]==2
  assert con.execute('SELECT count(*) FROM task_reminder_operations').fetchone()[0]==2
  assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
 receipts[relative]=saved
with closing(sqlite3.connect(root/'platform.sqlite3')) as con:
 assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
reference=current.snapshot_current(root)
before=data._read_json(proof/'after.json')
assert reference['households']==2 and len(reference['databases'])==3 and len(receipts)==2
for relative,value in reference['databases'].items():
 if relative!='platform.sqlite3':
  assert all(value['tables'][n]['count']==2 for n in current.NEW_TABLES)
  for table in ('settings','finance_account_profiles','finance_account_cashflows','finance_account_reviews',
   'finance_analysis_operations','finance_fx_rates','journey_routes','journey_route_stops','journey_route_operations'):
   assert value['tables'][table]==before['databases'][relative]['tables'][table]
data._write_new(proof/'populated-reference.json',reference)
data._write_new(proof/'populated-api-receipts.json',receipts)
print(json.dumps({'populated':True,'households':2,'statesPerHousehold':2,'receiptsPerHousehold':2,
 'actions':['read','snooze'],'seedMethod':'real local authenticated Flask task/reminder APIs; same-intent replay checked',
 'workerStarted':False}))
'''


def candidate_input(candidate, package_sha256):
    candidate = policy.checked(Path(candidate).absolute(), True)
    verified = profile.verify_package(candidate / 'package', package_sha256)
    source = policy.checked(candidate / 'source', True)
    modules = ((SELF, __file__), ('deploy/build_task_reminders_release.py', profile.__file__),
               ('deploy/membership_release_package.py', policy.__file__),
               ('deploy/membership_release_build.py', build.__file__),
               ('deploy/steady_linux_rehearsal.py', previous.__file__),
               ('deploy/journey_routes_linux_rehearsal.py', routes.__file__),
               ('deploy/rehearse_restore.py', restore.__file__))
    for name, filename in modules:
        need(verified['blobs'].get(name) == policy.plain(Path(filename).absolute()),
             'executed helper differs: ' + name)
    need(build.tree_hashes(source) == {**verified['manifest']['files'],
         'RELEASE-MANIFEST.json': verified['metadata']['manifestSha256']}, 'candidate source differs')
    need(verified['metadata']['parentImage'] == profile.PARENT_IMAGE and
         verified['metadata']['oldManifestSha256'] == profile.OLD_MANIFEST, 'baseline differs')
    return candidate, source, verified


def programs(blobs, documented_restore):
    """Reuse fixed route lifecycle/restore code, adapting only explicit anchors."""
    code, binding = routes.programs(blobs, documented_restore)
    old = 'from deploy import check_journey_routes_migration as current'
    expected = {'BEGIN', 'MIGRATE', 'CHECK', 'POPULATE', 'POPULATED_CHECK',
                'POPULATED_BACKUP', 'RESTORE_OLD', 'RESTORE_CURRENT'}
    need({name for name, value in code.items() if old in value} == expected, 'migration binding layout changed')
    for name in expected:
        code[name] = routes.replace_once(code[name], old,
                                        'from deploy import check_task_reminders_migration as current')
    seed = routes.replace_once(code['SEED'], 'len(tables)==66', 'len(tables)==69')
    seed = routes.replace_once(seed, "'householdTables':66", "'householdTables':69")
    # Use the existing route sentinel DML verbatim; never copy runtime DDL.
    calls = [node for node in ast.walk(ast.parse(routes.POPULATE_ROUTES))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == 'executescript']
    need(len(calls) == 1 and len(calls[0].args) == 1, 'route sentinel layout changed')
    route_sql = ast.literal_eval(calls[0].args[0])
    need(isinstance(route_sql, str) and 'CREATE ' not in route_sql.upper(), 'route sentinel DDL forbidden')
    anchor = "  con.commit();assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0"
    code['SEED'] = routes.replace_once(seed, anchor, '  con.executescript(' + repr(route_sql) + ')\n' + anchor)
    controller = blobs['deploy/membership_release_controller.py']
    prefix = previous.literal(controller, 'DATA_PREFIX')
    code['POPULATE'] = prefix + ("\nfrom deploy import check_task_reminders_migration as current\n"
                                "contract=json.loads((proof/'rehearsal-contract.json').read_bytes())\n") + POPULATE_REMINDERS
    for value in code.values():
        ast.parse(value)
    return code, binding


def check_group(proof):
    load = lambda name: policy.json_value(policy.plain(proof / name))
    before, migrated, after = (load(name) for name in ('before.json', 'migrated.json', 'after.json'))
    need(before['households'] == migrated['households'] == after['households'] == 2 and
         before['databases'].keys() == migrated['databases'].keys() == after['databases'].keys()
         and len(after['databases']) == 3, 'group differs')
    for name, old in before['databases'].items():
        new = after['databases'][name]
        count = lambda item: len([n for n in item['tables'] if not n.startswith('sqlite_')])
        need(count(old) == (9 if name == 'platform.sqlite3' else 69) and
             count(new) == (9 if name == 'platform.sqlite3' else 71), 'table counts differ')
        if name != 'platform.sqlite3':
            need(all(old['tables'][n]['count'] == new['tables'][n]['count'] == 1 for n in FINANCE_TABLES),
                 'populated analysis rows missing')
            need(all(old['tables'][n]['count'] == new['tables'][n]['count'] == total
                     for n, total in ROUTE_COUNTS.items()), 'populated route rows missing')
            need(all(new['tables'][n]['count'] == 0 for n in ('task_reminders', 'task_reminder_operations')),
                 'app-only reminder tables not empty')
    result = load('result.json')
    need(result['verified'] is True and result['markerSha256'] == sha(previous.SYNTHETIC_MARKER), 'stopped check differs')
    return {'verified': True, 'households': 2, 'databases': 3, 'householdTables': [69, 71],
            'platformTables': [9, 9], 'preservedPopulatedFinanceTablesPerHousehold': 5,
            'preservedRouteRowsPerHousehold': ROUTE_COUNTS, 'newReminderTablesEmpty': True,
            'logicalSha256': result['logicalSha256']}


def rehearse(candidate, package_sha256, image_id, output_dir):
    need(sys.platform == 'linux' and os.geteuid() == 0 and sys.dont_write_bytecode and
         not sys.flags.optimize and sys.pycache_prefix is None, 'Linux root python -B without optimization required')
    need(not any(n.upper().startswith(('DOCKER_', 'COMPOSE_')) for n in os.environ), 'ambient Docker selector')
    candidate, source, verified = candidate_input(candidate, package_sha256)
    meta = verified['metadata']
    code, restore_binding = programs(verified['blobs'], restore.documented_programs(source)[0])
    output = Path(output_dir).absolute()
    need(not candidate.is_relative_to(output), 'output overlaps candidate')
    output = build.new_output(output, candidate)
    for name in ('data', 'proof'):
        path = output / name; path.mkdir(mode=0o700); os.chown(path, 10001, 10001)
    identity = {'head': meta['sourceHead'], 'tree': meta['tree'], 'imageId': build.image_id(image_id),
                'sourceHashes': verified['manifest']['files'], 'runtimeHashes': meta['runtimeFiles']}
    contract = {'kind': 'task-reminders-synthetic-linux-rehearsal', 'packageSha256': package_sha256,
                'manifestSha256': meta['manifestSha256'], 'identity': identity, 'parentImage': profile.PARENT_IMAGE,
                'syntheticMarkerSha256': sha(previous.SYNTHETIC_MARKER), 'syntheticMarkerOverride': True,
                'exactProductionControllerProgram': False, 'runnerSha256': sha(Path(__file__).read_bytes()),
                'programHashes': {name: sha(value.encode()) for name, value in code.items()},
                'restoreProgram': restore_binding, 'restoreScope': 'Isolated database-content restore only; sessions preserved for exact comparison; restored services never started.'}
    for name, value in (('identity.json', identity), ('rehearsal-contract.json', contract)):
        path = output / 'proof' / name; policy.write_new(path, encoded(value)); os.chown(path, 10001, 10001)
    docker = build.Executor(output)
    record = {'passed': False, 'steps': [], **contract, 'rehearsalContractSha256': sha(encoded(contract)),
              'sourceHead': meta['sourceHead'], 'tree': meta['tree'], 'imageId': image_id,
              'syntheticOnly': True, 'productionAccess': False}
    try:
        parent, child = (build.inspect_image(docker, image) for image in (profile.PARENT_IMAGE, image_id))
        layers = parent['RootFS']['Layers']
        need(child['RootFS']['Layers'][:-2] == layers and len(child['RootFS']['Layers']) == len(layers) + 2, 'image parent/layers differ')
        config = lambda value: {k: v for k, v in value['Config'].items() if k != 'Image'}
        need(config(parent) == config(child), 'image configuration differs')
        phase = lambda name, **options: previous.phase(docker, profile.PARENT_IMAGE if name == 'SEED' else image_id,
                                                      code[name], source, output, **options)
        need(phase('RUNTIME') == meta['runtimeFiles'], 'candidate runtime differs')
        record['steps'].append('candidate_runtime_and_fixed_parent_verified')
        need(phase('SEED', write=True, seed=True) == {'seeded': True, 'households': 2, 'databases': 3,
             'householdTables': 69, 'platformTables': 9}, 'seed scope differs')
        record['steps'].append('old_image_created_two_populated_synthetic_households_69_9')
        before = phase('BEGIN', write=True)
        need(before.get('verified') is True, 'backup incomplete')
        record['steps'].append('complete_stopped_three_database_backup_verified')
        migrated = phase('MIGRATE', write=True)
        need(migrated.get('verified') is True, 'migration incomplete')
        record['steps'].append('exact_two_table_migration_completed_for_both_households')
        started = phase('STARTUP', write=True)
        need(started.get('initialized') is True and started.get('households') == 2, 'startup incomplete')
        after = phase('CHECK')
        need(after.get('verified') is True and after['logicalSha256'] == migrated['logicalSha256'], 'post_startup drift')
        record['migration'] = check_group(output / 'proof')
        record['steps'].append('actual_app_startup_preserved_69_old_tables_platform_and_marker')
        rollback = phase('RESTORE_OLD')
        need(rollback.get('completeGroupRestored') is True and rollback.get('databases') == 3, 'old group rollback incomplete')
        record['rollback'] = rollback
        record['steps'].append('retained_69_9_backup_restored_to_new_isolated_directory')
        populated = phase('POPULATE', write=True)
        need(populated.get('populated') is True and populated.get('households') == 2
             and populated.get('statesPerHousehold') == populated.get('receiptsPerHousehold') == 2
             and populated.get('workerStarted') is False, 'reminder API seed incomplete')
        restarted = phase('RESTART', write=True)
        need(restarted.get('initialized') is True and restarted.get('households') == 2, 'populated restart incomplete')
        kept = phase('POPULATED_CHECK')
        need(kept.get('completeGroupRestored') is True, 'populated restart drift')
        record['steps'].append('nonempty_reminder_states_and_receipts_preserved_on_real_restart')
        backup = phase('POPULATED_BACKUP', write=True)
        need(backup.get('databases') == 3, 'populated backup incomplete')
        restored = phase('RESTORE_CURRENT')
        need(restored.get('completeGroupRestored') is True and restored.get('databases') == 3
             and restored.get('logicalSha256') == kept['logicalSha256'], 'populated restore drift')
        record.update(populated=populated, restart=kept, restore=restored)
        record['steps'].append('populated_71_9_complete_backup_restored_with_receipts_and_marker')
        need(candidate_input(candidate, package_sha256)[2] == verified, 'candidate changed during rehearsal')
        record['passed'] = True
    except Exception as error:
        record['error'] = str(error)
    finally:
        record['completedAt'] = datetime.now(timezone.utc).isoformat()
        record['evidence'] = {'proof/' + n: digest for n, digest in build.tree_hashes(output / 'proof').items()}
        record['commands'] = len(docker.records)
        policy.write_new(output / 'result.json', encoded(record))
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'package-sha256', 'image-id', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    result = rehearse(**vars(parser.parse_args(argv)))
    print(json.dumps({'passed': result['passed'], 'steps': result['steps'], 'error': result.get('error')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
