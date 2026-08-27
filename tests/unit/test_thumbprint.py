import pytest

from movie_brain.domain.thumbprint import (
    Candidate,
    Scored,
    Verdict,
    YearClass,
    make_query,
    parse_title,
    resolve,
    title_norm,
)


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


def test_review_detail_serializes_top_three_with_letters():
    import json

    from movie_brain.application.thumbprint import review_detail

    q = make_query("Passenger", 2005, "criterion")
    v = resolve(q, [cand(f"tt{i}", "Passenger", 2005, votes=i) for i in range(5)])
    d = json.loads(review_detail(v))
    assert d["reason"] == "ambiguous"
    assert [c["letter"] for c in d["candidates"]] == ["A", "B", "C"]
    assert all(c["why_not"] for c in d["candidates"])


def test_review_detail_round_trips_with_query():
    from movie_brain.application.thumbprint import parse_review_detail, review_detail

    q = make_query("Blade Runner (The Final Cut)", 2007, "apple", director=None, runtime_min=117)
    c = Candidate("tt0083658", 78, ("Blade Runner",), 1982, "Ridley Scott", 117, 10000, "movie", True, True)
    v = Verdict("review", None, "rerelease-ambiguous", (Scored(c, 5, 3, 0, 0, False, False),))
    d = parse_review_detail(review_detail(v, q))
    assert d is not None and d.reason == "rerelease-ambiguous"
    assert d.candidates[0]["letter"] == "A" and d.candidates[0]["tt"] == "tt0083658"
    assert d.query == {
        "title": "Blade Runner (The Final Cut)",
        "year": 2007,
        "source": "apple",
        "director": None,
        "runtime": 117,
    }


def test_parse_review_detail_returns_none_for_legacy_text():
    from movie_brain.application.thumbprint import parse_review_detail

    assert parse_review_detail("King Kong (1933)") is None
    assert parse_review_detail(None) is None


def test_load_edition_contract_reads_verified_c_rows(tmp_path):
    from movie_brain.application.repair import load_edition_contract

    csv = tmp_path / "eval.csv"
    csv.write_text(
        "group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,"
        "director,runtime_min\n"
        "C-edition,4409,apple,Blade Runner (The Final Cut),2007,tt0083658,78,x,work='Blade Runner' 1982; "
        "edition=['the final cut']; films.year=2007,verified,,117\n"
        "C-edition,4503,apple,Moonwalk One (The Director's Cut),2009,,,x,NEEDS HUMAN,proposed,,108\n"
        "B-apple-year-title,1,apple,X (1999),1999,tt1,2,x,twin 3,verified,,\n"
    )
    c = load_edition_contract(csv)
    assert set(c) == {4409}
    assert c[4409].work_title_note == "Blade Runner" and c[4409].work_year == 1982
    assert c[4409].tt == "tt0083658" and c[4409].tmdb_id == "78"


def _edition_film(repo, title, year):
    from datetime import date

    from movie_brain.domain.models import Film
    from movie_brain.domain.thumbprint import title_norm as tnorm

    fid = repo.create_film(Film(title, year, None, ""))
    repo.set_title_norm(fid, tnorm(title))
    repo.add_claim(fid, "metacritic", f"slug-{fid}", title, year_claimed=year, first_seen=date(2026, 8, 25).isoformat())
    return fid


def test_audit_editions_keeps_a_note_title_that_names_another_work_informational(repo):
    """Quai des Orfèvres: the note carries TMDB's English title — informational, not a mismatch."""
    from movie_brain.application.repair import EditionContract, audit_editions

    fid = _edition_film(repo, "Quai des Orfèvres [re-release]", 2002)
    contract = {fid: EditionContract(fid, "Jenny Lamour", 1947, "tt0039739", "49842")}
    (g,) = audit_editions(repo, contract)
    assert (g.verdict, g.work_title, g.work_year, g.edition_year) == ("no-twin", "Quai des Orfèvres", 1947, 2002)


def test_audit_editions_flags_a_row_that_is_no_longer_an_edition_of_anything(repo):
    from movie_brain.application.repair import EditionContract, audit_editions

    fid = _edition_film(repo, "Some Other Film", 2004)
    contract = {fid: EditionContract(fid, "Donnie Darko", 2001, "tt0246578", "141")}
    (g,) = audit_editions(repo, contract)
    assert g.verdict == "csv-mismatch"


def test_audit_editions_upgrades_the_work_title_casing_from_the_contract(repo):
    from movie_brain.application.repair import EditionContract, audit_editions

    fid = _edition_film(repo, "Goodfellas (Remastered Feature)", 2015)
    contract = {fid: EditionContract(fid, "GoodFellas", 1990, "tt0099685", "769")}
    (g,) = audit_editions(repo, contract)
    assert (g.verdict, g.work_title) == ("no-twin", "GoodFellas")


def test_audit_editions_twin_path_blocks_when_the_work_key_is_held_elsewhere(repo):
    """The survivor still parses with editions, so it gets re-keyed — a third film already
    holding that key must downgrade the group to `conflict` BEFORE the merge is committed."""
    from movie_brain.application.repair import EditionContract, audit_editions
    from movie_brain.domain.models import Film

    loser = _edition_film(repo, "Donnie Darko: The Director's Cut", 2004)
    survivor = _edition_film(repo, "Donnie Darko: Anniversary Special Edition", 2001)
    repo.create_film(Film("Donnie Darko", 2001, None, ""))  # holds 'donnie darko (2001)'
    contract = {
        fid: EditionContract(fid, "Donnie Darko", 2001, "tt0246578", "141") for fid in (loser, survivor)
    }
    (g,) = audit_editions(repo, contract)
    assert (g.film_id, g.verdict, g.twin_id) == (loser, "conflict", None)
    assert g.twin_title == "Donnie Darko: Anniversary Special Edition"
    assert f"twin #{survivor} but key 'donnie darko (2001)' held by #" in g.detail


def test_audit_editions_blocks_a_twin_that_holds_a_different_imdb_id(repo):
    """The merge writes the contract tt onto the survivor; a survivor already keyed to another
    work is not this work's twin, and keeping its id silently would hide the disagreement."""
    from datetime import date

    from movie_brain.application.repair import EditionContract, audit_editions
    from movie_brain.domain.models import Film
    from movie_brain.domain.thumbprint import title_norm as tnorm

    fid = _edition_film(repo, "Overlord [re-release]", 2006)
    twin = repo.create_film(Film("Overlord", 1975, None, ""))
    repo.set_title_norm(twin, tnorm("Overlord"))
    repo.set_external_id(twin, "tmdb", "55343", date(2026, 8, 25))
    repo.set_external_id(twin, "imdb", "tt0080749", date(2026, 8, 25))  # the 2018 film's tt
    contract = {fid: EditionContract(fid, "Overlord", 1975, "tt0073502", "55343")}
    (g,) = audit_editions(repo, contract)
    assert (g.verdict, g.twin_id) == ("conflict", None)
    assert g.detail == f"twin #{twin} but holds imdb tt0080749, contract says tt0073502"


def test_audit_editions_blocks_on_a_tt_held_by_a_disposed_film(repo):
    """`key_work`'s UNIQUE(authority, value) refusal is blind to dispositions, so the pre-check
    must be too — holders built from live films only would promise a write the DB refuses."""
    from datetime import date

    from movie_brain.application.repair import EditionContract, audit_editions

    fid = _edition_film(repo, "Blade Runner (The Final Cut)", 2007)
    ghost = _edition_film(repo, "Blade Runner (ghost)", 1982)
    repo.set_external_id(ghost, "imdb", "tt0083658", date(2026, 8, 25))
    repo.tombstone_film(ghost, date(2026, 8, 25), note="x")
    contract = {fid: EditionContract(fid, "Blade Runner", 1982, "tt0083658", "78")}
    (g,) = audit_editions(repo, contract)
    assert g.verdict == "conflict" and f"tt0083658 held by #{ghost}" in g.detail


def test_audit_editions_defers_a_film_criterion_still_lists(repo):
    """`record_catalog` upserts ON CONFLICT(films.key): re-keying a listed film would mint a
    duplicate on the next walk."""
    from datetime import date

    from movie_brain.application.repair import EditionContract, audit_editions
    from movie_brain.domain.models import Film

    fid = _edition_film(repo, "SCENES FROM A MARRIAGE: Theatrical Version", 1973)
    repo.record_catalog(
        "criterion",
        [Film("SCENES FROM A MARRIAGE: Theatrical Version", 1973, None, "https://c/sfam")],
        date(2026, 8, 25),
    )
    contract = {fid: EditionContract(fid, "Scenes from a Marriage", 1974, "tt6725014", "133919")}
    (g,) = audit_editions(repo, contract)
    assert g.verdict == "conflict"
    assert g.detail == "current criterion listing — re-key deferred to the ingester switch"


def test_repair_editions_stops_the_batch_when_survivor_keying_refuses_after_the_merge(repo, monkeypatch):
    from datetime import date

    from movie_brain.application.repair import EditionContract, repair_editions

    loser = _edition_film(repo, "Donnie Darko: The Director's Cut", 2004)
    survivor = _edition_film(repo, "Donnie Darko: Anniversary Special Edition", 2001)
    contract = {
        fid: EditionContract(fid, "Donnie Darko", 2001, "tt0246578", "141") for fid in (loser, survivor)
    }
    monkeypatch.setattr(repo, "key_work", lambda *a, **k: False)  # a concurrent writer took the key
    log: list[str] = []
    with pytest.raises(RuntimeError, match="PARTIAL"):
        repair_editions(
            repo, date(2026, 8, 25), apply=True, confirm=lambda g: True, contract=contract, log=log.append
        )
    assert any(line.startswith("[partial] ") and "survivor keying refused" in line for line in log)
    assert repo.disposition_of(loser) == ("merged", survivor)
