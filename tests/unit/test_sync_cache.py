from __future__ import annotations

from datetime import date

from movie_brain.application.sync import SOURCE, sync
from movie_brain.domain.models import Film
from movie_brain.infrastructure.thumbprint_fetch import SESSION_CACHE_NAME

TODAY = date(2026, 8, 19)


def test_ratings_only_sync_with_nothing_to_key_skips_the_session_cache_write(repo, config_dir):
    """FIX 1 regression: whenever a config dir and both API keys are present, sync builds the
    resolver's candidate cache (merging the ~10MB checked-in fixture) — even on a
    `--ratings-only` run, where the keying step never runs at all. Before the fix,
    `cache.save()` ran unconditionally outside the ratings-only guard and re-serialized the
    whole merged dict (fixture included) to the session cache file on every such run. With
    zero misses (nothing was ever fetched), the session cache file must never be created."""
    repo.record_catalog(SOURCE, [Film("Seven Samurai", 1954, "Kurosawa", "https://c/seven-samurai")], TODAY)

    result = sync(
        repo,
        api_key="key",
        today=TODAY,
        ratings_only=True,
        tmdb_token="tok",
        config_dir=config_dir,
        log=lambda m: None,
    )

    assert result.exit_code == 0
    assert not (config_dir / SESSION_CACHE_NAME).exists()
