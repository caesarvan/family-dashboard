"""Prepare/verify video source or build two candidate images; never activate.

Actual build is an explicit Linux-only local-Docker action. It installs pinned
dependencies in new images, never runs Compose or mounts production data.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import media_video_release_package as package
from deploy import membership_release_build as common

need, sha, encoded = package.need, package.sha, package.encoded
PYTHON_BASE = 'python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea'
FFMPEG_PACKAGE = '7:7.1.5-0+deb13u1'


def runtime_map(role, context):
    omitted = {'Dockerfile', '.dockerignore'}
    return {n: h for n, h in context.items() if n not in omitted}


def probe_program(role):
    root = '/app' if role == 'app' else '/decoder'
    script = ("from pathlib import Path; import hashlib,json,os,subprocess\n"
              f"root=Path({root!r}); files={{}}\n"
              "for p in root.rglob('*'):\n"
              " if p.is_symlink(): raise RuntimeError('linked runtime')\n"
              " if p.is_file(): files[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()\n"
              "value={'uid':os.geteuid(),'files':files}\n")
    if role == 'decoder':
        script += ("import PIL\nvalue['pillow']=PIL.__version__\nvalue['tools']={}\n"
                   "for name in ('ffmpeg','ffprobe'):\n"
                   " p=Path('/usr/bin')/name\n"
                   " r=subprocess.run([str(p),'-version'],capture_output=True,check=True,timeout=10)\n"
                   " value['tools'][name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'version':r.stdout.decode()}\n"
                   "value['ffmpegPackage']=subprocess.check_output(['dpkg-query','-W','-f=${Version}','ffmpeg']).decode()\n")
    return script + 'print(json.dumps(value,sort_keys=True))\n'


def probe(run, image, role):
    args = ['create', '--network', 'none', '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--memory', '256m', '--memory-swap', '256m',
            '--cpus', '1', '--pids-limit', '64', '--workdir', '/', '--entrypoint', 'python',
            image, '-B', '-c', probe_program(role)]
    container = common.must(run(args), 'image probe creation failed').decode().strip()
    need(len(container) == 64 and all(c in '0123456789abcdef' for c in container), 'invalid probe container ID')
    try:
        return package.common.json_value(common.must(run(['start', '--attach', container], timeout=60),
                                                    'image runtime probe failed'))
    finally:
        common.must(run(['rm', '--force', container]), 'owned image probe cleanup failed')


def validate_verification(config, actual, role, expected):
    need(config.get('User') == ('dashboard' if role == 'app' else '10001:10001') and
         config.get('WorkingDir') == ('/app' if role == 'app' else '/decoder'), 'image user/workdir differs')
    expected_entry = None if role == 'app' else ['python', '-B', '/decoder/media_video_service.py']
    expected_cmd = (['gunicorn', '--bind', '0.0.0.0:8000', '--workers', '1', '--threads', '4', '--timeout', '45',
                     '--access-logfile', '-', '--access-logformat', '%(h)s %(m)s %(U)s %(s)s', 'app:create_app()']
                    if role == 'app' else ['--socket', '/decoder-private/video.sock', '--temp-root', '/decode-temp',
                                          '--ffmpeg', '/usr/bin/ffmpeg', '--ffprobe', '/usr/bin/ffprobe'])
    need(config.get('Entrypoint') == expected_entry and config.get('Cmd') == expected_cmd, 'image command differs')
    need(actual.get('uid') == 10001 and actual.get('files') == expected, 'image runtime bytes differ')
    if role == 'decoder':
        need(actual.get('pillow') == '12.3.0' and actual.get('ffmpegPackage') == FFMPEG_PACKAGE,
             'decoder package version differs')
        need(set(actual.get('tools', {})) == {'ffmpeg', 'ffprobe'}, 'decoder tools missing')
        for tool in actual['tools'].values():
            package.common.checksum(tool['sha256'])
            need(isinstance(tool['version'], str) and len(tool['version']) <= 20000
                 and '7.1.5' in tool['version'], 'decoder tool version differs')


def verify_image(run, image, role, expected):
    config = common.inspect_image(run, image)['Config']
    actual = probe(run, image, role)
    validate_verification(config, actual, role, expected)
    return {'config': config, 'runtime': actual}


def build(package_dir, package_sha256, output_dir, *, runner=None):
    value = package.verify_package(package_dir, package_sha256)
    need(value['blobs'][package.BUILDER] == package.common.plain(Path(__file__).absolute()),
         'executed builder differs from package')
    output = common.new_output(output_dir, package_dir)
    run = runner or common.Executor(output)
    meta = value['metadata']
    attempt = dict(schemaVersion=1, kind='media-video-dual-image-build', sourceHead=meta['sourceHead'], tree=meta['tree'],
                   packageSha256=package_sha256, manifestSha256=meta['manifestSha256'],
                   startedAt=datetime.now(timezone.utc).isoformat(), productionOperations=False)
    common.save(output / 'attempt.json', encoded(attempt))
    results = {}; folder = None; record = None
    try:
        for role, blobs in package.contexts(value['blobs']).items():
            record = None
            folder = output / role; folder.mkdir(mode=0o700)
            context = folder / 'context'
            for name, raw in blobs.items():
                common.save(context / name, raw)
            expected = meta['contexts'][role]
            need(common.tree_hashes(context) == expected, 'build context differs')
            record = dict(role=role, sourceHead=meta['sourceHead'], packageSha256=package_sha256,
                          contextHashes=expected, dockerfileSha256=sha(blobs['Dockerfile']), exitCode=None,
                          successful=False, pythonBase=PYTHON_BASE)
            # No image tag is created/replaced. Exact pinned recipes require
            # dependency network during image construction, never at runtime.
            result = run(['build', '--pull=false', '--network=default', '--iidfile', str(folder / 'image-id'), '.'],
                         cwd=context, timeout=1800)
            common.save(folder / 'stdout', result.stdout); common.save(folder / 'stderr', result.stderr)
            record['exitCode'] = result.returncode
            record.update(stdoutSha256=sha(result.stdout), stderrSha256=sha(result.stderr))
            # Record failure even when Docker creates an iidfile before failing.
            if result.returncode != 0:
                common.save(folder / 'build.json', encoded(record))
                raise ValueError('candidate image build failed; retain partial attempt')
            image = common.image_id(package.common.plain(folder / 'image-id', 100).decode().strip())
            record['imageId'] = image
            need(image not in [v['imageId'] for v in results.values()], 'two roles must bind distinct image IDs')
            record.update(imageId=image, verification=verify_image(run, image, role, runtime_map(role, expected)))
            need(common.tree_hashes(context) == expected, 'context changed during build')
            record['successful'] = True
            common.save(folder / 'build.json', encoded(record)); results[role] = record
        need(set(results) == {'app', 'decoder'}, 'both image roles required')
        need(package.verify_package(package_dir, package_sha256) == value, 'package changed during build')
        result = {**attempt, 'allPassed': True, 'images': {k: v['imageId'] for k, v in results.items()},
                  'builds': {k: sha(package.common.plain(output / k / 'build.json', 2_000_000)) for k in results},
                  'completedAt': datetime.now(timezone.utc).isoformat()}
        common.save(output / 'build.json', encoded(result))
        return result
    except Exception as error:
        if record is not None and folder is not None and not (folder / 'build.json').exists():
            common.save(folder / 'build.json', encoded({**record, 'successful': False, 'errorType': type(error).__name__}))
        common.save(output / 'failed.json', encoded({**attempt, 'allPassed': False, 'errorType': type(error).__name__,
                    'completedRoles': sorted(results), 'productionOperations': False}))
        raise
    finally:
        if isinstance(run, common.Executor):
            common.save(output / 'commands.json', encoded({'commands': run.records}))


def verify_build(build_dir, build_sha256, package_dir, package_sha256):
    """Bind both independent successful build records; no daemon or side effects."""
    value = package.verify_package(package_dir, package_sha256); meta = value['metadata']
    root = package.common.checked(Path(build_dir).absolute(), True)
    need(not (root / 'failed.json').exists(), 'failed attempt is not a complete build')
    raw = package.common.plain(root / 'build.json', 2_000_000)
    need(sha(raw) == package.common.checksum(build_sha256), 'build receipt hash differs')
    result = package.common.json_value(raw)
    need(result.get('kind') == 'media-video-dual-image-build' and result.get('allPassed') is True
         and result.get('productionOperations') is False and result.get('sourceHead') == meta['sourceHead']
         and result.get('tree') == meta['tree'] and result.get('packageSha256') == package_sha256
         and result.get('manifestSha256') == meta['manifestSha256'], 'build identity differs')
    need(set(result['images']) == set(result['builds']) == {'app', 'decoder'} and
         len(set(result['images'].values())) == 2, 'both distinct immutable images required')
    for role, image in result['images'].items():
        common.image_id(image)
        raw = package.common.plain(root / role / 'build.json', 2_000_000)
        need(sha(raw) == result['builds'][role], 'image build record changed')
        record = package.common.json_value(raw)
        need(record.get('role') == role and record.get('successful') is True and type(record.get('exitCode')) is int
             and record['exitCode'] == 0 and record.get('imageId') == image and record.get('sourceHead') == meta['sourceHead']
             and record.get('packageSha256') == package_sha256 and record.get('contextHashes') == meta['contexts'][role]
             and record['verification']['runtime']['files'] == runtime_map(role, meta['contexts'][role]), 'image receipt differs')
        need(record.get('pythonBase') == PYTHON_BASE and
             record.get('dockerfileSha256') == meta['contexts'][role]['Dockerfile'], 'image recipe differs')
        need(package.common.plain(root / role / 'image-id', 100).decode().strip() == image,
             'image ID file differs')
        for name in ('stdout', 'stderr'):
            need(sha(package.common.plain(root / role / name)) == record.get(name + 'Sha256'),
                 'image build output changed')
        validate_verification(record['verification']['config'], record['verification']['runtime'], role,
                              runtime_map(role, meta['contexts'][role]))
        need(common.tree_hashes(root / role / 'context') == meta['contexts'][role], 'retained context differs')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    fields = {'prepare': ('repo', 'commit', 'export-dir', 'build-evidence', 'evidence-sha256', 'output-dir'),
              'verify': ('output-dir', 'package-sha256'), 'build': ('package-dir', 'package-sha256', 'output-dir'),
              'verify-build': ('build-dir', 'build-sha256', 'package-dir', 'package-sha256')}
    for name, options in fields.items():
        sub = commands.add_parser(name)
        for option in options:
            sub.add_argument('--' + option, required=True)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    if action == 'verify':
        value = package.verify_package(**args)
        result = dict(verified=True, sourceHead=value['metadata']['sourceHead'], files=len(value['blobs']))
    else:
        result = {'prepare': package.prepare, 'build': build, 'verify-build': verify_build}[action](**args)
    print(json.dumps(result)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
