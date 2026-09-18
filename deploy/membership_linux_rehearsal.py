"""One stopped, synthetic two-household Linux migration rehearsal.

Uses immutable local images and the candidate controller's exact programs.
Never touches production volumes, environment, tags, compose or systemd.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
from deploy import membership_release_package as package
from deploy import membership_release_build as build

SELF = 'deploy/membership_linux_rehearsal.py'
need, sha, encoded = package.need, package.digest, package.encoded
SYNTHETIC_ENV = {
    'DATA_DIR': '/data', 'SECRET_KEY': 'membership-linux-rehearsal-synthetic-only',
    'PUBLIC_ORIGIN': 'https://membership-rehearsal.invalid', 'COOKIE_SECURE': '1',
    'MEMBER1_PASSWORD': 'synthetic-parent-password-one', 'MEMBER2_PASSWORD': 'synthetic-parent-password-two',
    'PYTHONDONTWRITEBYTECODE': '1', 'ASSISTANT_PROVIDER': 'openai',
    'OPENAI_API_KEY': '', 'NVIDIA_API_KEY': '', 'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '',
    'MICROSOFT_CLIENT_ID': '', 'MICROSOFT_CLIENT_SECRET': '',
}

SEED_PROGRAM = r'''
from pathlib import Path
from contextlib import closing
import json,os,sqlite3,socket
root=Path('/data');proof=Path('/proof')
assert not list(root.iterdir()), 'synthetic root must start empty'
def no_network(*args,**kwargs):raise RuntimeError('seed_network_forbidden')
socket.socket.connect=no_network
import app
assert Path(app.__file__).resolve()==Path('/app/app.py')
application=app.create_app({'TESTING':True})
origin=os.environ['PUBLIC_ORIGIN']
def request(client,method,path,**kwargs):
 return client.open(path,method=method,base_url=origin,**kwargs)
def login(client,password):
 response=request(client,'POST','/api/login',json={'username':'member1','password':password},headers={'Origin':origin})
 assert response.status_code==200
 return {'X-CSRF-Token':request(client,'GET','/api/me').json['csrf'],'Origin':origin}
primary=application.test_client();headers=login(primary,os.environ['MEMBER1_PASSWORD'])
response=request(primary,'POST','/api/items/tasks',json={'title':'Synthetic primary household task'},headers=headers)
assert response.status_code==201
invitation=request(primary,'POST','/api/spaces/invitations',json={},headers=headers)
assert invitation.status_code==201
secondary=application.test_client()
response=request(secondary,'POST','/api/spaces/redeem',json={'invitation':invitation.json['invitation'],
 'name':'Synthetic second household','slug':'synthetic-second',
 'MEMBER1_PASSWORD':'synthetic-child-password-one','MEMBER2_PASSWORD':'synthetic-child-password-two'},headers={'Origin':origin})
assert response.status_code==201
assert request(secondary,'GET',response.json['entry']).status_code==303
child_headers=login(secondary,'synthetic-child-password-one')
assert request(secondary,'POST','/api/items/tasks',json={'title':'Synthetic second household task'},headers=child_headers).status_code==201
households=application.extensions['household_platform'].households()
assert len(households)==2 and sum(h['id']=='default' for h in households)==1
counts={}; roles={}
for index,household in enumerate(households):
 path=root/'household.sqlite3' if household['id']=='default' else root/'spaces'/household['id']/'household.sqlite3'
 with closing(sqlite3.connect(path)) as con:
  con.execute("UPDATE users SET household_role='member' WHERE id='member2'")
  con.execute("INSERT OR REPLACE INTO private_finance(owner,data,revision) VALUES(?,?,?)",('member1',json.dumps({'synthetic':True,'value':100+index}),7))
  con.execute("INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)",('member1','synthetic-rehearsal','synthetic-only','2026-01-01T00:00:00+00:00'))
  con.commit();con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
  tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
  assert len(tables)==58 and 'household_memberships' not in tables
  relative=path.relative_to(root).as_posix();counts[relative]=len(tables)
  roles[relative]=dict(con.execute('SELECT household_role,count(*) FROM users GROUP BY household_role'))
  assert roles[relative]=={'admin':1,'member':1}
with closing(sqlite3.connect(root/'platform.sqlite3')) as con:
 con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
 assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}=={'households','household_invitations'}
 assert con.execute('PRAGMA user_version').fetchone()[0]==0
record={'synthetic':True,'households':2,'databases':3,'householdTables':counts,'platformTables':2,
 'roleCounts':roles,'setup':'Real old-image Flask login/invitation/redeem/task APIs; explicit synthetic SQLite private rows and member-role values'}
with (proof/'seed.json').open('x') as stream:json.dump(record,stream)
(proof/'seed.json').chmod(0o600)
print(json.dumps({'seeded':True,'households':2,'databases':3,'householdTables':58,'platformTables':2}))
'''


def controller_programs(raw):
    values = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('DATA_PREFIX', 'BACKUP_PROGRAM', 'WARM_PROGRAM', 'RUNTIME_PROGRAM'):
                    need(target.id not in values, 'duplicate controller program')
                    values[target.id] = ast.literal_eval(node.value)
    need(set(values) == {'DATA_PREFIX', 'BACKUP_PROGRAM', 'WARM_PROGRAM', 'RUNTIME_PROGRAM'}
         and all(isinstance(p, str) and p for p in values.values()), 'missing controller programs')
    for value in values.values():
        ast.parse(value)
    warm_functions = [n for n in ast.parse(values['WARM_PROGRAM']).body if isinstance(n, ast.FunctionDef) and n.name == 'warm']
    need(len(warm_functions) == 1, 'one actual controller warm callback required')
    warm = ast.get_source_segment(values['WARM_PROGRAM'], warm_functions[0])
    values['RESTART_PROGRAM'] = values['DATA_PREFIX'] + warm + "\nwarm()\nprint(json.dumps({'restarted':True}))\n"
    values['CHECK_PROGRAM'] = values['DATA_PREFIX'] + """
value=data.check_current_after(proof/'attempt',root)
with (proof/'after-restart.json').open('x') as stream:json.dump(value,stream)
(proof/'after-restart.json').chmod(0o600)
print(json.dumps({'verified':value['verified'],'households':value['households'],'databases':value['databases']}))
"""
    return values


def files(root):
    return build.tree_hashes(root)


def image_id(value):
    need(isinstance(value, str) and re.fullmatch('sha256:[0-9a-f]{64}', value), 'immutable image ID required')
    return value


def candidate_input(candidate, package_sha256):
    candidate = package.checked(Path(candidate).absolute(), True)
    verified = package.verify_package(candidate / 'package', package_sha256)
    need(verified['blobs'].get(SELF) == package.plain(Path(__file__).absolute()), 'executed rehearsal differs from candidate')
    need(verified['blobs'].get('deploy/membership_release_build.py') == package.plain(Path(build.__file__).absolute()),
         'executed isolation helper differs from candidate')
    source = package.checked(candidate / 'source', True)
    need(files(source) == {**verified['manifest']['files'], 'RELEASE-MANIFEST.json': verified['metadata']['manifestSha256']},
         'candidate source/manifest differs')
    programs = controller_programs(verified['blobs']['deploy/membership_release_controller.py'])
    return candidate, source, verified, programs


def new_output(path, candidate):
    path = Path(path).absolute()
    need('..' not in path.parts and not path.exists(), 'new output required; never replay an attempt')
    package.checked(path.parent, True)
    need(not path.is_relative_to(candidate) and not candidate.is_relative_to(path), 'output overlaps candidate')
    path.mkdir(mode=0o700)
    return path


def container_parameters(image, program, source, output, *, data_write, include_source=True):
    image_id(image)
    mounts = [(output / 'data', '/data', not data_write), (output / 'proof', '/proof', False)]
    if include_source:
        mounts.append((source, '/release', True))
    for host, target, readonly in mounts:
        need(host.is_absolute() and ',' not in str(host) and '\n' not in str(host), 'unsafe mount path')
    return {'image': image, 'program': program, 'mounts': mounts, 'env': list(SYNTHETIC_ENV.items()),
            'writable': True, 'timeout': 360}


def run_container(docker, **parameters):
    raw = build.must(build.isolated(docker, **parameters), 'rehearsal phase failed; no automatic retry')
    return package.json_value(raw)


def inspect_images(docker, child):
    values = []
    for image in (package.PARENT_IMAGE, image_id(child)):
        values.append(build.inspect_image(docker, image))
    parent, new = values
    layers = parent['RootFS']['Layers']
    need(new['RootFS']['Layers'][:-2] == layers and len(new['RootFS']['Layers']) == len(layers) + 2, 'candidate image parent/layers differ')
    config = lambda value: {k: v for k, v in value['Config'].items() if k != 'Image'}
    need(config(parent) == config(new), 'candidate image configuration differs')


def proof_summary(proof):
    load = lambda name: package.json_value(package.plain(proof / name))
    seed, before, after = load('seed.json'), load('before.json'), load('attempt/after.json')
    result, restarted = load('attempt/result.json'), load('after-restart.json')
    need(seed['synthetic'] is True and seed['households'] == 2 and seed['databases'] == 3
         and seed['platformTables'] == 2 and set(seed['householdTables'].values()) == {58}, 'seed scope differs')
    need(len(seed['roleCounts']) == 2 and all(v == {'admin': 1, 'member': 1} for v in seed['roleCounts'].values()), 'ordinary roles not seeded')
    need(before['households'] == after['households'] == 2 and len(before['databases']) == len(after['databases']) == 3
         and set(before['databases']) == set(after['databases']), 'database group differs')
    for name in before['databases']:
        old, new = before['databases'][name], after['databases'][name]
        count = lambda value: len([n for n in value['tables'] if not n.startswith('sqlite_')])
        need(old['membershipPhase'] == 'before' and new['membershipPhase'] == 'after', 'schema phase differs')
        need((count(old), count(new)) == ((2, 9) if name == 'platform.sqlite3' else (58, 61)), 'schema table counts differ')
    need(result['state'] == 'completed' and result['households'] == 2 and result['databases'] == 3
         and set(result['comparisons']) == set(before['databases'])
         and all(v['verified'] is True for v in result['comparisons'].values()), 'full preservation proof missing')
    need(restarted['verified'] is True and restarted['households'] == 2 and restarted['databases'] == 3
         and restarted['logicalSha256'] == result['afterLogicalSha256'], 'restart preservation differs')
    need(not (proof / 'attempt/failed.json').exists(), 'failed migration marker')
    return {'verified': True, 'households': 2, 'databases': 3, 'householdTables': [58, 61],
            'platformTables': [2, 9], 'preservationCompared': 3, 'ordinaryMemberRolesSeeded': True,
            'restartLogicalSha256': restarted['logicalSha256']}


def rehearse(candidate, package_sha256, image_id, output_dir):
    need(sys.platform == 'linux' and os.geteuid() == 0 and sys.dont_write_bytecode and not sys.flags.optimize,
         'Linux root python -B required for isolated UID 10001 directories')
    candidate, source, verified, programs = candidate_input(candidate, package_sha256)
    meta = verified['metadata']
    output = new_output(output_dir, candidate)
    for name in ('data', 'proof'):
        path = output / name; path.mkdir(mode=0o700); os.chown(path, 10001, 10001)
    identity = {'head': meta['sourceHead'], 'tree': meta['tree'], 'imageId': image_id,
                'sourceHashes': verified['manifest']['files'], 'runtimeHashes': meta['runtimeFiles']}
    package.write_new(output / 'proof/identity.json', encoded(identity))
    os.chown(output / 'proof/identity.json', 10001, 10001)
    docker = build.Executor(output)
    record = {'passed': False, 'steps': [], 'sourceHead': meta['sourceHead'], 'tree': meta['tree'],
              'packageSha256': package_sha256, 'manifestSha256': meta['manifestSha256'], 'imageId': image_id,
              'parentImage': package.PARENT_IMAGE, 'controllerSha256': sha(verified['blobs']['deploy/membership_release_controller.py']),
              'programHashes': {k: sha(v.encode()) for k, v in programs.items()}, 'seedProgramSha256': sha(SEED_PROGRAM.encode()),
              'syntheticOnly': True, 'productionAccess': False}
    try:
        inspect_images(docker, image_id)
        observed = run_container(docker, **container_parameters(image_id, programs['RUNTIME_PROGRAM'], source, output, data_write=False))
        need(observed == meta['runtimeFiles'], 'candidate runtime bytes differ')
        record['steps'].append('candidate_runtime_verified')
        seeded = run_container(docker, **container_parameters(package.PARENT_IMAGE, SEED_PROGRAM, source, output,
                                                              data_write=True, include_source=False))
        need(seeded == {'seeded': True, 'households': 2, 'databases': 3, 'householdTables': 58, 'platformTables': 2}, 'old-image seed failed')
        record['steps'].append('old_image_two_households_seeded_and_process_stopped')
        for name in ('BACKUP_PROGRAM', 'WARM_PROGRAM', 'RESTART_PROGRAM', 'CHECK_PROGRAM'):
            program = programs[name] if name in ('RESTART_PROGRAM', 'CHECK_PROGRAM') else programs['DATA_PREFIX'] + programs[name]
            value = run_container(docker, **container_parameters(image_id, program, source, output, data_write=name != 'CHECK_PROGRAM'))
            need(value.get('restarted' if name == 'RESTART_PROGRAM' else 'verified') is True, 'phase did not verify')
            record['steps'].append(name)
        record['result'] = proof_summary(output / 'proof')
        need(candidate_input(candidate, package_sha256)[2] == verified, 'candidate bytes changed during rehearsal')
        record['passed'] = True
    except Exception as error:
        record['error'] = str(error)
    finally:
        record['completedAt'] = datetime.now(timezone.utc).isoformat()
        record['evidence'] = {'proof/' + name: value for name, value in files(output / 'proof').items()}
        record['commands'] = len(docker.records)
        package.write_new(output / 'result.json', encoded(record))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'package-sha256', 'image-id', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    record = rehearse(**vars(parser.parse_args()))
    print(json.dumps(record))
    raise SystemExit(0 if record['passed'] else 1)


if __name__ == '__main__':
    main()
