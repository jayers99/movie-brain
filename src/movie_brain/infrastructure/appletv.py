"""Apple TV app adapter: export the owned-movie library via AppleScript.

The raw osascript output is archived before parsing (re-derivability rule):
a parser fix replays the archive without touching the TV app again. macOS-only;
never runs in sync — `movie-brain owned import` is the only caller.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path

from movie_brain.domain.models import OwnedTitle

_SCRIPT = """
tell application "TV"
    -- Batch-read names, years, and durations as separate evaluations; AppleScript
    -- doesn't guarantee identical ordering, so we guard against count mismatch.
    set ns to name of (every track of library playlist 1 whose media kind is movie)
    set ys to year of (every track of library playlist 1 whose media kind is movie)
    set ds to duration of (every track of library playlist 1 whose media kind is movie)
    if (count of ns) is not (count of ys) then error "name/year count mismatch"
    if (count of ns) is not (count of ds) then error "name/duration count mismatch"
end tell
set out to ""
repeat with i from 1 to count of ns
    set out to out & item i of ns & tab & item i of ys & tab & item i of ds & linefeed
end repeat
return out
"""


class AppleTvError(Exception):
    pass


def archive_path(config_dir: Path, today: date) -> Path:
    return config_dir / "appletv" / f"owned-{today.isoformat()}.txt"


def _run_osascript() -> str:
    try:
        result = subprocess.run(["osascript", "-e", _SCRIPT], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as e:
        raise AppleTvError("osascript timed out after 300s") from e
    if result.returncode != 0:
        raise AppleTvError(f"osascript failed: {result.stderr.strip() or result.returncode}")
    return result.stdout


def parse_export(text: str) -> list[OwnedTitle]:
    titles: list[OwnedTitle] = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        raw_title = parts[0]
        raw_year = parts[1]
        title = raw_title.strip()
        if not title:
            continue
        year = int(raw_year) if raw_year.strip().isdigit() and int(raw_year) > 0 else None

        # Handle runtime from third column (v2 format)
        runtime_min: int | None = None
        if len(parts) >= 3:
            raw_duration = parts[2].strip()
            if raw_duration and raw_duration != "missing value":
                try:
                    seconds = float(raw_duration)
                    runtime_min = round(seconds / 60)
                except ValueError:
                    runtime_min = None

        titles.append(OwnedTitle(title, year, runtime_min))
    return titles


def fetch_owned(
    config_dir: Path,
    *,
    runner: Callable[[], str] | None = None,
    today: date | None = None,
) -> list[OwnedTitle]:
    raw = (runner or _run_osascript)()
    if not raw.strip():
        raise AppleTvError("TV app returned no movies — is the library empty or automation consent denied?")
    dest = archive_path(config_dir, today or date.today())
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(raw)
    return parse_export(raw)
