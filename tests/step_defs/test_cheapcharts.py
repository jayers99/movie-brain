from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.cheapcharts import resolve_itunes_ids
from movie_brain.domain.models import Film
from movie_brain.infrastructure.cheapcharts import MAX_IMDB_IDS, Product, RateLimited

scenarios("../features/cheapcharts.feature")


@dataclass
class FakeCheapCharts:
    """Only the two calls the resolver is allowed to make."""

    by_imdb: dict[str, Product] = field(default_factory=dict)
    by_title: dict[str, list[Product]] = field(default_factory=dict)
    imdb_batches: list[list[str]] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    refuse_after: int | None = None

    def products_by_imdb(self, imdb_ids):
        ids = list(imdb_ids)
        assert len(ids) <= MAX_IMDB_IDS, f"batch of {len(ids)} exceeds the API cap"
        if self.refuse_after is not None and len(self.imdb_batches) >= self.refuse_after:
            raise RateLimited("prices")
        self.imdb_batches.append(ids)
        return {tt: self.by_imdb[tt] for tt in ids if tt in self.by_imdb}

    def search(self, title, limit=5):
        self.searches.append(title)
        return self.by_title.get(title, [])


@pytest.fixture
def cheapcharts() -> FakeCheapCharts:
    return FakeCheapCharts()


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict:
    return {}


# Given ---------------------------------------------------------------------


@given(parsers.parse('a film "{title}" ({year:d}) holding imdb id "{tt}"'))
def seed_film(repo, today, films, title, year, tt):
    film_id = repo.create_film(Film(title, year, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "imdb", tt, today)
    films[title] = film_id


@given(parsers.parse('CheapCharts maps "{tt}" to itunes id "{itunes_id}"'))
def maps_imdb(cheapcharts, tt, itunes_id):
    cheapcharts.by_imdb[tt] = Product(itunes_id=itunes_id, title="Vertigo (1958)", year=1958, imdb_id=tt)


@given(parsers.parse('CheapCharts knows no imdb mapping for "{tt}"'))
def no_imdb_mapping(cheapcharts, tt):
    cheapcharts.by_imdb.pop(tt, None)


@given(parsers.parse('a CheapCharts search for "{query}" returns "{title}" ({year:d}) as itunes id "{itunes_id}"'))
def search_returns(cheapcharts, query, title, year, itunes_id):
    cheapcharts.by_title.setdefault(query, []).append(Product(itunes_id=itunes_id, title=title, year=year))


@given(parsers.parse('the film "{title}" already holds itunes id "{itunes_id}"'))
def already_holds(repo, today, films, title, itunes_id):
    repo.set_external_id(films[title], "itunes", itunes_id, today)


@given(parsers.parse('a film "{title}" already holds itunes id "{itunes_id}"'))
def other_film_holds(repo, today, films, title, itunes_id):
    film_id = repo.create_film(Film(title, None, None, ""))
    assert film_id is not None
    repo.set_external_id(film_id, "itunes", itunes_id, today)
    films[title] = film_id


@given(parsers.parse("{n:d} more films holding imdb ids that CheapCharts does not know"))
def more_films(repo, today, films, n):
    for i in range(n):
        title = f"Filler {i}"
        film_id = repo.create_film(Film(title, 1960 + i, None, ""))
        assert film_id is not None
        repo.set_external_id(film_id, "imdb", f"tt900000{i}", today)
        films[title] = film_id


# When ----------------------------------------------------------------------


@when("I resolve cheapcharts ids without applying")
def run_dry(repo, cheapcharts, today, result):
    result["report"] = resolve_itunes_ids(repo, cheapcharts, today, apply=False, log=lambda _m: None)


@when("I resolve cheapcharts ids with apply")
def run_apply(repo, cheapcharts, today, result):
    result["report"] = resolve_itunes_ids(repo, cheapcharts, today, apply=True, log=lambda _m: None)


# Then ----------------------------------------------------------------------


@then(parsers.parse("the report counts {scanned:d} scanned and {resolved:d} resolved"))
def counts(result, scanned, resolved):
    report = result["report"]
    assert (report.scanned, report.resolved) == (scanned, resolved)


@then(parsers.parse("the report counts {n:d} resolved by search"))
def counts_by_search(result, n):
    assert result["report"].by_search == n


@then(parsers.parse("the report counts {n:d} unmatched"))
def counts_unmatched(result, n):
    assert result["report"].unmatched == n


@then(parsers.parse("the report counts {n:d} ambiguous"))
def counts_ambiguous(result, n):
    assert result["report"].ambiguous == n


@then(parsers.parse("the report counts {n:d} held"))
def counts_held(result, n):
    assert result["report"].held == n


@then(parsers.parse('the film "{title}" holds itunes id "{itunes_id}"'))
def holds_itunes(repo, films, title, itunes_id):
    assert repo.external_ids_for(films[title]).get("itunes") == itunes_id


@then(parsers.parse('the film "{title}" still holds no itunes id'))
def no_itunes(repo, films, title):
    assert "itunes" not in repo.external_ids_for(films[title])


@then(parsers.parse('CheapCharts was never asked about "{tt}"'))
def never_asked(cheapcharts, tt):
    assert all(tt not in batch for batch in cheapcharts.imdb_batches), cheapcharts.imdb_batches


@then(parsers.parse("CheapCharts was asked in {batches:d} batches of at most {size:d} imdb ids"))
def batched(cheapcharts, batches, size):
    assert len(cheapcharts.imdb_batches) == batches, cheapcharts.imdb_batches
    assert all(len(batch) <= size for batch in cheapcharts.imdb_batches)


@given(parsers.parse('the film "{title}" is directed by "{director}"'))
def set_director(repo, films, title, director):
    with repo._conn() as c:
        c.execute("UPDATE films SET director = ? WHERE id = ?", (director, films[title]))


@given(
    parsers.parse(
        'a CheapCharts search for "{query}" returns "{title}" ({year:d}) by "{director}" as itunes id "{itunes_id}"'
    )
)
def search_returns_with_director(cheapcharts, query, title, year, director, itunes_id):
    cheapcharts.by_title.setdefault(query, []).append(
        Product(itunes_id=itunes_id, title=title, year=year, director=director)
    )


@given(parsers.parse("CheapCharts starts refusing after {n:d} batch"))
def refuse_after(cheapcharts, n):
    cheapcharts.refuse_after = n


@then("the report is marked rate limited")
def marked_rate_limited(result):
    assert result["report"].rate_limited is True
