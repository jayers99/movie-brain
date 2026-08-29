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


def test_duplicate_rank_raises():
    text = "# slug: s\n# name: n\n1\tA\tB\n1\tC\tD\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_empty_title_raises():
    text = "# slug: s\n# name: n\n1\t\tB\n"
    with pytest.raises(ListFileError):
        parse_list_file(text)


def test_read_list_file_reads_from_disk(tmp_path: Path):
    p = tmp_path / "cahiers-100.tsv"
    p.write_text(FULL_HEADER)
    parsed = read_list_file(p)
    assert isinstance(parsed, ParsedList)
    assert parsed.meta.slug == "cahiers-100"
    assert len(parsed.entries) == 2
