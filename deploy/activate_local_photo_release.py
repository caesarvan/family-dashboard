"""Fixed five-service 73/9 source update; never run the 71-to-73 migration."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import media_video_release_controller as shared


class Controller(shared.Controller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, mode='local-photo-source-update')


def verify_restored_group(root, proof, *, source_identity, plan_sha256):
    """Verify the explicitly restored full 73/9 group, retained backup and binding.

    This helper runs read-only with every data/socket writer stopped. It does
    not restore, initialize, migrate, delete sidecars or restart services.
    """
    from deploy import media_video_release_data as data
    from deploy import membership_release_data as core
    proof = core._directory(proof)
    before = core._read_json(core._relative(proof, 'before.json'))
    attempt = core._read_json(core._relative(proof, 'attempt.json'))
    identity = core._source_identity(source_identity)
    core.need(attempt == {'kind': data.SPEC.attempt_kind, 'planSha256': plan_sha256,
        'beforeSha256': core._digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': core._digest(identity), 'markerSha256': data.MEMBERSHIP_MARKER_SHA256},
        'local_photo_restore_binding')
    data.SPEC.profile(before)
    receipt = core._read_json(core._relative(proof, 'backup.json'))
    manifest = core._relative(proof / 'backup-group/backups', receipt['manifest'])
    backup = data.validate_backup(root, before, manifest)
    core.need(backup == core._read_json(core._relative(proof, 'backup-verified.json')), 'retained_backup_changed')
    return data.verify_restore(before, root, marker_sha256=attempt['markerSha256'])


def main(argv=None):
    return shared.main(argv, mode='local-photo-source-update')


if __name__ == '__main__':
    main()
