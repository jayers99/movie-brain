from __future__ import annotations

from datetime import date

from movie_brain.domain.models import FilmView
from movie_brain.infrastructure.database import Repository


def rate_film(repo: Repository, film_id: int, score: int | None, today: date) -> FilmView:
    if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10):
        raise ValueError("score must be an integer 0–10")
    if not repo.set_rating(film_id, score, today):
        raise LookupError(film_id)
    view = repo.get_view(film_id, today)
    assert view is not None
    return view
