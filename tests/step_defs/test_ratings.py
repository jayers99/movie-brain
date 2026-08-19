from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.ratings import rate_film
from movie_brain.domain.models import Film

scenarios("../features/ratings.feature")
TODAY = date(2026, 8, 19)


@pytest.fixture
def ctx(repo):
    return {"repo": repo, "fid": None}


@given(parsers.parse('a current film "{title} ({year:d})"'))
def film(ctx, title, year):
    f = Film(title, year, "D", "u")
    ctx["repo"].record_catalog("criterion", [f], TODAY)
    ctx["fid"] = ctx["repo"].film_id_by_key(f.key)


@when(parsers.parse("I rate it {score:d}"))
def rate(ctx, score):
    rate_film(ctx["repo"], ctx["fid"], score, TODAY)


@when("I clear its rating")
def clear(ctx):
    rate_film(ctx["repo"], ctx["fid"], None, TODAY)


@then(parsers.parse("its view shows my rating {score:d}"))
def shows(ctx, score):
    assert ctx["repo"].get_view(ctx["fid"]).my_rating == score


@then("its view shows no rating")
def shows_none(ctx):
    assert ctx["repo"].get_view(ctx["fid"]).my_rating is None


@then(parsers.parse("rating it {score:d} raises ValueError"))
def bad_score(ctx, score):
    with pytest.raises(ValueError):
        rate_film(ctx["repo"], ctx["fid"], score, TODAY)


@then(parsers.parse("rating film {fid:d} raises LookupError"))
def unknown(ctx, fid):
    with pytest.raises(LookupError):
        rate_film(ctx["repo"], fid, 5, TODAY)
