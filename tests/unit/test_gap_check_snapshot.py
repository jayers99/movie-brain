"""The gap-check snapshot script exports a commit and copies one database, nothing else."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gap_check_snapshot.sh"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "CLAUDE.md").write_text("# app\n")
    (r / "src").mkdir()
    (r / "src" / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(r), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "one"],
        check=True,
    )
    (r / "src" / "a.py").write_text("x = 2\n")  # dirty working tree: must NOT be exported
    return r


def run(repo: Path, scratch: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=repo,
        env={**os.environ, "CLAUDE_SCRATCHPAD": str(scratch)},
        capture_output=True,
        text=True,
    )


def paths(out: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in out.stdout.strip().splitlines())


def test_exports_the_commit_not_the_working_tree(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "backup.db"
    db.write_bytes(b"sqlite")
    scratch = tmp_path / "scratch"
    out = run(repo, scratch, "HEAD", str(db), "trial")
    assert out.returncode == 0, out.stderr
    project = Path(paths(out)["PROJECT"])
    assert project == scratch / "gap-check" / "trial" / "project"
    assert (project / "src" / "a.py").read_text() == "x = 1\n"
    assert not (project / ".git").exists()


def test_config_dir_holds_the_database_and_nothing_else(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "backup.db"
    db.write_bytes(b"sqlite")
    (tmp_path / "credentials.toml").write_text("[x]\n")  # beside the backup; must not travel
    scratch = tmp_path / "scratch"
    lines = paths(run(repo, scratch, "HEAD", str(db), "trial"))
    config = Path(lines["CONFIG"])
    assert sorted(p.name for p in config.iterdir()) == ["movie-brain.db"]
    assert (config / "movie-brain.db").read_bytes() == b"sqlite"
    assert Path(lines["FINDINGS"]) == scratch / "gap-check" / "trial" / "FINDINGS.md"
    assert not Path(lines["FINDINGS"]).exists()


def test_rerun_replaces_the_snapshot(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "backup.db"
    db.write_bytes(b"sqlite")
    scratch = tmp_path / "scratch"
    run(repo, scratch, "HEAD", str(db), "trial")
    stale = scratch / "gap-check" / "trial" / "project" / "stale.txt"
    stale.write_text("old")
    run(repo, scratch, "HEAD", str(db), "trial")
    assert not stale.exists()


def test_name_defaults_to_the_short_hash(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "backup.db"
    db.write_bytes(b"sqlite")
    short = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    lines = paths(run(repo, tmp_path / "scratch", "HEAD", str(db)))
    assert Path(lines["PROJECT"]).parent.name == short


def test_missing_database_exits_2(repo: Path, tmp_path: Path) -> None:
    out = run(repo, tmp_path / "scratch", "HEAD", str(tmp_path / "nope.db"), "trial")
    assert out.returncode == 2
    assert "nope.db" in out.stderr


def test_missing_argument_exits_2(repo: Path, tmp_path: Path) -> None:
    out = run(repo, tmp_path / "scratch", "HEAD")
    assert out.returncode == 2
    assert "usage" in out.stderr.lower()
