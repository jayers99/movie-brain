import os
import plistlib
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_plist_template_runs_sync_at_3am():
    text = (ROOT / "launchd" / "com.jayers.movie-brain.plist.template").read_text()
    data = plistlib.loads(text.replace("__REPO__", "/r").replace("__CONFIG_DIR__", "/c").encode())
    assert data["Label"] == "com.jayers.movie-brain"
    assert data["ProgramArguments"] == ["/r/.venv/bin/movie-brain", "sync"]
    assert data["StartCalendarInterval"] == {"Hour": 3, "Minute": 0}
    assert data["StandardOutPath"] == "/c/sync.log" and data["StandardErrorPath"] == "/c/sync.log"


def test_install_script_is_executable_and_uses_config_dir():
    script = ROOT / "scripts" / "install-launch-agent.sh"
    assert script.stat().st_mode & 0o111
    body = script.read_text()
    assert "MOVIE_BRAIN_CONFIG_DIR" in body and "com.jayers.movie-brain.plist" in body


@pytest.fixture
def fake_launchctl(tmp_path: Path) -> Path:
    # launchd jobs don't inherit the invoking shell's env, so the installer must never
    # rely on OMDB_API_KEY alone. Stub launchctl so running the real script in a test
    # can't touch the developer's actual launchd state.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "launchctl"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def test_install_script_writes_env_key_to_file_since_launchd_wont_see_the_env(tmp_path: Path, fake_launchctl: Path):
    config_dir = tmp_path / "config"
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_launchctl}:{os.environ['PATH']}",
        "MOVIE_BRAIN_CONFIG_DIR": str(config_dir),
        "HOME": str(home_dir),
        "OMDB_API_KEY": "secret-key-123",
    }
    result = subprocess.run(
        [str(ROOT / "scripts" / "install-launch-agent.sh")], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    key_file = config_dir / "omdb-api-key.txt"
    assert key_file.read_text() == "secret-key-123"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert "Wrote OMDB_API_KEY" in result.stdout


def test_install_script_still_fails_when_neither_key_file_nor_env_present(tmp_path: Path, fake_launchctl: Path):
    config_dir = tmp_path / "config"
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_launchctl}:{os.environ['PATH']}",
        "MOVIE_BRAIN_CONFIG_DIR": str(config_dir),
        "HOME": str(home_dir),
    }
    env.pop("OMDB_API_KEY", None)
    result = subprocess.run(
        [str(ROOT / "scripts" / "install-launch-agent.sh")], env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert not (config_dir / "omdb-api-key.txt").exists()
    assert "put your OMDb API key" in result.stderr
