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
