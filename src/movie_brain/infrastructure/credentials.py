"""Site logins live in ONE file outside the repo — `<config_dir>/credentials.toml`, mode 600, one
section per site with `username` and `password` (owner ruling 2026-09-19). The code reads it;
nothing secret is in the code, and nothing read here is ever printed or logged. Since backlog 21
the OMDb key and the TMDB token are read from here too (`[omdb] api_key`, `[tmdb] read_token`,
through `load_secret`); the old one-line key files and the environment variables still work."""

from __future__ import annotations

import tomllib

from movie_brain.infrastructure.config import Config

PLACEHOLDER = "PUT-YOUR-"  # the template the owner filled in; an untouched value is no credential


def _section(config: Config, site: str) -> dict[str, object] | None:
    path = config.credentials_file
    if not path.exists():
        return None
    try:
        section = tomllib.loads(path.read_text()).get(site)
    except (ValueError, OSError):  # ValueError covers tomllib.TOMLDecodeError AND UnicodeDecodeError
        return None
    return section if isinstance(section, dict) else None


def load_secret(config: Config, site: str, name: str) -> str | None:
    """One named value of one site's section (`[omdb] api_key`), or None when the file, the
    section or the value is missing, unreadable, not text, empty, or still the placeholder —
    every one of which sends the caller on to its older source, so no sync can break on this."""
    value = (_section(config, site) or {}).get(name)
    if not isinstance(value, str) or not value.strip() or PLACEHOLDER in value:
        return None
    return value.strip()


def load_credentials(config: Config, site: str) -> tuple[str, str] | None:
    """(username, password) for `site`, or None when the file, the section or either value is
    missing, unreadable, or still the placeholder."""
    section = _section(config, site)
    if section is None:
        return None
    username, password = section.get("username"), section.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        return None
    if PLACEHOLDER in username or PLACEHOLDER in password:
        return None
    return username, password
