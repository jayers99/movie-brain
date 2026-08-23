from __future__ import annotations

from unittest.mock import patch

from movie_brain.infrastructure.notify import notify


def test_notify_shells_out_to_osascript():
    with patch("movie_brain.infrastructure.notify.subprocess.run") as run:
        notify("movie-brain", 'Alpha on HBO Max — brief "window"')
    args = run.call_args.args[0]
    assert args[0] == "osascript" and args[1] == "-e"
    assert 'with title "movie-brain"' in args[2]
    assert "Alpha on HBO Max" in args[2]


def test_notify_swallows_failure():
    with patch("movie_brain.infrastructure.notify.subprocess.run", side_effect=OSError("no osascript")):
        notify("movie-brain", "body")  # must not raise


def test_notify_keeps_non_ascii_literal_for_osascript():
    # json.dumps defaults to ensure_ascii=True, which emits \uXXXX escapes that
    # osascript's AppleScript parser rejects as a syntax error. The sync summary
    # body always contains "·" with >=2 arrivals, plus "…" on truncation and
    # accented film titles — so the generated script must keep these literal.
    body = "2 watchlist arrivals: Céline on MUBI · 8½ on HBO Max … and 1 more"
    with patch("movie_brain.infrastructure.notify.subprocess.run") as run:
        notify("movie-brain", body)
    script = run.call_args.args[0][2]
    assert "\\u" not in script
    assert "·" in script
    assert "Céline" in script
