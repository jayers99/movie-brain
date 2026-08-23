import json

from movie_brain.domain.models import McTitle
from movie_brain.infrastructure.metacritic import (
    archive_dir,
    archived_pages,
    page_path,
    parse_archive,
    parse_page,
)


def test_parse_page_extracts_cards_in_order(nuxt_page):
    html = nuxt_page([("Seven Samurai", "seven-samurai-1954", 1956, 98), ("Tokyo Story", "tokyo-story", 1972, 97)])
    assert parse_page(html, page=1) == [
        McTitle("seven-samurai-1954", "Seven Samurai", 1956, 98, rank=1, page=1),
        McTitle("tokyo-story", "Tokyo Story", 1972, 97, rank=2, page=1),
    ]


def test_parse_page_rank_offsets_by_page(nuxt_page):
    html = nuxt_page([("Late Spring", "late-spring", 1949, 96)])
    (t,) = parse_page(html, page=3)
    assert t.rank == 2 * 24 + 1  # (page-1) * CARDS_PER_PAGE + position


def test_parse_page_tolerates_missing_year_and_score(nuxt_page):
    html = nuxt_page([("Mystery", "mystery", None, None)])
    (t,) = parse_page(html, page=1)
    assert t.year is None and t.score is None and t.slug == "mystery"


def test_parse_page_without_nuxt_island_yields_nothing():
    assert parse_page("<html><body>bot wall</body></html>", page=1) == []


def test_archive_roundtrip(tmp_path, nuxt_page):
    archive = archive_dir(tmp_path)
    for page, cards in [(1, [("A", "a", 2000, 90)]), (2, [("B", "b", 2001, 89)])]:
        p = page_path(archive, page)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(nuxt_page(cards))
    assert archived_pages(archive) == [1, 2]
    titles = parse_archive(archive)
    assert [t.slug for t in titles] == ["a", "b"]
    assert [t.page for t in titles] == [1, 2]


def test_archived_pages_empty_when_no_archive(tmp_path):
    assert archived_pages(archive_dir(tmp_path)) == []


def test_parse_page_matches_nuxt_script_regardless_of_attribute_order(nuxt_page):
    html = nuxt_page([("Movie", "movie", 2001, 77)])
    swapped = html.replace(
        'type="application/json" id="__NUXT_DATA__"',
        'id="__NUXT_DATA__" type="application/json"',
    )
    titles = parse_page(swapped, page=1)
    assert [t.slug for t in titles] == ["movie"]


def test_parse_page_skips_corrupt_card_and_keeps_valid_ones(nuxt_page):
    good_html = nuxt_page([("Good Movie", "good-movie", 2001, 88)])
    start = good_html.index(">", good_html.index("__NUXT_DATA__")) + 1
    end = good_html.index("</script>", start)
    data = json.loads(good_html[start:end])
    # A card whose index values are wildly out of range for the flat array.
    data.append({"title": 9999, "slug": 9999, "premiereYear": 9999, "criticScoreSummary": 9999})
    html = good_html[:start] + json.dumps(data) + good_html[end:]
    titles = parse_page(html, page=1)
    assert [t.slug for t in titles] == ["good-movie"]
