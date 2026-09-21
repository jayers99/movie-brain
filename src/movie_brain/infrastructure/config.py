from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "movie-brain"
CONFIG_DIR_ENV = "MOVIE_BRAIN_CONFIG_DIR"
API_KEY_ENV = "OMDB_API_KEY"
TMDB_TOKEN_ENV = "MOVIE_BRAIN_TMDB_TOKEN"


@dataclass(frozen=True)
class Config:
    config_dir: Path

    @property
    def db_path(self) -> Path:
        return self.config_dir / "movie-brain.db"

    @property
    def key_file(self) -> Path:
        return self.config_dir / "omdb-api-key.txt"

    @property
    def tmdb_token_file(self) -> Path:
        return self.config_dir / "tmdb-read-token.txt"

    @property
    def credentials_file(self) -> Path:
        return self.config_dir / "credentials.toml"


def load_config() -> Config:
    env = os.environ.get(CONFIG_DIR_ENV)
    return Config(Path(env) if env else DEFAULT_CONFIG_DIR)


def _from_credentials(config: Config, site: str, name: str) -> str | None:
    # Imported here: `credentials` imports `Config` from this module.
    from movie_brain.infrastructure.credentials import load_secret

    return load_secret(config, site, name)


def load_api_key(config: Config) -> str | None:
    """Environment, then `credentials.toml` (`[omdb] api_key`, backlog 21), then the old key file."""
    if key := os.environ.get(API_KEY_ENV):
        return key.strip()
    if key := _from_credentials(config, "omdb", "api_key"):
        return key
    if config.key_file.exists():
        return config.key_file.read_text().strip() or None
    return None


def load_tmdb_token(config: Config) -> str | None:
    """Environment, then `credentials.toml` (`[tmdb] read_token`), then the old token file."""
    if token := os.environ.get(TMDB_TOKEN_ENV):
        return token.strip()
    if token := _from_credentials(config, "tmdb", "read_token"):
        return token
    if config.tmdb_token_file.exists():
        return config.tmdb_token_file.read_text().strip() or None
    return None
