from pathlib import Path

from movie_brain.infrastructure.config import Config, load_api_key, load_config, load_tmdb_token


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


def test_tmdb_token_env_wins(monkeypatch):
    from movie_brain.infrastructure.config import load_config, load_tmdb_token

    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", " tok ")
    assert load_tmdb_token(load_config()) == "tok"


def test_tmdb_token_from_file(config_dir):
    from movie_brain.infrastructure.config import load_config, load_tmdb_token

    cfg = load_config()
    assert load_tmdb_token(cfg) is None
    cfg.tmdb_token_file.write_text("filetok\n")
    assert load_tmdb_token(cfg) == "filetok"


def _toml(tmp_path, text):
    (tmp_path / "credentials.toml").write_text(text)
    return Config(tmp_path)


def test_keys_are_read_from_the_one_credentials_file(monkeypatch, tmp_path):
    """Backlog 21 (owner ruling 2026-09-19): every site's secret lives in credentials.toml."""
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    monkeypatch.delenv("MOVIE_BRAIN_TMDB_TOKEN", raising=False)
    cfg = _toml(tmp_path, '[omdb]\napi_key = "k-from-toml"\n\n[tmdb]\nread_token = "t-from-toml"\n')
    assert load_api_key(cfg) == "k-from-toml"
    assert load_tmdb_token(cfg) == "t-from-toml"


def test_the_credentials_file_wins_over_the_old_key_files_and_env_wins_over_both(monkeypatch, tmp_path):
    cfg = _toml(tmp_path, '[omdb]\napi_key = "k-from-toml"\n\n[tmdb]\nread_token = "t-from-toml"\n')
    cfg.key_file.write_text("k-from-txt\n")
    cfg.tmdb_token_file.write_text("t-from-txt\n")
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    monkeypatch.delenv("MOVIE_BRAIN_TMDB_TOKEN", raising=False)
    assert (load_api_key(cfg), load_tmdb_token(cfg)) == ("k-from-toml", "t-from-toml")
    monkeypatch.setenv("OMDB_API_KEY", "k-from-env")
    monkeypatch.setenv("MOVIE_BRAIN_TMDB_TOKEN", "t-from-env")
    assert (load_api_key(cfg), load_tmdb_token(cfg)) == ("k-from-env", "t-from-env")


def test_a_missing_placeholder_or_broken_section_falls_back_to_the_old_key_files(monkeypatch, tmp_path):
    """No sync may break: today's txt files keep working whatever state the toml is in."""
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    monkeypatch.delenv("MOVIE_BRAIN_TMDB_TOKEN", raising=False)
    for text in ("", "[cheapcharts]\nusername = 'a'\npassword = 'b'\n", '[omdb]\napi_key = "PUT-YOUR-KEY-HERE"\n',
                 "[omdb]\napi_key = 7\n", "not = [valid toml"):
        cfg = _toml(tmp_path, text)
        cfg.key_file.write_text("k-from-txt\n")
        cfg.tmdb_token_file.write_text("t-from-txt\n")
        assert (load_api_key(cfg), load_tmdb_token(cfg)) == ("k-from-txt", "t-from-txt"), text
