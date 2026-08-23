from __future__ import annotations

import contextlib
import json
import subprocess


def notify(title: str, body: str) -> None:
    """Post a macOS notification via osascript (works from the user LaunchAgent).

    json.dumps produces a double-quoted, escaped literal that AppleScript accepts.
    All failures are swallowed: an alert must never affect the sync outcome.
    """
    script = f"display notification {json.dumps(body)} with title {json.dumps(title)}"
    with contextlib.suppress(Exception):  # notification failure must never affect the sync
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True, timeout=10)
