"""Discovery probe for CheapCharts' account + wishlist API (backlog 3, "Wishlist it").

The website is an Angular app that talks to a plain HTTP API at buster.cheapcharts.de/v1/ —
read out of its own main bundle on 2026-09-19, then proven against the owner's account the same day
(login, read, addItem and changeInitPrice all succeeded; itemType MUST be `buymovies`, `movies` is refused):

    POST Account.php   body: country, action=login, email, password (SHA-256 hex), origin=website,
                             appEntity=cc_main_website            -> a sessionToken
    POST Wishlist.php?country=us&store=itunes&action=getShortItemList_v2   body: sessionToken
    POST Wishlist.php?...&action=addItem&itemType=buymovies&idInStore=<id> body: sessionToken
    POST Wishlist.php?...&action=changeInitPrice&itemType=buymovies&idInStore=<id>
                          &customPrice=<p>&customPriceHd=<p>               body: sessionToken
    POST Wishlist.php?...&action=removeItem&itemType=buymovies&idInStore=<id> body: sessionToken

Credentials come ONLY from <config_dir>/credentials.toml, section [cheapcharts]; they are never
printed, and neither is the session token. `read` changes nothing on the account. `add` and
`remove` DO write to the owner's real wishlist — run them only on his say-so.

    uv run python scripts/discovery/cheapcharts_wishlist_probe.py read
    uv run python scripts/discovery/cheapcharts_wishlist_probe.py add 273058482 5.99
    uv run python scripts/discovery/cheapcharts_wishlist_probe.py remove 273058482
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import tomllib
from typing import Any

import requests

from movie_brain.infrastructure.config import load_config

API = "https://buster.cheapcharts.de/v1/"
HEADERS = {"Referer": "https://www.cheapcharts.com/", "User-Agent": "movie-brain/probe"}
PLACEHOLDER = "PUT-YOUR-"
SECRET_KEYS = ("token", "password", "email", "mail", "user", "name", "device", "customer")
DELAY_S = 1.5


def credentials() -> tuple[str, str]:
    path = load_config().config_dir / "credentials.toml"
    if not path.exists():
        sys.exit(f"no credentials file at {path}")
    section = tomllib.loads(path.read_text()).get("cheapcharts") or {}
    username, password = section.get("username", ""), section.get("password", "")
    if not username or not password or PLACEHOLDER in username or PLACEHOLDER in password:
        sys.exit(f"[cheapcharts] username/password in {path} are still the placeholders")
    return username, password


def redact(value: Any, key: str = "") -> Any:
    """Shape without secrets: any key that smells personal shows only its type and length."""
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value[:3]] + ([f"… {len(value) - 3} more"] if len(value) > 3 else [])
    if any(s in key.lower() for s in SECRET_KEYS):
        return f"<{type(value).__name__} len {len(str(value))}>"
    return value


def post(session: requests.Session, endpoint: str, params: dict[str, str], body: dict[str, str]) -> dict[str, Any]:
    time.sleep(DELAY_S)
    response = session.post(API + endpoint, params=params, data=body, headers=HEADERS, timeout=30)
    print(f"  HTTP {response.status_code}  {endpoint}  action={params.get('action') or body.get('action')}")
    try:
        data: dict[str, Any] = response.json()
    except ValueError:
        sys.exit(f"  not JSON: {response.text[:200]!r}")
    return data


def find_token(data: Any) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "sessionToken" and isinstance(value, str):
                return value
            if (found := find_token(value)) is not None:
                return found
    if isinstance(data, list):
        for value in data:
            if (found := find_token(value)) is not None:
                return found
    return None


def login(session: requests.Session) -> str:
    username, password = credentials()
    data = post(
        session,
        "Account.php",
        {},
        {
            "country": "us",
            "action": "login",
            "email": username,
            # The website never sends the plain password: it sends its SHA-256 hex digest (login form, hashPassword()).
            "password": hashlib.sha256(password.encode()).hexdigest(),
            "origin": "website",
            "appEntity": "cc_main_website",
        },
    )
    print("  login response shape:", json.dumps(redact(data))[:600])
    token = find_token(data)
    if not token:
        sys.exit("  no sessionToken in the login response — wrong email/password, or an Apple/Facebook sign-in account")
    print(f"  logged in (token: {len(token)} characters, not shown)")
    return token


def wishlist_params(action: str, **extra: str) -> dict[str, str]:
    return {"country": "us", "store": "itunes", "action": action, **extra}


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in ("read", "add", "remove"):
        sys.exit(__doc__)
    session = requests.Session()
    token = login(session)
    body = {"sessionToken": token}
    if argv[0] == "add":
        itunes_id, price = argv[1], argv[2]
        data = post(
            session, "Wishlist.php", wishlist_params("addItem", itemType="buymovies", idInStore=itunes_id), body
        )
        print("  addItem:", json.dumps(redact(data))[:500])
        data = post(
            session,
            "Wishlist.php",
            wishlist_params(
                "changeInitPrice", itemType="buymovies", idInStore=itunes_id, customPrice=price, customPriceHd=price
            ),
            body,
        )
        print("  changeInitPrice:", json.dumps(redact(data))[:500])
    elif argv[0] == "remove":
        data = post(
            session, "Wishlist.php", wishlist_params("removeItem", itemType="buymovies", idInStore=argv[1]), body
        )
        print("  removeItem:", json.dumps(redact(data))[:500])
    data = post(session, "Wishlist.php", wishlist_params("getShortItemList_v2"), body)
    print("  wishlist shape:", json.dumps(redact(data))[:1200])


if __name__ == "__main__":
    main(sys.argv[1:])
