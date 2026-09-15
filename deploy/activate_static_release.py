"""Strict static-only entry. Shared mechanics do not relax its source policy."""
import argparse
from pathlib import Path
import signal
import json
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import release_core as core
from deploy.release_core import (ROOT, RELEASES, VOLUME, HELPER, CONTROLLER, REQUIRED,
    TOOLS, DEPENDENCIES, ANONYMOUS_PATHS, CONTAINER_CODE, READBACK_CODE,
    need, sha, encoded, put, source_files, backend_hashes, static_hashes,
    command, release_lock, verify_images, verify_http, host_environment)


def validate_changes(base, candidate, changed):
    return core.validate_changes(base, candidate, changed, policy=core.STATIC)


def evidence(candidate, ready, hashes, image):
    return core.evidence(candidate, ready, hashes, image, policy=core.STATIC)


def activate(candidate_root, image, manifest_sha, ready_sha, *, root=ROOT, releases=RELEASES,
             project='family-dashboard', volume=VOLUME, runner=command):
    return core.activate(candidate_root, image, manifest_sha, ready_sha, root=root,
        releases=releases, project=project, volume=volume, runner=runner, policy=core.STATIC)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('image')
    parser.add_argument('manifest_sha256')
    parser.add_argument('ready_sha256')
    args = parser.parse_args(argv)

    def interrupted(*unused):
        raise RuntimeError('release_signal_interrupted')

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        result = activate(args.candidate, args.image, args.manifest_sha256, args.ready_sha256)
    except BaseException:
        raise SystemExit('static_release_failed; inspect the private release record; no automatic restore') from None
    # The full private record stays on disk. No configuration values on stdout.
    print(json.dumps({k: result[k] for k in ('status', 'phase', 'image', 'publishedAt', 'releaseDirectory')}))


if __name__ == '__main__':
    main()
