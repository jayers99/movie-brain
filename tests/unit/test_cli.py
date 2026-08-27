import json

from typer.testing import CliRunner

from movie_brain.application.repair import DupesReport, LinksReport, YearsReport
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


def test_rematch_requires_tmdb_token(config_dir):
    r = runner.invoke(app, ["rematch"])
    assert r.exit_code == 2
    assert "MOVIE_BRAIN_TMDB_TOKEN" in r.output


def test_rematch_propagates_exit_code(config_dir, monkeypatch):
    (config_dir / "tmdb-read-token.txt").write_text("tok")
    from movie_brain.application.rematch import RematchReport

    calls = {}

    def fake_rematch(repo, client, today, **kw):
        calls["token"] = client.headers["Authorization"]
        return RematchReport(1, 0, 0, 0, 0, 0, 0, 0, 0)

    monkeypatch.setattr("movie_brain.cli.rematch", fake_rematch)
    r = runner.invoke(app, ["rematch"])
    assert r.exit_code == 1
    assert calls["token"] == "Bearer tok"


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


def test_metacritic_dial_shows_default_and_sets(config_dir):
    r = runner.invoke(app, ["metacritic", "dial"])
    assert r.exit_code == 0
    assert "100" in r.output  # DEFAULT_TOP_N

    r = runner.invoke(app, ["metacritic", "dial", "500"])
    assert r.exit_code == 0

    r = runner.invoke(app, ["metacritic", "dial"])
    assert "500" in r.output


def test_owned_import_reports_and_propagates_exit(config_dir, monkeypatch):
    import movie_brain.cli as cli
    from movie_brain.application.owned import OwnedReport

    monkeypatch.setattr(cli, "import_owned", lambda repo, cfg, today, **kw: OwnedReport(0, 870, 600, 250, 20, 3))
    r = runner.invoke(app, ["owned", "import"])
    assert r.exit_code == 0
    assert "870" in r.output and "600" in r.output and "250" in r.output

    monkeypatch.setattr(cli, "import_owned", lambda repo, cfg, today, **kw: OwnedReport(1, 0, 0, 0, 0, 0))
    r = runner.invoke(app, ["owned", "import"])
    assert r.exit_code == 1


def test_repair_dupes_dry_run_never_confirms(monkeypatch):
    seen = {}

    def fake(repo, today, *, apply, confirm, log):
        seen["apply"] = apply
        return DupesReport(3, 1, 1, 1, 0, 0)

    monkeypatch.setattr("movie_brain.cli.repair_dupes", fake)
    r = runner.invoke(app, ["repair", "dupes"])
    assert r.exit_code == 0 and seen["apply"] is False and "twins: 1" in r.output


def test_repair_links_requires_token(config_dir):
    r = runner.invoke(app, ["repair", "links"])
    assert r.exit_code == 2 and "TMDB" in r.output


def test_repair_links_film_option(monkeypatch):
    calls = {}
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, film_id=None, apply, log):
        calls.update(film_id=film_id, apply=apply)
        return LinksReport(0, 1, 1, 1)

    monkeypatch.setattr("movie_brain.cli.repair_links", fake)
    r = runner.invoke(app, ["repair", "links", "--film", "1689", "--apply"])
    assert r.exit_code == 0 and calls == {"film_id": 1689, "apply": True}


def test_repair_links_film_without_link_exits_1(monkeypatch):
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, film_id=None, apply, log):
        raise LookupError("film 1689 holds no TMDB link")

    monkeypatch.setattr("movie_brain.cli.repair_links", fake)
    r = runner.invoke(app, ["repair", "links", "--film", "1689"])
    assert r.exit_code == 1 and "no TMDB link" in r.output


def test_repair_years_args_pair(monkeypatch):
    calls = {}

    def fake(repo, today, *, film_id=None, year=None, apply, log):
        calls.update(film_id=film_id, year=year, apply=apply)
        return YearsReport(0, 0, 1, True)

    monkeypatch.setattr("movie_brain.cli.repair_years", fake)
    r = runner.invoke(app, ["repair", "years", "12", "1927", "--apply"])
    assert r.exit_code == 0 and calls == {"film_id": 12, "year": 1927, "apply": True}


def test_repair_editions_dry_run_lists_zero_groups(config_dir):
    r = runner.invoke(app, ["repair", "editions"])
    assert r.exit_code == 0
    assert "groups: 0" in r.output


def test_repair_editions_partial_merge_exits_1(monkeypatch):
    def fake(repo, today, *, apply, confirm, contract, limit, log):
        raise RuntimeError("[partial] #1 PARTIAL: merged into #2 but survivor keying refused")

    monkeypatch.setattr("movie_brain.cli.repair_editions", fake)
    r = runner.invoke(app, ["repair", "editions", "--apply", "--yes"])
    assert r.exit_code == 1
    assert "PARTIAL: merged into #2" in r.output


def test_review_resolve_reports_value_errors(monkeypatch):
    def fake(repo, review_id, **kw):
        raise ValueError("choose exactly one")

    monkeypatch.setattr("movie_brain.cli.resolve_review", fake)
    r = runner.invoke(app, ["review", "resolve", "7", "--dismiss", "--create"])
    assert r.exit_code == 1 and "choose exactly one" in r.output
