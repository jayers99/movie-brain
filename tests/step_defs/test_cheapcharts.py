from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import requests
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.cheapcharts import audit_itunes_ids, recheck_itunes_ids, resolve_itunes_ids
from movie_brain.domain.models import Film
from movie_brain.infrastructure.cheapcharts import MAX_IMDB_IDS, Product, ProductFiling, RateLimited

scenarios("../features/cheapcharts.feature")


@dataclass
class FakeCheapCharts:
    """Only the two calls the resolver is allowed to make."""

    by_imdb: dict[str, Product] = field(default_factory=dict)
    by_title: dict[str, list[Product]] = field(default_factory=dict)
    imdb_batches: list[list[str]] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    removed: dict[str, bool] = field(default_factory=dict)
    filings: dict[str, ProductFiling] = field(default_factory=dict)
    filing_calls: int = 0
    refuse_filing_after: int | None = None
    refuse_after: int | None = None
    down: bool = False

    def products_by_imdb(self, imdb_ids):
        ids = list(imdb_ids)
        if self.down:
            raise requests.ConnectionError("cheapcharts down")
        assert len(ids) <= MAX_IMDB_IDS, f"batch of {len(ids)} exceeds the API cap"
        if self.refuse_after is not None and len(self.imdb_batches) >= self.refuse_after:
            raise RateLimited("prices")
        self.imdb_batches.append(ids)
        return {tt: self.by_imdb[tt] for tt in ids if tt in self.by_imdb}

    def search(self, title, limit=5):
        self.searches.append(title)
        return self.by_title.get(title, [])

    def filing(self, itunes_id):
        """Unless a step says otherwise a product is filed under the Background film's own id —
        the ordinary case, where the search found the right page."""
        self.filing_calls += 1
        if self.refuse_filing_after is not None and self.filing_calls > self.refuse_filing_after:
            raise RateLimited("detail")
        return self.filings.get(itunes_id, ProductFiling("tt0052357", ()))

    def is_removed(self, itunes_id):
        """None = CheapCharts has nothing to say about this product."""
        return self.removed.get(itunes_id)


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


@given(parsers.parse('CheapCharts maps "{tt}" to a REMOVED itunes id "{itunes_id}"'))
def maps_imdb_removed(cheapcharts, tt, itunes_id):
    cheapcharts.by_imdb[tt] = Product(itunes_id=itunes_id, title="Vertigo (1958)", year=1958, imdb_id=tt, removed=True)


@given(parsers.parse('CheapCharts files product "{itunes_id}" under imdb id "{tt}"'))
def filed_under(cheapcharts, itunes_id, tt):
    cheapcharts.filings[itunes_id] = ProductFiling(tt, ())


@given(parsers.parse('CheapCharts files product "{itunes_id}" under imdb id "{tt}", directed by "{name}"'))
def filed_under_with_director(cheapcharts, itunes_id, tt, name):
    cheapcharts.filings[itunes_id] = ProductFiling(tt, (name,))


@given(parsers.parse('CheapCharts files product "{itunes_id}" under no imdb id, directed by "{name}"'))
def filed_without_imdb(cheapcharts, itunes_id, name):
    cheapcharts.filings[itunes_id] = ProductFiling(None, (name,))


@given(parsers.parse("CheapCharts stops answering product lookups after {n:d}"))
def filing_refuses_after(cheapcharts, n):
    cheapcharts.refuse_filing_after = n


@given(parsers.parse('CheapCharts says product "{itunes_id}" is {state}'))
def product_state(cheapcharts, itunes_id, state):
    assert state in ("removed", "live")
    cheapcharts.removed[itunes_id] = state == "removed"


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


@when("I resolve cheapcharts ids with apply, retrying the misses")
def run_apply_retry(repo, cheapcharts, today, result):
    result["report"] = resolve_itunes_ids(repo, cheapcharts, today, apply=True, retry_misses=True, log=lambda _m: None)


@when(parsers.parse('CheapCharts maps "{tt}" to itunes id "{itunes_id}"'))
def maps_imdb_later(cheapcharts, tt, itunes_id):
    maps_imdb(cheapcharts, tt, itunes_id)


@given("CheapCharts cannot be reached")
def cc_down(cheapcharts):
    cheapcharts.down = True


@when("CheapCharts can be reached again")
def cc_up(cheapcharts):
    cheapcharts.down = False


@then(parsers.parse("the second run scanned {n:d} films"))
def second_scanned(result, n):
    assert result["report"].scanned == n


@then(parsers.parse('CheapCharts was asked about "{tt}" {n:d} time'))
def asked_times(cheapcharts, tt, n):
    assert sum(tt in batch for batch in cheapcharts.imdb_batches) == n


@when("I recheck cheapcharts ids with apply")
def run_recheck_apply(repo, cheapcharts, today, result):
    result["report"] = recheck_itunes_ids(repo, cheapcharts, today, apply=True, log=lambda _m: None)


@when("I recheck cheapcharts ids without applying")
def run_recheck_dry(repo, cheapcharts, today, result):
    result["report"] = recheck_itunes_ids(repo, cheapcharts, today, apply=False, log=lambda _m: None)


@when(parsers.parse('I recheck cheapcharts ids with apply after "{title}"'))
def run_recheck_apply_after(repo, cheapcharts, today, films, result, title):
    result["report"] = recheck_itunes_ids(
        repo, cheapcharts, today, apply=True, after=films[title], log=lambda _m: None
    )


@when("I audit the stored cheapcharts ids")
def run_audit(repo, cheapcharts, result):
    result["lines"] = []
    result["report"] = audit_itunes_ids(repo, cheapcharts, log=result["lines"].append)


@when(parsers.parse('I audit the stored cheapcharts ids after "{title}"'))
def run_audit_after(repo, cheapcharts, films, result, title):
    result["lines"] = []
    result["report"] = audit_itunes_ids(repo, cheapcharts, after=films[title], log=result["lines"].append)


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


@then(parsers.parse("the report counts {n:d} replaced"))
def counts_replaced(result, n):
    assert result["report"].replaced == n


@then(parsers.parse("the report counts {n:d} dropped"))
def report_dropped(result, n):
    assert result["report"].dropped == n


@then(parsers.parse("the report counts {n:d} dead"))
def counts_dead(result, n):
    assert result["report"].dead == n


@then(parsers.parse("the report counts {n:d} live"))
def counts_live(result, n):
    assert result["report"].live == n


@then(parsers.parse("the report counts {n:d} scanned"))
def counts_scanned_only(result, n):
    assert result["report"].scanned == n


@then(parsers.parse('the film "{title}" holds exactly one itunes id'))
def holds_exactly_one_itunes(repo, films, title):
    values = [v for a, v in repo.external_ids_all(films[title]) if a == "itunes"]
    assert len(values) == 1, values


@then(parsers.parse('the film "{title}" holds every itunes id "{a}" and "{b}"'))
def holds_every_itunes(repo, films, title, a, b):
    values = [v for auth, v in repo.external_ids_all(films[title]) if auth == "itunes"]
    assert sorted(values) == sorted([a, b]), values


@then("CheapCharts was never searched")
def never_searched(cheapcharts):
    assert cheapcharts.searches == []


@then(parsers.parse("the audit counts {scanned:d} scanned and {suspect:d} suspect"))
def audit_counts(result, scanned, suspect):
    assert (result["report"].scanned, result["report"].suspects) == (scanned, suspect)


@then(parsers.parse("the audit counts {n:d} unverified"))
def audit_unverified(result, n):
    assert result["report"].unverified == n


@then(parsers.parse('the audit names "{title}" with itunes id "{itunes_id}"'))
def audit_names(result, title, itunes_id):
    assert any(title in line and itunes_id in line for line in result["lines"]), result["lines"]


@then(parsers.parse('the audit is rate limited and resumes after "{title}"'))
def audit_resume(result, films, title):
    assert result["report"].rate_limited is True
    assert result["report"].last_film_id == films[title]


@then(parsers.parse("the audit counts {n:d} misfiled"))
def audit_misfiled(result, n):
    assert result["report"].misfiled == n

