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
    assert blob == struct.pack(f"<{EMBED_DIM}f", *v) and len(blob) == EMBED_DIM * 4
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


def test_sentence_transformer_adapter_loads_the_model_once_under_concurrent_first_queries(monkeypatch):
    """The dashboard crashed twice on 2026-09-22: five typeahead requests reached the lazy loader
    while the model was still loading (five 'Loading weights' bars, then the process died with no
    traceback). Reproduced with the load alone serialised: ONE load, then SIGSEGV inside BERT's
    first forward with five threads encoding at once — and five concurrent encodes on a warm model
    were fine. Flask's dev server is threaded, so load AND encode go through one lock."""
    import sys
    import threading
    import time
    import types

    from movie_brain.infrastructure import embeddings

    constructions = []
    inside, overlap = [0], [0]  # how many encodes are running right now, and the most ever seen

    class SlowModel:
        def __init__(self, name):
            constructions.append(threading.get_ident())
            time.sleep(0.05)  # long enough for every thread to reach _load before the first returns

        def encode(self, texts, **kw):
            inside[0] += 1
            overlap[0] = max(overlap[0], inside[0])
            time.sleep(0.02)
            inside[0] -= 1
            return [[0.0] * EMBED_DIM for _ in texts]

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=SlowModel))
    monkeypatch.setattr(embeddings.importlib.util, "find_spec", lambda name: object())
    embedder = embeddings.SentenceTransformerEmbedder()
    threads = [threading.Thread(target=embedder.encode, args=(["q"],)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(constructions) == 1
    assert overlap[0] == 1  # encodes never ran concurrently


class _AlwaysUnavailable:
    """An embedder that always fails to load — stands in for a model not cached, offline."""

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        raise SemanticUnavailable("could not load: offline")


def test_embed_query_latches_semantic_unavailable_after_the_first_failure(repo):
    embedder = _AlwaysUnavailable()
    idx = VectorIndex(repo, embedder, model="m")
    with pytest.raises(SemanticUnavailable):
        idx.embed_query("gumshoe")
    with pytest.raises(SemanticUnavailable):
        idx.embed_query("gumshoe")
    assert embedder.calls == 1  # the second call never reaches the embedder


def test_index_notices_a_merge_that_moves_the_loser_vector_onto_the_survivor(repo, fake_embedder):
    a, b = _films(repo, 2)
    repo.write_embeddings([(b, pack(_unit(0)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert [i for i, _ in idx.nearest(_unit(0), 2.0)] == [b]
    repo.merge_film(b, a, D)  # survivor a holds no vector, so the loser's row MOVES to a
    assert [i for i, _ in idx.nearest(_unit(0), 2.0)] == [a]


def test_index_notices_a_tombstoned_film_dropping_out(repo, fake_embedder):
    (a,) = _films(repo, 1)
    repo.write_embeddings([(a, pack(_unit(0)))], D, model="m", dim=EMBED_DIM)
    idx = VectorIndex(repo, fake_embedder, model="m")
    assert [i for i, _ in idx.nearest(_unit(0), 2.0)] == [a]
    repo.tombstone_film(a, D)  # film_embedding is untouched; only _NOT_DISPOSED hides the row
    assert idx.nearest(_unit(0), 2.0) == []
