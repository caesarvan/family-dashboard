"""New selection/output/build reuse guards only; no product/browser acceptance."""
from datetime import datetime, timezone
import subprocess
from unittest.mock import patch

import pytest

from scripts import check_expo_calendar_conflicts_browser as harness


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Synthetic Harness Test',
            '-c', 'user.email=synthetic@example.invalid', *args], cwd=tmp_path).decode().strip()
    git('init', '--quiet')
    path = tmp_path / 'frontend' / 'app.tsx'; path.parent.mkdir(); path.write_text('synthetic input\n')
    git('add', '--', 'frontend/app.tsx'); git('commit', '--quiet', '-m', 'Synthetic source')
    head = git('rev-parse', 'HEAD')
    evidence = {'sourceHead': head, 'sourceTree': git('rev-parse', head + '^{tree}')}
    def change(name):
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('synthetic changed input\n')
        git('add', '--', name); git('commit', '--quiet', '-m', 'Synthetic delta')
        return git('rev-parse', 'HEAD')
    return git, head, evidence, change


def test_exact_cases_and_artifact_counts():
    assert harness.selected_cases(None) == harness.CASES
    assert len(harness.CASES) == 3 and sum(harness.CASE_SCREENSHOTS.values()) == 8
    assert harness.selected_cases([harness.CASES[2], harness.CASES[0], harness.CASES[2]]) == (harness.CASES[2], harness.CASES[0])
    assert harness.CASE_SCREENSHOTS[harness.selected_cases([harness.CASES[2]])[0]] == 3
    for value in ([], ['unknown'], [harness.CASES[0], 'unknown']):
        with pytest.raises(ValueError):
            harness.selected_cases(value)


def test_output_is_exclusive_and_old_failure_cannot_be_overwritten(tmp_path):
    fixed = datetime(2027, 10, 13, tzinfo=timezone.utc)
    with patch.object(harness, 'datetime') as clock:
        clock.now.return_value = fixed
        output = harness.exclusive_output(tmp_path)
        assert output.parent == tmp_path / 'test-results'
        original = output / 'failure.txt'; original.write_text('prior failure evidence')
        with pytest.raises(FileExistsError):
            harness.exclusive_output(tmp_path)
        assert original.read_text() == 'prior failure evidence'


def test_reuse_only_allows_own_three_reviewed_paths(repo):
    git, head, evidence, change = repo
    assert harness.build_source_delta(git, head, evidence, head) == []
    for path in sorted(harness.BUILD_REUSE_PATHS):
        current = change(path)
        assert path in harness.build_source_delta(git, current, evidence, head)


@pytest.mark.parametrize('path', ['frontend/app.tsx', 'frontend/new.tsx', 'app.py', 'docs/OTHER.md'])
def test_reuse_rejects_product_or_unrelated_changes(repo, path):
    git, head, evidence, change = repo
    with pytest.raises(AssertionError):
        harness.build_source_delta(git, change(path), evidence, head)


def test_reuse_requires_exact_build_identity_and_ancestry(repo):
    git, head, evidence, change = repo
    with pytest.raises(AssertionError):
        harness.build_source_delta(git, head, {**evidence, 'sourceTree': '0' * 40}, head)
    with pytest.raises(AssertionError):
        harness.build_source_delta(git, head, evidence, '0' * 40)
    later = change(harness.HARNESS)
    later_evidence = {'sourceHead': later, 'sourceTree': git('rev-parse', later + '^{tree}')}
    with pytest.raises(AssertionError, match='ancestor'):
        harness.build_source_delta(git, head, later_evidence, later)


@pytest.fixture
def static_page():
    # Actual DOM geometry only: no Flask, product bundle, model or cloud.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        requests = []
        def deny(route):
            requests.append(route.request.url)
            route.abort()
        context.route('**/*', deny)
        page = context.new_page()
        try:
            yield page
            assert not requests
        finally:
            context.close(); browser.close()


def test_horizontal_scroll_items_are_reachable_not_page_clipping(static_page):
    page = static_page
    page.set_content('''<style>body{margin:0}#strip{margin:16px;width:358px;overflow-x:auto}
      #strip>div{display:flex;gap:8px;width:max-content}button{flex:none;width:84px;height:44px}</style>
      <div id="strip"><div>''' + ''.join(f'<button>day{i}</button>' for i in range(7)) + '</div></div>')
    before = harness.layout_metrics(page)
    assert before['bodyScroll'] == before['rootScroll'] == before['viewport'] == 390
    assert not before['clipped'] and before['scrollableClipped']
    assert any(item['label'] == 'day6' for item in before['scrollableClipped'])
    page.locator('#strip').evaluate('node => node.scrollLeft=node.scrollWidth-node.clientWidth')
    box = page.get_by_role('button', name='day6', exact=True).bounding_box()
    assert box['x'] >= 16 and box['x'] + box['width'] <= 374
    after = harness.layout_metrics(page)
    assert not after['clipped'] and after['bodyScroll'] == after['rootScroll'] == 390


@pytest.mark.parametrize('body', [
    '<button style="position:absolute;left:380px;width:90px">bad</button>',
    '<div style="width:358px;overflow-x:auto"><div style="width:700px"><button style="position:fixed;left:380px;width:90px">bad</button></div></div>',
    '<div style="width:358px;overflow-x:auto"><div style="width:700px"><div style="width:100px;overflow-x:hidden"><button style="position:relative;left:380px;width:90px">bad</button></div></div></div>',
])
def test_real_clipping_is_not_exempted_by_missing_fixed_or_hidden_scroll(static_page, body):
    static_page.set_content('<style>body{margin:0}button{height:44px}</style>' + body)
    result = harness.layout_metrics(static_page)
    assert any(item['label'] == 'bad' for item in result['clipped'])
    assert not result['scrollableClipped']


@pytest.mark.parametrize('outer_style', ['width:100px;overflow-x:hidden', 'position:fixed;width:358px'])
def test_outer_ancestor_clipping_or_fixed_position_cannot_be_exempted(static_page, outer_style):
    static_page.set_content('<style>body{margin:0}button{height:44px}</style>'
        + '<div style="' + outer_style + '"><div id="strip" style="width:358px;overflow-x:auto">'
        + '<div style="width:700px"><button style="position:relative;left:380px;width:90px">bad</button></div></div></div>')
    result = harness.layout_metrics(static_page)
    assert any(item['label'] == 'bad' for item in result['clipped'])
    assert not result['scrollableClipped']
