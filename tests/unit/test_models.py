from movie_brain.domain.models import Film, FilmView, film_key


def test_film_key_matches_legacy_scheme():
    assert film_key("  Seven Samurai ", 1954) == "seven samurai (1954)"
    assert film_key("God is Good", None) == "god is good (None)"


def test_film_key_property():
    assert Film("Trio", 1950, "Ken Annakin", "https://c/trio").key == "trio (1950)"


def test_film_view_to_dict_round_trips_fields():
    v = FilmView(
        1, "Trio", 1950, "Ken Annakin", "https://c/trio", "English", 7.1, 90, True, False, None, "2026-08-01", 8
    )
    d = v.to_dict()
    assert d["id"] == 1 and d["imdb"] == 7.1 and d["my_rating"] == 8 and d["pending"] is False
