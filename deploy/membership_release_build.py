"""Build one fixed-parent image and validate its actual runtime in isolation.

No SSH, installation, production mounts, migration, activation or backup.
Outputs are exclusive per attempt; failed attempts are retained.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

if __package__ in (None, ''):
    sys.path.append(str(Path(__file__).resolve().parents[1]))
from deploy import membership_release_package as package

SELF = 'deploy/membership_release_build.py'
DEPS = '/opt/family-dashboard-candidates/media-25c9f20/test-deps-retry2'
DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
need, sha, encoded = package.need, package.digest, package.encoded
SCHEMA_BINDINGS = (
    ('check_finance_receipt_migration', 'finance_hub'),
    ('check_investment_operation_migration', 'investment_operations'),
    ('check_finance_accounts_migration', 'finance_accounts'),
    ('check_household_members_migration', 'household_members'),
)


def tree_hashes(root, *, dependencies=False):
    root = package.checked(Path(root).absolute(), True)
    found, total = {}, 0
    for folder, dirs, files in os.walk(root):
        for name in dirs:
            package.checked(Path(folder) / name, True)
        for name in files:
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            need(dependencies or path.suffix not in ('.pyc', '.pyo'), 'unexpected source bytecode')
            raw = package.plain(path)
            total += len(raw)
            need(total <= 400_000_000 and len(found) < 15000, 'tree size exceeded')
            found[relative] = sha(raw)
    package.names_unique(list(found))
    return found


def save(path, raw, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    package.write_new(path, raw)
    path.chmod(mode)


def new_output(path, *inputs):
    path = Path(path).absolute()
    need('..' not in path.parts and not path.exists(), 'new output directory required')
    package.checked(path.parent, True)
    need(not any(path.is_relative_to(Path(p).absolute()) for p in inputs), 'output overlaps input')
    path.mkdir(mode=0o700)
    return path


def checked_package(directory, digest, *, baseline=None):
    value = package.verify_package(directory, digest, **package.baseline_kwargs(baseline))
    need(value['blobs'].get(SELF) == package.plain(Path(__file__).absolute()), 'executed builder differs from package')
    return value


def image_id(value):
    need(isinstance(value, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', value), 'immutable image ID required')
    return value


def selection_record(raw, digest, meta):
    need(sha(raw) == package.checksum(digest), 'selection hash differs')
    value = package.json_value(raw)
    need(set(value) == {'schemaVersion', 'sourceHead', 'manifestSha256', 'modules', 'nodeids', 'allowedSkips'}
         and value['schemaVersion'] == 1 and value['sourceHead'] == meta['sourceHead']
         and value['manifestSha256'] == meta['manifestSha256'], 'selection identity differs')
    modules, nodes, skips = value['modules'], value['nodeids'], value['allowedSkips']
    need(isinstance(modules, list) and modules and len(modules) == len(set(modules)), 'invalid module list')
    need(all(isinstance(n, str) and re.fullmatch(r'tests/test_[a-zA-Z0-9_]+\.py', n)
             and n in meta['sourceFiles'] for n in modules), 'test module outside package')
    need(isinstance(nodes, list) and nodes and len(nodes) <= 10000 and len(nodes) == len(set(nodes)), 'invalid node set')
    need(all(isinstance(n, str) and 0 < len(n) < 2000 and n.split('::', 1)[0] in modules and '::' in n
             and all(ord(c) >= 32 for c in n) for n in nodes), 'invalid node ID')
    need(set(n.split('::', 1)[0] for n in nodes) == set(modules), 'empty selected module')
    need(isinstance(skips, dict) and set(skips) <= set(nodes)
         and all(isinstance(v, str) and 0 < len(v) <= 1000 for v in skips.values()), 'invalid skip allowlist')
    return value


class Executor:
    """Only the local Unix Docker daemon; preserve every command's raw output."""
    def __init__(self, output):
        self.output, self.records = Path(output), []

    def __call__(self, args, *, cwd=None, timeout=120):
        need(sys.platform == 'linux' and sys.dont_write_bytecode and not sys.flags.optimize,
             'use Linux python -B without optimization')
        started = time.monotonic()
        try:
            result = subprocess.run(DOCKER + args, cwd=cwd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            result = subprocess.CompletedProcess(DOCKER + args, 124, error.stdout or b'', error.stderr or b'')
        index = f'commands/{len(self.records):03d}'
        for kind in ('stdout', 'stderr'):
            save(self.output / (index + '.' + kind), getattr(result, kind))
        self.records.append({'arguments': DOCKER + args, 'exitCode': result.returncode,
                             'seconds': time.monotonic() - started, 'stdout': index + '.stdout', 'stderr': index + '.stderr'})
        save(self.output / (index + '.json'), encoded(self.records[-1]))
        return result


def must(result, message):
    need(result.returncode == 0, message)
    return result.stdout


def inspect_image(run, image):
    value = json.loads(must(run(['image', 'inspect', image_id(image)]), 'image inspect failed'))
    need(isinstance(value, list) and len(value) == 1 and value[0]['Id'] == image, 'image identity differs')
    return value[0]


def isolated(run, image, program, *, mounts=(), env=(), writable=False, timeout=120):
    args = ['create', '--network', 'none', '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--memory', '1024m', '--pids-limit', '256',
            '--workdir', '/app', '--entrypoint', 'python']
    if writable:
        args += ['--tmpfs', '/tmp:rw,size=805306368,mode=1777']
    for key, value in env:
        args += ['--env', key + '=' + value]
    for host, target, readonly in mounts:
        need(',' not in str(host) and '\n' not in str(host), 'unsafe bind mount path')
        args += ['--mount', f'type=bind,src={host},dst={target}' + (',readonly' if readonly else '')]
    created = must(run([*args, image_id(image), '-B', '-c', program]), 'isolated container creation failed').decode().strip()
    need(re.fullmatch('[a-f0-9]{64}', created), 'unexpected created container ID')
    try:
        return run(['start', '--attach', created], timeout=timeout)
    finally:
        must(run(['rm', '--force', created]), 'owned temporary container cleanup failed')


PROBE = """from pathlib import Path
import hashlib,json
root=Path('/app'); result={}
for p in root.rglob('*'):
 if p.is_symlink() or p.suffix in ('.pyc','.pyo'): raise RuntimeError('unsafe runtime file')
 if p.is_file(): result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(result,sort_keys=True))
"""


def build(package_dir, package_sha256, output_dir, *, runner=None, baseline=None):
    verified = checked_package(package_dir, package_sha256, **package.baseline_kwargs(baseline))
    meta = verified['metadata']
    output = new_output(output_dir, package_dir)
    run = runner or Executor(output)
    parent_image = package.baseline_values(baseline)[1]
    parent = inspect_image(run, parent_image)
    parent_user = parent.get('Config', {}).get('User')
    # Restore the inspected parent user verbatim, but accept only a closed
    # single-line USER name/ID[:group] grammar (no directives or expansion).
    user_part = r'(?:[a-z_][a-z0-9_-]{0,31}|[0-9]{1,10})'
    need(isinstance(parent_user, str) and re.fullmatch(user_part + r'(?::' + user_part + r')?', parent_user),
         'unsafe parent image user')
    context = output / 'context'
    for name in meta['runtimeFiles']:
        save(context / 'runtime' / name, verified['blobs'][name])
    cleanup = ("from pathlib import Path; import shutil; p=Path('/app/static/experience'); "
               "assert p.is_dir() and p.resolve()==Path('/app/static/experience'); "
               "assert not any(v.is_symlink() for v in [p,*p.parents,*p.rglob('*')]); shutil.rmtree(p)")
    recipe = ('FROM ' + parent_image + '\nUSER 0\nRUN python -B -c ' + shlex.quote(cleanup)
              + '\nUSER ' + parent_user + '\nCOPY --chown=10001:10001 runtime/ /app/\n')
    save(context / 'Dockerfile', recipe.encode('ascii'))
    need(tree_hashes(context / 'runtime') == meta['runtimeFiles'], 'context runtime differs')
    result = run(['build', '--network=none', '--pull=false', '--iidfile', str(output / 'image-id'), '.'],
                 cwd=context, timeout=1800)
    save(output / 'build.log', result.stdout + b'\n' + result.stderr)
    must(result, 'isolated image build failed; retain this attempt')
    child_id = image_id(package.plain(output / 'image-id', 100).decode().strip())
    child = inspect_image(run, child_id)
    before, after = parent['RootFS']['Layers'], child['RootFS']['Layers']
    need(len(after) == len(before) + 2 and after[:-2] == before, 'child must add exactly cleanup and COPY layers')
    config = lambda image: {k: v for k, v in image['Config'].items() if k != 'Image'}
    need(config(parent) == config(child), 'parent image configuration changed')
    actual = json.loads(must(isolated(run, child_id, PROBE), 'child runtime inspection failed'))
    need(actual == meta['runtimeFiles'], 'child runtime bytes differ')
    need(tree_hashes(context / 'runtime') == actual, 'context changed during build')
    need(checked_package(package_dir, package_sha256, **package.baseline_kwargs(baseline)) == verified, 'package changed during build')
    record = {'schemaVersion': 1, 'imageId': child_id, 'sourceHead': meta['sourceHead'], 'tree': meta['tree'],
              'packageSha256': package_sha256, 'manifestSha256': meta['manifestSha256'],
              'parentImage': parent_image, 'parentConfig': config(parent), 'addedLayers': 2,
              'runtimeHashes': actual, 'dockerfileSha256': sha(recipe.encode('ascii')), 'exitCode': 0,
              'completedAt': datetime.now(timezone.utc).isoformat(), 'productionOperations': False}
    save(output / 'build.json', encoded(record))
    if isinstance(run, Executor):
        save(output / 'commands.json', encoded({'commands': run.records}))
    return record


def loaded_modules(runtime, expected):
    result = {}
    for filename in sorted(expected):
        if '/' in filename or not filename.endswith('.py'):
            continue
        name = filename[:-3]
        path = Path(importlib.import_module(name).__file__).resolve()
        need(path == (runtime / filename).resolve(), 'root module shadowed: ' + name)
        result[name] = str(path)
    return result


def schema_bindings(support, runtime, expected):
    result = []
    for helper_name, module_name in SCHEMA_BINDINGS:
        relative = 'deploy/' + helper_name + '.py'
        if relative not in expected:
            continue
        helper = importlib.import_module('deploy.' + helper_name)
        module = importlib.import_module(module_name)
        need(Path(helper.__file__).resolve() == (support / relative).resolve()
             and helper.ROOT.resolve() == support.resolve() and getattr(helper, module_name) is module,
             'schema helper source binding differs')
        helper.ROOT = runtime
        schema = helper.schema_definition()
        need(schema['sourceSha256'] == expected[module_name + '.py'], 'schema runtime hash differs')
        result.append((helper, module_name, schema))
    return result


class SelectionPlugin:
    def __init__(self, selection):
        self.selection, self.collected, self.deselected, self.reports = selection, [], [], {}

    def pytest_collection_modifyitems(self, session, config, items):
        self.collected = [item.nodeid for item in items]
        need(len(self.collected) == len(set(self.collected)) and set(self.collected) == set(self.selection['nodeids']),
             'actual collection differs from frozen node set')

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    def pytest_runtest_logreport(self, report):
        value = {'when': report.when, 'outcome': report.outcome, 'xfail': hasattr(report, 'wasxfail')}
        if report.skipped:
            reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
            value['reason'] = reason.removeprefix('Skipped: ')
        self.reports.setdefault(report.nodeid, []).append(value)

    def accepted(self):
        if self.deselected or set(self.reports) != set(self.selection['nodeids']):
            return False
        for node, reports in self.reports.items():
            if any(r['xfail'] or r['outcome'] == 'failed' for r in reports):
                return False
            skips = [r['reason'] for r in reports if r['outcome'] == 'skipped']
            if skips:
                if skips != [self.selection['allowedSkips'].get(node)]:
                    return False
            elif not any(r['when'] == 'call' and r['outcome'] == 'passed' for r in reports):
                return False
        return True


def container_validate(runtime=Path('/app'), support=Path('/test-support'), proof=Path('/proof'),
                       inputs=Path('/validation-inputs'), dependencies=Path('/test-deps')):
    """Container entry; explicit path arguments support real isolated unit fixtures."""
    request = package.json_value((inputs / 'request.json').read_bytes())
    expected, selection = request['runtimeFiles'], request['selection']
    evidence = {'before': {}, 'after': {}, 'loadedBefore': {}, 'loadedAfter': {},
                'sourceBefore': {}, 'sourceAfter': {}, 'runtimeVerifiedBefore': False, 'runtimeVerifiedAfter': False}
    code = 1
    try:
        source = tree_hashes(support)
        manifest_sha = source.pop('RELEASE-MANIFEST.json')
        need(manifest_sha == request['manifestSha256'] and source == request['sourceFiles'], 'test-support differs')
        evidence.update(before=tree_hashes(runtime), sourceBefore=source)
        need(evidence['before'] == expected, 'actual /app runtime differs')
        need(tree_hashes(dependencies, dependencies=True) == request['dependencies'], 'test dependencies differ')
        evidence['loadedBefore'] = loaded_modules(runtime, expected)
        bindings = schema_bindings(support, runtime, source)
        evidence['runtimeVerifiedBefore'] = True
        import pytest
        need(Path(pytest.__file__).resolve() == (dependencies / 'pytest/__init__.py').resolve(),
             'pytest must come from the explicit dependency mount')
        plugin = SelectionPlugin(selection)
        code = int(pytest.main(['-q', '-p', 'no:cacheprovider', '--import-mode=append', '--rootdir=' + str(support),
                               '--junitxml=' + str(proof / 'results.xml'),
                               *[str(support / n) for n in selection['nodeids']]], plugins=[plugin]))
        evidence.update(collected=plugin.collected, deselected=plugin.deselected, reports=plugin.reports)
        evidence['loadedAfter'] = loaded_modules(runtime, expected)
        evidence['after'] = tree_hashes(runtime)
        after = tree_hashes(support)
        need(after.pop('RELEASE-MANIFEST.json') == manifest_sha, 'source manifest changed')
        evidence['sourceAfter'] = after
        need(evidence['after'] == expected and after == source, 'runtime/source changed during validation')
        need(tree_hashes(dependencies, dependencies=True) == request['dependencies'], 'test dependencies changed')
        for helper, module_name, schema in bindings:
            need(helper.ROOT == runtime and getattr(helper, module_name) is sys.modules[module_name]
                 and helper.schema_definition() == schema, 'schema binding changed during validation')
        need(plugin.accepted(), 'unapproved skip, deselection, failed/missing test report')
        evidence['runtimeVerifiedAfter'] = True
    except Exception as error:
        evidence['error'] = str(error)
        traceback.print_exc()
        code = 1
    finally:
        evidence['pytestExitCode'] = code
        save(proof / 'runtime.json', encoded(evidence))
    return code


def junit_result(path, selection):
    root = ET.fromstring(package.plain(path))
    cases = root.findall('.//testcase')
    need(len(cases) == len(selection['nodeids']), 'JUnit count differs')
    identities = [(c.get('classname'), c.get('name')) for c in cases]
    need(len(identities) == len(set(identities)), 'duplicate JUnit test')
    expected = []
    for node in selection['nodeids']:
        module, *parts = node.split('::')
        expected.append((module[:-3].replace('/', '.') + ''.join('.' + p for p in parts[:-1]), parts[-1]))
    need(set(identities) == set(expected), 'JUnit node identities differ')
    need(not root.findall('.//failure') and not root.findall('.//error'), 'JUnit failure/error')
    skipped = sum(c.find('skipped') is not None for c in cases)
    return {'tests': len(cases), 'passed': len(cases) - skipped, 'skipped': skipped, 'failures': 0, 'errors': 0}


def validate(package_dir, package_sha256, image_id, selection, selection_sha256, output_dir,
             pytest_dependencies=DEPS, *, runner=None, baseline=None):
    verified = checked_package(package_dir, package_sha256, **package.baseline_kwargs(baseline))
    meta = verified['metadata']
    frozen = selection_record(package.plain(selection, 4_000_000), selection_sha256, meta)
    dependencies = package.checked(Path(pytest_dependencies).absolute(), True)
    dep_hashes = tree_hashes(dependencies, dependencies=True)
    need('pytest/__init__.py' in dep_hashes, 'existing pytest dependencies required')
    output = new_output(output_dir, package_dir, dependencies)
    run = runner or Executor(output)
    inspect_image(run, image_id)
    support, proof, inputs = output / 'source', output / 'proof', output / 'inputs'
    proof.mkdir(mode=0o777); proof.chmod(0o777)
    for name, raw in verified['blobs'].items():
        save(support / name, raw)
    save(support / 'RELEASE-MANIFEST.json', package.plain(Path(package_dir).absolute() / 'release-manifest.json'))
    request = {'runtimeFiles': meta['runtimeFiles'], 'sourceFiles': verified['manifest']['files'],
               'manifestSha256': meta['manifestSha256'], 'selection': frozen, 'dependencies': dep_hashes}
    save(inputs / 'request.json', encoded(request))
    env = [('PYTHONPATH', '/app:/test-support:/test-deps'), ('PYTHONDONTWRITEBYTECODE', '1'),
           ('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1'), ('DATA_DIR', '/tmp/membership-validation'),
           ('ASSISTANT_PROVIDER', 'openai')]
    env += [(k, '') for k in ('NVIDIA_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
                              'MICROSOFT_CLIENT_ID', 'MICROSOFT_CLIENT_SECRET', 'PYTEST_ADDOPTS')]
    program = 'from deploy.membership_release_build import container_validate; raise SystemExit(container_validate())'
    result = isolated(run, image_id, program, mounts=((support, '/test-support', True),
        (dependencies, '/test-deps', True), (inputs, '/validation-inputs', True), (proof, '/proof', False)),
        env=env, writable=True, timeout=3600)
    save(proof / 'validation.log', result.stdout + b'\n' + result.stderr)
    passed, counts, error = False, {}, None
    try:
        runtime = package.json_value(package.plain(proof / 'runtime.json', 4_000_000))
        expected_loaded = {n[:-3]: '/app/' + n for n in meta['runtimeFiles'] if '/' not in n and n.endswith('.py')}
        need(result.returncode == 0 and runtime['pytestExitCode'] == 0 and runtime['runtimeVerifiedBefore'] is True
             and runtime['runtimeVerifiedAfter'] is True, 'container validation failed')
        need(runtime['before'] == runtime['after'] == meta['runtimeFiles']
             and runtime['sourceBefore'] == runtime['sourceAfter'] == verified['manifest']['files']
             and runtime['loadedBefore'] == runtime['loadedAfter'] == expected_loaded, 'runtime/source evidence differs')
        need(set(runtime['collected']) == set(frozen['nodeids']) and len(runtime['collected']) == len(frozen['nodeids'])
             and runtime['deselected'] == [], 'collection evidence differs')
        plugin = SelectionPlugin(frozen); plugin.reports = runtime['reports']
        need(plugin.accepted(), 'unapproved result evidence')
        counts = junit_result(proof / 'results.xml', frozen)
        need(tree_hashes(dependencies, dependencies=True) == dep_hashes, 'dependency bytes changed')
        current_source = tree_hashes(support)
        need(current_source.pop('RELEASE-MANIFEST.json') == meta['manifestSha256']
             and current_source == verified['manifest']['files'], 'host source bytes changed')
        need(checked_package(package_dir, package_sha256, **package.baseline_kwargs(baseline)) == verified, 'package changed during validation')
        passed = True
    except Exception as failure:
        error = str(failure)
    evidence = {'proof/' + p.name: sha(package.plain(p)) for p in proof.iterdir() if p.is_file()}
    record = {'schemaVersion': 1, 'imageId': image_id, 'sourceHead': meta['sourceHead'], 'tree': meta['tree'],
              'packageSha256': package_sha256, 'manifestSha256': meta['manifestSha256'],
              'exitCode': 0 if passed else (result.returncode or 1), 'containerExitCode': result.returncode,
              'allPassed': passed, 'error': error, 'counts': counts, 'evidence': evidence,
              'junitPath': 'proof/results.xml', 'runtimePath': 'proof/runtime.json',
              'selectionSha256': selection_sha256, 'dependencyHashes': dep_hashes,
              'completedAt': datetime.now(timezone.utc).isoformat(), 'productionOperations': False}
    save(output / 'validation.json', encoded(record))
    if isinstance(run, Executor):
        save(output / 'commands.json', encoded({'commands': run.records}))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for name in ('build', 'validate'):
        command = commands.add_parser(name)
        for field in ('package-dir', 'package-sha256', 'output-dir'):
            command.add_argument('--' + field, required=True)
        if name == 'validate':
            for field in ('image-id', 'selection', 'selection-sha256'):
                command.add_argument('--' + field, required=True)
            command.add_argument('--pytest-dependencies', default=DEPS)
    args = vars(parser.parse_args()); action = args.pop('action')
    result = build(**args) if action == 'build' else validate(**args)
    print(json.dumps(result))
    raise SystemExit(0 if result.get('allPassed', True) else 1)


if __name__ == '__main__':
    main()
