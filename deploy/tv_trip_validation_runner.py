"""Run the TV-trip validator with 384 MiB RAM and zero container swap.

The shared image builder stays unchanged. Only its exact validation create
command is transformed; inspect must confirm the limits before start.
"""
import argparse
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy import build_tv_trip_release as profile

builder = profile.builder
need = builder.need
SELF = 'deploy/tv_trip_validation_runner.py'
LIMIT = 384 * 1024 ** 2
PROGRAM = 'from deploy.membership_release_build import container_validate; raise SystemExit(container_validate())'


class BoundedValidationExecutor(builder.Executor):
    def __init__(self, output, image):
        super().__init__(output)
        self.image = builder.image_id(image)
        self.transforms = []

    def __call__(self, args, *, cwd=None, timeout=120):
        if not args or args[0] != 'create':
            return super().__call__(args, cwd=cwd, timeout=timeout)
        original = list(args)
        prefix = ['create', '--network', 'none', '--read-only', '--user', '10001:10001',
                  '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                  '--memory', '1024m', '--pids-limit', '256', '--workdir', '/app',
                  '--entrypoint', 'python', '--tmpfs', '/tmp:rw,size=805306368,mode=1777']
        need(not self.transforms and original[:len(prefix)] == prefix and
             original[-4:] == [self.image, '-B', '-c', PROGRAM] and
             original.count('--memory') == 1 and '--memory-swap' not in original,
             'unexpected TV validation create command')
        actual = original.copy()
        index = actual.index('--memory')
        actual[index:index+2] = ['--memory', '384m', '--memory-swap', '384m']
        record = {'originalArguments': original, 'executedArguments': actual,
                  'verifiedBeforeStart': False}
        self.transforms.append(record)
        result = super().__call__(actual, cwd=cwd, timeout=timeout)
        if result.returncode:
            return result
        identifier = result.stdout.decode().strip()
        need(re.fullmatch('[a-f0-9]{64}', identifier), 'invalid owned container identity')
        record['containerId'] = identifier
        try:
            inspected = json.loads(builder.must(super().__call__(['inspect', identifier]),
                                               'validation limit inspection failed'))
            need(isinstance(inspected, list) and len(inspected) == 1, 'invalid container inspection')
            value = inspected[0]
            host, config = value['HostConfig'], value['Config']
            observed = {name: host.get(name) for name in
                        ('Memory', 'MemorySwap', 'NetworkMode', 'ReadonlyRootfs',
                         'PidsLimit', 'CapDrop', 'SecurityOpt')}
            observed.update(id=value.get('Id'), image=value.get('Image'),
                            user=config.get('User'), running=value['State'].get('Running'))
            record['inspected'] = observed
            need(observed == {'Memory': LIMIT, 'MemorySwap': LIMIT, 'NetworkMode': 'none',
                              'ReadonlyRootfs': True, 'PidsLimit': 256, 'CapDrop': ['ALL'],
                              'SecurityOpt': ['no-new-privileges:true'], 'id': identifier,
                              'image': self.image, 'user': '10001:10001', 'running': False},
                 'actual validation container limits differ')
            record['verifiedBeforeStart'] = True
        except Exception:
            # isolated() has not received the ID yet, so it cannot clean up.
            builder.must(super().__call__(['rm', '--force', identifier]),
                         'owned rejected container cleanup failed')
            raise
        return result


def validate(*, package_dir, package_sha256, image_id, selection, selection_sha256,
             output_dir, pytest_dependencies=builder.DEPS):
    verified = profile.verify_package(package_dir, package_sha256)
    need(verified['blobs'].get(SELF) == profile.package.plain(Path(__file__).absolute()),
         'executed TV validation runner differs from package')
    output = Path(output_dir).absolute()
    need(not output.exists(), 'new validation output required')
    runner = BoundedValidationExecutor(output, image_id)
    result = None
    admitted = False
    try:
        result = profile.validate(package_dir=package_dir, package_sha256=package_sha256,
                                  image_id=image_id, selection=selection,
                                  selection_sha256=selection_sha256, output_dir=output_dir,
                                  pytest_dependencies=pytest_dependencies, runner=runner)
        need(len(runner.transforms) == 1 and runner.transforms[0]['verifiedBeforeStart'],
             'validation did not use the inspected memory limits')
        admitted = True
        return result
    finally:
        if output.is_dir():
            builder.save(output / 'memory-contract.json', builder.encoded({
                'kind': 'tv-trip-validation-memory-v1', 'limitBytes': LIMIT,
                'swapBytes': 0, 'imageId': image_id,
                'runnerSha256': builder.sha(profile.package.plain(Path(__file__).absolute())),
                'transforms': runner.transforms,
                'validationCompleted': result is not None,
                'allPassed': bool(admitted and result and result.get('allPassed')),
                'productionOperations': False}))
            # The subclass normally triggers the shared builder's own save.
            # Preserve commands on an early exception too, without overwriting.
            if not (output / 'commands.json').exists():
                builder.save(output / 'commands.json', builder.encoded({'commands': runner.records}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('package-dir', 'package-sha256', 'image-id', 'selection',
                  'selection-sha256', 'output-dir'):
        parser.add_argument('--'+field, required=True)
    parser.add_argument('--pytest-dependencies', default=builder.DEPS)
    result = validate(**vars(parser.parse_args(argv)))
    print(json.dumps(result))
    return 0 if result.get('allPassed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
