from movie_brain.domain.audit import VERDICTS, WEIGHTS, AuditSubject, normalize_title, run_checks, total_score


def subject(**kw) -> AuditSubject:
    base = dict(
        film_id=1, title="Alpha", year=1950, criterion_director=None, mc_score=None,
        omdb_title=None, omdb_year=None, omdb_director=None, omdb_runtime_min=None, omdb_imdb_id=None,
        omdb_type=None, omdb_imdb_rating=None, omdb_metascore=None,
        tmdb_imdb_id=None, tmdb_title=None, tmdb_original_title=None, tmdb_alt_titles=(), tmdb_runtime_min=None,
        shared_imdb_film_ids=(),
    )
    base.update(kw)
    return AuditSubject(**base)


def codes(s: AuditSubject) -> list[str]:
    return [f.code for f in run_checks(s)]


def test_vocabulary_and_weights():
    assert VERDICTS == ("fine", "omdb-wrong", "tmdb-wrong", "film-wrong", "twin")
    assert WEIGHTS == {
        "mc-score": 3, "imdb-id": 3, "tmdb-title": 3, "omdb-title": 2, "director": 2,
        "runtime": 2, "shared-imdb": 2, "year": 1, "stub": 1,
    }


def test_normalize_title_strips_diacritics_punctuation_articles_and_annotations():
    assert normalize_title("The Deer Hunter") == "deer hunter"
    assert normalize_title("L'Armée des ombres") == "l armee des ombres"
    assert normalize_title("La piscine") == "piscine"
    assert normalize_title("Investigation of a Citizen Above Suspicion [re-release]") == "investigation of a citizen above suspicion"
    assert normalize_title("Schindler's List") == "schindler s list"


def test_no_evidence_no_flags():
    assert codes(subject()) == []


def test_deer_hunter_stub_and_imdb_id():
    s = subject(
        title="The Deer Hunter", year=1978,
        omdb_title="The Deer Hunter (1978)", omdb_year=1978, omdb_director="N/A", omdb_imdb_rating="N/A",
        omdb_imdb_id="tt24735970", omdb_type="movie", tmdb_imdb_id="tt0077416",
    )
    got = codes(s)
    assert "stub" in got and "imdb-id" in got
    assert "omdb-title" in got  # "The Deer Hunter (1978)" normalizes to "deer hunter 1978" ≠ "deer hunter"
    assert "year" not in got


def test_schindler_omdb_title_is_equality_not_containment():
    s = subject(
        title="Schindler's List", year=1993,
        omdb_title="The Making of 'Schindler's List'", omdb_year=1993, omdb_imdb_id="tt2709758",
        tmdb_imdb_id="tt0108052", omdb_type="movie",
    )
    got = codes(s)
    assert got == ["imdb-id", "omdb-title"]
    assert total_score(run_checks(s)) == 5


def test_army_of_shadows_prefix_year_only():
    s = subject(
        title="Army of Shadows", year=1969,
        omdb_title="Army of Shadows", omdb_year=2006, omdb_imdb_id="tt0064040", tmdb_imdb_id="tt0064040",
        omdb_type="movie", omdb_director="Jean-Pierre Melville", omdb_imdb_rating="8.1",
    )
    assert codes(s) == ["year"]


def test_year_within_one_does_not_fire():
    assert codes(subject(year=1978, omdb_year=1979, omdb_title="Alpha")) == []


def test_mc_score_disagreement():
    assert codes(subject(mc_score=95, omdb_metascore=61, omdb_title="Alpha")) == ["mc-score"]
    assert codes(subject(mc_score=95, omdb_metascore=95, omdb_title="Alpha")) == []


def test_director_shares_no_surname():
    assert codes(subject(criterion_director="Powell & Pressburger", omdb_director="Michael Powell, Emeric Pressburger", omdb_title="Alpha")) == []
    assert codes(subject(criterion_director="Jean Renoir", omdb_director="Michael Curtiz", omdb_title="Alpha")) == ["director"]


def test_runtime_gap_over_ten_minutes():
    assert codes(subject(omdb_runtime_min=90, tmdb_runtime_min=105, omdb_title="Alpha")) == ["runtime"]
    assert codes(subject(omdb_runtime_min=90, tmdb_runtime_min=99, omdb_title="Alpha")) == []


def test_tmdb_title_matches_any_of_title_original_or_alts():
    assert codes(subject(title="Harakiri", tmdb_title="Harakiri", tmdb_original_title="切腹")) == []
    assert codes(subject(title="Harakiri", tmdb_title="Seppuku", tmdb_original_title="切腹", tmdb_alt_titles=("Harakiri",))) == []
    assert codes(subject(title="Harakiri", tmdb_title="Seppuku", tmdb_original_title="切腹")) == ["tmdb-title"]


def test_shared_imdb_and_type():
    assert codes(subject(omdb_title="Alpha", omdb_imdb_id="tt1", shared_imdb_film_ids=(7,))) == ["shared-imdb"]
    assert codes(subject(omdb_title="Alpha", omdb_type="series")) == ["stub"]


def test_flag_detail_is_human_readable():
    s = subject(mc_score=95, omdb_metascore=61, omdb_title="Alpha")
    (f,) = run_checks(s)
    assert f.detail == "OMDb Metascore 61 vs Metacritic 95"
