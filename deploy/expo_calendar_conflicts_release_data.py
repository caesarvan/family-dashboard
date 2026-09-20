"""Populated 71/9 preservation using the existing closed reader and backup core.

No DDL or initializer runs here. All reminder states and operation receipts, plus all previous tables, are part of the complete logical snapshot.
"""
import re

from deploy import assistant_trip_change_release_data as shared
from deploy import check_task_reminders_migration as reminders

MEMBERSHIP_MARKER_SHA256 = shared.MEMBERSHIP_MARKER_SHA256
marker_digest = shared.marker_digest
snapshot = snapshot_current = reminders.snapshot_current
verify_restore = reminders.verify_restore


def _profile(value):
    shared.need(isinstance(value, dict) and set(value) == {'format', 'rootSha256', 'households', 'databases'}
                and value['format'] == 'membership-database-group-v1', 'snapshot_shape')
    shared.need(type(value['households']) is int and value['households'] >= 1 and
                len(value['databases']) == value['households'] + 1 and
                {'platform.sqlite3', 'household.sqlite3'} <= value['databases'].keys(), 'snapshot_group')
    for path, fingerprint in value['databases'].items():
        platform = path == 'platform.sqlite3'
        shared.need(platform or path == 'household.sqlite3' or
                    re.fullmatch('spaces/[0-9a-f]{24}/household.sqlite3', path), 'snapshot_path')
        expected = (shared.migration.BASE_PLATFORM_TABLES | shared.migration.NEW_PLATFORM_TABLES
                    if platform else reminders.BASE_TABLES | reminders.NEW_TABLES)
        tables = {n for n in fingerprint['tables'] if not n.startswith('sqlite_')}
        shared.need(tables == expected and len(tables) == (9 if platform else 71), 'expected_71_9_profile')
        shared.need(fingerprint['userVersion'] == (1 if platform else 0) and
                    fingerprint['membershipPhase'] == ('after' if platform else 'partial_or_unknown'),
                    'snapshot_version_profile')


SPEC = shared.DataSpec(_profile, snapshot_current, 'expo-calendar-conflicts-release-attempt')


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
