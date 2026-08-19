from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "movie-brain"
CONFIG_DIR_ENV = "MOVIE_BRAIN_CONFIG_DIR"
API_KEY_ENV = "OMDB_API_KEY"


@dataclass(frozen=True)
class Config:
    config_dir: Path

    @property
    def db_path(self) -> Path:
        return self.config_dir / "movie-brain.db"

    @property
    def key_file(self) -> Path:
        return self.config_dir / "omdb-api-key.txt"


def load_config() -> Config:
    env = os.environ.get(CONFIG_DIR_ENV)
    return Config(Path(env) if env else DEFAULT_CONFIG_DIR)


def load_api_key(config: Config) -> str | None:
    if key := os.environ.get(API_KEY_ENV):
        return key.strip()
    if config.key_file.exists():
        return config.key_file.read_text().strip() or None
    return None
