import plistlib
from pathlib import Path

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
