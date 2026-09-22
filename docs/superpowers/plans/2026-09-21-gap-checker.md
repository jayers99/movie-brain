# Gap Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the gap checker into the repo so a fresh session can run it at point A (before the mock-up reaches the owner) and point C (after the build, before his hands-on test): one prompt file, one snapshot script with a test, one trial-log section, one CLAUDE.md note.

**Architecture:** No Python module — the checker is a fresh subagent launched by hand with three paths. The only code is a bash script that builds those three paths (a `git archive` of a commit, a copy of a database backup in its own config dir with no credentials) so the checker can never see the working tree, git history or a credential. The prompt is documentation, versioned like the rules.

**Tech Stack:** bash, `git archive`, pytest (`subprocess` in a temp git repo, as `tests/unit/test_schedule.py` does for scripts).

**Spec:** `docs/superpowers/specs/2026-09-21-gap-checker-design.md`

## Global Constraints

- The snapshot directory holds NO `credentials.toml`, `omdb-api-key.txt` or `tmdb-read-token.txt` — the script copies exactly one file, the database, and the test asserts nothing else landed.
- The snapshot lives in the session scratchpad (`$CLAUDE_SCRATCHPAD` if set, else `$TMPDIR/gap-check`), never under the repo.
- The prompt keeps the four checks' wording from `docs/superpowers/research/2026-09-21-gap-checker-backtest/checker-prompt-as-run.md` (that is the wording that scored 4 of 5) and adds the two point-C checks and the findings format from spec §4.
- No hard-wrapped prose in any `.md`.

---

### Task 1: `scripts/gap_check_snapshot.sh` with its test

**Files:**
- Create: `scripts/gap_check_snapshot.sh`
- Test: `tests/unit/test_gap_check_snapshot.py`

**Interfaces:**
- Produces: `scripts/gap_check_snapshot.sh <commit> <db-file> [name]` → prints three lines `PROJECT=<dir>`, `CONFIG=<dir>`, `FINDINGS=<path>`; exit 2 on a missing argument or a missing db file. `name` defaults to the commit's short hash; every run to the same name REPLACES the snapshot.

- [ ] **Step 1: Write the failing test**

```python
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


def test_exports_the_commit_not_the_working_tree(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "backup.db"
    db.write_bytes(b"sqlite")
    scratch = tmp_path / "scratch"
    out = run(repo, scratch, "HEAD", str(db), "trial")
    assert out.returncode == 0, out.stderr
    lines = dict(line.split("=", 1) for line in out.stdout.strip().splitlines())
    project = Path(lines["PROJECT"])
    assert project == scratch / "gap-check" / "trial" / "project"
    assert (project / "src" / "a.py").read_text() == "x = 1\n"
    assert not (project / ".git").exists()


def test_config_dir_holds_the_database_and_nothing_else(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "backup.db"
    db.write_bytes(b"sqlite")
    (tmp_path / "credentials.toml").write_text("[x]\n")  # beside the backup; must not travel
    scratch = tmp_path / "scratch"
    out = run(repo, scratch, "HEAD", str(db), "trial")
    lines = dict(line.split("=", 1) for line in out.stdout.strip().splitlines())
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


def test_missing_database_exits_2(repo: Path, tmp_path: Path) -> None:
    out = run(repo, tmp_path / "scratch", "HEAD", str(tmp_path / "nope.db"), "trial")
    assert out.returncode == 2
    assert "nope.db" in out.stderr


def test_missing_argument_exits_2(repo: Path, tmp_path: Path) -> None:
    out = run(repo, tmp_path / "scratch", "HEAD")
    assert out.returncode == 2
    assert "usage" in out.stderr.lower()
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/unit/test_gap_check_snapshot.py -q` Expected: 5 failures (script not found / permission denied).

- [ ] **Step 3: Write the script**

```bash
#!/usr/bin/env bash
# Build the three paths a gap checker needs, so it can never see the working
# tree, git history or a credential: a git-archive of one commit, a copy of one
# database backup in a config dir of its own, and the findings path.
#   scripts/gap_check_snapshot.sh <commit> <db-file> [name]
# Prints PROJECT=, CONFIG=, FINDINGS=. A rerun with the same name replaces it.
set -euo pipefail

usage() { echo "usage: $0 <commit> <db-file> [name]" >&2; exit 2; }
[ $# -ge 2 ] || usage
COMMIT="$1"; DB="$2"
[ -f "$DB" ] || { echo "no such database: $DB" >&2; exit 2; }
NAME="${3:-$(git rev-parse --short "$COMMIT")}"
ROOT="${CLAUDE_SCRATCHPAD:-${TMPDIR:-/tmp}}/gap-check/$NAME"
PROJECT="$ROOT/project"; CONFIG="$ROOT/config"

rm -rf "$ROOT"
mkdir -p "$PROJECT" "$CONFIG"
git archive "$COMMIT" | tar -x -C "$PROJECT"
cp "$DB" "$CONFIG/movie-brain.db"
chmod 600 "$CONFIG/movie-brain.db"

echo "PROJECT=$PROJECT"
echo "CONFIG=$CONFIG"
echo "FINDINGS=$ROOT/FINDINGS.md"
```

Then `chmod +x scripts/gap_check_snapshot.sh`.

- [ ] **Step 4: Run the test to see it pass**

Run: `uv run pytest tests/unit/test_gap_check_snapshot.py -q` Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tests/unit/test_gap_check_snapshot.py && uv run mypy
git add scripts/gap_check_snapshot.sh tests/unit/test_gap_check_snapshot.py
git commit -m "the gap checker's snapshot: one commit, one database, no credential, never the working tree"
```

---

### Task 2: The prompt file `docs/superpowers/checks/gap-check.md`

**Files:**
- Create: `docs/superpowers/checks/gap-check.md`
- Read: `docs/superpowers/research/2026-09-21-gap-checker-backtest/checker-prompt-as-run.md` (the wording to keep), spec §4–§6.

**Interfaces:**
- Produces: a prompt the launcher hands to a `general-purpose` subagent with the three paths from Task 1 filled into its "Paths" block, plus the point (A or C) and the brief folder.

- [ ] **Step 1: Write the file**

Contents — the as-run prompt's five sections verbatim (title, "What you have", "The four checks", "Findings file", closing rules), with these changes and additions:

1. Replace the opening line's "clickable mock-up for the owner" framing with a two-point framing: at **point A** the inputs are the brief draft, the mock-up page and the plan if one exists; at **point C** they are the feature branch and the brief with its stories, and the app runs on a migrated copy.
2. A **Paths** block at the top, filled by the launcher:

```
Point: A | C
Project directory: <PROJECT>
Brief folder inside it: docs/superpowers/briefs/<feature>/
Config directory (set MOVIE_BRAIN_CONFIG_DIR to this): <CONFIG>
Findings file to write: <FINDINGS>
Dashboard port range: <e.g. 5700–5709>
```

3. Under "The four checks", the two point-C checks from spec §4:

```
5. **Every story replayed on the real app** (point C only). The Playwright tests under the story names must pass, AND you walk each story by hand on the running copy with the real film the story names, keeping a screenshot beside the findings file. A story that passes as a test but reads differently on screen is a finding.
6. **The fixtures against the real answers** (point C only). Where a credentials file exists in the config directory AND the call is read-only, make the real call ONCE and diff its answer's shape (keys, nesting, types — never the values) against the test fixture that mocks it; a key the fixture has and the answer lacks, or the reverse, is a finding. Where the call writes, or no credentials exist, name it under "Not checked". Never write to an external account. Never print, log or copy a credential, token, customer id or email — the config file is read only by the app's own code.
```

4. Under "Findings file", add after the field list: "**Kinds** at point C also include `fixture-mismatch` (check 6) and `story-differs-on-screen` (check 5)."
5. A closing **What happens next** paragraph, from spec §6: the builder answers every finding in the trial log as fixed / story added / declined / unverifiable; one fix wave, one scoped re-check of the fixed findings only; the checker never loops and never talks to the builder.

- [ ] **Step 2: Check it against the as-run prompt**

Run: `diff <(sed -n '/## The four checks/,/## Findings file/p' docs/superpowers/research/2026-09-21-gap-checker-backtest/checker-prompt-as-run.md) <(sed -n '/## The four checks/,/## Findings file/p' docs/superpowers/checks/gap-check.md)` Expected: the only differences are the two added checks (5 and 6) — the wording of 1–4 is unchanged.

- [ ] **Step 3: Unwrap and commit**

```bash
~/code/praxis-workspace/praxis-halo/bin/unwrap-md docs/superpowers/checks/gap-check.md
git add docs/superpowers/checks/gap-check.md
git commit -m "the gap checker's prompt: the four checks that scored 4 of 5 on the back-test, plus the two that need a running app"
```

---

### Task 3: Wiring — the launcher recipe, the trial-log section, CLAUDE.md

**Files:**
- Create: `docs/superpowers/checks/README.md` (the launcher recipe)
- Modify: each of the four existing trial logs gains nothing (history); the section is for NEW logs — documented in the README.
- Modify: `CLAUDE.md` — one bullet under "## Rules" after the tests bullet.

- [ ] **Step 1: Write the README**

```markdown
# Checks

Fresh-agent checks a session runs BY HAND at fixed points of a feature. Each is a prompt file here; the session launches a `general-purpose` subagent with the prompt and the paths, reads the findings file, and answers every finding in the feature's trial log.

## Gap check (`gap-check.md`)

Spec: `../specs/2026-09-21-gap-checker-design.md`. Evidence: `../research/2026-09-21-gap-checker-backtest/`.

**Point A — before the stories and mock-up reach the owner.** Commit the draft brief and mock-up first (the snapshot is a commit, never the working tree), then:

    scripts/gap_check_snapshot.sh HEAD ~/.config/movie-brain/movie-brain.db <feature>-a

Launch one `general-purpose` subagent whose prompt is `gap-check.md` with the Paths block filled from the script's three lines, `Point: A`, the brief folder and a free port range. Wait for the findings file.

**Point C — after the build, before the owner's hands-on test.** Migrate a copy of the live database the way the hands-on trial is prepared, then:

    scripts/gap_check_snapshot.sh <branch-head> <migrated-copy.db> <feature>-c

Same launch with `Point: C`. If the owner's `credentials.toml` should be available for check 6, copy it into the CONFIG directory yourself, by name, mode 600 — the script never does.

**Triage.** In the feature's `trial-log.md`, a section:

    ## Gap check (point A | C)

    | # | Finding (kind) | Answer | Note |
    |---|---|---|---|
    | 1 | … | fixed / story added / declined / unverifiable | … |

    Agent minutes: N · Findings: N · Fixed: N · Stories added: N · Declined: N · Not checked: …

One fix wave, one scoped re-check of the fixed findings only (relaunch with the same prompt plus the line `Re-check only findings: 1, 4, 7`). Anything still open after that goes to the diagnostic checkpoint. The owner sees only the story cards that changed, a decision packet if a finding touches something he approved, and the one summary line at the foot of the delivery.

**Retire** a point when ten consecutive runs at that point produce nothing the builder fixes; cut it back if the owner's mock-up rounds slow down.
```

- [ ] **Step 2: Add the CLAUDE.md bullet**

After the bullet beginning `- Tests mirror the layers:` in `CLAUDE.md`, add:

```markdown
- **Gap check** (spec `docs/superpowers/specs/2026-09-21-gap-checker-design.md`, decided on a back-test that found 4 of 5 past misses — `docs/superpowers/research/2026-09-21-gap-checker-backtest/`): before the stories and mock-up reach the owner (point A) and after the build before his hands-on test (point C), a fresh subagent runs `docs/superpowers/checks/gap-check.md` on a snapshot from `scripts/gap_check_snapshot.sh` (a commit's `git archive` plus one database copy, no credential, never the working tree) and writes a findings file; the builder answers every finding in the trial log (fixed / story added / declined / unverifiable), one fix wave, one scoped re-check, no agent chat. The launcher recipe is `docs/superpowers/checks/README.md`. The owner sees only changed story cards, a decision packet when a finding touches something he approved, and one summary line.
```

- [ ] **Step 3: Full gates and commit**

```bash
uv run pytest -q tests/unit/test_gap_check_snapshot.py && uv run ruff check . && uv run mypy
git add docs/superpowers/checks/README.md CLAUDE.md
git commit -m "the gap check is on the record: launcher recipe, trial-log section, CLAUDE.md"
```

- [ ] **Step 4: Rehearse the launcher once, for real**

Run `scripts/gap_check_snapshot.sh HEAD ~/.config/movie-brain/backups/movie-brain-v28-2026-09-20.db rehearsal` and confirm the three printed paths exist, the CONFIG dir holds one file, and `git -C <PROJECT> status` fails (no repo). Do NOT launch a checker — the rehearsal is of the script against a real backup, not of a feature. Remove the snapshot afterwards.
