from __future__ import annotations

import json
import re
import sqlite3
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from movie_brain.domain.audit import VERDICTS, AuditFlag, AuditSubject
from movie_brain.domain.filters import NEW_ARRIVAL_DAYS
from movie_brain.domain.models import Film, FilmView, McTitle, OmdbRating, ReviewEntry, film_key
from movie_brain.domain.thumbprint import title_norm

MISS_RETRY_DAYS = 30
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
TMDB_REFRESH_STAMP = "tmdb_providers_refreshed_at"

_RUNTIME_MIN = re.compile(r"(\d+)\s*min")


class FilmRow(NamedTuple):
    """One film's matching evidence: read-time COALESCE of films + omdb payload."""

    id: int
    title: str
    year: int | None
    director: str | None
    runtime_min: int | None
    omdb_mc: int | None


@dataclass(frozen=True)
class TmdbFactsRow:
    tmdb_id: int
    imdb_id: str | None
    title: str
    original_title: str
    alt_titles: tuple[str, ...]
    release_year: int | None
    runtime_min: int | None


class TmdbMatchTarget(NamedTuple):
    """One film awaiting a TMDB match, with the policy bit the wrapper needs."""

    film_id: int
    title: str
    year: int | None
    commerce: bool  # no criterion listing → commerce-created; year is COMMERCE band


class MergeReport(NamedTuple):
    moved: dict[str, int]
    dropped: dict[str, int]
    reviews_resolved: int


class ClaimRow(NamedTuple):
    id: int
    film_id: int
    authority: str
    value: str
    title_ingested: str
    year_claimed: int | None
    edition_label: str | None
    edition_year: int | None
    runtime_min: int | None
    first_seen: str


class EditionFilm(NamedTuple):
    """One undisposed film with its tmdb/imdb external ids, for the editions resolver."""

    id: int
    title: str
    year: int | None
    title_norm: str | None
    tmdb_id: str | None
    imdb_id: str | None


class TwinFilm(NamedTuple):
    """One undisposed film's twin-audit evidence (repair twins)."""

    id: int
    title: str
    year: int | None
    omdb_imdb: str | None  # OMDb payload imdbID (by-title stub or by-id record)
    tmdb_imdb: str | None  # external_ids imdb, else tmdb_facts.imdb_id
    tmdb_id: str | None


class RepairFilm(NamedTuple):
    """One non-dispositioned film's repair-audit evidence."""

    id: int
    title: str
    year: int | None
    tmdb: str | None
    criterion: bool
    rated: bool
    owned: bool
    watchlisted: bool
    omdb_found: bool


_ONE_ROW_TABLES = ("omdb", "tmdb", "my_ratings", "watchlist", "owned")  # film_id PRIMARY KEY tables


_TMDB_TARGET_SELECT = (
    "SELECT f.id, f.title, f.year, "
    "NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') AS commerce "
    "FROM films f "
)

# A dispositioned film (tombstoned or merged-away) has no row of its own in any read model:
# tombstoned films are hidden outright, merged losers are aliased onto their survivor
# (films_for_matching) rather than surfaced under their own id.
_NOT_DISPOSED = "NOT EXISTS (SELECT 1 FROM film_disposition d WHERE d.film_id = f.id)"

# One id per film for identity authorities; claim authorities may repeat (migration 012).
KEY_AUTHORITIES: frozenset[str] = frozenset({"tmdb", "imdb"})


class PendingMigrations(RuntimeError):
    """An existing DB is behind the checked-in migrations; only `migrate --apply` may advance it."""

    def __init__(self, pending: list[str]) -> None:
        self.pending = pending
        super().__init__("pending migrations: " + ", ".join(pending) + " — run 'movie-brain migrate --apply'")


def _applied_versions(conn: sqlite3.Connection) -> set[int] | None:
    """Applied schema versions, or None when the DB has never been initialised."""
    has_versions = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not has_versions:
        return None
    return {int(r[0]) for r in conn.execute("SELECT version FROM schema_version")}


def _pending_files(applied: set[int]) -> list[Path]:
    return [m for m in sorted(MIGRATIONS_DIR.glob("*.sql")) if int(m.name.split("_")[0]) not in applied]


def pending_migrations(db_path: Path) -> list[str]:
    """Migration file names an existing DB still lacks (empty for a fresh or current DB)."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        applied = _applied_versions(conn)
        return [] if applied is None else [m.name for m in _pending_files(applied)]
    finally:
        conn.close()


def init_db(db_path: Path, *, apply: bool = False) -> None:
    """Create a fresh DB in full, or bring an existing one up to date ONLY when `apply` is set.

    Creation is not migration: a DB with no `schema_version` table (first run, tests, a
    scratch copy) bootstraps regardless. An existing DB behind the checked-in migrations
    raises `PendingMigrations` so no ordinary verb can advance the live schema as a side
    effect of merely opening the repository (a T2 subagent did exactly that)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        applied = _applied_versions(conn)
        pending = _pending_files(applied or set())
        if applied is not None and pending and not apply:
            raise PendingMigrations([m.name for m in pending])
        if pending and applied:
            _backup_pre_migration(conn, db_path, max(applied))
        for mig in pending:
            conn.executescript(mig.read_text())
        conn.commit()
    finally:
        conn.close()


def _backup_pre_migration(conn: sqlite3.Connection, db_path: Path, current_version: int) -> None:
    """Snapshot the DB before new migrations touch it — the rollback point for a bad migration."""
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(exist_ok=True)
    dest_path = backups_dir / f"{db_path.stem}-v{current_version}-{date.today().isoformat()}.db"
    if dest_path.exists():
        # Never clobber an existing snapshot: if a prior migration attempt failed midway
        # (executescript is non-atomic), schema_version still reads the old version, and a
        # same-day re-run must not overwrite the good pre-migration backup with corrupted state.
        return
    dest = sqlite3.connect(dest_path)
    try:
        conn.backup(dest)
        dest.commit()
    finally:
        dest.close()


# One deterministic metacritic slug per film (earliest first_seen, then smallest value) — a
# film may hold several claim-authority `metacritic` external_ids (editions/rereleases), and
# these read models must not fan out into duplicate rows per film. `metacritic_claim_rows`
# is exempt: it must keep returning every slug.
_MC_SLUG_SQL = (
    "(SELECT e.film_id, e.value FROM external_ids e WHERE e.authority = 'metacritic' "
    " AND NOT EXISTS (SELECT 1 FROM external_ids e2 WHERE e2.film_id = e.film_id AND e2.authority = 'metacritic' "
    "   AND (e2.first_seen < e.first_seen OR (e2.first_seen = e.first_seen AND e2.value < e.value))))"
)


_VIEW_SQL = f"""
SELECT f.id, f.title, f.year,
       COALESCE(f.director, NULLIF(json_extract(o.payload, '$.Director'), 'N/A')) AS director,
       l.url, o.language, o.imdb, o.rt,
       COALESCE(mc.score, o.metacritic) AS metacritic, x.value AS mc_slug, o.found,
       (o.film_id IS NULL) AS pending, l.leaving_date, l.first_seen, r.score,
       COALESCE(l.last_seen < (SELECT MAX(last_seen) FROM listings WHERE source = l.source), 0) AS departed,
       (l.film_id IS NOT NULL) AS criterion
FROM films f
LEFT JOIN listings l ON l.film_id = f.id AND l.source = ?
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN my_ratings r ON r.film_id = f.id
LEFT JOIN {_MC_SLUG_SQL} x ON x.film_id = f.id
LEFT JOIN metacritic mc ON mc.slug = x.value
"""


_SERVICES_SQL = f"""
SELECT l.film_id, s.name, s.subscribed, s.kind FROM listings l
JOIN movie_service s ON s.slug = l.source
WHERE l.source != 'criterion'
  AND l.last_seen >= COALESCE(
      (SELECT value FROM meta WHERE key = '{TMDB_REFRESH_STAMP}'),
      (SELECT MAX(last_seen) FROM listings l2 WHERE l2.source = l.source))
ORDER BY l.film_id, s.subscribed DESC, s.kind DESC, s.name
"""


def _services_by_film(c: sqlite3.Connection) -> dict[int, list[dict[str, object]]]:
    out: dict[int, list[dict[str, object]]] = {}
    for r in c.execute(_SERVICES_SQL):
        out.setdefault(int(r["film_id"]), []).append(
            {"name": str(r["name"]), "subscribed": bool(r["subscribed"]), "kind": str(r["kind"])}
        )
    return out


_NEW_ON_SQL = """
SELECT t.film_id, t.source, s.name, MAX(t.appeared_on) AS appeared_on
FROM availability_transitions t
JOIN movie_service s ON s.slug = t.source AND s.kind = 'svod'
WHERE t.appeared_on >= ?
GROUP BY t.film_id, t.source
ORDER BY t.film_id, t.source
"""


def _new_on_by_film(c: sqlite3.Connection, cutoff_iso: str) -> dict[int, list[dict[str, object]]]:
    out: dict[int, list[dict[str, object]]] = {}
    for r in c.execute(_NEW_ON_SQL, (cutoff_iso,)):
        out.setdefault(int(r["film_id"]), []).append(
            {"source": str(r["source"]), "name": str(r["name"]), "appeared_on": str(r["appeared_on"])}
        )
    return out


def _watchlist_ids(c: sqlite3.Connection) -> set[int]:
    return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM watchlist")}


def _owned_ids(c: sqlite3.Connection) -> set[int]:
    return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM owned")}


def _revisit_by_film(c: sqlite3.Connection) -> dict[int, str | None]:
    return {int(r["film_id"]): r["note"] for r in c.execute("SELECT film_id, note FROM needs_revisit")}


def _audit_by_film(c: sqlite3.Connection) -> dict[int, tuple[dict[str, object] | None, dict[str, object] | None]]:
    """(audit, verdict) per film. `fine` suppresses audit only for the identical reason set."""
    flags: dict[int, list[dict[str, object]]] = {}
    scores: dict[int, int] = {}
    for r in c.execute("SELECT film_id, reason, detail, score FROM audit_flags ORDER BY film_id, reason"):
        fid = int(r["film_id"])
        flags.setdefault(fid, []).append({"code": str(r["reason"]), "detail": str(r["detail"])})
        scores[fid] = scores.get(fid, 0) + int(r["score"])
    latest: dict[int, dict[str, object]] = {}
    for r in c.execute(
        "SELECT v.film_id, v.verdict, v.reasons, v.note, v.marked_on FROM audit_verdict v "
        "WHERE v.id = (SELECT MAX(id) FROM audit_verdict WHERE film_id = v.film_id)"
    ):
        latest[int(r["film_id"])] = {
            "verdict": str(r["verdict"]),
            "reasons": str(r["reasons"]),
            "note": r["note"],
            "marked_on": str(r["marked_on"]),
        }
    out: dict[int, tuple[dict[str, object] | None, dict[str, object] | None]] = {}
    for fid in set(flags) | set(latest):
        audit: dict[str, object] | None = None
        if fid in flags:
            codes = ",".join(str(f["code"]) for f in flags[fid])
            v = latest.get(fid)
            if not (v and v["verdict"] == "fine" and v["reasons"] == codes):
                audit = {"score": scores[fid], "reasons": flags[fid]}
        out[fid] = (audit, latest.get(fid))
    return out


def _row_to_view(
    row: sqlite3.Row,
    services: list[dict[str, object]] | None = None,
    *,
    watchlisted: bool = False,
    new_on: list[dict[str, object]] | None = None,
    owned: bool = False,
    revisit: tuple[bool, str | None] = (False, None),
    audit: tuple[dict[str, object] | None, dict[str, object] | None] = (None, None),
) -> FilmView:
    return FilmView(
        id=row["id"],
        title=row["title"],
        year=row["year"],
        director=row["director"],
        url=row["url"],
        language=row["language"],
        imdb=row["imdb"],
        rt=row["rt"],
        metacritic=row["metacritic"],
        found=None if row["found"] is None else bool(row["found"]),
        pending=bool(row["pending"]),
        leaving_date=row["leaving_date"],
        first_seen=row["first_seen"],
        my_rating=row["score"],
        departed=bool(row["departed"]),
        metacritic_url=f"https://www.metacritic.com/movie/{row['mc_slug']}/" if row["mc_slug"] else None,
        services=services or [],
        watchlisted=watchlisted,
        new_on=new_on or [],
        criterion=bool(row["criterion"]),
        owned=owned,
        needs_revisit=revisit[0],
        revisit_note=revisit[1],
        audit=audit[0],
        verdict=audit[1],
    )


class Repository:
    def __init__(self, db_path: Path, *, migrate: bool = False) -> None:
        self.db_path = db_path
        init_db(db_path, apply=migrate)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # films / listings -------------------------------------------------
    def upsert_film(self, film: Film) -> int:
        with self._conn() as c:
            c.execute(
                "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, director=excluded.director",
                (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
            )
            row = c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()
            return int(row["id"])

    def film_id_by_key(self, key: str) -> int | None:
        with self._conn() as c:
            row = c.execute("SELECT id FROM films WHERE key = ?", (key,)).fetchone()
            return None if row is None else int(row["id"])

    def create_film(self, film: Film) -> int | None:
        """Insert a brand-new film (fresh guid) — never updates an existing row.

        Returns None on a key collision: promotion's tripwire, handled by the caller
        as a match_review entry, never an overwrite.
        """
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
            )
            if cur.rowcount == 0:
                return None
            return int(c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()["id"])

    def record_listing(self, film_id: int, source: str, url: str, seen: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO listings (film_id, source, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id, source) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen",
                (film_id, source, url, seen.isoformat(), seen.isoformat()),
            )

    @staticmethod
    def _write_listing(
        c: sqlite3.Connection, film_id: int, source: str, url: str, day: str, frontier: str | None
    ) -> bool:
        """Upsert one listing row; append an availability transition on insert or reappearance.

        frontier = the source's currency cutoff captured BEFORE this write batch began
        (per-source MAX(last_seen) for criterion, the tmdb refresh stamp for TMDB-fed
        sources). A row strictly older than it was displayed as departed, so going
        current again is a transition; None (fresh DB) means only true inserts fire.
        """
        row = c.execute("SELECT last_seen FROM listings WHERE film_id = ? AND source = ?", (film_id, source)).fetchone()
        is_transition = row is None or (frontier is not None and row["last_seen"] < frontier)
        c.execute(
            "INSERT INTO listings (film_id, source, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(film_id, source) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen",
            (film_id, source, url, day, day),
        )
        if is_transition:
            c.execute(
                "INSERT INTO availability_transitions (film_id, source, appeared_on) VALUES (?, ?, ?)",
                (film_id, source, day),
            )
        return is_transition

    def record_listing_with_transition(self, film_id: int, source: str, url: str, seen: date) -> bool:
        """Write one listing row, applying the TMDB refresh-stamp frontier for reappearance detection.

        For TMDB-fed sources only: criterion listings go through record_catalog, which uses
        the per-source MAX(last_seen) frontier instead.
        """
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (TMDB_REFRESH_STAMP,)).fetchone()
            frontier = None if row is None else str(row["value"])
            return self._write_listing(c, film_id, source, url, seen.isoformat(), frontier)

    def watchlist_transitions_on(self, day: date) -> list[tuple[str, str]]:
        with self._conn() as c:
            rows = c.execute(
                # svod only: a film becoming *purchasable* (apple-tv-store) is recorded
                # as a transition but is never an arrival worth alerting on.
                "SELECT f.title, s.name AS service "
                "FROM availability_transitions t "
                "JOIN watchlist w ON w.film_id = t.film_id "
                "JOIN films f ON f.id = t.film_id "
                "JOIN movie_service s ON s.slug = t.source AND s.kind = 'svod' "
                "WHERE t.appeared_on = ? ORDER BY t.id",
                (day.isoformat(),),
            ).fetchall()
            return [(str(r["title"]), str(r["service"])) for r in rows]

    def record_catalog(self, source: str, films: list[Film], seen: date) -> None:
        day = seen.isoformat()
        with self._conn() as c:
            # Currency frontier BEFORE any write: record_catalog runs on every sync and
            # re-stamps current rows, so comparing against a mid-batch MAX would misread
            # every untouched-yet row as a reappearance.
            row = c.execute("SELECT MAX(last_seen) AS m FROM listings WHERE source = ?", (source,)).fetchone()
            frontier = None if row["m"] is None else str(row["m"])
            # A merged loser's key can still show up on a fresh catalog walk (its listing
            # follows it to the survivor); a tombstoned film's own id is untouched — the
            # human hid it, so a reappearing listing stays hidden with it. Nothing is deleted.
            dispositions = {
                int(r["film_id"]): (str(r["kind"]), r["survivor_id"])
                for r in c.execute("SELECT film_id, kind, survivor_id FROM film_disposition")
            }
            for film in films:
                c.execute(
                    "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, "
                    "director=excluded.director",
                    (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
                )
                film_id = int(c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()["id"])
                while film_id in dispositions and dispositions[film_id][0] == "merged":
                    film_id = int(dispositions[film_id][1])  # alias → survivor (chains allowed)
                self._write_listing(c, film_id, source, film.url, day, frontier)
                try:
                    # A catalog source is a CLAIM authority (migration 012): extra rows are
                    # legal, so a changed URL is added, never UPDATEd over the film's existing
                    # row. The UPDATE this replaced collapsed every row a film held for the
                    # source onto one value — after 012 a merge survivor can hold two criterion
                    # URLs, and that collapse raised IntegrityError on every sync.
                    c.execute(
                        "INSERT INTO external_ids (film_id, authority, value, first_seen) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(film_id, authority, value) DO NOTHING",
                        (film_id, source, film.url, day),
                    )
                except sqlite3.IntegrityError:
                    # UNIQUE(authority, value): a second film (e.g. Criterion corrected its
                    # year, minting a new key) claims a URL another film already holds.
                    # Contain it here — the films + listings writes for this film must still
                    # land, and one bad conflict must never roll back the whole catalog walk.
                    print(
                        f"external id conflict for {film.key!r}: authority={source!r} value={film.url!r}",
                        file=sys.stderr,
                    )

    def set_leaving(self, source: str, leaving: dict[str, str]) -> None:
        with self._conn() as c:
            c.execute("UPDATE listings SET leaving_date = NULL WHERE source = ?", (source,))
            for key, label in leaving.items():
                c.execute(
                    "UPDATE listings SET leaving_date = ? WHERE source = ? "
                    "AND film_id = (SELECT id FROM films WHERE key = ?)",
                    (label, source, key),
                )

    def _current_rows(
        self,
        c: sqlite3.Connection,
        source: str,
        extra_where: str = "",
        params: tuple[object, ...] = (),
    ) -> list[sqlite3.Row]:
        sql = (
            "SELECT f.id, f.title, f.year, f.director, l.url FROM films f JOIN listings l ON l.film_id = f.id "
            "WHERE l.source = ? AND l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) "
            "AND " + _NOT_DISPOSED + " " + extra_where + " ORDER BY f.id"
        )
        return c.execute(sql, (source, source, *params)).fetchall()

    def current_films(self, source: str) -> list[tuple[int, Film]]:
        with self._conn() as c:
            return [
                (r["id"], Film(r["title"], r["year"], r["director"], r["url"])) for r in self._current_rows(c, source)
            ]

    # external ids / services ------------------------------------------
    def set_external_id(self, film_id: int, authority: str, value: str, seen: date) -> None:
        """Key authority (tmdb/imdb): replace this film's single row. Claim authority:
        add the row (no-op if this film already has it). Raises IntegrityError when another
        film holds (authority, value)."""
        with self._conn() as c:
            if authority in KEY_AUTHORITIES:
                c.execute(
                    "UPDATE external_ids SET value = ? WHERE film_id = ? AND authority = ? AND value != ?",
                    (value, film_id, authority, value),
                )
            c.execute(
                "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(film_id, authority, value) DO NOTHING",
                (film_id, authority, value, seen.isoformat()),
            )

    def external_ids_for(self, film_id: int) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute("SELECT authority, value FROM external_ids WHERE film_id = ?", (film_id,)).fetchall()
            return {str(r["authority"]): str(r["value"]) for r in rows}

    def external_ids_all(self, film_id: int) -> list[tuple[str, str]]:
        """Every (authority, value) row for this film, ordered — claim authorities may hold several."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT authority, value FROM external_ids WHERE film_id = ? ORDER BY authority, value", (film_id,)
            ).fetchall()
            return [(str(r["authority"]), str(r["value"])) for r in rows]

    def claimed_values(self, authority: str) -> set[str]:
        with self._conn() as c:
            rows = c.execute("SELECT value FROM external_ids WHERE authority = ?", (authority,)).fetchall()
            return {str(r["value"]) for r in rows}

    def external_id_holders(self, authority: str) -> dict[str, int]:
        """value → film id for one authority across EVERY film, disposed included. The
        `UNIQUE(authority, value)` guard and `key_work`'s refusal checks are blind to
        dispositions, so a pre-check built from live films only would miss a merged-away or
        tombstoned holder and promise a write that the DB then refuses."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT film_id, value FROM external_ids WHERE authority = ? ORDER BY film_id", (authority,)
            ).fetchall()
            return {str(r["value"]): int(r["film_id"]) for r in rows}

    def has_listing(self, film_id: int, source: str) -> bool:
        """This film carries a listing from `source` — the same subquery `_TMDB_TARGET_SELECT`
        negates for `commerce`. Departed counts: Criterion rotates titles back in, and a
        re-listing under a key we re-keyed away would mint a duplicate film."""
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM listings WHERE film_id = ? AND source = ? LIMIT 1", (film_id, source)
            ).fetchone()
            return row is not None

    def tmdb_facts_needed(self) -> list[tuple[int, int]]:
        """Linked films with no tmdb_facts row, or a row fetched for a different tmdb id."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT x.film_id, x.value FROM external_ids x JOIN films f ON f.id = x.film_id "
                "LEFT JOIN tmdb_facts t ON t.film_id = x.film_id "
                "WHERE x.authority = 'tmdb' AND (t.film_id IS NULL OR t.tmdb_id != CAST(x.value AS INTEGER)) "
                "AND " + _NOT_DISPOSED + " ORDER BY x.film_id"
            ).fetchall()
            return [(int(r["film_id"]), int(r["value"])) for r in rows]

    def upsert_tmdb_facts(self, film_id: int, facts: TmdbFactsRow, fetched_on: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO tmdb_facts (film_id, tmdb_id, imdb_id, title, original_title, alt_titles, "
                "release_year, runtime_min, fetched_on) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET tmdb_id=excluded.tmdb_id, imdb_id=excluded.imdb_id, "
                "title=excluded.title, original_title=excluded.original_title, alt_titles=excluded.alt_titles, "
                "release_year=excluded.release_year, runtime_min=excluded.runtime_min, fetched_on=excluded.fetched_on",
                (
                    film_id,
                    facts.tmdb_id,
                    facts.imdb_id,
                    facts.title,
                    facts.original_title,
                    json.dumps(list(facts.alt_titles)),
                    facts.release_year,
                    facts.runtime_min,
                    fetched_on.isoformat(),
                ),
            )

    # audit --------------------------------------------------------------
    def audit_subjects(self) -> list[AuditSubject]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, f.director, mc.score AS mc_score, o.found, "
                "json_extract(o.payload, '$.Title') AS o_title, json_extract(o.payload, '$.Year') AS o_year, "
                "json_extract(o.payload, '$.Director') AS o_dir, json_extract(o.payload, '$.Runtime') AS o_rt, "
                "json_extract(o.payload, '$.imdbID') AS o_imdb, json_extract(o.payload, '$.Type') AS o_type, "
                "json_extract(o.payload, '$.imdbRating') AS o_rating, json_extract(o.payload, '$.Metascore') AS o_ms, "
                "t.imdb_id AS t_imdb, t.title AS t_title, t.original_title AS t_orig, t.alt_titles AS t_alts, "
                "t.runtime_min AS t_rt "
                "FROM films f "
                "LEFT JOIN omdb o ON o.film_id = f.id AND o.found = 1 AND o.payload IS NOT NULL "
                f"LEFT JOIN {_MC_SLUG_SQL} x ON x.film_id = f.id "
                "LEFT JOIN metacritic mc ON mc.slug = x.value "
                "LEFT JOIN tmdb_facts t ON t.film_id = f.id "
                "WHERE " + _NOT_DISPOSED + " ORDER BY f.id"
            ).fetchall()
            by_imdb: dict[str, list[int]] = {}
            for r in rows:
                if r["o_imdb"]:
                    by_imdb.setdefault(str(r["o_imdb"]), []).append(int(r["id"]))
            out: list[AuditSubject] = []
            for r in rows:
                fid = int(r["id"])
                o_year = str(r["o_year"] or "")[:4]
                rt_m = _RUNTIME_MIN.match(str(r["o_rt"])) if r["o_rt"] else None
                ms = r["o_ms"]
                out.append(
                    AuditSubject(
                        film_id=fid,
                        title=str(r["title"]),
                        year=r["year"],
                        criterion_director=r["director"],
                        mc_score=r["mc_score"],
                        omdb_title=r["o_title"],
                        omdb_year=int(o_year) if o_year.isdigit() else None,
                        omdb_director=r["o_dir"],
                        omdb_runtime_min=int(rt_m.group(1)) if rt_m else None,
                        omdb_imdb_id=r["o_imdb"],
                        omdb_type=r["o_type"],
                        omdb_imdb_rating=r["o_rating"],
                        omdb_metascore=int(ms) if isinstance(ms, str) and ms.isdigit() else None,
                        tmdb_imdb_id=r["t_imdb"],
                        tmdb_title=r["t_title"],
                        tmdb_original_title=r["t_orig"],
                        tmdb_alt_titles=tuple(json.loads(r["t_alts"])) if r["t_alts"] else (),
                        tmdb_runtime_min=r["t_rt"],
                        shared_imdb_film_ids=tuple(i for i in by_imdb.get(str(r["o_imdb"] or ""), []) if i != fid),
                    )
                )
            return out

    def replace_audit_flags(self, flags: dict[int, list[AuditFlag]], run_on: date) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM audit_flags")
            c.executemany(
                "INSERT INTO audit_flags (film_id, reason, detail, score, run_on) VALUES (?, ?, ?, ?, ?)",
                [(fid, f.code, f.detail, f.score, run_on.isoformat()) for fid, fl in flags.items() for f in fl],
            )

    def current_reasons(self, film_id: int) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT reason FROM audit_flags WHERE film_id = ? ORDER BY reason", (film_id,)).fetchall()
            return [str(r["reason"]) for r in rows]

    def add_verdict(
        self, film_id: int, verdict: str, reasons: list[str], note: str | None, today: date
    ) -> dict[str, object] | None:
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}; expected one of {', '.join(VERDICTS)}")
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films f WHERE f.id = ? AND " + _NOT_DISPOSED, (film_id,)).fetchone() is None:
                return None
            joined = ",".join(sorted(reasons))
            c.execute(
                "INSERT INTO audit_verdict (film_id, verdict, reasons, note, marked_on) VALUES (?, ?, ?, ?, ?)",
                (film_id, verdict, joined, note, today.isoformat()),
            )
            return {"verdict": verdict, "reasons": joined, "note": note, "marked_on": today.isoformat()}

    def verdict_history(
        self, verdict: str | None = None
    ) -> list[tuple[int, str, int | None, str, str, str | None, str]]:
        with self._conn() as c:
            sql = (
                "SELECT v.film_id, f.title, f.year, v.verdict, v.reasons, v.note, v.marked_on "
                "FROM audit_verdict v JOIN films f ON f.id = v.film_id "
            )
            params: tuple[object, ...] = ()
            if verdict is not None:
                sql += "WHERE v.verdict = ? "
                params = (verdict,)
            rows = c.execute(sql + "ORDER BY v.id", params).fetchall()
            return [
                (
                    int(r["film_id"]),
                    str(r["title"]),
                    r["year"],
                    str(r["verdict"]),
                    str(r["reasons"]),
                    r["note"],
                    str(r["marked_on"]),
                )
                for r in rows
            ]

    def services(self) -> list[dict[str, object]]:
        with self._conn() as c:
            rows = c.execute("SELECT slug, name, kind, subscribed, region FROM movie_service ORDER BY slug").fetchall()
            return [dict(r) for r in rows]

    # metacritic -------------------------------------------------------
    def upsert_mc_titles(self, titles: list[McTitle], fetched_at: date) -> None:
        day = fetched_at.isoformat()
        with self._conn() as c:
            for t in titles:
                c.execute(
                    "INSERT INTO metacritic (slug, title, year, score, rank, page, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(slug) DO UPDATE SET title=excluded.title, year=excluded.year, "
                    "score=excluded.score, rank=excluded.rank, page=excluded.page, fetched_at=excluded.fetched_at",
                    (t.slug, t.title, t.year, t.score, t.rank, t.page, day),
                )

    def top_staged_titles(self, n: int) -> list[McTitle]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT slug, title, year, score, rank, page FROM metacritic WHERE rank <= ? ORDER BY rank",
                (n,),
            ).fetchall()
            return [
                McTitle(str(r["slug"]), str(r["title"]), r["year"], r["score"], int(r["rank"]), int(r["page"]))
                for r in rows
            ]

    def staged_title_count(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM metacritic").fetchone()[0])

    def films_for_matching(self) -> list[FilmRow]:
        with self._conn() as c:
            disposition_rows = c.execute("SELECT film_id, kind, survivor_id FROM film_disposition").fetchall()
            raw_survivor = {int(r["film_id"]): int(r["survivor_id"]) for r in disposition_rows if r["kind"] == "merged"}
            tombstoned = {int(r["film_id"]) for r in disposition_rows if r["kind"] == "tombstoned"}
            # Resolve every merged loser straight to its ULTIMATE survivor (chain-walk once,
            # in memory, from the single film_disposition read above) — record_catalog and
            # canonical_film_id already chain-walk; this read model must match them, or a
            # multi-hop merge (A -> B, then B -> C) would alias A's evidence under the
            # no-longer-canonical B instead of C.
            canonical: dict[int, int] = {}
            for loser in raw_survivor:
                fid = loser
                seen: set[int] = set()
                while fid in raw_survivor and fid not in seen:
                    seen.add(fid)
                    fid = raw_survivor[fid]
                canonical[loser] = fid

            rows = c.execute(
                "SELECT f.id, f.title, f.year, "
                "COALESCE(f.director, NULLIF(json_extract(o.payload, '$.Director'), 'N/A')) AS director, "
                "NULLIF(json_extract(o.payload, '$.Runtime'), 'N/A') AS runtime, "
                "o.metacritic "
                "FROM films f LEFT JOIN omdb o ON o.film_id = f.id ORDER BY f.id"
            ).fetchall()
            out = []
            for r in rows:
                film_id = int(r["id"])
                if film_id in tombstoned:
                    continue
                resolved_id = canonical.get(film_id, film_id)
                runtime_raw = r["runtime"]
                m = _RUNTIME_MIN.match(runtime_raw) if runtime_raw else None
                runtime_min = int(m.group(1)) if m else None
                out.append(
                    FilmRow(resolved_id, str(r["title"]), r["year"], r["director"], runtime_min, r["metacritic"])
                )
            return out

    def films_for_repair(self) -> list[RepairFilm]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value AS tmdb, "
                "EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') AS criterion, "
                "EXISTS (SELECT 1 FROM my_ratings r WHERE r.film_id = f.id) AS rated, "
                "EXISTS (SELECT 1 FROM owned w WHERE w.film_id = f.id) AS owned, "
                "EXISTS (SELECT 1 FROM watchlist w WHERE w.film_id = f.id) AS watchlisted, "
                "COALESCE((SELECT o.found FROM omdb o WHERE o.film_id = f.id), 0) AS omdb_found "
                "FROM films f LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
                "WHERE " + _NOT_DISPOSED + " ORDER BY f.id"
            ).fetchall()
            return [
                RepairFilm(
                    int(r["id"]),
                    str(r["title"]),
                    r["year"],
                    r["tmdb"],
                    bool(r["criterion"]),
                    bool(r["rated"]),
                    bool(r["owned"]),
                    bool(r["watchlisted"]),
                    bool(r["omdb_found"]),
                )
                for r in rows
            ]

    def film_ids_with_external(self, authority: str) -> set[int]:
        with self._conn() as c:
            rows = c.execute("SELECT film_id FROM external_ids WHERE authority = ?", (authority,)).fetchall()
            return {int(r["film_id"]) for r in rows}

    def replace_unresolved_reviews(
        self, authority: str, entries: list[ReviewEntry], created: date, *, reason: str | None = None
    ) -> None:
        # Derived state, recomputed per match run — the immutability rule binds films, not
        # this queue. reason scopes the replace so recomputing one reason's rows (tmdb
        # no-match) can't wipe durable rows queued under the same authority (year-collision).
        with self._conn() as c:
            if reason is None:
                c.execute("DELETE FROM match_review WHERE authority = ? AND resolved = 0", (authority,))
            else:
                c.execute(
                    "DELETE FROM match_review WHERE authority = ? AND resolved = 0 AND reason = ?",
                    (authority, reason),
                )
            for e in entries:
                c.execute(
                    "INSERT INTO match_review (authority, film_id, value, reason, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (authority, e.film_id, e.value, e.reason, e.detail, created.isoformat()),
                )

    def append_reviews(self, authority: str, entries: list[ReviewEntry], created: date) -> None:
        with self._conn() as c:
            for e in entries:
                c.execute(
                    "INSERT INTO match_review (authority, film_id, value, reason, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (authority, e.film_id, e.value, e.reason, e.detail, created.isoformat()),
                )

    def open_reviews(self, authority: str) -> list[dict[str, object]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, film_id, value, reason, detail, created_at FROM match_review "
                "WHERE authority = ? AND resolved = 0 ORDER BY id",
                (authority,),
            ).fetchall()
            return [dict(r) for r in rows]

    def review(self, review_id: int) -> dict[str, object] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM match_review WHERE id = ?", (review_id,)).fetchone()
            return None if row is None else dict(row)

    def list_reviews(self, authority: str | None = None, reason: str | None = None) -> list[dict[str, object]]:
        where = ["m.resolved = 0"]
        params: list[object] = []
        if authority:
            where.append("m.authority = ?")
            params.append(authority)
        if reason:
            where.append("m.reason = ?")
            params.append(reason)
        with self._conn() as c:
            rows = c.execute(
                "SELECT m.id, m.authority, m.film_id, m.value, m.reason, m.detail, m.created_at, "
                "f.title, f.year FROM match_review m LEFT JOIN films f ON f.id = m.film_id "
                "WHERE " + " AND ".join(where) + " ORDER BY m.authority, m.reason, m.id",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_review(self, review_id: int, note: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE match_review SET resolved = 1, detail = COALESCE(detail, '') || ? WHERE id = ?",
                (f" [{note}]", review_id),
            )

    def resolved_review_keys(self, authority: str) -> set[tuple[str, int | None, str | None]]:
        """(reason, film_id, value) of every resolved row — a resolution is a standing decision."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT reason, film_id, value FROM match_review WHERE authority = ? AND resolved = 1", (authority,)
            ).fetchall()
            return {(str(r["reason"]), r["film_id"], r["value"]) for r in rows}

    def staged_title(self, slug: str) -> McTitle | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT slug, title, year, score, rank, page FROM metacritic WHERE slug = ?", (slug,)
            ).fetchone()
            return (
                None
                if r is None
                else McTitle(str(r["slug"]), str(r["title"]), r["year"], r["score"], int(r["rank"]), int(r["page"]))
            )

    def tmdb_target(self, film_id: int) -> TmdbMatchTarget | None:
        # Mirrors films_needing_tmdb_match's _NOT_DISPOSED filter: a merged-away or
        # tombstoned film is never a valid tmdb match target.
        with self._conn() as c:
            r = c.execute(_TMDB_TARGET_SELECT + "WHERE f.id = ? AND " + _NOT_DISPOSED, (film_id,)).fetchone()
            return None if r is None else TmdbMatchTarget(int(r["id"]), str(r["title"]), r["year"], bool(r["commerce"]))

    # tmdb ---------------------------------------------------------------
    def films_needing_tmdb_match(self) -> list[TmdbMatchTarget]:
        with self._conn() as c:
            rows = c.execute(
                _TMDB_TARGET_SELECT
                + "WHERE "
                + _NOT_DISPOSED
                + " AND NOT EXISTS (SELECT 1 FROM tmdb t WHERE t.film_id = f.id) ORDER BY f.id"
            ).fetchall()
            return [TmdbMatchTarget(int(r["id"]), str(r["title"]), r["year"], bool(r["commerce"])) for r in rows]

    def films_tmdb_missed_targets(self) -> list[TmdbMatchTarget]:
        with self._conn() as c:
            rows = c.execute(
                _TMDB_TARGET_SELECT
                + "JOIN tmdb t ON t.film_id = f.id WHERE t.found = 0 AND "
                + _NOT_DISPOSED
                + " ORDER BY f.id"
            ).fetchall()
            return [TmdbMatchTarget(int(r["id"]), str(r["title"]), r["year"], bool(r["commerce"])) for r in rows]

    def films_with_tmdb(self) -> list[tuple[int, str, int | None, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value FROM films f "
                "JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
                "WHERE " + _NOT_DISPOSED + " ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], str(r["value"])) for r in rows]

    def clear_tmdb_link(self, film_id: int, today: date) -> None:
        """Human-confirmed repair only: drop a wrong TMDB link so the matcher can retry it."""
        with self._conn() as c:
            c.execute("DELETE FROM external_ids WHERE film_id = ? AND authority = 'tmdb'", (film_id,))
            c.execute(
                "INSERT INTO tmdb (film_id, found, looked_up) VALUES (?, 0, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET found = 0, looked_up = excluded.looked_up",
                (film_id, today.isoformat()),
            )

    def commerce_films_with_tmdb(self) -> list[tuple[int, str, int | None, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value FROM films f "
                "JOIN external_ids x ON x.film_id = f.id AND x.authority = 'tmdb' "
                "WHERE NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') "
                "AND " + _NOT_DISPOSED + " "
                "ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], str(r["value"])) for r in rows]

    def update_film_year(self, film_id: int, year: int) -> int | None:
        """Adopt an authority year: rewrite films.year and recompute key.

        Returns the id of the film whose identity already owns the recomputed
        key — the detected-twin case; the caller queues a year-collision review
        and this film stays untouched (never overwrite, collectors never delete).

        The one holder that does NOT block is this film's OWN merged-away loser:
        it was folded into *this* film, so its key is dead and belongs here. It
        is retired in place (suffixed with its own id, which is unique) and this
        film takes it. Without that, a merge would permanently block its own
        survivor from adopting the loser's year, since the loser's films row is
        deliberately never deleted.

        Every other holder blocks, and blocks under its CANONICAL id: a loser
        merged into some *other* survivor reports that survivor as the clash, so
        the review names the live identity a human would have to reconcile. A
        tombstoned holder blocks as itself — tombstoned_keys() is the guard that
        stops the ingesters re-creating it, and that guard IS the key.
        """
        with self._conn() as c:
            row = c.execute("SELECT title FROM films WHERE id = ?", (film_id,)).fetchone()
            if row is None:
                raise LookupError(f"unknown film {film_id}")
            new_key = film_key(str(row["title"]), year)
            # films.key is UNIQUE, so at most one other film can hold new_key.
            holder = c.execute("SELECT id FROM films WHERE key = ? AND id != ?", (new_key, film_id)).fetchone()
            if holder is not None:
                held_by = int(holder["id"])
                disposed = c.execute("SELECT 1 FROM film_disposition WHERE film_id = ?", (held_by,)).fetchone()
                if disposed is None:
                    return held_by  # a live film owns that key
                canonical = self._canonical_in(c, held_by)
                if canonical != film_id:
                    return canonical  # another identity owns it (tombstones report themselves)
                # This film's own merged-away loser: retire the dead key.
                c.execute("UPDATE films SET key = key || ' #' || id WHERE id = ?", (held_by,))
            c.execute("UPDATE films SET year = ?, key = ? WHERE id = ?", (year, new_key, film_id))
            return None

    def stale_omdb_years(self) -> list[tuple[int, str, int | None, int]]:
        """Non-Criterion films whose OMDb payload was fetched under a different year than films.year."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, CAST(substr(json_extract(o.payload, '$.Year'), 1, 4) AS INTEGER) AS oy "
                "FROM films f JOIN omdb o ON o.film_id = f.id "
                "WHERE o.payload IS NOT NULL AND o.needs_refresh = 0 AND " + _NOT_DISPOSED + " "
                "AND NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = 'criterion') "
                "AND json_extract(o.payload, '$.Year') GLOB '[0-9][0-9][0-9][0-9]*' "
                "AND oy IS NOT NULL AND oy != COALESCE(f.year, -1) ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], int(r["oy"])) for r in rows]

    def mark_omdb_refresh(self, film_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE omdb SET needs_refresh = 1 WHERE film_id = ?", (film_id,))

    def mark_omdb_refresh_if_missed(self, film_id: int) -> None:
        """Re-queue only a stale OMDb miss — a found row is left alone."""
        with self._conn() as c:
            c.execute("UPDATE omdb SET needs_refresh = 1 WHERE film_id = ? AND found = 0", (film_id,))

    def film_id_for_external(self, authority: str, value: str) -> int | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT film_id FROM external_ids WHERE authority = ? AND value = ?", (authority, value)
            ).fetchone()
            return None if row is None else int(row["film_id"])

    def upsert_tmdb(self, film_id: int, *, found: bool, looked_up: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO tmdb (film_id, found, looked_up) VALUES (?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET found=excluded.found, looked_up=excluded.looked_up",
                (film_id, int(found), looked_up.isoformat()),
            )

    def record_tmdb_providers(self, film_id: int, checked: date, payload: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE tmdb SET providers_checked_at = ?, payload = ? WHERE film_id = ?",
                (checked.isoformat(), payload, film_id),
            )

    def films_for_watchlist_refresh(self) -> list[tuple[int, str, bool]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value, (t.providers_checked_at IS NULL) AS first_check FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "JOIN watchlist w ON w.film_id = t.film_id "
                "WHERE t.found = 1 "
                "AND NOT EXISTS (SELECT 1 FROM film_disposition d WHERE d.film_id = t.film_id) "
                "ORDER BY t.film_id"
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"]), bool(r["first_check"])) for r in rows]

    def films_for_first_check(self, limit: int) -> list[tuple[int, str, bool]]:
        """Matched films whose providers have never been checked (first_check is always True)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "WHERE t.found = 1 AND t.providers_checked_at IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM film_disposition d WHERE d.film_id = t.film_id) "
                "ORDER BY t.film_id LIMIT ?",
                (limit,),
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"]), True) for r in rows]

    def films_for_provider_refresh(self, skip_checked_on: date | None = None) -> list[tuple[int, str, bool]]:
        where = "" if skip_checked_on is None else "AND COALESCE(t.providers_checked_at, '') != ? "
        params: tuple[object, ...] = () if skip_checked_on is None else (skip_checked_on.isoformat(),)
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value, (t.providers_checked_at IS NULL) AS first_check FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "WHERE t.found = 1 "
                "AND NOT EXISTS (SELECT 1 FROM film_disposition d WHERE d.film_id = t.film_id) "
                + where
                + "ORDER BY (t.providers_checked_at IS NOT NULL), "
                "t.providers_checked_at, t.film_id",
                params,
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"]), bool(r["first_check"])) for r in rows]

    def films_tmdb_missed(self) -> list[tuple[int, str, int | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year FROM films f JOIN tmdb t ON t.film_id = f.id "
                "WHERE t.found = 0 AND " + _NOT_DISPOSED + " ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"]) for r in rows]

    def provider_map(self) -> dict[int, str]:
        with self._conn() as c:
            rows = c.execute("SELECT tmdb_provider_id, service_slug FROM service_provider").fetchall()
            return {int(r["tmdb_provider_id"]): str(r["service_slug"]) for r in rows}

    # meta -------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # omdb -------------------------------------------------------------
    def films_needing_lookup(self, source: str, today: date) -> list[tuple[int, Film]]:
        cutoff = (today - timedelta(days=MISS_RETRY_DAYS)).isoformat()
        where = (
            "AND (NOT EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id) "
            "OR EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id AND "
            "(o.needs_refresh = 1 OR (o.found = 0 AND (o.year_fallback = 0 OR o.looked_up <= ?)))))"
        )
        with self._conn() as c:
            return [
                (r["id"], Film(r["title"], r["year"], r["director"], r["url"]))
                for r in self._current_rows(c, source, where, (cutoff,))
            ]

    def films_needing_lookup_discovery(self, source: str, today: date) -> list[tuple[int, Film]]:
        """Discovery films (no listing for `source`, i.e. never on Criterion) needing OMDb."""
        cutoff = (today - timedelta(days=MISS_RETRY_DAYS)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, x.value AS slug FROM films f "
                f"LEFT JOIN {_MC_SLUG_SQL} x ON x.film_id = f.id "
                "WHERE NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = ?) "
                "AND (NOT EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id) "
                "OR EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id AND "
                "(o.needs_refresh = 1 OR (o.found = 0 AND (o.year_fallback = 0 OR o.looked_up <= ?))))) "
                "AND " + _NOT_DISPOSED + " "
                "ORDER BY f.id",
                (source, cutoff),
            ).fetchall()
            return [
                (
                    int(r["id"]),
                    Film(
                        str(r["title"]),
                        r["year"],
                        None,
                        f"https://www.metacritic.com/movie/{r['slug']}/" if r["slug"] else "",
                    ),
                )
                for r in rows
            ]

    def upsert_omdb(
        self,
        film_id: int,
        rating: OmdbRating,
        looked_up: date,
        *,
        year_fallback: bool = True,
        needs_refresh: bool = False,
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO omdb "
                "(film_id, found, imdb, rt, metacritic, language, looked_up, year_fallback, needs_refresh, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET "
                "found=excluded.found, imdb=excluded.imdb, rt=excluded.rt, metacritic=excluded.metacritic, "
                "language=excluded.language, "
                "looked_up=excluded.looked_up, year_fallback=excluded.year_fallback, "
                "needs_refresh=excluded.needs_refresh, payload=COALESCE(excluded.payload, omdb.payload)",
                (
                    film_id,
                    int(rating.found),
                    rating.imdb,
                    rating.rt,
                    rating.metacritic,
                    rating.language,
                    looked_up.isoformat(),
                    int(year_fallback),
                    int(needs_refresh),
                    rating.payload,
                ),
            )

    # ratings ----------------------------------------------------------
    def set_rating(self, film_id: int, score: int | None, rated_at: date) -> bool:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return False
            if score is None:
                c.execute("DELETE FROM my_ratings WHERE film_id = ?", (film_id,))
            else:
                c.execute(
                    "INSERT INTO my_ratings (film_id, score, rated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(film_id) DO UPDATE SET score=excluded.score, rated_at=excluded.rated_at",
                    (film_id, score, rated_at.isoformat()),
                )
            return True

    def all_my_ratings(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT f.key, r.score FROM my_ratings r JOIN films f ON f.id = r.film_id").fetchall()
            return {str(r["key"]): int(r["score"]) for r in rows}

    # watchlist --------------------------------------------------------
    def toggle_watchlist(self, film_id: int, today: date) -> bool | None:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            if c.execute("SELECT 1 FROM watchlist WHERE film_id = ?", (film_id,)).fetchone() is None:
                c.execute("INSERT INTO watchlist (film_id, added_on) VALUES (?, ?)", (film_id, today.isoformat()))
                return True
            c.execute("DELETE FROM watchlist WHERE film_id = ?", (film_id,))
            return False

    def watchlist_film_ids(self) -> set[int]:
        with self._conn() as c:
            return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM watchlist")}

    # owned -------------------------------------------------------------
    def mark_owned(self, film_id: int, today: date, source: str = "apple-tv") -> bool:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO owned (film_id, source, first_imported) VALUES (?, ?, ?) ON CONFLICT(film_id) DO NOTHING",
                (film_id, source, today.isoformat()),
            )
            return cur.rowcount > 0

    def owned_film_ids(self) -> set[int]:
        with self._conn() as c:
            return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM owned")}

    # claims (thumbprint step 0) ---------------------------------------
    def add_claim(
        self,
        film_id: int,
        authority: str,
        value: str,
        title_ingested: str,
        *,
        year_claimed: int | None = None,
        edition_label: str | None = None,
        runtime_min: int | None = None,
        first_seen: str,
    ) -> bool:
        """INSERT OR IGNORE on UNIQUE(authority, value); False when the claim already exists."""
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO claim (film_id, authority, value, title_ingested, year_claimed, "
                "edition_label, runtime_min, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (film_id, authority, value, title_ingested, year_claimed, edition_label, runtime_min, first_seen),
            )
            return cur.rowcount > 0

    def claims_for_film(self, film_id: int) -> list[ClaimRow]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, film_id, authority, value, title_ingested, year_claimed, edition_label, edition_year, "
                "runtime_min, first_seen FROM claim WHERE film_id = ? ORDER BY id",
                (film_id,),
            ).fetchall()
            return [ClaimRow(*r) for r in rows]

    def claim_counts(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT authority, COUNT(*) AS n FROM claim GROUP BY authority").fetchall()
            return {str(r["authority"]): int(r["n"]) for r in rows}

    def set_title_norm(self, film_id: int, title_norm: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE films SET title_norm = ? WHERE id = ?", (title_norm, film_id))

    def films_missing_title_norm(self) -> list[tuple[int, str]]:
        with self._conn() as c:
            rows = c.execute(
                f"SELECT f.id, f.title FROM films f WHERE f.title_norm IS NULL AND {_NOT_DISPOSED} ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"])) for r in rows]

    def criterion_listing_rows(self) -> list[tuple[int, str, str, str, int | None]]:
        """(film_id, url, title, first_seen, year) for every undisposed film's Criterion listing."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, l.url, f.title, l.first_seen, f.year FROM listings l JOIN films f ON f.id = l.film_id "
                f"WHERE l.source = 'criterion' AND {_NOT_DISPOSED} ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["url"]), str(r["title"]), str(r["first_seen"]), r["year"]) for r in rows]

    def metacritic_claim_rows(self) -> list[tuple[int, str, str, int | None, str]]:
        """(film_id, slug, mc_title, mc_year, first_seen) via external_ids authority 'metacritic'."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT e.film_id, e.value, m.title, m.year, e.first_seen FROM external_ids e "
                "JOIN metacritic m ON m.slug = e.value JOIN films f ON f.id = e.film_id "
                f"WHERE e.authority = 'metacritic' AND {_NOT_DISPOSED} ORDER BY e.film_id"
            ).fetchall()
            return [
                (int(r["film_id"]), str(r["value"]), str(r["title"]), r["year"], str(r["first_seen"])) for r in rows
            ]

    def owned_rows(self) -> list[tuple[int, str]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT o.film_id, o.first_imported FROM owned o JOIN films f ON f.id = o.film_id "
                f"WHERE {_NOT_DISPOSED}"
            ).fetchall()
            return [(int(r["film_id"]), str(r["first_imported"])) for r in rows]

    def films_for_twins(self) -> list[TwinFilm]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, json_extract(o.payload, '$.imdbID') AS o_imdb, "
                "COALESCE((SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'imdb'), "
                "         (SELECT imdb_id FROM tmdb_facts t WHERE t.film_id = f.id)) AS t_imdb, "
                "(SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'tmdb') AS t_id "
                f"FROM films f LEFT JOIN omdb o ON o.film_id = f.id WHERE {_NOT_DISPOSED} ORDER BY f.id"
            ).fetchall()
            return [
                TwinFilm(int(r["id"]), str(r["title"]), r["year"], r["o_imdb"], r["t_imdb"], r["t_id"]) for r in rows
            ]

    def key_film_directly(self, film_id: int, *, new_title: str, imdb_id: str, today: date) -> bool:
        """Retitle a raw `Title (YYYY)` film to its parsed title and record its IMDb id
        (repair twins NO-TWIN case). False, nothing written, when the recomputed key or the
        imdb value is already held by another film."""
        with self._conn() as c:
            row = c.execute("SELECT year FROM films WHERE id = ?", (film_id,)).fetchone()
            if row is None:
                raise LookupError(f"unknown film {film_id}")
            new_key = film_key(new_title, row["year"])
            holder = c.execute("SELECT id FROM films WHERE key = ? AND id != ?", (new_key, film_id)).fetchone()
            if holder is not None and self._canonical_in(c, int(holder["id"])) == film_id:
                # this film's OWN merged-away loser holds the clean key: dead key, retire it in
                # place (same rule as update_film_year) so the survivor can take its title back
                c.execute("UPDATE films SET key = key || ' #' || id WHERE id = ?", (holder["id"],))
                holder = None
            other = c.execute(
                "SELECT film_id FROM external_ids WHERE authority = 'imdb' AND value = ? AND film_id != ?",
                (imdb_id, film_id),
            ).fetchone()
            if holder is not None or other is not None:
                return False
            c.execute("UPDATE films SET title = ?, key = ? WHERE id = ?", (new_title, new_key, film_id))
            c.execute(
                "UPDATE external_ids SET value = ? WHERE film_id = ? AND authority = 'imdb' AND value != ?",
                (imdb_id, film_id, imdb_id),
            )
            c.execute(
                "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, 'imdb', ?, ?) "
                "ON CONFLICT(film_id, authority, value) DO NOTHING",
                (film_id, imdb_id, today.isoformat()),
            )
            return True

    def films_for_editions(self) -> list[EditionFilm]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, f.title_norm, "
                "(SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'tmdb') AS t_id, "
                "(SELECT value FROM external_ids e WHERE e.film_id = f.id AND e.authority = 'imdb') AS i_id "
                f"FROM films f WHERE {_NOT_DISPOSED} ORDER BY f.id"
            ).fetchall()
            return [
                EditionFilm(int(r["id"]), str(r["title"]), r["year"], r["title_norm"], r["t_id"], r["i_id"])
                for r in rows
            ]

    def set_claim_edition_year(self, claim_id: int, year: int | None) -> None:
        with self._conn() as c:
            c.execute("UPDATE claim SET edition_year = ? WHERE id = ?", (year, claim_id))

    def claim_for_film_authority(self, film_id: int, authority: str) -> ClaimRow | None:
        """This film's claim from one authority — lowest id when several exist."""
        rows = [r for r in self.claims_for_film(film_id) if r.authority == authority]
        return rows[0] if rows else None

    def key_work(self, film_id: int, *, title: str, year: int, tt: str, tmdb_id: str | None, today: date) -> bool:
        """An edition row becomes its work (repair editions NO-TWIN): retitle, re-year, recompute
        key + title_norm, record imdb (+ tmdb). False, nothing written, when the new key is held
        by another live identity or tt / tmdb_id is held by another film. This film's own
        merged-away loser holding the key is retired in place (update_film_year rule)."""
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                raise LookupError(f"unknown film {film_id}")
            new_key = film_key(title, year)
            holder = c.execute("SELECT id FROM films WHERE key = ? AND id != ?", (new_key, film_id)).fetchone()
            # Every refusal check runs before any write: a plain `return False` inside an
            # open `_conn()` still commits, so a dead-key retirement or id write performed
            # before a later check fails would survive the refusal (bug fixed in review).
            retire_holder_id: int | None = None
            if holder is not None:
                if self._canonical_in(c, int(holder["id"])) != film_id:
                    return False
                retire_holder_id = int(holder["id"])
            for auth, val in (("imdb", tt), ("tmdb", tmdb_id)):
                if val and c.execute(
                    "SELECT 1 FROM external_ids WHERE authority = ? AND value = ? AND film_id != ?",
                    (auth, val, film_id),
                ).fetchone():
                    return False
            if retire_holder_id is not None:
                c.execute("UPDATE films SET key = key || ' #' || id WHERE id = ?", (retire_holder_id,))
            c.execute(
                "UPDATE films SET title = ?, year = ?, key = ?, title_norm = ? WHERE id = ?",
                (title, year, new_key, title_norm(title), film_id),
            )
            for auth, val in (("imdb", tt), ("tmdb", tmdb_id)):
                if val:
                    # Same UPDATE-then-INSERT shape as set_external_id: preserves first_seen
                    # on an existing row instead of the DELETE+INSERT this replaced (bug
                    # fixed in review), which reset first_seen to `today` on every call.
                    c.execute(
                        "UPDATE external_ids SET value = ? WHERE film_id = ? AND authority = ? AND value != ?",
                        (val, film_id, auth, val),
                    )
                    c.execute(
                        "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(film_id, authority, value) DO NOTHING",
                        (film_id, auth, val, today.isoformat()),
                    )
            return True

    # dispositions -----------------------------------------------------
    def disposition_of(self, film_id: int) -> tuple[str, int | None] | None:
        with self._conn() as c:
            row = c.execute("SELECT kind, survivor_id FROM film_disposition WHERE film_id = ?", (film_id,)).fetchone()
            return None if row is None else (str(row["kind"]), row["survivor_id"])

    @staticmethod
    def _canonical_in(c: sqlite3.Connection, film_id: int) -> int:
        """Follow merged→survivor chains on an open connection (cycle-safe)."""
        seen: set[int] = set()
        while film_id not in seen:
            seen.add(film_id)
            row = c.execute(
                "SELECT survivor_id FROM film_disposition WHERE film_id = ? AND kind = 'merged'", (film_id,)
            ).fetchone()
            if row is None:
                return film_id
            film_id = int(row["survivor_id"])
        return film_id

    def canonical_film_id(self, film_id: int) -> int:
        """Follow merged→survivor chains; tombstoned and undisposed films are their own canon."""
        with self._conn() as c:
            return self._canonical_in(c, film_id)

    def disposed_film_ids(self) -> set[int]:
        with self._conn() as c:
            return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM film_disposition")}

    def tombstoned_keys(self) -> set[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.key FROM films f JOIN film_disposition d ON d.film_id = f.id WHERE d.kind = 'tombstoned'"
            ).fetchall()
            return {str(r["key"]) for r in rows}

    # needs revisit -------------------------------------------------------
    def toggle_revisit(self, film_id: int, today: date, note: str | None = None) -> bool | None:
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            if c.execute("SELECT 1 FROM needs_revisit WHERE film_id = ?", (film_id,)).fetchone() is None:
                c.execute(
                    "INSERT INTO needs_revisit (film_id, marked_on, note) VALUES (?, ?, ?)",
                    (film_id, today.isoformat(), note),
                )
                return True
            c.execute("DELETE FROM needs_revisit WHERE film_id = ?", (film_id,))
            return False

    def set_revisit_note(self, film_id: int, note: str | None) -> bool:
        with self._conn() as c:
            return c.execute("UPDATE needs_revisit SET note = ? WHERE film_id = ?", (note, film_id)).rowcount > 0

    def clear_revisit(self, film_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM needs_revisit WHERE film_id = ?", (film_id,))

    def revisits(self) -> list[tuple[int, str, int | None, str, str | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT n.film_id, f.title, f.year, n.marked_on, n.note FROM needs_revisit n "
                "JOIN films f ON f.id = n.film_id WHERE " + _NOT_DISPOSED + " "
                "ORDER BY n.marked_on, n.film_id"
            ).fetchall()
            return [(int(r["film_id"]), str(r["title"]), r["year"], str(r["marked_on"]), r["note"]) for r in rows]

    def _assert_repairable(self, c: sqlite3.Connection, film_id: int) -> None:
        if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
            raise ValueError(f"unknown film {film_id}")
        if c.execute("SELECT 1 FROM film_disposition WHERE film_id = ?", (film_id,)).fetchone() is not None:
            raise ValueError(f"film {film_id} is already dispositioned")

    def tombstone_film(self, film_id: int, today: date, note: str | None = None) -> None:
        with self._conn() as c:
            self._assert_repairable(c, film_id)
            # A tombstone is a resolution, same as a merge is for its loser: drop any
            # needs_revisit flag rather than leaving it to haunt the (now-hidden) film.
            c.execute("DELETE FROM needs_revisit WHERE film_id = ?", (film_id,))
            c.execute(
                "INSERT INTO film_disposition (film_id, kind, survivor_id, note, created_at) "
                "VALUES (?, 'tombstoned', NULL, ?, ?)",
                (film_id, note, today.isoformat()),
            )

    def merge_film(self, loser_id: int, survivor_id: int, today: date, note: str | None = None) -> MergeReport:
        """Human-confirmed merge: move every dependent row to the survivor, alias the loser.

        One transaction. Survivor rows win on conflict (the dropped loser values are kept
        in the disposition note — full row for `my_ratings`/`watchlist`/`owned`, just the
        loser's `film_id` for `omdb`/`tmdb` since those payloads are large); listings widen
        to the union of both seen windows; transitions (append-only history) simply
        re-point; the loser's open reviews are resolved as part of the merge. The loser
        film row is never deleted.
        """
        if loser_id == survivor_id:
            raise ValueError("loser and survivor are the same film")
        moved: dict[str, int] = {}
        dropped: dict[str, int] = {}
        kept: dict[str, Any] = {}
        with self._conn() as c:
            self._assert_repairable(c, loser_id)
            self._assert_repairable(c, survivor_id)
            # The merge IS the loser's resolution: drop its needs_revisit flag outright
            # (never move it) — the survivor keeps its own flag untouched.
            c.execute("DELETE FROM needs_revisit WHERE film_id = ?", (loser_id,))
            for table in _ONE_ROW_TABLES:
                loser_row = c.execute(f"SELECT * FROM {table} WHERE film_id = ?", (loser_id,)).fetchone()
                if loser_row is None:
                    continue
                if c.execute(f"SELECT 1 FROM {table} WHERE film_id = ?", (survivor_id,)).fetchone() is None:
                    c.execute(f"UPDATE {table} SET film_id = ? WHERE film_id = ?", (survivor_id, loser_id))
                    moved[table] = 1
                else:
                    c.execute(f"DELETE FROM {table} WHERE film_id = ?", (loser_id,))
                    dropped[table] = 1
                    if table == "my_ratings":
                        kept[table] = {"score": loser_row["score"], "rated_at": loser_row["rated_at"]}
                    elif table in ("omdb", "tmdb"):
                        kept[table] = {"film_id": loser_id}
                    elif table == "watchlist":
                        kept[table] = {"added_on": loser_row["added_on"]}
                    elif table == "owned":
                        kept[table] = {"first_imported": loser_row["first_imported"]}
            for row in c.execute("SELECT * FROM listings WHERE film_id = ?", (loser_id,)).fetchall():
                twin = c.execute(
                    "SELECT first_seen, last_seen, leaving_date FROM listings WHERE film_id = ? AND source = ?",
                    (survivor_id, row["source"]),
                ).fetchone()
                if twin is None:
                    c.execute(
                        "UPDATE listings SET film_id = ? WHERE film_id = ? AND source = ?",
                        (survivor_id, loser_id, row["source"]),
                    )
                    moved["listings"] = moved.get("listings", 0) + 1
                else:
                    c.execute(
                        "UPDATE listings SET first_seen = MIN(first_seen, ?), last_seen = MAX(last_seen, ?), "
                        "leaving_date = COALESCE(leaving_date, ?) WHERE film_id = ? AND source = ?",
                        (row["first_seen"], row["last_seen"], row["leaving_date"], survivor_id, row["source"]),
                    )
                    c.execute("DELETE FROM listings WHERE film_id = ? AND source = ?", (loser_id, row["source"]))
                    dropped["listings"] = dropped.get("listings", 0) + 1
            n_claims = c.execute("UPDATE claim SET film_id = ? WHERE film_id = ?", (survivor_id, loser_id)).rowcount
            if n_claims:
                moved["claim"] = n_claims
            for row in c.execute("SELECT authority, value FROM external_ids WHERE film_id = ?", (loser_id,)).fetchall():
                auth, val = str(row["authority"]), str(row["value"])
                held = (
                    c.execute(
                        "SELECT 1 FROM external_ids WHERE film_id = ? AND authority = ?", (survivor_id, auth)
                    ).fetchone()
                    if auth in KEY_AUTHORITIES
                    else None
                )
                if held is None:
                    c.execute(
                        "UPDATE external_ids SET film_id = ? WHERE film_id = ? AND authority = ? AND value = ?",
                        (survivor_id, loser_id, auth, val),
                    )
                    moved["external_ids"] = moved.get("external_ids", 0) + 1
                else:
                    c.execute(
                        "DELETE FROM external_ids WHERE film_id = ? AND authority = ? AND value = ?",
                        (loser_id, auth, val),
                    )
                    dropped["external_ids"] = dropped.get("external_ids", 0) + 1
                    kept.setdefault("external_ids", []).append({auth: val})
            cur = c.execute(
                "UPDATE availability_transitions SET film_id = ? WHERE film_id = ?", (survivor_id, loser_id)
            )
            if cur.rowcount:
                moved["availability_transitions"] = cur.rowcount
            cur = c.execute(
                "UPDATE match_review SET resolved = 1, detail = COALESCE(detail, '') || ? "
                "WHERE film_id = ? AND resolved = 0",
                (f" [merged into film {survivor_id} {today.isoformat()}]", loser_id),
            )
            resolved = cur.rowcount
            # The survivor's own reviews that named the loser as the counterpart (id-conflict /
            # year-collision) are satisfied by this merge too; unrelated survivor rows stay open.
            cur = c.execute(
                "UPDATE match_review SET resolved = 1, detail = COALESCE(detail, '') || ? "
                "WHERE film_id = ? AND value = ? AND resolved = 0",
                (
                    f" [counterpart film {loser_id} merged into this film {today.isoformat()}]",
                    survivor_id,
                    str(loser_id),
                ),
            )
            resolved += cur.rowcount
            full_note = json.dumps({"note": note, "dropped": kept}) if (note or kept) else None
            c.execute(
                "INSERT INTO film_disposition (film_id, kind, survivor_id, note, created_at) "
                "VALUES (?, 'merged', ?, ?, ?)",
                (loser_id, survivor_id, full_note, today.isoformat()),
            )
            return MergeReport(moved, dropped, resolved)

    # views ------------------------------------------------------------
    def list_views(self, source: str, today: date | None = None) -> list[FilmView]:
        cutoff = ((today or date.today()) - timedelta(days=NEW_ARRIVAL_DAYS)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                _VIEW_SQL
                + "WHERE "
                + _NOT_DISPOSED
                + " AND (l.film_id IS NULL "
                + "OR l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) "
                + "OR r.score IS NOT NULL) ORDER BY f.id",
                (source, source),
            ).fetchall()
            services = _services_by_film(c)
            new_on = _new_on_by_film(c, cutoff)
            wl = _watchlist_ids(c)
            ow = _owned_ids(c)
            rv = _revisit_by_film(c)
            au = _audit_by_film(c)
            return [
                _row_to_view(
                    r,
                    services.get(r["id"]),
                    watchlisted=r["id"] in wl,
                    new_on=new_on.get(r["id"]),
                    owned=r["id"] in ow,
                    revisit=(r["id"] in rv, rv.get(r["id"])),
                    audit=au.get(r["id"], (None, None)),
                )
                for r in rows
            ]

    def get_view(self, film_id: int, today: date | None = None) -> FilmView | None:
        cutoff = ((today or date.today()) - timedelta(days=NEW_ARRIVAL_DAYS)).isoformat()
        with self._conn() as c:
            row = c.execute(_VIEW_SQL + "WHERE f.id = ? AND " + _NOT_DISPOSED, ("criterion", film_id)).fetchone()
            if row is None:
                return None
            rv = _revisit_by_film(c)
            au = _audit_by_film(c)
            return _row_to_view(
                row,
                _services_by_film(c).get(row["id"]),
                watchlisted=row["id"] in _watchlist_ids(c),
                new_on=_new_on_by_film(c, cutoff).get(row["id"]),
                owned=row["id"] in _owned_ids(c),
                revisit=(row["id"] in rv, rv.get(row["id"])),
                audit=au.get(row["id"], (None, None)),
            )

    def get_payload(self, film_id: int) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT payload FROM omdb WHERE film_id = ?", (film_id,)).fetchone()
            return None if row is None or row["payload"] is None else str(row["payload"])

    def summary(self, source: str) -> dict[str, int]:
        views = self.list_views(source)
        crit = [v for v in views if v.criterion]
        return {
            "films": len(crit),
            "rated": sum(1 for v in crit if v.found is True),
            "pending": sum(1 for v in crit if v.pending),
            "unmatched": sum(1 for v in crit if v.found is False),
            "leaving": sum(1 for v in crit if v.leaving_date is not None),
            "mine": sum(1 for v in crit if v.my_rating is not None),
            "departed": sum(1 for v in crit if v.departed),
            "discovery": sum(1 for v in views if not v.criterion),
            "owned": sum(1 for v in views if v.owned),
        }
