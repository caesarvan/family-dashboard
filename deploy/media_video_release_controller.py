"""Five-service video activation using a separately reviewed operator bundle.

stage is read-only with respect to production. activate consumes a plan once.
Failures retain the original source/credentials/backup and stop owned candidate
processes; no automatic database restore, socket deletion or old-service start.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import prepare_media_video_activation as prepare
from deploy import build_media_video_release as build
from deploy import media_video_service_lifecycle as services
from deploy.membership_release_controller import (
    ROOT, RELEASES, VOLUME, PUBLIC_ORIGIN, ReleaseError, need, regular, read, put,
    encoded, sha, relative, source_hashes, runtime_environment, run,
)

TIMER = 'family-dashboard-backup.timer'
DATA_PREFIX = """
from pathlib import Path
import hashlib,json,sys
sys.path[:0]=['/app','/release']
from deploy import check_media_video_migration as data
from deploy.membership_release_controller import source_hashes
root=Path('/data');proof=Path('/proof')
identity=json.loads((proof/'identity.json').read_bytes())
source_hashes(Path('/release'),identity['sourceHashes'],exact=True)
observed={}
for p in Path('/app').rglob('*'):
 if p.is_symlink():raise RuntimeError('runtime_link')
 if p.is_file():observed[p.relative_to('/app').as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
if observed!=identity['runtimeHashes']:raise RuntimeError('runtime_changed')
kwargs={'source_identity':identity,'plan_sha256':json.loads((proof/'binding.json').read_bytes())['planSha256']}
"""
DATA_ACTIONS = {
    'backup': "value=data.begin(root,proof,**kwargs)",
    'migrate': "value=data.migrate(root,proof,**kwargs)",
    'check': "value=data.check_stopped(root,proof,**kwargs)",
    'verify-rollback': "value=data.verify_rollback(proof,root)",
}


def verify_operator(candidate, expected, *, mode='video-migration'):
    need(mode in ('video-migration', 'local-photo-source-update', 'discovery-source-update',
                  'finance-flow-source-update', 'journey-finance-73-to-75', 'media-date-source-update', 'assistant-list-source-update', 'tv-trip-75-to-77'), 'unsupported_release_mode')
    policy = prepare
    if mode == 'local-photo-source-update':
        from deploy import prepare_local_photo_activation as policy
    elif mode == 'tv-trip-75-to-77':
        from deploy import prepare_tv_trip_activation as policy
    elif mode == 'assistant-list-source-update':
        from deploy import prepare_assistant_list_activation as policy
    elif mode == 'media-date-source-update':
        from deploy import prepare_media_date_activation as policy
    elif mode == 'journey-finance-73-to-75':
        from deploy import prepare_journey_finance_activation as policy
    elif mode == 'finance-flow-source-update':
        from deploy import prepare_finance_flow_activation as policy
    elif mode == 'discovery-source-update':
        from deploy import prepare_discovery_activation as policy
    manifest = read(candidate / 'operator.json', expected)
    need(set(manifest['files']) == set(policy.OPERATORS), 'operator_closure_changed')
    source_hashes(candidate / 'operator', manifest['files'], exact=False)
    # Rehash the actually executing closure as well as the retained bundle.
    executing = Path(__file__).resolve().parents[1]
    for name, digest in manifest['files'].items():
        need(sha(regular(executing / name).read_bytes()) == digest, 'executed_operator_changed')
    actual = {p.relative_to(candidate / 'operator').as_posix() for p in (candidate / 'operator').rglob('*') if p.is_file()}
    need(actual == set(manifest['files']), 'unexpected_operator_file')
    return manifest


class Controller:
    def __init__(self, candidate, plan_sha256, *, runner=run, root=ROOT, releases=RELEASES, mode='video-migration'):
        self.candidate = regular(Path(candidate).absolute(), directory=True)
        self.root, self.releases = Path(root).absolute(), Path(releases).absolute()
        self.plan_sha = plan_sha256
        self.plan = read(self.candidate / 'plan.json', plan_sha256)
        self.runner = runner
        self.source = self.candidate / 'source'
        need(mode in ('video-migration', 'local-photo-source-update', 'discovery-source-update',
                      'finance-flow-source-update', 'journey-finance-73-to-75', 'media-date-source-update', 'assistant-list-source-update', 'tv-trip-75-to-77'), 'unsupported_release_mode')
        self.mode, self.policy = mode, prepare
        self.source_update = mode != 'video-migration'
        self.needs_migration = mode in ('video-migration', 'journey-finance-73-to-75', 'tv-trip-75-to-77')
        self.after_schema = [77, 9] if mode == 'tv-trip-75-to-77' else [75, 9] if mode in ('journey-finance-73-to-75', 'media-date-source-update', 'assistant-list-source-update') else [73, 9]
        self.images, self.parent_image, self.before_schema = prepare.IMAGES, services.PARENT_IMAGE, [71, 9]
        self.release_prefix = 'media-video-73-'
        self.data_prefix, self.data_actions = DATA_PREFIX, DATA_ACTIONS
        if self.source_update:
            if mode == 'tv-trip-75-to-77':
                from deploy import prepare_tv_trip_activation as policy
            elif mode == 'assistant-list-source-update':
                from deploy import prepare_assistant_list_activation as policy
            elif mode == 'media-date-source-update':
                from deploy import prepare_media_date_activation as policy
            elif mode == 'journey-finance-73-to-75':
                from deploy import prepare_journey_finance_activation as policy
            elif mode == 'finance-flow-source-update':
                from deploy import prepare_finance_flow_activation as policy
            elif mode == 'discovery-source-update':
                from deploy import prepare_discovery_activation as policy
            else:
                from deploy import prepare_local_photo_activation as policy
            self.policy, self.images = policy, policy.plan_images(self.plan)
            self.parent_image, self.before_schema = policy.package.PARENT_IMAGE, [73, 9]
            self.release_prefix = ('finance-flow-73-' if mode == 'finance-flow-source-update' else
                                   'discovery-73-' if mode == 'discovery-source-update' else 'local-photo-73-')
            self.data_prefix = DATA_PREFIX.replace('check_media_video_migration', 'media_video_release_data')
            self.data_actions = {'backup': DATA_ACTIONS['backup'], 'check': DATA_ACTIONS['check'],
                'verify-rollback': 'from deploy.activate_local_photo_release import verify_restored_group; value=verify_restored_group(root,proof,**kwargs)'}
            if mode == 'tv-trip-75-to-77':
                self.before_schema = [75, 9]
                self.release_prefix = 'tv-trip-77-'
                self.data_prefix = DATA_PREFIX.replace('check_media_video_migration', 'check_tv_trip_migration')
                self.data_actions = DATA_ACTIONS
            elif mode == 'journey-finance-73-to-75':
                self.release_prefix = 'journey-finance-75-'
                self.data_prefix = DATA_PREFIX.replace('check_media_video_migration', 'check_journey_finance_migration')
                self.data_actions = DATA_ACTIONS
            elif mode == 'assistant-list-source-update':
                self.before_schema = [75, 9]
                self.release_prefix = 'assistant-list-75-'
                self.data_prefix = DATA_PREFIX.replace('check_media_video_migration', 'journey_finance_release_data')
                self.data_actions = {'backup': DATA_ACTIONS['backup'], 'check': DATA_ACTIONS['check'],
                    'verify-rollback': 'from deploy.activate_assistant_list_release import verify_restored_group; value=verify_restored_group(root,proof,**kwargs)'}
            elif mode == 'media-date-source-update':
                self.before_schema = [75, 9]
                self.release_prefix = 'media-date-75-'
                self.data_prefix = DATA_PREFIX.replace('check_media_video_migration', 'journey_finance_release_data')
                self.data_actions = {'backup': DATA_ACTIONS['backup'], 'check': DATA_ACTIONS['check'],
                    'verify-rollback': 'from deploy.activate_media_date_release import verify_restored_group; value=verify_restored_group(root,proof,**kwargs)'}
            policy.check_plan(self.plan)
        need(self.plan.get('kind') == (self.policy.KIND if self.source_update
                                      else 'media-video-five-service-activation-v1') and
             self.plan.get('parentSource') == self.policy.PARENT_SOURCE and
             self.plan.get('parentManifest') == self.policy.PARENT_MANIFEST and
             (self.source_update or self.plan.get('sourceHead') == prepare.APP_SOURCE) and self.plan.get('images') == self.images and
             self.plan.get('schemaBefore') == self.before_schema and self.plan.get('schemaAfter') == self.after_schema, 'plan_contract_changed')
        self.lifecycle = services.Lifecycle(self.call, **dict(app_image=self.images['app'],
                                                             decoder_image=self.images['decoder']), root=self.root, mode=mode)
        self.release = None
        self.data_helper = None
        self.data_helper_stop = None

    def call(self, argv, *, cwd=None, timeout=240):
        return self.runner(argv, cwd=cwd or self.root, timeout=timeout)

    def docker(self, *args, timeout=120):
        return self.call([*services.DOCKER, *args], timeout=timeout)

    def evidence(self):
        verify_operator(self.candidate, self.plan['operatorSha256'], mode=self.mode)
        need(read(self.candidate / 'plan.json', self.plan_sha) == self.plan, 'plan_changed')
        value, built, observed = self.policy.verify_evidence(self.plan['inputs'])
        need(observed == self.plan['verifiedEvidence'], 'retained_evidence_changed')
        self.files = value['manifest']['files']; self.metadata = value['metadata']
        source_hashes(self.source, self.files, exact=True)
        need(sha(regular(self.source / 'RELEASE-MANIFEST.json').read_bytes()) == self.metadata['manifestSha256'],
             'candidate_manifest_changed')
        self.runtime = (self.metadata['runtimeFiles'] if self.source_update
                        else build.runtime_map('app', self.metadata['contexts']['app']))
        need(self.metadata['sourceHead'] == self.plan['sourceHead'], 'plan_source_changed')
        self.build = built
        if self.source_update:
            need(built['imageId'] == self.images['app'] and self.metadata['tree'] == self.plan['tree'], 'plan_image_or_tree_changed')

    def check_images(self):
        # Only inspect existing immutable images. Stage never creates/runs a probe.
        if self.source_update:
            app = self.lifecycle.inspect(self.images['app'])
            decoder = self.lifecycle.inspect(self.images['decoder'])
            need(app.get('Id') == self.images['app'] and decoder.get('Id') == self.images['decoder'],
                 'candidate_image_missing')
            need({k: v for k, v in app['Config'].items() if k != 'Image'} == self.build['parentConfig'],
                 'candidate_image_config_changed')
            return
        for role, image in self.images.items():
            value = self.lifecycle.inspect(image)
            need(value.get('Id') == image, 'candidate_image_missing')
            folder = Path(self.plan['inputs']['build']['root']) / role
            record = read(folder / 'build.json', self.build['builds'][role])
            need(value['Config'] == record['verification']['config'], 'candidate_image_config_changed')

    def baseline(self):
        old = read(self.root / 'RELEASE-MANIFEST.json', self.policy.PARENT_MANIFEST)
        need(old.get('sourceHead') == self.policy.PARENT_SOURCE, 'parent_source_changed')
        source_hashes(self.root, old['files'])
        if self.source_update:
            need(old['files'].get('deploy/nginx.conf') == self.policy.package.NGINX_BEFORE, 'parent_nginx_changed')
        env = regular(self.root / '.env')
        need(stat.S_IMODE(env.stat().st_mode) == 0o600 and sha(env.read_bytes()) == self.plan['envSha256'],
             'parent_environment_changed')
        captured = self.lifecycle.capture('parent')
        self.lifecycle.compose('parent', 'config', '--quiet')
        return old, captured

    def stage(self):
        need(not (self.candidate / 'activation-started.json').exists(), 'plan_consumed')
        self.evidence(); self.check_images()
        old, captured = self.baseline()
        result = {'planSha256': self.plan_sha, 'services': captured, 'parentManifest': self.policy.PARENT_MANIFEST,
                  'parentFilesSha256': sha(encoded(old['files'])), 'images': self.images,
                  'schemaBefore': self.before_schema, 'schemaAfter': self.after_schema, 'productionWrites': False}
        put(self.candidate / 'stage.json', result)
        return result

    def stopped(self):
        for mounted in (VOLUME, services.SOCKET_VOLUME):
            need(not self.docker('ps', '--quiet', '--filter', 'volume='+mounted).strip(), 'volume_still_running')
        need(not self.docker('ps', '--quiet', '--filter', 'label=com.docker.compose.project='+services.PROJECT).strip(),
             'project_still_running')

    def preserve(self, old, captured):
        before = self.release / 'source-before'; before.mkdir(mode=0o700)
        for name in [*old['files'], 'RELEASE-MANIFEST.json']:
            target = before / relative(name); target.parent.mkdir(parents=True, exist_ok=True)
            put(target, regular(self.root / name).read_bytes())
        source_hashes(before, old['files'], exact=True)
        put(self.release / 'env-before', regular(self.root / '.env').read_bytes())
        observed = self.lifecycle.inspect(captured['app']['id'])
        need(observed['Id'] == captured['app']['id'] and observed['Image'] == self.parent_image,
             'environment_container_changed')
        raw = runtime_environment(observed['Config']['Env'])
        need(sha(raw) == captured['app']['environmentSha256'], 'runtime_environment_changed')
        put(self.release / 'app-runtime.env', raw)
        preserved_images = {}
        images = [('app', self.parent_image), ('web', services.WEB_IMAGE)]
        if self.source_update: images.append(('decoder', self.images['decoder']))
        for role, image in images:
            tag = 'family-dashboard-preserved:'+self.release.name.lower()+'-'+role
            self.docker('tag', image, tag)
            preserved_images[role] = {'image': image, 'tag': tag}
        put(self.release / 'parent-images.json', preserved_images)

    def socket_ready(self):
        listed = self.docker('volume', 'ls', '--quiet', '--filter', 'name=^'+services.SOCKET_VOLUME+'$').decode().splitlines()
        need(listed in ([], [services.SOCKET_VOLUME]), 'ambiguous_socket_volume')
        if not listed:
            return  # Compose creates the image-initialized private directory later.
        values = json.loads(self.docker('volume', 'inspect', services.SOCKET_VOLUME))
        need(len(values) == 1 and values[0]['Name'] == services.SOCKET_VOLUME and values[0]['Driver'] == 'local' and
             not values[0].get('Options'), 'socket_volume_changed')
        directory = regular(Path(values[0]['Mountpoint']), directory=True)
        mode = directory.stat()
        need(mode.st_uid == 10001 and stat.S_IMODE(mode.st_mode) == 0o700 and not list(directory.iterdir()),
             'socket_volume_not_empty_private; retain it and investigate, never delete automatically')

    def proof_init(self):
        proof = self.release / 'proof'; proof.mkdir(mode=0o700)
        identity = {'head': self.metadata['sourceHead'], 'tree': self.metadata['tree'], 'imageId': self.images['app'],
                    'sourceHashes': self.files, 'runtimeHashes': self.runtime}
        put(proof / 'identity.json', identity); put(proof / 'binding.json', {'planSha256': self.plan_sha})
        if os.name != 'nt':
            os.chown(proof, 10001, 10001)
            for p in proof.iterdir(): os.chown(p, 10001, 10001)
        return proof

    def data_call(self, action, *, write=True):
        need(action in self.data_actions, 'unknown_data_action')
        self.stopped()
        proof = self.release / 'proof'
        env = regular(self.release / 'app-runtime.env')
        preserved = read(self.release / 'binding.json')
        need(preserved['planSha256'] == self.plan_sha and sha(env.read_bytes()) == preserved['runtimeEnvSha256'] and
             stat.S_IMODE(env.stat().st_mode) == 0o600 and
             sha(regular(self.root / '.env').read_bytes()) == self.plan['envSha256'], 'data_environment_changed')
        source_hashes(self.source, self.files, exact=True)
        helper = {'action': action, 'name': 'family-dashboard-video-data-'+secrets.token_hex(12), 'id': None}
        self.data_helper, self.data_helper_stop = helper, None
        self.record('data_helper_create_intent', helper=dict(helper))
        args = ['create', '--name', helper['name'], '--label', 'family-dashboard.release-plan='+self.plan_sha,
                '--label', 'family-dashboard.data-action='+action,
                '--network', 'none', '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--memory', '384m', '--memory-swap', '384m',
                '--cpus', '1', '--pids-limit', '128', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=134217728,mode=1777',
                '--env-file', str(env), '--mount', 'type=volume,src='+VOLUME+',dst=/data'+('' if write else ',readonly'),
                '--mount', 'type=bind,src='+str(self.source)+',dst=/release,readonly',
                '--mount', 'type=bind,src='+str(proof)+',dst=/proof', '--entrypoint', 'python', self.images['app'],
                '-B', '-c', self.data_prefix+self.data_actions[action]+"\nprint(json.dumps(value))"]
        try:
            cid = self.docker(*args).decode().strip()
            need(re.fullmatch('[0-9a-f]{64}', cid), 'data_helper_create_unconfirmed')
            helper['id'] = cid
            self.record('data_helper_created', helper=dict(helper))
            state = self.helper_state(helper)
            need(state.get('Status') == 'created' and not state.get('Running'), 'data_helper_not_fresh')
            raw = self.docker('start', '--attach', cid, timeout=360)
            state = self.helper_state(helper)
            need(state.get('Status') == 'exited' and state.get('Running') is False and
                 state.get('ExitCode') == 0 and not state.get('OOMKilled'), 'data_helper_not_successful')
            value = json.loads(raw)
            need(value.get('verified') is True, 'data_operation_not_verified')
        except BaseException:
            self.stop_data_helper()
            raise
        need(self.stop_data_helper()['complete'], 'data_helper_stop_unconfirmed')
        return value

    def helper_state(self, helper):
        """Bind only the recorded CID; never persist its private inspect Config."""
        value = self.lifecycle.inspect(helper['id'])
        labels = value.get('Config', {}).get('Labels') or {}
        need(value.get('Id') == helper['id'] and value.get('Name') == '/'+helper['name'] and
             value.get('Image') == self.images['app'] and
             labels.get('family-dashboard.release-plan') == self.plan_sha and
             labels.get('family-dashboard.data-action') == helper['action'], 'data_helper_identity_changed')
        return value['State']

    def stop_data_helper(self):
        """Stop only this attempt's confirmed helper and prove no volume writer remains."""
        helper = self.data_helper
        result = {'complete': False, 'helper': dict(helper) if helper else None, 'failure': None}
        try:
            need(helper is not None and helper.get('id') is not None, 'data_helper_create_unconfirmed')
            state = self.helper_state(helper)
            if state.get('Running') or state.get('Status') not in ('created', 'exited', 'dead'):
                try:
                    self.docker('stop', '--signal', 'SIGTERM', '--timeout', '30', helper['id'], timeout=60)
                except BaseException as error:
                    result['stopErrorType'] = type(error).__name__
                # A failed/expired CLI is never evidence of a stopped daemon process.
                state = self.helper_state(helper)
            need(state.get('Running') is False and state.get('Pid') == 0 and
                 state.get('Status') in ('created', 'exited', 'dead'), 'data_helper_still_running')
            result['terminal'] = {key: state.get(key) for key in ('Status', 'Running', 'Pid', 'ExitCode', 'OOMKilled', 'FinishedAt')}
            self.stopped()
            result['complete'] = True
        except BaseException as error:
            result['failure'] = type(error).__name__+':'+str(error)
        self.data_helper_stop = result
        self.record('data_helper_stop_checked', **result)
        return result

    def install(self, old):
        self.stopped()
        old_expo = regular(self.root / 'static/experience', directory=True)
        old_expo.rename(self.release / 'expo-before')
        for name, digest in self.files.items():
            target = self.root / relative(name); target.parent.mkdir(parents=True, exist_ok=True)
            regular(target.parent, directory=True)
            need(not target.is_symlink(), 'linked_install_target')
            temporary = target.with_name(target.name+'.video-new')
            put(temporary, regular(self.source/name).read_bytes())
            temporary.chmod(0o755 if name.startswith('deploy/') and name.endswith('.sh') else 0o644)
            os.replace(temporary, target)
        for name in old['files'].keys()-self.files.keys():
            if name.startswith('static/experience/'): continue  # Preserved as an intact directory above.
            target = regular(self.root / relative(name))
            need(sha(target.read_bytes()) == old['files'][name], 'obsolete_source_changed')
            target.unlink()  # Exact manifest-owned, already backed-up file only.
        tmp = self.root / 'RELEASE-MANIFEST.json.video-new'
        put(tmp, regular(self.source/'RELEASE-MANIFEST.json').read_bytes()); tmp.chmod(0o644)
        os.replace(tmp, self.root/'RELEASE-MANIFEST.json')
        source_hashes(self.root, self.files)
        need(sha(regular(self.root/'.env').read_bytes()) == self.plan['envSha256'], 'environment_changed')
        self.docker('tag', self.images['app'], 'family-dashboard-app:latest')
        self.docker('tag', self.images['decoder'], 'family-dashboard-video-decoder:latest')

    def record(self, event, **fields):
        # Append-only phase receipts survive partial writes and never overwrite a failure.
        entries = list(self.release.glob('phase-*.json'))
        put(self.release / ('phase-%03d.json' % len(entries)), {'event': event, 'planSha256': self.plan_sha, **fields})

    def activate(self):
        need(not (self.candidate / 'activation-started.json').exists(), 'plan_consumed')
        self.evidence(); self.check_images()
        staged = read(self.candidate/'stage.json')
        old, captured = self.baseline()
        need(staged['planSha256'] == self.plan_sha and staged['services'] == captured and
             staged['parentFilesSha256'] == sha(encoded(old['files'])), 'staged_parent_changed')
        need(self.call(['systemctl', 'is-active', TIMER]).strip() == b'active', 'backup_timer_inactive')
        need(self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', 'family-dashboard-backup.service']).strip()
             == b'inactive', 'backup_running')
        put(self.candidate/'activation-started.json', {'planSha256': self.plan_sha})
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        self.release = regular(self.releases, directory=True) / (self.release_prefix+stamp)
        self.release.mkdir(mode=0o700)
        try:
            self.preserve(old, captured)
            put(self.release/'binding.json', {'planSha256': self.plan_sha,
                'runtimeEnvSha256': sha(regular(self.release/'app-runtime.env').read_bytes())})
            self.record('parent_source_and_configuration_preserved')
            self.call(['systemctl', 'stop', TIMER])
            need(self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', 'family-dashboard-backup.service']).strip()
                 == b'inactive', 'backup_raced_stop')
            self.lifecycle.drain('parent', captured); self.stopped()
            self.record('parent_writers_stopped')
            self.proof_init()
            backup = self.data_call('backup'); self.record('complete_group_backup_verified', result=backup)
            migrated = backup
            if self.needs_migration:
                migrated = self.data_call('migrate'); self.record('complete_group_migrated', result=migrated)
            self.install(old); self.record('candidate_source_installed')
            self.socket_ready()
            app = self.lifecycle.start_app_only()
            warm = """from app import create_app
import json
a=create_app();p=a.extensions['household_platform'];hs=p.households()
for h in hs:p.child(h)
print(json.dumps({'initialized':True,'households':len(hs)}))
"""
            warmed = json.loads(self.docker('exec', app['id'], 'python', '-B', '-c', warm, timeout=180))
            need(warmed.get('initialized') is True and warmed.get('households') == migrated['households'],
                 'registered_households_not_initialized')
            self.lifecycle.stop_app_only(app)
            preserved = self.data_call('check', write=False)
            self.record('app_only_stopped_preservation_verified', result=preserved)
            self.socket_ready()
            binding = {}
            if self.source_update:
                binding = {'plan_sha256': self.plan_sha,
                           'source_identity_sha256': sha(encoded(read(self.release/'proof/identity.json'))[:-1])}
            current = self.lifecycle.start_after_preservation(migrated, preserved, **binding)
            health = json.loads(self.call(['curl', '--fail', '--silent', '--show-error', '--max-time', '30',
                                          PUBLIC_ORIGIN+'/healthz']))
            need(health.get('status') == 'ok', 'public_health_failed')
            source_hashes(self.root, self.files)
            need(sha(regular(self.root/'.env').read_bytes()) == self.plan['envSha256'], 'environment_changed')
            self.call(['systemctl', 'start', TIMER])
            need(self.call(['systemctl', 'is-active', TIMER]).strip() == b'active', 'backup_timer_not_restarted')
            result = {'completed': True, 'planSha256': self.plan_sha, 'releaseDirectory': str(self.release),
                      'completedAt': datetime.now(timezone.utc).isoformat(), 'services': current,
                      'backup': backup, **({'migration': migrated} if self.needs_migration else {}),
                      'preservation': preserved,
                      'images': self.images, 'schema': self.after_schema}
            put(self.candidate/'activation.json', result)
            self.record('activation_complete')
            return result
        except BaseException as error:
            timer_stopped = False
            try:
                self.call(['systemctl', 'stop', TIMER]); timer_stopped = True
            except Exception:
                pass
            stopped = self.lifecycle.stop_after_failure()
            if self.data_helper is not None and not (self.data_helper_stop or {}).get('complete'):
                stopped['failed'].append('data-helper:stop_unverified')
                stopped['complete'] = False
            failure = {'completed': False, 'planSha256': self.plan_sha, 'releaseDirectory': str(self.release),
                       'errorType': type(error).__name__, 'candidateStop': stopped,
                       'dataHelperStop': self.data_helper_stop,
                       'backupTimerStopRequested': timer_stopped, 'automaticRestore': False}
            put(self.candidate/'failure.json', failure)
            raise

    def verify_rollback(self, release):
        """Verify a manually restored COMPLETE parent group; never restore/start it."""
        self.evidence()
        self.release = regular(Path(release).absolute(), directory=True)
        need(self.release.parent == self.releases and self.release.name.startswith(self.release_prefix), 'recovery_location')
        need(read(self.release/'binding.json')['planSha256'] == self.plan_sha and
             read(self.candidate/'activation-started.json')['planSha256'] == self.plan_sha, 'recovery_plan_binding')
        self.stopped()
        need(self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', TIMER]).strip() == b'inactive', 'recovery_timer_active')
        need(self.call(['systemctl', 'show', '-p', 'ActiveState', '--value', 'family-dashboard-backup.service']).strip()
             == b'inactive', 'recovery_backup_running')
        old = read(self.root/'RELEASE-MANIFEST.json', self.policy.PARENT_MANIFEST)
        source_hashes(self.root, old['files'])
        value = self.data_call('verify-rollback', write=False)
        put(self.release/'rollback-verified.json', {'planSha256': self.plan_sha, 'verified': True,
            'completeGroup': value, 'servicesStarted': False, 'operatorMustReviewBeforeRestart': True})
        return value


@contextmanager
def release_lock():
    import fcntl
    regular(RELEASES, directory=True)
    descriptors = []
    try:
        # Both historical operator families use this order in the video window.
        for name in ('.membership-release.lock', '.static-release.lock'):
            fd = os.open(RELEASES/name, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
            descriptors.append(fd)
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        for fd in reversed(descriptors): os.close(fd)


def main(argv=None, *, mode='video-migration'):
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('stage', 'activate', 'verify-rollback'))
    p.add_argument('candidate', type=Path); p.add_argument('plan_sha256')
    p.add_argument('--release', type=Path)
    a = p.parse_args(argv)
    need(sys.platform == 'linux' and os.geteuid() == 0 and sys.dont_write_bytecode and
         not sys.flags.optimize and sys.pycache_prefix is None, 'operator_runtime')
    need(not any(n.upper().startswith(('COMPOSE_', 'DOCKER_')) for n in os.environ), 'ambient_docker_selector')
    need(a.candidate.is_absolute() and a.candidate.parent == Path('/opt/family-dashboard-candidates'), 'candidate_location')
    need((a.release is not None) == (a.action == 'verify-rollback'), 'recovery_release_required')
    def interrupted(*_): raise ReleaseError('release_interrupted')
    for number in (signal.SIGTERM, signal.SIGINT): signal.signal(number, interrupted)
    with release_lock():
        c = Controller(a.candidate, a.plan_sha256, mode=mode)
        value = c.verify_rollback(a.release) if a.action == 'verify-rollback' else getattr(c, a.action)()
    print(json.dumps({'action': a.action, 'completed': value.get('completed', False),
                      'verified': value.get('verified', False), 'planSha256': a.plan_sha256}))


if __name__ == '__main__':
    try:
        main()
    except (ReleaseError, ValueError, KeyError, OSError):
        raise SystemExit('video_release_failed; preserve original receipts and stopped state; no automatic restore') from None
