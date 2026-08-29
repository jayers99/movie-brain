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

    def fake(repo, client, today, *, film_id=None, tt=None, apply, log):
        calls.update(film_id=film_id, tt=tt, apply=apply)
        return LinksReport(0, 1, 1, 1)

    monkeypatch.setattr("movie_brain.cli.repair_links", fake)
    r = runner.invoke(app, ["repair", "links", "--film", "1689", "--apply"])
    assert r.exit_code == 0 and calls == {"film_id": 1689, "tt": None, "apply": True}


def test_repair_links_film_without_link_exits_1(monkeypatch):
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, film_id=None, tt=None, apply, log):
        raise LookupError("film 1689 holds no TMDB link")

    monkeypatch.setattr("movie_brain.cli.repair_links", fake)
    r = runner.invoke(app, ["repair", "links", "--film", "1689"])
    assert r.exit_code == 1 and "no TMDB link" in r.output


def test_repair_links_tt_passes_through_and_reports_rekeys(monkeypatch):
    calls = {}
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, film_id=None, tt=None, apply, log):
        calls.update(film_id=film_id, tt=tt, apply=apply)
        return LinksReport(0, 0, 0, 0, 1)

    monkeypatch.setattr("movie_brain.cli.repair_links", fake)
    r = runner.invoke(app, ["repair", "links", "--film", "493", "--tt", "tt0075915", "--apply"])
    assert r.exit_code == 0 and calls == {"film_id": 493, "tt": "tt0075915", "apply": True}
    assert "re-keyed: 1" in r.output


def test_repair_links_tt_misuse_exits_2(monkeypatch):
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, film_id=None, tt=None, apply, log):
        raise ValueError("--tt requires --film")

    monkeypatch.setattr("movie_brain.cli.repair_links", fake)
    r = runner.invoke(app, ["repair", "links", "--tt", "tt0075915"])
    assert r.exit_code == 2 and "requires --film" in r.output


def test_repair_links_tt_held_exits_nonzero(monkeypatch):
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, film_id=None, tt=None, apply, log):
        return LinksReport(1, 0, 0, 0, 0)

    monkeypatch.setattr("movie_brain.cli.repair_links", fake)
    r = runner.invoke(app, ["repair", "links", "--film", "493", "--tt", "tt0075915", "--apply"])
    assert r.exit_code == 1


def test_repair_imdb_requires_token(config_dir):
    r = runner.invoke(app, ["repair", "imdb"])
    assert r.exit_code == 2 and "TMDB" in r.output


def test_repair_imdb_help():
    r = runner.invoke(app, ["repair", "imdb", "--help"])
    assert r.exit_code == 0
    assert "--apply" in r.output and "--limit" in r.output


def test_repair_imdb_dry_run_passes_the_flag_through_and_reports(monkeypatch):
    from movie_brain.application.backfill_imdb import BackfillReport

    calls = {}
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, apply=False, limit=None, log):
        calls.update(apply=apply, limit=limit)
        return BackfillReport(3, 0, 1, 1, 1)

    monkeypatch.setattr("movie_brain.cli.backfill_imdb", fake)
    r = runner.invoke(app, ["repair", "imdb"])
    assert r.exit_code == 0
    assert calls == {"apply": False, "limit": None}
    assert "scanned: 3" in r.output and "backfilled: 0" in r.output
    assert "no imdb id: 1" in r.output and "held: 1" in r.output and "failed: 1" in r.output


def test_repair_imdb_apply_and_limit_pass_through(monkeypatch):
    from movie_brain.application.backfill_imdb import BackfillReport

    calls = {}
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "tok")

    def fake(repo, client, today, *, apply=False, limit=None, log):
        calls.update(apply=apply, limit=limit)
        return BackfillReport()

    monkeypatch.setattr("movie_brain.cli.backfill_imdb", fake)
    r = runner.invoke(app, ["repair", "imdb", "--apply", "--limit", "25"])
    assert r.exit_code == 0
    assert calls == {"apply": True, "limit": 25}


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


def test_repair_disagreements_dry_run_on_empty_db(config_dir):
    r = runner.invoke(app, ["repair", "disagreements"])
    assert r.exit_code == 0 and "groups: 0" in r.output
    assert "pending: 0" in r.output and "review-open: 0" in r.output


def test_repair_disagreements_partial_exits_1(monkeypatch):
    def fake(repo, today, *, apply, confirm, contract, tmdb, fetcher, limit, log):
        raise RuntimeError("[partial] #1 PARTIAL: imdb tt1 written but tmdb 2 id-conflict")

    monkeypatch.setattr("movie_brain.cli.repair_disagreements", fake)
    r = runner.invoke(app, ["repair", "disagreements", "--apply", "--yes"])
    assert r.exit_code == 1 and "PARTIAL" in r.output


def test_review_list_shows_candidate_lines(config_dir):
    from datetime import date

    from movie_brain.application.thumbprint import review_detail
    from movie_brain.domain.models import Film, ReviewEntry
    from movie_brain.domain.thumbprint import Candidate, Scored, Verdict, make_query
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    fid = repo.create_film(Film("Blade Runner (The Final Cut)", 2007, None, ""))
    q = make_query("Blade Runner (The Final Cut)", 2007, "apple", director=None, runtime_min=117)
    c = Candidate("tt0083658", 78, ("Blade Runner",), 1982, "Ridley Scott", 117, 10000, "movie", True, True)
    v = Verdict("review", None, "rerelease-ambiguous", (Scored(c, 5, 3, 0, 0, False, False),))
    repo.append_reviews(
        "tmdb", [ReviewEntry("rerelease-ambiguous", film_id=fid, detail=review_detail(v, q))], date(2026, 8, 26)
    )

    r = runner.invoke(app, ["review", "list"])
    assert r.exit_code == 0
    assert "A tt0083658" in r.output


def test_review_list_marks_a_series_film(config_dir):
    from datetime import date

    from movie_brain.domain.models import Film, ReviewEntry
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    fid = repo.create_film(Film("Dekalog", 1988, None, ""))
    repo.set_film_kind(fid, "series")
    repo.append_reviews("tmdb", [ReviewEntry("no-match-reviewed", film_id=fid, detail="x")], date(2026, 8, 28))

    r = runner.invoke(app, ["review", "list"])
    assert r.exit_code == 0
    assert "[series]" in r.output


def test_review_resolve_reports_value_errors(monkeypatch):
    def fake(repo, review_id, **kw):
        raise ValueError("choose exactly one")

    monkeypatch.setattr("movie_brain.cli.resolve_review", fake)
    r = runner.invoke(app, ["review", "resolve", "7", "--dismiss", "--create"])
    assert r.exit_code == 1 and "choose exactly one" in r.output


def _pretend_one_behind(tmp_path, monkeypatch):
    """Point MIGRATIONS_DIR at a copy with one extra migration so the DB is 'behind'."""
    import shutil

    from movie_brain.infrastructure import database as dbmod

    src = dbmod.MIGRATIONS_DIR
    copy = tmp_path / "migrations"
    shutil.copytree(src, copy)
    n = max(int(p.name.split("_")[0]) for p in copy.glob("*.sql")) + 1
    (copy / f"{n:03d}_t3_probe.sql").write_text(
        f"CREATE TABLE t3_probe (x INTEGER); INSERT INTO schema_version (version) VALUES ({n});"
    )
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", copy)
    return n


def test_status_refuses_a_db_that_is_behind(config_dir, tmp_path, monkeypatch):
    from movie_brain.infrastructure.database import init_db

    init_db(config_dir / "movie-brain.db")
    _pretend_one_behind(tmp_path, monkeypatch)
    r = runner.invoke(app, ["status"])
    assert r.exit_code == 2
    assert "movie-brain migrate --apply" in r.output


def test_migrate_dry_run_lists_pending_then_apply(config_dir, tmp_path, monkeypatch):
    from movie_brain.infrastructure.database import init_db, pending_migrations

    init_db(config_dir / "movie-brain.db")
    n = _pretend_one_behind(tmp_path, monkeypatch)
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 0 and f"{n:03d}_t3_probe.sql" in r.output and "--apply" in r.output
    assert pending_migrations(config_dir / "movie-brain.db")  # dry run wrote nothing
    r = runner.invoke(app, ["migrate", "--apply"])
    assert r.exit_code == 0 and pending_migrations(config_dir / "movie-brain.db") == []
    assert runner.invoke(app, ["status"]).exit_code == 0


def test_migrate_on_current_db_says_so(config_dir):
    r = runner.invoke(app, ["migrate"])
    assert r.exit_code == 0 and "up to date" in r.output


def test_repair_verbs_still_exit_2_on_a_db_that_is_behind(config_dir, tmp_path, monkeypatch):
    """`typer.Exit` subclasses RuntimeError: the migrate guard must not be swallowed by the
    repair verbs' own `except RuntimeError` (which would print a bare "2" and exit 1)."""
    from movie_brain.infrastructure.database import init_db

    init_db(config_dir / "movie-brain.db")
    _pretend_one_behind(tmp_path, monkeypatch)
    for argv in (["repair", "disagreements"], ["repair", "editions"], ["repair", "nomatch"]):
        r = runner.invoke(app, argv)
        assert r.exit_code == 2, (argv, r.exit_code, r.output)
        assert "movie-brain migrate --apply" in r.output, (argv, r.output)


def test_repair_nomatch_dry_run_on_empty_db(config_dir):
    r = runner.invoke(app, ["repair", "nomatch"])
    assert r.exit_code == 0 and "groups: 0" in r.output and "skipped: 0" in r.output


def test_repair_nomatch_partial_exits_1(monkeypatch):
    def fake(repo, today, *, apply, confirm, tmdb, fetcher, limit, log):
        raise RuntimeError("[partial] #1 PARTIAL: imdb tt1 written but tmdb 2 id-conflict")

    monkeypatch.setattr("movie_brain.cli.repair_nomatch", fake)
    r = runner.invoke(app, ["repair", "nomatch", "--apply", "--yes"])
    assert r.exit_code == 1 and "PARTIAL" in r.output


def test_repair_nomatch_session_cache_is_not_the_fixture(config_dir, monkeypatch, tmp_path):
    seen = {}

    def fake(repo, today, *, apply, confirm, tmdb, fetcher, limit, log):
        seen["fetcher"] = fetcher
        from movie_brain.application.repair_keys import NomatchReport

        return NomatchReport(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    monkeypatch.setattr("movie_brain.cli.repair_nomatch", fake)
    (config_dir / "tmdb-read-token.txt").write_text("tok")
    (config_dir / "omdb-api-key.txt").write_text("key")
    r = runner.invoke(app, ["repair", "nomatch"])
    assert r.exit_code == 0
    cache = seen["fetcher"].cache
    assert cache.path == config_dir / "nomatch-cache.json.gz" and not cache.read_only


def test_scorecard_rendering_keeps_bracketed_resolver_reasons_intact(config_dir, tmp_path, monkeypatch):
    """The scorecard is the artifact the owner reads before authorising a live run.

    Rich would read `[director corroborated]` as markup and an 80-column non-terminal would
    fold the entry's two-line block, both silently — and both would leave the string the
    other tests assert on untouched. This pins the CLI's own rendering of the card, which is
    where `markup=False, highlight=False, soft_wrap=True` lives.
    """
    from movie_brain.application.lists import EntryOutcome, ListImportReport

    detail = "gate 2b: tmdb lookup failed — holder unknown  [director corroborated]"
    row = EntryOutcome(
        rank=1,
        title_listed="Citizen Kane",
        director_listed="Orson Welles",
        kind="would-create",
        film_id=None,
        tt="tt0033467",
        reason="director corroborated",
        form_used="Citizen Kane",
        detail=detail,
    )
    monkeypatch.setattr(
        "movie_brain.cli.import_list", lambda *a, **kw: ListImportReport(0, 1, 0, 1, 0, 0, 0, [row])
    )
    (config_dir / "omdb-api-key.txt").write_text("k")
    (config_dir / "tmdb-read-token.txt").write_text("t")
    path = tmp_path / "x.tsv"
    path.write_text("# slug: x\n# name: X\n1\tCitizen Kane\tOrson Welles\n")

    r = runner.invoke(app, ["lists", "import", str(path)])

    assert r.exit_code == 0
    # verbatim and unfolded: the reason is intact and still on its entry's own line.
    assert any(line.endswith(detail) for line in r.output.splitlines())


def test_scorecard_rendering_keeps_the_agreement_tally_line_intact(config_dir, tmp_path, monkeypatch):
    """The tally line (spec §2/§6) is the headline of a supplied-id import: it carries no
    brackets, but it is long (well past 80 columns) and full of `·` separators — exactly the
    shape the CLI's non-terminal 80-column fold already broke once for the two-line entry
    blocks above. Pin that `soft_wrap=True` keeps this line whole too.
    """
    from movie_brain.application.lists import AGREE, DISAGREE, SUPPLIED, EntryOutcome, ListImportReport

    def row(rank: int, agreement: str) -> EntryOutcome:
        return EntryOutcome(
            rank=rank,
            title_listed=f"Film {rank}",
            director_listed=None,
            kind="linked",
            film_id=1,
            tt="tt0000001",
            reason="director corroborated",
            form_used=f"Film {rank}",
            detail="film 1 'Film' (1950)  via imdb tt0000001",
            agreement=agreement,
        )

    rows = [row(1, AGREE), row(2, DISAGREE), row(3, SUPPLIED)]
    monkeypatch.setattr(
        "movie_brain.cli.import_list", lambda *a, **kw: ListImportReport(0, 3, 3, 0, 0, 0, 0, rows)
    )
    (config_dir / "omdb-api-key.txt").write_text("k")
    (config_dir / "tmdb-read-token.txt").write_text("t")
    path = tmp_path / "x.tsv"
    path.write_text("# slug: x\n# name: X\n1\tFilm 1\t\n2\tFilm 2\t\n3\tFilm 3\t\n")

    r = runner.invoke(app, ["lists", "import", str(path)])

    assert r.exit_code == 0
    expected = (
        "resolver vs supplied id:  agree 1 · disagree 1 · resolver had no verdict 1  (of 3 compared)"
    )
    # verbatim, on its own line and unfolded — not split across an 80-column wrap.
    assert expected in r.output.splitlines()


def test_lists_trust_shows_every_list_ordered_desc_then_slug(config_dir):
    from datetime import date

    from movie_brain.domain.models import ListMeta
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    today = date(2026, 8, 29)
    repo.upsert_film_list(
        ListMeta("cahiers-100", "100 Films for an Ideal Cinematheque", "Cahiers du Cinéma", 2008, None, True), today
    )
    repo.upsert_film_list(ListMeta("bergan-100", "Bergan 100", None, None, None, True), today)
    repo.set_list_trust("bergan-100", 5)

    r = runner.invoke(app, ["lists", "trust"])
    assert r.exit_code == 0
    lines = [ln for ln in r.output.splitlines() if ln.strip()]
    assert lines[0].startswith("bergan-100") and "trust 5" in lines[0]
    assert lines[1].startswith("cahiers-100") and "trust 1" in lines[1]


def test_lists_trust_sets_and_persists(config_dir):
    from datetime import date

    from movie_brain.domain.models import ListMeta
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    repo.upsert_film_list(ListMeta("cahiers-100", "Cahiers", None, None, None, True), date(2026, 8, 29))

    r = runner.invoke(app, ["lists", "trust", "cahiers-100", "9"])
    assert r.exit_code == 0
    assert "9" in r.output

    assert repo.film_list("cahiers-100").trust == 9


def test_lists_trust_accepts_zero(config_dir):
    from datetime import date

    from movie_brain.domain.models import ListMeta
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    repo.upsert_film_list(ListMeta("cahiers-100", "Cahiers", None, None, None, True), date(2026, 8, 29))

    r = runner.invoke(app, ["lists", "trust", "cahiers-100", "0"])
    assert r.exit_code == 0
    assert repo.film_list("cahiers-100").trust == 0


def test_lists_trust_rejects_negative_value(config_dir):
    from datetime import date

    from movie_brain.domain.models import ListMeta
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    repo.upsert_film_list(ListMeta("cahiers-100", "Cahiers", None, None, None, True), date(2026, 8, 29))

    r = runner.invoke(app, ["lists", "trust", "cahiers-100", "-1"])
    assert r.exit_code != 0
    assert repo.film_list("cahiers-100").trust == 1  # unchanged


def test_lists_trust_unknown_slug_errors_and_names_known_lists(config_dir):
    from datetime import date

    from movie_brain.domain.models import ListMeta
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    repo.upsert_film_list(ListMeta("cahiers-100", "Cahiers", None, None, None, True), date(2026, 8, 29))

    r = runner.invoke(app, ["lists", "trust", "no-such-list", "5"])
    assert r.exit_code == 2
    assert "no-such-list" in r.output
    assert "cahiers-100" in r.output


def test_lists_trust_unknown_slug_on_empty_registry_says_so(config_dir):
    r = runner.invoke(app, ["lists", "trust", "no-such-list", "5"])
    assert r.exit_code == 2
    assert "no lists registered" in r.output


def test_lists_trust_no_n_shows_one_lists_trust(config_dir):
    from datetime import date

    from movie_brain.domain.models import ListMeta
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    repo.upsert_film_list(ListMeta("cahiers-100", "Cahiers", None, None, None, True), date(2026, 8, 29))
    repo.set_list_trust("cahiers-100", 7)

    r = runner.invoke(app, ["lists", "trust", "cahiers-100"])
    assert r.exit_code == 0
    assert r.output.strip().startswith("cahiers-100")
    assert "trust 7" in r.output


def test_lists_trust_no_n_on_unknown_slug_errors(config_dir):
    from datetime import date

    from movie_brain.domain.models import ListMeta
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    repo.upsert_film_list(ListMeta("cahiers-100", "Cahiers", None, None, None, True), date(2026, 8, 29))

    r = runner.invoke(app, ["lists", "trust", "no-such-list"])
    assert r.exit_code == 2
    assert "no-such-list" in r.output
    assert "cahiers-100" in r.output


def test_lists_trust_no_n_on_unknown_slug_and_empty_registry_says_so(config_dir):
    # The other empty-registry test (test_lists_trust_unknown_slug_on_empty_registry_says_so)
    # passes an N and hits the SET branch; this one omits N to hit the show-one branch's own
    # "no lists registered" fallback, which had no direct test.
    r = runner.invoke(app, ["lists", "trust", "no-such-list"])
    assert r.exit_code == 2
    assert "no lists registered" in r.output


def test_lists_trust_reimport_preserves_trust(config_dir, tmp_path, monkeypatch):
    """Pins the trap this task exists to close: `lists import`'s own registry write
    (`upsert_film_list`) must never reset a trust the owner set with `lists trust`.

    A genuine round trip through the real `lists import` CLI verb — not a direct call to
    `repo.upsert_film_list` — so a future refactor of `import_list`'s registry write would
    actually be caught here."""
    from datetime import date

    from lists_fakes import RecordingFetcher, StubTmdb, candidate

    from movie_brain.domain.models import Film
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    today = date(2026, 8, 29)
    fid = repo.create_film(Film("Citizen Kane", 1941, "Orson Welles", ""))
    assert fid is not None
    repo.set_external_id(fid, "imdb", "tt0033467", today)

    (config_dir / "omdb-api-key.txt").write_text("k")
    (config_dir / "tmdb-read-token.txt").write_text("t")
    monkeypatch.setattr("movie_brain.cli.TmdbClient", lambda token: StubTmdb())
    fetcher = RecordingFetcher(by_title={"Citizen Kane": [candidate("tt0033467", 100, "Citizen Kane", 1941, "Orson Welles")]})
    monkeypatch.setattr(
        "movie_brain.infrastructure.thumbprint_fetch.session_fetcher", lambda *a, **kw: (fetcher, None)
    )

    path = tmp_path / "cahiers-100.tsv"
    path.write_text("# slug: cahiers-100\n# name: Cahiers\n1\tCitizen Kane\tOrson Welles\n")

    r = runner.invoke(app, ["lists", "import", str(path), "--apply"])
    assert r.exit_code == 0, r.output
    assert repo.film_list("cahiers-100").trust == 1  # default, un-set

    r = runner.invoke(app, ["lists", "trust", "cahiers-100", "9"])
    assert r.exit_code == 0
    assert repo.film_list("cahiers-100").trust == 9

    # The re-import — same file, same slug — is the trap: `import_list` calls
    # `upsert_film_list` again on every run, e.g. to pick up newly created films.
    r = runner.invoke(app, ["lists", "import", str(path), "--apply"])
    assert r.exit_code == 0, r.output

    assert repo.film_list("cahiers-100").trust == 9


def test_lists_trust_no_args_on_an_empty_registry_says_so(tmp_path, monkeypatch):
    """Silence reads as a failure. The two slug branches already have this fallback; the
    no-argument branch did not, so an empty registry printed nothing at all."""
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["lists", "trust"])
    assert result.exit_code == 0, result.output
    assert "no lists registered" in result.output
