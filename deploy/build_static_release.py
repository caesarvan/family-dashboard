"""Build a static-only image from an already available immutable parent.

No package installation, provider IO, production data or deployment occurs.
The only Dockerfile instruction after FROM copies the frozen static directory.
Proofs bind the complete source manifest, recipe, parent layers, image config,
backend bytes and every resulting static file. Invoke with a new output path:

  python deploy/build_static_release.py SOURCE PARENT_IMAGE MANIFEST_SHA OUTPUT

This builder does not authorize deployment or compare the candidate Dockerfile,
Compose and Nginx files with the installed source. The static release controller
must separately compare its externally approved base manifest and reject changes
to those deployment files before stopping or installing anything.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import re
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(SOURCE_ROOT))

from deploy.activate_journey_documents_release import (
    command, encoded, need, plain_file, read_manifest, sha, source_files,
)
from deploy import activate_journey_documents_release as common
from deploy import release_core as core


PROBE = r'''
import hashlib,json,sys
from pathlib import Path,PurePosixPath
root=Path('/app'); names=json.loads(sys.argv[1]); result={}
for name in names:
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or p.as_posix()!=name:
        raise RuntimeError('invalid_probe_path')
    target=root/name
    if not target.is_file() or target.is_symlink() or not target.resolve().is_relative_to(root):
        raise RuntimeError('invalid_probe_file')
    result[name]=hashlib.sha256(target.read_bytes()).hexdigest()
actual=sorted(str(p.relative_to(root)) for p in root.glob('*.py') if p.is_file())
actual+=['requirements.txt']
static=sorted(str(p.relative_to(root)) for p in (root/'static').rglob('*') if p.is_file())
print(json.dumps({'hashes':result,'backendFiles':sorted(actual),'staticFiles':static}))
'''
BYTECODE_PROBE = core.BYTECODE_CHECK + "\nimport json\nprint(json.dumps({'bytecodeExcluded':True}))\n"


def probe_bytecode(runner, image, cwd):
    raw = runner(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                  '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                  '--memory', '192m', '--pids-limit', '64', '--entrypoint', 'python',
                  image, '-c', BYTECODE_PROBE], cwd=cwd, timeout=120)
    need(json.loads(raw) == {'bytecodeExcluded': True}, 'source_bytecode_unsafe')


def image_info(runner, image, cwd):
    need(isinstance(image, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'invalid_image')
    values = json.loads(runner(['docker', 'image', 'inspect', image], cwd=cwd))
    need(isinstance(values, list) and len(values) == 1, 'image_not_unique')
    value = values[0]
    need(value.get('Id') == image and isinstance(value.get('Config'), dict), 'image_identity')
    rootfs = value.get('RootFS', {})
    layers = rootfs.get('Layers')
    need(rootfs.get('Type') == 'layers' and isinstance(layers, list) and layers
         and all(isinstance(layer, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', layer) for layer in layers), 'image_layers')
    return value


def probe(runner, image, names, cwd):
    output = runner(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                     '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                     '--memory', '192m', '--pids-limit', '64', '--entrypoint', 'python',
                     image, '-c', PROBE, json.dumps(sorted(names))], cwd=cwd, timeout=120)
    value = json.loads(output)
    need(isinstance(value, dict) and set(value) == {'hashes', 'backendFiles', 'staticFiles'}, 'probe_shape')
    return value


def build(source, parent, manifest_sha, output, *, runner=command):
    return _build(source, parent, manifest_sha, output, runner=runner, policy=core.STATIC)


def _build(source, parent, manifest_sha, output, *, runner=command, policy, base_manifest_sha=None):
    core.need(policy in (core.STATIC, core.SOURCE), 'unknown_release_policy')
    source, output = Path(source), Path(output)
    need(source.is_absolute() and source.resolve(strict=True) == source, 'source_path')
    need(output.is_absolute() and output.parent.resolve(strict=True) == output.parent
         and not output.exists() and not output.is_symlink(), 'output_must_be_new')
    manifest, manifest_raw = read_manifest(source / 'RELEASE-MANIFEST.json', manifest_sha)
    read_sources = core.source_files if policy is core.SOURCE else source_files
    values = read_sources(source, manifest['files'])
    need(values.get('deploy/build_static_release.py') == plain_file(Path(__file__))
         and values.get('deploy/activate_journey_documents_release.py') == plain_file(Path(common.__file__)),
         'builder_source_mismatch')
    core.bind_modules(values, [core.CORE] + ([core.SOURCE_ENTRY] if policy is core.SOURCE else []))
    backend = {n: sha(v) for n, v in values.items() if (n.endswith('.py') and '/' not in n) or n == 'requirements.txt'}
    static = {n: sha(v) for n, v in values.items() if n.startswith('static/')}
    need('app.py' in backend and 'requirements.txt' in backend and 'static/index.html' in static, 'source_incomplete')
    base, base_raw = None, None
    if policy is core.SOURCE:
        base, base_raw = read_manifest(source / 'BASE-MANIFEST.json', base_manifest_sha)
        core.validate_changes(base['files'], manifest['files'],
            sorted(n for n, d in manifest['files'].items() if base['files'].get(n) != d), policy=policy)
        parent_expected = {**core.backend_hashes(base['files']), **core.static_hashes(base['files'])}
    else:
        parent_expected = backend
    before = image_info(runner, parent, source)
    if policy is core.SOURCE:
        env = dict(s.split('=', 1) for s in before['Config'].get('Env', []))
        need(env.get('PYTHONDONTWRITEBYTECODE') == '1' and not env.get('PYTHONPYCACHEPREFIX'), 'source_bytecode_environment')
        probe_bytecode(runner, parent, source)
    parent_probe = probe(runner, parent, parent_expected, source)
    need(parent_probe['hashes'] == parent_expected
         and parent_probe['backendFiles'] == sorted(core.backend_hashes(parent_expected)), 'parent_backend_differs')
    if policy is core.SOURCE:
        need(parent_probe['staticFiles'] == sorted(core.static_hashes(parent_expected)), 'parent_static_differs')
    # Removing static assets would leave stale parent files after COPY.
    need(set(parent_probe['staticFiles']) <= set(static), 'static_removal_not_supported')
    read_sources(source, manifest['files'])
    need(plain_file(source / 'RELEASE-MANIFEST.json') == manifest_raw, 'manifest_changed')
    output.mkdir(mode=0o700)
    context = output / 'context'; context.mkdir(mode=0o700)
    payload = static if policy is core.STATIC else {
        'app/' + n: h for n, h in {**backend, **static}.items() if n != 'requirements.txt'}
    copy = 'static/ /app/static/' if policy is core.STATIC else 'app/ /app/'
    recipe = f'FROM {parent}\nCOPY --chown=10001:10001 {copy}\n'.encode('ascii')
    (context / 'Dockerfile').write_bytes(recipe)
    for name in payload:
        path = context / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(values[name if policy is core.STATIC else name[4:]])
    report = {'status': 'building', 'startedAt': datetime.now(timezone.utc).isoformat(),
              'mode': policy.mode, 'parentImage': parent, 'manifestSha256': manifest_sha,
              'sourceHashes': manifest['files'], 'nonStaticRuntimeHashes': backend, 'staticHashes': static,
              'recipeSha256': sha(recipe), 'parentConfigSha256': sha(encoded(before['Config'])),
              'parentLayers': before['RootFS']['Layers'], 'productionOperations': False,
              'pipExecuted': False, 'output': str(output)}
    if policy is core.SOURCE:
        report.update(baseManifestSha256=base_manifest_sha, parentRuntimeHashes=parent_expected,
                      candidateRuntimeHashes={**backend, **static},
                      runtimeChanges=core.runtime_changes(base['files'], manifest['files']))
    report_path = output / 'build.json'

    def record():
        report_path.write_bytes(encoded(report)); report_path.chmod(0o600)

    def frozen_context():
        need(plain_file(context / 'Dockerfile') == recipe, 'recipe_changed')
        found = {p.relative_to(context).as_posix() for p in context.rglob('*') if p.is_file() or p.is_symlink()}
        need(found == set(payload) | {'Dockerfile'}, 'build_context_changed')
        for name, digest in payload.items():
            need(sha(plain_file(context / name)) == digest, 'build_static_changed')
        read_sources(source, manifest['files'])
        need(plain_file(source / 'RELEASE-MANIFEST.json') == manifest_raw, 'manifest_changed')
        if base_raw is not None:
            need(plain_file(source / 'BASE-MANIFEST.json') == base_raw, 'base_manifest_changed')

    record()
    try:
        frozen_context()
        iidfile = output / 'image.id'
        runner(['docker', 'build', '--network', 'none', '--pull=false', '--iidfile', str(iidfile), str(context)],
               cwd=output, timeout=300)
        image = plain_file(iidfile).decode('ascii').strip()
        after = image_info(runner, image, output)
        frozen_context()
        # No RUN, dependency resolution, config changes or alternate base.
        need(after['Config'] == before['Config'], 'image_config_changed')
        layers = after['RootFS']['Layers']
        need(layers[:-1] == before['RootFS']['Layers'] and len(layers) == len(before['RootFS']['Layers']) + 1,
             'image_not_single_static_layer')
        child_probe = probe(runner, image, {**backend, **static}, output)
        need(child_probe['hashes'] == {**backend, **static}
             and child_probe['backendFiles'] == sorted(backend)
             and child_probe['staticFiles'] == sorted(static), 'image_files_differ')
        if policy is core.SOURCE: probe_bytecode(runner, image, output)
        frozen_context()
        report.update(status='built', completedAt=datetime.now(timezone.utc).isoformat(), image=image,
                      childLayers=layers, childConfigSha256=sha(encoded(after['Config'])),
                      parentBackendVerified=True, childBackendVerified=True, staticVerified=True,
                      parentLayersPreserved=True, configurationUnchanged=True)
        if policy is core.SOURCE: report['bytecodeExcluded'] = True
        record()
        return report
    except Exception as error:
        report.update(status='failed', errorType=type(error).__name__, manualReviewRequired=True)
        record()
        raise RuntimeError(policy.prefix + '_build_failed; inspect_private_build_report') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('parent_image')
    parser.add_argument('manifest_sha256')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = build(args.source, args.parent_image, args.manifest_sha256, args.output)
    except Exception:
        print(json.dumps({'status': 'failed', 'manualReviewRequired': True}))
        raise SystemExit(1) from None
    print(json.dumps({k: result[k] for k in ('status', 'image', 'parentImage', 'manifestSha256', 'output')}))


if __name__ == '__main__':
    main()
