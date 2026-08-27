import json

from movie_brain.application.repair import (
    DisagreementContract,
    audit_disagreements,
    format_disagreement,
    load_disagreement_contract,
)
from movie_brain.domain.models import Film
from movie_brain.infrastructure.database import OmdbRating, TmdbFactsRow

HEADER = "group,film_id,source,title_ingested,year_ingested,expected_tt,expected_tmdb,verified_by,note,status,director,runtime_min\n"


def _csv(tmp_path, *rows):
    p = tmp_path / "eval.csv"
    p.write_text(HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return p


def _found_rating(tt: str) -> OmdbRating:
    return OmdbRating(7.0, 80, True, "English", json.dumps({"imdbID": tt, "Title": "x"}))


def _facts(tmdb_id: int, tt: str) -> TmdbFactsRow:
    return TmdbFactsRow(tmdb_id, tt, "T", "T", (), 2000, None)


def test_load_contract_keeps_every_d_row(tmp_path):
    p = _csv(
        tmp_path,
        "D-disagree,7,criterion,Bound,1995,tt0112565,,x,note,verified,Kimi Takesue,",
        "D-disagree,8,criterion,Resurrection,,,,?,note,proposed,,",
        "C-edition,9,apple,Blade Runner (Final Cut),2007,tt1,2,x,work='Blade Runner' 1982,verified,,",
    )
    c = load_disagreement_contract(p)
    assert set(c) == {7, 8}
    assert c[7] == DisagreementContract(7, "verified", "tt0112565", None, "Bound", 1995, "criterion", "Kimi Takesue")
    assert c[8].status == "proposed" and c[8].year_ingested is None and c[8].director is None


def _split(repo, today, title, omdb_tt, tmdb_tt, tmdb_id):
    fid = repo.create_film(Film(title, 2000, None, ""))
    repo.upsert_omdb(fid, _found_rating(omdb_tt), today)      # same helpers as test_database Task 3
    repo.set_external_id(fid, "tmdb", str(tmdb_id), today)
    repo.upsert_tmdb_facts(fid, _facts(tmdb_id, tmdb_tt), today)
    return fid


def _contract(fid, tt, tmdb=None, status="verified"):
    return DisagreementContract(fid, status, tt, tmdb, "T", 2000, "criterion", None)


def test_verdicts_follow_the_contract_row(repo, today):
    refetch = _split(repo, today, "Refetch", "ttA", "ttB", 1)
    relink = _split(repo, today, "Relink", "ttC", "ttD", 2)
    adopt = _split(repo, today, "Adopt", "ttE", "ttF", 3)
    adopt_no_tmdb = _split(repo, today, "Adopt2", "ttG", "ttH", 4)
    proposed = _split(repo, today, "Proposed", "ttI", "ttJ", 5)
    none = _split(repo, today, "None", "ttK", "ttL", 6)
    orphan = _split(repo, today, "Orphan", "ttM", "ttN", 7)
    held = _split(repo, today, "Held", "ttO", "ttP", 8)
    other = repo.create_film(Film("Other", 1999, None, ""))
    repo.set_external_id(other, "imdb", "ttQ", today)
    contract = {
        refetch: _contract(refetch, "ttB"),
        relink: _contract(relink, "ttC"),
        adopt: _contract(adopt, "ttZ", "99"),
        adopt_no_tmdb: _contract(adopt_no_tmdb, "ttY"),
        proposed: _contract(proposed, "ttJ", status="proposed"),
        none: _contract(none, "NONE"),
        held: _contract(held, "ttQ"),
    }
    got = {g.film_id: g.verdict for g in audit_disagreements(repo, contract)}
    assert got == {
        refetch: "refetch", relink: "relink", adopt: "adopt", adopt_no_tmdb: "conflict",
        proposed: "review", none: "review", orphan: "conflict", held: "conflict",
    }
    line = format_disagreement(next(g for g in audit_disagreements(repo, contract) if g.film_id == held))
    assert line.startswith("[conflict]") and f"held by #{other}" in line
