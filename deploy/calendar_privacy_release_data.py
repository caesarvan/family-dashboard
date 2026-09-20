"""Strict populated 71/9 source-update preservation; no DDL or backfill."""
from deploy import assistant_trip_change_release_data as shared
from deploy import expo_calendar_conflicts_release_data as previous

MEMBERSHIP_MARKER_SHA256 = previous.MEMBERSHIP_MARKER_SHA256
marker_digest = previous.marker_digest
snapshot = snapshot_current = previous.snapshot_current
verify_restore = previous.verify_restore
SPEC = shared.DataSpec(previous._profile, snapshot_current, 'calendar-privacy-release-attempt')


def validate_backup(data_root, before, manifest_path, *, phase='current'):
    return shared.validate_backup(data_root, before, manifest_path, phase=phase, spec=SPEC)


def finish_stopped_backup(data_root, before, manifest_path, *, phase='current'):
    return shared.finish_stopped_backup(data_root, before, manifest_path, phase=phase, spec=SPEC)


def begin(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    return shared.begin(root, proof, source_identity=source_identity, plan_sha256=plan_sha256,
                        marker_sha256=marker_sha256, spec=SPEC)


def check_stopped(root, proof, *, source_identity, plan_sha256, marker_sha256=MEMBERSHIP_MARKER_SHA256):
    return shared.check_stopped(root, proof, source_identity=source_identity, plan_sha256=plan_sha256,
                                marker_sha256=marker_sha256, spec=SPEC)
