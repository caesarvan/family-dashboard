"""Explicit four-to-five service lifecycle for the reviewed video candidate.

This is a release-controller component, not an activation CLI. Its caller owns
the release lock, bound plan, backup timer, complete database backup/migration,
source installation and rollback decision. No data, volume, image or socket is
removed here. Raw service environments are never returned in public receipts.
"""
from pathlib import Path
import json
import re

from deploy.membership_release_controller import (
    ROOT, VOLUME, WEB_IMAGE, need, regular, runtime_environment, sha,
)

PARENT_IMAGE = 'sha256:a783c58c882748d273c5956e2d94a43c99261c61c6b41f0489118d9fd96f6654'
BEFORE_COMPOSE = '803c3c1551f2ccb1f285a8d578dbeab7ea4e53102e1cbb64d9a69d6c4d30dad1'
AFTER_COMPOSE = '677afc31a129ec955630bef0cdf124d476be2c0d6b939a77b2bb8472f6a0215f'
PROJECT = 'family-dashboard'
SOCKET_VOLUME = 'family-dashboard_decoder-socket'
SOCKET = '/decoder-private/video.sock'
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
OLD_SERVICES = ('app', 'sync', 'media', 'web')
NEW_SERVICES = (*OLD_SERVICES, 'decoder')
MIB = 1024 ** 2
MEMORY = {'app': 384, 'sync': 192, 'media': 384, 'web': 96, 'decoder': 768}


def immutable(value):
    need(isinstance(value, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', value), 'immutable_image_required')
    return value


def environment(value):
    raw = runtime_environment(value)
    return dict(line.split('=', 1) for line in raw.decode('utf8').splitlines())


def labels(value, name):
    actual = value['Config'].get('Labels') or {}
    need(actual.get('com.docker.compose.project') == PROJECT and
         actual.get('com.docker.compose.service') == name, 'service_identity_changed')
    need(value.get('Name') == '/' + PROJECT + '-' + name + '-1', 'service_name_changed')
    need(re.fullmatch('[0-9a-f]{64}', value.get('Id', '')), 'invalid_container_id')


def mount_map(value):
    mounts = value.get('Mounts')
    need(isinstance(mounts, list), 'mounts_missing')
    result = {}
    for mount in mounts:
        destination = mount.get('Destination')
        need(isinstance(destination, str) and destination not in result, 'duplicate_mount')
        result[destination] = mount
    return result


def volume(mounts, path, name):
    value = mounts.get(path, {})
    need(value.get('Type') == 'volume' and value.get('Name') == name and value.get('RW') is True,
         'service_volume_changed')


def decoder_contract(value):
    host, config = value['HostConfig'], value['Config']
    need(config.get('User') == '10001:10001' and config.get('WorkingDir') == '/decoder', 'decoder_identity_changed')
    need(config.get('Entrypoint') == ['python', '-B', '/decoder/media_video_service.py'] and
         config.get('Cmd') == ['--socket', SOCKET, '--temp-root', '/decode-temp', '--ffmpeg', '/usr/bin/ffmpeg',
                              '--ffprobe', '/usr/bin/ffprobe'], 'decoder_command_changed')
    need(host.get('NetworkMode') == 'none' and host.get('ReadonlyRootfs') is True and
         host.get('Memory') == host.get('MemorySwap') == 768 * MIB and
         host.get('NanoCpus') == 1_000_000_000 and host.get('PidsLimit') == 128,
         'decoder_isolation_changed')
    need(host.get('CapDrop') == ['ALL'] and not host.get('CapAdd') and not host.get('Privileged') and
         'no-new-privileges:true' in (host.get('SecurityOpt') or []), 'decoder_capabilities_changed')
    need(host.get('Ulimits') == [{'Name': 'nofile', 'Hard': 128, 'Soft': 128}], 'decoder_file_limit_changed')
    tmpfs = host.get('Tmpfs') or {}
    need(set(tmpfs) == {'/decode-temp'} and set(tmpfs['/decode-temp'].split(',')) ==
         {'rw', 'noexec', 'nosuid', 'nodev', 'size=384m', 'uid=10001', 'gid=10001', 'mode=0700'},
         'decoder_temp_changed')
    mounts = mount_map(value)
    volume(mounts, '/decoder-private', SOCKET_VOLUME)
    need(set(mounts) <= {'/decoder-private', '/decode-temp'} and
         ('/decode-temp' not in mounts or mounts['/decode-temp'].get('Type') == 'tmpfs'),
         'decoder_unexpected_mount')


class Lifecycle:
    def __init__(self, call, app_image, decoder_image, *, root=ROOT, mode='video-migration'):
        self.call = call
        self.root = Path(root).absolute()
        self.app_image, self.decoder_image = immutable(app_image), immutable(decoder_image)
        need(len({self.app_image, self.decoder_image, PARENT_IMAGE, WEB_IMAGE}) == 4, 'distinct_candidate_images_required')
        need(mode in ('video-migration', 'local-photo-source-update', 'discovery-source-update', 'finance-flow-source-update'), 'unsupported_lifecycle_mode')
        self.mode = mode
        self.source_update = mode != 'video-migration'
        self.parent_image, self.before_compose, self.parent_services = PARENT_IMAGE, BEFORE_COMPOSE, OLD_SERVICES
        if self.source_update:
            if mode == 'finance-flow-source-update':
                from deploy import build_finance_flow_release as photos
            elif mode == 'discovery-source-update':
                from deploy import build_discovery_release as photos
            else:
                from deploy import build_local_photo_release as photos
            need(self.decoder_image == photos.DECODER_IMAGE and self.app_image != photos.PARENT_IMAGE,
                 'local_photo_images_changed')
            self.parent_image, self.before_compose = photos.PARENT_IMAGE, photos.COMPOSE_SHA256
            self.parent_services = NEW_SERVICES
        self.parent_environments = None
        self.phase, self.recorded = 'unbound', {}

    def docker(self, *args, timeout=120):
        return self.call([*DOCKER, *args], cwd=self.root, timeout=timeout)

    def inspect(self, identifier):
        values = json.loads(self.docker('inspect', identifier))
        need(isinstance(values, list) and len(values) == 1, 'ambiguous_container')
        return values[0]

    def compose(self, phase, *args, timeout=180):
        need(phase in ('parent', 'candidate'), 'unknown_service_phase')
        actual = sha(regular(self.root / 'compose.yaml').read_bytes())
        need(actual == (self.before_compose if phase == 'parent' else AFTER_COMPOSE), 'compose_source_changed')
        return self.docker('compose', '--project-name', PROJECT, '--project-directory', str(self.root),
                           '--file', str(self.root / 'compose.yaml'), *args, timeout=timeout)

    def check(self, name, value, phase, *, running=True):
        need(name in (self.parent_services if phase == 'parent' else NEW_SERVICES), 'unknown_service')
        labels(value, name)
        expected_image = WEB_IMAGE if name == 'web' else (self.decoder_image if name == 'decoder' else
                         self.parent_image if phase == 'parent' else self.app_image)
        need(value.get('Image') == expected_image, 'service_image_changed')
        state = value['State']
        need(state.get('Running') is running and not state.get('OOMKilled') and
             (phase == 'parent' or not value.get('RestartCount')), 'service_state_changed')
        if not running:
            need(state.get('ExitCode') in (0, 143), 'unclean_service_stop')
            return
        host = value['HostConfig']
        need(host.get('Memory') == MEMORY[name] * MIB, 'service_memory_changed')
        if name in ('app', 'sync', 'media'):
            need(host.get('ReadonlyRootfs') is True and value['Config'].get('User') == 'dashboard',
                 'application_identity_changed')
            mounts = mount_map(value)
            volume(mounts, '/data', VOLUME)
            expected = {'/data', '/tmp'} | ({'/decoder-private'} if name == 'media' and (phase == 'candidate' or self.source_update) else set())
            need(set(mounts) <= expected and ('/tmp' not in mounts or mounts['/tmp'].get('Type') == 'tmpfs'),
                 'application_unexpected_mount')
            if name == 'media' and (phase == 'candidate' or self.source_update):
                volume(mounts, '/decoder-private', SOCKET_VOLUME)
            env = environment(value['Config'].get('Env'))
            if self.source_update and name == 'media':
                need(env.get('MEDIA_VIDEO_SOCKET') == SOCKET, 'parent_socket_environment_changed')
        elif name == 'decoder':
            decoder_contract(value)
            image_env = self.inspect(self.decoder_image)['Config'].get('Env')
            need(value['Config'].get('Env') == image_env, 'decoder_environment_added')
        if name in ('app', 'decoder'):
            need(state.get('Health', {}).get('Status') == 'healthy', 'service_unhealthy')
        if phase == 'candidate' and name in ('app', 'sync', 'media'):
            need(self.parent_environments is not None, 'parent_environments_unbound')
            expected_env = dict(self.parent_environments[name])
            if name == 'media':
                expected_env['MEDIA_VIDEO_SOCKET'] = SOCKET
            need(environment(value['Config']['Env']) == expected_env, 'candidate_environment_changed')

    def capture(self, phase):
        need(phase in ('parent', 'candidate'), 'unknown_service_phase')
        names = self.parent_services if phase == 'parent' else NEW_SERVICES
        values = {name: self.inspect(PROJECT + '-' + name + '-1') for name in names}
        listed = self.docker('ps', '--all', '--quiet', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + PROJECT)
        ids = listed.decode().splitlines()
        need(len(ids) == len(names) and set(ids) == {v['Id'] for v in values.values()}, 'unexpected_project_container')
        for name, value in values.items():
            self.check(name, value, phase)
        if phase == 'parent':
            self.parent_environments = {n: environment(values[n]['Config']['Env']) for n in ('app', 'sync', 'media')}
            self.phase = 'parent-bound'
        result = {name: {'id': value['Id'], 'image': value['Image']} for name, value in values.items()}
        for name in ('app', 'sync', 'media'):
            result[name]['environmentSha256'] = sha(runtime_environment(values[name]['Config']['Env']))
        return result

    def drain(self, phase, captured):
        """Drain workers before decoder; prove no data/socket users remain."""
        need(phase in ('parent', 'candidate'), 'unknown_service_phase')
        need(self.phase == ('parent-bound' if phase == 'parent' else 'live'), 'invalid_drain_phase')
        names = self.parent_services if phase == 'parent' else NEW_SERVICES
        need(set(captured) == set(names), 'incomplete_service_capture')
        for name in names:
            value = self.inspect(captured[name]['id'])
            need(value['Id'] == captured[name]['id'], 'captured_container_changed')
            self.check(name, value, phase)
            if name in ('app', 'sync', 'media'):
                need(sha(runtime_environment(value['Config']['Env'])) == captured[name]['environmentSha256'],
                     'environment_changed_before_stop')
        sequence = [('web', 30), ('sync', 60), ('media', 1200)]
        if phase == 'candidate' or self.source_update:
            sequence.append(('decoder', 30))
        sequence.append(('app', 60))
        stopped = []
        self.phase = 'draining'
        for name, grace in sequence:
            # Rebind the canonical name immediately before Compose selects it.
            value = self.inspect(PROJECT + '-' + name + '-1')
            need(value['Id'] == captured[name]['id'], 'service_replaced_before_stop')
            self.compose(phase, 'stop', '--timeout', str(grace), name, timeout=grace + 60)
            self.check(name, self.inspect(captured[name]['id']), phase, running=False)
            stopped.append(name)
        for mounted in (VOLUME, SOCKET_VOLUME):
            need(not self.docker('ps', '--quiet', '--filter', 'volume=' + mounted).strip(), 'volume_still_in_use')
        self.phase = 'stopped'
        return {'stopped': stopped, 'dataWritersStopped': True, 'socketUsersStopped': True}

    def remember(self, names):
        # Called even when Compose reports failure after creating a container.
        # Ignore unrecognized identities; the final running-container check
        # still prevents claiming a complete stop while any such process runs.
        for name in names:
            try:
                value = self.inspect(PROJECT + '-' + name + '-1')
                labels(value, name)
                expected = WEB_IMAGE if name == 'web' else self.decoder_image if name == 'decoder' else self.app_image
                need(value['Image'] == expected, 'candidate_not_created')
                self.recorded[name] = {'id': value['Id'], 'image': value['Image']}
            except Exception:
                pass

    def up(self, names, wait):
        try:
            return self.compose('candidate', 'up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                                '--wait', '--wait-timeout', str(wait), *names, timeout=wait + 30)
        finally:
            self.remember(names)

    def start_app_only(self):
        need(self.phase in ('stopped', 'preserved'), 'invalid_app_start_phase')
        need(not self.docker('ps', '--quiet', '--filter', 'volume=' + VOLUME).strip(), 'data_writer_still_running')
        self.phase = 'starting-app'
        self.up(('app',), 150)
        value = self.inspect(PROJECT + '-app-1')
        self.check('app', value, 'candidate')
        self.phase = 'app-only'
        return {'id': value['Id'], 'image': value['Image']}

    def stop_app_only(self, captured):
        need(self.phase == 'app-only', 'invalid_app_stop_phase')
        value = self.inspect(PROJECT + '-app-1')
        need(value['Id'] == captured['id'] and value['Image'] == self.app_image, 'app_only_identity_changed')
        self.compose('candidate', 'stop', '--timeout', '60', 'app', timeout=90)
        self.check('app', self.inspect(captured['id']), 'candidate', running=False)
        need(not self.docker('ps', '--quiet', '--filter', 'volume=' + VOLUME).strip(), 'data_writer_still_running')
        self.phase = 'app-stopped'

    def start_after_preservation(self, migrated, preserved, *, plan_sha256=None, source_identity_sha256=None):
        """Use the caller's hash-verified migration and stopped-check receipts."""
        need(self.parent_environments is not None, 'parent_environments_unbound')
        need(self.phase == 'app-stopped', 'invalid_preservation_phase')
        for value in (migrated, preserved):
            need(value.get('verified') is True and type(value.get('households')) is int and value['households'] >= 1
                 and value.get('databases') == value['households'] + 1, 'incomplete_preservation_receipt')
        if self.source_update:
            # begin() is an actual backup receipt, never relabelled as migration.
            for key, expected in (('planSha256', plan_sha256), ('sourceIdentitySha256', source_identity_sha256)):
                need(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected)
                     and preserved.get(key) == expected, 'preservation_identity_changed')
            keys = ('logicalSha256', 'markerSha256')
        else:
            need(plan_sha256 is None and source_identity_sha256 is None, 'unexpected_preservation_binding')
            keys = ('planSha256', 'logicalSha256', 'sourceIdentitySha256')
        for key in keys:
            need(re.fullmatch('[0-9a-f]{64}', migrated.get(key, '')) and migrated[key] == preserved.get(key),
                 'preservation_identity_changed')
        need(migrated['households'] == preserved['households'], 'preservation_group_changed')
        self.phase = 'preserved'
        self.start_app_only()
        self.phase = 'starting-decoder'
        self.up(('decoder',), 90)
        self.check('decoder', self.inspect(PROJECT + '-decoder-1'), 'candidate')
        self.phase = 'starting-workers'
        self.up(('sync', 'media'), 150)
        for name in ('sync', 'media'):
            self.check(name, self.inspect(PROJECT + '-' + name + '-1'), 'candidate')
        self.phase = 'starting-web'
        self.up(('web',), 90)
        result = self.capture('candidate')
        self.phase = 'live'
        return result

    def stop_after_failure(self):
        """Stop only positively identified candidates, including partial starts.

        This uses immutable container IDs, not mutable Compose selectors. A
        missing/failed operation remains an incomplete stop receipt. The caller
        must retain stopped state and never automatically resume an old schema.
        """
        recorded = self.recorded
        result = {'stopped': [], 'failed': [], 'complete': False}
        for name, grace in (('web', 30), ('sync', 60), ('media', 1200), ('decoder', 30), ('app', 60)):
            if name not in recorded:
                continue
            if name == 'decoder':
                try:
                    media = self.inspect(PROJECT + '-media-1')
                    labels(media, 'media')
                    need(media['State'].get('Running') is False, 'media_not_stopped')
                    if 'media' in recorded:
                        need(media['Id'] == recorded['media']['id'], 'media_identity_changed')
                except Exception:
                    result['failed'].append('decoder:media_stop_unverified')
                    continue
            try:
                value = self.inspect(recorded[name]['id'])
                labels(value, name)
                expected = WEB_IMAGE if name == 'web' else self.decoder_image if name == 'decoder' else self.app_image
                need(value['Id'] == recorded[name]['id'] and value['Image'] == expected, 'failure_container_changed')
                if value['State']['Running']:
                    self.docker('stop', '--timeout', str(grace), value['Id'], timeout=grace + 60)
                self.check(name, self.inspect(value['Id']), 'candidate', running=False)
                result['stopped'].append(name)
            except Exception:
                result['failed'].append(name)
        for mounted in (VOLUME, SOCKET_VOLUME):
            try:
                if self.docker('ps', '--quiet', '--filter', 'volume=' + mounted).strip():
                    result['failed'].append('running:' + mounted)
            except Exception:
                result['failed'].append('unverified:' + mounted)
        try:
            if self.docker('ps', '--quiet', '--filter', 'label=com.docker.compose.project=' + PROJECT).strip():
                result['failed'].append('running:project')
        except Exception:
            result['failed'].append('unverified:project')
        result['complete'] = not result['failed']
        self.phase = 'failed-stopped' if result['complete'] else 'failed-unverified'
        return result
