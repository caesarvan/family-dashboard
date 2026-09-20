"""Offline tool guards only; these tests do not prove video or browser success."""
from datetime import datetime, timezone
import subprocess
from unittest.mock import patch

import pytest
from scripts import check_expo_media_video_browser as harness
from browser_expo_media_video_check import fixture_command


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


def test_case_selection_counts_are_exact():
    assert harness.selected_cases(None) == harness.CASES
    assert len(harness.CASES) == 3 and sum(harness.CASE_SCREENSHOTS.values()) == 6
    assert harness.selected_cases([harness.CASES[2], harness.CASES[0], harness.CASES[2]]) == (harness.CASES[2], harness.CASES[0])
    assert harness.CASE_SCREENSHOTS[harness.selected_cases([harness.CASES[2]])[0]] == 2
    for value in ([], ['unknown'], [harness.CASES[0], 'unknown']):
        with pytest.raises(ValueError): harness.selected_cases(value)


def test_output_cannot_overwrite_old_failure(tmp_path):
    fixed = datetime(2027, 10, 13, tzinfo=timezone.utc)
    with patch.object(harness, 'datetime') as clock:
        clock.now.return_value = fixed
        output = harness.exclusive_output(tmp_path)
        assert output.parent == tmp_path / 'test-results'
        original = output / 'failure.txt'; original.write_text('prior failure evidence')
        with pytest.raises(FileExistsError): harness.exclusive_output(tmp_path)
        assert original.read_text() == 'prior failure evidence'


def test_reuse_only_allows_own_four_reviewed_paths(repo):
    git, head, evidence, change = repo
    assert harness.build_source_delta(git, head, evidence, head) == []
    for path in sorted(harness.BUILD_REUSE_PATHS):
        assert path in harness.build_source_delta(git, change(path), evidence, head)


@pytest.mark.parametrize('path', ['frontend/app.tsx', 'frontend/new.tsx', 'app.py', 'media_playback.py', 'docs/OTHER.md'])
def test_reuse_rejects_business_or_unrelated_changes(repo, path):
    git, head, evidence, change = repo
    with pytest.raises(AssertionError): harness.build_source_delta(git, change(path), evidence, head)


def test_reuse_requires_exact_tree_head_and_ancestor(repo):
    git, head, evidence, change = repo
    with pytest.raises(AssertionError): harness.build_source_delta(git, head, {**evidence, 'sourceTree': '0' * 40}, head)
    with pytest.raises(AssertionError): harness.build_source_delta(git, head, evidence, '0' * 40)
    later = change(harness.HARNESS)
    later_evidence = {'sourceHead': later, 'sourceTree': git('rev-parse', later + '^{tree}')}
    with pytest.raises(AssertionError, match='ancestor'): harness.build_source_delta(git, head, later_evidence, later)


def test_fixture_argv_only_generates_local_lavfi_media(tmp_path):
    path = tmp_path / 'synthetic.mp4'
    args = fixture_command(tmp_path / 'trusted ffmpeg.exe', path)
    assert args[0] == str(tmp_path / 'trusted ffmpeg.exe') and args[-1] == str(path)
    assert [args[i+1] for i, value in enumerate(args) if value == '-i'] == [
        'testsrc2=size=320x180:rate=24:duration=8', 'sine=frequency=440:sample_rate=48000:duration=8']
    assert '-nostdin' in args and args[args.index('-threads:v') + 1] == '2'
    assert not any('://' in value for value in args)


def test_tool_hash_mismatch_cannot_execute_subprocess(tmp_path):
    path = tmp_path / 'unreviewed-tool'; path.write_bytes(b'synthetic untrusted binary')
    with patch.object(harness.subprocess, 'run', side_effect=AssertionError('must not execute')) as run:
        with pytest.raises(AssertionError): harness.tool_identity(path, '0' * 64)
        run.assert_not_called()
