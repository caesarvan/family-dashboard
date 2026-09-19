"""Isolated synthetic 66/9 -> 69/9 Linux migration, restart and database restore.

Run with python -B and --candidate/--package-sha256/--image-id/--output-dir.
Uses the fixed old image and a new output directory; never mounts production.
The marker is synthetic. Restores preserve sessions for comparison and never
start restored services: this is not the complete production recovery procedure.
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
from deploy import build_journey_routes_release as profile
from deploy import membership_release_package as policy
from deploy import membership_release_build as build
from deploy import steady_linux_rehearsal as previous
from deploy import rehearse_restore as restore

SELF = 'deploy/journey_routes_linux_rehearsal.py'
need, sha, encoded = policy.need, policy.digest, policy.encoded
FINANCE_TABLES = ('finance_account_profiles', 'finance_account_cashflows',
                  'finance_account_reviews', 'finance_analysis_operations', 'finance_fx_rates')

# Same explicit synthetic rows as the preceding 66/9 rehearsal; no DDL copy.
POPULATE_FINANCE = '''
  con.executescript("""
    PRAGMA foreign_keys=ON;
    INSERT INTO finance_accounts VALUES('synthetic-account','member1','Synthetic','Synthetic',
      'asset','CNY','',0,1,'2026-09-19','2026-09-19');
    INSERT INTO finance_account_profiles VALUES('member1','synthetic-account','cash','immediate',1,'now');
    INSERT INTO finance_account_cashflows VALUES('synthetic-flow','member1','synthetic-account',
      '2026-09-18','in',12345,'synthetic',1,'now','now');
    INSERT INTO finance_account_reviews VALUES('member1','synthetic-account','2026-09-01',
      '2026-09-18','digest',1,'now');
    INSERT INTO finance_analysis_operations VALUES('member1','synthetic-request','digest',
      'cashflow','synthetic-account','{}','now');
    INSERT INTO finance_fx_rates VALUES('synthetic-version','2026-09-18','USD','1.2',
      'https://example.invalid/synthetic','digest','now','now');
  """)
'''

POPULATE_ROUTES = '''
from contextlib import closing
import sqlite3
before=current.snapshot_current(root)
for relative in before['databases']:
 if relative=='platform.sqlite3':continue
 with closing(sqlite3.connect(data._relative(root,relative))) as con:
  con.executescript("""
   PRAGMA foreign_keys=ON;
   INSERT INTO journey_routes VALUES('aaaaaaaaaaaaaaaaaaaaaaaa','member1','Synthetic',NULL,'private',2,'now','now',NULL);
   INSERT INTO journey_route_stops VALUES('aaaaaaaaaaaaaaaaaaaaaaaa',0,NULL);
   INSERT INTO journey_routes VALUES('bbbbbbbbbbbbbbbbbbbbbbbb','member1','Synthetic deleted',NULL,'private',3,'now','now','now');
   INSERT INTO journey_route_operations VALUES('member1','synthetic-create','digest','create','aaaaaaaaaaaaaaaaaaaaaaaa',1,'now');
   INSERT INTO journey_route_operations VALUES('member1','synthetic-delete','digest','delete','bbbbbbbbbbbbbbbbbbbbbbbb',3,'now');
  """)
  assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()==[(0,0,0)]
  assert con.execute('SELECT count(*) FROM journey_routes WHERE deleted_at IS NOT NULL').fetchone()[0]==1
reference=current.snapshot_current(root)
for relative,value in reference['databases'].items():
 if relative!='platform.sqlite3':
  assert {n:value['tables'][n]['count'] for n in current.NEW_TABLES}=={
   'journey_routes':2,'journey_route_stops':1,'journey_route_operations':2}
data._write_new(proof/'populated-reference.json',reference)
print(json.dumps({'populated':True,'households':reference['households'],'routeRowsPerHousehold':2,
 'softDeletedRowsPerHousehold':1,'stopRowsPerHousehold':1,'operationRowsPerHousehold':2,
 'seedMethod':'explicit synthetic SQL; verifies preservation, not API receipt replay'}))
'''

RESTORE_GROUP = '''
from contextlib import redirect_stdout
import io
def restore_group(backup_root,manifest_name,target_name,program):
 assert target_name in ('restored-old','restored-current')
 destination=proof/target_name
 destination.mkdir(mode=0o700,exist_ok=False)
 manifest=data._read_json(data._relative(backup_root,'backups/'+manifest_name))
 for relative in ['backups/'+manifest_name,*[x['path'] for x in manifest['snapshots']]]:
  original=data._relative(backup_root,relative)
  target=destination/relative
  assert target.is_relative_to(destination)
  target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  with target.open('xb') as stream:stream.write(original.read_bytes())
  target.chmod(0o600)
 captured=io.StringIO()
 sys.argv=['documented-restore',manifest_name,'platform','default']
 with redirect_stdout(captured):exec(compile(program,'<documented-synthetic-restore>','exec'),{'__name__':'__main__'})
 with (proof/(target_name+'-instructions.stdout')).open('x') as stream:stream.write(captured.getvalue())
 marker=(root/data.ROOT_ATTEMPT).read_bytes()
 assert hashlib.sha256(marker).hexdigest()==contract['syntheticMarkerSha256']
 with (destination/data.ROOT_ATTEMPT).open('xb') as stream:stream.write(marker)
 (destination/data.ROOT_ATTEMPT).chmod(0o600)
 return destination
'''


def replace_once(value, old, new):
    need(value.count(old) == 1, 'reviewed program anchor changed: ' + old)
    return value.replace(old, new, 1)


def candidate_input(candidate, package_sha256):
    candidate = policy.checked(Path(candidate).absolute(), True)
    verified = profile.verify_package(candidate / 'package', package_sha256)
    source = policy.checked(candidate / 'source', True)
    modules = ((SELF, __file__), ('deploy/build_journey_routes_release.py', profile.__file__),
               ('deploy/membership_release_package.py', policy.__file__),
               ('deploy/membership_release_build.py', build.__file__),
               ('deploy/steady_linux_rehearsal.py', previous.__file__),
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
    """Build auditable fixed programs; no caller-supplied code or restore target."""
    controller = blobs['deploy/membership_release_controller.py']
    prefix = previous.literal(controller, 'DATA_PREFIX')
    binding = ("\nfrom deploy import check_journey_routes_migration as current\n"
               "contract=json.loads((proof/'rehearsal-contract.json').read_bytes())\n")
    call = ("(root,proof,source_identity=identity,plan_sha256="
            "hashlib.sha256((proof/'rehearsal-contract.json').read_bytes()).hexdigest(),"
            "marker_sha256=" + repr(sha(previous.SYNTHETIC_MARKER)) + ")")
    seed = replace_once(previous.SEED_PROGRAM, 'len(tables)==61', 'len(tables)==66')
    seed = replace_once(seed, "'householdTables':61", "'householdTables':66")
    anchor = "  con.commit();assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0"
    seed = replace_once(seed, anchor, POPULATE_FINANCE + anchor)
    seed = "from pathlib import Path\nroot=Path('/data');proof=Path('/proof');runtime=Path('/app')\n" + seed
    seed += "\nwith (root/'membership-release-attempt.json').open('xb') as stream:stream.write(" + repr(previous.SYNTHETIC_MARKER) + ")\n(root/'membership-release-attempt.json').chmod(0o600)\n"
    restored = {name: replace_once(documented_restore, "root = Path('/data').resolve(strict=True)",
                "root = Path('/proof/" + name + "').resolve(strict=True)")
                for name in ('restored-old', 'restored-current')}
    code = {'RUNTIME': previous.literal(controller, 'RUNTIME_PROGRAM'), 'SEED': seed,
            'BEGIN': prefix + binding + 'print(json.dumps(current.begin' + call + '))',
            'MIGRATE': prefix + binding + 'print(json.dumps(current.migrate' + call + '))',
            'STARTUP': prefix + previous.STARTUP_PROGRAM,
            'CHECK': prefix + binding + 'print(json.dumps(current.check_stopped' + call + '))',
            'POPULATE': prefix + binding + POPULATE_ROUTES,
            'RESTART': prefix + previous.STARTUP_PROGRAM.replace('app-startup.json', 'app-restart-populated.json'),
            'POPULATED_CHECK': prefix + binding + """
reference=data._read_json(proof/'populated-reference.json')
result=current.verify_restore(reference,root,marker_sha256=contract['syntheticMarkerSha256'])
data._write_new(proof/'populated-restart-result.json',result)
print(json.dumps(result))
""",
            'POPULATED_BACKUP': prefix + binding + """
from deploy.backup import backup_all
reference=data._read_json(proof/'populated-reference.json')
assert current.verify_restore(reference,root,marker_sha256=contract['syntheticMarkerSha256'])['verified']
receipt=backup_all(root)
data._write_new(proof/'populated-backup.json',receipt)
print(json.dumps(receipt))
""",
            'RESTORE_OLD': prefix + binding + RESTORE_GROUP + "\n" +
                "receipt=data._read_json(proof/'backup.json')\n" +
                "destination=restore_group(proof/'backup-group',receipt['manifest'],'restored-old'," + repr(restored['restored-old']) + ")\n" +
                "result=current.verify_rollback(proof,destination)\ndata._write_new(proof/'rollback-result.json',result)\nprint(json.dumps(result))",
            'RESTORE_CURRENT': prefix + binding + RESTORE_GROUP + "\n" +
                "receipt=data._read_json(proof/'populated-backup.json')\n" +
                "destination=restore_group(root,receipt['manifest'],'restored-current'," + repr(restored['restored-current']) + ")\n" +
                "reference=data._read_json(proof/'populated-reference.json')\n" +
                "result=current.verify_restore(reference,destination,marker_sha256=contract['syntheticMarkerSha256'])\n" +
                "data._write_new(proof/'restore-current-result.json',result)\nprint(json.dumps(result))",
    }
    # Two explicit proof filenames in the immutable startup helper, not one.
    need(previous.STARTUP_PROGRAM.count('app-startup.json') == 2, 'startup proof layout changed')
    for value in code.values():
        ast.parse(value)
    return code, {'originalSha256': sha(documented_restore.encode()),
                  'targetRootMappings': {"/data": ['/proof/restored-old', '/proof/restored-current']},
                  'executedSha256': {name: sha(value.encode()) for name, value in restored.items()}}


def check_group(proof):
    load = lambda name: policy.json_value(policy.plain(proof / name))
    before, migrated, after = (load(name) for name in ('before.json', 'migrated.json', 'after.json'))
    need(before['households'] == migrated['households'] == after['households'] == 2 and
         before['databases'].keys() == migrated['databases'].keys() == after['databases'].keys()
         and len(after['databases']) == 3, 'group differs')
    for name, old in before['databases'].items():
        new = after['databases'][name]
        count = lambda item: len([n for n in item['tables'] if not n.startswith('sqlite_')])
        need(count(old) == (9 if name == 'platform.sqlite3' else 66) and
             count(new) == (9 if name == 'platform.sqlite3' else 69), 'table counts differ')
        if name != 'platform.sqlite3':
            need(all(old['tables'][n]['count'] == new['tables'][n]['count'] == 1 for n in FINANCE_TABLES),
                 'populated analysis rows missing')
    result = load('result.json')
    need(result['verified'] is True and result['markerSha256'] == sha(previous.SYNTHETIC_MARKER), 'stopped check differs')
    return {'verified': True, 'households': 2, 'databases': 3, 'householdTables': [66, 69],
            'platformTables': [9, 9], 'preservedPopulatedFinanceTablesPerHousehold': 5,
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
    contract = {'kind': 'journey-routes-synthetic-linux-rehearsal', 'packageSha256': package_sha256,
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
             'householdTables': 66, 'platformTables': 9}, 'seed scope differs')
        record['steps'].append('old_image_created_two_populated_synthetic_households_66_9')
        before = phase('BEGIN', write=True)
        need(before.get('verified') is True, 'backup incomplete')
        record['steps'].append('complete_stopped_three_database_backup_verified')
        migrated = phase('MIGRATE', write=True)
        need(migrated.get('verified') is True, 'migration incomplete')
        record['steps'].append('exact_three_table_migration_completed_for_both_households')
        started = phase('STARTUP', write=True)
        need(started.get('initialized') is True and started.get('households') == 2, 'startup incomplete')
        after = phase('CHECK')
        need(after.get('verified') is True and after['logicalSha256'] == migrated['logicalSha256'], 'post_startup drift')
        record['migration'] = check_group(output / 'proof')
        record['steps'].append('actual_app_startup_preserved_66_old_tables_platform_and_marker')
        rollback = phase('RESTORE_OLD')
        need(rollback.get('completeGroupRestored') is True and rollback.get('databases') == 3, 'old group rollback incomplete')
        record['rollback'] = rollback
        record['steps'].append('retained_66_9_backup_restored_to_new_isolated_directory')
        populated = phase('POPULATE', write=True)
        need(populated.get('populated') is True and populated.get('households') == 2, 'route seed incomplete')
        restarted = phase('RESTART', write=True)
        need(restarted.get('initialized') is True and restarted.get('households') == 2, 'populated restart incomplete')
        kept = phase('POPULATED_CHECK')
        need(kept.get('completeGroupRestored') is True, 'populated restart drift')
        record['steps'].append('nonempty_routes_stops_soft_deletion_and_receipts_preserved_on_real_restart')
        backup = phase('POPULATED_BACKUP', write=True)
        need(backup.get('databases') == 3, 'populated backup incomplete')
        restored = phase('RESTORE_CURRENT')
        need(restored.get('completeGroupRestored') is True and restored.get('databases') == 3
             and restored.get('logicalSha256') == kept['logicalSha256'], 'populated restore drift')
        record.update(populated=populated, restart=kept, restore=restored)
        record['steps'].append('populated_69_9_complete_backup_restored_with_receipts_and_marker')
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
