#!/usr/bin/env python3
"""Update three NVIDIA settings in an existing .env; never activate services."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import getpass
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata
import uuid
import warnings


KEYS = ("ASSISTANT_PROVIDER", "NVIDIA_MODEL", "NVIDIA_API_KEY")
ENV_LIMIT = 1024 * 1024
KEY_LIMIT = 4096
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z", re.ASCII)
ASSIGNMENT = re.compile(r"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:=|:)[ \t]*")
ERRORS = {
    "arguments": "Invalid configuration arguments.",
    "values": "Invalid assistant configuration values.",
    "format": "The existing configuration format is unsupported or ambiguous.",
    "file": "An existing regular UTF-8 configuration file is required.",
    "busy": "Another assistant configuration update is in progress.",
    "changed": "The configuration changed; no replacement was made.",
    "input": "A single nonempty hidden credential input is required.",
    "platform": "Configuration updates require POSIX file permissions.",
    "io": "Configuration could not be completed; inspect files privately before retrying.",
    "cancelled": "Configuration was cancelled.",
}


class ConfigurationError(ValueError):
    """Only fixed public error text, never values or original exceptions."""

    def __init__(self, code="io"):
        self.code = code if code in ERRORS else "io"
        super().__init__(ERRORS[self.code])


def _sanitized(default):
    """Raise outside the handler, discarding sensitive exception context too."""
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Exception as error:
                code = error.code if isinstance(error, ConfigurationError) else default
            raise ConfigurationError(code)
        return call
    return decorate


def _controls(value, *, multiline=False):
    allowed = "\n\r\t" if multiline else ""
    return any(unicodedata.category(char).startswith("C") and char not in allowed
               or char in "\u2028\u2029" for char in value)


@_sanitized("values")
def validate_value(key, value):
    if key not in KEYS or not isinstance(value, str) or not value or _controls(value):
        raise ConfigurationError("values")
    if key == "ASSISTANT_PROVIDER" and value != "nvidia":
        raise ConfigurationError("values")
    if key == "NVIDIA_MODEL" and not MODEL_PATTERN.fullmatch(value):
        raise ConfigurationError("values")
    if key == "NVIDIA_API_KEY" and (not value.strip() or len(value.encode("utf-8")) > KEY_LIMIT):
        raise ConfigurationError("values")
    return value


def quote_value(value):
    # Same literal Compose dotenv quoting as configure-oauth.py; no expansion.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


@_sanitized("format")
def env_records(text):
    """Strict records: (key, exact original block, literal unexpanded value).

    Unrelated quoted multiline records are kept intact. Bare keys, duplicate
    keys and text after a closing quote are rejected, not guessed or repaired.
    """
    if _controls(text, multiline=True) or re.search(r"\r(?!\n)", text):
        raise ConfigurationError("format")
    lines = text.splitlines(keepends=True)
    records, seen, offset = [], set(), 0
    while offset < len(lines):
        block = lines[offset]
        offset += 1
        if not block.strip() or block.lstrip(" \t").startswith("#"):
            records.append((None, block, ""))
            continue
        match = ASSIGNMENT.match(block)
        if not match or match.group(1) in seen:
            raise ConfigurationError("format")
        key = match.group(1)
        seen.add(key)
        raw = block[match.end():]
        if raw.startswith(("'", '"')):
            quote, index, closed = raw[0], 1, False
            value = []
            while not closed:
                while index < len(raw):
                    char = raw[index]
                    index += 1
                    if char == quote:
                        closed = True
                        break
                    if char == "\\" and index < len(raw):
                        following = raw[index]
                        if following == "\\" and quote == "'":
                            value.append("\\\\")
                            index += 1
                            continue
                        # Decode only escapes needed for safe literal inspection.
                        if following == quote or quote == '"' and following in '\\$':
                            value.append(following)
                            index += 1
                            continue
                        if quote == '"' and following in "nrt":
                            value.append({"n": "\n", "r": "\r", "t": "\t"}[following])
                            index += 1
                            continue
                    value.append(char)
                if closed:
                    break
                if offset >= len(lines):
                    raise ConfigurationError("format")
                block += lines[offset]
                raw += lines[offset]
                offset += 1
            if not re.fullmatch(r"[ \t]*(?:#[^\r\n]*)?(?:\r?\n)?", raw[index:]):
                raise ConfigurationError("format")
            value = "".join(value)
        else:
            value = raw.rstrip("\r\n").strip(" \t")
            value = "" if value.startswith("#") else re.split(r"[ \t]+#", value, maxsplit=1)[0]
            # Reject apparent quote syntax in an unquoted record instead of
            # deciding whether a later line is part of its value.
            if any(char in value for char in "\"'") or value.endswith("\\"):
                raise ConfigurationError("format")
        records.append((key, block, value))
    return records


@_sanitized("values")
def render_env(original, updates):
    if not isinstance(original, str) or len(original.encode("utf-8")) > ENV_LIMIT:
        raise ConfigurationError("format")
    if not isinstance(updates, dict) or set(updates) != set(KEYS):
        raise ConfigurationError("values")
    for key in KEYS:
        validate_value(key, updates[key])
    records = env_records(original)
    newline = "\r\n" if "\r\n" in original else "\n"
    result, replaced = [], set()
    for key, block, _ in records:
        if key in updates:
            result.append(f"{key}={quote_value(updates[key])}{newline}")
            replaced.add(key)
        else:
            result.append(block)
    missing = [key for key in KEYS if key not in replaced]
    if missing and result and not result[-1].endswith("\n"):
        result.append(newline)
    result.extend(f"{key}={quote_value(updates[key])}{newline}" for key in missing)
    return "".join(result)


def _safe_path(path):
    path = Path(path).absolute()
    # Do not traverse symlinked directories or Windows reparse points either.
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ConfigurationError("file")
    return path


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _snapshot(path):
    path = _safe_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > ENV_LIMIT:
        raise ConfigurationError("file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        # Windows path-stat and fd-stat expose different ctime semantics on
        # some Python versions. Compare those APIs by identity/size/mtime;
        # retain ctime when comparing the same API before and after a read.
        if _identity(opened)[:-1] != _identity(before)[:-1]:
            raise ConfigurationError("changed")
        original = stream.read(ENV_LIMIT + 1)
        if _identity(os.fstat(stream.fileno())) != _identity(opened):
            raise ConfigurationError("changed")
    if _identity(path.lstat()) != _identity(before):
        raise ConfigurationError("changed")
    if len(original) > ENV_LIMIT or b"\0" in original:
        raise ConfigurationError("file")
    try:
        original.decode("utf-8-sig")
    except UnicodeError:
        raise ConfigurationError("file") from None
    return original, _identity(before)


@_sanitized("file")
def read_existing(path):
    try:
        return _snapshot(path)[0]
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("file") from None


@_sanitized("io")
def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            if os.name == "posix":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise ConfigurationError("io") from None


@contextmanager
def _update_lock(path):
    lock = path.with_name(path.name + ".assistant-lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ConfigurationError("busy") from None
    info = os.fstat(fd)
    os.close(fd)
    try:
        yield
    finally:
        # Never remove an unrelated lock that replaced ours.
        try:
            current = lock.lstat()
            if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino):
                lock.unlink()
        except FileNotFoundError:
            pass


def _sync_directory(path):
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@_sanitized("io")
def update_env(path, updates):
    """Private exact backup + atomic replacement; pure local file operation.

    Public CLI requires POSIX. Direct Windows calls are for synthetic tests;
    Windows chmod is not a private ACL guarantee.
    """
    temporary = None
    try:
        path = _safe_path(path)
        with _update_lock(path):
            original, identity = _snapshot(path)
            bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
            candidate = bom + render_env(original[len(bom):].decode("utf-8"), updates).encode("utf-8")
            if len(candidate) > ENV_LIMIT:
                raise ConfigurationError("values")
            original_hash = hashlib.sha256(original).digest()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(f"{path.name}.assistant-backup-{stamp}-{uuid.uuid4().hex}")
            write_private(backup, original)
            pending = path.with_name(f".assistant-config-{uuid.uuid4().hex}")
            write_private(pending, candidate)
            temporary = pending
            _sync_directory(path.parent)
            current, current_identity = _snapshot(path)
            if current_identity != identity or hashlib.sha256(current).digest() != original_hash:
                raise ConfigurationError("changed")
            os.replace(temporary, path)
            temporary = None
            _sync_directory(path.parent)
            return backup
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("io") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


@_sanitized("file")
def configured_status(path):
    records = env_records(read_existing(path).decode("utf-8-sig"))
    values = {key: value for key, _, value in records if key in KEYS}
    return {**{key: bool(values.get(key)) for key in KEYS},
            "isNvidia": values.get("ASSISTANT_PROVIDER") == "nvidia"}


@_sanitized("input")
def read_key_stdin(stream):
    try:
        raw = stream.read(KEY_LIMIT + 3)
        if not isinstance(raw, bytes):
            raise ConfigurationError("input")
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        return validate_value("NVIDIA_API_KEY", raw.decode("utf-8"))
    except Exception:
        raise ConfigurationError("input") from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal diagnostic can print unknown secret arguments.
        raise ConfigurationError("arguments")


def main(argv=None):
    parser = _Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--key-stdin", action="store_true")
    parser.add_argument("--check", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.check:
            if args.model is not None or args.key_stdin:
                raise ConfigurationError("arguments")
            print(json.dumps(configured_status(args.env_file), sort_keys=True))
            return 0
        validate_value("NVIDIA_MODEL", args.model)
        if os.name != "posix":
            raise ConfigurationError("platform")
        # Reject malformed input files before asking for credentials.
        configured_status(args.env_file)
        if args.key_stdin:
            key = read_key_stdin(sys.stdin.buffer)
        else:
            if not sys.stdin.isatty():
                raise ConfigurationError("input")
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                key = validate_value("NVIDIA_API_KEY", getpass.getpass("NVIDIA API key (hidden): "))
        update_env(args.env_file, {"ASSISTANT_PROVIDER": "nvidia", "NVIDIA_MODEL": args.model, "NVIDIA_API_KEY": key})
        print("Configuration saved with a private exact backup. Services were not restarted.")
        return 0
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(ERRORS["cancelled"], file=sys.stderr)
        return 130
    except Exception:
        print(ERRORS["io"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
