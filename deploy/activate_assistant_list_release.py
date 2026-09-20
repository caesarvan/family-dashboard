"""Assistant list update on the installed five-service 75/9 database group."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deploy import media_video_release_controller as shared


class Controller(shared.Controller):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, mode='assistant-list-source-update')


def verify_restored_group(root, proof, *, source_identity, plan_sha256):
    """Read-only verification after an explicit complete 75/9 group restore."""
    from deploy import journey_finance_release_data as data
    from deploy import membership_release_data as core
    proof = core._directory(proof)
    before = core._read_json(core._relative(proof, 'before.json'))
    attempt = core._read_json(core._relative(proof, 'attempt.json'))
    identity = core._source_identity(source_identity)
    core.need(attempt == {'kind': data.SPEC.attempt_kind, 'planSha256': plan_sha256,
        'beforeSha256': core._digest(before), 'sourceIdentity': identity,
        'sourceIdentitySha256': core._digest(identity), 'markerSha256': data.MEMBERSHIP_MARKER_SHA256},
        'assistant_list_restore_binding')
    data.SPEC.profile(before)
    receipt = core._read_json(core._relative(proof, 'backup.json'))
    manifest = core._relative(proof / 'backup-group/backups', receipt['manifest'])
    backup = data.validate_backup(root, before, manifest)
    core.need(backup == core._read_json(core._relative(proof, 'backup-verified.json')), 'retained_backup_changed')
    return data.verify_restore(before, root, marker_sha256=attempt['markerSha256'])


def main(argv=None):
    return shared.main(argv, mode='assistant-list-source-update')


if __name__ == '__main__':
    main()
