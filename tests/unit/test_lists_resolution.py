"""The curated-list resolution helpers: the form ladder and the four gates.

Duplicate films are the failure this import must not produce (design §0), so every
assertion here is about refusing rather than guessing: which forms were asked, in what
order, which gate answered, and whether a tombstoned holder is told apart from a miss.
"""

from __future__ import annotations

import sqlite3

import pytest
from lists_fakes import RecordingFetcher, StubTmdb
from lists_fakes import candidate as _cand

from movie_brain.application.lists import (
    AUTHORITY,
    ID_DISAGREEMENT,
    corpus_veto,
    entry_forms,
    find_holder,
    reconcile,
    resolve_entry,
)
from movie_brain.domain.matching import Candidate as CorpusCandidate
from movie_brain.domain.matching import CandidateIndex
from movie_brain.domain.models import Film, ListEntry
from movie_brain.domain.thumbprint import Scored, Verdict

DIAMOND = "Diamond Earrings (Madame de…)"
OPHULS = "Max Ophüls"


def _match(tt, *cands):
    """A `match` verdict whose `ranked` carries `cands` — the shape find_holder reads."""
    ranked = tuple(Scored(c, 9, 3, 0, 3, c.in_tmdb and c.in_omdb, False) for c in cands)
    return Verdict("match", tt, "director corroborated", ranked)


# --- entry_forms ---------------------------------------------------------------------------


def test_authority_is_list():
    assert AUTHORITY == "list"


def test_entry_forms_of_a_plain_title_is_one_form():
    # title == base and there is no alt: forms() de-duplicates them down to one.
    assert entry_forms("Greed") == ["Greed"]


def test_entry_forms_is_primary_then_base_then_alt():
    assert entry_forms(DIAMOND) == [DIAMOND, "Diamond Earrings", "Madame de…"]


# --- resolve_entry: the fallback-only ladder -------------------------------------------------


def test_single_form_title_issues_exactly_one_query():
    fetcher = RecordingFetcher({"Greed": [_cand("tt0016654", 613, "Greed", director="Erich von Stroheim")]})

    verdict, form = resolve_entry(fetcher, ListEntry(1, "Greed", "Erich von Stroheim"))

    assert fetcher.queried == ["Greed"]
    assert (verdict.kind, verdict.tt, form) == ("match", "tt0016654", "Greed")


def test_the_query_carries_the_listed_director_and_never_a_year():
    fetcher = RecordingFetcher()

    resolve_entry(fetcher, ListEntry(1, "Greed", "Erich von Stroheim"))

    (q,) = fetcher.queries
    assert (q.year, q.source, q.director) == (None, "list", "Erich von Stroheim")


def test_an_embedded_year_never_reaches_the_query():
    # "the year is always None" is a governing constraint: a year in the listed title would
    # otherwise flip the query to YearClass.DATABASE and let a wrong year decide the verdict.
    fetcher = RecordingFetcher()

    resolve_entry(fetcher, ListEntry(1, "Napoléon (1927)", "Abel Gance"))

    (q,) = fetcher.queries
    assert (q.title, q.year, q.year_class.value) == ("Napoléon", None, "apple-field")


def test_a_parenthetical_whose_primary_misses_falls_back_to_base_then_alt():
    fetcher = RecordingFetcher({"Madame de…": [_cand("tt0046022", 18183, "Madame de…", director=OPHULS)]})

    verdict, form = resolve_entry(fetcher, ListEntry(33, DIAMOND, OPHULS))

    assert fetcher.queried == [DIAMOND, "Diamond Earrings", "Madame de…"]
    assert (verdict.kind, verdict.tt, form) == ("match", "tt0046022", "Madame de…")


def test_the_ladder_stops_at_the_first_match():
    fetcher = RecordingFetcher(
        {"Diamond Earrings": [_cand("tt0046022", 18183, "Diamond Earrings", director=OPHULS)]}
    )

    verdict, form = resolve_entry(fetcher, ListEntry(33, DIAMOND, OPHULS))

    assert fetcher.queried == [DIAMOND, "Diamond Earrings"]  # the alt form is never asked
    assert (verdict.tt, form) == ("tt0046022", "Diamond Earrings")


def test_a_primary_match_is_never_overridden_by_a_later_form():
    fetcher = RecordingFetcher(
        {
            DIAMOND: [_cand("tt0046022", 18183, DIAMOND, director=OPHULS)],
            "Diamond Earrings": [_cand("tt9999999", 1, "Diamond Earrings", director=OPHULS)],
        }
    )

    verdict, form = resolve_entry(fetcher, ListEntry(33, DIAMOND, OPHULS))

    assert fetcher.queried == [DIAMOND]
    assert (verdict.tt, form) == ("tt0046022", DIAMOND)


def test_when_no_form_matches_the_primary_forms_verdict_is_returned():
    # The primary form conflicts on director; the later forms find nothing at all. The
    # returned reason must be the primary's, not the last form's "no candidates".
    fetcher = RecordingFetcher({DIAMOND: [_cand("tt0000001", 1, DIAMOND, director="Jean Renoir")]})

    verdict, form = resolve_entry(fetcher, ListEntry(33, DIAMOND, OPHULS))

    assert fetcher.queried == [DIAMOND, "Diamond Earrings", "Madame de…"]
    assert (verdict.kind, verdict.reason, form) == ("review", "director conflicts only", DIAMOND)


def test_a_failing_form_is_logged_and_the_ladder_continues():
    fetcher = RecordingFetcher(
        {"Madame de…": [_cand("tt0046022", 18183, "Madame de…", director=OPHULS)]},
        offline=[DIAMOND, "Diamond Earrings"],
    )
    logs = []

    verdict, form = resolve_entry(fetcher, ListEntry(33, DIAMOND, OPHULS), log=logs.append)

    assert fetcher.queried == [DIAMOND, "Diamond Earrings", "Madame de…"]
    assert (verdict.tt, form) == ("tt0046022", "Madame de…")
    assert len(logs) == 2


def test_when_every_form_raises_the_result_is_none_and_the_primary_form():
    fetcher = RecordingFetcher(offline=[DIAMOND, "Diamond Earrings", "Madame de…"])
    logs = []

    verdict, form = resolve_entry(fetcher, ListEntry(33, DIAMOND, OPHULS), log=logs.append)

    assert (verdict, form) == (None, DIAMOND)
    assert len(logs) == 3


# --- find_holder: gates 1, 2, 2b -------------------------------------------------------------


def _film(repo, title, year=None):
    return repo.create_film(Film(title, year, None, ""))


def test_gate_1_finds_the_film_holding_the_imdb_id(repo, today):
    fid = _film(repo, "Intolerance", 1916)
    repo.set_external_id(fid, "imdb", "tt0006864", today)

    verdict = _match("tt0006864", _cand("tt0006864", 3059, "Intolerance"))

    assert find_holder(repo, None, verdict) == (fid, "imdb tt0006864")


def test_gate_2_finds_the_tmdb_holder_of_the_winning_candidate(repo, today):
    fid = _film(repo, "Intolerance", 1916)
    repo.set_external_id(fid, "tmdb", "3059", today)

    # The winner is the ranked entry whose tt is the verdict's; a rival must not be read.
    verdict = _match(
        "tt0006864",
        _cand("tt9999999", 111, "Intolerance"),
        _cand("tt0006864", 3059, "Intolerance"),
    )

    assert find_holder(repo, None, verdict) == (fid, "tmdb 3059")


def test_gate_2b_finds_the_holder_when_the_winner_is_omdb_only(repo, today):
    # Live case #69 Intolerance: nobody holds tt0006864, the winner carries no tmdb_id, but
    # film #3096 holds tmdb=3059 and find_by_imdb maps the tt straight onto it.
    fid = _film(repo, "'Intolerance'", 1916)
    repo.set_external_id(fid, "tmdb", "3059", today)
    tmdb = StubTmdb({"tt0006864": 3059})

    verdict = _match("tt0006864", _cand("tt0006864", None, "Intolerance", in_tmdb=False))

    assert find_holder(repo, tmdb, verdict) == (fid, "tmdb(find 3059)")
    assert tmdb.calls == ["tt0006864"]


def test_gate_2b_is_not_asked_when_the_winner_already_carries_a_tmdb_id(repo):
    tmdb = StubTmdb({"tt0006864": 3059})

    verdict = _match("tt0006864", _cand("tt0006864", 111, "Intolerance"))

    assert find_holder(repo, tmdb, verdict) == (None, "no holder")
    assert tmdb.calls == []


def test_gate_2b_still_runs_when_the_winner_is_absent_from_ranked(repo, today):
    # `resolve` truncates `ranked` to the top three, so the winning tt can be missing from it
    # entirely. Gate 2 cannot run then — but gate 2b needs only verdict.tt, and refusing to
    # ask would fail in the creating direction.
    fid = _film(repo, "Intolerance", 1916)
    repo.set_external_id(fid, "tmdb", "3059", today)
    tmdb = StubTmdb({"tt0006864": 3059})

    verdict = _match("tt0006864", _cand("tt1111111", 111, "Intolerance"), _cand("tt2222222", 222, "Intolerance"))
    assert all(s.candidate.tt != verdict.tt for s in verdict.ranked)

    assert find_holder(repo, tmdb, verdict) == (fid, "tmdb(find 3059)")
    assert tmdb.calls == ["tt0006864"]


def test_gate_2b_is_skipped_without_a_tmdb_client(repo, today):
    fid = _film(repo, "Intolerance", 1916)
    repo.set_external_id(fid, "tmdb", "3059", today)

    verdict = _match("tt0006864", _cand("tt0006864", None, "Intolerance", in_tmdb=False))

    assert find_holder(repo, None, verdict) == (None, "no holder")


def test_a_failing_gate_2b_lookup_is_logged_and_labelled_as_a_failure_not_a_miss(repo):
    # "the holder is unknown" must not read like "nobody holds this work" — the scorecard
    # has to be able to say so, because the caller's next move is creation.
    tmdb = StubTmdb(raises=True)
    logs = []

    verdict = _match("tt0006864", _cand("tt0006864", None, "Intolerance", in_tmdb=False))

    assert find_holder(repo, tmdb, verdict, log=logs.append) == (None, "tmdb lookup failed")
    assert len(logs) == 1


def test_no_gate_answers_when_nobody_holds_either_id(repo):
    _film(repo, "Intolerance", 1916)

    verdict = _match("tt0006864", _cand("tt0006864", 3059, "Intolerance"))

    assert find_holder(repo, None, verdict) == (None, "no holder")


def test_a_tombstoned_holder_is_reported_as_tombstoned_not_as_a_miss(repo, today):
    fid = _film(repo, "Intolerance", 1916)
    repo.set_external_id(fid, "imdb", "tt0006864", today)
    repo.tombstone_film(fid, today)

    verdict = _match("tt0006864", _cand("tt0006864", 3059, "Intolerance"))

    assert find_holder(repo, None, verdict) == (None, f"tombstoned #{fid}")


def test_a_holder_that_was_merged_away_resolves_to_its_survivor(repo, today):
    # merge_film moves external ids to the survivor, so this stale pointer is planted
    # directly: canonical_film_id is the guard that must never hand back a dead identity.
    loser = _film(repo, "Intolerance", 1916)
    survivor = _film(repo, "Intolerance: A Drama of Comparisons", 1916)
    repo.set_external_id(loser, "imdb", "tt0006864", today)
    with sqlite3.connect(repo.db_path) as c:
        c.execute(
            "INSERT INTO film_disposition (film_id, kind, survivor_id, created_at) VALUES (?, 'merged', ?, ?)",
            (loser, survivor, today.isoformat()),
        )

    verdict = _match("tt0006864", _cand("tt0006864", 3059, "Intolerance"))

    assert find_holder(repo, None, verdict) == (survivor, "imdb tt0006864")


def test_find_holder_answers_nothing_for_a_verdict_that_is_not_a_match(repo, today):
    fid = _film(repo, "Intolerance", 1916)
    repo.set_external_id(fid, "imdb", "tt0006864", today)

    assert find_holder(repo, None, Verdict("review", None, "weak", ())) == (None, "")


# --- corpus_veto: gate 3 ---------------------------------------------------------------------


def test_corpus_veto_fires_on_a_hit_for_the_alt_form_alone():
    index = CandidateIndex([CorpusCandidate(3096, "Madame de…", 1953)])

    assert [c.id for c in corpus_veto(index, entry_forms(DIAMOND))] == [3096]


def test_corpus_veto_de_duplicates_a_film_hit_by_two_forms():
    # 'Diamond Earrings: Madame de…' is hit by the primary form exactly and by the base
    # form through the index's colon-prefix bucket.
    index = CandidateIndex([CorpusCandidate(7, "Diamond Earrings: Madame de…", 1953)])

    assert [c.id for c in corpus_veto(index, entry_forms(DIAMOND))] == [7]


def test_corpus_veto_keeps_form_order_across_several_hits():
    index = CandidateIndex(
        [CorpusCandidate(1, "Diamond Earrings", 1953), CorpusCandidate(2, "Madame de…", 1953)]
    )

    assert [c.id for c in corpus_veto(index, entry_forms(DIAMOND))] == [1, 2]


def test_corpus_veto_is_empty_when_the_catalog_has_nothing_alike():
    index = CandidateIndex([CorpusCandidate(1, "Greed", 1924)])

    assert corpus_veto(index, entry_forms(DIAMOND)) == []


# --- reconcile: the comparison policy (supplied-id spec §5) ----------------------------------

MATCHED = _match("tt0016654", _cand("tt0016654", 613, "Greed"))
NO_MATCH = Verdict("review", None, "no candidates", ())


@pytest.mark.parametrize(
    ("verdict", "tt_listed", "expected"),
    [
        (MATCHED, "tt0016654", ("tt0016654", "agree")),
        (MATCHED, "tt9999999", (None, "disagree")),
        (NO_MATCH, "tt9999999", ("tt9999999", "supplied")),
        (MATCHED, None, ("tt0016654", "")),
        (NO_MATCH, None, (None, "")),
        (None, "tt9999999", ("tt9999999", "supplied")),
    ],
    ids=[
        "match-same-id",
        "match-different-id",
        "no-match-with-id",
        "match-no-id",
        "no-match-no-id",
        "no-verdict-with-id",
    ],
)
def test_reconcile_is_the_policy_table(verdict, tt_listed, expected):
    # Spec §5, one row per case. Pure: no repo, no fetcher, no clock.
    assert reconcile(verdict, tt_listed) == expected


def test_a_disagreement_offers_no_tt_at_all_to_proceed_on():
    # Never link, never create: the tt is withheld, so a caller that forgot to branch on the
    # agreement cannot accidentally proceed on either source's id.
    tt, agreement = reconcile(MATCHED, "tt9999999")
    assert tt is None and agreement == "disagree"


def test_a_match_with_no_supplied_id_is_untouched_by_the_policy():
    # ~40 existing scenarios depend on this row being today's behaviour, exactly.
    assert reconcile(MATCHED, None) == (MATCHED.tt, "")


def test_the_disagreement_reason_is_the_sixth_list_reason():
    assert ID_DISAGREEMENT == "id-disagreement"
