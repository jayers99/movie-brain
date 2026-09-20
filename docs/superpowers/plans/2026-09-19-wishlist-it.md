# Wishlist it Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One drawer button puts a film on the owner's CheapCharts wishlist at its lowest-ever price plus one dollar, and a heart on the row shows which films are already there.

**Architecture:** A new one-row table `cheapcharts_wishlist` (watchlist pattern, migration 027) holds the hearts, with exactly two writers: the button and the wholesale wishlist read. `infrastructure/cheapcharts.py` gains the public price-history read and a `CheapChartsAccount` (login, read, add, set-target over plain `requests`); `application/wishlist.py` orchestrates them behind two Protocols so the web layer can be driven by fakes; `POST /api/films/<id>/wishlist` is the only new route. No price is ever stored or shown.

**Tech Stack:** Python 3.12, Flask, SQLite, `requests`, `tomllib`, Typer, vanilla JS; tests with pytest, `responses`, Playwright.

**Spec:** `docs/superpowers/briefs/2026-09-19-price-watch/brief.md` (version 1.0 frozen; this plan's new agent defaults are amended into it as 1.1 by Task 7). Approved preview: `docs/superpowers/briefs/2026-09-19-price-watch/mockup-3.html` — where they disagree the brief wins.

## Global Constraints

- **Nothing touches the owner's real CheapCharts account during the build — no login, no read, no write.** Every test mocks HTTP with `responses` or uses the fakes this plan defines. Never run `scripts/discovery/cheapcharts_wishlist_probe.py`.
- Never print, log, fixture or commit a credential, session token, customer id, username or email. Never read `~/.config/movie-brain/credentials.toml`. Test credentials are the invented `someone@example.test` / `hunter2`.
- Exceptions raised by the account code carry OUR wording only — never the API's `message` text or a response body (the login response carries the account's email).
- Never run against the live DB: no `migrate --apply`, no `cheapcharts resolve --apply`, no `dashboard` without `MOVIE_BRAIN_CONFIG_DIR` pointed at a scratch directory. No merge, no push.
- Exact on-screen wording (hard taste boundary): `♡ Wishlist it` · `Reaching CheapCharts…` · `♥ Wishlisted` · `Couldn't reach CheapCharts.` · `Try again` · heart tooltip `On your CheapCharts wishlist`. No price anywhere on screen. Nothing new on a row that is not wishlisted.
- Heart: `♥`, class `icon-wish`, colour `#c2410c`, 13px, LAST among the row's badges.
- The button appears only when the film holds an `itunes` id (`cheapcharts_url` non-null), is not owned, and is not wishlisted.
- Target = lowest price ever + `$1.00`; a one-off low counts; both SD and HD targets set to the same value; HD history first, SD history when HD is empty, no history = failure.
- Migration number 027; never edit an applied migration; wrap in `BEGIN`/`COMMIT`; insert the `schema_version` row.
- Match surrounding code: comment density, naming, idiom. Do not hard-wrap prose in `.md` files.
- Gates after every task, all four must pass: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy`, `uv run python scripts/matching_benchmark.py --assert-dominance && uv run python scripts/thumbprint_benchmark.py --assert`.
- Commits: one brief line on the WHY, ending with the trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `migrations/027_cheapcharts_wishlist.sql` (create) | the hearts table |
| `src/movie_brain/domain/wishlist.py` (create) | the target rule: `TARGET_MARKUP`, `target_price` |
| `src/movie_brain/domain/models.py` (modify) | `FilmView.wishlisted` |
| `src/movie_brain/infrastructure/database.py` (modify) | `wishlisted_film_ids`, `mark_wishlisted`, `replace_wishlist`, `itunes_id_for`, view wiring, `merge_film` |
| `src/movie_brain/infrastructure/cheapcharts.py` (modify) | `Pacer`, `parse_evolution`, `CheapChartsClient.lowest_price`, `CheapChartsError`/`CheapChartsRefused`, `CheapChartsAccount` |
| `src/movie_brain/infrastructure/credentials.py` (create) | `load_credentials(config, site)` from `<config_dir>/credentials.toml` |
| `src/movie_brain/infrastructure/config.py` (modify) | `Config.credentials_file` |
| `src/movie_brain/application/wishlist.py` (create) | Protocols, `WishlistGateway`, `WishlistError`, `NotForSale`, `wishlist_film`, `refresh_wishlist` |
| `src/movie_brain/web/app.py` (modify) | `create_app(..., wishlist=None)`, `POST /api/films/<id>/wishlist` |
| `src/movie_brain/web/static/app.js`, `app.css` (modify) | heart, button, busy/done/failed states |
| `src/movie_brain/cli.py` (modify) | `cheapcharts wishlist` verb, dashboard start-up refresh |
| `tests/unit/test_wishlist.py` (create) | domain, repository, application |
| `tests/unit/test_cheapcharts_account.py` (create) | price history, pacer, credentials, account |
| `tests/web/test_wishlist_api.py` (create) | the route, including the acceptance examples over mocked HTTP |
| `tests/web/test_wishlist_page.py` (create) | Playwright: heart, button, states |
| `tests/web/conftest.py` (modify) | seed + fake gateway |

---

### Task 1: Thin end-to-end slice — button → route → fake CheapCharts → heart on the row

Acceptance example this slice is tied to: **Do the Right Thing — lowest $2.99 → click → added at $3.99, the button becomes "♥ Wishlisted", the heart appears on the row.**

**Files:**
- Create: `migrations/027_cheapcharts_wishlist.sql`, `src/movie_brain/domain/wishlist.py`, `src/movie_brain/application/wishlist.py`, `tests/unit/test_wishlist.py`, `tests/web/test_wishlist_api.py`, `tests/web/test_wishlist_page.py`
- Modify: `src/movie_brain/domain/models.py` (FilmView), `src/movie_brain/infrastructure/database.py`, `src/movie_brain/web/app.py`, `src/movie_brain/web/static/app.js`, `src/movie_brain/web/static/app.css`, `tests/web/conftest.py`

**Interfaces:**
- Consumes: `Repository.get_view`, `Repository.set_external_id(film_id, "itunes", value, day)`, `Repository.mark_owned`, `_ONE_ROW_TABLES`.
- Produces:
  - `domain/wishlist.py`: `TARGET_MARKUP: Decimal`, `target_price(low: Decimal) -> Decimal`
  - `Repository.wishlisted_film_ids() -> set[int]`, `Repository.mark_wishlisted(film_id: int, today: date) -> bool | None` (None = no such film), `Repository.itunes_id_for(film_id: int) -> str | None`
  - `FilmView.wishlisted: bool`
  - `application/wishlist.py`: `PriceSource` and `WishlistAccount` Protocols, `WishlistGateway(prices, account)`, `WishlistError`, `NotForSale`, `wishlist_film(repo, gateway, film_id, today) -> None`
  - `create_app(repo, today, embedder, lists_dir, wishlist: WishlistGateway | None = None)`; `POST /api/films/<int:film_id>/wishlist` → `200 {"wishlisted": true}` · `404 {"error": "not found"}` · `409 {"error": "not for sale"}` · `502 {"error": "Couldn't reach CheapCharts."}`
  - `tests/web/conftest.py`: `FakePrices`, `FakeAccount`, module-level `FAKE_ACCOUNT`, and seed ids `CHARLIE_ITUNES = "273058482"`, `DELTA_ITUNES = "366474905"`, `ECHO_ITUNES = "495816081"`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_wishlist.py`:

```python
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from movie_brain.application.wishlist import NotForSale, WishlistError, WishlistGateway, wishlist_film
from movie_brain.domain.models import Film
from movie_brain.domain.wishlist import target_price

D = date(2026, 9, 19)


def _film(repo, title, year, itunes=None):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    if itunes:
        repo.set_external_id(fid, "itunes", itunes, D)
    return fid


class FakePrices:
    def __init__(self, lows):
        self.lows = lows

    def lowest_price(self, itunes_id):
        return self.lows.get(itunes_id)


class FakeAccount:
    def __init__(self, listed=()):
        self.calls = []
        self.listed = list(listed)

    def add_item(self, itunes_id):
        self.calls.append(("add", itunes_id))
        if itunes_id not in self.listed:
            self.listed.append(itunes_id)
        return True

    def set_target(self, itunes_id, target):
        self.calls.append(("target", itunes_id, target))

    def wishlist_ids(self):
        self.calls.append(("read",))
        return list(self.listed)


def test_target_is_the_lowest_price_ever_plus_one_dollar():
    assert target_price(Decimal("2.99")) == Decimal("3.99")  # Do the Right Thing: a one-off low still counts
    assert target_price(Decimal("7.99")) == Decimal("8.99")  # Mulholland Dr.


def test_mark_wishlisted_round_trips_and_reports_missing(repo):
    a = _film(repo, "Alpha", 1950)
    assert repo.get_view(a, D).wishlisted is False
    assert repo.mark_wishlisted(a, D) is True
    assert repo.mark_wishlisted(a, D) is True  # idempotent
    assert repo.wishlisted_film_ids() == {a}
    assert repo.get_view(a, D).wishlisted is True
    assert [v.wishlisted for v in repo.list_views("criterion", D) if v.id == a] == [True]
    assert repo.mark_wishlisted(999, D) is None


def test_itunes_id_for_reads_the_stored_store_id(repo):
    a, b = _film(repo, "Alpha", 1950, "282538466"), _film(repo, "Beta", 1960)
    assert repo.itunes_id_for(a) == "282538466" and repo.itunes_id_for(b) is None


def test_a_click_adds_the_film_at_lowest_plus_one_and_marks_it(repo):
    dtrt = _film(repo, "Do the Right Thing", 1989, "282538466")
    account = FakeAccount()
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), dtrt, D)
    assert ("add", "282538466") in account.calls
    assert ("target", "282538466", Decimal("3.99")) in account.calls
    assert repo.wishlisted_film_ids() == {dtrt}


def test_an_owned_or_unsold_film_is_refused_before_cheapcharts_is_asked(repo):
    owned = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(owned, D)
    unsold = _film(repo, "La Dolce Vita", 1960)
    account = FakeAccount()
    gateway = WishlistGateway(FakePrices({}), account)
    for fid in (owned, unsold):
        with pytest.raises(NotForSale):
            wishlist_film(repo, gateway, fid, D)
    with pytest.raises(LookupError):
        wishlist_film(repo, gateway, 999, D)
    assert account.calls == [] and repo.wishlisted_film_ids() == set()


def test_no_price_history_at_all_fails_and_marks_nothing(repo):
    fid = _film(repo, "Obscure", 1970, "111")
    account = FakeAccount()
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == [] and repo.wishlisted_film_ids() == set()


def test_an_already_wishlisted_film_is_left_alone(repo):
    """The button never shows on it; the route still must not touch a hand-set target."""
    fid = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(fid, D)
    account = FakeAccount()
    wishlist_film(repo, WishlistGateway(FakePrices({"273058482": Decimal("4.99")}), account), fid, D)
    assert account.calls == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/unit/test_wishlist.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'movie_brain.application.wishlist'`.

- [ ] **Step 3: Migration, domain rule, repository, read model**

Create `migrations/027_cheapcharts_wishlist.sql`:

```sql
-- "Wishlist it" (brief 2026-09-19-price-watch): which films are on the owner's CheapCharts
-- wishlist. The wishlist itself lives on CheapCharts; this is the local mirror that draws the
-- heart. Watchlist pattern: one row per film, exactly two writers — the drawer button
-- (mark_wishlisted) and the wholesale wishlist read (replace_wishlist). No price is stored.
-- merge_film moves it survivor-wins (_ONE_ROW_TABLES).
BEGIN;
CREATE TABLE cheapcharts_wishlist (
    film_id  INTEGER PRIMARY KEY REFERENCES films(id),
    added_on TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (27);
COMMIT;
```

Create `src/movie_brain/domain/wishlist.py`:

```python
"""The CheapCharts wishlist target rule (brief 2026-09-19-price-watch): the owner's own ruling is
the film's lowest price EVER plus one dollar — a low that happened exactly once still counts
(Do the Right Thing: $2.99 once, $4.99 thirty-two times → $3.99). No price is stored or shown;
the low is read at the moment of the click."""

from __future__ import annotations

from decimal import Decimal

TARGET_MARKUP = Decimal("1.00")


def target_price(low: Decimal) -> Decimal:
    return low + TARGET_MARKUP
```

In `src/movie_brain/domain/models.py`, add to `FilmView` directly after the `old_rating` field:

```python
    # On my CheapCharts wishlist (migration 027). The drawer's "Wishlist it" button and the
    # wholesale wishlist read are the only writers; the list itself lives on CheapCharts.
    wishlisted: bool = False
```

In `src/movie_brain/infrastructure/database.py`:

1. Append `"cheapcharts_wishlist",` to `_ONE_ROW_TABLES` (after `"rank_mark"`).
2. Next to `_rank_mark_ids`, add:

```python
def _wishlisted_ids(c: sqlite3.Connection) -> set[int]:
    return {int(r["film_id"]) for r in c.execute("SELECT film_id FROM cheapcharts_wishlist")}
```

3. `_row_to_view` gains a keyword `wishlisted: bool = False` (after `old_rating`) and passes `wishlisted=wishlisted` into `FilmView(...)`.
4. `list_views`: add `wi = _wishlisted_ids(c)` beside `rm = _rank_mark_ids(c)` and pass `wishlisted=r["id"] in wi`; `get_view`: pass `wishlisted=row["id"] in _wishlisted_ids(c)`.
5. In `merge_film`'s `_ONE_ROW_TABLES` loop, after the `rank_mark` branch:

```python
                    elif table == "cheapcharts_wishlist":
                        kept[table] = {"added_on": loser_row["added_on"]}
```

6. After the `rank_mark` methods, add:

```python
    # cheapcharts_wishlist ("Wishlist it", brief 2026-09-19-price-watch) ----------
    def wishlisted_film_ids(self) -> set[int]:
        with self._conn() as c:
            return _wishlisted_ids(c)

    def mark_wishlisted(self, film_id: int, today: date) -> bool | None:
        """The button's write: idempotent, None when the film does not exist. There is no
        un-mark — a heart only comes off when a wishlist read no longer holds the film."""
        with self._conn() as c:
            if c.execute("SELECT 1 FROM films WHERE id = ?", (film_id,)).fetchone() is None:
                return None
            c.execute(
                "INSERT OR IGNORE INTO cheapcharts_wishlist (film_id, added_on) VALUES (?, ?)",
                (film_id, today.isoformat()),
            )
            return True

    def itunes_id_for(self, film_id: int) -> str | None:
        """The store id behind this film's CheapCharts link. `itunes` is a claim authority and
        may repeat; this is the same scalar pick `_VIEW_SQL` makes, so the wishlisted product is
        the one the drawer links to."""
        with self._conn() as c:
            row = c.execute(
                "SELECT value FROM external_ids WHERE film_id = ? AND authority = 'itunes'", (film_id,)
            ).fetchone()
            return None if row is None else str(row["value"])
```

- [ ] **Step 4: The application use case**

Create `src/movie_brain/application/wishlist.py`:

```python
""""Wishlist it" (brief 2026-09-19-price-watch): put a film on the owner's CheapCharts wishlist at
its lowest price ever plus one dollar, and mirror which films are there so the row can show a
heart. The wishlist itself stays on CheapCharts — it alerts his phone and makes buying easy.

The two Protocols are the seam: `infrastructure/cheapcharts.py` implements them over HTTP, and
the web tests drive the routes with fakes, so nothing in a test run can reach a real account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from movie_brain.domain.wishlist import target_price
from movie_brain.infrastructure.database import Repository


class PriceSource(Protocol):
    def lowest_price(self, itunes_id: str) -> Decimal | None: ...


class WishlistAccount(Protocol):
    def add_item(self, itunes_id: str) -> bool: ...

    def set_target(self, itunes_id: str, target: Decimal) -> None: ...

    def wishlist_ids(self) -> list[str]: ...


@dataclass(frozen=True)
class WishlistGateway:
    prices: PriceSource
    account: WishlistAccount


class WishlistError(Exception):
    """Anything that ends as the drawer's "Couldn't reach CheapCharts." — nothing was marked."""


class NotForSale(Exception):
    """Owned, or no store id: the button never shows on such a film, so this is a stale page."""


def wishlist_film(repo: Repository, gateway: WishlistGateway, film_id: int, today: date) -> None:
    view = repo.get_view(film_id, today)
    if view is None:
        raise LookupError(film_id)
    if view.wishlisted:
        return  # never re-target a film the last read already holds: an old hand-set target stays
    itunes_id = repo.itunes_id_for(film_id)
    if view.owned or itunes_id is None:
        raise NotForSale(film_id)
    low = gateway.prices.lowest_price(itunes_id)
    if low is None:
        raise WishlistError("no price history")
    gateway.account.add_item(itunes_id)
    gateway.account.set_target(itunes_id, target_price(low))
    repo.mark_wishlisted(film_id, today)
```

- [ ] **Step 5: Run the unit tests**

Run: `uv run pytest tests/unit/test_wishlist.py -q`
Expected: 7 passed.

- [ ] **Step 6: Write the failing route tests**

Create `tests/web/test_wishlist_api.py`:

```python
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from movie_brain.application.wishlist import WishlistError, WishlistGateway
from movie_brain.domain.models import Film
from movie_brain.web.app import create_app

D = date(2026, 9, 19)
DTRT = "282538466"


class FakePrices:
    def lowest_price(self, itunes_id):
        return Decimal("2.99")


class FakeAccount:
    def __init__(self):
        self.targets = {}
        self.down = False

    def add_item(self, itunes_id):
        if self.down:
            raise WishlistError("down")
        return True

    def set_target(self, itunes_id, target):
        self.targets[itunes_id] = target

    def wishlist_ids(self):
        return list(self.targets)


@pytest.fixture
def account():
    return FakeAccount()


@pytest.fixture
def client(repo, account):
    app = create_app(repo, today=lambda: D, wishlist=WishlistGateway(FakePrices(), account))
    app.testing = True
    return app.test_client()


def _film(repo, title, year, itunes=None):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    if itunes:
        repo.set_external_id(fid, "itunes", itunes, D)
    return fid


def test_a_click_wishlists_the_film_and_the_payload_carries_the_heart(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    assert client.get(f"/api/films/{fid}").get_json()["wishlisted"] is False
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": True}
    assert account.targets == {DTRT: Decimal("3.99")}
    assert client.get(f"/api/films/{fid}").get_json()["wishlisted"] is True
    assert [f["wishlisted"] for f in client.get("/api/films").get_json() if f["id"] == fid] == [True]


def test_unknown_owned_and_unsold_films_are_refused(client, repo, account):
    assert client.post("/api/films/999/wishlist").status_code == 404
    unsold = _film(repo, "La Dolce Vita", 1960)
    owned = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(owned, D)
    for fid in (unsold, owned):
        r = client.post(f"/api/films/{fid}/wishlist")
        assert r.status_code == 409 and r.get_json() == {"error": "not for sale"}
    assert account.targets == {}


def test_a_cheapcharts_failure_is_the_one_failure_line_and_marks_nothing(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    account.down = True
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    assert repo.wishlisted_film_ids() == set()


def test_with_no_credentials_configured_the_click_fails_the_same_way(repo):
    app = create_app(repo, today=lambda: D)  # wishlist=None: no credentials file
    app.testing = True
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    r = app.test_client().post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
```

Run: `uv run pytest tests/web/test_wishlist_api.py -q`
Expected: FAIL — `create_app() got an unexpected keyword argument 'wishlist'`.

- [ ] **Step 7: The route**

In `src/movie_brain/web/app.py`:

```python
import threading
...
from movie_brain.application.wishlist import NotForSale, WishlistError, WishlistGateway, wishlist_film
```

Add the parameter `wishlist: WishlistGateway | None = None,` to `create_app` after `lists_dir`. Inside `create_app`, beside `RANK_SOURCE`:

```python
    UNREACHABLE = "Couldn't reach CheapCharts."  # the brief's one failure line, whatever went wrong
    # One click at a time: a click is four or five paced calls to one account, and the dev
    # server is threaded.
    wishlist_lock = threading.Lock()
```

After the `toggle_watchlist` route:

```python
    @app.post("/api/films/<int:film_id>/wishlist")
    def post_wishlist(film_id: int) -> tuple[Response, int]:
        if wishlist is None:  # no credentials file: the same line as any other failure
            return jsonify({"error": UNREACHABLE}), 502
        try:
            with wishlist_lock:
                wishlist_film(repo, wishlist, film_id, today())
        except LookupError:
            return jsonify({"error": "not found"}), 404
        except NotForSale:
            return jsonify({"error": "not for sale"}), 409
        except WishlistError:
            return jsonify({"error": UNREACHABLE}), 502
        return jsonify({"wishlisted": True}), 200
```

Note the `wishlist is None` check runs before the film lookup on purpose — but the 404 test posts to a client WITH a gateway, so both orders pass; keep this order.

Run: `uv run pytest tests/web/test_wishlist_api.py -q`
Expected: 4 passed.

- [ ] **Step 8: Seed the dashboard fixture and write the failing Playwright test**

In `tests/web/conftest.py`, add near the top (after `TODAY`):

```python
# "Wishlist it": the live server is driven by fakes — no test run can reach a real account.
CHARLIE_ITUNES, DELTA_ITUNES, ECHO_ITUNES = "273058482", "366474905", "495816081"


class FakePrices:
    def lowest_price(self, itunes_id: str) -> Decimal | None:
        return Decimal("2.99")


class FakeAccount:
    """Delta's product always fails, so the failure line has a film of its own and the two
    click tests never depend on each other's order."""

    def __init__(self) -> None:
        self.targets: dict[str, Decimal] = {ECHO_ITUNES: Decimal("5.99")}

    def add_item(self, itunes_id: str) -> bool:
        time.sleep(0.4)  # long enough for "Reaching CheapCharts…" to be seen
        if itunes_id == DELTA_ITUNES:
            raise WishlistError("down")
        return True

    def set_target(self, itunes_id: str, target: Decimal) -> None:
        self.targets[itunes_id] = target

    def wishlist_ids(self) -> list[str]:
        return list(self.targets)


FAKE_ACCOUNT = FakeAccount()
```

with imports `from decimal import Decimal` and `from movie_brain.application.wishlist import WishlistError, WishlistGateway`.

At the end of `seed()`:

```python
    # "Wishlist it": Charlie is for sale and not wishlisted (the click film); Delta is for sale
    # and its add always fails (the failure line); Echo is already wishlisted and also carries a
    # list badge (the heart-comes-last film). All three hold a current Criterion listing, so the
    # store id changes nobody's reachability. Alpha stays owned + unwishlisted: no heart, no button.
    repo.set_external_id(ids["charlie (1970)"], "itunes", CHARLIE_ITUNES, TODAY)
    repo.set_external_id(ids["delta (1980)"], "itunes", DELTA_ITUNES, TODAY)
    repo.set_external_id(ids["echo (1990)"], "itunes", ECHO_ITUNES, TODAY)
    repo.mark_wishlisted(ids["echo (1990)"], TODAY)
```

In the `server` fixture, change the app construction to:

```python
    app = create_app(seeded_repo, today=lambda: TODAY, wishlist=WishlistGateway(FakePrices(), FAKE_ACCOUNT))
```

Run the whole web suite now (`uv run pytest tests/web -q`) — the three new store ids must not change any existing test. If one fails because a film gained a CheapCharts link, move that film's store id to a different seeded Criterion film and adjust the comment; do NOT weaken the existing test.

Create `tests/web/test_wishlist_page.py`:

```python
from __future__ import annotations

from decimal import Decimal

from playwright.sync_api import Page, expect

from tests.web.conftest import CHARLIE_ITUNES, FAKE_ACCOUNT

HEART_TIP = "On your CheapCharts wishlist"


def _open(dash: Page, title: str):
    dash.locator("tbody tr", has_text=title).first.click()
    body = dash.locator("#drawer-body")
    expect(body).to_contain_text(title)
    return body


def _row(dash: Page, title: str):
    return dash.locator("#films tbody tr", has_text=title).first


def test_one_click_wishlists_the_film_and_the_heart_arrives_on_its_row(dash: Page):
    expect(_row(dash, "Charlie").locator(".icon-wish")).to_have_count(0)
    body = _open(dash, "Charlie")
    button = body.locator("p.links button.wish-button")
    expect(button).to_have_text("♡ Wishlist it")
    button.click()
    expect(button).to_have_text("Reaching CheapCharts…")
    expect(button).to_be_disabled()
    expect(body.locator("p.links .wish-done")).to_have_text("♥ Wishlisted")
    expect(body.locator("p.links button.wish-button")).to_have_count(0)
    heart = _row(dash, "Charlie").locator(".icon-wish")
    expect(heart).to_have_text("♥")
    expect(heart).to_have_attribute("title", HEART_TIP)
    assert FAKE_ACCOUNT.targets[CHARLIE_ITUNES] == Decimal("3.99")  # lowest ever 2.99 + $1
    expect(body).not_to_contain_text("3.99")  # no prices on screen, anywhere
```

If `from tests.web.conftest import …` does not resolve (check how `tests/web/test_rank_page.py` or `tests/lists_fakes.py` is imported elsewhere and copy that idiom), expose the two names through a fixture instead — do not add `sys.path` hacks.

Run: `uv run pytest tests/web/test_wishlist_page.py -q`
Expected: FAIL — no `button.wish-button` in the drawer.

- [ ] **Step 9: The heart and the button**

In `src/movie_brain/web/static/app.css`, after the `.badge-watch` rule:

```css
.icon-wish { color:#c2410c; font-size:13px; margin-left:2px; }
#drawer p.links .wish-done { color:#c2410c; }
```

In `src/movie_brain/web/static/app.js`:

1. In `rowHtml`, the heart comes LAST among the badges — change `+ oldBadge(f) + watchBadge;` to:

```js
      + oldBadge(f) + watchBadge
      // On my CheapCharts wishlist — always the last mark on the row, and never a price.
      + (f.wishlisted ? ' <span class="icon-wish" title="On your CheapCharts wishlist">♥</span>' : '');
```

2. Above `detailHtml` (or beside the other small drawer helpers), add:

```js
  // "Wishlist it" (brief 2026-09-19-price-watch). One slot in the links row, after the CheapCharts
  // link: the done mark, or the button — shown only for a film the Apple store sells (it holds a
  // store id, hence a direct CheapCharts page) that I do not own. Anything else: nothing, no message.
  const WISH_BUTTON = '♡ Wishlist it';
  function wishHtml(d) {
    if (d.wishlisted) return ' <span class="wish" data-id="' + d.id + '"><span class="wish-done">♥ Wishlisted</span></span>';
    if (!d.cheapcharts_url || d.owned) return '';
    return ` <span class="wish" data-id="${d.id}"><button class="wish-button">${WISH_BUTTON}</button></span>`;
  }
```

3. In `detailHtml`'s `<p class="links">`, insert `${wishHtml(d)}` immediately before the closing `</p>` (after the CheapCharts link expression).

4. Beside the other `body.addEventListener('click', …)` handlers, add:

```js
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.wish-button'); if (!b || b.disabled) return;
    const slot = b.closest('.wish'); const id = Number(slot.dataset.id);
    // Four or five paced calls to CheapCharts: 5-10 s. The button says so and cannot be clicked twice.
    b.disabled = true; b.textContent = 'Reaching CheapCharts…';
    const r = await fetch(`/api/films/${id}/wishlist`, { method: 'POST' }).catch(() => null);
    if (!r || !r.ok) { b.disabled = false; b.textContent = WISH_BUTTON; return; }
    // Patch in place, as the toggles do: re-opening the drawer would desync closeDrawer()'s history bookkeeping.
    slot.innerHTML = '<span class="wish-done">♥ Wishlisted</span>';
    const film = state.films.find((f) => f.id === id);
    if (film) { film.wishlisted = true; applyFilters(); }
  });
```

(The failure line and "Try again" replace the plain reset in Task 5.)

Run: `uv run pytest tests/web/test_wishlist_page.py -q`
Expected: 1 passed.

- [ ] **Step 10: Gates and commit**

Run all four gates (Global Constraints). Expected: all pass; the suite count grows by 12.

```bash
git add migrations/027_cheapcharts_wishlist.sql src/movie_brain tests
git commit -m "one click wishlists a film at its lowest price plus a dollar: the thin path from the drawer button to a heart on the row, CheapCharts faked" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The lowest price ever, read from CheapCharts at the moment of the click

**Files:**
- Modify: `src/movie_brain/infrastructure/cheapcharts.py`
- Create: `tests/unit/test_cheapcharts_account.py`

**Interfaces:**
- Consumes: `CheapChartsClient`, `RateLimited`, `REFERER`, `COUNTRY`, `STORE`, `DELAY_S`.
- Produces:
  - `ACCOUNT_API = "https://buster.cheapcharts.de/v1/"`, `DETAIL_URL = ACCOUNT_API + "DetailData.php"`, `TIMEOUT_S = 30`
  - `class Pacer(delay_s: float = DELAY_S, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic)` with `wait() -> None`
  - `parse_evolution(text: str) -> list[Decimal]`
  - `CheapChartsClient(session=None, *, delay_s=DELAY_S, sleep=time.sleep, pacer: Pacer | None = None)` and `CheapChartsClient.lowest_price(itunes_id: str) -> Decimal | None` (satisfies `application.wishlist.PriceSource`)

The wire format, read from the live public endpoint on 2026-09-19 (no account involved): `results.movies` is ONE object; `priceHdEvolution` / `priceSdEvolution` are `~`-joined `YYYY-MM-DD:<sign><price>` entries, newest first, where the sign is the DIRECTION of the change (`-` a drop, `+` a rise) and the oldest entry carries no sign. The price is the absolute value.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cheapcharts_account.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest
import responses

from movie_brain.infrastructure.cheapcharts import (
    DETAIL_URL,
    CheapChartsClient,
    Pacer,
    RateLimited,
    parse_evolution,
)

# Do the Right Thing's real shape, shortened: $2.99 exactly once, $4.99 again and again.
DTRT_HD = "2026-08-12:+14.99~2026-08-04:-4.99~2025-08-26:+7.99~2025-08-26:-2.99~2025-08-20:+14.99~2019-02-19:9.99"


def _detail(hd: str | None, sd: str | None = None) -> dict:
    movie: dict[str, object] = {"title": "Do the Right Thing", "priceHd": 14.99, "priceHdIsLowest": 0}
    if hd is not None:
        movie["priceHdEvolution"] = hd
    if sd is not None:
        movie["priceSdEvolution"] = sd
    return {"results": {"movies": movie}}


def test_parse_evolution_reads_every_price_whatever_its_direction_sign():
    assert parse_evolution(DTRT_HD) == [Decimal(p) for p in ("14.99", "4.99", "7.99", "2.99", "14.99", "9.99")]
    assert parse_evolution("") == []
    assert parse_evolution("garbage~2020-01-01:~2020-01-02:+x") == []


@responses.activate
def test_lowest_price_is_computed_from_the_hd_history_and_a_one_off_low_counts():
    responses.get(DETAIL_URL, json=_detail(DTRT_HD, sd="2020-01-01:0.99"))
    assert CheapChartsClient().lowest_price("282538466") == Decimal("2.99")
    sent = responses.calls[0].request
    assert "idInStore=282538466" in sent.url and "itemType=movies" in sent.url
    assert sent.headers["Referer"] == "https://www.cheapcharts.com/"


@responses.activate
def test_lowest_price_falls_back_to_the_sd_history_when_there_is_no_hd_one():
    responses.get(DETAIL_URL, json=_detail(hd="", sd="2024-03-01:+9.99~2023-01-01:5.99"))
    assert CheapChartsClient().lowest_price("1") == Decimal("5.99")


@responses.activate
def test_lowest_price_is_none_with_no_history_at_all_or_no_such_product():
    responses.get(DETAIL_URL, json=_detail(hd=None))
    responses.get(DETAIL_URL, json={"results": {"movies": []}})
    client = CheapChartsClient(delay_s=0)
    assert client.lowest_price("1") is None
    assert client.lowest_price("2") is None


@responses.activate
def test_lowest_price_stops_on_a_429():
    responses.get(DETAIL_URL, status=429)
    with pytest.raises(RateLimited):
        CheapChartsClient().lowest_price("1")


def test_pacer_waits_only_the_remainder_since_the_last_call():
    now, slept = [100.0], []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    pacer = Pacer(1.5, sleep=sleep, clock=lambda: now[0])
    pacer.wait()  # first call: no wait
    now[0] += 0.5
    pacer.wait()  # 0.5 s later: waits the other 1.0
    now[0] += 60
    pacer.wait()  # a dashboard idle for a minute does not wait at all
    assert slept == [1.0]


@responses.activate
def test_a_client_given_a_pacer_paces_through_it():
    waits = []

    class Spy(Pacer):
        def wait(self) -> None:
            waits.append(1)

    responses.get(DETAIL_URL, json=_detail(DTRT_HD))
    CheapChartsClient(pacer=Spy()).lowest_price("1")
    assert waits == [1]
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_cheapcharts_account.py -q`
Expected: ImportError on `DETAIL_URL`.

- [ ] **Step 3: Implement**

In `src/movie_brain/infrastructure/cheapcharts.py`: add `from decimal import Decimal, InvalidOperation` to the imports; after `SEARCH_URL`:

```python
# The website's own API (one level above the GPT API). DetailData is public — only a Referer.
ACCOUNT_API = "https://buster.cheapcharts.de/v1/"
DETAIL_URL = ACCOUNT_API + "DetailData.php"
TIMEOUT_S = 30
```

After `RateLimited`:

```python
class Pacer:
    """At least `delay_s` between calls, measured on a clock: a dashboard that last called
    CheapCharts an hour ago does not wait, a click's five calls in a row each do. One Pacer is
    shared by the public client and the account, because they are one host."""

    def __init__(
        self,
        delay_s: float = DELAY_S,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.delay_s = delay_s
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self.delay_s - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


def parse_evolution(text: str) -> list[Decimal]:
    """Every price in a `priceHdEvolution` string: `~`-joined `YYYY-MM-DD:±price`, newest first.
    The sign is the DIRECTION of the change (`-` a drop, `+` a rise; the oldest entry has none),
    never part of the price. Unreadable entries are skipped, never guessed."""
    prices: list[Decimal] = []
    for entry in text.split("~"):
        _, sep, raw = entry.partition(":")
        if not sep:
            continue
        try:
            price = Decimal(raw.strip().lstrip("+-"))
        except InvalidOperation:
            continue
        if price.is_finite() and price > 0:
            prices.append(price)
    return prices
```

`CheapChartsClient.__init__` gains `pacer: Pacer | None = None` (keyword-only, after `sleep`) stored as `self._pacer`; `_get` becomes:

```python
    def _get(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        if self._pacer is not None:
            self._pacer.wait()
        elif self._requested:
            self._sleep(self.delay_s)
        self._requested = True
        resp = self.session.get(url, params=params, headers={"Referer": REFERER}, timeout=TIMEOUT_S)
```

(the rest unchanged). Add the method after `search`:

```python
    def lowest_price(self, itunes_id: str) -> Decimal | None:
        """The product's lowest price EVER, computed from its full history — never taken from
        `priceHdIsLowest`, so the number is ours. HD history first; a film with no HD history
        uses the SD one; None when there is no history at all (or no such product)."""
        data = self._get(
            DETAIL_URL, {"store": STORE, "country": COUNTRY, "itemType": "movies", "idInStore": itunes_id}
        )
        movie = (data.get("results") or {}).get("movies")
        if not isinstance(movie, dict):
            return None
        for field in ("priceHdEvolution", "priceSdEvolution"):
            prices = parse_evolution(str(movie.get(field) or ""))
            if prices:
                return min(prices)
        return None
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_cheapcharts_account.py tests/unit/test_cheapcharts.py -q`
Expected: all pass (the existing client tests prove the no-pacer path is unchanged).

- [ ] **Step 5: Gates and commit**

```bash
git add src/movie_brain/infrastructure/cheapcharts.py tests/unit/test_cheapcharts_account.py
git commit -m "the lowest price ever is computed from CheapCharts' own history at the click, so a one-off low counts and no price is ever stored" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Credentials file and the CheapCharts account (login, read, add, set target)

**Files:**
- Create: `src/movie_brain/infrastructure/credentials.py`
- Modify: `src/movie_brain/infrastructure/config.py`, `src/movie_brain/infrastructure/cheapcharts.py`, `tests/unit/test_cheapcharts_account.py`

**Interfaces:**
- Consumes: `Pacer`, `ACCOUNT_API`, `TIMEOUT_S`, `REFERER`, `RateLimited`, `Config`.
- Produces:
  - `Config.credentials_file -> Path` (`<config_dir>/credentials.toml`)
  - `load_credentials(config: Config, site: str) -> tuple[str, str] | None`
  - `ACCOUNT_URL`, `WISHLIST_URL`
  - `class CheapChartsError(Exception)`, `class CheapChartsRefused(CheapChartsError)`
  - `class CheapChartsAccount(username: str, password: str, session: requests.Session | None = None, *, pacer: Pacer | None = None)` with `wishlist_ids() -> list[str]`, `add_item(itunes_id: str) -> bool`, `set_target(itunes_id: str, target: Decimal) -> None` (satisfies `application.wishlist.WishlistAccount`)

The account API, proven on the owner's account 2026-09-19 (brief, "The account API"): form-encoded POSTs, JSON answers `{status: "success"|"error", message, …}` with HTTP 200 even on error. Login sends the SHA-256 HEX digest of the password, never the plain text. `itemType` MUST be `buymovies`. A bad token answers `status: error`, message "Couldn't load user. DeviceId or sessionToken unknown".

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cheapcharts_account.py`:

```python
import hashlib
from urllib.parse import parse_qs, urlsplit

from movie_brain.infrastructure.cheapcharts import (
    ACCOUNT_URL,
    WISHLIST_URL,
    CheapChartsAccount,
    CheapChartsError,
)
from movie_brain.infrastructure.config import Config
from movie_brain.infrastructure.credentials import load_credentials

USER, PASSWORD = "someone@example.test", "hunter2"  # invented — never a real account
LOGIN_OK = {
    "status": "success",
    "message": "already logged in",  # seen live: still a success
    "additionalInfo": {"sessionToken": "tok-1", "email": USER, "customerId": 42},
}
BAD_TOKEN = {"status": "error", "message": "Couldn't load user. DeviceId or sessionToken unknown"}


def _account() -> CheapChartsAccount:
    return CheapChartsAccount(USER, PASSWORD, pacer=Pacer(0))


def _action(call) -> str:
    return parse_qs(urlsplit(call.request.url).query)["action"][0]


def _body(call) -> dict[str, list[str]]:
    return parse_qs(call.request.body)


def test_credentials_are_read_from_the_one_toml_file_keyed_by_site(config_dir):
    config = Config(config_dir)
    assert load_credentials(config, "cheapcharts") is None  # no file
    config.credentials_file.write_text('[cheapcharts]\nusername = "someone@example.test"\npassword = "hunter2"\n')
    assert load_credentials(config, "cheapcharts") == (USER, PASSWORD)
    assert load_credentials(config, "othersite") is None  # no such section


def test_placeholder_or_half_filled_credentials_count_as_missing(config_dir):
    config = Config(config_dir)
    config.credentials_file.write_text('[cheapcharts]\nusername = "PUT-YOUR-EMAIL-HERE"\npassword = "x"\n')
    assert load_credentials(config, "cheapcharts") is None
    config.credentials_file.write_text('[cheapcharts]\nusername = "someone@example.test"\n')
    assert load_credentials(config, "cheapcharts") is None
    config.credentials_file.write_text("not toml [")
    assert load_credentials(config, "cheapcharts") is None


@responses.activate
def test_login_sends_the_sha256_digest_never_the_plain_password_and_reads_the_wishlist():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(
        WISHLIST_URL,
        json={"status": "success", "results": {"movies": [
            {"idInStore": 273058482, "initialPriceValue": 5.99, "initialHdPriceValue": 5.99, "customPrice": True},
            {"idInStore": "366474905", "initialPriceValue": 5.99, "initialHdPriceValue": 5.99},
        ]}},
    )
    assert _account().wishlist_ids() == ["273058482", "366474905"]
    login, read = responses.calls
    sent = _body(login)
    assert sent["password"] == [hashlib.sha256(PASSWORD.encode()).hexdigest()]
    assert PASSWORD not in login.request.body
    assert sent["email"] == [USER] and sent["action"] == ["login"] and sent["country"] == ["us"]
    assert sent["origin"] == ["website"] and sent["appEntity"] == ["cc_main_website"]
    assert _action(read) == "getShortItemList_v2" and _body(read)["sessionToken"] == ["tok-1"]
    assert login.request.headers["Referer"] == "https://www.cheapcharts.com/"


@responses.activate
def test_an_empty_wishlist_reads_as_no_films():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "results": {}})
    assert _account().wishlist_ids() == []


@responses.activate
def test_add_and_set_target_send_buymovies_and_the_same_price_for_sd_and_hd():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item added"})
    responses.post(WISHLIST_URL, json={"status": "success", "message": "init price was changed to 3.99"})
    account = _account()
    assert account.add_item("282538466") is True
    account.set_target("282538466", Decimal("3.99"))
    _, add, target = responses.calls
    q = parse_qs(urlsplit(add.request.url).query)
    assert q["action"] == ["addItem"] and q["itemType"] == ["buymovies"] and q["idInStore"] == ["282538466"]
    assert q["country"] == ["us"] and q["store"] == ["itunes"]
    q = parse_qs(urlsplit(target.request.url).query)
    assert q["action"] == ["changeInitPrice"] and q["itemType"] == ["buymovies"]
    assert q["customPrice"] == ["3.99"] and q["customPriceHd"] == ["3.99"]
    assert len([c for c in responses.calls if c.request.url.startswith(ACCOUNT_URL)]) == 1  # one login, token reused


@responses.activate
def test_a_refused_add_is_reported_not_raised_so_set_target_can_still_run():
    """The API's exact answer for a film already on the wishlist was never observed; whatever it
    is, the caller goes on to set the target and lets the read-back decide."""
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "error", "message": "whatever it says"})
    assert _account().add_item("1") is False


@responses.activate
def test_a_refused_set_target_raises():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "error", "message": "no such item"})
    with pytest.raises(CheapChartsError):
        _account().set_target("1", Decimal("3.99"))


@responses.activate
def test_an_expired_token_triggers_one_fresh_login_and_a_retry():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json=BAD_TOKEN)
    responses.post(ACCOUNT_URL, json={**LOGIN_OK, "additionalInfo": {"sessionToken": "tok-2"}})
    responses.post(WISHLIST_URL, json={"status": "success", "results": {"movies": []}})
    assert _account().wishlist_ids() == []
    assert _body(responses.calls[-1])["sessionToken"] == ["tok-2"]


@responses.activate
def test_a_token_refused_twice_is_an_error_even_for_add():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json=BAD_TOKEN)
    with pytest.raises(CheapChartsError):
        _account().add_item("1")


@responses.activate
def test_a_failed_login_raises_without_echoing_anything_the_api_said():
    responses.post(ACCOUNT_URL, json={"status": "error", "message": f"wrong password for {USER}"})
    with pytest.raises(CheapChartsError) as exc:
        _account().wishlist_ids()
    assert USER not in str(exc.value) and PASSWORD not in str(exc.value) and "wrong password" not in str(exc.value)


@responses.activate
def test_a_429_and_a_non_json_answer_both_stop_the_call():
    responses.post(ACCOUNT_URL, status=429)
    with pytest.raises(RateLimited):
        _account().wishlist_ids()
    responses.replace(responses.POST, ACCOUNT_URL, body="<html>maintenance</html>", status=200)
    with pytest.raises(CheapChartsError):
        _account().wishlist_ids()
```

(`responses` serves registered responses for one URL in registration order — the ordering above relies on it, as the existing CheapCharts tests do. If the 429/non-JSON test's `responses.replace` misbehaves, split it into two tests.)

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_cheapcharts_account.py -q`
Expected: ImportError on `ACCOUNT_URL`.

- [ ] **Step 3: Credentials**

In `src/movie_brain/infrastructure/config.py`, add to `Config`:

```python
    @property
    def credentials_file(self) -> Path:
        return self.config_dir / "credentials.toml"
```

Create `src/movie_brain/infrastructure/credentials.py`:

```python
"""Site logins live in ONE file outside the repo — `<config_dir>/credentials.toml`, mode 600, one
section per site with `username` and `password` (owner ruling 2026-09-19). The code reads it;
nothing secret is in the code, and nothing read here is ever printed or logged. The OMDb and
TMDB keys are NOT here yet — moving them is its own chore (backlog 21)."""

from __future__ import annotations

import tomllib

from movie_brain.infrastructure.config import Config

PLACEHOLDER = "PUT-YOUR-"  # the template the owner filled in; an untouched value is no credential


def load_credentials(config: Config, site: str) -> tuple[str, str] | None:
    """(username, password) for `site`, or None when the file, the section or either value is
    missing, unreadable, or still the placeholder."""
    path = config.credentials_file
    if not path.exists():
        return None
    try:
        section = tomllib.loads(path.read_text()).get(site)
    except (tomllib.TOMLDecodeError, OSError):
        return None
    if not isinstance(section, dict):
        return None
    username, password = section.get("username"), section.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        return None
    if PLACEHOLDER in username or PLACEHOLDER in password:
        return None
    return username, password
```

- [ ] **Step 4: The account**

In `src/movie_brain/infrastructure/cheapcharts.py`: add `import hashlib`; after `DETAIL_URL` add:

```python
ACCOUNT_URL = ACCOUNT_API + "Account.php"
WISHLIST_URL = ACCOUNT_API + "Wishlist.php"
```

After `RateLimited` (before `Pacer` is fine):

```python
class CheapChartsError(Exception):
    """The account API failed. The message is OUR wording only — never the API's text or a
    response body: the login answer carries the account's email and customer id."""


class CheapChartsRefused(CheapChartsError):
    """The API answered `status: error` for a reason other than the session token."""
```

At the end of the module (before `_year`):

```python
class CheapChartsAccount:
    """The owner's CheapCharts account over the website's own API — plain form POSTs, proven
    end to end on 2026-09-19 (brief 2026-09-19-price-watch). The session token lives in memory
    only; a missing or refused one triggers exactly one fresh login. Every answer is HTTP 200
    with `status: success|error`."""

    def __init__(
        self,
        username: str,
        password: str,
        session: requests.Session | None = None,
        *,
        pacer: Pacer | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self.session = session or requests.Session()
        self._pacer = pacer or Pacer()
        self._token: str | None = None

    def wishlist_ids(self) -> list[str]:
        """The iTunes ids of every film on the wishlist, in CheapCharts' order."""
        data = self._wishlist("getShortItemList_v2")
        movies = (data.get("results") or {}).get("movies") or []
        return [str(m["idInStore"]) for m in movies if isinstance(m, dict) and m.get("idInStore")]

    def add_item(self, itunes_id: str) -> bool:
        """False when the API refused — most likely the film is already there, but its wording
        for that was never observed, so the caller sets the target anyway and trusts the read-back."""
        try:
            self._wishlist("addItem", itemType="buymovies", idInStore=itunes_id)
        except CheapChartsRefused:
            return False
        return True

    def set_target(self, itunes_id: str, target: Decimal) -> None:
        """Both the SD and the HD target, the same value — what the proving add did."""
        price = f"{target:.2f}"
        self._wishlist(
            "changeInitPrice", itemType="buymovies", idInStore=itunes_id, customPrice=price, customPriceHd=price
        )

    def _wishlist(self, action: str, **extra: str) -> dict[str, Any]:
        params = {"country": COUNTRY, "store": STORE, "action": action, **extra}
        for attempt in (1, 2):
            token = self._token or self._login()
            data = self._post(WISHLIST_URL, params, {"sessionToken": token})
            if data.get("status") == "success":
                return data
            if "sessiontoken" not in str(data.get("message") or "").lower():
                raise CheapChartsRefused(action)
            self._token = None  # expired: one fresh login, then one retry
            if attempt == 2:
                break
        raise CheapChartsError(f"{action}: session token refused after a fresh login")

    def _login(self) -> str:
        data = self._post(
            ACCOUNT_URL,
            {},
            {
                "country": COUNTRY,
                "action": "login",
                "email": self._username,
                # The website never sends the plain password: its login form sends the SHA-256 hex digest.
                "password": hashlib.sha256(self._password.encode()).hexdigest(),
                "origin": "website",
                "appEntity": "cc_main_website",
            },
        )
        token = (data.get("additionalInfo") or {}).get("sessionToken") if data.get("status") == "success" else None
        if not isinstance(token, str) or not token:
            raise CheapChartsError("login refused")
        self._token = token
        return token

    def _post(self, url: str, params: dict[str, str], body: dict[str, str]) -> dict[str, Any]:
        self._pacer.wait()
        resp = self.session.post(url, params=params, data=body, headers={"Referer": REFERER}, timeout=TIMEOUT_S)
        if resp.status_code == 429:
            raise RateLimited(url)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            raise CheapChartsError("answer was not JSON") from None
        if not isinstance(data, dict):
            raise CheapChartsError("answer was not a JSON object")
        return data
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/unit/test_cheapcharts_account.py -q`
Expected: all pass.

- [ ] **Step 6: Gates and commit**

```bash
git add src/movie_brain/infrastructure tests/unit/test_cheapcharts_account.py
git commit -m "the software logs in and adds the film itself: CheapCharts' own account API over plain requests, credentials from the one config file, the token never leaving memory" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The full click and the wholesale wishlist read

A click always means "on my wishlist at lowest + $1": add AND set-target every time, then read the wishlist back. If the read succeeds, the read IS the truth (hearts replaced wholesale; the click succeeded only if the film is in it). If the read fails, the click succeeded only if the add itself was accepted. Nothing is marked otherwise, and every remote failure becomes `WishlistError`.

**Files:**
- Modify: `src/movie_brain/application/wishlist.py`, `src/movie_brain/infrastructure/database.py`, `tests/unit/test_wishlist.py`, `tests/web/test_wishlist_api.py`

**Interfaces:**
- Consumes: Task 1's `wishlist_film`, Protocols, `mark_wishlisted`; Task 2's `CheapChartsClient.lowest_price`, `DETAIL_URL`, `Pacer`; Task 3's `CheapChartsAccount`, `CheapChartsError`, `ACCOUNT_URL`, `WISHLIST_URL`; existing `RateLimited`.
- Produces:
  - `Repository.replace_wishlist(itunes_ids: Iterable[str], today: date) -> int` (films now hearted)
  - `RefreshReport(on_cheapcharts: int, known: int)`, `refresh_wishlist(repo: Repository, account: WishlistAccount, today: date) -> RefreshReport` (raises `WishlistError`)
  - final `wishlist_film` semantics (signature unchanged)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_wishlist.py`:

```python
import requests

from movie_brain.application.wishlist import RefreshReport, refresh_wishlist
from movie_brain.infrastructure.cheapcharts import CheapChartsError, RateLimited


def test_replace_wishlist_is_wholesale_and_keeps_the_date_of_a_film_that_stays(repo):
    stays, goes, arrives = _film(repo, "A", 1950, "1"), _film(repo, "B", 1951, "2"), _film(repo, "C", 1952, "3")
    repo.replace_wishlist(["1", "2", "999"], date(2026, 9, 1))  # 999: on CheapCharts, unknown here
    assert repo.wishlisted_film_ids() == {stays, goes}
    assert repo.replace_wishlist(["1", "3"], D) == 2  # B was bought or removed on CheapCharts
    assert repo.wishlisted_film_ids() == {stays, arrives}
    with repo._conn() as c:
        rows = dict(c.execute("SELECT film_id, added_on FROM cheapcharts_wishlist").fetchall())
    assert rows == {stays: "2026-09-01", arrives: "2026-09-19"}


def test_a_film_holding_two_store_ids_is_hearted_by_either(repo):
    fid = _film(repo, "A", 1950, "1")
    repo.set_external_id(fid, "itunes", "2", D)
    assert repo.replace_wishlist(["2"], D) == 1 and repo.wishlisted_film_ids() == {fid}


def test_refresh_reads_the_wishlist_and_reports_how_much_of_it_we_know(repo):
    known = _film(repo, "The Leopard", 1963, "273058482")
    report = refresh_wishlist(repo, FakeAccount(listed=["273058482", "555", "556"]), D)
    assert report == RefreshReport(on_cheapcharts=3, known=1) and repo.wishlisted_film_ids() == {known}


def test_a_failed_refresh_keeps_the_last_known_hearts(repo):
    fid = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(fid, D)

    class Down(FakeAccount):
        def wishlist_ids(self):
            raise requests.ConnectionError("offline")

    with pytest.raises(WishlistError):
        refresh_wishlist(repo, Down(), D)
    assert repo.wishlisted_film_ids() == {fid}


def test_a_click_reads_the_wishlist_back_and_replaces_every_heart(repo):
    dtrt = _film(repo, "Do the Right Thing", 1989, "282538466")
    stale = _film(repo, "Bought Since", 1990, "777")
    leopard = _film(repo, "The Leopard", 1963, "273058482")
    repo.mark_wishlisted(stale, D)
    account = FakeAccount(listed=["273058482"])
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), account), dtrt, D)
    assert [c[0] for c in account.calls] == ["add", "target", "read"]
    assert repo.wishlisted_film_ids() == {dtrt, leopard}


def test_a_refused_add_still_sets_the_target_and_the_read_back_decides(repo):
    """A half-finished earlier click (added, target never set) is repaired by Try again."""
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")

    class AlreadyThere(FakeAccount):
        def add_item(self, itunes_id):
            self.calls.append(("add", itunes_id))
            return False

    there = AlreadyThere(listed=["282538466"])
    wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), there), fid, D)
    assert ("target", "282538466", Decimal("3.99")) in there.calls and repo.wishlisted_film_ids() == {fid}

    other = _film(repo, "Mulholland Dr.", 2001, "1753833311")
    absent = AlreadyThere(listed=[])  # refused for some other reason: the read-back does not hold it
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(FakePrices({"1753833311": Decimal("7.99")}), absent), other, D)
    assert other not in repo.wishlisted_film_ids()


def test_when_the_read_back_fails_an_accepted_add_is_believed_and_a_refused_one_is_not(repo):
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")
    prices = FakePrices({"282538466": Decimal("2.99")})

    class NoRead(FakeAccount):
        def wishlist_ids(self):
            raise CheapChartsError("read")

    wishlist_film(repo, WishlistGateway(prices, NoRead()), fid, D)
    assert repo.wishlisted_film_ids() == {fid}

    class RefusedNoRead(NoRead):
        def add_item(self, itunes_id):
            return False

    other = _film(repo, "Mulholland Dr.", 2001, "1753833311")
    with pytest.raises(WishlistError):
        wishlist_film(repo, WishlistGateway(FakePrices({"1753833311": Decimal("7.99")}), RefusedNoRead()), other, D)
    assert other not in repo.wishlisted_film_ids()


@pytest.mark.parametrize("boom", [requests.ConnectionError("x"), RateLimited("x"), CheapChartsError("x")])
def test_every_remote_failure_becomes_the_one_wishlist_error_and_marks_nothing(repo, boom):
    fid = _film(repo, "Do the Right Thing", 1989, "282538466")

    class Failing(FakeAccount):
        def set_target(self, itunes_id, target):
            raise boom

    with pytest.raises(WishlistError) as exc:
        wishlist_film(repo, WishlistGateway(FakePrices({"282538466": Decimal("2.99")}), Failing()), fid, D)
    assert repo.wishlisted_film_ids() == set()
    assert str(exc.value) == type(boom).__name__  # the class name only — never a message that could carry a secret
```

Append to `tests/web/test_wishlist_api.py` — the acceptance examples over fully mocked HTTP, the real adapters wired in:

```python
import responses

from movie_brain.infrastructure.cheapcharts import (
    ACCOUNT_URL,
    DETAIL_URL,
    WISHLIST_URL,
    CheapChartsAccount,
    CheapChartsClient,
    Pacer,
)

LOGIN_OK = {"status": "success", "message": "ok", "additionalInfo": {"sessionToken": "tok-1"}}


def _real_client(repo):
    pacer = Pacer(0)
    gateway = WishlistGateway(
        CheapChartsClient(pacer=pacer), CheapChartsAccount("someone@example.test", "hunter2", pacer=pacer)
    )
    app = create_app(repo, today=lambda: D, wishlist=gateway)
    app.testing = True
    return app.test_client()


def _history(hd):
    return {"results": {"movies": {"priceHdEvolution": hd}}}


@pytest.mark.parametrize(
    ("title", "year", "itunes", "history", "target"),
    [
        # $2.99 exactly once, $4.99 again and again — the owner's ruling: the one-off low counts.
        ("Do the Right Thing", 1989, "282538466",
         "2026-08-12:+14.99~2026-08-04:-4.99~2025-08-26:+7.99~2025-08-26:-2.99~2025-08-12:-4.99~2019-02-19:9.99", "3.99"),
        ("Mulholland Dr.", 2001, "1753833311", "2026-05-01:+14.99~2026-04-20:-7.99~2024-01-01:14.99", "8.99"),
    ],
)
@responses.activate
def test_acceptance_a_click_adds_the_film_at_its_lowest_price_ever_plus_one_dollar(
    repo, title, year, itunes, history, target
):
    fid = _film(repo, title, year, itunes)
    responses.get(DETAIL_URL, json=_history(history))
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item added"})
    responses.post(WISHLIST_URL, json={"status": "success", "message": f"init price was changed to {target}"})
    responses.post(WISHLIST_URL, json={"status": "success", "results": {"movies": [{"idInStore": int(itunes)}]}})
    r = _real_client(repo).post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": True}
    set_target = responses.calls[3].request.url
    assert f"customPrice={target}" in set_target and f"customPriceHd={target}" in set_target
    assert f"idInStore={itunes}" in set_target and "itemType=buymovies" in set_target
    assert repo.wishlisted_film_ids() == {fid}


@responses.activate
def test_acceptance_cheapcharts_unreachable_or_password_refused_marks_nothing(repo):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    client = _real_client(repo)
    # unreachable: `responses` raises ConnectionError for the unregistered DetailData call
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    # the password no longer works
    responses.get(DETAIL_URL, json=_history("2020-01-01:4.99"))
    responses.post(ACCOUNT_URL, json={"status": "error", "message": "wrong password"})
    r = client.post(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    assert repo.wishlisted_film_ids() == set()


@responses.activate
def test_acceptance_owned_and_unsold_films_never_reach_cheapcharts(repo):
    big_sleep = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(big_sleep, D)
    dolce_vita = _film(repo, "La Dolce Vita", 1960)
    client = _real_client(repo)
    assert client.post(f"/api/films/{big_sleep}/wishlist").status_code == 409
    assert client.post(f"/api/films/{dolce_vita}/wishlist").status_code == 409
    assert len(responses.calls) == 0
```

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_wishlist.py tests/web/test_wishlist_api.py -q`
Expected: ImportError on `RefreshReport`.

- [ ] **Step 3: `replace_wishlist`**

In `database.py`, after `mark_wishlisted` (add `Iterable` to the `collections.abc` import if it is not there):

```python
    def replace_wishlist(self, itunes_ids: Iterable[str], today: date) -> int:
        """The wishlist read's write: the local hearts become exactly the films holding one of
        these store ids — a film bought or removed on CheapCharts loses its heart, one added there
        by hand gains it, one that stays keeps its date. Ids no film holds are simply not ours.
        Returns how many films are hearted now."""
        wanted = set(itunes_ids)
        with self._conn() as c:
            film_ids = {
                int(r["film_id"])
                for r in c.execute("SELECT film_id, value FROM external_ids WHERE authority = 'itunes'")
                if str(r["value"]) in wanted
            }
            current = _wishlisted_ids(c)
            c.executemany("DELETE FROM cheapcharts_wishlist WHERE film_id = ?", [(f,) for f in current - film_ids])
            c.executemany(
                "INSERT INTO cheapcharts_wishlist (film_id, added_on) VALUES (?, ?)",
                [(f, today.isoformat()) for f in sorted(film_ids - current)],
            )
            return len(film_ids)
```

- [ ] **Step 4: The final use case**

In `src/movie_brain/application/wishlist.py`: add imports

```python
import requests

from movie_brain.infrastructure.cheapcharts import CheapChartsError, RateLimited
```

add after `NotForSale`:

```python
# Everything the adapters can raise. It is re-raised as WishlistError carrying the CLASS NAME
# only: an HTTP error's text holds the URL, and the login answer holds the account's email.
_REMOTE_ERRORS = (requests.RequestException, RateLimited, CheapChartsError)


@dataclass(frozen=True)
class RefreshReport:
    on_cheapcharts: int  # films on the CheapCharts wishlist
    known: int  # of those, films movie-brain holds — the hearts


def refresh_wishlist(repo: Repository, account: WishlistAccount, today: date) -> RefreshReport:
    """Read the wishlist and replace the local hearts wholesale. On any failure nothing is
    written — the dashboard keeps the last known hearts."""
    try:
        ids = account.wishlist_ids()
    except _REMOTE_ERRORS as exc:
        raise WishlistError(type(exc).__name__) from exc
    return RefreshReport(on_cheapcharts=len(ids), known=repo.replace_wishlist(ids, today))
```

and replace `wishlist_film`'s tail (everything from `low = …`) with:

```python
    # A click always means "on my wishlist at lowest + $1": add AND set-target every time, so a
    # half-finished click (added, target never set) is repaired by "Try again". A refused add is
    # not fatal by itself — most likely the film is already there — the read-back decides.
    try:
        low = gateway.prices.lowest_price(itunes_id)
        if low is None:
            raise WishlistError("no price history")
        added = gateway.account.add_item(itunes_id)
        gateway.account.set_target(itunes_id, target_price(low))
    except _REMOTE_ERRORS as exc:
        raise WishlistError(type(exc).__name__) from exc
    try:
        ids: list[str] | None = gateway.account.wishlist_ids()
    except _REMOTE_ERRORS:
        ids = None
    if ids is None:
        # Both writes went through but the wishlist cannot be read: believe an ACCEPTED add.
        if not added:
            raise WishlistError("add refused and the wishlist could not be read back")
        repo.mark_wishlisted(film_id, today)
        return
    repo.replace_wishlist(ids, today)  # hearts are refreshed after every add
    if itunes_id not in ids:
        raise WishlistError("the wishlist read back without the film")
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/unit/test_wishlist.py tests/web/test_wishlist_api.py tests/web/test_wishlist_page.py -q`
Expected: all pass. (Task 1's `test_a_click_adds_the_film_at_lowest_plus_one_and_marks_it` still passes because `FakeAccount.add_item` appends to `listed`.)

- [ ] **Step 6: Gates and commit**

```bash
git add src/movie_brain tests
git commit -m "a click is believed only when CheapCharts reads it back: add and target every time so Try again repairs a half-finished click, hearts replaced wholesale from the read" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The drawer's other states — already wishlisted, failure line, no button — and the heart's place on the row

**Files:**
- Modify: `src/movie_brain/web/static/app.js`, `src/movie_brain/web/static/app.css`, `tests/web/test_wishlist_page.py`

**Interfaces:**
- Consumes: Task 1's seed (Charlie for sale; Delta always fails; Echo wishlisted with a list badge; Alpha owned with a store id; Bravo without one), `wishHtml`, the `.wish-button` handler.
- Produces: nothing later tasks rely on.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_wishlist_page.py`:

```python
def test_a_failed_click_says_so_offers_try_again_and_marks_nothing(dash: Page):
    body = _open(dash, "Delta")
    body.locator("p.links button.wish-button").click()
    failed = body.locator("p.links .wish-failed")
    expect(failed).to_contain_text("Couldn't reach CheapCharts.")
    retry = failed.locator("button.wish-button")
    expect(retry).to_have_text("Try again")
    expect(_row(dash, "Delta").locator(".icon-wish")).to_have_count(0)
    retry.click()  # the same click again: busy, then the same line (Delta's fake never recovers)
    expect(body.locator("p.links button.wish-button").first).to_have_text("Reaching CheapCharts…")
    expect(body.locator("p.links .wish-failed")).to_contain_text("Couldn't reach CheapCharts.")
    expect(_row(dash, "Delta").locator(".icon-wish")).to_have_count(0)


def test_an_already_wishlisted_film_shows_the_mark_where_the_button_was(dash: Page):
    body = _open(dash, "Echo")
    expect(body.locator("p.links .wish-done")).to_have_text("♥ Wishlisted")
    expect(body.locator("p.links button.wish-button")).to_have_count(0)


def test_the_heart_comes_last_after_the_list_count_and_any_other_badge(dash: Page):
    cell = _row(dash, "Echo").locator("td.c-title")
    expect(cell.locator(".badge-lists")).to_have_count(1)
    last = cell.locator("span").last
    expect(last).to_have_class("icon-wish")
    expect(last).to_have_attribute("title", HEART_TIP)


def test_an_owned_film_and_a_film_apple_does_not_sell_get_no_button_and_no_message(dash: Page):
    body = _open(dash, "Alpha")  # owned, holds a store id, not wishlisted: The Big Sleep
    expect(body.locator("p.links .cheapcharts-link")).to_have_count(1)
    expect(body.locator(".wish")).to_have_count(0)
    expect(_row(dash, "Alpha").locator(".icon-wish")).to_have_count(0)
    dash.keyboard.press("Escape")
    body = _open(dash, "Bravo")  # no store id: La Dolce Vita
    expect(body.locator(".wish")).to_have_count(0)
    expect(body).not_to_contain_text("CheapCharts.")  # nothing said


def test_only_wishlisted_rows_carry_anything_new(dash: Page):
    hearts = dash.locator("#films tbody .icon-wish")
    # Echo is seeded; Charlie joins it only if the click test already ran in this session.
    assert hearts.count() in (1, 2)
    expect(_row(dash, "Bravo").locator(".icon-wish")).to_have_count(0)
```

Check how the existing dashboard tests close a drawer (search `tests/web/test_dashboard.py` for `Escape` / `#drawer-close`) and use the same idiom in place of `dash.keyboard.press("Escape")` if Escape is not what they use. If Bravo or Echo is hidden by the default view in this fixture, open it the way the existing tests reach that film — do not change the seed's existing rows.

- [ ] **Step 2: Run to see the failure test fail**

Run: `uv run pytest tests/web/test_wishlist_page.py -q`
Expected: `test_a_failed_click_…` FAILS (no `.wish-failed`); the others may already pass — that is fine, they pin Task 1's markup.

- [ ] **Step 3: The failure line**

In `app.js`, replace the handler's failure branch

```js
    if (!r || !r.ok) { b.disabled = false; b.textContent = WISH_BUTTON; return; }
```

with

```js
    if (!r || !r.ok) {
      // One line whatever went wrong — offline, a refused password, no price history — and nothing is marked.
      slot.innerHTML = '<span class="wish-failed">Couldn\'t reach CheapCharts. <button class="wish-button">Try again</button></span>';
      return;
    }
```

("Try again" is a `.wish-button` inside the same `.wish` slot, so the same handler runs it: it goes busy in place, then the slot becomes the done mark or the failure line again.)

In `app.css`, after the `.wish-done` rule:

```css
#drawer p.links .wish-failed { color:var(--muted); }
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/web/test_wishlist_page.py -q`
Expected: 6 passed.

- [ ] **Step 5: Gates and commit**

```bash
git add src/movie_brain/web/static tests/web/test_wishlist_page.py
git commit -m "a failed click says one plain line and offers Try again; an owned or unsold film gets no button and no message" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Hearts on day one — the `cheapcharts wishlist` verb, the dashboard's start-up read, and merge

**Files:**
- Modify: `src/movie_brain/cli.py`, `tests/unit/test_cli.py`, `tests/unit/test_wishlist.py`

**Interfaces:**
- Consumes: `load_credentials`, `load_config` (already imported in `cli.py` — check), `CheapChartsClient(pacer=)`, `CheapChartsAccount`, `Pacer`, `WishlistGateway`, `WishlistError`, `refresh_wishlist`, `create_app(..., wishlist=)`.
- Produces: `movie-brain cheapcharts wishlist`; `cli._wishlist_gateway() -> WishlistGateway | None`; `cli._refresh_hearts(repo, gateway) -> str` (the one status line both the verb and the dashboard print).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_wishlist.py`:

```python
def test_merge_moves_the_heart_survivor_wins(repo):
    a, b = _film(repo, "Alpha", 1950), _film(repo, "Alpha", 1951)
    repo.mark_wishlisted(b, D)
    repo.merge_film(b, a, D)
    assert repo.wishlisted_film_ids() == {a}
    c, d = _film(repo, "Beta", 1960), _film(repo, "Beta", 1961)
    repo.mark_wishlisted(c, D)
    repo.mark_wishlisted(d, D)
    report = repo.merge_film(d, c, D)
    assert report.dropped.get("cheapcharts_wishlist") == 1 and repo.wishlisted_film_ids() == {a, c}
```

(It should pass already — Task 1 registered the table — and pins the behaviour. If it does not, fix `merge_film`.)

Read the top of `tests/unit/test_cli.py` for its runner idiom (`CliRunner`, how it builds a repo under `config_dir`), then append tests in that idiom:

```python
@responses.activate
def test_cheapcharts_wishlist_reads_the_account_and_reports_the_hearts(config_dir):
    from movie_brain.infrastructure.cheapcharts import ACCOUNT_URL, WISHLIST_URL
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    fid = repo.create_film(Film("The Leopard", 1963, "Luchino Visconti", ""))
    repo.set_external_id(fid, "itunes", "273058482", date(2026, 9, 19))
    (config_dir / "credentials.toml").write_text(
        '[cheapcharts]\nusername = "someone@example.test"\npassword = "hunter2"\n'
    )
    responses.post(ACCOUNT_URL, json={"status": "success", "additionalInfo": {"sessionToken": "tok-1"}})
    responses.post(
        WISHLIST_URL, json={"status": "success", "results": {"movies": [{"idInStore": 273058482}, {"idInStore": 5}]}}
    )
    result = runner.invoke(app, ["cheapcharts", "wishlist"])
    assert result.exit_code == 0
    assert "2 films on CheapCharts" in result.output and "1 known here" in result.output
    assert "someone@example.test" not in result.output and "tok-1" not in result.output
    assert repo.wishlisted_film_ids() == {fid}


def test_cheapcharts_wishlist_without_credentials_exits_2_and_names_the_file(config_dir):
    from movie_brain.infrastructure.database import Repository

    Repository(config_dir / "movie-brain.db")
    result = runner.invoke(app, ["cheapcharts", "wishlist"])
    assert result.exit_code == 2 and "credentials.toml" in result.output


@responses.activate
def test_cheapcharts_wishlist_unreachable_exits_1_and_keeps_the_hearts(config_dir):
    from movie_brain.infrastructure.database import Repository

    repo = Repository(config_dir / "movie-brain.db")
    fid = repo.create_film(Film("The Leopard", 1963, "Luchino Visconti", ""))
    repo.mark_wishlisted(fid, date(2026, 9, 19))
    (config_dir / "credentials.toml").write_text(
        '[cheapcharts]\nusername = "someone@example.test"\npassword = "hunter2"\n'
    )
    result = runner.invoke(app, ["cheapcharts", "wishlist"])  # nothing registered: ConnectionError
    assert result.exit_code == 1 and "last known hearts" in result.output
    assert repo.wishlisted_film_ids() == {fid}
```

Adapt names (`runner`, `app`, imports, whether stderr is mixed into `result.output`) to what the file already uses. The account's default `Pacer()` would sleep 1.5 s between the two calls — monkeypatch `movie_brain.cli.Pacer` to `lambda: Pacer(0)` or patch `time.sleep` the way the file's other CheapCharts CLI tests do, if they exist; otherwise accept the 1.5 s.

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/unit/test_cli.py -q -k wishlist`
Expected: FAIL — no such command `wishlist`.

- [ ] **Step 3: Implement**

In `src/movie_brain/cli.py`, extend the imports:

```python
from movie_brain.application.wishlist import WishlistError, WishlistGateway, refresh_wishlist
from movie_brain.infrastructure.cheapcharts import CheapChartsAccount, CheapChartsClient, Pacer
from movie_brain.infrastructure.credentials import load_credentials
```

Beside the other private helpers (near `_repo`):

```python
def _wishlist_gateway() -> WishlistGateway | None:
    """The CheapCharts account behind "Wishlist it", or None when `credentials.toml` has no
    usable [cheapcharts] section. One Pacer for both clients: they are one host."""
    creds = load_credentials(load_config(), "cheapcharts")
    if creds is None:
        return None
    pacer = Pacer()
    return WishlistGateway(CheapChartsClient(pacer=pacer), CheapChartsAccount(*creds, pacer=pacer))


def _refresh_hearts(repo: Repository, gateway: WishlistGateway) -> str:
    """Read the wishlist, replace the hearts, and word the outcome. Raises WishlistError."""
    report = refresh_wishlist(repo, gateway.account, date.today())
    return f"wishlist: {report.on_cheapcharts} films on CheapCharts · {report.known} known here"
```

(Use whatever name `cli.py` already imports `Repository` and `load_config` under; add the import if missing.)

The verb, after `cheapcharts_resolve_cmd`:

```python
@cheapcharts_app.command("wishlist")
def cheapcharts_wishlist_cmd() -> None:
    """Read my CheapCharts wishlist and refresh the dashboard's hearts from it.

    Logs in with the [cheapcharts] section of <config_dir>/credentials.toml, reads the wishlist,
    and replaces the local hearts wholesale: a film bought or removed on CheapCharts loses its
    heart, one added there by hand gains it. Reads the account, never writes to it; the only
    write is the local mirror, which the dashboard refreshes the same way every time it starts —
    so there is no dry run. Prints counts only, never a price or anything from the account.
    """
    gateway = _wishlist_gateway()
    if gateway is None:
        err.print(f"no [cheapcharts] username/password in {load_config().credentials_file}")
        raise typer.Exit(2)
    try:
        console.print(_refresh_hearts(_repo(), gateway))
    except WishlistError as exc:
        err.print(f"wishlist: couldn't reach CheapCharts ({exc}) — keeping the last known hearts")
        raise typer.Exit(1) from exc
```

The dashboard verb becomes:

```python
    embedder = SentenceTransformerEmbedder() if SentenceTransformerEmbedder.available() else None
    repo = _repo()
    gateway = _wishlist_gateway()
    console.print(f"movie-brain dashboard → http://{host}:{port}")
    console.print(
        "semantic search: "
        + ("on (loads the model on the first meaning query)" if embedder else "off — uv sync --extra semantic")
    )
    # Hearts are refreshed on every start. CheapCharts being down never stops the dashboard.
    if gateway is None:
        console.print("wishlist: off — no [cheapcharts] login in credentials.toml")
    else:
        try:
            console.print(_refresh_hearts(repo, gateway))
        except WishlistError:
            console.print("wishlist: couldn't reach CheapCharts — showing the last known hearts")
    create_app(repo, embedder=embedder, wishlist=gateway).run(host=host, port=port, debug=False)
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_cli.py tests/unit/test_wishlist.py -q`
Expected: all pass.

- [ ] **Step 5: Gates and commit**

```bash
git add src/movie_brain/cli.py tests/unit
git commit -m "films wishlisted before today get their heart: the dashboard reads the wishlist on every start and carries on without it when CheapCharts is down" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Amend the brief to 1.1 and log the build's decisions

**Files:**
- Modify: `docs/superpowers/briefs/2026-09-19-price-watch/brief.md`, `docs/superpowers/briefs/2026-09-19-price-watch/trial-log.md`

(`CLAUDE.md`, the backlog tick and the trial scorecard wait for the owner's say-so after his hands-on test — kickoff, "Delivery".)

- [ ] **Step 1: Amend the brief — never rewrite a 1.0 line**

Change the version line's opening to `**Version 1.1 — amended 2026-09-19 during the build (1.0 frozen the same day).**` keeping the rest of the paragraph, and append a new section at the end of the file:

```markdown
## Amendments

**1.1 — 2026-09-19, by the builder, under the execution authority (none of these is visible on screen or touches the account beyond what 1.0 approved).** New agent defaults:

| Decision | Whose |
|---|---|
| A click is believed only when CheapCharts reads it back: after add + set-target the wishlist is read, the hearts are replaced from it, and the film is marked only if the read holds it. If that read fails, an ACCEPTED add is believed; a refused one is not | agent default — 1.0's "treat already-on-the-wishlist as fine" could not be built as written, because the API's answer for that case was never observed. A refused add no longer stops the click; the set-target call and the read-back decide |
| The table is `cheapcharts_wishlist` (migration 027); a film holding several store ids is hearted by any of them, and the button wishlists the same product the CheapCharts link opens | agent default |
| Errors from the account carry our own wording only, never the API's text — the login answer holds the account's email | agent default |
| With no usable `[cheapcharts]` section, the dashboard starts with the last known hearts and says "wishlist: off"; the button still shows, and a click ends in the ordinary failure line | agent default |
| `movie-brain cheapcharts wishlist` has no dry run: it never writes to the account, and its one local write is the same refresh every dashboard start performs | agent default |
| Calls to CheapCharts are paced 1.5 s apart on a clock, shared between the price read and the account, so a dashboard idle for an hour does not wait before its first call | agent default |
| One click at a time: a second click anywhere waits for the first to finish | agent default |

Format note for the record: `priceHdEvolution` entries are `date:±price` where the sign is the DIRECTION of the change, not part of the price; the oldest entry has no sign (read from the public endpoint 2026-09-19, no account involved).
```

- [ ] **Step 2: Log it in the trial log**

Append a row to the "Probes used" table of `trial-log.md`:

```markdown
| One public, unauthenticated price-history read (Do the Right Thing) at plan time — no account involved | the exact `priceHdEvolution` format, which the brief gave only as `date:±price~…` | yes — the sign turned out to be the direction of the change, not part of the price; a parser built on the brief's wording alone would have had to guess. Cost to him: zero minutes |
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/briefs/2026-09-19-price-watch
git commit -m "the brief becomes 1.1 by amendment: the build's own defaults are on the record, above all that a click is believed only when CheapCharts reads it back" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Un-wishlist — the click is reversible (brief amendment 1.2, the owner's ruling at delivery)

The owner, on delivery: "there is no way to unwhishlist it. it should be reversable". This reverses one line of 1.0's "What deliberately does not ship" (no un-wishlist button). Design (agent default, the simplest symmetric one): in the drawer the "♥ Wishlisted" mark IS the button. One click removes the film from the CheapCharts wishlist, the slot goes back to "♡ Wishlist it" (or to nothing, for a film that gets no add button — an owned one), and the heart leaves the row. No confirmation step: the watchlist star beside the title is instant too, and a mistaken click is undone by one more click, which re-adds at lowest + $1 — the owner's own rule. The truth rule is the add's mirror image: remove, then read the wishlist back; the read IS the truth; if the read fails, an ACCEPTED remove is believed and a refused one is not. `removeItem` was seen in the site's code and never exercised — its first real run is the owner's hands-on test.

**Files:**
- Modify: `src/movie_brain/infrastructure/cheapcharts.py`, `src/movie_brain/infrastructure/database.py`, `src/movie_brain/application/wishlist.py`, `src/movie_brain/web/app.py`, `src/movie_brain/web/static/app.js`, `src/movie_brain/web/static/app.css`, `tests/unit/test_cheapcharts_account.py`, `tests/unit/test_wishlist.py`, `tests/web/test_wishlist_api.py`, `tests/web/test_wishlist_page.py`, `tests/web/conftest.py`, `docs/superpowers/briefs/2026-09-19-price-watch/brief.md`, `docs/superpowers/briefs/2026-09-19-price-watch/trial-log.md`

**Interfaces:**
- Consumes: `CheapChartsAccount._wishlist`, `CheapChartsRefused`, `WishlistAccount` Protocol, `_REMOTE_ERRORS`, `WishlistError`, `Repository.replace_wishlist / wishlisted_film_ids / itunes_id_for`, the route's `wishlist_lock` and `UNREACHABLE`, `wishHtml`, the `.wish-button` handler.
- Produces:
  - `CheapChartsAccount.remove_item(itunes_id: str) -> bool` (False = the API refused for a non-token reason); `WishlistAccount` Protocol gains the same method
  - `Repository.unmark_wishlisted(film_id: int) -> None`
  - `application/wishlist.py::unwishlist_film(repo, gateway, film_id, today) -> None` (raises `LookupError`, `WishlistError`)
  - `DELETE /api/films/<int:film_id>/wishlist` → `200 {"wishlisted": false}` · `404 {"error": "not found"}` · `502 {"error": "Couldn't reach CheapCharts."}`

Exact wording stays a hard boundary: `♡ Wishlist it` · `Reaching CheapCharts…` · `♥ Wishlisted` · `Couldn't reach CheapCharts.` · `Try again`. One new string, a tooltip on the "♥ Wishlisted" button only: `Remove from your CheapCharts wishlist`. No price anywhere.

- [ ] **Step 1: Failing tests — the account**

Append to `tests/unit/test_cheapcharts_account.py` (merge imports at the top):

```python
@responses.activate
def test_remove_item_sends_buymovies_and_reports_a_refusal_instead_of_raising():
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item removed"})
    responses.post(WISHLIST_URL, json={"status": "error", "message": "whatever it says"})
    account = _account()
    assert account.remove_item("282538466") is True
    q = parse_qs(urlsplit(responses.calls[1].request.url).query)
    assert q["action"] == ["removeItem"] and q["itemType"] == ["buymovies"] and q["idInStore"] == ["282538466"]
    assert q["country"] == ["us"] and q["store"] == ["itunes"]
    assert account.remove_item("282538466") is False  # e.g. already gone: the read-back decides
```

Implement in `CheapChartsAccount`, after `set_target`:

```python
    def remove_item(self, itunes_id: str) -> bool:
        """False when the API refused — most likely the film is already gone. Seen in the site's
        own code, first exercised by the owner's hands-on test; the caller trusts the read-back."""
        try:
            self._wishlist("removeItem", itemType="buymovies", idInStore=itunes_id)
        except CheapChartsRefused:
            return False
        return True
```

- [ ] **Step 2: Failing tests — repository and use case**

Append to `tests/unit/test_wishlist.py`. First give the module's `FakeAccount` a `remove_item` that logs `("remove", itunes_id)`, drops the id from `self.listed` and returns True. Then:

```python
def test_unmark_wishlisted_is_idempotent(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)
    repo.unmark_wishlisted(fid)
    repo.unmark_wishlisted(fid)
    assert repo.wishlisted_film_ids() == set() and repo.get_view(fid, D).wishlisted is False


def test_un_wishlisting_removes_the_film_and_the_read_back_replaces_every_heart(repo):
    nashville = _film(repo, "Nashville", 1975, "366474905")
    leopard = _film(repo, "The Leopard", 1963, "273058482")
    stale = _film(repo, "Bought Since", 1990, "777")
    for fid in (nashville, stale):
        repo.mark_wishlisted(fid, D)
    account = FakeAccount(listed=["366474905", "273058482"])
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), nashville, D)
    assert [c[0] for c in account.calls] == ["remove", "read"]
    assert repo.wishlisted_film_ids() == {leopard}


def test_an_owned_wishlisted_film_can_be_un_wishlisted(repo):
    fid = _film(repo, "The Big Sleep", 1946, "290555722")
    repo.mark_owned(fid, D)
    repo.mark_wishlisted(fid, D)
    unwishlist_film(repo, WishlistGateway(FakePrices({}), FakeAccount(listed=["290555722"])), fid, D)
    assert repo.wishlisted_film_ids() == set()


def test_un_wishlisting_a_film_that_is_not_wishlisted_asks_cheapcharts_nothing(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    account = FakeAccount(listed=["366474905"])
    unwishlist_film(repo, WishlistGateway(FakePrices({}), account), fid, D)
    assert account.calls == []
    with pytest.raises(LookupError):
        unwishlist_film(repo, WishlistGateway(FakePrices({}), account), 999, D)


def test_a_remove_the_read_back_still_holds_is_a_failure_and_the_heart_stays(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)

    class Sticky(FakeAccount):
        def remove_item(self, itunes_id):
            self.calls.append(("remove", itunes_id))
            return False  # refused, and the film is still listed

    with pytest.raises(WishlistError):
        unwishlist_film(repo, WishlistGateway(FakePrices({}), Sticky(listed=["366474905"])), fid, D)
    assert repo.wishlisted_film_ids() == {fid}


def test_when_the_read_back_fails_an_accepted_remove_is_believed_and_a_refused_one_is_not(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)

    class NoRead(FakeAccount):
        def wishlist_ids(self):
            raise CheapChartsError("read")

    class RefusedNoRead(NoRead):
        def remove_item(self, itunes_id):
            return False

    with pytest.raises(WishlistError):
        unwishlist_film(repo, WishlistGateway(FakePrices({}), RefusedNoRead(listed=["366474905"])), fid, D)
    assert repo.wishlisted_film_ids() == {fid}
    unwishlist_film(repo, WishlistGateway(FakePrices({}), NoRead(listed=["366474905"])), fid, D)
    assert repo.wishlisted_film_ids() == set()


def test_a_remote_failure_while_removing_becomes_the_one_wishlist_error(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)

    class Down(FakeAccount):
        def remove_item(self, itunes_id):
            raise requests.ConnectionError("offline")

    with pytest.raises(WishlistError) as exc:
        unwishlist_film(repo, WishlistGateway(FakePrices({}), Down()), fid, D)
    assert str(exc.value) == "ConnectionError" and repo.wishlisted_film_ids() == {fid}
```

Implement. `database.py`, after `mark_wishlisted`:

```python
    def unmark_wishlisted(self, film_id: int) -> None:
        """The un-wishlist button's write when the wishlist cannot be read back (an accepted
        remove is believed). Idempotent. Every other heart removal is `replace_wishlist`'s."""
        with self._conn() as c:
            c.execute("DELETE FROM cheapcharts_wishlist WHERE film_id = ?", (film_id,))
```

Update `mark_wishlisted`'s docstring (it says there is no un-mark) and migration-independent comments accordingly — never edit `migrations/027`. `application/wishlist.py`: add `def remove_item(self, itunes_id: str) -> bool: ...` to the `WishlistAccount` Protocol, and after `wishlist_film`:

```python
def unwishlist_film(repo: Repository, gateway: WishlistGateway, film_id: int, today: date) -> None:
    """The click is reversible (owner ruling at delivery, brief 1.2). The add's mirror image:
    remove, then read the wishlist back — the read IS the truth. An owned film can be taken off
    too: that is the likeliest reason to want it gone."""
    view = repo.get_view(film_id, today)
    if view is None:
        raise LookupError(film_id)
    itunes_id = repo.itunes_id_for(film_id)
    if not view.wishlisted or itunes_id is None:
        return  # a stale page: nothing to remove, and CheapCharts is asked nothing
    try:
        removed = gateway.account.remove_item(itunes_id)
    except _REMOTE_ERRORS as exc:
        raise WishlistError(type(exc).__name__) from exc
    try:
        ids: list[str] | None = gateway.account.wishlist_ids()
    except _REMOTE_ERRORS:
        ids = None
    if ids is None:
        if not removed:
            raise WishlistError("remove refused and the wishlist could not be read back")
        repo.unmark_wishlisted(film_id)
        return
    repo.replace_wishlist(ids, today)
    if film_id in repo.wishlisted_film_ids():
        raise WishlistError("the wishlist read back still holding the film")
```

(The last check asks the repository rather than `itunes_id in ids` so a film holding two store ids is judged by either.)

- [ ] **Step 3: Failing tests — the route**

In `tests/web/test_wishlist_api.py` give the module's `FakeAccount` `remove_item` (raises `WishlistError("down")` when `self.down`, else pops the id from `self.targets` and returns True). Add:

```python
def test_delete_un_wishlists_the_film(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    client.post(f"/api/films/{fid}/wishlist")
    r = client.delete(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": False}
    assert account.targets == {} and repo.wishlisted_film_ids() == set()
    assert client.get(f"/api/films/{fid}").get_json()["wishlisted"] is False
    assert client.delete("/api/films/999/wishlist").status_code == 404


def test_a_failed_un_wishlist_is_the_same_failure_line_and_the_heart_stays(client, repo, account):
    fid = _film(repo, "Do the Right Thing", 1989, DTRT)
    client.post(f"/api/films/{fid}/wishlist")
    account.down = True
    r = client.delete(f"/api/films/{fid}/wishlist")
    assert r.status_code == 502 and r.get_json() == {"error": "Couldn't reach CheapCharts."}
    assert repo.wishlisted_film_ids() == {fid}


@responses.activate
def test_acceptance_un_wishlisting_sends_remove_item_and_believes_the_read_back(repo):
    fid = _film(repo, "Nashville", 1975, "366474905")
    repo.mark_wishlisted(fid, D)
    responses.post(ACCOUNT_URL, json=LOGIN_OK)
    responses.post(WISHLIST_URL, json={"status": "success", "message": "Item removed"})
    responses.post(WISHLIST_URL, json={"status": "success", "results": {"movies": []}})
    r = _real_client(repo).delete(f"/api/films/{fid}/wishlist")
    assert r.status_code == 200 and r.get_json() == {"wishlisted": False}
    remove = responses.calls[1].request.url
    assert "action=removeItem" in remove and "idInStore=366474905" in remove and "itemType=buymovies" in remove
    assert repo.wishlisted_film_ids() == set()
```

Route, in `web/app.py` after `post_wishlist` (import `unwishlist_film`):

```python
    @app.delete("/api/films/<int:film_id>/wishlist")
    def delete_wishlist(film_id: int) -> tuple[Response, int]:
        if wishlist is None:
            return jsonify({"error": UNREACHABLE}), 502
        try:
            with wishlist_lock:
                unwishlist_film(repo, wishlist, film_id, today())
        except LookupError:
            return jsonify({"error": "not found"}), 404
        except WishlistError:
            return jsonify({"error": UNREACHABLE}), 502
        return jsonify({"wishlisted": False}), 200
```

- [ ] **Step 4: Failing Playwright tests, then the drawer**

`tests/web/conftest.py`: `FakeAccount.remove_item` — sleep 1.0 s like `add_item`; raise `WishlistError("down")` for a new seeded film whose remove always fails; otherwise pop from `targets` and return True. Seed (at the end of `seed()`, comment in the file's voice): **Foxtrot** gets itunes id `FOXTROT_ITUNES = "111000111"` and is wishlisted, and its remove always fails (the un-wishlist failure film); **Golf** gets `GOLF_ITUNES = "222000222"` and is wishlisted (the un-wishlist click film — it has no Criterion listing and no services, so check `reachable` first: a film holding an itunes id IS reachable, and Golf was reachable-neutral before? If giving Golf or Foxtrot a store id changes any existing test's count, pick different seeded films or create two new discovery films "India" and "Juliet" with `repo.create_film` + OMDb language English — new films may change header counts that tests pin, so prefer reusing films, and never weaken an existing test). Both ids must also be in `FAKE_ACCOUNT.targets` initially so a read-back during another test's click keeps their hearts. Echo stays wishlisted and untouched by any click test (other tests pin its heart).

Append to `tests/web/test_wishlist_page.py` (use the real titles you seeded):

```python
def test_the_wishlisted_mark_is_a_button_and_one_click_takes_the_film_off_again(dash: Page):
    expect(_row(dash, "Golf").locator(".icon-wish")).to_have_count(1)
    body = _open(dash, "Golf")
    mark = body.locator("p.links button.wish-button.wish-done")
    expect(mark).to_have_text("♥ Wishlisted")
    expect(mark).to_have_attribute("title", "Remove from your CheapCharts wishlist")
    mark.click()
    busy = body.locator("p.links button.wish-button")
    expect(busy).to_have_text("Reaching CheapCharts…")
    expect(busy).to_be_disabled()
    expect(body.locator("p.links button.wish-button")).to_have_text("♡ Wishlist it")
    expect(_row(dash, "Golf").locator(".icon-wish")).to_have_count(0)


def test_a_failed_un_wishlist_says_so_and_try_again_retries_the_removal(dash: Page):
    body = _open(dash, "Foxtrot")
    body.locator("p.links button.wish-done").click()
    failed = body.locator("p.links .wish-failed")
    expect(failed).to_contain_text("Couldn't reach CheapCharts.")
    expect(_row(dash, "Foxtrot").locator(".icon-wish")).to_have_count(1)  # nothing changed
    with dash.expect_request(lambda r: r.method == "DELETE" and r.url.endswith("/wishlist")):
        failed.locator("button.wish-button").click()  # Try again repeats the REMOVAL, not an add
    expect(body.locator("p.links .wish-failed")).to_contain_text("Couldn't reach CheapCharts.")
```

The session-scoped server is shared: the Golf test must not depend on order — if another test could re-heart Golf (a read-back replaces hearts from `FAKE_ACCOUNT.targets`, and the remove pops Golf from it, so it stays gone) confirm by running the file forwards and with `-p no:randomly` reversed (`uv run pytest tests/web/test_wishlist_page.py -q` then the same with the tests listed in reverse order on the command line). Update the two existing tests that pin the already-wishlisted drawer (`.wish-done` is now a `button.wish-button.wish-done`; `test_an_already_wishlisted_film_shows_the_mark_where_the_button_was` asserted there is NO `button.wish-button` — it must now assert the mark is the un-wishlist button with its tooltip) and `test_only_wishlisted_rows_carry_anything_new` (its allowed set of hearted titles grows by the new seeded films). Those are the only existing assertions that may change, and only in that direction.

`app.js`:

```js
  const WISH_DONE = '<button class="wish-button wish-done" title="Remove from your CheapCharts wishlist">♥ Wishlisted</button>';
  function wishSlotHtml(d) {  // the slot's resting content for this film's state
    if (d.wishlisted) return WISH_DONE;
    if (!d.cheapcharts_url || d.owned) return '';
    return `<button class="wish-button">${WISH_BUTTON}</button>`;
  }
  function wishHtml(d) {
    const inner = wishSlotHtml(d);
    return inner ? ` <span class="wish" data-id="${d.id}">${inner}</span>` : '';
  }
```

and the handler: decide the action ONCE per slot and remember it on the slot, so "Try again" repeats the same action:

```js
    const b = e.target.closest('.wish-button'); if (!b || b.disabled) return;
    const slot = b.closest('.wish'); const id = Number(slot.dataset.id);
    const film = state.films.find((f) => f.id === id);
    // The mark is the un-wishlist button (brief 1.2: the click is reversible). "Try again" sits in
    // the same slot and repeats whichever action failed, remembered on the slot.
    if (!b.closest('.wish-failed')) slot.dataset.action = b.classList.contains('wish-done') ? 'remove' : 'add';
    const removing = slot.dataset.action === 'remove';
    slot.innerHTML = '<button class="wish-button" disabled>Reaching CheapCharts…</button>';
    const r = await fetch(`/api/films/${id}/wishlist`, { method: removing ? 'DELETE' : 'POST' }).catch(() => null);
    if (!r || !r.ok) { /* the existing failure line, unchanged */ return; }
    const wishlisted = !removing;
    if (film) { film.wishlisted = wishlisted; applyFilters(); }
    // An owned film gets no add button: its slot simply empties.
    slot.innerHTML = wishSlotHtml({ ...(film || {}), id, wishlisted });
```

Note the drawer's detail object `d` and the list's `film` both carry `cheapcharts_url` and `owned`; if `film` is missing (it should not be) fall back to leaving the slot empty after a removal. Keep the existing comments' substance. CSS: `.wish-done` is now a button — make it read as the mark, not as a grey system button: keep the `#c2410c` colour and give it `background:none; border:none; padding:0; font:inherit; cursor:pointer;` so the approved preview's look of "♥ Wishlisted" is unchanged.

- [ ] **Step 5: Amend the brief to 1.2 and log the correction**

`brief.md`: change the version line's opening to `**Version 1.2 — amended 2026-09-19 at delivery (1.1 amended during the build; 1.0 frozen the same day).**`, leave every other existing line untouched (including "no un-wishlist button" in 1.0's list — the amendment supersedes it, the original stays), and append to the `## Amendments` section:

```markdown
**1.2 — 2026-09-19, by the owner, on first sight of the delivery:** "there is no way to unwhishlist it. it should be reversable". This supersedes 1.0's "no un-wishlist button" (What deliberately does not ship) and 1.0's "exactly two writers".

| Decision | Whose |
|---|---|
| The click is reversible | your choice, 2026-09-19 |
| In the drawer the "♥ Wishlisted" mark IS the button: one click removes the film from your CheapCharts wishlist, the button goes back to "♡ Wishlist it" (an owned film's slot just empties) and the heart leaves the row. Its tooltip reads "Remove from your CheapCharts wishlist". No confirmation step — a mistaken click is undone by one more click | agent default, NOT previewed — look at it in the hands-on test |
| Taking a film off and putting it back sets the target to lowest + $1 again, so a target you had set by hand on CheapCharts is not restored | agent default — a consequence of "a click always means lowest + $1" |
| Removal follows the add's truth rule: remove, read the wishlist back, the read decides; if the read fails an accepted remove is believed. A failure is the same line, and "Try again" repeats the removal | agent default |
| A film you own that is on your wishlist can be taken off the same way (it cannot be put back from here: owned films get no add button) | agent default |
| The remove call (`removeItem`) was seen in the site's code and never run against your account; its first real run is your hands-on test | fact, stated so it is not a surprise |
```

`trial-log.md`: append to the "Surprises and corrections" table:

```markdown
| 6 | On first sight of the delivery he asked for the one thing the frozen brief listed as deliberately not shipping: an un-wishlist. "There is no way to unwhishlist it. it should be reversable." The line sat in a list of twelve exclusions he approved by reading, never by using — the same failure as correction 4: words he had not pictured. Built the same evening as amendment 1.2. | changed preference or misunderstood intent — his to tag; caught at delivery, before the hands-on test |
```

Never hard-wrap these lines.

- [ ] **Step 6: Gates and commit**

All four gates. Then:

```bash
git add src/movie_brain tests docs/superpowers/briefs/2026-09-19-price-watch docs/superpowers/plans/2026-09-19-wishlist-it.md
git commit -m "the click is reversible: the Wishlisted mark is the button that takes the film off again, judged by the same read-back as the add"
```
(with the attribution trailer as the second -m).

---

### Task 9: The wishlist read really works, and nothing is ever written before a successful read (brief amendment 1.3)

**Root cause, from the owner's hands-on test (2026-09-19, evidence: his own redacted `probe read` output).** Every wishlist READ failed against the real API while add / set-target / remove worked: the dashboard started with no hearts, and each click's read-back failed too (only the "accepted add is believed" fallback moved The Leopard's heart). The real `getShortItemList_v2` answer carries **no `status` key at all**. Its top-level keys are exactly `results`, `originRequest`, `responseTimestamp`; `results` is an object with `ebooks`, `movies` and `tv` lists; each movie is `{"idInStore": "<digits as a STRING>", "initialPriceValue": <number, may be -1>, "initialHdPriceValue": <number>, "customPrice": true}` with `customPrice` simply ABSENT when no target was set. `CheapChartsAccount._wishlist` demands `status == "success"`, so it raised `CheapChartsRefused` on every read. The brief's "answers JSON `{status: …}`" was a generalisation from the write calls, and every test mocked the read with an invented `"status": "success"`. An error answer DOES carry `status: "error"` (proven for a bad token: "Couldn't load user. DeviceId or sessionToken unknown").

Three changes, one task.

**A. The read accepts the real shape.** In `infrastructure/cheapcharts.py`:
- `_wishlist(action, *, needs_status: bool = True, **extra)`: an answer with `status == "error"` is handled exactly as today (token message → one fresh login + one retry; anything else → `CheapChartsRefused`). With `needs_status=True` (add, set-target, remove — proven to send it) anything other than `status == "success"` is still refused. With `needs_status=False` (the read) an answer WITHOUT a `status` key is returned to the caller, whose shape guards are the validation.
- Replace `wishlist_ids()` with:

```python
@dataclass(frozen=True)
class WishlistItem:
    itunes_id: str
    custom_target: bool  # a target price was set for it — by hand on CheapCharts, or by us


    def wishlist_items(self) -> list[WishlistItem]:
        """Every film on the wishlist, in CheapCharts' order. The read is the one call whose
        answer carries NO `status` key on success (seen on the real account 2026-09-19) — its
        shape is the validation: `results` must be an object holding a `movies` list, anything
        else is refused rather than read as an empty wishlist (a wholesale replace would erase
        every heart). `customPrice` is simply absent on an item with no target."""
```
  keeping today's shape guards (`CheapChartsError("unexpected answer shape")`), `str(m["idInStore"])`, and `custom_target=m.get("customPrice") is True`.
- Tests (`tests/unit/test_cheapcharts_account.py`): a module constant `REAL_READ` reproducing the real answer's SHAPE with INVENTED ids (never the owner's real ids — the repo is public): top-level `results` / `originRequest` / `responseTimestamp`, NO `status`; `results` with `ebooks`, `movies` (one with `customPrice: true` and `initialPriceValue: -1`, one without `customPrice`), `tv`. Pin: it parses to the right `WishlistItem`s; ebooks/tv are ignored; a `status: "error"` non-token answer raises; the bad-token answer still triggers one re-login; a write answer without `status` is still refused. **Every mocked read in the whole test suite must drop the invented `"status": "success"`** (`test_cheapcharts_account.py`, `tests/unit/test_cli.py`, `tests/web/test_wishlist_api.py`) — a read mock that still carries it is a finding.

**B. Never write before a successful read.** `application/wishlist.py`: the Protocol's `wishlist_ids` becomes `wishlist_items(self) -> list[WishlistItem]` (import the dataclass from infrastructure, as the module already imports its errors). New rules, replacing the read-back-after design and its "an accepted add/remove is believed when the read fails" fallback (brief 1.1 row 1 and 1.2's truth-rule row are superseded):

```python
def _read(repo: Repository, account: WishlistAccount, today: date) -> dict[str, WishlistItem]:
    """Read the wishlist and replace the local hearts from it. Every click starts here: if the
    wishlist cannot be read, nothing is written — to CheapCharts or locally."""
    try:
        items = account.wishlist_items()
    except _REMOTE_ERRORS as exc:
        raise _failed(exc) from exc
    repo.replace_wishlist([i.itunes_id for i in items], today)
    return {i.itunes_id: i for i in items}
```

`wishlist_film`: existing guards unchanged (LookupError; locally wishlisted → return without any call; owned / no store id → NotForSale). Then `items = _read(...)`. If the film is now hearted (`film_id in repo.wishlisted_film_ids()`): look up `items.get(itunes_id)`; if it is missing (hearted through another store id) or has `custom_target` → **return: the film was already there with a target, set by hand or by us — it gets its heart and its target is never touched**. If it is there WITHOUT a custom target (a half-finished earlier click) → fall through to set the target only. Then: `low = lowest_price(...)` (None → `WishlistError("no price history")`, before any write); if the film was not on the wishlist: `add_item` must return True, else `WishlistError("add refused")`; `set_target(itunes_id, target_price(low))`; `repo.mark_wishlisted`. No trailing read.
`unwishlist_film`: guards unchanged; `_read(...)`; if the film is no longer hearted → return (already gone on CheapCharts); else `remove_item` must return True, else `WishlistError("remove refused")`; `repo.unmark_wishlisted`. No trailing read.
`refresh_wishlist` uses `wishlist_items`.
Rewrite the affected unit/API/Playwright fakes and tests to the new rule. Tests that must exist (unit, with fakes logging calls): read happens FIRST and a failed read means NO add/target/remove call and no local change; a film already on the wishlist with a custom target gets its heart and NO add/target call (the hand-set-target invariant — name the test after it); a film there without a custom target gets set-target only, no add; a refused add/remove is a failure; the pre-read replaces every heart; un-wishlisting a film CheapCharts no longer holds makes no remove call and drops the heart; the two acceptance examples ($3.99 / $8.99) over fully mocked HTTP with the real read shape, asserting the call ORDER login → read → DetailData → addItem → changeInitPrice (login happens at the first account call, which is now the read; DetailData may precede it only if you keep the price lookup first — keep the order given here so a failed read costs no public call either).

**C. The reason is named, off-screen.** `_failed(exc) -> WishlistError`: a `CheapChartsError`'s own message (our wording only, pinned since Task 3), `"rate limited"` for `RateLimited`, the class name for a `requests` exception. Update `test_every_remote_failure_becomes_the_one_wishlist_error…` accordingly — deliberately, it pinned the old class-name-only rule. `cli.py`: the dashboard's and the verb's failure lines become `wishlist: couldn't read your CheapCharts wishlist ({reason}) — showing the last known hearts` / `— keeping the last known hearts` (keep `soft_wrap=True`, `markup=False` where brackets could appear; update the three CLI tests, which pin "last known hearts"). `web/app.py`: both wishlist routes log the reason to the server's terminal before answering 502 — `app.logger.warning("wishlist click failed: %s", exc)` — so a failed click is diagnosable next time. **The on-screen line stays exactly `Couldn't reach CheapCharts.`** Never log or print an API message, a response body, a token, an email or a price.

**D. Amend the brief to 1.3 and log the defect.** `brief.md`: version line opening → `**Version 1.3 — amended 2026-09-19 after the hands-on test (1.2 at delivery; 1.1 during the build; 1.0 frozen the same day).**`; append to `## Amendments`:

```markdown
**1.3 — 2026-09-19, by the builder, after your hands-on test found that films already on your wishlist got no heart.** Cause: the wishlist read's answer carries no `status` field (add, set-target and remove do), my code demanded one, and every test had mocked the read from the brief's wording instead of from a real answer — so every read failed while every write worked. Supersedes 1.1's first row and 1.2's truth-rule row.

| Decision | Whose |
|---|---|
| Every click READS your wishlist first and refreshes the hearts from it. If the read fails, nothing is written — not to CheapCharts, not locally — and you see the ordinary failure line | agent default (replaces "read back after the write; if that fails, believe an accepted add") |
| A film the read shows is already on your wishlist WITH a target — set by hand or by us — just gets its heart; its target is never touched. This is what protects a hand-set target even when the local hearts are stale | agent default — it enforces 1.0's "old hand-set targets are not touched" at the moment of the click instead of trusting the last read |
| A film already there WITHOUT a target (a half-finished earlier click) gets its target set, nothing else | agent default |
| An add or a remove CheapCharts refuses is a failure; there is no fallback that believes a write without proof | agent default |
| The terminal names why a read or a click failed (our own wording only — never anything CheapCharts said); the on-screen line stays "Couldn't reach CheapCharts." | agent default |
| Test fixtures for a CheapCharts answer are built from the real answer's shape (ids invented), never from prose | process rule, from this defect |

Correction to "The account API" above, for the record: the Read answers `{results: {ebooks[], movies[], tv[]}, originRequest, responseTimestamp}` with NO `status` key; `idInStore` is a string; `customPrice` is absent when no target is set; `initialPriceValue` may be `-1`.
```

`trial-log.md`, "Surprises and corrections" table, new last row:

```markdown
| 7 | His hands-on test: no film already on his wishlist got a heart. Every wishlist read failed against the real API while every write worked — the read's answer has no `status` field, the brief had generalised one from the write calls, and every test mocked the read from that prose. 1,546 green tests, three reviews and a final review all missed it, because all of them checked the code against the same wrong sentence. Found in his first minutes with the real thing; fixed as amendment 1.3, which also stops any click from writing before a successful read. | implementation defect — caught by the hands-on test, before any merge. Process lesson: a fixture for an external answer must be captured from the real answer, and "proven against the real account" in a brief must say WHICH calls' answers were actually seen |
```

Never hard-wrap; change no other existing line.

**Files:** `src/movie_brain/infrastructure/cheapcharts.py`, `src/movie_brain/application/wishlist.py`, `src/movie_brain/web/app.py`, `src/movie_brain/cli.py`, `tests/unit/test_cheapcharts_account.py`, `tests/unit/test_wishlist.py`, `tests/unit/test_cli.py`, `tests/web/test_wishlist_api.py`, `tests/web/conftest.py` (+ `tests/web/test_wishlist_page.py` only if a fake's behaviour forces it), the two docs. `app.js` does not change.

**Gates and commit:** all four gates; commit subject on the why, e.g. `the wishlist read never worked against the real CheapCharts: its answer has no status field; and no click writes before a successful read, so a hand-set target is safe even when the hearts are stale`.
