from __future__ import annotations

import struct
from datetime import date

import pytest

from movie_brain.domain.models import Film
from movie_brain.domain.search import EMBED_DIM, MAX_DISTANCE
from movie_brain.infrastructure.embeddings import SemanticUnavailable, VectorIndex, pack, unpack

D = date(2026, 8, 19)


def test_pack_is_yt_brain_bytes_and_unpack_inverts_it():
    v = [0.0] * EMBED_DIM
    v[0], v[5] = 0.6, 0.8
    blob = pack(v)
    assert blob == struct.pack(f"{EMBED_DIM}f", *v) and len(blob) == EMBED_DIM * 4
    assert unpack(blob) == pytest.approx(v)


def test_pack_refuses_the_wrong_dimension():
    with pytest.raises(ValueError):
        pack([1.0, 0.0])


def _unit(*dims: int) -> list[float]:
    v = [0.0] * EMBED_DIM
    for d in dims:
        v[d] = 1.0
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def _films(repo, n):
    return [repo.create_film(Film(f"F{i}", 1950 + i, None, "")) for i in range(n)]


def test_nearest_orders_by_distance_inside_the_floor_and_ties_by_id(repo, fake_embedder):
    a, b, c = _films(repo, 3)
    repo.write_embeddings([(a, pack(_unit(0))), (b, pack(_unit(0, 1))), (c, pack(_unit(2)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    q = _unit(0)
    assert idx.nearest(q, MAX_DISTANCE) == [(a, pytest.approx(0.0)), (b, pytest.approx(1 - 2 ** -0.5))]
    assert idx.nearest(q, 2.0)[-1] == (c, pytest.approx(1.0))  # a wide floor admits everything, farthest last
    assert len(idx) == 3


def test_distances_reports_only_the_films_that_hold_a_vector(repo, fake_embedder):
    a, b = _films(repo, 2)
    repo.write_embeddings([(a, pack(_unit(0)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert idx.distances(_unit(0), [a, b, 999]) == {a: pytest.approx(0.0)}


def test_index_rebuilds_when_the_table_changes(repo, fake_embedder):
    a, b = _films(repo, 2)
    repo.write_embeddings([(a, pack(_unit(0)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert [i for i, _ in idx.nearest(_unit(0), 2.0)] == [a]
    repo.write_embeddings([(b, pack(_unit(0)))], date(2026, 8, 20), model="m", dim=EMBED_DIM)
    assert [i for i, _ in idx.nearest(_unit(0), 2.0)] == [a, b]


def test_embed_query_goes_through_the_embedder_once(repo, fake_embedder):
    idx = VectorIndex(repo, fake_embedder, model="m")
    v = idx.embed_query("gumshoe sleuth")
    assert fake_embedder.asked == ["gumshoe sleuth"] and len(v) == EMBED_DIM
    assert sum(x * x for x in v) == pytest.approx(1.0)


def test_an_empty_index_answers_nothing_without_error(repo, fake_embedder):
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert idx.nearest(_unit(0), 2.0) == [] and idx.distances(_unit(0), [1]) == {} and len(idx) == 0


def test_sentence_transformer_adapter_reports_availability_and_raises_when_absent(monkeypatch):
    from movie_brain.infrastructure import embeddings

    monkeypatch.setattr(embeddings.importlib.util, "find_spec", lambda name: None)
    assert embeddings.SentenceTransformerEmbedder.available() is False
    with pytest.raises(SemanticUnavailable):
        embeddings.SentenceTransformerEmbedder().encode(["x"])
