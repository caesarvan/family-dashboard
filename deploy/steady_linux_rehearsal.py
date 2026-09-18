"""Synthetic two-household 61/9 steady startup rehearsal; never production data.

Uses the fixed parent image, isolated Executor, and real candidate app startup.
The marker override is synthetic, not the production controller's exact program.
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
from deploy import membership_release_package as package
from deploy import membership_release_build as build
from deploy import steady_release_package as steady

SELF = 'deploy/steady_linux_rehearsal.py'
need, sha, encoded = package.need, package.digest, package.encoded
SYNTHETIC_MARKER = encoded({'kind': 'steady-rehearsal-synthetic-marker', 'syntheticOnly': True,
                            'notProductionMigrationReceipt': True})
SYNTHETIC_ENV = {
    'DATA_DIR': '/data', 'SECRET_KEY': 'steady-linux-rehearsal-synthetic-only',
    'PUBLIC_ORIGIN': 'https://steady-rehearsal.invalid', 'COOKIE_SECURE': '1',
    'MEMBER1_PASSWORD': 'synthetic-parent-password-one', 'MEMBER2_PASSWORD': 'synthetic-parent-password-two',
    'PYTHONDONTWRITEBYTECODE': '1', 'ASSISTANT_PROVIDER': 'openai',
    'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
    'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
}

# root/proof/runtime are explicit synthetic paths supplied by the wrapper.
SEED_PROGRAM = r'''
from contextlib import closing
import json,os,sqlite3,socket
assert not list(root.iterdir()), 'synthetic root must start empty'
def no_network(*args,**kwargs):raise RuntimeError('seed_network_forbidden')
socket.socket.connect=no_network
import app
assert Path(app.__file__).resolve()==runtime/'app.py'
application=app.create_app()
origin=os.environ['PUBLIC_ORIGIN']
def request(client,method,path,**kwargs):return client.open(path,method=method,base_url=origin,**kwargs)
def login(client,password):
 assert request(client,'POST','/api/login',json={'username':'member1','password':password},headers={'Origin':origin}).status_code==200
 return {'X-CSRF-Token':request(client,'GET','/api/me').json['csrf'],'Origin':origin}
def content(client,headers,title):
 assert request(client,'POST','/api/items/tasks',json={'title':title},headers=headers).status_code==201
 assert request(client,'PATCH','/api/members/member2/role',json={'expectedAuthVersion':1,'householdRole':'member'},headers=headers).status_code==200
primary=application.test_client();headers=login(primary,os.environ['MEMBER1_PASSWORD'])
content(primary,headers,'Synthetic primary household task')
invitation=request(primary,'POST','/api/spaces/invitations',json={},headers=headers)
assert invitation.status_code==201
secondary=application.test_client()
response=request(secondary,'POST','/api/spaces/redeem',json={'invitation':invitation.json['invitation'],
 'name':'Synthetic second household','slug':'synthetic-second',
 'MEMBER1_PASSWORD':'synthetic-child-password-one','MEMBER2_PASSWORD':'synthetic-child-password-two'},headers={'Origin':origin})
assert response.status_code==201
assert request(secondary,'GET',response.json['entry']).status_code==303
content(secondary,login(secondary,'synthetic-child-password-one'),'Synthetic second household task')
households=application.extensions['household_platform'].households()
assert len(households)==2 and sum(h['id']=='default' for h in households)==1
counts={};roles={}
for index,household in enumerate(households):
 path=root/'household.sqlite3' if household['id']=='default' else root/'spaces'/household['id']/'household.sqlite3'
 with closing(sqlite3.connect(path)) as con:
  con.execute("INSERT OR REPLACE INTO private_finance(owner,data,revision) VALUES(?,?,?)",('member1',json.dumps({'synthetic':True,'value':100+index}),7))
  con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)",('member1','synthetic-rehearsal','synthetic-only','2026-01-01T00:00:00+00:00'))
  con.commit();assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
  tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
  assert len(tables)==61 and 'household_memberships' in tables
  relative=path.relative_to(root).as_posix();counts[relative]=len(tables)
  roles[relative]=dict(con.execute('SELECT household_role,count(*) FROM users GROUP BY household_role'))
  assert roles[relative]=={'admin':1,'member':1}
with closing(sqlite3.connect(root/'platform.sqlite3')) as con:
 assert con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
 assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]==9
 assert con.execute('PRAGMA user_version').fetchone()[0]==1
record={'synthetic':True,'households':2,'databases':3,'householdTables':counts,'platformTables':9,'roleCounts':roles,
 'setup':'Real fixed-parent app login/invitation/redeem/task/role APIs; explicit synthetic private and audit rows'}
with (proof/'seed.json').open('x') as stream:json.dump(record,stream)
(proof/'seed.json').chmod(0o600)
print(json.dumps({'seeded':True,'households':2,'databases':3,'householdTables':61,'platformTables':9}))
'''

STARTUP_PROGRAM = r'''
import socket
def no_network(*args,**kwargs):raise RuntimeError('startup_network_forbidden')
socket.socket.connect=no_network
import app
assert Path(app.__file__).resolve()==Path('/app/app.py')
application=app.create_app()
platform=application.extensions['household_platform'];households=platform.households()
assert len(households)==2
for household in households:
 child=platform.child(household)
 assert not child.config.get('_HOUSEHOLD_RECOVERY_ONLY')
result={'initialized':True,'households':len(households),'mode':'normal_app_factory_all_registered_households'}
with (proof/'app-startup.json').open('x') as stream:json.dump(result,stream)
(proof/'app-startup.json').chmod(0o600)
print(json.dumps(result))
'''


def literal(raw, name):
    values = [ast.literal_eval(node.value) for node in ast.parse(raw).body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    need(len(values) == 1 and isinstance(values[0], str), 'missing or duplicate program constant: ' + name)
    return values[0]


def candidate_input(candidate, package_sha256):
    candidate = package.checked(Path(candidate).absolute(), True)
    verified = steady.verify_package(candidate / 'package', package_sha256)
    for relative, local in ((SELF, __file__), ('deploy/membership_release_build.py', build.__file__),
                            ('deploy/membership_release_package.py', package.__file__),
                            ('deploy/steady_release_package.py', steady.__file__)):
        need(verified['blobs'].get(relative) == package.plain(Path(local).absolute()), 'executed helper differs: ' + relative)
    source = package.checked(candidate / 'source', True)
    need(build.tree_hashes(source) == {**verified['manifest']['files'],
         'RELEASE-MANIFEST.json': verified['metadata']['manifestSha256']}, 'candidate source differs')
    need(verified['metadata']['parentImage'] == steady.PARENT_IMAGE and
         verified['metadata']['oldManifestSha256'] == steady.OLD_MANIFEST, 'steady baseline differs')
    return candidate, source, verified


def programs(blobs):
    controller = blobs['deploy/membership_release_controller.py']
    prefix = literal(controller, 'DATA_PREFIX')
    binding = "\nfrom deploy import steady_release_data as steady\ncontract=json.loads((proof/'rehearsal-contract.json').read_bytes())\n"
    marker = repr(sha(SYNTHETIC_MARKER))
    call = "(root,proof,source_identity=identity,plan_sha256=hashlib.sha256((proof/'rehearsal-contract.json').read_bytes()).hexdigest(),marker_sha256=" + marker + ")"
    seed = "from pathlib import Path\nroot=Path('/data');proof=Path('/proof');runtime=Path('/app')\n" + SEED_PROGRAM
    seed += "\nwith (root/'membership-release-attempt.json').open('xb') as stream:stream.write(" + repr(SYNTHETIC_MARKER) + ")\n(root/'membership-release-attempt.json').chmod(0o600)\n"
    values = {'RUNTIME': literal(controller, 'RUNTIME_PROGRAM'), 'SEED': seed,
              'BEGIN': prefix + binding + 'print(json.dumps(steady.begin' + call + '))\n',
              'STARTUP': prefix + STARTUP_PROGRAM,
              'CHECK': prefix + binding + 'print(json.dumps(steady.check_stopped' + call + '))\n'}
    for value in values.values():
        ast.parse(value)
    return values


def phase(docker, image, program, source, output, *, write=False, seed=False):
    mounts = [(output / 'data', '/data', not write), (output / 'proof', '/proof', False)]
    if not seed:
        mounts.append((source, '/release', True))
    raw = build.must(build.isolated(docker, build.image_id(image), program, mounts=mounts,
                     env=list(SYNTHETIC_ENV.items()), writable=True, timeout=360), 'steady rehearsal phase failed; retain attempt')
    return package.json_value(raw)


def summary(proof):
    load = lambda name: package.json_value(package.plain(proof / name))
    seed, before, after, result = (load(name) for name in ('seed.json', 'before.json', 'after.json', 'result.json'))
    need(seed['synthetic'] is True and seed['households'] == 2 and seed['databases'] == 3 and seed['platformTables'] == 9
         and len(seed['householdTables']) == 2 and set(seed['householdTables'].values()) == {61}
         and len(seed['roleCounts']) == 2 and all(v == {'admin': 1, 'member': 1} for v in seed['roleCounts'].values()), 'seed scope differs')
    need(before['households'] == after['households'] == 2 and len(before['databases']) == len(after['databases']) == 3
         and before['databases'].keys() == after['databases'].keys(), 'database group differs')
    for name, old in before['databases'].items():
        new = after['databases'][name]
        need(old['membershipPhase'] == new['membershipPhase'] == 'after', 'schema phase differs')
        count = lambda value: len([n for n in value['tables'] if not n.startswith('sqlite_')])
        need(count(old) == count(new) == (9 if name == 'platform.sqlite3' else 61), 'table counts differ')
        need({k:v for k,v in old.items() if k != 'fileSha256'} ==
             {k:v for k,v in new.items() if k != 'fileSha256'}, 'schema rows or sequence changed')
    need(result['verified'] is True and result['households'] == 2 and result['databases'] == 3
         and result['markerSha256'] == sha(SYNTHETIC_MARKER), 'stopped check differs')
    return {'verified': True, 'households': 2, 'databases': 3, 'householdTables': [61, 61],
            'platformTables': [9, 9], 'preservationCompared': 3, 'logicalSha256': result['logicalSha256'],
            'syntheticMarkerSha256': result['markerSha256']}


def rehearse(candidate, package_sha256, image_id, output_dir):
    need(sys.platform == 'linux' and os.geteuid() == 0 and sys.dont_write_bytecode and not sys.flags.optimize
         and sys.pycache_prefix is None, 'Linux root python -B without optimization required')
    need(not any(n.upper().startswith(('COMPOSE_', 'DOCKER_')) for n in os.environ), 'ambient Docker selector')
    candidate, source, verified = candidate_input(candidate, package_sha256)
    meta, blobs = verified['metadata'], verified['blobs']
    code = programs(blobs)
    output = Path(output_dir).absolute()
    need(not candidate.is_relative_to(output), 'output overlaps candidate')
    output = build.new_output(output, candidate)
    for name in ('data', 'proof'):
        path = output / name; path.mkdir(mode=0o700); os.chown(path, 10001, 10001)
    identity = {'head': meta['sourceHead'], 'tree': meta['tree'], 'imageId': build.image_id(image_id),
                'sourceHashes': verified['manifest']['files'], 'runtimeHashes': meta['runtimeFiles']}
    contract = {'kind': 'steady-synthetic-rehearsal', 'packageSha256': package_sha256,
                'manifestSha256': meta['manifestSha256'], 'identity': identity, 'parentImage': steady.PARENT_IMAGE,
                'syntheticMarkerSha256': sha(SYNTHETIC_MARKER),
                'productionMarkerSha256': literal(blobs['deploy/steady_release_data.py'], 'MEMBERSHIP_MARKER_SHA256'),
                'controllerSha256': sha(blobs['deploy/steady_release_controller.py']),
                'programHashes': {name: sha(value.encode()) for name, value in code.items()},
                'exactProductionControllerProgram': False, 'syntheticMarkerOverride': True}
    for name, value in (('identity.json', identity), ('rehearsal-contract.json', contract)):
        path = output / 'proof' / name; package.write_new(path, encoded(value)); os.chown(path, 10001, 10001)
    docker = build.Executor(output)
    record = {'passed': False, 'steps': [], **contract, 'rehearsalContractSha256': sha(encoded(contract)),
              'sourceHead': meta['sourceHead'], 'tree': meta['tree'], 'imageId': image_id,
              'syntheticOnly': True, 'productionAccess': False}
    try:
        parent, child = (build.inspect_image(docker, image) for image in (steady.PARENT_IMAGE, image_id))
        layers = parent['RootFS']['Layers']
        need(child['RootFS']['Layers'][:-2] == layers and len(child['RootFS']['Layers']) == len(layers) + 2, 'image parent/layers differ')
        config = lambda value: {k:v for k,v in value['Config'].items() if k != 'Image'}
        need(config(parent) == config(child), 'image configuration differs')
        need(phase(docker, image_id, code['RUNTIME'], source, output) == meta['runtimeFiles'], 'candidate runtime differs')
        record['steps'].append('candidate_runtime_verified')
        seeded = phase(docker, steady.PARENT_IMAGE, code['SEED'], source, output, write=True, seed=True)
        need(seeded == {'seeded': True, 'households': 2, 'databases': 3, 'householdTables': 61, 'platformTables': 9}, 'seed failed')
        record['steps'].append('fixed_parent_two_households_seeded_and_process_exited')
        before = phase(docker, image_id, code['BEGIN'], source, output, write=True)
        need(before.get('verified') is True, 'begin did not verify')
        record['steps'].append('stopped_backup_verified')
        started = phase(docker, image_id, code['STARTUP'], source, output, write=True)
        need(started.get('initialized') is True and started.get('households') == 2, 'app startup incomplete')
        record['steps'].append('real_app_initialized_all_households_and_process_exited')
        after = phase(docker, image_id, code['CHECK'], source, output)
        need(after.get('verified') is True and after.get('logicalSha256') == before.get('logicalSha256'), 'stopped state drift')
        record['steps'].append('all_schema_rows_sequences_and_synthetic_marker_preserved')
        record['result'] = summary(output / 'proof')
        need(candidate_input(candidate, package_sha256)[2] == verified, 'candidate changed during rehearsal')
        record['passed'] = True
    except Exception as error:
        record['error'] = str(error)
    finally:
        record['completedAt'] = datetime.now(timezone.utc).isoformat()
        record['evidence'] = {'proof/' + name: digest for name, digest in build.tree_hashes(output / 'proof').items()}
        record['commands'] = len(docker.records)
        package.write_new(output / 'result.json', encoded(record))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'package-sha256', 'image-id', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    result = rehearse(**vars(parser.parse_args()))
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
