from datetime import date

from movie_brain.application.availability import queue_review_once, record_tmdb_match
from movie_brain.domain.models import Film, ReviewEntry
from movie_brain.infrastructure.database import TmdbMatchTarget

TODAY = date(2026, 8, 19)


def test_queue_review_once_is_idempotent(repo):
    """The dedup guard: a second append of the same reason+film_id is a no-op — proves
    the branch at availability.py's queue_review_once directly, independent of any
    caller's per-run review-queue rebuild (which never re-touches an already-matched
    film, so it can't exercise this guard on its own)."""
    fid = repo.upsert_film(Film("Nosferatu", 2024, None, "https://mc/nosferatu"))
    entry = ReviewEntry("year-collision", film_id=fid, value="99", detail="twin")

    first = queue_review_once(repo, "tmdb", entry, TODAY)
    second = queue_review_once(repo, "tmdb", entry, TODAY)

    assert first is True
    assert second is False
    rows = [r for r in repo.open_reviews("tmdb") if r["reason"] == "year-collision" and r["film_id"] == fid]
    assert len(rows) == 1


def test_record_tmdb_match_replay_does_not_double_queue_year_collision(repo):
    """Task 6's rematch reuses record_tmdb_match verbatim, including on films already
    reviewed once — the queue_review_once guard inside it (not the per-run no-match
    rebuild, which excludes already-matched films entirely) is what keeps a repeated
    call from stacking duplicate year-collision rows for the same twin."""
    repo.upsert_film(Film("Nosferatu", 1922, None, "https://c/nosferatu"))
    fid = repo.upsert_film(Film("Nosferatu", 2024, None, "https://mc/nosferatu"))
    target = TmdbMatchTarget(fid, "Nosferatu", 2024, True)

    outcome1 = record_tmdb_match(repo, target, 653, 1922, TODAY, lambda msg: None)
    outcome2 = record_tmdb_match(repo, target, 653, 1922, TODAY, lambda msg: None)

    assert outcome1 == "matched"
    assert outcome2 == "matched"
    reviews = [r for r in repo.open_reviews("tmdb") if r["reason"] == "year-collision" and r["film_id"] == fid]
    assert len(reviews) == 1
