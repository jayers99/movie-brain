from __future__ import annotations

import sqlite3
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from movie_brain.domain.filters import NEW_ARRIVAL_DAYS
from movie_brain.domain.models import Film, FilmView, McTitle, OmdbRating, ReviewEntry

MISS_RETRY_DAYS = 30
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
TMDB_REFRESH_STAMP = "tmdb_providers_refreshed_at"


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        has_versions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")} if has_versions else set()
        pending = [m for m in sorted(MIGRATIONS_DIR.glob("*.sql")) if int(m.name.split("_")[0]) not in applied]
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


_VIEW_SQL = """
SELECT f.id, f.title, f.year, f.director, l.url, o.language, o.imdb, o.rt,
       COALESCE(mc.score, o.metacritic) AS metacritic, x.value AS mc_slug, o.found,
       (o.film_id IS NULL) AS pending, l.leaving_date, l.first_seen, r.score,
       (l.last_seen < (SELECT MAX(last_seen) FROM listings WHERE source = l.source)) AS departed
FROM films f
JOIN listings l ON l.film_id = f.id AND l.source = ?
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN my_ratings r ON r.film_id = f.id
LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'metacritic'
LEFT JOIN metacritic mc ON mc.slug = x.value
"""


_SERVICES_SQL = f"""
SELECT l.film_id, s.name, s.subscribed FROM listings l
JOIN movie_service s ON s.slug = l.source
WHERE s.kind = 'svod' AND l.source != 'criterion'
  AND l.last_seen >= COALESCE(
      (SELECT value FROM meta WHERE key = '{TMDB_REFRESH_STAMP}'),
      (SELECT MAX(last_seen) FROM listings l2 WHERE l2.source = l.source))
ORDER BY l.film_id, s.subscribed DESC, s.name
"""


def _services_by_film(c: sqlite3.Connection) -> dict[int, list[dict[str, object]]]:
    out: dict[int, list[dict[str, object]]] = {}
    for r in c.execute(_SERVICES_SQL):
        out.setdefault(int(r["film_id"]), []).append({"name": str(r["name"]), "subscribed": bool(r["subscribed"])})
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


def _row_to_view(
    row: sqlite3.Row,
    services: list[dict[str, object]] | None = None,
    *,
    watchlisted: bool = False,
    new_on: list[dict[str, object]] | None = None,
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
    )


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        init_db(db_path)

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
        row = c.execute(
            "SELECT last_seen FROM listings WHERE film_id = ? AND source = ?", (film_id, source)
        ).fetchone()
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
            for film in films:
                c.execute(
                    "INSERT INTO films (guid, title, year, director, key) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, "
                    "director=excluded.director",
                    (str(uuid.uuid4()), film.title, film.year, film.director, film.key),
                )
                film_id = int(c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()["id"])
                self._write_listing(c, film_id, source, film.url, day, frontier)
                try:
                    c.execute(
                        "INSERT INTO external_ids (film_id, authority, value, first_seen) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(film_id, authority) DO UPDATE SET value=excluded.value",
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
            + extra_where
            + " ORDER BY f.id"
        )
        return c.execute(sql, (source, source, *params)).fetchall()

    def current_films(self, source: str) -> list[tuple[int, Film]]:
        with self._conn() as c:
            return [
                (r["id"], Film(r["title"], r["year"], r["director"], r["url"])) for r in self._current_rows(c, source)
            ]

    # external ids / services ------------------------------------------
    def set_external_id(self, film_id: int, authority: str, value: str, seen: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO external_ids (film_id, authority, value, first_seen) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(film_id, authority) DO UPDATE SET value=excluded.value",
                (film_id, authority, value, seen.isoformat()),
            )

    def external_ids_for(self, film_id: int) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute("SELECT authority, value FROM external_ids WHERE film_id = ?", (film_id,)).fetchall()
            return {str(r["authority"]): str(r["value"]) for r in rows}

    def claimed_values(self, authority: str) -> set[str]:
        with self._conn() as c:
            rows = c.execute("SELECT value FROM external_ids WHERE authority = ?", (authority,)).fetchall()
            return {str(r["value"]) for r in rows}

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

    def films_for_matching(self) -> list[tuple[int, str, int | None, int | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year, o.metacritic FROM films f "
                "LEFT JOIN omdb o ON o.film_id = f.id ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"], r["metacritic"]) for r in rows]

    def film_ids_with_external(self, authority: str) -> set[int]:
        with self._conn() as c:
            rows = c.execute("SELECT film_id FROM external_ids WHERE authority = ?", (authority,)).fetchall()
            return {int(r["film_id"]) for r in rows}

    def replace_unresolved_reviews(self, authority: str, entries: list[ReviewEntry], created: date) -> None:
        # Derived state, recomputed per match run — the immutability rule binds films, not this queue.
        with self._conn() as c:
            c.execute("DELETE FROM match_review WHERE authority = ? AND resolved = 0", (authority,))
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

    # tmdb ---------------------------------------------------------------
    def films_needing_tmdb_match(self) -> list[tuple[int, str, int | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year FROM films f "
                "WHERE NOT EXISTS (SELECT 1 FROM tmdb t WHERE t.film_id = f.id) ORDER BY f.id"
            ).fetchall()
            return [(int(r["id"]), str(r["title"]), r["year"]) for r in rows]

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
                "WHERE t.found = 1 ORDER BY t.film_id"
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"]), bool(r["first_check"])) for r in rows]

    def films_for_provider_refresh(self, skip_checked_on: date | None = None) -> list[tuple[int, str, bool]]:
        where = "" if skip_checked_on is None else "AND COALESCE(t.providers_checked_at, '') != ? "
        params: tuple[object, ...] = () if skip_checked_on is None else (skip_checked_on.isoformat(),)
        with self._conn() as c:
            rows = c.execute(
                "SELECT t.film_id, x.value, (t.providers_checked_at IS NULL) AS first_check FROM tmdb t "
                "JOIN external_ids x ON x.film_id = t.film_id AND x.authority = 'tmdb' "
                "WHERE t.found = 1 " + where + "ORDER BY (t.providers_checked_at IS NOT NULL), "
                "t.providers_checked_at, t.film_id",
                params,
            ).fetchall()
            return [(int(r["film_id"]), str(r["value"]), bool(r["first_check"])) for r in rows]

    def films_tmdb_missed(self) -> list[tuple[int, str, int | None]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT f.id, f.title, f.year FROM films f JOIN tmdb t ON t.film_id = f.id "
                "WHERE t.found = 0 ORDER BY f.id"
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
                "LEFT JOIN external_ids x ON x.film_id = f.id AND x.authority = 'metacritic' "
                "WHERE NOT EXISTS (SELECT 1 FROM listings l WHERE l.film_id = f.id AND l.source = ?) "
                "AND (NOT EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id) "
                "OR EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id AND "
                "(o.needs_refresh = 1 OR (o.found = 0 AND (o.year_fallback = 0 OR o.looked_up <= ?))))) "
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

    # views ------------------------------------------------------------
    def list_views(self, source: str, today: date | None = None) -> list[FilmView]:
        cutoff = ((today or date.today()) - timedelta(days=NEW_ARRIVAL_DAYS)).isoformat()
        with self._conn() as c:
            rows = c.execute(
                _VIEW_SQL
                + "WHERE l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) "
                + "OR r.score IS NOT NULL ORDER BY f.id",
                (source, source),
            ).fetchall()
            services = _services_by_film(c)
            new_on = _new_on_by_film(c, cutoff)
            wl = _watchlist_ids(c)
            return [
                _row_to_view(r, services.get(r["id"]), watchlisted=r["id"] in wl, new_on=new_on.get(r["id"]))
                for r in rows
            ]

    def get_view(self, film_id: int, today: date | None = None) -> FilmView | None:
        cutoff = ((today or date.today()) - timedelta(days=NEW_ARRIVAL_DAYS)).isoformat()
        with self._conn() as c:
            row = c.execute(_VIEW_SQL + "WHERE f.id = ?", ("criterion", film_id)).fetchone()
            if row is None:
                return None
            return _row_to_view(
                row,
                _services_by_film(c).get(row["id"]),
                watchlisted=row["id"] in _watchlist_ids(c),
                new_on=_new_on_by_film(c, cutoff).get(row["id"]),
            )

    def get_payload(self, film_id: int) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT payload FROM omdb WHERE film_id = ?", (film_id,)).fetchone()
            return None if row is None or row["payload"] is None else str(row["payload"])

    def summary(self, source: str) -> dict[str, int]:
        views = self.list_views(source)
        return {
            "films": len(views),
            "rated": sum(1 for v in views if v.found is True),
            "pending": sum(1 for v in views if v.pending),
            "unmatched": sum(1 for v in views if v.found is False),
            "leaving": sum(1 for v in views if v.leaving_date is not None),
            "mine": sum(1 for v in views if v.my_rating is not None),
            "departed": sum(1 for v in views if v.departed),
        }
