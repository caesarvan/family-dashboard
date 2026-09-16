"""Synthetic local files only; no credentials, services, Docker or network."""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "configure-assistant.py"
spec = importlib.util.spec_from_file_location("assistant_configuration", SCRIPT)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
MODEL = "us/azure/openai/gpt-4o-mini"
SECRET = "synthetic-secret-$HOME-${NOT_REAL}-$$-'quote'-\"double\"-\\tail\\"
UPDATES = {"ASSISTANT_PROVIDER": "nvidia", "NVIDIA_MODEL": MODEL, "NVIDIA_API_KEY": SECRET}


def parsed(raw):
    return {key: value for key, _, value in config.env_records(raw) if key}


def assert_safe(error):
    assert str(error) in config.ERRORS.values()
    assert error.__context__ is None
    assert error.__cause__ is None


def run_cli(*args, content=b"", env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=content,
                          capture_output=True, timeout=15, env=env)


def test_render_preserves_unrelated_multiline_export_comments_and_mixed_endings():
    unrelated = ("# 保留\r\nSECRET_KEY=household\n"
                 "NOTES='first\r\nNVIDIA_API_KEY=inside-value\nlast' # original\r\n"
                 'DOUBLE="first\\\"quote\nNVIDIA_MODEL=inside-value\nlast"\n'
                 "TRAILING='two\\\\'\r\n")
    original = unrelated + "export NVIDIA_API_KEY : old # drop old comment\r\n"
    result = config.render_env(original, UPDATES)
    assert result.startswith(unrelated)
    assert parsed(result)["NVIDIA_API_KEY"] == SECRET
    assert parsed(result)["TRAILING"] == "two\\\\"
    assert parsed(result)["NVIDIA_MODEL"] == MODEL
    assert result.count("export NVIDIA_API_KEY") == 0
    assert result.count('NVIDIA_API_KEY="') == 1


@pytest.mark.parametrize("value", ["a", "a/b:c-1_2.3", "a" * 200, MODEL])
def test_model_safe_ascii(value):
    assert config.validate_value("NVIDIA_MODEL", value) == value


@pytest.mark.parametrize("value", [None, "", "a" * 201, "model name", "模型", "a\n", "$HOME",
                                  "a;cmd", "a&cmd", "a`cmd", "a'", 'a"', "a\\", "/a", "-a"])
def test_model_rejects_unsafe_or_ambiguous_values(value):
    with pytest.raises(config.ConfigurationError) as caught:
        config.validate_value("NVIDIA_MODEL", value)
    assert_safe(caught.value)


@pytest.mark.parametrize("updates", [{}, {"NVIDIA_MODEL": MODEL}, {**UPDATES, "OTHER": "value"},
                                    {**UPDATES, "ASSISTANT_PROVIDER": "openai"},
                                    {**UPDATES, "NVIDIA_API_KEY": ""}])
def test_only_complete_three_key_updates(updates):
    with pytest.raises(config.ConfigurationError) as caught:
        config.render_env("SECRET_KEY=unchanged\n", updates)
    assert_safe(caught.value)


@pytest.mark.parametrize("original", ["X=1\nX=2\n", "NVIDIA_MODEL=a\nexport NVIDIA_MODEL=b\n",
    "X='unterminated\n", 'X="a" trailing\n', 'X="a"Y=b\n', "bare-key\n", "export X\n",
    "X=a\rY=b", "X=bad\0value", "X=bad\x1bvalue", "X=a\u2028Y=b", "X=a\x85Y=b",
    "X=a'quoted\n", "X=continued\\\nmore\n", "X=`command`\nINVALID", "bad-key=value\n"])
def test_ambiguous_input_is_rejected_before_writes(tmp_path, original):
    path = tmp_path / ".env"
    before = original.encode()
    path.write_bytes(before)
    with pytest.raises(config.ConfigurationError) as caught:
        config.update_env(path, UPDATES)
    assert_safe(caught.value)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("secret", ["", "   ", "nul\0", "line\n", "line\r", "tab\t", "del\x7f",
                                   "c1\x85", "zero\u200b", "sep\u2028", "bad\ud800", "a" * 4097])
def test_secret_controls_or_size_rejected(secret):
    with pytest.raises(config.ConfigurationError) as caught:
        config.validate_value("NVIDIA_API_KEY", secret)
    assert_safe(caught.value)


@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_stdin_accepts_one_bounded_line_and_preserves_spaces(ending):
    secret = " " + "a" * 4094 + " "
    assert config.read_key_stdin(io.BytesIO(secret.encode() + ending)) == secret


@pytest.mark.parametrize("raw", [b"", b"\n", b"a\nb", b"a\n\n", b"a\r", b"a\0", b"\xff",
                                 b"a" * 4097, b"a" * 4097 + b"\n", ("密" * 1366).encode()])
def test_stdin_rejects_multiline_invalid_utf8_or_oversize(raw):
    with pytest.raises(config.ConfigurationError) as caught:
        config.read_key_stdin(io.BytesIO(raw))
    assert_safe(caught.value)


def test_stdin_read_is_bounded():
    class Stream:
        def read(self, size):
            assert size == 4099
            return b"a" * size
    with pytest.raises(config.ConfigurationError):
        config.read_key_stdin(Stream())


@pytest.mark.parametrize("original", [b"", b"\xef\xbb\xbfX=unchanged", b"X=unchanged\r\n", b"X=unchanged"])
def test_exact_backup_bom_no_final_newline_and_private_modes(tmp_path, original):
    path = tmp_path / ".env"
    path.write_bytes(original)
    backup = config.update_env(path, UPDATES)
    assert backup.read_bytes() == original
    assert path.read_bytes().startswith(original)
    assert parsed(path.read_bytes().decode("utf-8-sig"))["NVIDIA_API_KEY"] == SECRET
    assert set(tmp_path.iterdir()) == {path, backup}
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600


@pytest.mark.parametrize("raw", [b"\xff", b"\0", b"x" * (1024 * 1024 + 1)], ids=["utf8", "nul", "oversize"])
def test_file_input_bounds(tmp_path, raw):
    path = tmp_path / ".env"
    path.write_bytes(raw)
    with pytest.raises(config.ConfigurationError) as caught:
        config.update_env(path, UPDATES)
    assert_safe(caught.value)
    assert path.read_bytes() == raw
    assert set(tmp_path.iterdir()) == {path}


def test_candidate_size_bound(tmp_path):
    path = tmp_path / ".env"
    raw = b"#" + b"x" * (config.ENV_LIMIT - 1)
    path.write_bytes(raw)
    with pytest.raises(config.ConfigurationError):
        config.update_env(path, UPDATES)
    assert path.read_bytes() == raw
    assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize("kind", ["missing", "directory", "hardlink", "symlink", "parent-symlink"])
def test_rejects_nonregular_or_linked_paths(tmp_path, kind):
    path = tmp_path / ".env"
    real = tmp_path / "real"
    real.mkdir()
    target = real / "env"
    target.write_bytes(b"X=unchanged\n")
    if kind == "directory":
        path.mkdir()
    elif kind == "hardlink":
        os.link(target, path)
    elif kind in {"symlink", "parent-symlink"}:
        try:
            path.symlink_to(target if kind == "symlink" else real, target_is_directory=kind == "parent-symlink")
        except OSError:
            pytest.skip("This Windows identity cannot create symlinks; Linux run covers it")
        if kind == "parent-symlink":
            path = path / "env"
    with pytest.raises(config.ConfigurationError) as caught:
        config.update_env(path, UPDATES)
    assert_safe(caught.value)
    assert target.read_bytes() == b"X=unchanged\n"


@pytest.mark.parametrize("changed", [b"X=concurrent\n", b"X=before\n"])
def test_concurrent_content_or_identical_replacement_not_overwritten(tmp_path, monkeypatch, changed):
    path = tmp_path / ".env"
    original = b"X=before\n"
    path.write_bytes(original)
    real = config._snapshot
    calls = 0
    def race(target):
        nonlocal calls
        calls += 1
        if calls == 2:
            other = tmp_path / "other"
            other.write_bytes(changed)
            os.replace(other, path)
        return real(target)
    monkeypatch.setattr(config, "_snapshot", race)
    with pytest.raises(config.ConfigurationError) as caught:
        config.update_env(path, UPDATES)
    assert caught.value.code == "changed"
    assert_safe(caught.value)
    assert path.read_bytes() == changed
    backups = list(tmp_path.glob(".env.assistant-backup-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert not list(tmp_path.glob(".assistant-config-*"))
    assert not list(tmp_path.glob("*.assistant-lock"))


def test_lock_rejects_simultaneous_tool_and_preserves_existing_lock(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"X=before\n")
    lock = tmp_path / ".env.assistant-lock"
    lock.write_bytes(b"existing")
    with pytest.raises(config.ConfigurationError) as caught:
        config.update_env(path, UPDATES)
    assert caught.value.code == "busy"
    assert lock.read_bytes() == b"existing"
    assert path.read_bytes() == b"X=before\n"


@pytest.mark.parametrize("operation", ["backup", "temporary", "replace", "sync-before", "sync-after"])
def test_write_failures_keep_original_or_committed_file_and_exact_backup(tmp_path, monkeypatch, operation):
    path = tmp_path / ".env"
    original = b"X=before\n"
    path.write_bytes(original)
    real_write = config.write_private
    sync_calls = 0
    def fail(*args, **kwargs):
        raise OSError(SECRET)
    def write(target, content):
        if operation == "backup" and "backup" in target.name or operation == "temporary" and "config" in target.name:
            fail()
        real_write(target, content)
    def sync(parent):
        nonlocal sync_calls
        sync_calls += 1
        if (operation == "sync-before" and sync_calls == 1) or (operation == "sync-after" and sync_calls == 2):
            fail()
    monkeypatch.setattr(config, "write_private", write)
    monkeypatch.setattr(config, "_sync_directory", sync)
    if operation == "replace":
        monkeypatch.setattr(config.os, "replace", fail)
    with pytest.raises(config.ConfigurationError) as caught:
        config.update_env(path, UPDATES)
    assert_safe(caught.value)
    if operation == "sync-after":
        assert parsed(path.read_text())["NVIDIA_API_KEY"] == SECRET
    else:
        assert path.read_bytes() == original
    backups = list(tmp_path.glob(".env.assistant-backup-*"))
    assert len(backups) == (0 if operation == "backup" else 1)
    assert all(backup.read_bytes() == original for backup in backups)
    assert not list(tmp_path.glob(".assistant-config-*"))
    assert not list(tmp_path.glob("*.assistant-lock"))


def test_private_write_partial_failure_closes_and_removes_only_own_file(tmp_path, monkeypatch):
    path = tmp_path / "new"
    def fail(fd):
        raise OSError(SECRET)
    monkeypatch.setattr(config.os, "fsync", fail)
    with pytest.raises(config.ConfigurationError) as caught:
        config.write_private(path, SECRET.encode())
    assert_safe(caught.value)
    assert not path.exists()
    path.write_bytes(b"other writer")
    with pytest.raises(config.ConfigurationError):
        config.write_private(path, SECRET.encode())
    assert path.read_bytes() == b"other writer"


def test_temporary_name_collision_does_not_delete_existing_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_bytes(b"X=original\n")
    class Id:
        hex = "fixed"
    monkeypatch.setattr(config.uuid, "uuid4", lambda: Id())
    collision = tmp_path / ".assistant-config-fixed"
    collision.write_bytes(b"not ours")
    with pytest.raises(config.ConfigurationError):
        config.update_env(path, UPDATES)
    assert collision.read_bytes() == b"not ours"
    assert path.read_bytes() == b"X=original\n"


@pytest.mark.parametrize("provider,expected", [("nvidia", True), ('"nvidia"', True), ("'nvidia'", True),
    ("openai", False), ("${OTHER}", False), ("", False)])
def test_real_cli_check_only_booleans_no_values(tmp_path, provider, expected):
    path = tmp_path / ".env"
    raw = f"ASSISTANT_PROVIDER={provider}\nNVIDIA_MODEL={MODEL}\nNVIDIA_API_KEY={config.quote_value(SECRET)}\n".encode()
    path.write_bytes(raw)
    result = run_cli("--env-file", str(path), "--check")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"ASSISTANT_PROVIDER": bool(provider), "NVIDIA_MODEL": True,
                                         "NVIDIA_API_KEY": True, "isNvidia": expected}
    assert not result.stderr and MODEL.encode() not in result.stdout and SECRET.encode() not in result.stdout
    assert path.read_bytes() == raw
    assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize("extra", [["--key", SECRET], ["--model", SECRET], ["--bogus", SECRET],
                                   ["--check", "--key-stdin"], ["--check", "--model", MODEL]])
def test_real_cli_rejects_arguments_without_echo(tmp_path, extra):
    path = tmp_path / ".env"
    path.write_bytes(b"X=original\n")
    result = run_cli("--env-file", str(path), *extra)
    assert result.returncode == 1
    assert not result.stdout
    assert result.stderr.decode().strip() in config.ERRORS.values()
    assert SECRET.encode() not in result.stderr
    assert path.read_bytes() == b"X=original\n"


def test_real_cli_never_uses_environment_key_fallback(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"X=original\n")
    result = run_cli("--env-file", str(path), "--model", MODEL,
                     env={**os.environ, "NVIDIA_API_KEY": SECRET})
    assert result.returncode == 1
    assert SECRET.encode() not in result.stdout + result.stderr
    assert path.read_bytes() == b"X=original\n"


@pytest.mark.skipif(os.name != "posix", reason="Writing CLI requires actual POSIX 0600; tested in WSL")
def test_real_cli_stdin_success_and_private_backup(tmp_path):
    path = tmp_path / ".env"
    raw = b"\xef\xbb\xbfSECRET_KEY=unchanged\r\nNOTES='first\nlast'\r\n"
    path.write_bytes(raw)
    result = run_cli("--env-file", str(path), "--model", MODEL, "--key-stdin", content=SECRET.encode() + b"\n")
    assert result.returncode == 0 and not result.stderr
    assert SECRET.encode() not in result.stdout
    assert parsed(path.read_bytes().decode("utf-8-sig"))["NVIDIA_API_KEY"] == SECRET
    backups = list(tmp_path.glob(".env.assistant-backup-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == raw
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IMODE(backups[0].stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="Actual POSIX CLI path")
@pytest.mark.parametrize("content", [b"", b"a\nb", b"a\n\n", b"\xff", b"a" * 4097])
def test_real_cli_invalid_stdin_does_not_write(tmp_path, content):
    path = tmp_path / ".env"
    path.write_bytes(b"X=original\n")
    result = run_cli("--env-file", str(path), "--model", MODEL, "--key-stdin", content=content)
    assert result.returncode == 1 and not result.stdout
    assert path.read_bytes() == b"X=original\n"
    assert set(tmp_path.iterdir()) == {path}


@pytest.mark.skipif(os.name != "posix", reason="Actual POSIX CLI path")
def test_getpass_hidden_input_and_no_echo_fallback(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    path.write_bytes(b"X=original\n")
    monkeypatch.setattr(config.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(config.getpass, "getpass", lambda prompt: SECRET)
    assert config.main(["--env-file", str(path), "--model", MODEL]) == 0
    assert SECRET not in str(capsys.readouterr())
    before = path.read_bytes()
    def fallback(prompt):
        config.warnings.warn(SECRET, config.getpass.GetPassWarning)
        raise AssertionError("Warning should have aborted before fallback")
    monkeypatch.setattr(config.getpass, "getpass", fallback)
    assert config.main(["--env-file", str(path), "--model", MODEL]) == 1
    assert SECRET not in str(capsys.readouterr())
    assert path.read_bytes() == before
