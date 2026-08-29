from movie_brain.domain.models import FilmView
from movie_brain.domain.watch import best_source, rank_key, watch_options

CRITERION = {"name": "Criterion Channel", "subscribed": True, "kind": "svod", "quality": 5, "has_apple_app": True}


def svc(name, *, subscribed=True, kind="svod", quality=1, has_apple_app=False):
    return {"name": name, "subscribed": subscribed, "kind": kind, "quality": quality, "has_apple_app": has_apple_app}


def view(**kw) -> FilmView:
    base = dict(
        id=1, title="T", year=1950, director="D", url=None, language="French",
        imdb=None, rt=None, found=True, pending=False, leaving_date=None,
        first_seen="2026-01-01", my_rating=None,
    )
    base.update(kw)
    return FilmView(**base)


def test_subscribed_outranks_everything_else():
    v = view(services=[svc("Paid Better", subscribed=False, quality=9, has_apple_app=True), svc("Mine", quality=1)])
    assert best_source(v, None)["name"] == "Mine"


def test_quality_outranks_the_apple_app():
    v = view(services=[svc("Good Transfer", quality=5), svc("Has App", quality=1, has_apple_app=True)])
    assert best_source(v, None)["name"] == "Good Transfer"


def test_the_apple_app_breaks_a_tie_and_never_more():
    v = view(services=[svc("No App", quality=3), svc("App", quality=3, has_apple_app=True)])
    assert best_source(v, None)["name"] == "App"


def test_name_is_the_final_stable_tiebreak():
    v = view(services=[svc("Zed", quality=3), svc("Alpha", quality=3)])
    assert [o["name"] for o in watch_options(v, None)] == ["Alpha", "Zed"]


def test_monetization_tier_is_not_a_key():
    """C2: a free-with-ads service with a better transfer must be allowed to win."""
    v = view(services=[svc("Paid Flat", quality=2), svc("Free With Ads", quality=6)])
    assert best_source(v, None)["name"] == "Free With Ads"


def test_a_store_is_never_a_watch_option():
    v = view(services=[svc("Apple TV Store", kind="store", quality=9)])
    assert best_source(v, None) is None


def test_a_current_criterion_listing_joins_the_ranking():
    v = view(services=[svc("Tubi", quality=1)], criterion=True, departed=False)
    assert best_source(v, CRITERION)["name"] == "Criterion Channel"


def test_a_departed_criterion_listing_does_not():
    v = view(services=[svc("Tubi", quality=1)], criterion=True, departed=True)
    assert best_source(v, CRITERION)["name"] == "Tubi"


def test_a_film_with_no_criterion_listing_does_not_get_one():
    v = view(services=[svc("Tubi", quality=1)], criterion=False)
    assert best_source(v, CRITERION)["name"] == "Tubi"


def test_no_options_means_no_best_source():
    assert best_source(view(services=[], criterion=False), CRITERION) is None


def test_watch_options_does_not_mutate_the_view():
    original = svc("Tubi")
    v = view(services=[original], criterion=True, departed=False)
    watch_options(v, CRITERION)
    assert v.services == [original]
    assert len(v.services) == 1


def test_rank_key_is_ascending_best_first():
    assert rank_key(svc("A", quality=9)) < rank_key(svc("A", quality=1))


def test_quality_zero_ranks_below_quality_one():
    """0 is a legal quality (`services quality SLUG 0`), not an absent one — it must rank
    last rather than fold into the default."""
    assert rank_key(svc("A", quality=0)) > rank_key(svc("A", quality=1))


def test_a_zero_quality_option_loses_to_a_positive_one():
    # "Alpha" would win the name tiebreak, so only quality can decide this.
    v = view(services=[svc("Alpha", quality=0), svc("Zed", quality=1)])
    assert best_source(v, None)["name"] == "Zed"
    assert [o["name"] for o in watch_options(v, None)] == ["Zed", "Alpha"]
