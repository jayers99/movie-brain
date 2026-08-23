from movie_brain.domain.matching import MatchResult, clean_title, match_film, norm_title


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
