from __future__ import annotations

from movie_brain.application.thumbprint import film_query
from movie_brain.domain.models import Film


def _film(repo, today, title, year, director=None, claims=()):
    fid = repo.create_film(Film(title, year, director, ""))
    for authority, ctitle, cyear, runtime in claims:
        repo.add_claim(
            fid, authority, f"{authority}:{title}", ctitle,
            year_claimed=cyear, runtime_min=runtime, first_seen=today.isoformat(),
        )
    return fid


def test_film_query_prefers_criterion_then_metacritic_then_apple(repo, today):
    fid = _film(repo, today, "Bound", 1996, "The Wachowskis", claims=(
        ("apple-tv", "Bound (Unrated)", 1997, 108),
        ("metacritic", "Bound", 1996, None),
        ("criterion", "Bound", 1996, None),
    ))
    q = film_query(repo, fid, "Bound", 1996, "The Wachowskis")
    assert (q.raw_title, q.year, q.source) == ("Bound", 1996, "criterion")


def test_film_query_carries_apple_runtime_even_from_another_source(repo, today):
    fid = _film(repo, today, "Bound", 1996, None, claims=(
        ("apple-tv", "Bound (Unrated)", 1997, 108),
        ("metacritic", "Bound", 1996, None),
    ))
    q = film_query(repo, fid, "Bound", 1996, None)
    assert (q.source, q.runtime_min) == ("metacritic", 108)


def test_film_query_without_claims_falls_back_to_the_film_row(repo, today):
    fid = _film(repo, today, "Bound", 1996, "The Wachowskis")
    q = film_query(repo, fid, "Bound", 1996, "The Wachowskis")
    assert (q.raw_title, q.year, q.source, q.director) == ("Bound", 1996, "unknown", "The Wachowskis")


def test_film_query_apple_claim_maps_to_source_apple(repo, today):
    fid = _film(repo, today, "Bound", 1996, None, claims=(("apple-tv", "Bound (Unrated)", 1997, 108),))
    q = film_query(repo, fid, "Bound", 1996, None)
    assert (q.raw_title, q.year, q.source) == ("Bound (Unrated)", 1997, "apple")
