from types import SimpleNamespace
from sync_worker import sync_household


def test_failed_publication_does_not_starve_existing_calendar_and_task_sync():
    seen=[]
    def bad():
        raise ValueError('must never log private provider body')
    application=SimpleNamespace(extensions={'task_publish':SimpleNamespace(tick=bad),'calendar_publish':SimpleNamespace(tick=bad),
        'cloud_accounts':SimpleNamespace(tick=lambda:seen.append('cloud_read'))})
    platform=SimpleNamespace(child=lambda _h:application)
    sync_household(platform,{'id':'test'})
    assert seen==['cloud_read']
