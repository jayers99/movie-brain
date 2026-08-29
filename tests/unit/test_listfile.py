from __future__ import annotations

from pathlib import Path

import pytest

from movie_brain.domain.models import ListEntry, ListMeta
from movie_brain.infrastructure.listfile import ListFileError, ParsedList, parse_list_file, read_list_file

FULL_HEADER = """\
# slug: cahiers-100
# name: 100 Films for an Ideal Cinematheque
# curator: Cahiers du Cinéma
# published: 2008
# source: https://www.filmdetail.com/2008/11/23/cahiers-du-cinemas-100-greatest-films/
# ordered: true
1\tCitizen Kane\tOrson Welles
2\tThe Night of the Hunter\tCharles Laughton
"""


def test_full_header_block_parses_into_list_meta():
    parsed = parse_list_file(FULL_HEADER)
    assert parsed.meta == ListMeta(
        slug="cahiers-100",
        name="100 Films for an Ideal Cinematheque",
        curator="Cahiers du Cinéma",
        published_year=2008,
        source_url="https://www.filmdetail.com/2008/11/23/cahiers-du-cinemas-100-greatest-films/",
        ordered=True,
    )
    assert parsed.entries == (
        ListEntry(1, "Citizen Kane", "Orson Welles"),
        ListEntry(2, "The Night of the Hunter", "Charles Laughton"),
    )


def test_ordered_false_yields_ordered_false():
    text = "# slug: s\n# name: n\n# ordered: false\n1\tA\tB\n"
    assert parse_list_file(text).meta.ordered is False


def test_ordered_defaults_to_true_when_absent():
    text = "# slug: s\n# name: n\n1\tA\tB\n"
    assert parse_list_file(text).meta.ordered is True


def test_two_column_row_gives_none_director():
    text = "# slug: s\n# name: n\n1\tA Title\n"
    assert parse_list_file(text).entries[0].director_listed is None


def test_empty_third_column_gives_none_director():
    text = "# slug: s\n# name: n\n1\tA Title\t\n"
    assert parse_list_file(text).entries[0].director_listed is None


def test_blank_lines_and_hash_lines_after_header_are_skipped():
    text = "# slug: s\n# name: n\n1\tFirst\tDir One\n\n# a comment mid-file\n2\tSecond\tDir Two\n"
    parsed = parse_list_file(text)
    assert [e.rank for e in parsed.entries] == [1, 2]


def test_curly_apostrophe_and_ellipsis_survive_byte_for_byte():
    text = "# slug: s\n# name: n\n1\tSingin' in the Rain\tGene Kelly\n2\tMadame de…\tMax Ophüls\n"
    parsed = parse_list_file(text)
    assert parsed.entries[0].title_listed == "Singin' in the Rain"
    assert parsed.entries[1].title_listed == "Madame de…"


def test_missing_slug_raises():
    text = "# name: n\n1\tA\tB\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_missing_name_raises():
    text = "# slug: s\n1\tA\tB\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_non_integer_rank_raises():
    text = "# slug: s\n# name: n\nX\tA\tB\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_repeated_printed_rank_is_a_tie_not_an_error():
    # A duplicate printed rank used to be rejected outright; now position (line order)
    # makes each entry addressable and a repeated label is exactly what a tie looks like.
    text = "# slug: s\n# name: n\n=243\tA\tB\n=243\tC\tD\n"
    parsed = parse_list_file(text)
    assert [e.rank for e in parsed.entries] == [1, 2]
    assert [e.rank_label for e in parsed.entries] == ["=243", "=243"]


def test_empty_title_raises():
    text = "# slug: s\n# name: n\n1\t\tB\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_four_column_row_parses_tt_listed():
    text = "# slug: s\n# name: n\n1\tThe Birth of a Nation\tD.W. Griffith\ttt0004972\n"
    assert parse_list_file(text).entries[0].tt_listed == "tt0004972"


def test_three_column_row_yields_none_tt_listed():
    text = "# slug: s\n# name: n\n1\tA Title\tA Director\n"
    assert parse_list_file(text).entries[0].tt_listed is None


def test_empty_fourth_column_yields_none_tt_listed():
    text = "# slug: s\n# name: n\n1\tA Title\tA Director\t\n"
    assert parse_list_file(text).entries[0].tt_listed is None


def test_mixed_arity_within_one_file():
    text = (
        "# slug: s\n# name: n\n"
        "1\tFirst\tDir One\ttt0004972\n"
        "2\tSecond\tDir Two\n"
        "3\tThird\tDir Three\t\n"
    )
    parsed = parse_list_file(text)
    assert [e.tt_listed for e in parsed.entries] == ["tt0004972", None, None]


@pytest.mark.parametrize(
    "bad_id",
    ["0004972", "ttabc", "tt0004972 "],
    ids=["missing-tt-prefix", "non-numeric", "trailing-space"],
)
def test_malformed_tt_listed_raises(bad_id: str):
    text = f"# slug: s\n# name: n\n1\tA Title\tA Director\t{bad_id}\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_whitespace_only_fourth_column_reads_as_no_id():
    # A cell of spaces is an empty cell, exactly as the header values treat one — not a
    # malformed id. Whitespace AROUND a value stays malformed (see the parametrized case
    # above): the id is stored verbatim, so a padded one is a typo worth stopping on.
    text = "# slug: s\n# name: n\n1\tA Title\tA Director\t   \n"
    assert parse_list_file(text).entries[0].tt_listed is None


def test_a_fifth_column_raises_rather_than_being_ignored():
    # The file is hand-checked-in and this parser's whole rationale is that a typo here is
    # silent forever. A future fifth column should be a deliberate parser change, not a
    # stray cell nobody notices.
    text = "# slug: s\n# name: n\n1\tA Title\tA Director\ttt0004972\t1941\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_short_but_well_formed_tt_listed_is_accepted():
    # The contract regex (`^tt\d+$`, spec §3) has no minimum digit count — a short id
    # is a task-2 reconciliation concern, not a task-1 format-validity one.
    text = "# slug: s\n# name: n\n1\tA Title\tA Director\ttt123\n"
    assert parse_list_file(text).entries[0].tt_listed == "tt123"


def test_read_list_file_reads_from_disk(tmp_path: Path):
    p = tmp_path / "cahiers-100.tsv"
    p.write_text(FULL_HEADER)
    parsed = read_list_file(p)
    assert isinstance(parsed, ParsedList)
    assert parsed.meta.slug == "cahiers-100"
    assert len(parsed.entries) == 2


# --- tied ranks (design 2026-08-28-tied-ranks-design.md §3) ---


def test_sequential_printed_ranks_yield_no_labels():
    # The existing-file guarantee: when the printed cell equals the line position, there's
    # nothing to record beyond `rank` itself.
    text = "# slug: s\n# name: n\n1\tA\tB\n2\tC\tD\n3\tE\tF\n"
    parsed = parse_list_file(text)
    assert [e.rank for e in parsed.entries] == [1, 2, 3]
    assert [e.rank_label for e in parsed.entries] == [None, None, None]


def test_repeated_tie_label_yields_contiguous_ranks_with_shared_label():
    text = "# slug: s\n# name: n\n=243\tA\tB\n=243\tC\tD\n=243\tE\tF\n"
    parsed = parse_list_file(text)
    assert [e.rank for e in parsed.entries] == [1, 2, 3]
    assert [e.rank_label for e in parsed.entries] == ["=243", "=243", "=243"]


def test_mixed_file_labels_only_where_printed_differs_from_position():
    text = "# slug: s\n# name: n\n1\tA\tB\n2\tC\tD\n=3\tE\tF\n=3\tG\tH\n5\tI\tJ\n"
    parsed = parse_list_file(text)
    assert [e.rank for e in parsed.entries] == [1, 2, 3, 4, 5]
    assert [e.rank_label for e in parsed.entries] == [None, None, "=3", "=3", None]


def test_decreasing_tie_labels_raise_the_reversed_bfi_page_case():
    # The BFI page defaults to listing 250 -> 1; an extraction that forgets to reverse it
    # comes out backwards. This is exactly that shape and must be rejected, not imported
    # upside down.
    text = "# slug: s\n# name: n\n=243\tA\tB\n=225\tC\tD\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_decreasing_plain_ranks_raise_the_reversed_bfi_page_case():
    text = "# slug: s\n# name: n\n250\tA\tB\n249\tC\tD\n248\tE\tF\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


@pytest.mark.parametrize(
    "bad_rank",
    ["abc", "=", "-1", "3.5", "= 243"],
    ids=["letters", "bare-equals", "negative", "decimal", "space-after-equals"],
)
def test_malformed_rank_raises(bad_rank: str):
    text = f"# slug: s\n# name: n\n{bad_rank}\tA Title\tA Director\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_ranks_are_contiguous_by_construction_so_a_gap_cannot_occur():
    # There is no longer any way to write a "gap" in the printed column — rank is derived
    # from line order, not parsed from the file, so three data rows always yield 1, 2, 3
    # regardless of what's printed (as long as the labels are individually well-formed and
    # non-decreasing).
    text = "# slug: s\n# name: n\n=1\tA\tB\n=50\tC\tD\n=50\tE\tF\n"
    parsed = parse_list_file(text)
    assert [e.rank for e in parsed.entries] == [1, 2, 3]


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("slug", ["cahiers-100", "bergan-100"])
def test_checked_in_real_lists_still_parse_byte_identically(slug: str):
    # cahiers-100.tsv and bergan-100.tsv are checked in and already imported into the
    # owner's live database. They print 1..100, which equals their line order, so under
    # the new label-aware rules they must still parse to 100 rows with rank_label None on
    # every row — the one thing this task must not break.
    parsed = read_list_file(REPO_ROOT / "lists" / f"{slug}.tsv")
    assert len(parsed.entries) == 100
    assert [e.rank for e in parsed.entries] == list(range(1, 101))
    assert all(e.rank_label is None for e in parsed.entries)


HEADER_ONLY = "# slug: s\n# name: n\n"


def test_a_label_that_equals_the_position_but_carries_an_equals_sign_is_still_a_label():
    """`=3` at position 3 differs from `"3"`, so it is stored — the file said `=3`, not `3`."""
    parsed = parse_list_file(HEADER_ONLY + "1\tA\tdir\n2\tB\tdir\n=3\tC\tdir\n")
    assert [e.rank_label for e in parsed.entries] == [None, None, "=3"]


def test_a_file_whose_first_label_is_not_one_still_starts_at_position_one():
    """The other shape a bad extraction takes: a slice starting mid-poll. The non-decreasing
    check cannot see it, so this pins the behaviour rather than claiming to catch it."""
    parsed = parse_list_file(HEADER_ONLY + "=5\tA\tdir\n=5\tB\tdir\n=7\tC\tdir\n")
    assert [(e.rank, e.rank_label) for e in parsed.entries] == [(1, "=5"), (2, "=5"), (3, "=7")]
