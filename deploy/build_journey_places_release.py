"""Dedicated places image: verified immutable parent plus one pure COPY layer.

No pip, configuration change, network, private data, migration or deployment.
The development orchestration package is delivered as source, not runtime.
"""
from datetime import datetime, timezone
import argparse
import importlib.util
import json
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(SOURCE_ROOT))
from deploy import activate_journey_places_release as C

spec = importlib.util.spec_from_file_location('places_pinned_builder', SOURCE_ROOT / 'deploy/build_static_release.py')
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
need, sha, encoded, plain_file, read_manifest = C.need, C.sha, C.encoded, C.plain_file, C.read_manifest


def build(source, parent, manifest_sha, base_manifest_sha, output, *, runner=None):
    environment = C.host_environment()
    actual = C.command if runner is None else runner
    def frozen_runner(arguments, **kwargs):
        return actual(arguments, env=dict(environment), **kwargs)
    return _build(source, parent, manifest_sha, base_manifest_sha, output, runner=frozen_runner)


def probe_boundary(runner, image, cwd):
    program = C.RUNTIME_BOUNDARY + "\nimport json\nprint(json.dumps({'runtimeBoundaryVerified':True}))\n"
    value = runner(['docker','run','--rm','--network','none','--read-only','--user','10001:10001',
                    '--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','192m','--pids-limit','64',
                    '--entrypoint','python',image,'-c',program], cwd=cwd, timeout=120)
    need(json.loads(value) == {'runtimeBoundaryVerified':True}, 'runtime_boundary')


def _build(source, parent, manifest_sha, base_manifest_sha, output, *, runner):
    source, output = Path(source), Path(output)
    need(source.is_absolute() and source.resolve(strict=True) == source, 'source_path')
    need(output.is_absolute() and output.parent.resolve(strict=True) == output.parent
         and not output.exists() and not output.is_symlink(), 'output_must_be_new')
    manifest, manifest_raw = read_manifest(source / 'RELEASE-MANIFEST.json', manifest_sha)
    base, base_raw = read_manifest(source / 'BASE-MANIFEST.json', base_manifest_sha)
    values = C.source_files(source, manifest['files']); C.bind_modules(values)
    C.validate_changes(base['files'], manifest['files'], sorted(n for n,d in manifest['files'].items() if base['files'].get(n) != d))
    backend, static = C.backend_hashes(manifest['files']), C.static_hashes(manifest['files'])
    need('app.py' in backend and 'requirements.txt' in backend and 'static/index.html' in static, 'source_incomplete')
    parent_expected = {**C.backend_hashes(base['files']), **C.static_hashes(base['files'])}
    before = B.image_info(runner, parent, source)
    env = dict(s.split('=', 1) for s in before['Config'].get('Env', []))
    need(env.get('PYTHONDONTWRITEBYTECODE') == '1' and not env.get('PYTHONPYCACHEPREFIX'), 'source_bytecode_environment')
    probe_boundary(runner, parent, source)
    parent_probe = B.probe(runner, parent, parent_expected, source)
    need(parent_probe == {'hashes':parent_expected, 'backendFiles':sorted(C.backend_hashes(base['files'])),
                          'staticFiles':sorted(C.static_hashes(base['files']))}, 'parent_runtime_differs')
    need(set(parent_probe['staticFiles']) <= set(static), 'static_removal_not_supported')
    C.source_files(source, manifest['files'])
    need(plain_file(source/'RELEASE-MANIFEST.json') == manifest_raw and plain_file(source/'BASE-MANIFEST.json') == base_raw, 'manifest_changed')
    output.mkdir(mode=0o700); context = output/'context'; context.mkdir(mode=0o700)
    runtime = {**backend, **static}
    payload = {'app/'+name:digest for name,digest in runtime.items() if name != 'requirements.txt'}
    recipe = ('FROM '+parent+'\nCOPY --chown=10001:10001 app/ /app/\n').encode('ascii')
    (context/'Dockerfile').write_bytes(recipe)
    for name in payload:
        destination = context/name; destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(values[name.removeprefix('app/')])
    report = {'status':'pending', 'startedAt':datetime.now(timezone.utc).isoformat(), 'output':str(output),
              'mode':C.POLICY.mode, 'parentImage':parent,
              'manifestSha256':manifest_sha, 'baseManifestSha256':base_manifest_sha,
              'sourceHashes':manifest['files'], 'parentRuntimeHashes':parent_expected,
              'candidateRuntimeHashes':runtime, 'runtimeChanges':C.runtime_changes(base['files'],manifest['files']),
              'recipeSha256':sha(recipe), 'parentConfigSha256':sha(encoded(before['Config'])),
              'parentLayers':before['RootFS']['Layers'], 'productionOperations':False, 'pipExecuted':False}
    def record():
        path = output/'build.json'; path.write_bytes(encoded(report)); path.chmod(0o600)
    def frozen():
        need(plain_file(context/'Dockerfile') == recipe, 'recipe_changed')
        found = {p.relative_to(context).as_posix() for p in context.rglob('*') if p.is_file() or p.is_symlink()}
        need(found == set(payload)|{'Dockerfile'}, 'build_context_changed')
        need(all(sha(plain_file(context/name)) == digest for name,digest in payload.items()), 'build_payload_changed')
        C.source_files(source, manifest['files'])
        need(plain_file(source/'RELEASE-MANIFEST.json') == manifest_raw and plain_file(source/'BASE-MANIFEST.json') == base_raw, 'manifest_changed')
    record()
    try:
        frozen()
        iidfile = output/'image.id'
        runner(['docker','build','--network','none','--pull=false','--iidfile',str(iidfile),str(context)], cwd=output, timeout=300)
        image = plain_file(iidfile).decode('ascii').strip()
        after = B.image_info(runner, image, output)
        C.verify_images([before], [after], parent, image)
        child_probe = B.probe(runner, image, runtime, output)
        need(child_probe == {'hashes':runtime, 'backendFiles':sorted(backend), 'staticFiles':sorted(static)}, 'child_runtime_differs')
        probe_boundary(runner, image, output); frozen()
        report.update(status='built', image=image, completedAt=datetime.now(timezone.utc).isoformat(),
                      childLayers=after['RootFS']['Layers'], childConfigSha256=sha(encoded(after['Config'])),
                      parentLayersPreserved=True, configurationUnchanged=True, parentBackendVerified=True,
                      childBackendVerified=True, staticVerified=True, bytecodeExcluded=True)
        record(); return report
    except BaseException as error:
        report.update(status='failed', errorType=type(error).__name__, manualReviewRequired=True); record()
        raise RuntimeError('places_build_failed; inspect_private_build_report') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path); parser.add_argument('parent_image')
    parser.add_argument('manifest_sha256'); parser.add_argument('base_manifest_sha256'); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = build(args.source, args.parent_image, args.manifest_sha256, args.base_manifest_sha256, args.output)
    except Exception:
        print(json.dumps({'status':'failed', 'manualReviewRequired':True})); raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
