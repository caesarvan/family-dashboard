"""Harness-only frozen-source guard checks; not product/browser acceptance."""
import subprocess

import pytest

from browser_expo_assistant_document_search_check import BUILD_REUSE_PATHS, build_source_delta


@pytest.fixture
def source_repo(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Synthetic Harness Test',
            '-c', 'user.email=synthetic@example.invalid', *args], cwd=tmp_path).decode().strip()
    git('init', '--quiet')
    path = tmp_path / 'frontend' / 'App.tsx'
    path.parent.mkdir()
    path.write_text('synthetic input\n', encoding='utf-8')
    git('add', '--', 'frontend/App.tsx')
    git('commit', '--quiet', '-m', 'Synthetic base')
    head = git('rev-parse', 'HEAD')
    evidence = {'sourceHead': head, 'sourceTree': git('rev-parse', 'HEAD^{tree}')}

    def change(name):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('synthetic delta\n', encoding='utf-8')
        git('add', '--', name)
        git('commit', '--quiet', '-m', 'Synthetic delta')
        return git('rev-parse', 'HEAD')
    return git, head, evidence, change


@pytest.mark.parametrize('name', sorted(BUILD_REUSE_PATHS))
def test_reuse_requires_exact_build_or_explicit_harness_only_descendant(source_repo, name):
    git, head, evidence, change = source_repo
    assert build_source_delta(git, head, evidence, head) == []
    descendant = change(name)
    assert build_source_delta(git, descendant, evidence, head) == [name]
    with pytest.raises(AssertionError):
        build_source_delta(git, descendant, evidence, descendant)


@pytest.mark.parametrize('name', ['frontend/App.tsx', 'home_assistant.py', 'journey_documents.py', 'tests/browser_expo_trip_recap_check.py'])
def test_reuse_rejects_changed_product_and_fixture_dependencies(source_repo, name):
    git, head, evidence, change = source_repo
    with pytest.raises(AssertionError, match='only the reviewed harness'):
        build_source_delta(git, change(name), evidence, head)


def test_reuse_rejects_wrong_tree_and_non_ancestor(source_repo):
    git, head, evidence, change = source_repo
    with pytest.raises(AssertionError):
        build_source_delta(git, head, {**evidence, 'sourceTree': '0' * 40}, head)
    later = change('docs/EXPO-ASSISTANT-DOCUMENT-SEARCH-BROWSER.md')
    later_evidence = {'sourceHead': later, 'sourceTree': git('rev-parse', 'HEAD^{tree}')}
    with pytest.raises(AssertionError, match='ancestor'):
        build_source_delta(git, head, later_evidence, later)
