"""Run reviewed, bounded pytest groups in an immutable Linux image.

No build, dependency download, Compose, production volume or provider access.
The caller supplies a reviewed groups JSON and its SHA; counts are assertions,
never reused outcomes. Run with python -B on the local Docker host.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

SELF = 'tests/run_places_linux_validation.py'
LABEL = 'org.family-dashboard.places-linux-tests'
PRIOR = Path('/opt/family-dashboard-test-journey-documents-56975378c9e244c5bab40495fdb389b4/result.json')
PRIOR_SHA = '25da3126006089256813b118850ad07c3ca31cf6ae2c19cc25dc9a115f820979'
IMAGE = re.compile(r'sha256:[a-f0-9]{64}\Z')
SUPPORT_DIRS = ('tests', 'deploy', 'docs', '.cursor')
SUPPORT_FILES = ('pytest.ini', 'Dockerfile', 'compose.yaml', 'README.md', 'AGENTS.md',
                 'DESIGN.md', '.dockerignore', '.gitignore')
TOOLS = tuple('tools/inference_orchestrator/'+n+'.py' for n in ('__init__', '__main__', 'client', 'runner'))


def need(value, label):
    if not value:
        raise RuntimeError(label)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_json(path, digest):
    raw = path.read_bytes()
    need(re.fullmatch('[a-f0-9]{64}', digest or '') and hashlib.sha256(raw).hexdigest() == digest, 'json_identity')
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def names(files):
    need(isinstance(files, dict) and bool(files), 'file_map')
    for name, digest in files.items():
        need(isinstance(name, str) and name and '\\' not in name and ':' not in name
             and all(p not in ('', '.', '..') for p in name.split('/'))
             and isinstance(digest, str) and re.fullmatch('[a-f0-9]{64}', digest), 'file_entry')


def tree(root, *, bytecode=False):
    need(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir(), 'tree_root')
    result = {}
    for path in root.rglob('*'):
        need(not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'tree_link')
        need(bytecode or path.suffix not in ('.pyc', '.pyo'), 'tree_bytecode')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def source(root, digest):
    need(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir(), 'source_root')
    files = checked_json(root/'RELEASE-MANIFEST.json', digest)['files']
    names(files)
    actual = tree(root)
    need(all(actual.get(n) == d for n, d in files.items()), 'source_changed')
    need(files.get(SELF) == sha(Path(__file__)), 'runner_source')
    return files


def runtime(files):
    return {n: d for n, d in files.items() if n == 'requirements.txt'
            or n.startswith('static/') or '/' not in n and n.endswith('.py')}


def support(files):
    return {n: d for n, d in files.items() if n in SUPPORT_FILES or n in TOOLS
            or n.startswith(tuple(x+'/' for x in SUPPORT_DIRS))}


def groups(value, files):
    need(isinstance(value, dict) and set(value) == {'groups'}, 'groups_shape')
    items = value['groups']
    need(isinstance(items, list) and 1 <= len(items) <= 2, 'group_count')
    seen, scripts_seen, result = set(), set(), []
    for item in items:
        need(isinstance(item, dict) and {'name', 'scripts', 'expectedCount'} <= set(item)
             and set(item) <= {'name', 'scripts', 'expectedCount', 'timeoutSeconds'}, 'group_shape')
        name, scripts, count = item['name'], item['scripts'], item['expectedCount']
        timeout = item.get('timeoutSeconds', 600)
        need(isinstance(name, str) and re.fullmatch('[a-z][a-z0-9-]{0,23}', name) and name not in seen, 'group_name')
        need(type(count) is int and 1 <= count <= 20000 and type(timeout) is int and 60 <= timeout <= 1800, 'group_limits')
        need(isinstance(scripts, list) and 1 <= len(scripts) <= 100, 'scripts_shape')
        for script in scripts:
            need(isinstance(script, str) and re.fullmatch(r'tests/test_[A-Za-z0-9_]+\.py', script)
                 and script in files and script not in scripts_seen, 'test_script')
            scripts_seen.add(script)
        seen.add(name)
        result.append(dict(name=name, scripts=list(scripts), expectedCount=count, timeoutSeconds=timeout))
    return result


def copy_support(root, target, files):
    target.mkdir(mode=0o755)
    for name, digest in files.items():
        original, copied = root/name, target/name
        need(sha(original) == digest, 'fixture_source')
        copied.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        with copied.open('xb') as stream:
            stream.write(original.read_bytes())
        copied.chmod(0o644)
    need(tree(target) == files, 'fixture_changed')


PROGRAM = r'''
import hashlib,json,platform,sys,sysconfig
from pathlib import Path
cfg=json.loads(sys.argv[1]); root=Path('/app')
def identity():
 return {'version':sys.version,'implementation':sys.implementation.name,'cacheTag':sys.implementation.cache_tag,
         'soabi':sysconfig.get_config_var('SOABI'),'machine':platform.machine()}
def verify():
 assert sys.dont_write_bytecode and sys.pycache_prefix is None
 for p in root.rglob('*'):
  assert not p.is_symlink() and p.suffix not in ('.pyc','.pyo')
 paths=list(root.glob('*.py'))+[root/'requirements.txt']+[p for p in (root/'static').rglob('*') if p.is_file()]
 actual={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 assert actual==cfg['runtime']
 assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in cfg.get('support',{}).items())
 return actual
if cfg['mode']=='python':
 assert sys.dont_write_bytecode and sys.pycache_prefix is None
 print(json.dumps(identity(),sort_keys=True))
else:
 proof={'verified':False,'python':identity()};code=1
 try:
  proof['before']=verify()
  if cfg['mode']=='tests':
   import pytest
   proof['pytestVersion']=pytest.__version__
   code=int(pytest.main(['-q','-r','a','-p','no:cacheprovider','--junitxml=/tmp/targeted.xml',*cfg['scripts']]))
  else: code=0
  proof['after']=verify();proof['verified']=True
 except BaseException as error:
  proof['errorType']=type(error).__name__;code=1
 finally:
  Path('/tmp/runtime-proof.json').write_text(json.dumps(proof,sort_keys=True))
 raise SystemExit(code)
'''


class Docker:
    def __init__(self, run_id):
        self.run_id, self.created, self.proofs = run_id, [], []

    def call(self, args, **kwargs):
        return subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *args],
                              capture_output=True, text=True, timeout=60, check=True, **kwargs)

    def image(self, image):
        need(isinstance(image, str) and IMAGE.fullmatch(image), 'image_id')
        info = json.loads(self.call(['image', 'inspect', image]).stdout)[0]
        need(info['Id'] == image and info['Os'] == 'linux' and not info['Config'].get('Volumes'), 'image_config')

    def inspect_owned(self, name, image):
        info = json.loads(self.call(['container', 'inspect', name]).stdout)[0]
        need(info['Name'] == '/'+name and info['Image'] == image
             and info['Config'].get('Labels', {}).get(LABEL) == self.run_id
             and info['HostConfig']['NetworkMode'] == 'none', 'container_identity')
        return info

    def create(self, image, mounts):
        name = 'fd-places-tests-'+self.run_id+'-'+str(len(self.created)+1)
        need(not self.call(['container', 'ls', '-a', '-q', '--filter', 'name=^/'+name+'$']).stdout.strip(), 'existing_container')
        args = ['container', 'create', '--name', name, '--label', LABEL+'='+self.run_id,
                '--pull', 'never', '--network', 'none', '--read-only', '--user', '10001:10001',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--no-healthcheck',
                '--memory', '768m', '--pids-limit', '256', '--cpus', '2', '--workdir', '/app']
        for src, dst, readonly in mounts:
            need(src.is_absolute() and src.resolve(strict=True) == src and ',' not in str(src), 'mount_source')
            args += ['--mount', 'type=bind,src='+str(src)+',dst='+dst+(',readonly' if readonly else '')]
        if not any(dst == '/tmp' for _, dst, _ in mounts):
            args += ['--tmpfs', '/tmp:rw,noexec,nosuid,size=64m']
        for key, value in {'PYTHONPATH':'/app:/test-deps', 'PYTHONDONTWRITEBYTECODE':'1',
                           'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1', 'DATA_DIR':'/tmp/unused-default',
                           'ASSISTANT_PROVIDER':'local', 'NVIDIA_API_KEY':'', 'NVIDIA_MODEL':'',
                           'OPENAI_API_KEY':'', 'OPENAI_MODEL':'', 'MICROSOFT_CLIENT_ID':'',
                           'MICROSOFT_CLIENT_SECRET':'', 'GOOGLE_CLIENT_ID':'', 'GOOGLE_CLIENT_SECRET':''}.items():
            args += ['--env', key+'='+value]
        return name, args

    def execute(self, image, config, mounts, log, timeout):
        name, args = self.create(image, mounts)
        self.created.append((name, image))  # Account for ambiguous create timeouts.
        self.call([*args, '--entrypoint', 'python', image, '-B', '-c', PROGRAM, json.dumps(config)])
        info = self.inspect_owned(name, image)
        actual = {(m['Source'], m['Destination'], not m['RW']) for m in info['Mounts'] if m['Type'] == 'bind'}
        need(actual == {(str(s), d, r) for s, d, r in mounts}
             and all(m['Type'] in ('bind', 'tmpfs') for m in info['Mounts'])
             and info['Config']['User'] == '10001:10001' and info['HostConfig']['ReadonlyRootfs']
             and not info['HostConfig'].get('Privileged') and not info['HostConfig'].get('PortBindings'), 'container_isolation')
        self.proofs.append({'name':name, 'image':image, 'network':'none', 'user':'10001:10001',
                            'readonlyRootfs':True, 'mounts':[{'source':str(s),'destination':d,'readonly':r} for s,d,r in mounts]})
        with log.open('xb') as stream:
            result = subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', 'start', '-a', name],
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        state = self.inspect_owned(name, image)['State']
        need(not state['Running'] and not state['OOMKilled'], 'container_state')
        return state['ExitCode'] if result.returncode == 0 else result.returncode

    def cleanup(self):
        failures = []
        for name, image in reversed(self.created):
            try:
                listing = ['container', 'ls', '-a', '-q', '--filter', 'name=^/'+name+'$']
                if not self.call(listing).stdout.strip():
                    continue
                info = self.inspect_owned(name, image)
                if info['State']['Running']:
                    self.call(['stop', '--time', '20', name])
                need(not self.inspect_owned(name, image)['State']['Running'], 'cleanup_running')
                self.call(['container', 'rm', name])
                need(not self.call(listing).stdout.strip(), 'cleanup_residual')
            except BaseException as error:
                failures.append({'name':name, 'errorType':type(error).__name__})
        return {'passed':not failures, 'failures':failures, 'resourcesTracked':len(self.created)}


def junit(path, group):
    need(not path.is_symlink() and path.resolve(strict=True) == path, 'junit_path')
    cases = list(ET.parse(path).getroot().iter('testcase'))
    counts = {k:sum(c.find(tag) is not None for c in cases)
              for k, tag in [('failures','failure'), ('errors','error'), ('skipped','skipped')]}
    counts['tests'] = len(cases)
    wanted = {s[:-3].replace('/', '.') for s in group['scripts']}
    counts['scriptsMatched'] = (all(any(c.get('classname','') == s or c.get('classname','').startswith(s+'.') for c in cases) for s in wanted)
        and all(any(c.get('classname','') == s or c.get('classname','').startswith(s+'.') for s in wanted) for c in cases))
    counts['passed'] = sum(not any(c.find(tag) is not None for tag in ('failure','error','skipped')) for c in cases)
    return counts


def run(args):
    need(os.name == 'posix' and sys.dont_write_bytecode and sys.pycache_prefix is None, 'linux_bytecode')
    need(not any(k.upper().startswith(('DOCKER_', 'COMPOSE_')) for k in os.environ), 'host_selector')
    root = args.source
    need(root.parent == Path('/opt') and root.name.startswith('family-dashboard-candidate-journey-places-'), 'candidate_path')
    files = source(root, args.manifest_sha)
    selected = groups(checked_json(args.groups, args.groups_sha), files)
    prior = checked_json(PRIOR, PRIOR_SHA)
    dependencies = prior['dependencyHashes']; names(dependencies)
    deps = PRIOR.parent/'deps'
    need(tree(deps, bytecode=True) == dependencies, 'dependencies_changed')
    need(IMAGE.fullmatch(args.image or '') and IMAGE.fullmatch(prior['image']) and args.image != prior['image'], 'immutable_images')
    run_id = uuid.uuid4().hex
    output = args.output or Path('/opt')/('family-dashboard-places-tests-'+run_id)
    need(output.is_absolute() and output.parent.resolve(strict=True) == output.parent
         and output.parent == Path('/opt') and output.name.startswith('family-dashboard-places-tests-')
         and not output.exists() and not output.is_symlink(), 'new_output')
    output.mkdir(mode=0o700)
    docker = Docker(run_id)
    report = dict(passed=False, runId=run_id, startedAt=datetime.now(timezone.utc).isoformat(),
                  image=args.image, manifestSha256=args.manifest_sha, groupsSha256=args.groups_sha,
                  sourceHashesBefore=files, runs=[], productionWrites=0, productionDataMounted=False,
                  priorDependencyReportSha256=PRIOR_SHA, dependencyHashes=dependencies,
                  dependencyPurpose='Frozen test libraries only; no prior result or backend source reused')
    artifacts = []
    try:
        fixture = output/'fixtures'; fixture_hashes = support(files)
        copy_support(root, fixture, fixture_hashes)
        report['fixtureHashes'] = fixture_hashes
        raw_groups = args.groups.read_bytes()
        need(hashlib.sha256(raw_groups).hexdigest() == args.groups_sha, 'groups_changed')
        (output/'groups.json').write_bytes(raw_groups); artifacts.append(output/'groups.json')
        identities = []
        for label, image in [('prior-python',prior['image']), ('candidate-python',args.image)]:
            docker.image(image)
            log = output/(label+'.log'); artifacts.append(log)
            need(docker.execute(image, {'mode':'python'}, [], log, 60) == 0, 'python_probe')
            identities.append(json.loads(log.read_bytes()))
        need(identities[0] == identities[1], 'python_abi_mismatch')
        report['pythonCompatibility'] = {'verified':True, 'priorImage':prior['image'], 'identity':identities[0]}
        for group in selected:
            need(source(root, args.manifest_sha) == files and tree(fixture) == fixture_hashes, 'inputs_changed')
            need(tree(deps, bytecode=True) == dependencies, 'dependencies_changed')
            folder = output/group['name']; folder.mkdir(mode=0o700); os.chown(folder,10001,10001)
            log, xml, proof = (folder/n for n in ('targeted.log','targeted.xml','runtime-proof.json'))
            artifacts.extend([log,xml,proof])
            item = {**group, 'passed':False}; report['runs'].append(item)
            mounts = [(folder,'/tmp',False), (deps,'/test-deps',True)]
            for entry in sorted(fixture.iterdir()):
                mounts.append((entry,'/app/'+entry.name,True))
            cfg = {'mode':'tests', 'runtime':runtime(files), 'support':fixture_hashes, 'scripts':group['scripts']}
            item['exitCode'] = docker.execute(args.image, cfg, mounts, log, group['timeoutSeconds'])
            item['counts'] = junit(xml, group)
            need(item['counts']['tests'] == group['expectedCount'] and item['counts']['passed'] == group['expectedCount']
                 and item['counts']['scriptsMatched'], 'test_counts')
            need(not proof.is_symlink() and proof.resolve(strict=True) == proof, 'proof_path')
            value = json.loads(proof.read_bytes())
            need(item['exitCode'] == 0 and value['verified'] and value['before'] == value['after'] == runtime(files)
                 and value['python'] == identities[1], 'runtime_proof')
            item.update(passed=True, runtimeVerified=True, pytestVersion=value['pytestVersion'])
        report['passed'] = True
    except BaseException as error:
        report['failure'] = {'errorType':type(error).__name__, 'timeout':isinstance(error,subprocess.TimeoutExpired)}
    finally:
        report['cleanup'] = docker.cleanup()
        report['containers'] = docker.proofs
        try:
            report['sourceHashesAfter'] = source(root, args.manifest_sha)
            report['sourceUnchanged'] = report['sourceHashesAfter'] == files
            report['dependenciesUnchanged'] = tree(deps, bytecode=True) == dependencies
            report['fixturesUnchanged'] = tree(output/'fixtures') == report['fixtureHashes']
            report['groupsUnchanged'] = sha(args.groups) == args.groups_sha
        except BaseException as error:
            report['integrityErrorType'] = type(error).__name__
        report['passed'] = all([report['passed'], report['cleanup']['passed'], report.get('sourceUnchanged'),
                                report.get('dependenciesUnchanged'), report.get('fixturesUnchanged'), report.get('groupsUnchanged')])
        report['records'] = []
        for original in artifacts:
            try:
                need(not original.is_symlink() and original.resolve() == original, 'artifact_path')
                if original.is_file(): report['records'].append({'path':str(original), 'sha256':sha(original)})
            except BaseException as error:
                report['passed'] = False
                report.setdefault('artifactErrors', []).append({'path':str(original), 'errorType':type(error).__name__})
        report['completedAt'] = datetime.now(timezone.utc).isoformat()
        path = output/'result.json'
        with path.open('x', encoding='utf-8') as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2)
        path.chmod(0o600)
    print(json.dumps({'passed':report['passed'], 'report':str(path), 'sha256':sha(path)}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','groups'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--output',type=Path)
    for name in ('manifest-sha','image','groups-sha'): parser.add_argument('--'+name,required=True)
    def interrupted(*_args): raise RuntimeError('interrupted')
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,interrupted)
    raise SystemExit(run(parser.parse_args()))


if __name__ == '__main__':
    main()
