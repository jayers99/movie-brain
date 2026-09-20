"""Site logins live in ONE file outside the repo — `<config_dir>/credentials.toml`, mode 600, one
section per site with `username` and `password` (owner ruling 2026-09-19). The code reads it;
nothing secret is in the code, and nothing read here is ever printed or logged. The OMDb and
TMDB keys are NOT here yet — moving them is its own chore (backlog 21)."""

from __future__ import annotations

import tomllib

from movie_brain.infrastructure.config import Config

PLACEHOLDER = "PUT-YOUR-"  # the template the owner filled in; an untouched value is no credential


def load_credentials(config: Config, site: str) -> tuple[str, str] | None:
    """(username, password) for `site`, or None when the file, the section or either value is
    missing, unreadable, or still the placeholder."""
    path = config.credentials_file
    if not path.exists():
        return None
    try:
        section = tomllib.loads(path.read_text()).get(site)
    except (ValueError, OSError):  # ValueError covers tomllib.TOMLDecodeError AND UnicodeDecodeError
        return None
    if not isinstance(section, dict):
        return None
    username, password = section.get("username"), section.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        return None
    if PLACEHOLDER in username or PLACEHOLDER in password:
        return None
    return username, password
