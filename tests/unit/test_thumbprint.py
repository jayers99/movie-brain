import pytest

from movie_brain.domain.thumbprint import Candidate, YearClass, make_query, parse_title, resolve, title_norm


@pytest.mark.parametrize(
    "raw,title,eds,year,alts",
    [
        ("Rear Window (1954)", "Rear Window", (), 1954, ()),
        ("Blade Runner (The Final Cut)", "Blade Runner", ("the final cut",), None, ()),
        ("Straight Outta Compton (Unrated) [2015]", "Straight Outta Compton", ("unrated",), 2015, ()),
        ("Apocalypse Now Redux", "Apocalypse Now", ("redux",), None, ()),
        ("Donnie Darko: The Director's Cut", "Donnie Darko", ("the director's cut",), None, ()),
        ("Band of Outsiders [re-release]", "Band of Outsiders", ("re-release",), None, ()),
        ("(500) Days of Summer", "(500) Days of Summer", (), None, ()),
        ("Caché (Hidden)", "Caché (Hidden)", (), None, ("Hidden",)),
        ("LYNCH (one)", "LYNCH (one)", (), None, ("one",)),
        ("(2019)", "(2019)", (), None, ()),
        ("The Exorcist (Extended Director's Cut) (1973)", "The Exorcist", ("extended director's cut",), 1973, ()),
    ],
)
def test_parse_title(raw, title, eds, year, alts):
    p = parse_title(raw)
    assert (p.title, p.editions, p.embedded_year, p.alt_titles) == (title, eds, year, alts)


def test_base_and_forms_keep_alt_title_for_matching():
    p = parse_title("Caché (Hidden)")
    assert p.base == "Caché" and p.forms() == ("Caché (Hidden)", "Caché", "Hidden")
    assert title_norm("Blade Runner (The Final Cut)") == "bladerunner"


def test_year_class_rule():
    assert make_query("X (1999)", 2011, "apple").year_class is YearClass.DATABASE
    assert make_query("X (1999)", 2011, "apple").year == 1999
    assert make_query("X", 2011, "apple").year_class is YearClass.APPLE_FIELD
    assert make_query("X", 2011, "metacritic").year_class is YearClass.MC
    assert make_query("X", 2011, "criterion").year_class is YearClass.DATABASE


def cand(tt, title, year, director="", votes=0, tmdb=1, in_omdb=True, kind="movie", titles=()):
    return Candidate(tt, tmdb, (title, *titles), year, director, None, votes, kind, tmdb is not None, in_omdb, title)


def test_director_corroborated_beats_year_and_type():
    q = make_query("Die Insel", 1974, "criterion", director="Wim Wenders")
    v = resolve(
        q,
        [cand("tt1", "Die Insel", 1974, "Wim Wenders", kind="episode"), cand("tt2", "Die Insel", 2001, "Someone Else")],
    )
    assert (v.kind, v.tt, v.reason) == ("match", "tt1", "director corroborated")


def test_director_conflict_disqualifies():
    q = make_query("Revenge", 1989, "criterion", director="Yermek Shinarbayev")
    v = resolve(q, [cand("tt2", "Revenge", 1990, "Tony Scott", votes=50000)])
    assert (v.kind, v.reason) == ("review", "director conflicts only")


def test_exact_title_drops_longer_titles():
    q = make_query("Friday the 13th", 1980, "metacritic")
    v = resolve(
        q, [cand("tt1", "Friday the 13th", 1980, votes=200), cand("tt2", "Friday the 13th Part 2", 1981, votes=300)]
    )
    assert v.tt == "tt1"


def test_rerelease_ambiguous_apple_field_year():
    q = make_query("The Boston Strangler", 2004, "apple")
    v = resolve(q, [cand("tt1", "The Boston Strangler", 2006), cand("tt2", "The Boston Strangler", 1968, votes=9000)])
    assert (v.kind, v.reason) == ("review", "rerelease-ambiguous")


def test_commerce_year_is_rerelease_when_nothing_near():
    q = make_query("Mafioso", 2007, "metacritic")
    v = resolve(q, [cand("tt1", "Mafioso", 1962)])
    assert v.kind == "match" and v.reason.startswith("unique older exact title")


def test_votes_dominance():
    q = make_query("Under the Skin", 2014, "metacritic")
    v = resolve(q, [cand("tt1", "Under the Skin", 2013, votes=165354), cand("tt2", "Under the Skin", 2014, votes=0)])
    assert v.tt == "tt1" and v.reason == "votes dominate among year-near exact titles"


def test_generic_title_single_near_hit_without_agreement_is_review():
    q = make_query("Once", 2007, "criterion")
    v = resolve(q, [cand("tt1", "Once", 2007, votes=5, tmdb=None)])
    assert (v.kind, v.reason) == ("review", "ambiguous")


def test_imdb_duplicate_dropped():
    q = make_query("Muhammad Ali, the Greatest", 1974, "criterion")
    v = resolve(
        q,
        [
            cand("tt1", "Muhammad Ali, the Greatest", 1974, votes=500),
            cand("tt2", "Muhammad Ali, the Greatest", 1974, votes=3, tmdb=None),
        ],
    )
    assert v.tt == "tt1"


def test_junk_shape_dropped_unless_director_corroborated():
    q = make_query("Masculin Féminin", 1966, "criterion", director="Jean-Luc Godard")
    junk = cand("tt1", "Bande-annonce de 'Masculin féminin'", 1966, "Jean-Luc Godard", titles=("Masculin Féminin",))
    real = cand("tt2", "Masculine Feminine", 1966, "Jean-Luc Godard", votes=18000, titles=("Masculin Féminin",))
    assert resolve(q, [junk, real]).tt == "tt2"


def test_dateless_unique_exact_with_agreement():
    q = make_query("The Circus of Life", None, "criterion")
    v = resolve(q, [cand("tt1", "The Circus of Life", 1981)])
    assert v.kind == "match" and v.reason.startswith("dateless")
    generic = resolve(make_query("Once", None, "criterion"), [cand("tt1", "Once", 1981)])
    assert (generic.kind, generic.reason) == ("review", "weak")


def test_ranked_carries_top_three():
    q = make_query("Passenger", 2005, "criterion")
    v = resolve(q, [cand(f"tt{i}", "Passenger", 2005, votes=i) for i in range(5)])
    assert v.kind == "review" and len(v.ranked) == 3


def test_no_candidates():
    assert resolve(make_query("Nothing", 2000, "criterion"), []).reason == "no candidates"
