"""Focused reads against an isolated real Git repository, plus wire corruption."""
from pathlib import Path
import subprocess

import pytest

from deploy import git_blobs


def git(repo, *args, data=None):
    return subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "user.name=Blob Test",
         "-c", "user.email=blob-test@example.invalid", *args],
        cwd=repo, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True,
    ).stdout


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "isolated repository"
    repo.mkdir()
    git(repo, "init", "--object-format=sha1")
    files = {
        "old.txt": b"first\r\nversion\n",
        "binary.dat": b"\x00\xff\xfe\nheader blob 12\x00no-newline",
        "empty": b"",
        "folder/资料 with spaces.txt": "旅行资料\n".encode(),
        "literal[1].txt": b"literal bracket path",
        "literal1.txt": b"must not match a wildcard",
    }
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "first fixture")
    first = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "old.txt").write_bytes(b"second version")
    git(repo, "add", "old.txt")
    git(repo, "commit", "-m", "second fixture")
    second = git(repo, "rev-parse", "HEAD").decode().strip()
    return repo, first, second, files


def test_real_binary_unicode_spaces_order_and_no_repository_mutation(repository):
    repo, first, _second, files = repository
    guarded = [repo / ".git" / x for x in ("HEAD", "index", "config", "refs/heads/master")]
    guarded = [p for p in guarded if p.exists()]
    before = {p: p.read_bytes() for p in guarded}
    refs_before = git(repo, "show-ref")
    selection = list(reversed(files))
    result = git_blobs.read_git_blobs(repo, first, selection)
    assert list(result) == selection
    assert result == files
    assert all(result[p] == git(repo, "show", first + ":" + p) for p in files)
    assert {p: p.read_bytes() for p in guarded} == before
    assert git(repo, "show-ref") == refs_before
    assert git(repo, "status", "--porcelain") == b""


def test_pinned_old_commit_ignores_new_head_dirty_working_file_and_replace_ref(repository):
    repo, first, second, _files = repository
    (repo / "old.txt").write_bytes(b"uncommitted bytes")
    git(repo, "replace", first, second)
    assert git_blobs.read_git_blobs(repo, first, ["old.txt"]) == {"old.txt": b"first\r\nversion\n"}
    assert git_blobs.read_git_blobs(repo, second, ["old.txt"]) == {"old.txt": b"second version"}
    assert (repo / "old.txt").read_bytes() == b"uncommitted bytes"


def test_one_tree_process_and_one_batch_process(repository, monkeypatch):
    repo, first, _second, files = repository
    actual = git_blobs._git
    calls = []
    def traced(repo, args, data=None):
        calls.append(args[0])
        return actual(repo, args, data)
    monkeypatch.setattr(git_blobs, "_git", traced)
    assert git_blobs.read_git_blobs(repo, first, files) == files
    assert calls == ["ls-tree", "cat-file"]


def test_many_long_paths_use_fixed_argv_and_only_requested_blob_bodies(repository, monkeypatch):
    repo, first, _second, _files = repository
    oid = git(repo, "rev-parse", first + ":old.txt").strip()
    paths = ["wide/" + str(n).zfill(4) + "-" + "资料" * 10 + "x" * 90 + ".txt" for n in range(320)]
    assert len(subprocess.list2cmdline(paths)) > 32767
    # Insert real tree entries without needing Windows long working-tree paths.
    data = b"".join(b"100644 " + oid + b"\t" + p.encode() + b"\0" for p in paths)
    git(repo, "update-index", "-z", "--index-info", data=data)
    git(repo, "commit", "-m", "large path selection")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    actual = git_blobs._git
    calls = []
    def traced(repo, args, data=None):
        calls.append((args, data))
        return actual(repo, args, data)
    monkeypatch.setattr(git_blobs, "_git", traced)
    result = git_blobs.read_git_blobs(repo, commit, paths)
    assert result == {p: b"first\r\nversion\n" for p in paths}
    assert calls[0] == (["ls-tree", "-r", "-z", "--full-tree", commit], None)
    assert calls[1] == (["cat-file", "--batch"], commit.encode() + b"\n" + (oid + b"\n") * len(paths))


@pytest.mark.parametrize("paths", [
    ["../escape"], ["folder/../../escape"], ["/absolute"], ["C:/absolute"],
    ["folder\\file"], ["./old.txt"], ["folder//file"], ["folder/"], [""],
    ["old.txt\nHEAD:old.txt"], ["old.txt\r"], ["old\0.txt"],
    ["old.txt", "old.txt"], [None], "old.txt", ["\ud800"], None, 42,
])
def test_bad_paths_rejected_before_any_git(tmp_path, monkeypatch, paths):
    monkeypatch.setattr(git_blobs, "_git", lambda *_: pytest.fail("Git must not run"))
    with pytest.raises(ValueError):
        git_blobs.read_git_blobs(tmp_path, "a" * 40, paths)


@pytest.mark.parametrize("commit", ["HEAD", "main", "a" * 39, "a" * 41, "z" * 40, None])
def test_floating_or_malformed_commits_rejected(tmp_path, monkeypatch, commit):
    monkeypatch.setattr(git_blobs, "_git", lambda *_: pytest.fail("Git must not run"))
    with pytest.raises(ValueError):
        git_blobs.read_git_blobs(tmp_path, commit, ["old.txt"])


def test_missing_path_directory_nonblob_and_noncommit_rejected(repository):
    repo, first, _second, _files = repository
    for path in ("missing", "folder"):
        with pytest.raises(git_blobs.GitBlobReadError):
            git_blobs.read_git_blobs(repo, first, [path])
    tree = git(repo, "rev-parse", first + "^{tree}").decode().strip()
    blob = git(repo, "rev-parse", first + ":old.txt").decode().strip()
    git(repo, "tag", "-a", "fixture-tag", "-m", "tag", first)
    tag = git(repo, "rev-parse", "fixture-tag").decode().strip()
    for oid in (tree, blob, tag, "0" * 40):
        for paths in ([], ["old.txt"]):
            with pytest.raises(git_blobs.GitBlobReadError):
                git_blobs.read_git_blobs(repo, oid, paths)
    git(repo, "update-index", "--add", "--cacheinfo", "160000," + first + ",submodule")
    git(repo, "commit", "-m", "gitlink fixture")
    with pytest.raises(git_blobs.GitBlobReadError):
        git_blobs.read_git_blobs(repo, git(repo, "rev-parse", "HEAD").decode().strip(), ["submodule"])


def test_empty_selection_still_checks_actual_commit(repository):
    repo, first, _second, _files = repository
    assert git_blobs.read_git_blobs(repo, first.upper(), []) == {}


@pytest.mark.parametrize("damage", [
    "missing", "header", "type", "oid", "size", "body", "truncated", "separator", "extra", "order",
])
def test_corrupt_actual_batch_stream_is_rejected(repository, monkeypatch, damage):
    repo, first, _second, _files = repository
    actual = git_blobs._git
    def corrupted(repo, args, data=None):
        raw = actual(repo, args, data)
        if args[0] != "cat-file":
            return raw
        # Leave the real commit record intact; corrupt the real blob responses.
        header_end = raw.index(b"\n")
        boundary = header_end + 1 + int(raw[:header_end].split()[2]) + 1
        head = raw[:boundary]
        blobs = raw[boundary:]
        end = blobs.index(b"\n")
        fields = blobs[:end].split()
        if damage == "missing": return head + fields[0] + b" missing\n"
        if damage == "header": return head + b"bad header\n" + blobs[end + 1:]
        if damage == "type": return head + blobs.replace(b" blob ", b" tree ", 1)
        if damage == "oid": return head + b"0" * 40 + blobs[40:]
        if damage == "size": return head + fields[0] + b" blob -1\n" + blobs[end + 1:]
        if damage == "body": return head + blobs[:end + 1] + b"X" + blobs[end + 2:]
        if damage == "truncated": return raw[:-2]
        if damage == "separator": return raw[:-1] + b"X"
        if damage == "extra": return raw + b"\n"
        split = end + 1 + int(fields[2]) + 1
        return head + blobs[split:] + blobs[:split]
    monkeypatch.setattr(git_blobs, "_git", corrupted)
    with pytest.raises(git_blobs.GitBlobReadError):
        git_blobs.read_git_blobs(repo, first, ["old.txt", "binary.dat"])


def test_git_failure_is_not_a_partial_result(tmp_path):
    with pytest.raises(git_blobs.GitBlobReadError):
        git_blobs.read_git_blobs(tmp_path, "a" * 40, ["old.txt"])
