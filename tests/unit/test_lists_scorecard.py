"""`scorecard`'s `#N` prefix (tied-ranks design §4): it must print the poll's own rank
label when the entry carries one, never the counted line position underneath it."""

from __future__ import annotations

from movie_brain.application.lists import EntryOutcome, scorecard


def _outcome(rank: int, title: str, *, rank_label: str | None = None) -> EntryOutcome:
    return EntryOutcome(
        rank=rank,
        title_listed=title,
        director_listed=None,
        kind="linked",
        film_id=1,
        tt="tt0000001",
        reason="director corroborated",
        form_used=title,
        detail="detail",
        rank_label=rank_label,
    )


def test_scorecard_prints_the_rank_label_when_present():
    card = scorecard([_outcome(68, "Tied Film", rank_label="=68")])
    assert card.splitlines()[0].startswith("#=68 ")


def test_scorecard_prints_the_plain_rank_when_no_label():
    card = scorecard([_outcome(3, "Untied Film")])
    assert card.splitlines()[0].startswith("#3 ")


def test_an_empty_label_renders_empty_which_is_what_pins_is_not_none_over_or():
    """An empty label renders as a bare `#`, NOT the position — matching `app.js`'s `??`,
    which is the point of the alignment. The parser never emits `""` — `rank_label` is either None or a real label. This case
    exists to keep the distinction visible: under a truthiness check (`rank_label or rank`)
    an empty label would silently become the position, and only this test would notice if a
    future producer of `rank_label` were less careful than the parser."""
    card = scorecard([_outcome(7, "Odd Film", rank_label="")])
    assert card.splitlines()[0].startswith("# ")
