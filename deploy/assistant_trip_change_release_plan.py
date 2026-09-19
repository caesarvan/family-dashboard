"""Assemble a new offline candidate and plan; review its returned hash before stage."""
import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import assistant_trip_change_release_package as package
from deploy import assistant_trip_change_release_data as data
from deploy import assistant_trip_change_release_controller as controller
from deploy.membership_release_controller import need, read, regular, relative, put, sha, source_hashes, verify_junit

ENV_SHA256 = controller.SPEC.env_sha256
OPERATORS = controller.SPEC.operators


def assemble(package_dir, package_sha256, build_dir, build_sha256, validation_dir,
             validation_sha256, reviews, reviews_sha256, candidate):
    return _assemble(package_dir, package_sha256, build_dir, build_sha256, validation_dir,
                     validation_sha256, reviews, reviews_sha256, candidate,
                     package=package, controller_type=controller.Controller)


def _assemble(package_dir, package_sha256, build_dir, build_sha256, validation_dir,
              validation_sha256, reviews, reviews_sha256, candidate, *, package, controller_type):
    # Callers are fixed Python entry points; no profile/module name comes from JSON or CLI.
    spec = controller_type.SPEC
    need(package.BASELINE == spec.baseline, 'entry_profile_mismatch')
    package_dir, build_dir, validation_dir = [regular(p, directory=True) for p in (package_dir, build_dir, validation_dir)]
    verified = package.verify_package(package_dir, package_sha256)
    meta = verified['metadata']
    build = read(build_dir / 'build.json', build_sha256)
    validation = read(validation_dir / 'validation.json', validation_sha256)
    reviews_path = regular(reviews)
    review_files = read(reviews_path, reviews_sha256)
    need(isinstance(review_files, dict) and review_files, 'reviews_required')
    candidate = Path(candidate).absolute()
    regular(candidate.parent, directory=True)
    need(not candidate.exists() and not any(candidate.is_relative_to(p) or p.is_relative_to(candidate)
        for p in (package_dir, build_dir, validation_dir, reviews_path.parent)), 'candidate_must_be_new_and_separate')
    need(build.get('exitCode') == 0 and validation.get('allPassed') is True and validation.get('exitCode') == 0,
         'build_or_validation_failed')
    for evidence in (build, validation):
        need(evidence.get('packageSha256') == package_sha256 and evidence.get('sourceHead') == meta['sourceHead']
             and evidence.get('tree') == meta['tree'] and evidence.get('manifestSha256') == meta['manifestSha256'],
             'evidence_package_changed')
    need(build['imageId'] == validation['imageId'], 'evidence_image_changed')
    # All writes are exclusive; any partially assembled directory is retained.
    candidate.mkdir(mode=0o700)
    def copy(source, name, digest=None):
        raw = regular(source).read_bytes()
        need(digest is None or sha(raw) == digest, 'assembly_input_changed')
        target = candidate / relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        put(target, raw)
        return sha(raw)
    for name, digest in [('package.json', package_sha256), ('release-manifest.json', meta['manifestSha256']),
                         ('release.tar.gz', meta['archiveSha256'])]:
        copy(package_dir / name, 'package/' + name, digest)
    copy(package_dir / 'build-evidence.json', 'package/build-evidence.json')
    for name, raw in verified['blobs'].items():
        target = candidate / 'source' / relative(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        put(target, raw)
    copy(package_dir / 'release-manifest.json', 'source/RELEASE-MANIFEST.json', meta['manifestSha256'])
    # This subtree is bind-mounted read-only as /release for uid 10001. It
    # contains public source only; private package/reviews/env stay outside it.
    source = candidate / 'source'
    for path in (source, *source.rglob('*')):
        regular(path, directory=path.is_dir())
        path.chmod(0o755 if path.is_dir() else 0o644)
    copy(build_dir / 'build.json', 'build/build.json', build_sha256)
    copy(validation_dir / 'validation.json', 'validation/validation.json', validation_sha256)
    for name, digest in validation['evidence'].items():
        copy(validation_dir / relative(name), 'validation/' + name, digest)
    review_hashes = {}
    for name, path in review_files.items():
        review_hashes['reviews/' + relative(name)] = copy(Path(path), 'reviews/' + name)
    junit = candidate / 'validation' / relative(validation['junitPath'])
    need(validation['junitPath'] in validation['evidence'], 'unbound_junit')
    cases = list(ET.fromstring(regular(junit).read_bytes()).iter('testcase'))
    identities = [[c.get('classname'), c.get('name')] for c in cases]
    # Exact allowed skips come from the independently reviewed selection, which
    # must be supplied as one review file named selection.json and hash-bound.
    selection = read(candidate / 'reviews/selection.json')
    need(sha((candidate / 'reviews/selection.json').read_bytes()) == validation['selectionSha256']
         and selection['sourceHead'] == meta['sourceHead'] and selection['manifestSha256'] == meta['manifestSha256'],
         'selection_changed')
    package.builder.selection_record((candidate / 'reviews/selection.json').read_bytes(), validation['selectionSha256'], meta)
    package.builder.junit_result(junit, selection)
    allowed = []
    for node, reason in selection['allowedSkips'].items():
        module, *parts = node.split('::')
        allowed.append({'classname': module[:-3].replace('/', '.') + ''.join('.' + p for p in parts[:-1]),
                        'name': parts[-1], 'message': reason})
    # Preserve JUnit order for the shared controller's exact skip comparison.
    allowed.sort(key=lambda item: identities.index([item['classname'], item['name']]))
    verify_junit(junit, identities, allowed)
    plan = {'schemaVersion': 1, 'kind': spec.plan_kind, 'packageSha256': package_sha256,
            'imageId': build['imageId'], 'parentImage': package.PARENT_IMAGE, 'webImage': controller.WEB_IMAGE,
            'oldManifestSha256': package.OLD_MANIFEST, 'envSha256': spec.env_sha256,
            'controllerSha256': sha(regular(Path(__file__).with_name(spec.controller_file)).read_bytes()),
            'packageVerifierSha256': sha(regular(Path(package.package.__file__)).read_bytes()),
            'operatorHashes': {'deploy/' + n: sha(regular(Path(__file__).with_name(n)).read_bytes()) for n in spec.operators},
            'membershipMarkerSha256': data.MEMBERSHIP_MARKER_SHA256,
            'reviews': review_hashes, 'testCases': identities, 'allowedSkips': allowed,
            'build': {'path': 'build/build.json', 'sha256': build_sha256},
            'validation': {'path': 'validation/validation.json', 'sha256': validation_sha256}}
    source_hashes(candidate / 'source', verified['manifest']['files'], exact=True)
    put(candidate / 'release-plan.json', plan)
    digest = sha((candidate / 'release-plan.json').read_bytes())
    check = controller_type(candidate, digest)
    check.validate_evidence()  # Read-only originals; no Docker call.
    need(package.verify_package(package_dir, package_sha256) == verified, 'original_package_changed')
    return {'candidate': str(candidate), 'planSha256': digest, 'sourceHead': meta['sourceHead'],
            'imageId': build['imageId'], 'assembled': True, 'reviewRequired': True, 'productionOperations': False}


def main(argv=None, *, assemble_fn=assemble):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('package-dir', 'package-sha256', 'build-dir', 'build-sha256', 'validation-dir',
                  'validation-sha256', 'reviews', 'reviews-sha256', 'candidate'):
        parser.add_argument('--' + field, required=True)
    print(json.dumps(assemble_fn(**vars(parser.parse_args(argv)))))


if __name__ == '__main__':
    main()
