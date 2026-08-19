from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator
from datetime import date

import pytest
from playwright.sync_api import Page

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app

TODAY = date(2026, 8, 19)


FILMS = [
    Film("Alpha", 1950, "Ann", "https://c/alpha"),  # imdb 8.5 rt 95 English, leaving, rated by me 9
    Film("Bravo", 1960, "Bob", "https://c/bravo"),  # imdb 6.0 rt None French
    Film("Charlie", 1970, "Cy", "https://c/charlie"),  # unmatched
    Film("Delta", 1980, "Dee", "https://c/delta"),  # pending (no omdb row), the only "recently added"
    Film("Echo", 1990, "Ann", "https://c/echo"),  # imdb 7.0 rt 60 "English, Spanish", my rating 0
]


def seed(repo: Repository) -> None:
    films = FILMS
    # Old walk without Delta, then today's walk with all five → only Delta has first_seen = today.
    repo.record_catalog("criterion", [f for f in films if f.title != "Delta"], date(2026, 1, 1))
    repo.record_catalog("criterion", films, TODAY)
    ids = {f.key: repo.film_id_by_key(f.key) for f in films}
    repo.upsert_omdb(
        ids["alpha (1950)"],
        OmdbRating(
            8.5,
            95,
            True,
            "English",
            '{"Title":"Alpha","Plot":"A plot.","Poster":"N/A","Ratings":[{"Source":"Internet Movie Database","Value":"8.5/10"}]}',
        ),
        TODAY,
    )
    repo.upsert_omdb(ids["bravo (1960)"], OmdbRating(6.0, None, True, "French", '{"Title":"Bravo"}'), TODAY)
    repo.upsert_omdb(ids["charlie (1970)"], OmdbRating(None, None, False), TODAY)
    repo.upsert_omdb(ids["echo (1990)"], OmdbRating(7.0, 60, True, "English, Spanish", '{"Title":"Echo"}'), TODAY)
    repo.set_leaving("criterion", {"alpha (1950)": "August 31"})
    repo.set_rating(ids["alpha (1950)"], 9, TODAY)
    repo.set_rating(ids["echo (1990)"], 0, TODAY)


@pytest.fixture(scope="session")
def seeded_repo(tmp_path_factory: pytest.TempPathFactory) -> Repository:
    db = tmp_path_factory.mktemp("web") / "movie-brain.db"
    repo = Repository(db)
    seed(repo)
    return repo


@pytest.fixture(scope="session")
def server(seeded_repo: Repository) -> Generator[str, None, None]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(seeded_repo, today=lambda: TODAY)
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False), daemon=True).start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"


@pytest.fixture
def dash(page: Page, server: str) -> Page:
    page.goto(server)
    page.wait_for_selector("#films tbody[data-count]")
    return page
