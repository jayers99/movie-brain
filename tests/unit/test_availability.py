from datetime import date

from movie_brain.application.availability import queue_review_once, record_tmdb_match, tmdb_step
from movie_brain.domain.models import Film, OmdbRating, ReviewEntry, TmdbProviders
from movie_brain.infrastructure.database import TmdbMatchTarget

TODAY = date(2026, 8, 19)


class _StubTmdbClient:
    """Duck-types `TmdbClient.watch_providers` — `_refresh_pass` calls nothing else on it."""

    def __init__(self, providers: TmdbProviders) -> None:
        self.providers = providers

    def watch_providers(self, tmdb_id: int) -> TmdbProviders:
        return self.providers


def _seed_first_check_film(repo, today: date) -> int:
    """A matched film TMDB has never checked providers for — picked up by tmdb_step's
    first-check pass unconditionally, so no weekly-stamp gate needs defeating."""
    fid = repo.upsert_film(Film("Nosferatu", 2024, None, "https://mc/nosferatu"))
    repo.set_external_id(fid, "tmdb", "603", today)
    repo.upsert_tmdb(fid, found=True, looked_up=today)
    return fid


def _listing_sources(repo, film_id: int) -> set[str]:
    with repo._conn() as c:
        rows = c.execute("SELECT source FROM listings WHERE film_id = ?", (film_id,)).fetchall()
        return {str(r["source"]) for r in rows}


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


def test_queue_review_once_resolved_suppression_is_value_scoped(repo):
    """A dismissed row is a standing decision only for its own (reason, film, VALUE) —
    a fresh id-conflict claiming a *different* tmdb id for the same film is a new
    anomaly, not the one the human already resolved, and must still be queued."""
    fid = repo.upsert_film(Film("Nosferatu", 2024, None, "https://mc/nosferatu"))
    first = ReviewEntry("id-conflict", film_id=fid, value="5", detail="claimed by 5")
    assert queue_review_once(repo, "tmdb", first, TODAY) is True
    review_id = next(r["id"] for r in repo.open_reviews("tmdb") if r["film_id"] == fid)
    repo.resolve_review(review_id, "dismissed")

    same_value = ReviewEntry("id-conflict", film_id=fid, value="5", detail="claimed by 5 again")
    other_value = ReviewEntry("id-conflict", film_id=fid, value="6", detail="claimed by 6")

    assert queue_review_once(repo, "tmdb", same_value, TODAY) is False
    assert queue_review_once(repo, "tmdb", other_value, TODAY) is True
    rows = [r for r in repo.open_reviews("tmdb") if r["reason"] == "id-conflict" and r["film_id"] == fid]
    assert [r["value"] for r in rows] == ["6"]


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

    assert outcome1 == "collision"
    assert outcome2 == "collision"
    reviews = [r for r in repo.open_reviews("tmdb") if r["reason"] == "year-collision" and r["film_id"] == fid]
    assert len(reviews) == 1


def test_record_tmdb_match_year_adoption_requeues_stale_omdb_miss(repo):
    """Army of Shadows: promoted under Metacritic's 2006 re-release year, OMDb missed
    under 2006, then TMDB canonicalized 1969. The miss must not sit for the 30-day
    retry window — adopting a new year is new evidence, so the OMDb row is flagged
    for refetch exactly as `repair years --apply` does."""
    fid = repo.upsert_film(Film("Army of Shadows", 2006, None, "https://mc/army-of-shadows"))
    repo.upsert_omdb(fid, OmdbRating(None, None, False), TODAY)
    target = TmdbMatchTarget(fid, "Army of Shadows", 2006, True)

    outcome = record_tmdb_match(repo, target, 15383, 1969, TODAY, lambda msg: None)

    assert outcome == "adopted"
    queued = {i for i, _ in repo.films_needing_lookup_discovery("criterion", TODAY)}
    assert fid in queued


def test_record_tmdb_match_fills_a_missing_year_for_a_criterion_film(repo):
    """A missing year is not a value worth protecting: precedence only applies between
    two values that both exist. A Criterion film (commerce=False) with no year at all
    must still adopt TMDB's year — this is the bug fix, and must fail before it."""
    fid = repo.upsert_film(Film("Army of Shadows", None, None, "https://c/army-of-shadows"))
    target = TmdbMatchTarget(fid, "Army of Shadows", None, False)

    outcome = record_tmdb_match(repo, target, 15383, 1969, TODAY, lambda msg: None)

    assert outcome == "adopted"
    view = repo.get_view(fid)
    assert view is not None
    assert view.year == 1969


def test_record_tmdb_match_never_overwrites_a_criterion_films_existing_year(repo):
    """The protection that must not regress: a Criterion film that already HAS a year
    keeps it even when TMDB disagrees — precedence between two real values, unchanged
    by the fix."""
    fid = repo.upsert_film(Film("Army of Shadows", 2006, None, "https://c/army-of-shadows"))
    target = TmdbMatchTarget(fid, "Army of Shadows", 2006, False)

    outcome = record_tmdb_match(repo, target, 15383, 1969, TODAY, lambda msg: None)

    assert outcome == "matched"
    view = repo.get_view(fid)
    assert view is not None
    assert view.year == 2006


def test_record_tmdb_match_commerce_film_still_adopts_a_differing_year(repo):
    """Existing behaviour, unchanged: a commerce (no-Criterion-listing) film with a
    differing year still adopts TMDB's year."""
    fid = repo.upsert_film(Film("Army of Shadows", 2006, None, "https://mc/army-of-shadows"))
    target = TmdbMatchTarget(fid, "Army of Shadows", 2006, True)

    outcome = record_tmdb_match(repo, target, 15383, 1969, TODAY, lambda msg: None)

    assert outcome == "adopted"
    view = repo.get_view(fid)
    assert view is not None
    assert view.year == 1969


def test_record_tmdb_match_null_year_key_collision_queues_review(repo):
    """A film with no year at all can still collide on the recomputed key with an
    existing film holding the same title+TMDB-year — the collision path must still
    queue year-collision rather than overwrite, even on this new NULL-year branch."""
    repo.upsert_film(Film("Nosferatu", 1922, None, "https://c/nosferatu"))
    fid = repo.upsert_film(Film("Nosferatu", None, None, "https://c/nosferatu-2"))
    target = TmdbMatchTarget(fid, "Nosferatu", None, False)

    outcome = record_tmdb_match(repo, target, 653, 1922, TODAY, lambda msg: None)

    assert outcome == "collision"
    view = repo.get_view(fid)
    assert view is not None
    assert view.year is None
    reviews = [r for r in repo.open_reviews("tmdb") if r["reason"] == "year-collision" and r["film_id"] == fid]
    assert len(reviews) == 1


def test_rebuild_skips_a_film_whose_reviewed_row_was_resolved(repo, today):
    from movie_brain.application.availability import NO_MATCH_REVIEWED, rebuild_no_match_queue
    from movie_brain.domain.models import Film, ReviewEntry

    fid = repo.create_film(Film("Bound", 1996, None, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=today)
    repo.append_reviews("tmdb", [ReviewEntry(NO_MATCH_REVIEWED, film_id=fid, detail="{}")], today)
    rid = int(repo.open_reviews("tmdb")[0]["id"])
    repo.resolve_review(rid, "verified unkeyed")  # --none: a standing decision
    rebuild_no_match_queue(repo, today)
    assert repo.open_reviews("tmdb") == []


def test_rebuild_leaves_an_open_reviewed_row_alone_and_does_not_double_queue(repo, today):
    from movie_brain.application.availability import NO_MATCH_REVIEWED, rebuild_no_match_queue
    from movie_brain.domain.models import Film, ReviewEntry

    fid = repo.create_film(Film("Bound", 1996, None, ""))
    repo.upsert_tmdb(fid, found=False, looked_up=today)
    repo.append_reviews("tmdb", [ReviewEntry(NO_MATCH_REVIEWED, film_id=fid, detail="{}")], today)
    rebuild_no_match_queue(repo, today)
    rows = repo.open_reviews("tmdb")
    assert [r["reason"] for r in rows] == [NO_MATCH_REVIEWED]


def test_tmdb_step_records_free_and_ads_alongside_flatrate(repo, today):
    """C2 + the auto-registration this task adds: flatrate/free/ads are unioned, and an
    unmapped provider (Kanopy, Tubi TV) registers itself at subscribed=0 rather than
    being discarded — the 29-of-46-canon-films loss the task brief measures."""
    fid = _seed_first_check_film(repo, today)
    providers = TmdbProviders(
        flatrate=(1899,), rent=(), buy=(), link="https://x", payload="{}",
        free=(191,), ads=(73,),
        names={1899: "HBO Max", 191: "Kanopy", 73: "Tubi TV"},
    )
    tmdb_step(repo, _StubTmdbClient(providers), today, log=lambda _: None)
    assert _listing_sources(repo, fid) == {"max", "kanopy", "tubi-tv"}
    assert repo.movie_service("kanopy").subscribed is False
    assert repo.movie_service("tubi-tv").subscribed is False


def test_tmdb_step_never_records_criterion_from_tmdb(repo, today):
    """Criterion listings come from record_catalog's own currency frontier — the
    `criterion` exclusion inside the union must survive Task 4's rewrite."""
    fid = _seed_first_check_film(repo, today)
    providers = TmdbProviders(
        flatrate=(258,), rent=(), buy=(), link="https://x", payload="{}",
        names={258: "Criterion Channel"},
    )
    tmdb_step(repo, _StubTmdbClient(providers), today, log=lambda _: None)
    assert _listing_sources(repo, fid) == set()


def test_tmdb_step_skips_an_unregistrable_provider_and_keeps_the_rest(repo, today):
    """A provider name that slugifies to "" (all punctuation) must not raise mid-pass and
    abort a refresh over the whole catalog — it's skipped, logged, and the other providers
    in the same response still record."""
    fid = _seed_first_check_film(repo, today)
    providers = TmdbProviders(
        flatrate=(1899, 991), rent=(), buy=(), link="https://x", payload="{}",
        names={1899: "HBO Max", 991: "+++"},
    )
    messages: list[str] = []
    tmdb_step(repo, _StubTmdbClient(providers), today, log=messages.append)
    assert _listing_sources(repo, fid) == {"max"}
    assert 991 not in repo.provider_map()
    assert any("991" in m for m in messages)
