from datetime import UTC, datetime, timedelta

from movie_brain.application.criterion_bridge import (
    Observation,
    append_observation,
    is_fresh,
    load_observations,
    rewrite_observations,
)

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _obs(url, **kw):
    base = dict(url=url, film_id=56, status=307, location="/films/gpRRkq27/test-pattern", asked_at=NOW.isoformat())
    base.update(kw)
    return Observation(**base)


def test_append_then_load_round_trips(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/test-pattern"))
    got = load_observations(p)
    assert got["https://www.criterionchannel.com/test-pattern"].forward.mediaid == "gpRRkq27"


def test_a_half_written_last_line_is_ignored(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/a"))
    with p.open("a") as fh:
        fh.write('{"url": "https://www.criterionchannel.com/b", "film_id": 7, "sta')
    assert set(load_observations(p)) == {"https://www.criterionchannel.com/a"}


def test_a_later_line_for_the_same_url_wins(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/a", status=None, location=None))
    append_observation(p, _obs("https://www.criterionchannel.com/a"))
    assert load_observations(p)["https://www.criterionchannel.com/a"].forward.kind == "film"


def test_rewrite_replaces_the_whole_file(tmp_path):
    p = tmp_path / "criterion-bridge.jsonl"
    append_observation(p, _obs("https://www.criterionchannel.com/a"))
    rewrite_observations(p, [_obs("https://www.criterionchannel.com/a", applied=True)])
    assert load_observations(p)["https://www.criterionchannel.com/a"].applied is True
    assert not (tmp_path / "criterion-bridge.jsonl.tmp").exists()


def test_freshness_is_24_hours():
    assert is_fresh(_obs("u", asked_at=(NOW - timedelta(hours=23)).isoformat()), NOW)
    assert not is_fresh(_obs("u", asked_at=(NOW - timedelta(hours=25)).isoformat()), NOW)


def test_missing_file_is_empty(tmp_path):
    assert load_observations(tmp_path / "nope.jsonl") == {}
