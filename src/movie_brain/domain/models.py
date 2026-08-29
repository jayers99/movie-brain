from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace


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
class OwnedTitle:
    """One movie from the user's Apple TV library export."""

    title: str
    year: int | None
    runtime_min: int | None = None


@dataclass(frozen=True)
class ListMeta:
    """Header block of one checked-in curated list file (lists/<slug>.tsv)."""

    slug: str
    name: str
    curator: str | None
    published_year: int | None
    source_url: str | None
    ordered: bool


@dataclass(frozen=True)
class ListEntry:
    """One ranked row of a curated list; title/director are verbatim forever."""

    rank: int
    title_listed: str
    director_listed: str | None


@dataclass(frozen=True)
class TmdbCandidate:
    """One TMDB search result, reduced to what matching needs."""

    tmdb_id: int
    title: str
    original_title: str
    year: int | None
    popularity: float


@dataclass(frozen=True)
class TmdbProviders:
    """US watch-provider snapshot for one film; payload is the raw response text."""

    flatrate: tuple[int, ...]
    rent: tuple[int, ...]
    buy: tuple[int, ...]
    link: str | None
    payload: str


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
    url: str | None
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
    services: list[dict[str, object]] = field(default_factory=list)
    watchlisted: bool = False
    new_on: list[dict[str, object]] = field(default_factory=list)  # [{source, name, appeared_on}], arrivals window only
    criterion: bool = True  # has a Criterion listing (current or departed); False = discovery-only
    owned: bool = False  # in my Apple TV library (owned table); import is the only writer
    needs_revisit: bool = False  # drawer-flagged as factually suspect; drawer toggle is the only writer
    revisit_note: str | None = None
    audit: dict[str, object] | None = None  # {score, reasons:[{code, detail}]} from audit_flags; None = not a suspect
    verdict: dict[str, object] | None = None  # latest audit_verdict row; the dashboard endpoint is its only writer
    # verdict["reasons"] is a comma-joined sorted string (asymmetric with audit["reasons"] above, a list of dicts)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
