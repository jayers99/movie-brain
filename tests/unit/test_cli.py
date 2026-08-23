import json

from typer.testing import CliRunner

from movie_brain.application.sync import SyncResult
from movie_brain.cli import app

runner = CliRunner()


def test_sync_flags_are_mutually_exclusive(config_dir):
    (config_dir / "omdb-api-key.txt").write_text("k")
    r = runner.invoke(app, ["sync", "--full", "--ratings-only"])
    assert r.exit_code == 2
    assert "mutually exclusive" in r.output


def test_sync_requires_api_key(config_dir):
    r = runner.invoke(app, ["sync"])
    assert r.exit_code == 2
    assert "OMDB_API_KEY" in r.output


def test_sync_propagates_exit_code(config_dir, monkeypatch):
    (config_dir / "omdb-api-key.txt").write_text("k")
    calls = {}

    def fake_sync(repo, api_key, today, **kw):
        calls.update(kw, api_key=api_key)
        return SyncResult(1, False, 0, 0, False, False)

    monkeypatch.setattr("movie_brain.cli.sync", fake_sync)
    r = runner.invoke(app, ["sync", "--full"])
    assert r.exit_code == 1
    assert calls["force_full"] is True and calls["ratings_only"] is False and calls["api_key"] == "k"


def test_import_legacy_and_status(config_dir, tmp_path):
    legacy = tmp_path / "legacy"
    (legacy / "payloads").mkdir(parents=True)
    (legacy / "catalog.json").write_text(
        json.dumps(
            {
                "films_fetched_at": "2026-08-10",
                "leaving": {},
                "films": [{"title": "Trio", "year": 1950, "director": "D", "url": "u"}],
            }
        )
    )
    r = runner.invoke(app, ["import-legacy", "--from", str(legacy)])
    assert r.exit_code == 0 and "films: 1" in r.output
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 0 and "1" in r.output


def test_export_csv(config_dir, tmp_path):
    out = tmp_path / "x.csv"
    r = runner.invoke(app, ["export", "csv", str(out)])
    assert r.exit_code == 0 and out.exists()


def test_metacritic_crawl_reports_and_propagates_exit(config_dir, monkeypatch):
    from movie_brain.application.metacritic import CrawlReport

    calls = {}

    def fake_crawl(cfg_dir, pages, **kw):
        calls["pages"] = pages
        return CrawlReport(0, fetched=8, skipped=2, archived=10)

    monkeypatch.setattr("movie_brain.cli.crawl_archive", fake_crawl)
    r = runner.invoke(app, ["metacritic", "crawl"])
    assert r.exit_code == 0 and calls["pages"] == 10
    assert "fetched: 8" in r.output and "archived: 10" in r.output

    def failing_crawl(cfg_dir, pages, **kw):
        return CrawlReport(1, fetched=1, skipped=0, archived=1)

    monkeypatch.setattr("movie_brain.cli.crawl_archive", failing_crawl)
    r = runner.invoke(app, ["metacritic", "crawl", "--pages", "5"])
    assert r.exit_code == 1


def test_metacritic_match_prints_coverage_report(config_dir, monkeypatch):
    from movie_brain.application.metacritic import MatchReport

    report = MatchReport(0, pages=10, titles=240, floor=94, films=3051, matched=57, expected_missed=3, review_open=5)
    monkeypatch.setattr("movie_brain.cli.match_archive", lambda repo, cfg_dir, today: report)
    r = runner.invoke(app, ["metacritic", "match"])
    assert r.exit_code == 0
    assert "10 pages" in r.output and "240 titles" in r.output and "floor 94" in r.output
    assert "57/3051" in r.output and "1.9%" in r.output
    assert "expected-but-missed: 3" in r.output and "5 open" in r.output


def test_metacritic_match_fails_without_archive(config_dir, monkeypatch):
    from movie_brain.application.metacritic import MatchReport

    empty = MatchReport(1, 0, 0, None, 0, 0, 0, 0)
    monkeypatch.setattr("movie_brain.cli.match_archive", lambda repo, cfg_dir, today: empty)
    r = runner.invoke(app, ["metacritic", "match"])
    assert r.exit_code == 1
