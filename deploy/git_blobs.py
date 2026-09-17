"""Read raw blobs from one immutable SHA-1 commit; never inspect working files."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
from collections.abc import Iterable


class GitBlobReadError(RuntimeError):
    """Git failed or returned missing, mismatched or malformed objects."""


_OID = re.compile(rb"[0-9a-f]{40}")


def _git(repo: Path, args: list[str], data: bytes | None = None) -> bytes:
    # Do not follow replacement refs or lazily fetch missing promisor objects.
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "--no-optional-locks", *args],
            cwd=repo, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, check=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitBlobReadError("Git object read failed") from exc
    return result.stdout


def _batch_objects(raw: bytes, expected: list[tuple[bytes, bytes]]) -> list[bytes]:
    result: list[bytes] = []
    position = 0
    for oid, kind in expected:
        end = raw.find(b"\n", position)
        if end < 0:
            raise GitBlobReadError("Truncated batch header")
        header = raw[position:end].split(b" ")
        if (len(header) != 3 or header[:2] != [oid, kind]
                or not re.fullmatch(rb"0|[1-9][0-9]*", header[2])):
            raise GitBlobReadError("Missing or mismatched batch object/type/order")
        size = int(header[2])
        start = end + 1
        finish = start + size
        if finish >= len(raw) or raw[finish:finish + 1] != b"\n":
            raise GitBlobReadError("Truncated batch body or invalid separator")
        body = raw[start:finish]
        actual = hashlib.sha1(kind + b" " + header[2] + b"\0" + body).hexdigest()
        if actual.encode("ascii") != oid:
            raise GitBlobReadError("Batch object content hash mismatch")
        result.append(body)
        position = finish + 1
    if position != len(raw):
        raise GitBlobReadError("Unexpected trailing batch data")
    return result


def read_git_blobs(
    repo: str | os.PathLike[str], full40hexcommit: str, paths: Iterable[str],
) -> dict[str, bytes]:
    """Return exact raw Git bytes, preserving input path order.

    Nonempty reads use one NUL-delimited full-tree listing and one cat-file
    --batch process. Only requested blobs are read; argv length is constant.
    Invalid arguments raise ValueError; object/Git failures
    raise GitBlobReadError. An empty selection still verifies the commit.

    This does NOT assert HEAD, clean working files, branch identity, approved
    hashes, repository trust or source path/symlink policy. Callers retain
    those guards before and after reading. No checkout, config write or fetch.
    """
    if not isinstance(full40hexcommit, str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}", full40hexcommit,
    ):
        raise ValueError("Expected a full 40-hex commit, not a floating ref")
    commit = full40hexcommit.lower()
    if isinstance(paths, (str, bytes)):
        raise ValueError("Expected an iterable of paths, not one string")
    try:
        selected = list(paths)
    except TypeError as exc:
        raise ValueError("Expected an iterable of paths") from exc
    for path in selected:
        if (not isinstance(path, str) or not path
                or any(c in path for c in ("\0", "\r", "\n", "\\", ":"))
                or any(part in ("", ".", "..") for part in path.split("/"))):
            raise ValueError("Expected a relative, canonical POSIX Git path")
        try:
            path.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Git paths must be valid UTF-8") from exc
    if len(selected) != len(set(selected)):
        raise ValueError("Duplicate Git path")

    objects: dict[str, bytes] = {}
    if selected:
        requested = {p.encode("utf-8"): p for p in selected}
        raw = _git(Path(repo), ["ls-tree", "-r", "-z", "--full-tree", commit])
        if raw and not raw.endswith(b"\0"):
            raise GitBlobReadError("Truncated ls-tree output")
        for record in raw.split(b"\0")[:-1]:
            metadata, separator, name = record.partition(b"\t")
            if not separator:
                raise GitBlobReadError("Malformed ls-tree record")
            if name not in requested:
                continue
            fields = metadata.split(b" ")
            path = requested[name]
            if (len(fields) != 3 or fields[1] != b"blob"
                    or fields[0] not in (b"100644", b"100755", b"120000")
                    or not _OID.fullmatch(fields[2])
                    or path in objects):
                raise GitBlobReadError("Unexpected ls-tree path/type/object")
            objects[path] = fields[2]
        if set(objects) != set(selected):
            raise GitBlobReadError("Missing Git blob path")

    expected = [(commit.encode("ascii"), b"commit")]
    expected.extend((objects[path], b"blob") for path in selected)
    data = b"".join(oid + b"\n" for oid, _kind in expected)
    bodies = _batch_objects(_git(Path(repo), ["cat-file", "--batch"], data), expected)
    return dict(zip(selected, bodies[1:], strict=True))
