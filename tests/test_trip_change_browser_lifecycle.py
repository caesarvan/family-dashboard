"""Real Playwright/loopback HTTP coverage of the browser helper's route lifetime.

This tests the harness, not the Expo product or an AI provider.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
from threading import Thread

from playwright.sync_api import sync_playwright
import pytest

from browser_expo_assistant_trip_change_check import BUILD_REUSE_PATHS, Run, build_source_delta


@pytest.mark.parametrize('drop', [False, True], ids=['fulfill', 'drop'])
def test_actual_post_waits_for_callback_and_terminal_route_before_unroute(tmp_path, drop):
    received = []
    body = b'{"source":"loopback-response","value":17}'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<button onclick="fetch(\'/exchange\', {method:\'POST\', '
                             b'headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({value:17})})'
                             b'.catch(()=>{})">Send</button>')

        def do_POST(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            received.append((self.path, json.loads(raw)))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    events = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                base = 'http://127.0.0.1:' + str(server.server_port)
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                page.goto(base)

                class ObservedPage:
                    def __getattr__(self, name):
                        return getattr(page, name)

                    def route(self, url, handler):
                        def observed(route):
                            handler(route)
                            events.append('route-complete')
                        self.handler = observed
                        page.route(url, observed)

                    def unroute(self, url, _handler):
                        events.append('unroute')
                        page.unroute(url, self.handler)

                run = Run.__new__(Run)
                run.base, run.out, run.exchange_number = base, tmp_path, 0

                def after_response():
                    events.append('callback-start')
                    # Yield while the real handler is active, as the session
                    # replacement callback does with its own HTTP request.
                    page.wait_for_timeout(150)
                    response = context.request.post(base + '/checkpoint', data={'actor': 2})
                    assert response.status == 200
                    events.append('callback-complete')

                result = run.actual_post(ObservedPage(), '/exchange',
                    lambda: page.get_by_role('button', name='Send', exact=True).click(),
                    drop=drop, after_response=after_response)
                assert events == ['callback-start', 'callback-complete', 'route-complete', 'unroute']
                assert received == [('/exchange', {'value': 17}), ('/checkpoint', {'actor': 2})]
                assert result['status'] == 200 and result['result'] == json.loads(body)
                assert (tmp_path / 'exchange-01.body').read_bytes() == body
            finally:
                browser.close()
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        assert not worker.is_alive()


@pytest.fixture
def build_repo(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Synthetic Browser Test',
            '-c', 'user.email=synthetic@example.invalid', *args], cwd=tmp_path).decode().strip()
    git('init', '--quiet')
    file = tmp_path / 'frontend' / 'App.tsx'
    file.parent.mkdir()
    file.write_text('synthetic frontend\n', encoding='utf-8')
    git('add', '--', 'frontend/App.tsx')
    git('commit', '--quiet', '-m', 'Synthetic build source')
    head = git('rev-parse', 'HEAD')
    evidence = {'sourceHead': head, 'sourceTree': git('rev-parse', 'HEAD^{tree}')}

    def change(path):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('synthetic changed file\n', encoding='utf-8')
        git('add', '--', path)
        git('commit', '--quiet', '-m', 'Synthetic delta')
        return git('rev-parse', 'HEAD')
    return git, head, evidence, change


@pytest.mark.parametrize('path', sorted(BUILD_REUSE_PATHS))
def test_exact_build_or_explicit_harness_only_descendant_is_accepted(build_repo, path):
    git, build_head, evidence, change = build_repo
    assert build_source_delta(git, build_head, evidence, build_head) == []
    run_head = change(path)
    assert build_source_delta(git, run_head, evidence, build_head) == [path]
    with pytest.raises(AssertionError):
        build_source_delta(git, run_head, evidence, run_head)  # No implicit reuse.


@pytest.mark.parametrize('path', ['frontend/App.tsx', 'app.py', 'assistant_trip_intent.py'])
def test_build_reuse_rejects_product_source_changes(build_repo, path):
    git, build_head, evidence, change = build_repo
    with pytest.raises(AssertionError, match='only the reviewed harness'):
        build_source_delta(git, change(path), evidence, build_head)


def test_build_reuse_rejects_wrong_tree_and_non_ancestor(build_repo):
    git, build_head, evidence, change = build_repo
    with pytest.raises(AssertionError):
        build_source_delta(git, build_head, {**evidence, 'sourceTree': '0' * 40}, build_head)
    later = change('docs/EXPO-ASSISTANT-TRIP-CHANGE.md')
    later_evidence = {'sourceHead': later, 'sourceTree': git('rev-parse', later + '^{tree}')}
    with pytest.raises(AssertionError, match='ancestor'):
        build_source_delta(git, build_head, later_evidence, later)
