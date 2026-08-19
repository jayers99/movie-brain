from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from movie_brain.domain.models import Film, FilmView, OmdbRating

MISS_RETRY_DAYS = 30
MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        has_versions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")} if has_versions else set()
        for mig in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(mig.name.split("_")[0])
            if version not in applied:
                conn.executescript(mig.read_text())
        conn.commit()
    finally:
        conn.close()


_VIEW_SQL = """
SELECT f.id, f.title, f.year, f.director, l.url, o.language, o.imdb, o.rt, o.found,
       (o.film_id IS NULL) AS pending, l.leaving_date, l.first_seen, r.score
FROM films f
JOIN listings l ON l.film_id = f.id AND l.source = ?
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN my_ratings r ON r.film_id = f.id
"""


def _row_to_view(row: sqlite3.Row) -> FilmView:
    return FilmView(
        id=row["id"],
        title=row["title"],
        year=row["year"],
        director=row["director"],
        url=row["url"],
        language=row["language"],
        imdb=row["imdb"],
        rt=row["rt"],
        found=None if row["found"] is None else bool(row["found"]),
        pending=bool(row["pending"]),
        leaving_date=row["leaving_date"],
        first_seen=row["first_seen"],
        my_rating=row["score"],
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
                "INSERT INTO films (title, year, director, key) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, director=excluded.director",
                (film.title, film.year, film.director, film.key),
            )
            row = c.execute("SELECT id FROM films WHERE key = ?", (film.key,)).fetchone()
            return int(row["id"])

    def film_id_by_key(self, key: str) -> int | None:
        with self._conn() as c:
            row = c.execute("SELECT id FROM films WHERE key = ?", (key,)).fetchone()
            return None if row is None else int(row["id"])

    def record_listing(self, film_id: int, source: str, url: str, seen: date) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO listings (film_id, source, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id, source) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen",
                (film_id, source, url, seen.isoformat(), seen.isoformat()),
            )

    def record_catalog(self, source: str, films: list[Film], seen: date) -> None:
        day = seen.isoformat()
        with self._conn() as c:
            for film in films:
                c.execute(
                    "INSERT INTO films (title, year, director, key) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET title=excluded.title, year=excluded.year, "
                    "director=excluded.director",
                    (film.title, film.year, film.director, film.key),
                )
                c.execute(
                    "INSERT INTO listings (film_id, source, url, first_seen, last_seen) "
                    "VALUES ((SELECT id FROM films WHERE key = ?), ?, ?, ?, ?) "
                    "ON CONFLICT(film_id, source) DO UPDATE SET url=excluded.url, last_seen=excluded.last_seen",
                    (film.key, source, film.url, day, day),
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
                "(film_id, found, imdb, rt, language, looked_up, year_fallback, needs_refresh, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(film_id) DO UPDATE SET "
                "found=excluded.found, imdb=excluded.imdb, rt=excluded.rt, language=excluded.language, "
                "looked_up=excluded.looked_up, year_fallback=excluded.year_fallback, "
                "needs_refresh=excluded.needs_refresh, payload=COALESCE(excluded.payload, omdb.payload)",
                (
                    film_id,
                    int(rating.found),
                    rating.imdb,
                    rating.rt,
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

    # views ------------------------------------------------------------
    def list_views(self, source: str) -> list[FilmView]:
        with self._conn() as c:
            rows = c.execute(
                _VIEW_SQL + "WHERE l.last_seen = (SELECT MAX(last_seen) FROM listings WHERE source = ?) ORDER BY f.id",
                (source, source),
            ).fetchall()
            return [_row_to_view(r) for r in rows]

    def get_view(self, film_id: int) -> FilmView | None:
        with self._conn() as c:
            row = c.execute(_VIEW_SQL + "WHERE f.id = ?", ("criterion", film_id)).fetchone()
            return None if row is None else _row_to_view(row)

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
        }
