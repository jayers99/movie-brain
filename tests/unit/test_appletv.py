from __future__ import annotations

from datetime import date

import pytest

from movie_brain.infrastructure.appletv import AppleTvError, archive_path, fetch_owned, parse_export

TODAY = date(2026, 8, 19)


def test_parse_export_reads_tab_lines():
    text = "Step Brothers\t2008\nThe Other Guys\t2010\n"
    titles = parse_export(text)
    assert [(t.title, t.year) for t in titles] == [("Step Brothers", 2008), ("The Other Guys", 2010)]


def test_parse_export_missing_or_zero_year_becomes_none():
    titles = parse_export("Mystery Film\t0\nNo Year Film\t\nBlank Skipped\n\n")
    assert [(t.title, t.year) for t in titles] == [("Mystery Film", None), ("No Year Film", None)]


def test_fetch_owned_archives_raw_before_parsing(config_dir):
    raw = "Step Brothers\t2008\n"
    titles = fetch_owned(config_dir, runner=lambda: raw, today=TODAY)
    assert len(titles) == 1
    assert archive_path(config_dir, TODAY).read_text() == raw


def test_fetch_owned_runner_failure_raises_and_archives_nothing(config_dir):
    def boom() -> str:
        raise AppleTvError("osascript failed")

    with pytest.raises(AppleTvError):
        fetch_owned(config_dir, runner=boom, today=TODAY)
    assert not archive_path(config_dir, TODAY).exists()


def test_fetch_owned_empty_library_is_an_error(config_dir):
    with pytest.raises(AppleTvError):
        fetch_owned(config_dir, runner=lambda: "", today=TODAY)
