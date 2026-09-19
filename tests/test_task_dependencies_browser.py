"""Harness guard tests only; these are not the three browser product flows."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts.check_expo_task_dependencies_browser import ADD_TASK_NAME, BUILD_REUSE_PATHS, build_source_delta, completed_periodic_refresh, deliver


@pytest.fixture
def source_repo(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Synthetic Harness Test',
            '-c', 'user.email=synthetic@example.invalid', *args], cwd=tmp_path).decode().strip()
    git('init', '--quiet')
    target = tmp_path / 'frontend' / 'app.tsx'
    target.parent.mkdir(); target.write_text('synthetic source\n', encoding='utf-8')
    git('add', '--', 'frontend/app.tsx'); git('commit', '--quiet', '-m', 'Synthetic source')
    head = git('rev-parse', 'HEAD')
    evidence = {'sourceHead': head, 'sourceTree': git('rev-parse', 'HEAD^{tree}')}
    def change(name):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic changed source\n', encoding='utf-8')
        git('add', '--', name); git('commit', '--quiet', '-m', 'Synthetic change')
        return git('rev-parse', 'HEAD')
    return git, head, evidence, change


def test_exact_source_or_explicit_harness_only_ancestor(source_repo):
    git, head, evidence, change = source_repo
    assert build_source_delta(git, head, evidence, head) == []
    for name in sorted(BUILD_REUSE_PATHS):
        current = change(name)
        assert set(build_source_delta(git, current, evidence, head)) <= BUILD_REUSE_PATHS
        with pytest.raises(AssertionError):
            build_source_delta(git, current, evidence, current)


@pytest.mark.parametrize('name', ['frontend/app.tsx', 'task_dependencies.py', 'app.py', 'tests/browser_expo_finance_check.py'])
def test_reuse_rejects_any_changed_product_or_fixture(source_repo, name):
    git, head, evidence, change = source_repo
    with pytest.raises(AssertionError, match='only this reviewed harness'):
        build_source_delta(git, change(name), evidence, head)


def test_build_tree_and_ancestry_are_verified(source_repo):
    git, head, evidence, change = source_repo
    with pytest.raises(AssertionError):
        build_source_delta(git, head, {**evidence, 'sourceTree': '0' * 40}, head)
    later = change('docs/EXPO-TASK-DEPENDENCIES-BROWSER.md')
    later_evidence = {'sourceHead': later, 'sourceTree': git('rev-parse', 'HEAD^{tree}')}
    with pytest.raises(AssertionError, match='ancestor'):
        build_source_delta(git, head, later_evidence, later)


@pytest.mark.parametrize('fault', ['abort', 'gateway503'])
def test_commit_loss_injection_requires_backend_success(fault):
    calls = []
    route = SimpleNamespace(abort=lambda *args: calls.append(('abort', args)),
                            fulfill=lambda **kwargs: calls.append(('fulfill', kwargs)))
    response = SimpleNamespace(status=409, headers={}, body=lambda: b'{"error":"conflict"}')
    with pytest.raises(AssertionError, match='failed backend write'):
        deliver(route, response, fault)
    assert calls == []
    response.status = 201
    deliver(route, response, fault)
    assert len(calls) == 1
    if fault == 'abort':
        assert calls[0] == ('abort', ('failed',))
    else:
        assert calls[0][0] == 'fulfill' and calls[0][1]['status'] == 503
        assert set(json.loads(calls[0][1]['body'])) == {'error'}


def test_normal_delivery_preserves_real_error_bytes():
    calls = []
    route = SimpleNamespace(fulfill=lambda **kwargs: calls.append(kwargs))
    response = SimpleNamespace(status=409, headers={'Content-Type': 'application/json'}, body=lambda: b'{"code":"task_dependency_cycle"}')
    deliver(route, response)
    assert calls == [{'status': 409, 'headers': response.headers, 'body': response.body()}]


def test_periodic_refresh_requires_state_eof_then_later_identity_eof():
    base, listeners, events, order = 'https://127.0.0.1:12345', {}, [], []
    page = SimpleNamespace(on=lambda name, callback: listeners.__setitem__(name, callback),
                           remove_listener=lambda name, callback: listeners.pop(name))
    class Request:
        # Playwright requests use object identity, even for the same method/URL.
        def __init__(self, url):
            self.method, self.url = 'GET', url
    def response(path, value, label):
        request = Request(base + path)
        return SimpleNamespace(request=request, url=request.url, status=200,
                               finished=lambda: order.append(label + '-eof'), json=lambda: value)
    preflight = response('/api/me', {'user': {'id': 'member1', 'role': 'member'}}, 'preflight')
    state = response('/api/state', {'tasks': [{'id': 'original-committed-id'}]}, 'state')
    identity = response('/api/me', {'user': {'id': 'member1', 'role': 'member'}}, 'identity')
    events.extend([('request', preflight.request), ('response', preflight),
                   ('request', state.request), ('response', state),
                   ('request', identity.request), ('response', identity)])
    checks = []
    def settle(_page, check, **_kwargs):
        checks.append(len(order))
        # The helper must reject both request-start alone and the earlier /me.
        while not check():
            assert events
            name, value = events.pop(0)
            listeners[name](value)
    snapshot, evidence = completed_periodic_refresh(page, base, settle)
    assert snapshot == {'tasks': [{'id': 'original-committed-id'}]}
    assert order == ['state-eof', 'identity-eof'] and checks == [0, 1]
    assert evidence['stateRequestIndex'] == 1 and evidence['identityRequestIndex'] == 2
    assert evidence['stateStatus'] == evidence['identityStatus'] == 200
    assert evidence['responseBodiesFinished'] and not listeners and not events


def test_add_task_name_accepts_paper_icon_without_matching_other_actions():
    # Exact names observed in the R1 aria snapshot and the plain-text variant.
    assert ADD_TASK_NAME.fullmatch('\U000f0415 添加待办')
    assert ADD_TASK_NAME.fullmatch('添加待办')
    for name in ('批量添加待办', '添加待办事项', '查看 添加待办', '新建记录',
                 '\U000f0415 添加采购', '\U000f0415添加待办'):
        assert ADD_TASK_NAME.fullmatch(name) is None
