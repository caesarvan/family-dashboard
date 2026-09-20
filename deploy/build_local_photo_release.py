"""Fixed 73/9 local-photo and memories source update; no migration or decoder build."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASELINE = 'media-video-r1-local-photo'
KIND = 'local-photo-release-package'
INSTALLED_SOURCE = 'b8c4d599257d77709f65f455bab9e1a5d5c7aff1'
INSTALLED_TREE = '1ce81eb38bf9055cd650699ec0b3c7071a63b410'
PARENT_IMAGE = 'sha256:75d2cf07e1fe01eb56fe1fed999442b922d046eba52c64e4227ed176a0e975a5'
DECODER_IMAGE = 'sha256:005cc30d5eec73abdfa1fcc62f4d84d871edc2a1cc6169c96390e368f1511c8c'
OLD_MANIFEST = '20d4d43b69a8436df441283fe29a66388e535072f6cb117d1757525b78311291'
OLD_PACKAGE = 'e86eaf1632259195a6a96d56f1933a50edbe12b074f4a1f8111db0db5379f5ab'
AUDIT_SHA256 = '7b2b848631f54246159a23a67791941bc70b099a0462fdda9a19ad8bb4188ce8'
DOCKER_AFTER = 'e583bdf19a370535e7d99520f4193e17b1962a3e5100cde520cd462a158739e7'
COMPOSE_SHA256 = '677afc31a129ec955630bef0cdf124d476be2c0d6b939a77b2bb8472f6a0215f'
NGINX_BEFORE = 'c22066f070f5eeb80ddae0cd9d8973642148f7c3e324af46ce78e702c385dde9'
NGINX_AFTER = '5660e4e93bf9a56c208500cb7b73af430d5e8995b920badd48027f51ea5d3cd1'
DECODER_SOURCE_PINS = {
    'media_video_service.py': '407d80c87ca114e5a8c3d75ab3b45d2808ee3a2f23f19f536c5b41c81c131789',
    'deploy/Dockerfile.media-video-service': 'da0ec9958d0d63259e328fd2cab0ba0610b1049b362ae1584f89d7591d23f046',
}
SCHEMA_BEFORE = SCHEMA_AFTER = (73, 9)
NON_EXPO_RUNTIME_COUNT = 112
PRESERVED_RUNTIME_COUNT = 105
# Parent map minus exactly six existing changed modules; local uploader is new.
CHANGED_RUNTIME_FILES = frozenset({'app.py', 'home_assistant.py', 'data_portability.py',
    'household_media.py', 'media_playback.py', 'media_images.py', 'media_local_upload.py'})
PRESERVED_RUNTIME_SHA256 = '1f610adb441e515035f5f8b4aca4459862e06cb9c402346946f5f93cae90d17c'
RUNTIME_ADDITIONS = frozenset(['app.py', 'assistant_finance_query.py', 'assistant_trip_change_api.py', 'assistant_trip_intent.py', 'calendar_privacy.py', 'calendar_publish.py', 'cloud_accounts.py', 'cloud_providers.py', 'dashboard_preferences.py', 'data_portability.py', 'finance_accounts.py', 'finance_analysis.py', 'finance_baseline.py', 'finance_fx.py', 'finance_hub.py', 'finance_source_bridge.py', 'financial_files.py', 'frontend_runtime.py', 'google_photos_picker.py', 'home_assistant.py', 'household_media.py', 'household_members.py', 'household_memberships.py', 'household_routines.py', 'household_spaces.py', 'inventory_api.py', 'inventory_core.py', 'inventory_sources.py', 'investment_import.py', 'investment_operations.py', 'journey_documents.py', 'journey_places.py', 'journey_reschedule.py', 'journey_routes.py', 'journey_time.py', 'journey_workflows.py', 'media_crypto.py', 'media_images.py', 'media_import_worker.py', 'media_playback.py', 'media_playback_progress.py', 'media_video_storage.py', 'media_video_transport.py', 'media_videos.py', 'member_sessions.py', 'membership_http.py', 'membership_storage.py', 'personal_accounts.py', 'shopping_media.py', 'shopping_settlement.py', 'spending_observations.py', 'sync_health.py', 'sync_worker.py', 'task_dependencies.py', 'task_publish.py', 'task_reminders.py', 'tv_display.py', 'media_local_upload.py'])
FRONTEND_TESTS = frozenset(['frontend/tests/assistantDocumentSearch.test.mjs', 'frontend/tests/assistantFinanceQuery.test.mjs', 'frontend/tests/assistantTripChange.test.mjs', 'frontend/tests/calendarConflicts.test.mjs', 'frontend/tests/calendarPrivacy.test.mjs', 'frontend/tests/financeAnalysis.test.mjs', 'frontend/tests/inventoryFollowup.test.mjs', 'frontend/tests/inventorySources.test.mjs', 'frontend/tests/journeyBriefItems.test.mjs', 'frontend/tests/journeyRoutes.test.mjs', 'frontend/tests/journeySegments.test.ts', 'frontend/tests/localPhotoUpload.test.mjs', 'frontend/tests/localPhotoUploadPanel.test.mjs', 'frontend/tests/mediaUsability.test.mjs', 'frontend/tests/memberVideo.test.mjs', 'frontend/tests/photoMemories.test.mjs', 'frontend/tests/shoppingSchedule.test.mjs', 'frontend/tests/taskDependencies.test.mjs', 'frontend/tests/taskPublish.test.mjs', 'frontend/tests/taskReminders.test.mjs', 'frontend/tests/tvMedia.test.mjs'])
BROWSER_SCRIPTS = frozenset(['scripts/check_expo_calendar_conflicts_browser.py', 'scripts/check_expo_calendar_privacy_browser.py', 'scripts/check_expo_local_photo_browser.py', 'scripts/check_expo_media_video_browser.py', 'scripts/check_expo_photo_memories_browser.py', 'scripts/check_expo_task_dependencies_browser.py', 'scripts/check_expo_task_reminders_browser.py'])

from deploy import membership_release_package as package
from deploy import membership_release_build as builder


def prepare(**kwargs):
    return package.prepare(**kwargs, baseline=BASELINE)


def verify_package(output_dir, package_sha256):
    return package.verify_package(output_dir, package_sha256, baseline=BASELINE)


def build(**kwargs):
    return builder.build(**kwargs, baseline=BASELINE)


def validate(**kwargs):
    return builder.validate(**kwargs, baseline=BASELINE)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    fields = {
        'prepare': ('repo', 'commit', 'export-dir', 'build-evidence', 'evidence-sha256', 'output-dir'),
        'verify': ('output-dir', 'package-sha256'),
        'build': ('package-dir', 'package-sha256', 'output-dir'),
        'validate': ('package-dir', 'package-sha256', 'image-id', 'selection', 'selection-sha256', 'output-dir'),
    }
    for name, names in fields.items():
        command = commands.add_parser(name)
        for field in names:
            command.add_argument('--'+field, required=True)
        if name == 'validate': command.add_argument('--pytest-dependencies', default=builder.DEPS)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    if action == 'verify':
        checked = verify_package(**args)
        result = {'verified': True, 'sourceHead': checked['metadata']['sourceHead'], 'files': len(checked['blobs'])}
    else: result = {'prepare': prepare, 'build': build, 'validate': validate}[action](**args)
    print(json.dumps(result))
    return 0 if result.get('allPassed', True) else 1


if __name__ == '__main__': raise SystemExit(main())
