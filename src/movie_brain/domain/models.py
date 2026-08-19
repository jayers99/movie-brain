from __future__ import annotations

from dataclasses import asdict, dataclass


def film_key(title: str, year: int | None) -> str:
    return f"{title.strip().lower()} ({year})"


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
