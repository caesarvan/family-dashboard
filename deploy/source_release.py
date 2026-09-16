"""Explicitly reviewed Python/static updates on the unchanged 43-table schema.

Build, rehearse and activate are separate operations. No command accepts a
policy from READY, installs dependencies, warms a schema or restores a database.
Production activation requires independently approved evidence and permission.
"""
import argparse
import json
from pathlib import Path
import signal
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import release_core as core


def validate_changes(base, candidate, changed):
    return core.validate_changes(base, candidate, changed, policy=core.SOURCE)


def evidence(candidate, ready, hashes, image):
    return core.evidence(candidate, ready, hashes, image, policy=core.SOURCE)


def activate(candidate_root, image, manifest_sha, ready_sha, *, root=core.ROOT,
             releases=core.RELEASES, project='family-dashboard', volume=core.VOLUME,
             runner=core.command):
    return core.activate(candidate_root, image, manifest_sha, ready_sha, root=root,
        releases=releases, project=project, volume=volume, runner=runner, policy=core.SOURCE)


def build(source, parent, manifest_sha, base_manifest_sha, output, *, runner=None):
    from deploy import build_static_release as builder
    environment = core.host_environment()
    actual = core.command if runner is None else runner

    def frozen_runner(args, **kwargs):
        return actual(args, env=dict(environment), **kwargs)

    return builder._build(source, parent, manifest_sha, output,
        policy=core.SOURCE, base_manifest_sha=base_manifest_sha, runner=frozen_runner)


def rehearsal(source, manifest_sha, parent, image, build_proof, proof_sha, nginx_image,
              output, *, base_source, base_manifest_sha, runner=None):
    from deploy import rehearse_static_release as shared

    class SourceRehearsal(shared.Rehearsal):
        policy = core.SOURCE

    run = SourceRehearsal(source, manifest_sha, parent, image, build_proof, proof_sha,
                          nginx_image, output, runner=runner)
    run.base_source = Path(base_source)
    core.need(run.base_source.is_absolute() and run.base_source.resolve(strict=True) == run.base_source
              and not run.output.is_relative_to(run.base_source)
              and not run.base_source.is_relative_to(run.output)
              and run.base_source != run.source, 'separate_base_source')
    core.need(core.hash_string(base_manifest_sha), 'base_manifest_sha')
    run.base_manifest_sha = base_manifest_sha
    return run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    a = commands.add_parser('activate', help='Separately authorized production activation')
    for name in ('candidate', 'image', 'manifest_sha256', 'ready_sha256'): a.add_argument(name)
    b = commands.add_parser('build', help='Isolated immutable parent + one COPY layer')
    for name in ('source', 'parent_image', 'manifest_sha256', 'base_manifest_sha256', 'output'): b.add_argument(name)
    r = commands.add_parser('rehearse', help='New synthetic two-household Docker resources')
    for name in ('source', 'manifest-sha256', 'parent-image', 'image', 'build-proof',
                 'build-proof-sha256', 'nginx-image', 'output', 'base-source', 'base-manifest-sha256'):
        r.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)

    def interrupted(*unused): raise RuntimeError('source_release_interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, interrupted)
    try:
        if args.command == 'activate':
            value = activate(args.candidate, args.image, args.manifest_sha256, args.ready_sha256)
            result = {k: value[k] for k in ('status', 'phase', 'image', 'publishedAt', 'releaseDirectory')}
        elif args.command == 'build':
            value = build(args.source, args.parent_image, args.manifest_sha256, args.base_manifest_sha256, args.output)
            result = {k: value[k] for k in ('status', 'image', 'parentImage', 'manifestSha256', 'baseManifestSha256', 'output')}
        else:
            run = rehearsal(args.source, args.manifest_sha256, args.parent_image, args.image,
                args.build_proof, args.build_proof_sha256, args.nginx_image, args.output,
                base_source=args.base_source, base_manifest_sha=args.base_manifest_sha256)
            value = run.execute()
            result = {'passed': value['passed'], 'runId': run.run_id,
                      'report': str(run.output / 'source-rehearsal.json')}
            print(json.dumps(result)); return 0 if value['passed'] else 1
    except BaseException:
        print(json.dumps({'status': 'failed', 'manualReviewRequired': True,
                          'automaticRestoreAttempted': False}))
        return 1
    print(json.dumps(result)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
