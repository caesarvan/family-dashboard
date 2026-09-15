import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "configure-oauth.py"
spec = importlib.util.spec_from_file_location("oauth_configuration_helper", SCRIPT)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
MS_ID = "00000000-1234-4321-9876-123456789abc"


def test_preserves_unrelated_records_and_removes_duplicate_provider_values(tmp_path):
    original = ("# Household config\r\nSECRET_KEY=household-key\r\n"
                "MEMBER1_PASSWORD='unchanged $value'\r\n"
                "NOTES='first\r\nMICROSOFT_CLIENT_SECRET=not-a-real-setting\r\nlast'\r\n"
                "GOOGLE_CLIENT_ID=other.apps.googleusercontent.com\r\n"
                "MICROSOFT_CLIENT_ID=old\r\nexport MICROSOFT_CLIENT_ID=duplicate\r\n")
    path = tmp_path / ".env"
    path.write_bytes(original.encode())
    backup = config.update_env(path, {"MICROSOFT_CLIENT_ID": MS_ID, "MICROSOFT_CLIENT_SECRET": "new-test-secret"})
    result = path.read_bytes().decode()
    assert backup.read_bytes() == original.encode()
    assert result.startswith(original[:original.index("MICROSOFT_CLIENT_ID=old")])
    assert result.count("MICROSOFT_CLIENT_ID=") == 1
    assert "not-a-real-setting" in result
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600


@pytest.mark.parametrize("secret", ["", "injected\nSECRET_KEY=bad", "injected\rvalue", "nul\0value", "esc\x1bvalue"])
def test_rejects_unsafe_values_without_writes(tmp_path, secret):
    path = tmp_path / ".env"
    path.write_text("SECRET_KEY=unchanged\n", encoding="utf-8")
    with pytest.raises(config.ConfigurationError):
        config.update_env(path, {"MICROSOFT_CLIENT_SECRET": secret})
    assert path.read_text() == "SECRET_KEY=unchanged\n"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("key,value", [
    ("SECRET_KEY", "disallowed"),
    ("MICROSOFT_CLIENT_ID", "object-id-is-not-a-client-id"),
    ("GOOGLE_CLIENT_ID", "wrong.example.com"),
    ("PUBLIC_ORIGIN", "https://untrusted.example"),
])
def test_rejects_wrong_field_shapes(key, value):
    with pytest.raises(config.ConfigurationError):
        config.render_env("SECRET_KEY=unchanged\n", {key: value})


def test_unterminated_existing_quote_does_not_modify_file(tmp_path):
    path = tmp_path / ".env"
    original = b"SECRET_KEY='not closed\n"
    path.write_bytes(original)
    with pytest.raises(config.ConfigurationError):
        config.update_env(path, {"MICROSOFT_CLIENT_ID": MS_ID})
    assert path.read_bytes() == original
    assert len(list(tmp_path.iterdir())) == 1


def test_concurrent_edit_is_preserved(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_bytes(b"SECRET_KEY=before\n")
    real_read = config.read_existing
    calls = 0

    def changed_read(target):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(b"SECRET_KEY=concurrent-new-password\n")
        return real_read(target)

    monkeypatch.setattr(config, "read_existing", changed_read)
    with pytest.raises(config.ConfigurationError):
        config.update_env(path, {"MICROSOFT_CLIENT_ID": MS_ID})
    assert path.read_bytes() == b"SECRET_KEY=concurrent-new-password\n"
    assert not list(tmp_path.glob(".oauth-config-*"))


def test_check_prints_only_configuration_presence(tmp_path, capsys):
    path = tmp_path / ".env"
    path.write_text("SECRET_KEY=hidden-household\nMICROSOFT_CLIENT_ID=hidden-id\nMICROSOFT_CLIENT_SECRET=hidden-secret\nGOOGLE_CLIENT_SECRET=''\n", encoding="utf-8")
    assert config.main(["--env-file", str(path), "--check"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output.splitlines()[0]) == {"microsoft": True, "google": False, "public_origin": False}
    assert "hidden" not in output


def test_compose_parses_secrets_literally_without_expanding_variables(tmp_path):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose CLI is not installed")
    available = subprocess.run([docker, "compose", "version"], capture_output=True, timeout=20)
    if available.returncode:
        pytest.skip("Docker Compose CLI is unavailable")
    # Public synthetic values only. This command parses config without a daemon.
    secret = "literal-$HOME-${MISSING_TEST_ONLY}-$$-'quoted'-\"double\"-\\trailing\\"
    env_path = tmp_path / "test.env"
    env_path.write_text(config.render_env("", {"MICROSOFT_CLIENT_SECRET": secret}), encoding="utf-8")
    compose = tmp_path / "compose.yaml"
    compose.write_text("name: oauth-config-test\nservices:\n  probe:\n    image: busybox\n    env_file: test.env\n", encoding="utf-8")
    result = subprocess.run([docker, "compose", "--env-file", str(env_path), "-f", str(compose), "config", "--environment"], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, "Compose rejected a synthetic escaped credential"
    # Canonical YAML/JSON output escapes dollars for re-loading. --environment
    # exposes the parsed dotenv value directly, before that serialization step.
    parsed = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    assert parsed["MICROSOFT_CLIENT_SECRET"] == secret


def test_bom_and_missing_final_newline_are_preserved(tmp_path):
    path = tmp_path / ".env"
    original = b"\xef\xbb\xbfSECRET_KEY=unchanged"
    path.write_bytes(original)
    config.update_env(path, {"PUBLIC_ORIGIN": config.PUBLIC_ORIGIN})
    assert path.read_bytes().startswith(original + b"\nPUBLIC_ORIGIN=")
