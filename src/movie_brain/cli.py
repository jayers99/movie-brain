from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from movie_brain.application.export import write_csv
from movie_brain.application.legacy_import import import_legacy
from movie_brain.application.metacritic import DEFAULT_TOP_N, MC_TOP_N_KEY, crawl_archive, match_archive
from movie_brain.application.owned import import_owned
from movie_brain.application.rematch import rematch
from movie_brain.application.sync import SOURCE, sync
from movie_brain.infrastructure.config import load_api_key, load_config, load_tmdb_token
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.metacritic import CARDS_PER_PAGE, archive_dir, archived_pages
from movie_brain.infrastructure.notify import notify
from movie_brain.infrastructure.tmdb import TmdbClient

app = typer.Typer(
    name="movie-brain", help="Personal film brain: Criterion listings, OMDb ratings, my ratings.", no_args_is_help=True
)
export_app = typer.Typer(help="Export data.")
app.add_typer(export_app, name="export")
metacritic_app = typer.Typer(help="Metacritic browse archive: crawl pages, match films.")
app.add_typer(metacritic_app, name="metacritic")
owned_app = typer.Typer(help="Apple TV owned films: import the library, mark ownership.")
app.add_typer(owned_app, name="owned")
console = Console()
err = Console(stderr=True)

LEGACY_DEFAULT = Path.home() / ".local" / "share" / "criterion-ratings"


def _repo() -> Repository:
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    return Repository(cfg.db_path)


@app.command("sync")
def sync_cmd(
    full: Annotated[bool, typer.Option("--full", help="Force a complete catalog re-walk.")] = False,
    ratings_only: Annotated[
        bool, typer.Option("--ratings-only", help="Skip Criterion; refresh OMDb ratings only.")
    ] = False,
) -> None:
    """Refresh the catalog and OMDb ratings."""
    if full and ratings_only:
        err.print("--full and --ratings-only are mutually exclusive")
        raise typer.Exit(2)
    cfg = load_config()
    api_key = load_api_key(cfg)
    if not api_key:
        err.print(f"no OMDb key: set OMDB_API_KEY or write {cfg.key_file}")
        raise typer.Exit(2)
    result = sync(
        _repo(),
        api_key,
        date.today(),
        force_full=full,
        ratings_only=ratings_only,
        tmdb_token=load_tmdb_token(cfg),
        config_dir=cfg.config_dir,
        notifier=notify,
    )
    console.print(
        f"films: {result.films} · looked up: {result.looked_up} · full walk: {result.full_walk} · "
        f"tmdb matched: {result.tmdb_matched} · availability refreshed: {result.tmdb_refreshed} · "
        f"promoted: {result.mc_promoted}"
    )
    raise typer.Exit(result.exit_code)


@app.command()
def dashboard(
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 5556,
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
) -> None:
    """Run the local web dashboard."""
    from movie_brain.web.app import create_app

    console.print(f"movie-brain dashboard → http://{host}:{port}")
    create_app(_repo()).run(host=host, port=port, debug=False)


@app.command("import-legacy")
def import_legacy_cmd(
    from_dir: Annotated[Path, typer.Option("--from", help="criterion-ratings data dir.")] = LEGACY_DEFAULT,
) -> None:
    """One-shot import of criterion-ratings JSON data (idempotent)."""
    try:
        report = import_legacy(_repo(), from_dir, date.today())
    except FileNotFoundError as exc:
        err.print(f"missing {exc}")
        raise typer.Exit(1) from exc
    console.print(
        f"films: {report.films} · omdb: {report.omdb} · payloads: {report.payloads} · ratings: {report.ratings}"
    )
    if report.unmatched_keys:
        console.print(f"unmatched keys ({len(report.unmatched_keys)}): " + ", ".join(report.unmatched_keys))


@export_app.command("csv")
def export_csv(path: Annotated[Path, typer.Argument(help="Output CSV path.")]) -> None:
    """Write the watchlist as CSV."""
    n = write_csv(_repo(), path)
    console.print(f"wrote {n} rows to {path}")


@app.command()
def status() -> None:
    """Show counts."""
    s = _repo().summary(SOURCE)
    table = Table(title="movie-brain")
    table.add_column("metric")
    table.add_column("count", justify="right")
    for k, v in s.items():
        table.add_row(k, str(v))
    console.print(table)


@metacritic_app.command("crawl")
def metacritic_crawl(
    pages: Annotated[
        int, typer.Option("--pages", help="Target page count for the archive; already-archived pages are skipped.")
    ] = 10,
) -> None:
    """Politely walk Metacritic's score-sorted browse pages into the local raw archive."""
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    report = crawl_archive(cfg.config_dir, pages)
    console.print(f"fetched: {report.fetched} · skipped: {report.skipped} · archived: {report.archived} pages")
    raise typer.Exit(report.exit_code)


@metacritic_app.command("match")
def metacritic_match() -> None:
    """Match archived Metacritic titles to films (offline, re-runnable) and report coverage."""
    report = match_archive(_repo(), load_config().config_dir, date.today())
    if report.exit_code != 0:
        raise typer.Exit(report.exit_code)
    pct = 100 * report.matched / report.films if report.films else 0.0
    console.print(f"archive: {report.pages} pages · {report.titles} titles · score floor {report.floor}")
    console.print(f"matched: {report.matched}/{report.films} films ({pct:.1f}%)")
    console.print(f"expected-but-missed: {report.expected_missed} → review queue")
    console.print(f"review queue: {report.review_open} open")
    console.print(f"below floor / unscored: {report.unmatched - report.expected_missed}")
    raise typer.Exit(0)


@metacritic_app.command("dial")
def metacritic_dial(
    n: Annotated[int | None, typer.Argument(min=1, help="New top-N; omit to show the current dial.")] = None,
) -> None:
    """Show or set N, the Mode-B discovery dial (promotion runs in the nightly sync)."""
    repo = _repo()
    if n is None:
        current = int(repo.get_meta(MC_TOP_N_KEY) or DEFAULT_TOP_N)
        pages = len(archived_pages(archive_dir(load_config().config_dir)))
        staged = repo.staged_title_count()
        console.print(f"top-N: {current} · archive: {pages} pages · staged titles: {staged}")
        if staged < current:
            need = -(-current // CARDS_PER_PAGE)
            console.print(f"archive may be short — run: movie-brain metacritic crawl --pages {need}")
        return
    repo.set_meta(MC_TOP_N_KEY, str(n))
    console.print(f"top-N set to {n} — applied on the next sync")


@owned_app.command("import")
def owned_import() -> None:
    """Export the Apple TV library via AppleScript and mark/create owned films."""
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    report = import_owned(_repo(), cfg.config_dir, date.today())
    console.print(
        f"owned: {report.total} · matched: {report.matched} · created: {report.created} · "
        f"already: {report.already_owned} · review: {report.review_open}"
    )
    raise typer.Exit(report.exit_code)


@app.command("rematch")
def rematch_cmd() -> None:
    """One-shot repair: rematch TMDB misses, reconcile non-Criterion years (idempotent)."""
    cfg = load_config()
    token = load_tmdb_token(cfg)
    if not token:
        err.print(f"no TMDB token: set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}")
        raise typer.Exit(2)
    report = rematch(_repo(), TmdbClient(token), date.today())
    console.print(
        f"misses: {report.misses} · rematched: {report.rematched} · still missed: {report.still_missed} · "
        f"id conflicts: {report.id_conflicts}"
    )
    console.print(
        f"year-checked: {report.checked} · adopted: {report.years_adopted} · "
        f"collisions queued: {report.collisions_queued}"
    )
    console.print(f"audit: {report.uncorrected} uncorrected non-criterion year mismatches outside the merge queue")
    raise typer.Exit(report.exit_code)
