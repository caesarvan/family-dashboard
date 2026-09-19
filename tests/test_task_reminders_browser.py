"""Harness guards and static Edge locators; not reminder product acceptance."""
import html
import json
import subprocess
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts.check_expo_task_reminders_browser import (
    CASES, CASE_SCREENSHOTS, STORAGE_KEY, build_source_delta, identity_fault,
    labelled_button, reminder_card, selected_cases, stored_recovery,
)


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
    def change(name, remove=False):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True)
        if remove:
            path.unlink()
        else:
            path.write_text('synthetic changed source\n', encoding='utf-8')
        git('add', '--', name); git('commit', '--quiet', '-m', 'Synthetic change')
        return git('rev-parse', 'HEAD')
    return git, head, evidence, change


def test_frontend_identical_export_reuse_records_current_runtime_delta(source_repo):
    git, head, evidence, change = source_repo
    assert build_source_delta(git, head, evidence, head) == []
    for name in ('scripts/check_expo_task_reminders_browser.py', 'task_reminders.py', 'docs/example.md'):
        current = change(name)
        assert name in build_source_delta(git, current, evidence, head)
        with pytest.raises(AssertionError):
            build_source_delta(git, current, evidence, current)


@pytest.mark.parametrize('name,remove', [('frontend/app.tsx', False), ('frontend/extra.tsx', False), ('frontend/app.tsx', True)])
def test_reuse_rejects_modified_added_or_removed_frontend(source_repo, name, remove):
    git, head, evidence, change = source_repo
    # Keep the frontend tree present when its original leaf is removed.
    if remove:
        current = change('frontend/retained.tsx')
        head, evidence = current, {'sourceHead': current, 'sourceTree': git('rev-parse', 'HEAD^{tree}')}
    with pytest.raises(AssertionError, match='Complete frontend'):
        build_source_delta(git, change(name, remove), evidence, head)


def test_reuse_verifies_original_tree_and_ancestry(source_repo):
    git, head, evidence, change = source_repo
    with pytest.raises(AssertionError):
        build_source_delta(git, head, {**evidence, 'sourceTree': '0' * 40}, head)
    later = change('docs/example.md')
    later_evidence = {'sourceHead': later, 'sourceTree': git('rev-parse', 'HEAD^{tree}')}
    with pytest.raises(AssertionError, match='ancestor'):
        build_source_delta(git, head, later_evidence, later)


@pytest.mark.parametrize('status', [404, 429])
def test_identity_fault_requires_commit_and_real_identity_and_redacts_secrets(status):
    calls = []
    route = SimpleNamespace(fulfill=lambda **kwargs: calls.append(kwargs))
    value = {'user': {'id': 'member1', 'role': 'member', 'householdId': 'synthetic'},
             'csrf': 'synthetic-do-not-record', 'sessionIdentity': 'synthetic-session-private'}
    response = SimpleNamespace(status=200, json=lambda: value, body=lambda: json.dumps(value).encode())
    with pytest.raises(AssertionError, match='committed action'):
        identity_fault(route, response, status, None)
    response.status = 401
    with pytest.raises(AssertionError, match='real successful identity'):
        identity_fault(route, response, status, {'operation': 'synthetic'})
    assert not calls
    response.status = 200
    result = identity_fault(route, response, status, {'operation': 'synthetic'})
    assert result['backendStatus'] == 200 and result['deliveredStatus'] == status
    assert set(result) == {'backendStatus', 'deliveredStatus', 'memberId', 'householdId', 'backendResponseSha256'}
    assert calls[0]['status'] == status and set(json.loads(calls[0]['body'])) == {'error'}
    assert 'synthetic-do-not-record' not in json.dumps([result, calls])
    assert 'synthetic-session-private' not in json.dumps([result, calls])


def test_identity_fault_rejects_other_failure_and_nonmember():
    route = SimpleNamespace(fulfill=lambda **_kwargs: pytest.fail('must not fulfill'))
    response = SimpleNamespace(status=200, json=lambda: {'user': {'id': 'tv', 'role': 'tv'}})
    with pytest.raises(AssertionError):
        identity_fault(route, response, 503, True)
    with pytest.raises(AssertionError):
        identity_fault(route, response, 429, True)


def test_recovery_evidence_rejects_nonminimal_or_wrong_scope_payload():
    intent = dict(taskId='synthetic-original', requestId='a' * 32, occurrence='b' * 64, revision=0, action='read')
    value = dict(version=1, scope='c' * 64, recovery=dict(intent=intent, filter='all', page=1))
    page = SimpleNamespace(evaluate=lambda _fn, key: json.dumps(value) if key == STORAGE_KEY else None)
    assert stored_recovery(page) == value
    value['recovery']['intent']['title'] = 'must not persist task content'
    with pytest.raises(AssertionError):
        stored_recovery(page)
    del value['recovery']['intent']['title']; value['scope'] = 'raw-session-identity'
    with pytest.raises(AssertionError):
        stored_recovery(page)


def test_cases_are_independent_repeatable_and_have_exact_artifact_counts():
    assert selected_cases(None) == CASES
    assert sum(CASE_SCREENSHOTS.values()) == 10
    assert selected_cases([CASES[2], CASES[0], CASES[2]]) == (CASES[2], CASES[0])
    assert sum(CASE_SCREENSHOTS[name] for name in selected_cases([CASES[1]])) == 4
    for value in ([], ['unknown'], [CASES[0], 'unknown']):
        with pytest.raises(ValueError):
            selected_cases(value)


def test_actual_edge_static_unicode_and_scoped_reminder_locators():
    # Actual Python-to-JS regex/role serialization, with no product, HTTP or DB.
    title = '合成共享云任务长标题：' + '行程资料🧭与出发准备，' * 18
    actions = ('打开待办', '标为已读', '1 小时后提醒', '明天 09:00 提醒')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        try:
            context = browser.new_context(); requests = []
            context.on('request', lambda request: requests.append(request.url))
            context.route('**/*', lambda route: route.abort())
            page = context.new_page()
            for prefix in ('', '\U000f0415 '):
                page.set_content('<span>我的提醒</span><button id="open">' + prefix + '我的提醒</button>'
                                 '<button>我的提醒设置</button>')
                control = labelled_button(page, '我的提醒')
                assert control.get_attribute('id') == 'open'
                control.evaluate("node => node.onclick = () => node.dataset.clicked = 'yes'")
                control.click(); assert control.get_attribute('data-clicked') == 'yes'
            page.set_content('<button>我的提醒</button><button>查看我的提醒</button>')
            with pytest.raises(AssertionError, match='expected to have count'):
                labelled_button(page, '我的提醒')
            markup = ''.join('<div data-testid="section-card-content"><h2>' + html.escape(name) + '</h2>'
                             + ''.join('<button>' + html.escape(label) + '</button>' for label in actions) + '</div>'
                             for name in (title, '另一项提醒'))
            page.set_content(markup)
            card = reminder_card(page, title)
            for label in actions:
                expect(labelled_button(card, label)).to_be_enabled()
            expect(card.get_by_role('heading', name=title, exact=True)).to_have_text(title)
            assert not requests
        finally:
            browser.close()
