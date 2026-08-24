import csv
from datetime import date

from movie_brain.application.export import write_csv
from movie_brain.domain.models import Film, McTitle, OmdbRating

D = date(2026, 8, 19)


def test_csv_columns_order_and_status(repo, tmp_path):
    films = [
        Film("Low", 2000, "A", "u1"),
        Film("High", 2001, "B", "u2"),
        Film("Miss", 2002, None, "u3"),
        Film("Wait", 2003, None, "u4"),
        Film("Mid", 2004, None, "u5"),
        Film("Tie", 2005, None, "u6"),
    ]
    repo.record_catalog("criterion", films, D)
    ids = {f.key: repo.film_id_by_key(f.key) for f in films}
    # Sort hierarchy coverage: Tie and Low share mc 80 and break on rt (90 vs 50, against
    # title order); Mid has only rt, High only imdb (9.0 — higher than Low's, proving
    # metacritic outranks it), Miss/Wait nothing.
    repo.upsert_omdb(ids["low (2000)"], OmdbRating(6.0, 50, True, "English", metacritic=80), D)
    repo.upsert_omdb(ids["tie (2005)"], OmdbRating(None, 90, True, "English", metacritic=80), D)
    repo.upsert_omdb(ids["mid (2004)"], OmdbRating(None, 70, True, "English"), D)
    repo.upsert_omdb(ids["high (2001)"], OmdbRating(9.0, None, True, "French"), D)
    repo.upsert_omdb(ids["miss (2002)"], OmdbRating(None, None, False), D)
    repo.set_leaving("criterion", {"high (2001)": "August 31"})
    repo.set_rating(ids["low (2000)"], 3, D)
    out = tmp_path / "w.csv"
    assert write_csv(repo, out) == 6
    rows = list(csv.DictReader(out.open()))
    assert list(rows[0].keys()) == [
        "title",
        "year",
        "director",
        "language",
        "metacritic",
        "rt",
        "imdb",
        "status",
        "leaving",
        "url",
        "my-rating",
    ]
    assert [r["title"] for r in rows] == ["Tie", "Low", "Mid", "High", "Miss", "Wait"]
    assert rows[0]["metacritic"] == "80" and rows[0]["rt"] == "90"
    assert rows[1]["my-rating"] == "3" and rows[1]["status"] == "rated" and rows[1]["metacritic"] == "80"
    assert rows[2]["metacritic"] == "" and rows[2]["rt"] == "70"
    assert rows[3]["leaving"] == "August 31" and rows[3]["rt"] == "" and rows[3]["imdb"] == "9.0"
    assert rows[4]["status"] == "unmatched" and rows[5]["status"] == "pending"


def test_csv_includes_discovery_films_with_empty_url(repo, tmp_path):
    # Discovery: no criterion listing, scraped metascore only — ratifies that export
    # covers the full source-agnostic view, not just criterion listings.
    gid = repo.create_film(Film("Golf", 2020, None, ""))
    repo.set_external_id(gid, "metacritic", "golf-2020", D)
    repo.upsert_mc_titles([McTitle("golf-2020", "Golf", 2020, 88, 1, 1)], D)
    out = tmp_path / "w.csv"
    assert write_csv(repo, out) == 1
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["title"] == "Golf" and rows[0]["metacritic"] == "88"
    assert rows[0]["url"] == ""
