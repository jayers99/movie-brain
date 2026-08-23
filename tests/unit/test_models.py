from movie_brain.domain.models import Film, FilmView, film_key, merge_yearless


def test_film_key_matches_legacy_scheme():
    assert film_key("  Seven Samurai ", 1954) == "seven samurai (1954)"
    assert film_key("God is Good", None) == "god is good (None)"


def test_film_key_property():
    assert Film("Trio", 1950, "Ken Annakin", "https://c/trio").key == "trio (1950)"


def _film(title, year, url="https://c/x"):
    return Film(title, year, "Someone", url)


def test_merge_yearless_drops_duplicate_when_titled_twin_is_in_the_batch():
    titled = _film("Trio", 1950, "https://c/trio")
    dupe = _film("Trio", None, "https://c/trio-1")
    assert merge_yearless([titled, dupe], []) == [titled]


def test_merge_yearless_adopts_year_from_known_films():
    known = _film("Trio", 1950, "https://c/trio")
    fetched = _film("Trio", None, "https://c/trio-1")
    assert merge_yearless([fetched], [known]) == [Film("Trio", 1950, "Someone", "https://c/trio-1")]


def test_merge_yearless_keeps_ambiguous_titles_untouched():
    remake_a = _film("Crisis", 1946)
    remake_b = _film("Crisis", 1963)
    yearless = _film("Crisis", None)
    films = [remake_a, remake_b, yearless]
    assert merge_yearless(films, []) == films


def test_merge_yearless_keeps_films_with_no_titled_twin():
    lone = _film("Asparagus", None)
    assert merge_yearless([lone], []) == [lone]


def test_merge_yearless_matches_titles_case_insensitively():
    titled = _film("The Cremator", 1969)
    dupe = _film("the cremator", None)
    assert merge_yearless([titled, dupe], []) == [titled]


def test_film_view_to_dict_round_trips_fields():
    v = FilmView(
        1,
        "Trio",
        1950,
        "Ken Annakin",
        "https://c/trio",
        "English",
        7.1,
        90,
        True,
        False,
        None,
        "2026-08-01",
        8,
        departed=True,
        metacritic=88,
    )
    d = v.to_dict()
    assert d["id"] == 1 and d["imdb"] == 7.1 and d["my_rating"] == 8 and d["pending"] is False
    assert d["departed"] is True and d["metacritic"] == 88
