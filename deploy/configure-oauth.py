#!/usr/bin/env python3
"""Interactively update only OAuth credentials in an existing Compose .env file.

Run on the server in a real terminal. Credentials are never command arguments,
printed, or sent over the network by this helper. Containers are not restarted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid
import warnings


PUBLIC_ORIGIN = "https://home.caesarcharles.world"
PROVIDERS = {"microsoft": "MICROSOFT", "google": "GOOGLE"}
ALLOWED_KEYS = {"PUBLIC_ORIGIN"} | {
    f"{prefix}_{suffix}" for prefix in PROVIDERS.values()
    for suffix in ("CLIENT_ID", "CLIENT_SECRET")
}
ASSIGNMENT = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:=|:)[ \t]*")


class ConfigurationError(ValueError):
    """Safe to display: messages never contain configuration values."""


def validate_value(key: str, value: str) -> str:
    if key not in ALLOWED_KEYS:
        raise ConfigurationError("Only the documented OAuth settings may be changed.")
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ConfigurationError("A configuration value is empty or too long.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ConfigurationError("Configuration values cannot contain control characters or newlines.")
    if key == "PUBLIC_ORIGIN" and value != PUBLIC_ORIGIN:
        raise ConfigurationError("The public origin must match the documented HTTPS domain.")
    if key == "MICROSOFT_CLIENT_ID":
        try:
            parsed = uuid.UUID(value)
        except (ValueError, AttributeError):
            raise ConfigurationError("Microsoft Application (client) ID must be a UUID.") from None
        if str(parsed) != value.lower():
            raise ConfigurationError("Microsoft Application (client) ID must use the standard UUID format.")
    if key == "GOOGLE_CLIENT_ID" and not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", value):
        raise ConfigurationError("Google client ID must end in .apps.googleusercontent.com.")
    return value


def quote_value(value: str) -> str:
    """Compose dotenv double quotes: escape dollars as well as quotes/slashes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def env_records(text: str):
    """Yield complete original records, preserving unrelated multiline values."""
    lines = text.splitlines(keepends=True)
    offset = 0
    while offset < len(lines):
        first = lines[offset]
        match = ASSIGNMENT.match(first)
        block = first
        offset += 1
        if not match:
            yield None, block, ""
            continue
        raw = first[match.end():]
        if raw.startswith(("'", '"')):
            quote = raw[0]
            index = 1
            escaped = False
            closed = False
            while not closed:
                while index < len(raw):
                    char = raw[index]
                    index += 1
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        closed = True
                        break
                if closed:
                    break
                if offset >= len(lines):
                    raise ConfigurationError("The existing .env has an unterminated quoted value; no changes made.")
                block += lines[offset]
                raw += lines[offset]
                offset += 1
        yield match.group(1), block, raw


def render_env(original: str, updates: dict[str, str]) -> str:
    for key, value in updates.items():
        validate_value(key, value)
    newline = "\r\n" if "\r\n" in original else "\n"
    replaced = set()
    result = []
    for key, block, _ in env_records(original):
        if key not in updates:
            result.append(block)
        elif key not in replaced:
            result.append(f"{key}={quote_value(updates[key])}{newline}")
            replaced.add(key)
    missing = [key for key in updates if key not in replaced]
    if missing and result and not result[-1].endswith(("\n", "\r")):
        result.append(newline)
    result.extend(f"{key}={quote_value(updates[key])}{newline}" for key in missing)
    return "".join(result)


def read_existing(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("An existing regular .env file is required; symbolic links are not accepted.")
    content = path.read_bytes()
    if len(content) > 1024 * 1024 or b"\0" in content:
        raise ConfigurationError("The existing .env is not a supported text configuration.")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigurationError("The existing .env must use UTF-8 encoding.") from None
    return content


def write_private(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def update_env(path: Path, updates: dict[str, str]) -> Path:
    """Back up exact bytes, then atomically replace, with a concurrent-edit guard."""
    original = read_existing(path)
    bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    text = original[len(bom):].decode("utf-8")
    candidate = bom + render_env(text, updates).encode("utf-8")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.oauth-backup-{timestamp}")
    write_private(backup, original)
    fd, temporary_name = tempfile.mkstemp(prefix=".oauth-config-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        if read_existing(path) != original:
            raise ConfigurationError("The .env changed during this update; no replacement made. Retry after other edits finish.")
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup


def configured_status(path: Path) -> dict[str, bool]:
    original = read_existing(path).decode("utf-8-sig")
    present = {}
    for key, _, raw in env_records(original):
        if key not in ALLOWED_KEYS:
            continue
        value = raw.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            present[key] = not value.startswith(quote * 2)
        else:
            value = value.split(" #", 1)[0].strip()
            present[key] = bool(value) and not value.startswith("#")
    return {
        **{provider: all(present.get(f"{prefix}_{suffix}", False) for suffix in ("CLIENT_ID", "CLIENT_SECRET"))
           for provider, prefix in PROVIDERS.items()},
        "public_origin": present.get("PUBLIC_ORIGIN", False),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Configure family dashboard Web OAuth without printing credentials.")
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    parser.add_argument("--check", action="store_true", help="Only show whether configuration fields are populated; no values.")
    args = parser.parse_args(argv)
    try:
        if args.check:
            print(json.dumps(configured_status(args.env_file), ensure_ascii=True))
            print("Populated configuration fields only; this does not verify account authorization.")
            return 0
        if args.provider is None:
            parser.error("--provider is required unless --check is used")
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ConfigurationError("Use an interactive terminal (ssh -t racknerd). Piped credential input is disabled.")
        if os.name != "posix":
            raise ConfigurationError("Run this helper on the Linux server so file mode 0600 is enforced.")
        read_existing(args.env_file)
        prefix = PROVIDERS[args.provider]
        print(f"Configure {args.provider}. Existing household passwords and the other provider will be preserved.")
        client_id = validate_value(f"{prefix}_CLIENT_ID", input("Application / client ID: ").strip())
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            secret = getpass.getpass("Client secret VALUE (hidden): ")
            validate_value(f"{prefix}_CLIENT_SECRET", secret)
            repeated = getpass.getpass("Repeat client secret VALUE (hidden): ")
        if secret != repeated:
            raise ConfigurationError("The two secret entries do not match; no changes made.")
        update_env(args.env_file, {
            "PUBLIC_ORIGIN": PUBLIC_ORIGIN,
            f"{prefix}_CLIENT_ID": client_id,
            f"{prefix}_CLIENT_SECRET": secret,
        })
        print("Saved OAuth configuration and a timestamped backup, both with file mode 0600. No secret was printed.")
        print("Next: docker compose up -d --force-recreate app sync web")
        print("Then sign in with your household password and bind your provider in Account & sync.")
        return 0
    except (ConfigurationError, OSError, getpass.GetPassWarning, EOFError):
        # Never include arbitrary exception messages: they can contain .env text.
        print("Configuration was not completed. Check the client ID format, nonempty matching secrets, interactive terminal, and existing readable/writable .env.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled. No credentials were printed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
