from __future__ import annotations

from dataclasses import asdict, dataclass, replace


def film_key(title: str, year: int | None) -> str:
    return f"{title.strip().lower()} ({year})"


def merge_yearless(films: list[Film], known: list[Film]) -> list[Film]:
    """Fold year-less catalog entries into their titled twin.

    Criterion sometimes publishes a second, year-less page for a film it
    already lists (e.g. ``…/alice-in-the-cities-1``). A year-less film whose
    title matches exactly one year across ``films`` + ``known`` is dropped when
    that twin is already in ``films``, otherwise rewritten to the twin's year.
    Titles matching zero or several years pass through unchanged.
    """
    years_by_title: dict[str, set[int]] = {}
    for f in [*films, *known]:
        if f.year is not None:
            years_by_title.setdefault(f.title.strip().lower(), set()).add(f.year)
    fetched_keys = {f.key for f in films}

    merged: list[Film] = []
    for f in films:
        if f.year is None:
            years = years_by_title.get(f.title.strip().lower(), set())
            if len(years) == 1:
                (year,) = years
                if film_key(f.title, year) in fetched_keys:
                    continue
                f = replace(f, year=year)
        merged.append(f)
    return merged


@dataclass(frozen=True)
class Film:
    title: str
    year: int | None
    director: str | None
    url: str

    @property
    def key(self) -> str:
        return film_key(self.title, self.year)


@dataclass(frozen=True)
class OmdbRating:
    imdb: float | None
    rt: int | None
    found: bool
    language: str | None = None
    payload: str | None = None  # raw OMDb JSON text; None when not found
    metacritic: int | None = None


@dataclass(frozen=True)
class McTitle:
    """One title card from Metacritic's sorted browse walk (staged, not a film)."""

    slug: str
    title: str
    year: int | None
    score: int | None
    rank: int  # position in the sorted walk
    page: int


@dataclass(frozen=True)
class ReviewEntry:
    """A match anomaly queued for human review — never a deletion."""

    reason: str
    film_id: int | None = None
    value: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class FilmView:
    id: int
    title: str
    year: int | None
    director: str | None
    url: str
    language: str | None
    imdb: float | None
    rt: int | None
    found: bool | None  # None = no OMDb row yet
    pending: bool
    leaving_date: str | None
    first_seen: str | None
    my_rating: int | None
    departed: bool = False  # no longer in the source's current catalog
    metacritic: int | None = None
    metacritic_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
