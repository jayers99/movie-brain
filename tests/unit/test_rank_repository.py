from __future__ import annotations

from datetime import date

from movie_brain.domain.models import Film

D = date(2026, 9, 13)


def _film(repo, title, year):
    fid = repo.create_film(Film(title, year, "Dir", ""))
    assert fid is not None
    return fid


def test_set_unseen_marks_unmarks_and_reports_missing(repo):
    a = _film(repo, "Alpha", 1950)
    assert repo.set_unseen(a, True, D, note="never saw it") is True
    assert repo.unseen_film_ids() == {a}
    assert repo.get_view(a, D).unseen is True
    assert repo.set_unseen(a, True, D) is True  # idempotent
    assert repo.set_unseen(a, False, D) is False
    assert repo.unseen_film_ids() == set()
    assert repo.set_unseen(999, True, D) is None


def test_merge_moves_unseen_survivor_wins(repo):
    a = _film(repo, "Alpha", 1950)
    b = _film(repo, "Alpha", 1951)
    repo.set_unseen(b, True, D)
    repo.merge_film(b, a, D)
    assert repo.unseen_film_ids() == {a}
    c = _film(repo, "Beta", 1960)
    d = _film(repo, "Beta", 1961)
    repo.set_unseen(c, True, D, note="keep")
    repo.set_unseen(d, True, D, note="drop")
    report = repo.merge_film(d, c, D)
    assert report.dropped.get("unseen") == 1
    assert repo.unseen_film_ids() == {a, c}
