import pytest

from movie_brain.domain.matching import (
    Candidate,
    CandidateIndex,
    MatchQuery,
    MatchResult,
    MatchVerdict,
    YearKind,
    clean_apple_title,
    clean_title,
    match_candidates,
    match_film,
    match_owned,
    norm_title,
    parse_apple_title,
    pick_tmdb_match,
    split_annotations,
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
    assert norm_title("Léon") == "leon"  # diacritics fold; only punctuation/space drop
    assert norm_title("W.R.: Mysteries of the Organism") == norm_title("WR Mysteries of the Organism")


def test_norm_title_folds_diacritics():
    assert norm_title("Tête") == "tete"
    assert norm_title("Léon") == "leon"


def test_norm_title_ampersand_and_volume():
    assert norm_title("Willy Wonka & the Chocolate Factory") == norm_title("Willy Wonka and the Chocolate Factory")
    assert norm_title("Kill Bill: Vol. 1") == norm_title("Kill Bill: Volume 1")
    assert norm_title("Kill Bill Vol 2") == norm_title("Kill Bill Volume 2")
    assert norm_title("Volcano") == "volcano"  # \bvol\b must not fire inside words


def test_split_annotations_grammar():
    assert split_annotations("The Red Shoes [re-release]") == ("The Red Shoes", ("re-release",))
    assert split_annotations("The Leopard (Restored Version)") == ("The Leopard", ("restored version",))
    assert split_annotations("Star Trek: The Motion Picture – The Director's Edition") == (
        "Star Trek: The Motion Picture",
        ("director's edition",),
    )
    assert split_annotations("Blade Runner (Director's Cut) (4K)") == ("Blade Runner", ("4k", "director's cut"))
    assert split_annotations("Fanny (Part One)") == ("Fanny (Part One)", ())  # unknown parenthetical survives
    assert split_annotations("(Unrated)") == ("(Unrated)", ())  # never strip to empty


def test_match_exact_year_wins():
    candidates = [(1, "Nosferatu", 1922), (2, "Nosferatu", 1979)]
    assert match_film("Nosferatu", 1979, candidates) == MatchResult(winner=2)


def test_match_us_rerelease_year_drift_reviews_uncorroborated_gap():
    # MC stamps the US release year: an uncorroborated 19-year trailing gap is no longer
    # auto-matched (was: match) — M1 keeps wrong-match ~0 and asks for the M2 arbiter class.
    assert match_film("Tokyo Story", 1972, [(5, "Tokyo Story", 1953)]) == MatchResult(None, (), "year-gap")


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

    def test_no_title_match_near_year_fallback_removed(self):
        # The old title-blind "first of top-3 within +/-1 year" fallback is gone — it was
        # the Lawrence-of-Arabia-to-731627 wrong-match vector — so a title with no title
        # hit at all is a create/None, never a near-year guess.
        cands = [c(5, "Something Else", 1961), c(6, "Other", 1990), c(7, "Another", 1960)]
        assert pick_tmdb_match("The Original Title", 1960, cands) is None

    def test_fallback_never_reaches_past_top_three(self):
        cands = [c(1, "A", 1990), c(2, "B", 1990), c(3, "C", 1990), c(4, "D", 1960)]
        assert pick_tmdb_match("Missing Film", 1960, cands) is None

    def test_yearless_film_matches_exact_title_only_by_popularity(self):
        # Uses identical titles for both candidates; year is what distinguishes them here.
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


@pytest.mark.parametrize(
    ("raw", "title", "year"),
    [
        ("Rear Window (1954)", "Rear Window", 1954),  # embedded year is the original release year
        ("Vertigo (1958)", "Vertigo", 1958),
        ("Ran (1985)", "Ran", 1985),
        ("12 Angry Men (1957) (Unrated)", "12 Angry Men", 1957),  # annotation outside the year
        ("Anchorman 2: The Legend Continues (Unrated)", "Anchorman 2: The Legend Continues", None),
        ("Blade Runner (Director's Cut)", "Blade Runner", None),
        ("Shaun of the Dead", "Shaun of the Dead", None),
        ("(1985)", "(1985)", None),  # never strip down to an empty title
    ],
)
def test_parse_apple_title(raw, title, year):
    assert parse_apple_title(raw) == (title, year)


def test_match_owned_exact_year_wins():
    cands = [(1, "Solaris", 1972), (2, "Solaris", 2002)]
    assert match_owned("Solaris", 2002, cands).winner == 2


def test_match_owned_accepts_one_year_drift():
    assert match_owned("Alpha", 1951, [(1, "Alpha", 1950)]).winner == 1


def test_match_owned_commerce_two_year_drift_reviews_year_gap():
    # Default (no embedded_year) is COMMERCE: an uncorroborated >1-year gap reviews
    # rather than silently rejecting — same year-gap rule as match_film.
    assert match_owned("Alpha", 1952, [(1, "Alpha", 1950)]) == MatchResult(None, (), "year-gap")


def test_match_owned_tie_is_ambiguous():
    r = match_owned("Twin", 1979, [(1, "Twin", 1978), (2, "Twin", 1980)])
    assert r.winner is None and set(r.tied) == {1, 2}


def test_match_owned_yearless_needs_unique_candidate():
    assert match_owned("Solo", None, [(1, "Solo", 1996)]).winner == 1
    r = match_owned("Twin", None, [(1, "Twin", 1978), (2, "Twin", 1980)])
    assert r.winner is None and set(r.tied) == {1, 2}


def test_match_owned_embedded_year_is_tight_database_band():
    # An embedded title year is DATABASE-trust: exact wins...
    assert match_owned("Rear Window", 1954, [(1, "Rear Window", 1954)], embedded_year=True).winner == 1
    # ...and a 2-year disagreement disqualifies (DATABASE, |delta|>1) rather than
    # trailing-gap-reviewing like the COMMERCE default.
    r = match_owned("Nosferatu", 1924, [(1, "Nosferatu", 1922)], embedded_year=True)
    assert r == MatchResult(None, (), "conflict")


def test_match_owned_field_year_gap_with_runtime_corroboration_matches():
    # A plain (non-embedded) field year is COMMERCE: a trailing gap alone would review,
    # but a corroborating runtime match earns the win.
    cand = Candidate(1, "Stop Making Sense", 1984, runtime_min=88)
    assert match_owned("Stop Making Sense", 1999, [cand], runtime_min=88) == MatchResult(winner=1)


def test_match_owned_rerelease_hint_kwarg_corroborates_commerce_gap():
    # Fix round 1: owned.py pre-strips annotations before calling match_owned (via
    # parse_apple_title), so match_owned's own internal split_annotations(title) hint
    # is always False for that caller. The explicit rerelease_hint kwarg is how a
    # caller that already stripped the title can still corroborate a commerce-year
    # gap — e.g. "The Leopard (Restored Version)" (2004) vs the 1963 original.
    r = match_owned("The Leopard", 2004, [(1, "The Leopard", 1963)], rerelease_hint=True)
    assert r == MatchResult(winner=1)
    # Without the kwarg (and no annotation left in the already-stripped title), the
    # same gap is uncorroborated and reviews instead of guessing.
    r2 = match_owned("The Leopard", 2004, [(1, "The Leopard", 1963)])
    assert r2 == MatchResult(None, (), "year-gap")


def test_match_owned_accepts_plain_tuple_candidate_index_and_list():
    # Old-style (id, title, year) tuples, a list[Candidate], and a prebuilt
    # CandidateIndex must all still work as the candidates argument.
    tuple_result = match_owned("Solaris", 1972, [(1, "Solaris", 1972)])
    candidate_result = match_owned("Solaris", 1972, [Candidate(1, "Solaris", 1972)])
    index = CandidateIndex([Candidate(1, "Solaris", 1972)])
    index_result = match_owned("Solaris", 1972, index)
    assert tuple_result == candidate_result == index_result == MatchResult(winner=1)


def test_match_film_maps_review_reason_onto_match_result():
    # A level-2 (colon-prefix) hit with no year support reviews "weak-title" — match_film
    # must surface that core reason on MatchResult.reason, not just winner=None.
    idx = CandidateIndex([Candidate(1, "Hearts of Darkness: A Filmmaker's Apocalypse", 1991)])
    result = match_film("Hearts of Darkness", None, idx)
    assert result == MatchResult(None, (), "weak-title")


def C(
    id: int,
    title: str,
    year: int | None,
    director: str | None = None,
    runtime: int | None = None,
    pop: float | None = None,
) -> Candidate:
    return Candidate(id, title, year, director, runtime, pop)


class TestCandidateIndex:
    def test_l0_exact_beats_l1(self) -> None:
        # A decoy candidate whose L1 (annotation-stripped) bucket also normalizes to
        # "nosferatu" must not surface once an L0 exact hit is found.
        idx = CandidateIndex([C(1, "Nosferatu", 1922), C(2, "Nosferatu (Remastered)", 2000)])
        level, hits = idx.lookup("Nosferatu")
        assert level == 0
        assert [c.id for c in hits] == [1]

    def test_l1_annotation_stripped(self) -> None:
        idx = CandidateIndex([C(1, "The Leopard", 1963)])
        assert idx.lookup("The Leopard (Restored Version)") == (1, [C(1, "The Leopard", 1963)])

    def test_l2_subtitle_prefix_requires_two_words(self) -> None:
        idx = CandidateIndex([C(1, "Hearts of Darkness: A Filmmaker's Apocalypse", 1991)])
        level, hits = idx.lookup("Hearts of Darkness")
        assert level == 2 and hits[0].id == 1
        # single-word prefix never indexes: "Ran: Something" must NOT be reachable via "Ran"
        idx2 = CandidateIndex([C(2, "Ran: Something", 1985)])
        level2, hits2 = idx2.lookup("Ran")
        assert level2 == -1 and hits2 == []


class TestMatchCandidates:
    # commerce year: neutral-with-gap, disqualifying-early
    def test_commerce_gap_no_corroboration_reviews(self) -> None:
        idx = CandidateIndex([C(1, "Stop Making Sense", 1984)])
        query = MatchQuery(title="Stop Making Sense", year=1999, year_kind=YearKind.COMMERCE)
        assert match_candidates(query, idx) == MatchVerdict(kind="review", reason="year-gap")

    def test_commerce_gap_with_runtime_matches(self) -> None:
        idx = CandidateIndex([C(1, "Stop Making Sense", 1984, runtime=88)])
        query = MatchQuery(title="Stop Making Sense", year=1999, year_kind=YearKind.COMMERCE, runtime_min=88)
        assert match_candidates(query, idx) == MatchVerdict(kind="match", film_id=1)

    def test_commerce_gap_with_rerelease_hint_matches(self) -> None:
        idx = CandidateIndex([C(1, "Lawrence of Arabia", 1962)])
        query = MatchQuery(title="Lawrence of Arabia", year=2012, year_kind=YearKind.COMMERCE)
        assert match_candidates(query, idx, rerelease_hint=True) == MatchVerdict(kind="match", film_id=1)

    def test_commerce_year_earlier_than_all_candidates_creates(self) -> None:
        idx = CandidateIndex([C(1, "Solaris", 2002)])
        query = MatchQuery(title="Solaris", year=1972, year_kind=YearKind.COMMERCE)
        assert match_candidates(query, idx) == MatchVerdict(kind="create")

    def test_database_year_two_off_reviews(self) -> None:
        idx = CandidateIndex([C(1, "Nosferatu", 1952)])
        query = MatchQuery(title="Nosferatu", year=1954, year_kind=YearKind.DATABASE)
        assert match_candidates(query, idx) == MatchVerdict(kind="review", reason="conflict")

    # director / runtime evidence
    def test_director_conflict_reviews(self) -> None:
        idx = CandidateIndex([C(1, "Titanic", 1953, director="Jean Negulesco")])
        query = MatchQuery(title="Titanic", year=1953, year_kind=YearKind.DATABASE, director="James Cameron")
        assert match_candidates(query, idx) == MatchVerdict(kind="review", reason="conflict")

    def test_shared_director_in_comma_list_supports(self) -> None:
        idx = CandidateIndex([C(1, "Swiss Family Robinson", 1960, director="Ken Annakin, Harold French")])
        query = MatchQuery(title="Swiss Family Robinson", year=1960, year_kind=YearKind.DATABASE, director="Harold French")
        assert match_candidates(query, idx) == MatchVerdict(kind="match", film_id=1)

    def test_runtime_divergence_reviews(self) -> None:
        idx = CandidateIndex([C(1, "Nosferatu", 1922, runtime=94)])
        query = MatchQuery(title="Nosferatu", year=1922, year_kind=YearKind.DATABASE, runtime_min=132)
        assert match_candidates(query, idx) == MatchVerdict(kind="review", reason="conflict")

    # verdicts
    def test_no_candidates_creates(self) -> None:
        idx = CandidateIndex([])
        query = MatchQuery(title="Anything", year=2000, year_kind=YearKind.DATABASE)
        assert match_candidates(query, idx) == MatchVerdict(kind="create")

    def test_tie_reviews_with_tied_ids(self) -> None:
        idx = CandidateIndex([C(1, "Twin", 1978), C(2, "Twin", 1980)])
        query = MatchQuery(title="Twin", year=1979, year_kind=YearKind.DATABASE)
        verdict = match_candidates(query, idx)
        assert verdict == MatchVerdict(kind="review", reason="ambiguous", tied=(1, 2))

    def test_popularity_tiebreak_only_when_enabled(self) -> None:
        idx = CandidateIndex([C(1, "Twin", 1979, pop=5.0), C(2, "Twin", 1979, pop=8.0)])
        query = MatchQuery(title="Twin", year=1979, year_kind=YearKind.DATABASE)
        assert match_candidates(query, idx) == MatchVerdict(kind="review", reason="ambiguous", tied=(1, 2))
        assert match_candidates(query, idx, popularity_tiebreak=True) == MatchVerdict(kind="match", film_id=2)

    def test_l2_alone_without_year_reviews_weak_title(self) -> None:
        idx = CandidateIndex([C(1, "Hearts of Darkness: A Filmmaker's Apocalypse", 1991)])
        query = MatchQuery(title="Hearts of Darkness", year=None, year_kind=YearKind.DATABASE)
        assert match_candidates(query, idx) == MatchVerdict(kind="review", reason="weak-title")

    # arbitration hook (interface only)
    def test_arbiter_hit_reviews_remake_suspected(self) -> None:
        idx = CandidateIndex([C(1, "Stop Making Sense", 1984)])
        query = MatchQuery(title="Stop Making Sense", year=1999, year_kind=YearKind.COMMERCE)
        verdict = match_candidates(query, idx, arbiter=lambda t, y: True)
        assert verdict == MatchVerdict(kind="review", reason="remake-suspected")

    def test_arbiter_miss_matches_original(self) -> None:
        idx = CandidateIndex([C(1, "Stop Making Sense", 1984)])
        query = MatchQuery(title="Stop Making Sense", year=1999, year_kind=YearKind.COMMERCE)
        verdict = match_candidates(query, idx, arbiter=lambda t, y: False)
        assert verdict == MatchVerdict(kind="match", film_id=1)

    def test_arbiter_unavailable_falls_back_to_year_gap_review(self) -> None:
        idx = CandidateIndex([C(1, "Stop Making Sense", 1984)])
        query = MatchQuery(title="Stop Making Sense", year=2023, year_kind=YearKind.COMMERCE)
        verdict = match_candidates(query, idx, arbiter=lambda t, y: None)
        assert verdict.kind == "review" and verdict.reason == "year-gap"


def _tc(tmdb_id, title, year, popularity=1.0):
    return TmdbCandidate(tmdb_id, title, title, year, popularity)


def test_pick_tmdb_commerce_rerelease_matches_original_when_no_remake():
    # Stop Making Sense: commerce-created with the 2023 re-release year; TMDB only
    # knows the 1984 original → arbiter finds nothing near 2023 → match it.
    cands = [_tc(606, "Stop Making Sense", 1984)]
    arbiter = lambda t, y: False  # noqa: E731
    assert pick_tmdb_match("Stop Making Sense", 2023, cands, commerce_year=True, arbiter=arbiter) == 606


def test_pick_tmdb_commerce_gap_without_arbiter_is_a_miss():
    cands = [_tc(606, "Stop Making Sense", 1984)]
    assert pick_tmdb_match("Stop Making Sense", 2023, cands, commerce_year=True) is None


def test_pick_tmdb_commerce_remake_suspected_is_a_miss():
    cands = [_tc(606, "Stop Making Sense", 1984)]
    assert pick_tmdb_match("Stop Making Sense", 2023, cands, commerce_year=True, arbiter=lambda t, y: True) is None


def test_pick_tmdb_database_band_unchanged():
    # Criterion-walked films keep the tight band: a 2-year gap disqualifies.
    cands = [_tc(947, "Lawrence of Arabia", 1962)]
    assert pick_tmdb_match("Lawrence of Arabia", 1962, cands) == 947
    assert pick_tmdb_match("Lawrence of Arabia", 1964, cands) is None


def test_match_film_arbiter_resolves_year_gap():
    # Tokyo Story class: MC's 1972 US release vs our 1953 film — the arbiter says
    # no same-titled film exists near 1972, so the gap is a re-release: match.
    index = CandidateIndex([Candidate(id=7, title="Tokyo Story", year=1953)])
    assert match_film("Tokyo Story", 1972, index).winner is None  # no arbiter: review
    result = match_film("Tokyo Story", 1972, index, arbiter=lambda t, y: False)
    assert result.winner == 7
    hit = match_film("Tokyo Story", 1972, index, arbiter=lambda t, y: True)
    assert hit.winner is None and hit.reason == "remake-suspected"


def test_rerelease_hint_with_same_year_twin_and_older_original_is_review():
    from movie_brain.domain.matching import Candidate, match_film

    pool = [Candidate(1, "Metropolis", 1927), Candidate(2, "Metropolis", 2001)]
    assert match_film("Metropolis (re-release)", 2001, pool).reason == "rerelease-ambiguous"
    # No annotation → the exact-year film is the honest answer.
    assert match_film("Metropolis", 2001, pool).winner == 2
    # Annotation but no same-year twin → hint excuses the gap, original matches (Lawrence class).
    assert match_film("Metropolis (re-release)", 2001, [Candidate(1, "Metropolis", 1927)]).winner == 1


def test_pick_tmdb_dateless_candidate_cannot_win_among_year_disqualified_twins():
    # Intolerance (1916): every dated same-title candidate fails the DATABASE band; the one
    # dateless short must not inherit the match by default — it is a miss (review).
    cands = [_tc(48684, "Intolerance", 2000), _tc(879617, "Intolerance", 2020), _tc(1216137, "Intolerance", None)]
    assert pick_tmdb_match("Intolerance", 1916, cands) is None


def test_match_candidates_reports_yearless_among_dated():
    idx = CandidateIndex([C(1, "Intolerance", 2000), C(2, "Intolerance", None)])
    verdict = match_candidates(MatchQuery(title="Intolerance", year=1916, year_kind=YearKind.DATABASE), idx)
    assert verdict.kind == "review" and verdict.reason == "yearless-among-dated"


def test_pick_tmdb_lone_dateless_candidate_still_matches():
    # No dated rival was disqualified: a dateless entry is the only reading of the title.
    assert pick_tmdb_match("Trio", 1950, [_tc(3, "Trio", None)]) == 3


def test_pick_tmdb_feature_wins_via_original_title_over_the_dateless_short():
    # The live candidate set once the year retry adds the Griffith feature: its display title
    # carries a one-word colon prefix (never indexed — "Ran: Something" ≠ "Ran"), but its
    # original_title is the bare "Intolerance": exact title + exact year beats the dateless short.
    cands = [
        _tc(48684, "Intolerance", 2000),
        _tc(1216137, "Intolerance", None),
        TmdbCandidate(3059, "Intolerance: Love's Struggle Throughout the Ages", "Intolerance", 1916, 3.5),
    ]
    assert pick_tmdb_match("Intolerance", 1916, cands) == 3059
