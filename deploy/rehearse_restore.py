"""Rehearse the documented restore in disposable, synthetic Docker volumes.

This command never reads Compose configuration, .env, or existing data volumes.
Requires a local immutable Linux image built from this source tree. No ports are
published and every container uses --network none. Run on the Docker host.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import uuid


LABEL = 'org.family-dashboard.synthetic-recovery'
IMAGE_RE = re.compile(r'sha256:[a-f0-9]{64}\Z')
RUN_RE = re.compile(r'[a-f0-9]{32}\Z')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def documented_programs(root):
    """Extract the exact reviewed instructions; no restore algorithm duplication."""
    document = (root / 'docs/DEPLOYMENT.md').read_text(encoding='utf-8')
    matches = [body for body in re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", document, re.S)
               if "root = Path('/data').resolve(strict=True)" in body and 'from contextlib import ExitStack' in body]
    if len(matches) != 1:
        raise ValueError('Expected one documented restore program')
    restore = matches[0]
    ast.parse(restore)
    session_doc = (root / 'docs/MEMBER-SESSIONS.md').read_text(encoding='utf-8')
    sql_blocks = [body.strip() for body in re.findall(r'```sql\n(.*?)\n```', session_doc, re.S)
                  if 'BEGIN IMMEDIATE;' in body and 'UPDATE member_session_browsers' in body
                  and 'DELETE FROM cloud_oauth_states;' in body]
    if len(sql_blocks) != 1:
        raise ValueError('Expected one documented session invalidation program')
    return restore, sql_blocks[0]


def source_hashes(root):
    runtime = sorted([*root.glob('*.py'), root / 'requirements.txt',
                      *(root / 'static').rglob('*')])
    runtime = [p for p in runtime if p.is_file()]
    extra = [root / name for name in ('deploy/backup.py', 'deploy/rehearse_restore.py',
             'tests/restore_rehearsal_fixture.py', 'docs/DEPLOYMENT.md', 'docs/MEMBER-SESSIONS.md')]
    files = runtime + extra
    if any(p.is_symlink() or not p.resolve().is_relative_to(root) for p in files):
        raise ValueError('Unsafe source path')
    return ({p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in files},
            [p.relative_to(root).as_posix() for p in runtime])


def owned_resource(info, kind, run_id, name):
    """Require exact run identity and resource name before any resource mutation."""
    if not RUN_RE.fullmatch(run_id) or not re.fullmatch('fd-rehearsal-' + run_id + r'-[a-z0-9-]+', name):
        return False
    actual_name = info.get('Name', '').lstrip('/')
    labels = info.get('Labels', {}) if kind == 'volume' else info.get('Config', {}).get('Labels', {})
    return actual_name == name and (labels or {}).get(LABEL) == run_id


class Rehearsal:
    def __init__(self, root, image, output):
        if not IMAGE_RE.fullmatch(image):
            raise ValueError('An immutable local image ID is required')
        self.root, self.image, self.output = root.resolve(strict=True), image, output
        self.run_id = uuid.uuid4().hex
        self.resources = []
        self.counter = 0
        self.phase = 'preflight'
        self.output_created = False
        self.report = {'runId': self.run_id, 'scope': 'synthetic Docker recovery only',
                       'startedAt': datetime.now(timezone.utc).isoformat(), 'image': image,
                       'checks': [], 'containers': [], 'passed': False}
        self.env = {
            'DATA_DIR': '/data', 'SECRET_KEY': secrets.token_hex(32),
            'MEMBER1_PASSWORD': 'synthetic-' + secrets.token_hex(16),
            'MEMBER2_PASSWORD': 'synthetic-' + secrets.token_hex(16),
            'PUBLIC_ORIGIN': 'https://127.0.0.1:8000', 'COOKIE_SECURE': '0', 'TRUST_PROXY': '0',
            'MICROSOFT_CLIENT_ID': 'synthetic-rehearsal-client',
            'MICROSOFT_CLIENT_SECRET': 'synthetic-rehearsal-secret',
            'GOOGLE_CLIENT_ID': 'synthetic-rehearsal-client',
            'GOOGLE_CLIENT_SECRET': 'synthetic-rehearsal-secret',
            'OPENAI_API_KEY': '', 'OPENAI_MODEL': '',
            'FAMILY_DASHBOARD_SYNTHETIC_REHEARSAL': '1', 'REHEARSAL_RUN_ID': self.run_id,
        }

    def docker(self, args, *, data=None, timeout=90, check=True):
        result = subprocess.run(['docker', *args], input=data, text=True, encoding='utf-8',
                                capture_output=True, timeout=timeout)
        if check and result.returncode:
            # Never include command/env/fixture output in exceptions.
            raise RuntimeError('Docker operation failed during ' + self.phase)
        return result

    def inspect(self, kind, name):
        return json.loads(self.docker([kind, 'inspect', name]).stdout)[0]

    def require_owned(self, kind, name):
        info = self.inspect(kind, name)
        if not owned_resource(info, kind, self.run_id, name):
            raise RuntimeError('Resource ownership mismatch')
        return info

    def check(self, name, passed):
        self.report['checks'].append({'name': name, 'passed': bool(passed)})
        if not passed:
            raise RuntimeError('Rehearsal assertion failed: ' + name)

    def name(self, role):
        self.counter += 1
        return f'fd-rehearsal-{self.run_id}-{role}-{self.counter}'

    def volume(self, role):
        name = self.name(role)
        if self.docker(['volume', 'inspect', name], check=False).returncode == 0:
            raise RuntimeError('Refusing an existing volume')
        self.resources.append(('volume', name))
        self.docker(['volume', 'create', '--label', LABEL + '=' + self.run_id, name])
        self.require_owned('volume', name)
        self.ephemeral(['python', '-c', "import os; os.chown('/data',10001,10001); os.chmod('/data',0o700)"],
                       [(name, '/data', False)], user='0:0')
        return name

    def container(self, command, volumes=(), *, user='10001:10001'):
        name = self.name('container')
        if self.docker(['container', 'inspect', name], check=False).returncode == 0:
            raise RuntimeError('Refusing an existing container')
        args = ['container', 'create', '--name', name, '--label', LABEL + '=' + self.run_id,
                '--pull', 'never', '--network', 'none', '--read-only', '--user', user,
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '128',
                '--memory', '384m', '--cpus', '1', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m', '-i']
        # Root is used only to initialize ownership of newly created volumes.
        if user == '0:0':
            args += ['--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE']
        for volume, destination, readonly in volumes:
            self.require_owned('volume', volume)
            if destination not in ('/data', '/source', '/proof'):
                raise ValueError('Unexpected mount destination')
            args += ['--mount', f'type=volume,src={volume},dst={destination}' + (',readonly' if readonly else '')]
        for folder in ('tests', 'deploy'):
            path = self.root / folder
            if path.is_symlink() or ',' in str(path):
                raise ValueError('Unsafe source mount')
            args += ['--mount', f'type=bind,src={path},dst=/rehearsal/{folder},readonly']
        for key, value in self.env.items():
            args += ['--env', key + '=' + value]
        self.resources.append(('container', name))
        self.docker([*args, '--entrypoint', command[0], self.image, *command[1:]])
        info = self.require_owned('container', name)
        mounts = info['Mounts']
        expected_volumes = {v for v, _, _ in volumes}
        actual_volumes = {m['Name'] for m in mounts if m['Type'] == 'volume'}
        self.check('container_isolated_' + str(self.counter),
                   info['Image'] == self.image and info['HostConfig']['NetworkMode'] == 'none'
                   and not info['HostConfig'].get('PortBindings') and info['HostConfig']['ReadonlyRootfs']
                   and expected_volumes == actual_volumes
                   and all(not m['RW'] for m in mounts if m['Type'] == 'bind'))
        self.report['containers'].append({'name': name, 'image': info['Image'], 'user': info['Config']['User'],
            'network': info['HostConfig']['NetworkMode'], 'publishedPorts': False, 'readonlyRootfs': True,
            'mounts': [{'type': m['Type'], 'destination': m['Destination'], 'readonly': not m['RW'],
                        **({'volume': m['Name']} if m['Type'] == 'volume' else {})} for m in mounts]})
        return name

    def ephemeral(self, command, volumes=(), *, data=None, user='10001:10001', check=True):
        name = self.container(command, volumes, user=user)
        result = self.docker(['start', '-a', '-i', name], data=data, timeout=120, check=False)
        info = self.require_owned('container', name)
        if info['State']['Running']:
            raise RuntimeError('Ephemeral container still running')
        result.returncode = info['State']['ExitCode'] if result.returncode == 0 else result.returncode
        if check and result.returncode:
            raise RuntimeError('Isolated phase failed: ' + self.phase)
        return result

    def start_app(self, volume, proof):
        name = self.container(['gunicorn', '--bind', '127.0.0.1:8000', '--workers', '1', '--threads', '4',
                               '--timeout', '45', '--error-logfile', '-', 'app:create_app()'],
                              [(volume, '/data', False), (proof, '/proof', False)])
        self.docker(['start', name])
        for _ in range(30):
            probe = self.docker(['exec', name, 'python', '-c',
                "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2); assert r.status==200"],
                check=False, timeout=6)
            if probe.returncode == 0:
                return name
            if not self.require_owned('container', name)['State']['Running']:
                raise RuntimeError('Synthetic app exited')
            time.sleep(0.3)
        raise RuntimeError('Synthetic app health timeout')

    def fixture(self, name, phase):
        self.phase = 'fixture_' + phase
        self.require_owned('container', name)
        result = self.docker(['exec', name, 'python', '/rehearsal/tests/restore_rehearsal_fixture.py',
                              phase, '--proof-dir', '/proof'], timeout=180, check=False)
        try:
            value = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            value = {'phase': phase, 'passed': False, 'checks': []}
        # Fixture stdout contract contains fixed check names/booleans and counts only.
        checks = [{'name': str(x.get('name', 'invalid'))[:160], 'passed': x.get('passed') is True}
                  for x in value.get('checks', []) if isinstance(x, dict)]
        self.report[phase] = {'phase': phase, 'passed': value.get('passed') is True,
                              'checks': checks, 'exitCode': result.returncode,
                              'counts': {k: v for k, v in value.get('counts', {}).items()
                                         if re.fullmatch(r'[A-Za-z][A-Za-z0-9]{0,60}', k) and type(v) is int},
                              'httpRequests': value.get('httpRequests'),
                              'stage': value.get('stage'), 'errorType': value.get('errorType')}
        self.check('fixture_' + phase, result.returncode == 0 and value.get('passed') is True
                   and bool(checks) and all(x['passed'] for x in checks))

    def run(self):
        if os.name != 'posix':
            raise RuntimeError('Run on the Linux Docker host')
        # Existing output paths are rejected, including symlinks; no evidence overwrite.
        self.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.output_created = True
        before, runtime = source_hashes(self.root)
        restore, sql = documented_programs(self.root)
        self.report.update(sourceHashes=before, restoreProgramSha256=sha(restore.encode()),
                           sessionSqlSha256=sha(sql.encode()))
        image = self.inspect('image', self.image)
        self.check('local_linux_image', image['Id'] == self.image and image['Os'] == 'linux')
        runtime_map = {p: before[p] for p in runtime}
        program = "import hashlib,json,pathlib; expected=" + repr(runtime_map) + "; root=pathlib.Path('/app'); assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==s for p,s in expected.items()); print('verified')"
        self.ephemeral(['python', '-c', program])
        self.check('source_runtime_matches_image', True)
        self.phase = 'synthetic_seed'
        source, proof = self.volume('source'), self.volume('proof')
        app = self.start_app(source, proof)
        self.fixture(app, 'seed')
        self.require_owned('container', app)
        self.docker(['stop', '--time', '20', app], timeout=40)
        self.check('source_writers_stopped', not self.docker(['ps', '-q', '--filter', 'volume=' + source]).stdout.strip())
        self.phase = 'backup'
        backup = self.ephemeral(['python', '/rehearsal/deploy/backup.py'], [(source, '/data', False)])
        value = json.loads(backup.stdout.strip().splitlines()[-1])
        manifest = value['manifest']
        self.check('backup_three_databases', value.get('databases') == 3
                   and bool(re.fullmatch(r'manifest-[0-9TZ]+\.json', manifest)))
        self.report['backup'] = {'manifest': manifest, 'databases': 3}
        for scenario in ('bad_hash', 'missing_child', 'bad_mapping', 'valid'):
            self.phase = 'restore_' + scenario
            target = self.volume(scenario.replace('_', '-'))
            self.ephemeral(['python', '-', manifest, scenario], [(source, '/source', True), (target, '/data', False)],
                           data=COPY_SNAPSHOTS)
            result = self.ephemeral(['python', '-', manifest, 'platform', 'default'],
                                    [(target, '/data', False)], data=restore, check=False)
            if scenario != 'valid':
                self.check(scenario + '_rejected', result.returncode != 0)
                self.ephemeral(['python', '-c', NO_TARGETS], [(target, '/data', True)])
                self.check(scenario + '_no_target_created', True)
                continue
            self.check('documented_restore_succeeded', result.returncode == 0)
            self.phase = 'session_invalidation'
            self.ephemeral(['python', '-'], [(target, '/data', False)],
                           data=INVALIDATE_PREFIX + '\nsql = ' + repr(sql) + '\n' + INVALIDATE_BODY)
            self.check('documented_invalidation_all_households', True)
            restored = self.start_app(target, proof)
            self.fixture(restored, 'verify')
        after, _ = source_hashes(self.root)
        self.check('source_unchanged', before == after)
        self.report['passed'] = True

    def cleanup(self):
        failures = []
        for kind, name in reversed(self.resources):
            try:
                # A create can take effect before the CLI times out. Track names
                # before creation; distinguish absent resources from daemon errors.
                listed = self.docker([kind, 'ls', *(['-a'] if kind == 'container' else []),
                    '--format', '{{.Names}}' if kind == 'container' else '{{.Name}}']).stdout.splitlines()
                if name not in listed:
                    self.check('absent_' + name.split(self.run_id + '-')[1], True)
                    continue
                info = self.require_owned(kind, name)
                if kind == 'container':
                    if info['State']['Running']:
                        self.docker(['stop', '--time', '20', name], timeout=40)
                    self.require_owned(kind, name)
                    self.docker(['container', 'rm', name])
                else:
                    self.docker(['volume', 'rm', name])
                remaining = self.docker([kind, 'ls', *(['-a'] if kind == 'container' else []),
                    '--format', '{{.Names}}' if kind == 'container' else '{{.Name}}']).stdout.splitlines()
                self.check('removed_' + name.split(self.run_id + '-')[1], name not in remaining)
            except Exception as exc:
                failures.append({'kind': kind, 'name': name, 'errorType': type(exc).__name__})
        self.report['cleanup'] = {'passed': not failures, 'failures': failures,
                                  'resourcesTracked': len(self.resources)}
        if failures:
            self.report['passed'] = False


COPY_SNAPSHOTS = r'''
from pathlib import Path
import hashlib, json, re, shutil, sqlite3, sys
source, target = Path('/source'), Path('/data')
name, scenario = sys.argv[1:]
assert not list(target.iterdir())
assert re.fullmatch(r'manifest-[0-9TZ]+\.json',name)
manifest = json.loads((source/'backups'/name).read_text())
assert len(manifest['snapshots']) == 3
for item in manifest['snapshots']:
    relative = item['path']
    assert re.fullmatch(r'(backups|spaces/[a-f0-9]{24}/backups)/(household|platform)-[0-9TZ]+\.sqlite3',relative)
    src = source/relative
    assert src.resolve(strict=True).is_relative_to(source)
    assert not any(p.is_symlink() for p in (src,*src.parents) if p.is_relative_to(source))
    assert src.stat().st_size == item['bytes'] and hashlib.sha256(src.read_bytes()).hexdigest() == item['sha256']
    dst = target/relative
    dst.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    shutil.copyfile(src,dst); dst.chmod(0o600)
if scenario == 'bad_hash':
    manifest['snapshots'][-1]['sha256'] = '0'*64
elif scenario == 'missing_child':
    child = next(i for i in manifest['snapshots'] if i['path'].startswith('spaces/'))
    (target/child['path']).unlink()
elif scenario == 'bad_mapping':
    item = next(i for i in manifest['snapshots'] if i['path'].startswith('backups/platform-'))
    path = target/item['path']
    with sqlite3.connect(path) as con:
        con.execute("UPDATE households SET id=? WHERE id!='default'", ('b'*24,))
    item.update(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
else:
    assert scenario == 'valid'
(target/'backups'/name).write_text(json.dumps(manifest))
(target/'backups'/name).chmod(0o600)
print('Synthetic snapshot group copied.')
'''

NO_TARGETS = "from pathlib import Path; root=Path('/data'); assert not (root/'platform.sqlite3').exists(); assert not (root/'household.sqlite3').exists(); assert not list(root.glob('spaces/*/household.sqlite3')); print('No targets created.')"

INVALIDATE_PREFIX = """from pathlib import Path
import re, sqlite3
from contextlib import closing
root=Path('/data')
with closing(sqlite3.connect(root/'platform.sqlite3')) as registry:
    ids=[row[0] for row in registry.execute('SELECT id FROM households')]
assert len(ids)==2 and 'default' in ids
assert all(uid=='default' or re.fullmatch(r'[a-f0-9]{24}',uid) for uid in ids)
"""
INVALIDATE_BODY = """for uid in ids:
    path=root/'household.sqlite3' if uid=='default' else root/'spaces'/uid/'household.sqlite3'
    with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True)) as con:
        before=dict(con.execute('SELECT id, auth_version FROM users'))
        con.executescript(sql)
        assert dict(con.execute('SELECT id, auth_version FROM users'))=={k:v+1 for k,v in before.items()}
        assert con.execute('SELECT count(*) FROM member_sessions WHERE revoked_at IS NULL').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM cloud_oauth_states').fetchone()[0]==0
        assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
print('Documented member invalidation completed for both synthetic households.')
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Already local immutable sha256 image ID')
    parser.add_argument('--output', required=True, type=Path, help='New private report directory; parent must exist')
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    rehearsal = Rehearsal(args.source_root, args.image, args.output)
    try:
        rehearsal.run()
    except Exception as exc:
        rehearsal.report.update(passed=False, failure={'phase': rehearsal.phase, 'errorType': type(exc).__name__})
    finally:
        rehearsal.cleanup()
    rehearsal.report['completedAt'] = datetime.now(timezone.utc).isoformat()
    # Only write to a directory that this run created; never overwrite an old report.
    if rehearsal.output_created and rehearsal.output.is_dir() and not rehearsal.output.is_symlink():
        path = rehearsal.output / ('report-' + rehearsal.run_id + '.json')
        with path.open('x', encoding='utf-8') as stream:
            json.dump(rehearsal.report, stream, ensure_ascii=False, indent=2)
        path.chmod(0o600)
    print(json.dumps(rehearsal.report, ensure_ascii=False))
    return 0 if rehearsal.report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
