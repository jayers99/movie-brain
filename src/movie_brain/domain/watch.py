"""Ranking the places a film can be watched (design 2026-08-29-canon-best-source §5).

The best source is the first entry of a film's ranked svod set. Four keys decide it, in order:
subscribed (C3 — watch it once on something already paid for), quality (C7 via C9 — the owner's
hand-set per-service constant), an Apple TV app (C6 via C10 — a tiebreak, never a veto), and the
name, for stability.

The monetization tier is deliberately absent. C2 says flatrate, free and ads all mean "I can
watch this", so a free-with-ads service carrying a better transfer must be allowed to win.
`kind` keeps its other job — a `store` is a shop, not access, and is never a watch option.

`infrastructure/database.py::_SERVICES_SQL` orders `FilmView.services` on the same four keys;
`tests/unit/test_database.py::test_services_sql_order_matches_the_domain_ranking` is what keeps
the two in lockstep.
"""

from __future__ import annotations

from movie_brain.domain.models import FilmView

WatchOption = dict[str, object]


def rank_key(option: WatchOption) -> tuple[int, int, int, str]:
    """Ascending sort key — the smallest tuple is the BEST option, so `sorted` needs no reverse."""
    return (
        0 if option.get("subscribed") else 1,
        -int(option.get("quality") or 0),  # type: ignore[call-overload]
        0 if option.get("has_apple_app") else 1,
        str(option.get("name") or ""),
    )


def watch_options(view: FilmView, criterion: WatchOption | None) -> list[WatchOption]:
    """Every svod place this film can be watched today, best first.

    `criterion` is the `movie_service` row for slug 'criterion', as a dict. Criterion is absent
    from `FilmView.services` because `_SERVICES_SQL` filters it out (`l.source != 'criterion'`) —
    the Criterion listing reaches the read model through `_VIEW_SQL`'s own LEFT JOIN instead — so
    a current listing is re-joined here rather than in SQL. Criterion covers 88 of the canon's
    200, so a ranking blind to it answers the wrong question for 44% of the set.
    """
    options: list[WatchOption] = [dict(s) for s in view.services if s.get("kind") == "svod"]
    if criterion is not None and view.criterion and not view.departed:
        options.append(dict(criterion))
    return sorted(options, key=rank_key)


def best_source(
    view: FilmView, criterion: WatchOption | None, store: WatchOption | None = None
) -> WatchOption | None:
    """The single best place to watch this film, or None when nowhere streams it.

    POSSESSION SHORT-CIRCUITS THE RANKING (owner decision, 2026-08-29): a film already owned
    is the best access there is, so it answers with the store it was bought from and never
    competes on the four keys. `store` is the `apple-tv-store` registry row, passed rather
    than hardcoded so the drawer shows the registry's own name — and it is used even when the
    film carries no store LISTING, which matters: measured over the live catalogue, 38 of 858
    owned films have none. A `store` of None falls through to the ordinary ranking rather than
    returning nothing, so a caller that does not supply one is degraded, never broken.
    """
    if view.owned and store is not None:
        return dict(store)
    options = watch_options(view, criterion)
    return options[0] if options else None
