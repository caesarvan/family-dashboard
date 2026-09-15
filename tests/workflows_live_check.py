"""Read-only acceptance for the four workflow increments after deployment.

Reuses platform_live_check for all 23 frozen static assets, mobile/desktop
navigation and TV demo. Adds anonymous GET authorization checks and synthetic
home-layout interaction. Never reads credentials or dispatches production writes.
Run only after root confirms that this exact local release is live.
"""
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

import platform_live_check as platform


INCREMENT_GET_PATHS = [
    '/api/dashboard-layout',
    '/api/portability/summary',
    '/api/finance-hub/reconciliation',
    '/api/task-publish/state',
]


def demo_checks(args, output):
    result = {'requests': [], 'blockedRequests': [], 'pageErrors': [],
              'layoutPersistence': 'ephemeral browser localStorage only',
              'authenticatedWorkflowsExercised': False, 'completed': False}
    launch_args = ['--no-proxy-server']
    if args.resolve:
        launch_args.append(f'--host-resolver-rules=MAP {args.hostname} {args.resolve}')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.edge, headless=True, args=launch_args)
        context = browser.new_context(viewport={'width': 390, 'height': 844},
                                      ignore_https_errors=False, service_workers='block')

        def intercept(route):
            request = route.request
            url = urlsplit(request.url)
            reason = None
            if request.method not in {'GET', 'HEAD'}:
                reason = 'write'
            elif url.scheme in {'http', 'https'} and url.scheme + '://' + url.netloc != args.origin:
                reason = 'external'
            elif url.path.startswith(('/auth/', '/space/', '/api/pair/')) or url.path == '/tv':
                reason = 'sensitive-read'
            if reason:
                result['blockedRequests'].append({'method': request.method, 'path': url.path, 'reason': reason})
                route.abort()
                return
            result['requests'].append({'method': request.method, 'path': url.path})
            route.continue_()

        context.route('**/*', intercept)
        page = context.new_page()
        page.on('pageerror', lambda error: result['pageErrors'].append(str(error)))
        try:
            page.goto(args.origin + '/demo', wait_until='domcontentloaded')
            expect(page.locator('.ps-welcome')).to_be_visible()
            exports = page.evaluate('''() => ({
                layout: typeof window.ProductShell?.openLayout === 'function',
                taskPublish: typeof window.TaskPublish?.open === 'function',
                dataPortability: typeof window.DataPortability?.open === 'function',
                financeHub: typeof window.FinanceHub?.open === 'function'
            })''')
            assert all(exports.values()), exports
            result['moduleExports'] = exports

            page.locator('[data-ps-layout]').click()
            form = page.locator('#ps-layout-form')
            expect(form).to_be_visible()
            expect(form.locator('[type=submit]')).to_be_enabled()
            expect(form.locator('[data-layout-card]')).to_have_count(5)
            form.locator('[data-layout-card="trips"]').focus()
            page.keyboard.press('Alt+ArrowUp')
            assert form.locator('[data-layout-card]').evaluate_all('(nodes) => nodes.map(node => node.dataset.layoutCard)') == [
                'calendar', 'finance', 'tasks', 'trips', 'shopping']
            form.locator('[data-layout-visible="finance"]').uncheck()
            page.screenshot(path=str(output / 'workflows-live-layout-editor-phone.png'))
            form.locator('[type=submit]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('.ps-home-board > .card')).to_have_count(4)
            actual = page.evaluate('() => ProductShell.getLayout()')
            assert actual['order'] == ['calendar', 'finance', 'tasks', 'trips', 'shopping']
            assert actual['hidden'] == ['finance']
            width = page.evaluate('() => document.documentElement.scrollWidth')
            assert width <= 391, width
            page.screenshot(path=str(output / 'workflows-live-custom-home-phone.png'))

            page.reload(wait_until='domcontentloaded')
            expect(page.locator('.ps-home-board > .card')).to_have_count(4)
            assert page.evaluate('() => ProductShell.getLayout().hidden') == ['finance']
            result['demoLayout'] = {'keyboardReorder': True, 'hideCard': True,
                                   'reloadRetainsDemoPreference': True, 'horizontalOverflow': False}

            page.evaluate("() => ProductShell.navigate('settings')")
            expect(page.locator('[data-ps-page="settings"]')).to_be_visible()
            expect(page.locator('[data-portability-open]')).to_have_count(0)
            page.evaluate("() => ProductShell.navigate('tasks')")
            expect(page.locator('[data-ps-page="tasks"]')).to_be_visible()
            expect(page.locator('[data-task-publish-open]')).to_have_count(0)
            result['demoPrivateActions'] = {'exportVisible': False, 'publishVisible': False}

            page.set_viewport_size({'width': 1920, 'height': 1080})
            page.goto(args.origin + '/demo?tv=1', wait_until='domcontentloaded')
            expect(page.locator('.tv .board > .card')).to_have_count(5)
            expect(page.locator('[data-ps-layout], [data-portability-open], [data-task-publish-open]')).to_have_count(0)
            result['tvIgnoresDemoMemberLayout'] = True
            assert not result['blockedRequests'], result['blockedRequests']
            assert not result['pageErrors'], result['pageErrors']
            assert not any(item['path'] in INCREMENT_GET_PATHS for item in result['requests']), result['requests']
            result['completed'] = True
        finally:
            context.close()
            browser.close()
    return result


def main():
    args = platform.settings()
    output = platform.ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    report = {'startedAt': datetime.now(timezone.utc).isoformat(), 'origin': args.origin,
              'readOnly': True, 'credentialsRead': False, 'completed': False,
              'scope': 'Anonymous HTTPS GET checks and synthetic demo only; no member login, TV pairing, OAuth or real workflow writes.'}
    try:
        platform.ANONYMOUS_PATHS = list(dict.fromkeys(platform.ANONYMOUS_PATHS + INCREMENT_GET_PATHS))
        platform.main()
        baseline = json.loads((output / 'platform-live-browser-verification.json').read_text(encoding='utf-8'))
        report['platform'] = baseline
        assert baseline['completed'] and len(baseline['staticAssets']) == 23
        assert all(baseline['anonymousProtection'][path] == 401 for path in INCREMENT_GET_PATHS)
        report['incrementsAnonymousProtection'] = {path: baseline['anonymousProtection'][path] for path in INCREMENT_GET_PATHS}
        report['demoIncrementChecks'] = demo_checks(args, output)
        report['completed'] = True
    except Exception as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)[:1800]}
        raise
    finally:
        report['finishedAt'] = datetime.now(timezone.utc).isoformat()
        path = output / 'workflows-live-browser-verification.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'completed': report['completed'], 'report': str(path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
