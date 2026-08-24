import pytest

from movie_brain.domain.matching import (
    MatchResult,
    clean_apple_title,
    clean_title,
    match_film,
    match_owned,
    norm_title,
    pick_tmdb_match,
)
from movie_brain.domain.models import TmdbCandidate


def test_clean_title_strips_annotations():
    assert clean_title("Dekalog (1988)") == "Dekalog"
    assert clean_title("The Leopard (re-release)") == "The Leopard"
    assert clean_title("The Leopard (RE-RELEASE)") == "The Leopard"
    assert clean_title("Seven Samurai") == "Seven Samurai"
    # a parenthetical that is part of the title (not year/re-release) survives
    assert clean_title("Fanny (Part One)") == "Fanny (Part One)"


def test_norm_title_is_punctuation_and_case_insensitive():
    assert norm_title("Forbidden Lie$") == norm_title("Forbidden Lies")
    assert norm_title("PlayTime") == norm_title("playtime")
    assert norm_title("Léon") == "léon"  # unicode letters survive; only punctuation/space drop
    assert norm_title("W.R.: Mysteries of the Organism") == norm_title("WR Mysteries of the Organism")


def test_match_exact_year_wins():
    candidates = [(1, "Nosferatu", 1922), (2, "Nosferatu", 1979)]
    assert match_film("Nosferatu", 1979, candidates) == MatchResult(winner=2)


def test_match_us_rerelease_year_drift():
    # MC stamps the US release year: Tokyo Story 1972 must still match the 1953 film.
    assert match_film("Tokyo Story", 1972, [(5, "Tokyo Story", 1953)]) == MatchResult(winner=5)


def test_match_rejects_film_far_newer_than_mc_year():
    # original year > mc_year + 2 → a different film, not a match
    assert match_film("Solaris", 1972, [(9, "Solaris", 2002)]) == MatchResult(winner=None)


def test_match_yearless_film_matches_on_title():
    assert match_film("Trio", 1950, [(3, "Trio", None)]) == MatchResult(winner=3)


def test_match_yearless_mc_title_matches_on_title():
    assert match_film("Trio", None, [(3, "Trio", 1950)]) == MatchResult(winner=3)


def test_match_no_candidates():
    assert match_film("Anything", 2000, []) == MatchResult(winner=None)


def test_match_tie_is_ambiguous():
    # 1978 and 1980 are equidistant from 1979 and both pass the year rule → review, not a guess
    candidates = [(1, "Twin", 1978), (2, "Twin", 1980)]
    result = match_film("Twin", 1979, candidates)
    assert result.winner is None
    assert set(result.tied) == {1, 2}


def test_match_nearest_year_beats_farther():
    candidates = [(1, "Twin", 1950), (2, "Twin", 1978)]
    assert match_film("Twin", 1979, candidates) == MatchResult(winner=2)


def c(tmdb_id, title, year, pop=1.0, original=None):
    return TmdbCandidate(tmdb_id, title, original or title, year, pop)


class TestPickTmdbMatch:
    def test_exact_title_within_a_year_highest_popularity(self):
        cands = [c(1, "Solaris", 2002, pop=9.0), c(2, "Solaris", 1972, pop=5.0), c(3, "Solaris", 1972, pop=8.0)]
        assert pick_tmdb_match("Solaris", 1972, cands) == 3

    def test_original_title_and_punctuation_match(self):
        cands = [c(4, "Forbidden Lies", 2007, original="Forbidden Lie$")]
        assert pick_tmdb_match("Forbidden Lie$", 2007, cands) == 4

    def test_near_year_fallback_takes_first_of_top_three(self):
        cands = [c(5, "Something Else", 1961), c(6, "Other", 1990), c(7, "Another", 1960)]
        assert pick_tmdb_match("The Original Title", 1960, cands) == 5

    def test_fallback_never_reaches_past_top_three(self):
        cands = [c(1, "A", 1990), c(2, "B", 1990), c(3, "C", 1990), c(4, "D", 1960)]
        assert pick_tmdb_match("Missing Film", 1960, cands) is None

    def test_yearless_film_matches_exact_title_only_by_popularity(self):
        # norm_title keeps unicode letters ("Sanshō" != "Sansho"), so use identical titles here.
        cands = [c(8, "Sansho the Bailiff", 1954, pop=3.0), c(9, "Sansho the Bailiff", 1980, pop=1.0)]
        assert pick_tmdb_match("Sansho the Bailiff", None, cands) == 8
        assert pick_tmdb_match("Nothing Like It", None, cands) is None

    def test_no_candidates(self):
        assert pick_tmdb_match("Anything", 2000, []) is None


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("Anchorman 2: The Legend Continues (Unrated)", "Anchorman 2: The Legend Continues"),
        ("Blade Runner (Director's Cut)", "Blade Runner"),
        ("Apocalypse Now (Extended Edition)", "Apocalypse Now"),
        ("Dune (Theatrical Version)", "Dune"),
        ("Alien (Special Edition)", "Alien"),
        ("Trainspotting (Uncut)", "Trainspotting"),
        ("Jaws (Remastered)", "Jaws"),
        ("Lawrence of Arabia (4K)", "Lawrence of Arabia"),
        ("Parasite (Subtitled)", "Parasite"),
        ("Spirited Away (Dubbed)", "Spirited Away"),
        ("Amelie (English Subtitles)", "Amelie"),
        ("Shaun of the Dead", "Shaun of the Dead"),  # no annotation
        ("Notting Hill (1999)", "Notting Hill (1999)"),  # unknown parenthetical kept
    ],
)
def test_clean_apple_title(raw, cleaned):
    assert clean_apple_title(raw) == cleaned


def test_match_owned_exact_year_wins():
    cands = [(1, "Solaris", 1972), (2, "Solaris", 2002)]
    assert match_owned("Solaris", 2002, cands).winner == 2


def test_match_owned_accepts_one_year_drift():
    assert match_owned("Alpha", 1951, [(1, "Alpha", 1950)]).winner == 1


def test_match_owned_rejects_two_year_drift():
    r = match_owned("Alpha", 1952, [(1, "Alpha", 1950)])
    assert r.winner is None and r.tied == ()


def test_match_owned_tie_is_ambiguous():
    r = match_owned("Twin", 1979, [(1, "Twin", 1978), (2, "Twin", 1980)])
    assert r.winner is None and set(r.tied) == {1, 2}


def test_match_owned_yearless_needs_unique_candidate():
    assert match_owned("Solo", None, [(1, "Solo", 1996)]).winner == 1
    r = match_owned("Twin", None, [(1, "Twin", 1978), (2, "Twin", 1980)])
    assert r.winner is None and set(r.tied) == {1, 2}
