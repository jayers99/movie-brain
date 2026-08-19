from pathlib import Path

from movie_brain.infrastructure.config import Config, load_api_key, load_config


def test_load_config_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path))
    cfg = load_config()
    assert cfg.config_dir == tmp_path
    assert cfg.db_path == tmp_path / "movie-brain.db"


def test_load_config_defaults_to_home(monkeypatch):
    monkeypatch.delenv("MOVIE_BRAIN_CONFIG_DIR", raising=False)
    assert load_config().config_dir == Path.home() / ".config" / "movie-brain"


def test_api_key_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OMDB_API_KEY", " envkey ")
    (tmp_path / "omdb-api-key.txt").write_text("filekey\n")
    assert load_api_key(Config(tmp_path)) == "envkey"


def test_api_key_falls_back_to_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    (tmp_path / "omdb-api-key.txt").write_text("filekey\n")
    assert load_api_key(Config(tmp_path)) == "filekey"


def test_api_key_missing_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    assert load_api_key(Config(tmp_path)) is None
