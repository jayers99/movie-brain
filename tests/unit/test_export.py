import csv
from datetime import date

from movie_brain.application.export import write_csv
from movie_brain.domain.models import Film, OmdbRating

D = date(2026, 8, 19)


def test_csv_columns_order_and_status(repo, tmp_path):
    films = [
        Film("Low", 2000, "A", "u1"),
        Film("High", 2001, "B", "u2"),
        Film("Miss", 2002, None, "u3"),
        Film("Wait", 2003, None, "u4"),
    ]
    repo.record_catalog("criterion", films, D)
    ids = {f.key: repo.film_id_by_key(f.key) for f in films}
    repo.upsert_omdb(ids["low (2000)"], OmdbRating(6.0, 50, True, "English"), D)
    repo.upsert_omdb(ids["high (2001)"], OmdbRating(9.0, None, True, "French"), D)
    repo.upsert_omdb(ids["miss (2002)"], OmdbRating(None, None, False), D)
    repo.set_leaving("criterion", {"high (2001)": "August 31"})
    repo.set_rating(ids["low (2000)"], 3, D)
    out = tmp_path / "w.csv"
    assert write_csv(repo, out) == 4
    rows = list(csv.DictReader(out.open()))
    assert list(rows[0].keys()) == [
        "title",
        "year",
        "director",
        "language",
        "imdb",
        "rt",
        "status",
        "leaving",
        "url",
        "my-rating",
    ]
    assert [r["title"] for r in rows] == ["High", "Low", "Miss", "Wait"]
    assert rows[0]["leaving"] == "August 31" and rows[0]["rt"] == ""
    assert rows[1]["my-rating"] == "3" and rows[1]["status"] == "rated"
    assert rows[2]["status"] == "unmatched" and rows[3]["status"] == "pending"
