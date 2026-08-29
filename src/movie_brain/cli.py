from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from movie_brain.application.audit import run_audit
from movie_brain.application.export import write_csv
from movie_brain.application.legacy_import import import_legacy
from movie_brain.application.lists import create_films, import_list, scorecard
from movie_brain.application.metacritic import DEFAULT_TOP_N, MC_TOP_N_KEY, crawl_archive, match_archive
from movie_brain.application.owned import import_owned
from movie_brain.application.rematch import rematch
from movie_brain.application.repair import (
    DupGroup,
    EditionGroup,
    TwinGroup,
    load_edition_contract,
    load_expected_twins,
    repair_dupes,
    repair_editions,
    repair_links,
    repair_twins,
    repair_years,
)
from movie_brain.application.repair_keys import (
    DisagreementGroup,
    NomatchGroup,
    load_disagreement_contract,
    repair_disagreements,
    repair_nomatch,
)
from movie_brain.application.review import resolve_review
from movie_brain.application.sync import SOURCE, sync
from movie_brain.application.thumbprint import ReviewDetail, backfill_claims, parse_review_detail
from movie_brain.infrastructure.config import load_api_key, load_config, load_tmdb_token
from movie_brain.infrastructure.database import PendingMigrations, Repository, init_db, pending_migrations
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
lists_app = typer.Typer(help="Curated top-N lists: import a checked-in list file, create its missing films.")
app.add_typer(lists_app, name="lists")
repair_app = typer.Typer(help="Human-confirmed repairs: merge dupes, clear wrong TMDB links, fix years.")
app.add_typer(repair_app, name="repair")
review_app = typer.Typer(help="Resolve match_review anomalies: match to a film, create, or dismiss.")
app.add_typer(review_app, name="review")
thumbprint_app = typer.Typer(
    help="Thumbprint identity: claims backfill; the resolver is live in sync, owned import, and Mode-B promotion."
)
app.add_typer(thumbprint_app, name="thumbprint")
audit_app = typer.Typer(help="Data audit: read-only consistency checks; the human records verdicts in the dashboard.")
app.add_typer(audit_app, name="audit")
console = Console()
err = Console(stderr=True)

LEGACY_DEFAULT = Path.home() / ".local" / "share" / "criterion-ratings"


def _plain(msg: str) -> None:
    """stderr log without Rich markup: `[twin]` is a verdict tag, not a style."""
    err.print(msg, markup=False, highlight=False)


def _repo() -> Repository:
    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    try:
        return Repository(cfg.db_path)
    except PendingMigrations as exc:
        err.print(str(exc))
        raise typer.Exit(2) from exc


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
        f"availability refreshed: {result.tmdb_refreshed} · promoted: {result.mc_promoted} · "
        f"keyed: {result.tmdb_matched} · review: {result.tmdb_reviewed}"
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


@app.command("migrate")
def migrate_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Apply pending migrations (backs up first).")] = False,
) -> None:
    """The ONLY path that advances an existing DB's schema; without --apply it just lists what is pending."""
    cfg = load_config()
    pending = pending_migrations(cfg.db_path)
    if not pending:
        console.print("schema up to date")
        return
    for name in pending:
        console.print(f"pending: {name}")
    if not apply:
        console.print("dry run — re-run with --apply to migrate (a backup lands in backups/ first)")
        return
    init_db(cfg.db_path, apply=True)
    console.print(f"applied {len(pending)} migration(s)")


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
    """Export the Apple TV library via AppleScript and mark/create owned films.

    Each raw title is resolved through the thumbprint algorithm first, so an edition
    already held by an existing film (e.g. a "(The Final Cut)" import of a film already
    keyed under its own title) lands on that film instead of minting a twin."""
    from movie_brain.infrastructure.omdb import OmdbClient
    from movie_brain.infrastructure.thumbprint_fetch import session_fetcher

    cfg = load_config()
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    token, key = load_tmdb_token(cfg), load_api_key(cfg)
    tmdb = TmdbClient(token) if token else None
    fetcher, cache = session_fetcher(cfg.config_dir, tmdb, OmdbClient(key) if key else None)
    try:
        report = import_owned(_repo(), cfg.config_dir, date.today(), fetcher=fetcher, tmdb=tmdb)
    finally:
        if cache is not None:
            cache.save()  # the session cache, never the fixture
    console.print(
        f"owned: {report.total} · matched: {report.matched} · created: {report.created} · "
        f"already: {report.already_owned} · review: {report.review_open} · "
        f"resolved: {report.resolved_to_existing} · keyed: {report.keyed}"
    )
    raise typer.Exit(report.exit_code)


@lists_app.command("import")
def lists_import_cmd(
    path: Annotated[Path, typer.Argument(help="Path to the checked-in list file (e.g. lists/cahiers-100.tsv).")],
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Write the registry row, entries, claims and review rows (default: dry-run)."),
    ] = False,
) -> None:
    """Parse a checked-in list file and link its entries to films the catalog already holds.

    Never creates a film on any path — `lists create` is the separate, confirmed step for that."""
    from movie_brain.infrastructure.listfile import ListFileError, read_list_file
    from movie_brain.infrastructure.omdb import OmdbClient
    from movie_brain.infrastructure.thumbprint_fetch import session_fetcher

    try:
        parsed = read_list_file(path)
    except (ListFileError, OSError) as exc:
        err.print(str(exc))
        raise typer.Exit(2) from exc

    repo = _repo()  # outside the try below: typer.Exit subclasses RuntimeError, so the migrate guard would be swallowed
    cfg = load_config()
    token, key = load_tmdb_token(cfg), load_api_key(cfg)
    tmdb = TmdbClient(token) if token else None
    fetcher, cache = session_fetcher(cfg.config_dir, tmdb, OmdbClient(key) if key else None)
    if fetcher is None or tmdb is None:
        # Both are hard requirements here (session_fetcher needs both to build a fetcher at
        # all), unlike sync's OMDb-only fallback — and a caller silently forgetting `tmdb`
        # would disable gate 2b, so this is one accurate message for both failure shapes.
        err.print(
            f"no OMDb key and/or TMDB token: set OMDB_API_KEY/{cfg.key_file} and "
            f"MOVIE_BRAIN_TMDB_TOKEN/{cfg.tmdb_token_file}"
        )
        raise typer.Exit(2)
    try:
        report = import_list(
            repo, parsed.meta, parsed.entries, date.today(), fetcher=fetcher, tmdb=tmdb, apply=apply, log=_plain
        )
    finally:
        if cache is not None:
            cache.save()  # the session cache, never the fixture
    # markup=False: a resolver reason in [brackets] is text, not Rich markup. soft_wrap=True:
    # the scorecard is read as a file as often as on a terminal, and an 80-column wrap would
    # break the two-line-per-entry block the owner scans.
    console.print(scorecard(report.rows), markup=False, highlight=False, soft_wrap=True)
    raise typer.Exit(report.exit_code)


@lists_app.command("create")
def lists_create_cmd(
    slug: Annotated[str, typer.Argument(help="Slug of an already-imported list (see `lists import`).")],
    apply: Annotated[
        bool, typer.Option("--apply", help="Create, link and key the list's unresolved entries (default: dry-run).")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: skip the confirmation prompt.")] = False,
) -> None:
    """Create the films a list's still-unresolved entries would mint; re-resolves and re-gates every entry."""
    from movie_brain.infrastructure.omdb import OmdbClient
    from movie_brain.infrastructure.thumbprint_fetch import session_fetcher

    repo = _repo()  # outside the try below: typer.Exit subclasses RuntimeError, so the migrate guard would be swallowed
    cfg = load_config()
    token, key = load_tmdb_token(cfg), load_api_key(cfg)
    tmdb = TmdbClient(token) if token else None
    fetcher, cache = session_fetcher(cfg.config_dir, tmdb, OmdbClient(key) if key else None)
    if fetcher is None or tmdb is None:
        # Both are hard requirements here (session_fetcher needs both to build a fetcher at
        # all) — and a caller silently forgetting `tmdb` would disable gate 2b, so this is one
        # accurate message for both failure shapes. Checked BEFORE the confirmation prompt: a
        # run that cannot happen must not first ask the owner to authorise it.
        err.print(
            f"no OMDb key and/or TMDB token: set OMDB_API_KEY/{cfg.key_file} and "
            f"MOVIE_BRAIN_TMDB_TOKEN/{cfg.tmdb_token_file}"
        )
        raise typer.Exit(2)
    if apply and not yes and not typer.confirm(f"create missing films for list {slug!r}?", default=False):
        raise typer.Exit(0)
    try:
        report = create_films(repo, slug, date.today(), fetcher=fetcher, tmdb=tmdb, apply=apply, log=_plain)
    finally:
        if cache is not None:
            cache.save()  # the session cache, never the fixture
    # markup=False: a resolver reason in [brackets] is text, not Rich markup. soft_wrap=True:
    # the scorecard is read as a file as often as on a terminal, and an 80-column wrap would
    # break the two-line-per-entry block the owner scans.
    console.print(scorecard(report.rows), markup=False, highlight=False, soft_wrap=True)
    raise typer.Exit(report.exit_code)


@lists_app.command("trust")
def lists_trust_cmd(
    slug: Annotated[str | None, typer.Argument(help="List slug (e.g. cahiers-100); omit to show every list.")] = None,
    n: Annotated[int | None, typer.Argument(min=0, help="New trust; 0 is legal (visible, scores nothing).")] = None,
) -> None:
    """Show every list's trust, show one list's trust, or set one list's trust (the cross-list
    tally's weight).

    Nothing but this verb writes `film_list.trust` — `lists import` never touches it, so
    re-importing a list can't reset the owner's judgement of it."""
    repo = _repo()
    if slug is None:
        for m in repo.film_lists():
            console.print(f"{m.slug:<24} trust {m.trust}   {m.name}")
        return
    if n is None:
        meta = repo.film_list(slug)
        if meta is None:
            known = ", ".join(m.slug for m in repo.film_lists()) or "no lists registered"
            err.print(f"unknown list {slug!r} — known lists: {known}")
            raise typer.Exit(2)
        console.print(f"{meta.slug:<24} trust {meta.trust}   {meta.name}")
        return
    if not repo.set_list_trust(slug, n):
        known = ", ".join(m.slug for m in repo.film_lists()) or "no lists registered"
        err.print(f"unknown list {slug!r} — known lists: {known}")
        raise typer.Exit(2)
    console.print(f"{slug}: trust set to {n}")


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


@repair_app.command("dupes")
def repair_dupes_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Merge confirmed twin groups (default: dry-run).")] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="With --apply: confirm every twin group without prompting.")
    ] = False,
) -> None:
    """Audit duplicate films (norm-title groups + id-conflicts); merge twins after confirmation."""

    def confirm(g: DupGroup) -> bool:
        return yes or typer.confirm(f"merge {g.losers} into #{g.survivor}?", default=False)

    report = repair_dupes(_repo(), date.today(), apply=apply, confirm=confirm, log=err.print)
    console.print(
        f"groups: {report.groups} · twins: {report.twins} · distinct: {report.distinct} · "
        f"undecided: {report.undecided} · merged: {report.merged} · declined: {report.declined}"
    )


@repair_app.command("twins")
def repair_twins_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Merge/key confirmed groups (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every group without prompting.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Only the first N groups (batch size).")] = None,
) -> None:
    """Retire raw `Title (YYYY)` films into their same-year twin (contract-checked, one group at a time)."""
    from pathlib import Path

    eval_csv = Path(__file__).resolve().parents[2] / "scripts" / "eval" / "thumbprint_eval_v1.csv"
    expected = load_expected_twins(eval_csv)

    def confirm(g: TwinGroup) -> bool:
        target = f"→ #{g.twin_id}" if g.verdict == "twin" else f"key directly as imdb {g.imdb_id}"
        return yes or typer.confirm(f"#{g.raw_id} {g.raw_title!r} {target}?", default=False)

    def ratify(g: TwinGroup) -> None:
        if not eval_csv.exists() or g.verdict != "twin":
            return
        with eval_csv.open(encoding="utf-8") as f:
            if any(r["film_id"] == str(g.raw_id) and r["source"] == "apple" for r in csv.DictReader(f)):
                return
        with eval_csv.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f, lineterminator="\n").writerow(
                [
                    "B-apple-year-title",
                    g.raw_id,
                    "apple",
                    g.raw_title,
                    g.embedded_year,
                    g.imdb_id or "",
                    "",
                    "human",
                    f"twin {g.twin_id}",
                    "verified",
                    "",
                    "",
                ]
            )

    report = repair_twins(
        _repo(),
        date.today(),
        apply=apply,
        confirm=confirm,
        expected=expected,
        on_applied=ratify,
        limit=limit,
        log=_plain,
    )
    console.print(
        f"groups: {report.groups} · twin: {report.twins} · no-twin: {report.no_twin} · conflict: {report.conflict} · "
        f"csv-mismatch: {report.csv_mismatch} · applied: {report.applied} · declined: {report.declined}"
    )


@repair_app.command("editions")
def repair_editions_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Merge/key confirmed groups (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every group without prompting.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Only the first N groups (batch size).")] = None,
) -> None:
    """Fold edition-year films into their work (eval group C is the contract); old year → claim.edition_year."""
    from pathlib import Path

    eval_csv = Path(__file__).resolve().parents[2] / "scripts" / "eval" / "thumbprint_eval_v1.csv"
    contract = load_edition_contract(eval_csv)

    def confirm(g: EditionGroup) -> bool:
        target = f"merge → #{g.twin_id}" if g.verdict == "twin" else f"become {g.work_title!r} ({g.work_year})"
        return yes or typer.confirm(f"#{g.film_id} {g.title!r} {target}?", default=False)

    repo = _repo()  # outside the try: typer.Exit subclasses RuntimeError, so the migrate guard would be swallowed
    try:
        report = repair_editions(
            repo, date.today(), apply=apply, confirm=confirm, contract=contract, limit=limit, log=_plain
        )
    except RuntimeError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(
        f"groups: {report.groups} · twin: {report.twins} · no-twin: {report.no_twin} · conflict: {report.conflict} · "
        f"csv-mismatch: {report.csv_mismatch} · applied: {report.applied} · declined: {report.declined}"
    )


@repair_app.command("disagreements")
def repair_disagreements_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Act on confirmed groups (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every group without prompting.")] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Batch size over the actionable groups only.")
    ] = None,
) -> None:
    """Repair films whose OMDb imdbID ≠ TMDB imdb_id from eval group D (verified rows applied,
    proposed rows → A/B/C review). Already-repaired films list as pending / review-open and
    spend none of --limit, so repeated batches advance."""
    from movie_brain.infrastructure.omdb import OmdbClient
    from movie_brain.infrastructure.thumbprint_fetch import CandidateCache, CandidateFetcher

    root = Path(__file__).resolve().parents[2]
    contract = load_disagreement_contract(root / "scripts" / "eval" / "thumbprint_eval_v1.csv")
    # outside the try below: typer.Exit subclasses RuntimeError, so the migrate guard would be
    # swallowed there — and a behind DB should fail before the candidate cache is loaded.
    repo = _repo()
    cfg = load_config()
    token, key = load_tmdb_token(cfg), load_api_key(cfg)
    tmdb = TmdbClient(token) if token else None
    fetcher = None
    if tmdb is not None and key:
        # fixture hits are free; misses hit the live clients; NOTHING is saved back (path=None)
        data = CandidateCache.load(root / "scripts" / "eval" / "fixtures" / "cand_cache.json.gz", read_only=True).data
        fetcher = CandidateFetcher(CandidateCache(data, None), tmdb, OmdbClient(key))

    def confirm(g: DisagreementGroup) -> bool:
        prompt = f"#{g.film_id} {g.title!r} [{g.verdict}] → {g.expected_tt or 'review'}?"
        return yes or typer.confirm(prompt, default=False)

    try:
        report = repair_disagreements(
            repo, date.today(), apply=apply, confirm=confirm, contract=contract, tmdb=tmdb, fetcher=fetcher,
            limit=limit, log=_plain,
        )
    except RuntimeError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(
        f"groups: {report.groups} · refetch: {report.refetch} · relink: {report.relink} · adopt: {report.adopt} · "
        f"review: {report.review} · pending: {report.pending} · review-open: {report.review_open} · "
        f"conflict: {report.conflict} · applied: {report.applied} · declined: {report.declined}"
    )


@repair_app.command("nomatch")
def repair_nomatch_cmd(
    apply: Annotated[bool, typer.Option("--apply", help="Act on confirmed films (default: dry-run).")] = False,
    yes: Annotated[bool, typer.Option("--yes", help="With --apply: confirm every film without prompting.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", help="Batch size over the actionable films only.")] = None,
) -> None:
    """Rerun the open tmdb no-match films through the thumbprint resolver: auto matches are
    keyed, non-matches become durable A/B/C `no-match-reviewed` rows for `review resolve
    --pick/--tt/--none`. Candidates are cached per session in <config_dir>/nomatch-cache.json.gz
    (the eval fixture is never written)."""
    from movie_brain.infrastructure.omdb import OmdbClient
    from movie_brain.infrastructure.thumbprint_fetch import session_fetcher

    repo = _repo()
    cfg = load_config()
    token, key = load_tmdb_token(cfg), load_api_key(cfg)
    tmdb = TmdbClient(token) if token else None
    fetcher, cache = session_fetcher(cfg.config_dir, tmdb, OmdbClient(key) if key else None)

    def confirm(g: NomatchGroup) -> bool:
        prompt = f"#{g.film_id} {g.title!r} [{g.verdict}] → {g.tt or 'review'}?"
        return yes or typer.confirm(prompt, default=False)

    try:
        report = repair_nomatch(
            repo, date.today(), apply=apply, confirm=confirm, tmdb=tmdb, fetcher=fetcher, limit=limit, log=_plain
        )
    except RuntimeError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    finally:
        if cache is not None:
            cache.save()  # the session cache, never the fixture
    console.print(
        f"groups: {report.groups} · keyed: {report.keyed} · match: {report.match} · review: {report.review} · "
        f"unlinked: {report.unlinked} · linked: {report.linked} · review-open: {report.review_open} · "
        f"conflict: {report.conflict} · applied: {report.applied} · declined: {report.declined} · "
        f"skipped: {report.skipped}"
    )


@thumbprint_app.command("backfill")
def thumbprint_backfill_cmd(
    apply: Annotated[
        bool, typer.Option("--apply", help="Write the claim rows and title_norms (default: dry-run).")
    ] = False,
) -> None:
    """Copy owned / Criterion / Metacritic evidence into `claim` rows (pure copy, idempotent)."""
    cfg = load_config()
    r = backfill_claims(_repo(), cfg.config_dir, apply=apply, log=_plain)
    console.print(
        f"criterion: {r.criterion} · metacritic: {r.metacritic} · apple: {r.apple} "
        f"(unrecovered {r.apple_unrecovered}, twin-covered {r.apple_twin_covered}) · "
        f"editions: {r.editions} · title_norms filled: {r.title_norms}"
    )


@repair_app.command("links")
def repair_links_cmd(
    film: Annotated[
        int | None, typer.Option("--film", help="Audit/clear just this film's link (suspect regardless of title).")
    ] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Clear every suspect link (default: dry-run).")] = False,
) -> None:
    """Re-validate TMDB links by title (incl. alternative titles); suspects are listed, --apply clears them."""
    cfg = load_config()
    token = load_tmdb_token(cfg)
    if not token:
        err.print(f"no TMDB token: set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}")
        raise typer.Exit(2)
    try:
        report = repair_links(_repo(), TmdbClient(token), date.today(), film_id=film, apply=apply, log=err.print)
    except LookupError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"checked: {report.checked} · suspects: {report.suspects} · cleared: {report.cleared}")
    raise typer.Exit(report.exit_code)


@repair_app.command("years")
def repair_years_cmd(
    film_id: Annotated[int | None, typer.Argument(help="Film id to correct.")] = None,
    year: Annotated[int | None, typer.Argument(help="New original release year.")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Write the correction / mark stale OMDb rows.")] = False,
) -> None:
    """List the year worklist, or dry-run/apply one manual year correction."""
    try:
        report = repair_years(_repo(), date.today(), film_id=film_id, year=year, apply=apply, log=err.print)
    except (ValueError, LookupError) as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(
        f"open collisions: {report.collisions} · stale omdb: {report.stale} · refresh marked: {report.refresh_marked}"
        + (f" · changed: {report.changed}" if film_id is not None else "")
        + (f" · collided with film {report.collided_with}" if report.collided_with else "")
    )


@review_app.command("list")
def review_list(
    authority: Annotated[str | None, typer.Option("--authority", help="tmdb | metacritic | apple-tv")] = None,
    reason: Annotated[str | None, typer.Option("--reason", help="e.g. no-match, id-conflict, year-gap")] = None,
) -> None:
    """Show open match_review rows."""
    rows = _repo().list_reviews(authority, reason)
    table = Table(title=f"open reviews ({len(rows)})")
    for col in ("id", "authority", "reason", "film", "value", "detail"):
        table.add_column(col)
    parsed: dict[object, ReviewDetail] = {}
    for r in rows:
        kind = str(r["kind"] or "movie")
        film = f"#{r['film_id']} {r['title']} ({r['year']})" if r["film_id"] is not None else ""
        if film and kind != "movie":
            # A series is keyed by IMDb id alone — never offer it a tmdb id. The `\[` is rich's
            # markup escape: an unescaped "[series]" is read as a style tag and rendered as nothing.
            film += f" \\[{kind}]"
        detail = r["detail"]
        d = parse_review_detail(str(detail)) if detail is not None else None
        detail_cell = d.reason if d is not None else str(detail or "")
        if d is not None:
            parsed[r["id"]] = d
        table.add_row(str(r["id"]), str(r["authority"]), str(r["reason"]), film, str(r["value"] or ""), detail_cell)
    console.print(table)
    for rid, d in parsed.items():
        for c in d.candidates:
            console.print(
                f"  {rid} {c['letter']} {c['tt']} · {c['title']} ({c['year']}) · {c['director']} · "
                f"{c['runtime'] or '-'}m · {c['why_not'] or 'best'}"
            )


@review_app.command("revisits")
def review_revisits() -> None:
    """Films flagged 'needs revisit' in the drawer — the human worklist for repair/resolve."""
    rows = _repo().revisits()
    table = Table(title=f"needs revisit ({len(rows)})")
    for col in ("film", "title", "year", "marked", "note"):
        table.add_column(col)
    for fid, title, year, marked, note in rows:
        table.add_row(f"#{fid}", title, str(year or ""), marked, note or "")
    console.print(table)


@review_app.command("resolve")
def review_resolve(
    review_id: Annotated[int, typer.Argument(help="match_review id (see `review list`).")],
    film: Annotated[int | None, typer.Option("--film", help="Match to / merge into this film id.")] = None,
    tmdb_id: Annotated[int | None, typer.Option("--tmdb-id", help="Claim this TMDB id (tmdb no-match rows).")] = None,
    create: Annotated[bool, typer.Option("--create", help="Create a new film from the staged/owned title.")] = False,
    dismiss: Annotated[bool, typer.Option("--dismiss", help="Close the row; it is never re-queued.")] = False,
    pick: Annotated[
        str | None, typer.Option("--pick", help="Key the film to candidate A/B/C off the review detail.")
    ] = None,
    tt: Annotated[str | None, typer.Option("--tt", help="Key the film to this IMDb id (ranked or not).")] = None,
    none: Annotated[
        bool, typer.Option("--none", help="Standing 'no such work' verdict: verified unkeyed.")
    ] = False,
    series: Annotated[bool, typer.Option("--series", help="With --tt: this work is a series (IMDb id only).")] = False,
    note: Annotated[str | None, typer.Option("--note")] = None,
    eval_csv: Annotated[Path | None, typer.Option("--eval-csv", hidden=True)] = None,
) -> None:
    """Resolve one open review row."""
    token = load_tmdb_token(load_config())
    client = TmdbClient(token) if token else None
    if eval_csv is None:
        eval_csv = Path(__file__).resolve().parents[2] / "scripts" / "eval" / "thumbprint_eval_v1.csv"
    try:
        outcome = resolve_review(
            _repo(),
            review_id,
            today=date.today(),
            film_id=film,
            tmdb_id=tmdb_id,
            create=create,
            dismiss=dismiss,
            client=client,
            note=note,
            pick=pick,
            tt=tt,
            none=none,
            series=series,
            eval_csv=eval_csv,
            warn=err.print,
        )
    except ValueError as exc:
        err.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"review {review_id}: {outcome}")


@audit_app.command("run")
def audit_run(
    no_tmdb: Annotated[bool, typer.Option("--no-tmdb", help="Skip the TMDB facts fill; offline checks only.")] = False,
) -> None:
    """Score every film against cross-source consistency checks and replace audit_flags."""
    cfg = load_config()
    token = None if no_tmdb else load_tmdb_token(cfg)
    if not no_tmdb and not token:
        err.print(
            f"no TMDB token (set MOVIE_BRAIN_TMDB_TOKEN or write {cfg.tmdb_token_file}); running offline checks only"
        )
    client = TmdbClient(token) if token else None
    report = run_audit(_repo(), date.today(), tmdb=client)
    console.print(
        f"films: {report.films} · suspects: {report.suspects} · "
        f"tmdb facts fetched: {report.facts_fetched} · failed: {report.facts_failed}"
    )
    table = Table(title="flags by reason")
    table.add_column("reason")
    table.add_column("films", justify="right")
    for code, n in sorted(report.by_reason.items(), key=lambda kv: -kv[1]):
        table.add_row(code, str(n))
    console.print(table)
    top = Table(title=f"top {len(report.top)} suspects")
    for col in ("film", "title", "score", "reasons"):
        top.add_column(col)
    for fid, title, score, codes in report.top:
        top.add_row(f"#{fid}", title, str(score), ", ".join(codes))
    console.print(top)
    raise typer.Exit(report.exit_code)


@audit_app.command("verdicts")
def audit_verdicts(
    verdict: Annotated[str | None, typer.Option("--verdict", help="Only this verdict.")] = None,
) -> None:
    """Verdict history — the pattern-analysis export (oldest first)."""
    rows = _repo().verdict_history(verdict)
    table = Table(title=f"verdicts ({len(rows)})")
    for col in ("film", "title", "year", "verdict", "reasons", "note", "marked"):
        table.add_column(col)
    for fid, title, year, v, reasons, note, marked in rows:
        table.add_row(f"#{fid}", title, str(year or ""), v, reasons, note or "", marked)
    console.print(table)
