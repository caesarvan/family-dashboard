"""Read-only release acceptance against a live HTTPS origin.

Never reads credentials, logs in, starts TV pairing or visits OAuth callbacks.
Browser interception blocks every non-GET/HEAD request before network dispatch.
Run only after the intended release is deployed; local static hashes must match.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORIGIN = 'https://home.caesarcharles.world'
DEFAULT_IP = '96.44.160.28'
ROUTES = ['home', 'calendar', 'tasks', 'shopping', 'trips', 'finance', 'assistant', 'connections', 'settings', 'household']
ANONYMOUS_PATHS = ['/api/state', '/api/preferences', '/api/assistant/brief',
                   '/api/finance-hub/overview', '/api/finance-baseline/private', '/api/journeys']


def settings():
    parser = argparse.ArgumentParser(description='Read-only live HTTPS product acceptance; no credentials required.')
    parser.add_argument('--origin', default=DEFAULT_ORIGIN)
    parser.add_argument('--resolve', default=DEFAULT_IP, help='IP address for the origin hostname; empty string uses normal DNS.')
    parser.add_argument('--edge', default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    args = parser.parse_args()
    parsed = urlsplit(args.origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        parser.error('--origin must be an HTTPS origin without credentials, paths or query parameters')
    args.origin = args.origin.rstrip('/')
    if args.resolve:
        try:
            ipaddress.ip_address(args.resolve)
        except ValueError:
            parser.error('--resolve must be an IPv4/IPv6 address, or an empty string for normal DNS')
    args.hostname = parsed.hostname
    return args


def get(page, path, *, binary=False):
    # Using browser fetch retains Chromium DNS overrides and strict TLS checks.
    return page.evaluate('''async ({path,binary}) => {
      const response = await fetch(path,{method:'GET',credentials:'omit',cache:'no-store',redirect:'error'});
      const bytes = new Uint8Array(await response.arrayBuffer());
      const result = {status:response.status,contentType:response.headers.get('content-type'),bytes:bytes.length};
      if(binary){const digest=await crypto.subtle.digest('SHA-256',bytes);result.sha256=[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('');}
      else {const text=new TextDecoder().decode(bytes);try{result.json=JSON.parse(text)}catch{result.text=text.slice(0,1000)}}
      return result;
    }''', {'path': path, 'binary': binary})


def main():
    args = settings()
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    report_path = output / 'platform-live-browser-verification.json'
    report = {'origin': args.origin, 'startedAt': datetime.now(timezone.utc).isoformat(),
              'tlsVerification': 'strict', 'readOnly': True, 'credentialsRead': False,
              'blockedWrites': [], 'blockedSensitiveReads': [], 'blockedExternalRequests': [],
              'pageErrors': [], 'staticAssets': [], 'layouts': [], 'completed': False}
    launch_args = ['--no-proxy-server']
    if args.resolve:
        launch_args.append(f'--host-resolver-rules=MAP {args.hostname} {args.resolve}')
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=args.edge, headless=True, args=launch_args)
            context = browser.new_context(viewport={'width': 1440, 'height': 1050},
                                          ignore_https_errors=False, service_workers='block')
            def intercept(route):
                request = route.request
                url = urlsplit(request.url)
                if request.method not in {'GET', 'HEAD'}:
                    report['blockedWrites'].append({'method': request.method, 'path': url.path})
                    route.abort()
                    return
                if url.scheme in {'http', 'https'} and (url.scheme + '://' + url.netloc) != args.origin:
                    report['blockedExternalRequests'].append({'host': url.hostname, 'path': url.path})
                    route.abort()
                    return
                if url.path.startswith(('/auth/', '/space/', '/api/pair/')) or url.path == '/tv':
                    report['blockedSensitiveReads'].append(url.path)
                    route.abort()
                    return
                route.continue_()
            context.route('**/*', intercept)
            page = context.new_page()
            page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
            try:
                response = page.goto(args.origin + '/', wait_until='domcontentloaded')
                assert response.status == 200
                expect(page.locator('#login-form')).to_be_visible()
                assert page.locator('#login-form [name=password]').input_value() == ''
                report['loginPage'] = {'status': response.status, 'formVisible': True, 'loginAttempted': False}
                page.screenshot(path=str(output / 'platform-live-login.png'))
                health = get(page, '/healthz')
                assert health['status'] == 200 and health['json']['status'] == 'ok', health
                report['health'] = health['json']
                current = get(page, '/api/spaces/current')
                assert current['status'] == 200 and isinstance(current.get('json'), dict), current
                report['publicSpace'] = {key: current['json'].get(key) for key in ('id', 'name', 'slug', 'canInvite')}
                providers = get(page, '/api/auth/providers')
                assert providers['status'] == 200, providers
                payload = providers.get('json', {})
                entries = payload.get('providers', payload) if isinstance(payload, dict) else payload
                if isinstance(entries, dict):
                    entries = [{'provider': key, **value} for key, value in entries.items() if isinstance(value, dict)]
                report['providers'] = [{key: entry[key] for key in ('id', 'provider', 'name', 'configured', 'enabled') if key in entry}
                                       for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
                report['providerConfigurationNote'] = 'Recorded without asserting configuration; real OAuth authorization is not exercised.'
                report['anonymousProtection'] = {}
                for path in ANONYMOUS_PATHS:
                    checked = get(page, path)
                    report['anonymousProtection'][path] = checked['status']
                    assert checked['status'] == 401, (path, checked['status'])
                manifest = get(page, '/static/manifest.webmanifest')
                assert manifest['status'] == 200 and isinstance(manifest.get('json'), dict), manifest
                document = manifest['json']
                assert document.get('name') and document.get('start_url') == '/' and document.get('scope') == '/'
                assert document.get('display') in {'standalone', 'minimal-ui', 'fullscreen'} and document.get('icons')
                assert all(isinstance(icon.get('src'), str) and icon['src'].startswith('/static/') for icon in document['icons'])
                report['manifest'] = {'valid': True, 'name': document['name'], 'display': document['display']}
                # The local index is the source of truth for the deployed assets.
                # No .env, private report, access bundle, database or account file is opened.
                index = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
                assets = set(re.findall(r'(?:href|src)="(/static/[A-Za-z0-9_.-]+)"', index))
                assets.update(icon['src'] for icon in document['icons'])
                for path in sorted(assets):
                    local = ROOT / path.lstrip('/')
                    assert local.is_file() and local.resolve().is_relative_to((ROOT / 'static').resolve()), path
                    expected_hash = hashlib.sha256(local.read_bytes()).hexdigest()
                    actual = get(page, path, binary=True)
                    matched = actual['status'] == 200 and actual['sha256'] == expected_hash
                    report['staticAssets'].append({'path': path, 'status': actual['status'], 'matchedLocalSHA256': matched,
                                                   'sha256': actual.get('sha256')})
                    assert matched, ('Static asset mismatch', path)
                page.goto(args.origin + '/demo', wait_until='domcontentloaded')
                expect(page.locator('.ps-welcome')).to_be_visible()
                for label, width, height in [('desktop', 1440, 1050), ('phone', 390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    for name in ROUTES:
                        page.evaluate('(route) => ProductShell.navigate(route)', name)
                        expect(page.locator(f'[data-ps-page="{name}"]')).to_be_visible()
                        dimensions = page.evaluate('() => ({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                        assert dimensions['scroll'] <= width + 1, (label, name, dimensions)
                        report['layouts'].append({'view': label, 'route': name, 'horizontalOverflow': False})
                        if name == 'home':
                            page.screenshot(path=str(output / f'platform-live-demo-{label}.png'))
                # This is explicitly the synthetic TV demo; /tv pairing is blocked.
                page.set_viewport_size({'width': 1920, 'height': 1080})
                page.goto(args.origin + '/demo?tv=1', wait_until='domcontentloaded')
                expect(page.locator('.tv .board')).to_be_visible()
                screen = page.evaluate('''() => ({width:innerWidth,height:innerHeight,
                  scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,
                  cards:[...document.querySelectorAll('.board>.card')].map(el=>({height:el.clientHeight,scroll:el.scrollHeight,bottom:el.getBoundingClientRect().bottom}))})''')
                assert screen['scrollWidth'] <= 1921 and screen['scrollHeight'] <= 1081, screen
                assert len(screen['cards']) == 5 and all(card['scroll'] <= card['height'] + 2 and card['bottom'] <= 1081 for card in screen['cards']), screen
                report['tvDemo'] = {'width': 1920, 'height': 1080, 'cardCount': len(screen['cards']), 'layout': 'passed', 'pairingAttempted': False}
                page.screenshot(path=str(output / 'platform-live-demo-tv.png'))
                assert not report['pageErrors'], report['pageErrors']
                assert not report['blockedWrites'], report['blockedWrites']
                assert not report['blockedSensitiveReads'], report['blockedSensitiveReads']
                assert not report['blockedExternalRequests'], report['blockedExternalRequests']
                report['completed'] = True
            finally:
                context.close()
                browser.close()
    except Exception as error:
        # Diagnostic omits request bodies, credentials and raw API datasets.
        report['failure'] = {'type': type(error).__name__, 'message': str(error)[:1800]}
        raise
    finally:
        report['finishedAt'] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'completed': report['completed'], 'staticAssets': len(report['staticAssets']),
                          'layouts': len(report['layouts']), 'pageErrors': len(report['pageErrors']),
                          'blockedWrites': len(report['blockedWrites']), 'report': str(report_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
