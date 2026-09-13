"""Tier ranker use case (spec docs/superpowers/specs/2026-09-13-tier-ranker-design.md §4–§7).

The server stores clicks; this module derives the state from them on every call (§4.2). Every
function takes the repository and the source and returns the state the page renders next.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

from movie_brain.domain.models import ListMeta, Placed, RankSession
from movie_brain.domain.rank import (
    DEFAULT_LIST_NAME,
    RANKER_SLUGS,
    TIERS,
    VERDICTS,
    Insert,
    Place,
    next_step,
    order_queue,
    order_step,
    propose_anchors,
    tier_for_score,
    tiered_entries,
)
from movie_brain.infrastructure.database import Repository


class RankError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


ORDER_TIER = 1  # the one tier the order mode exposes (order spec O9)


def _film(repo: Repository, film_id: int) -> dict[str, object]:
    title, year, _ = repo.film_facts([film_id]).get(film_id, ("?", None, None))
    return {"film_id": film_id, "title": title, "year": year}


def proposal(repo: Repository, source: str) -> dict[str, object]:
    _check_source(source)
    seeded = repo.owned_seed_films()
    proposed = propose_anchors(seeded)
    choices: dict[int, list[dict[str, object]]] = {t: [] for t in range(1, TIERS + 1)}
    for f in seeded:
        choices[tier_for_score(f.score)].append(
            {"film_id": f.film_id, "title": f.title, "year": f.year, "score": f.score}
        )
    unseen = repo.unseen_film_ids()
    disposed = repo.disposed_film_ids()
    seeded_ids = {f.film_id for f in seeded}
    fallback: list[dict[str, object]] | None = None
    for t in range(1, TIERS + 1):
        if not choices[t]:
            if fallback is None:
                facts = repo.film_facts(
                    i
                    for i in repo.owned_film_ids()
                    if i not in unseen and i not in disposed and i not in seeded_ids
                )
                fallback = [
                    {"film_id": i, "title": f[0], "year": f[1], "score": None}
                    for i, f in sorted(facts.items(), key=lambda kv: kv[1][0])
                ]
            choices[t] = fallback
    out_prop = {
        t: None if p is None else {"film_id": p.film_id, "title": p.title, "year": p.year, "score": p.score}
        for t, p in proposed.items()
    }
    return {"proposal": out_prop, "choices": choices}


def _check_source(source: str) -> None:
    if source not in RANKER_SLUGS:
        raise RankError(400, f"unknown source {source!r}; v1 ranks 'owned' only")


def start_session(repo: Repository, source: str, anchors: Mapping[int, int], today: date) -> int:
    _check_source(source)
    if set(anchors) != set(range(1, TIERS + 1)):
        raise RankError(400, "an anchor is required for every tier 1–5")
    owned, unseen = repo.owned_film_ids(), repo.unseen_film_ids()
    for tier, fid in anchors.items():
        if fid not in owned or fid in unseen:
            raise RankError(400, f"tier {tier} anchor {fid} is not an owned, seen film")
    # swap_anchor already refuses a disposed or already-elsewhere-placed anchor (§ finding 2);
    # start_session must refuse the same shapes before a session is ever created, not after.
    disposed = repo.disposed_film_ids()
    seed_tier = {f.film_id: tier_for_score(f.score) for f in repo.owned_seed_films()}
    for tier, fid in anchors.items():
        if fid in disposed:
            raise RankError(400, f"tier {tier} anchor {fid} is disposed")
        if fid in seed_tier and seed_tier[fid] != tier:
            raise RankError(400, f"tier {tier} anchor {fid} is a seeded film for tier {seed_tier[fid]}")
    if len(set(anchors.values())) != len(anchors):
        raise RankError(400, "the five anchors must be distinct")
    if repo.open_rank_session(source) is not None:
        raise RankError(409, "a session is already open for this source")
    placements = seed_tier
    seed = int(today.strftime("%Y%m%d"))
    sid = repo.create_rank_session(source, seed, dict(anchors), placements, today)
    for tier, fid in anchors.items():
        if fid not in placements:
            repo.place_film(sid, fid, tier, "anchor", today)
    return sid


def _session(repo: Repository, source: str) -> RankSession:
    _check_source(source)
    s = repo.open_rank_session(source)
    if s is None:
        raise RankError(404, "no open session")
    return s


def _queue(repo: Repository, s: RankSession) -> list[int]:
    placed = repo.rank_placements(s.id)
    unseen = repo.unseen_film_ids()
    anchors = {fid for fid in repo.rank_anchors(s.id).values() if fid is not None}
    disposed = repo.disposed_film_ids()
    ids = [
        i
        for i in repo.owned_film_ids()
        if i not in placed and i not in unseen and i not in anchors and i not in disposed
    ]
    ordered = order_queue(s.seed, ids, repo.rank_deferrals(s.id))
    # A film mid-search (verdicts logged, not yet placed) leads: after an undo the same candidate
    # must come straight back (§4.4), and a crash between click and placement resumes it (§4.2).
    # One small query per queued film (~640 live) — fine for a one-user local app; if it ever
    # matters, add `films_with_verdicts(session_id) -> set[int]` to the repository.
    deferred = repo.rank_deferrals(s.id)
    in_progress = [i for i in ordered if i not in deferred and repo.verdicts_for(s.id, i)]
    return in_progress + [i for i in ordered if i not in in_progress]


def session_state(repo: Repository, source: str, today: date) -> dict[str, object]:
    _check_source(source)
    s = repo.open_rank_session(source)
    if s is None:
        return {"session": None}
    anchors = repo.rank_anchors(s.id)
    unseen_ids = repo.unseen_film_ids()
    placed = repo.rank_placements(s.id)
    queue = _queue(repo, s)
    # An anchor marked unseen from the drawer still occupies a NULL-or-not slot; treat it as
    # missing too (§4.6) so the tier stops serving pairs against a film that is out of the pool.
    needs = [t for t in range(1, TIERS + 1) if anchors[t] is None or anchors[t] in unseen_ids]
    pair: dict[str, object] | None = None
    corrupt: list[int] = []
    while queue and not needs:
        cand = queue[0]
        verdicts = repo.verdicts_for(s.id, cand)
        try:
            step = next_step(verdicts)
        except ValueError:
            # A ValueError here must never escape to the route (finding 1b): a log made
            # illegal by a merge-comparison bug, a hand-edited row, or any future write-path
            # defect is skipped — not placed, nothing written — rather than 500ing every
            # `/api/rank/*` call for the rest of the session.
            corrupt.append(cand)
            queue = queue[1:]
            continue
        if isinstance(step, Place):
            # Self-healing (§4.2): a crash between `append_comparison` and `place_film`, or a
            # placed film returned to the queue by an unmark, can leave a candidate whose
            # verdicts already resolve to a tier. Finish the write rather than wedge on it.
            repo.place_film(s.id, cand, step.tier, "compared", today)
            placed = repo.rank_placements(s.id)
            queue = queue[1:]
            continue
        anchor_id = anchors[step.tier]
        assert anchor_id is not None
        pair = {"candidate": _film(repo, cand), "anchor": _film(repo, anchor_id), "tier": step.tier, "asked": verdicts}
        break
    tally = {t: sum(1 for tier, _ in placed.values() if tier == t) for t in range(1, TIERS + 1)}
    return {
        "session": {"id": s.id, "source": s.source, "started_on": s.started_on, "list_slug": s.list_slug},
        "anchors": {t: (None if fid is None else _film(repo, fid)) for t, fid in anchors.items()},
        "tally": tally,
        "placed": len(placed),
        "remaining": len(queue),
        "unseen": len(unseen_ids & repo.owned_film_ids()),
        "pair": pair,
        "needs_anchor": needs,
        "done": not queue and not needs,
        "can_undo": s.last_action is not None,
        "corrupt": corrupt,
    }


def _order_queue(repo: Repository, s: RankSession) -> list[int]:
    """Order spec §4.2: the session's tier 1 placements not yet ordered, mid-insertion films
    first, then the seeded shuffle, order-mode deferrals last. Derived per request."""
    placed = repo.rank_placements(s.id)
    ordered = set(repo.rank_order(s.id, ORDER_TIER))
    unseen = repo.unseen_film_ids()
    disposed = repo.disposed_film_ids()
    ids = [
        fid
        for fid, (tier, _) in placed.items()
        if tier == ORDER_TIER and fid not in ordered and fid not in unseen and fid not in disposed
    ]
    deferred = repo.order_deferrals(s.id)
    queue = order_queue(s.seed, ids, deferred)
    in_progress = repo.films_with_order_verdicts(s.id)
    lead = [i for i in queue if i in in_progress and i not in deferred]
    return lead + [i for i in queue if i not in lead]


def order_state(repo: Repository, source: str, today: date) -> dict[str, object]:
    s = _session(repo, source)
    order = repo.rank_order(s.id, ORDER_TIER)
    queue = _order_queue(repo, s)
    pair: dict[str, object] | None = None
    corrupt: list[int] = []
    while queue:
        cand = queue[0]
        verdicts = repo.order_verdicts_for(s.id, cand)
        try:
            step = order_step(order, verdicts)
        except ValueError:
            corrupt.append(cand)  # never a 500: skipped, nothing written (order spec §4.1)
            queue = queue[1:]
            continue
        if isinstance(step, Insert):
            # O7 (an empty order takes its first film with no click) and the self-heal for a
            # crash between the last append and the insert both land here.
            repo.insert_ordered(s.id, ORDER_TIER, cand, step.slot, today)
            order = repo.rank_order(s.id, ORDER_TIER)
            queue = queue[1:]
            continue
        pair = {
            "candidate": _film(repo, cand),
            "other": _film(repo, step.film_id),
            "position": order.index(step.film_id) + 1,
            "of": len(order),
            "asked": [[other, v] for other, v in verdicts],
        }
        break
    return {
        "tier": ORDER_TIER,
        "ordered": len(order),
        "remaining": len(queue),
        "pair": pair,
        "done": not queue,
        "can_undo": s.last_action is not None,
        "corrupt": corrupt,
    }


def _current_order_pair(repo: Repository, source: str, today: date) -> tuple[RankSession, dict[str, object]]:
    s = _session(repo, source)
    pair = order_state(repo, source, today)["pair"]
    if not isinstance(pair, dict):
        raise RankError(409, "no current pair")
    return s, pair


def order_verdict(
    repo: Repository, source: str, film_id: int, other_film_id: int, verdict: str, today: date
) -> dict[str, object]:
    if verdict not in VERDICTS:
        raise RankError(400, f"verdict must be one of {', '.join(VERDICTS)}")
    s, pair = _current_order_pair(repo, source, today)
    cand, other = pair["candidate"], pair["other"]
    assert isinstance(cand, dict) and isinstance(other, dict)
    if cand["film_id"] != film_id or other["film_id"] != other_film_id:
        raise RankError(409, "that pair is no longer current")
    cid = repo.append_order_comparison(s.id, ORDER_TIER, film_id, other_film_id, verdict, today)
    step = order_step(repo.rank_order(s.id, ORDER_TIER), repo.order_verdicts_for(s.id, film_id))
    inserted = isinstance(step, Insert)
    if isinstance(step, Insert):
        repo.insert_ordered(s.id, ORDER_TIER, film_id, step.slot, today)
    repo.set_last_action(
        s.id,
        {"mode": "order", "kind": "order_verdict", "film_id": film_id, "comparison_id": cid, "inserted": inserted},
    )
    return order_state(repo, source, today)


def order_pass(repo: Repository, source: str, film_id: int, today: date) -> dict[str, object]:
    s, pair = _current_order_pair(repo, source, today)
    cand = pair["candidate"]
    assert isinstance(cand, dict)
    if cand["film_id"] != film_id:
        raise RankError(409, "that candidate is no longer current")
    repo.defer_order_film(s.id, film_id, today.isoformat())
    repo.set_last_action(s.id, {"mode": "order", "kind": "order_defer", "film_id": film_id})
    return order_state(repo, source, today)


def _current_pair(repo: Repository, source: str, today: date) -> tuple[RankSession, dict[str, object]]:
    s = _session(repo, source)
    state = session_state(repo, source, today)
    pair = state["pair"]
    if not isinstance(pair, dict):
        raise RankError(409, "no current pair")
    return s, pair


def record_verdict(
    repo: Repository, source: str, film_id: int, anchor_tier: int, verdict: str, today: date
) -> dict[str, object]:
    if verdict not in VERDICTS:
        raise RankError(400, f"verdict must be one of {', '.join(VERDICTS)}")
    s, pair = _current_pair(repo, source, today)
    cand = pair["candidate"]
    anchor = pair["anchor"]
    assert isinstance(cand, dict) and isinstance(anchor, dict)
    if cand["film_id"] != film_id or pair["tier"] != anchor_tier:
        raise RankError(409, "that pair is no longer current")
    cid = repo.append_comparison(s.id, film_id, int(anchor["film_id"]), anchor_tier, verdict, today)
    step = next_step(repo.verdicts_for(s.id, film_id))
    placed_tier = None
    if isinstance(step, Place):
        repo.place_film(s.id, film_id, step.tier, "compared", today)
        placed_tier = step.tier
    repo.set_last_action(
        s.id,
        {"mode": "tiers", "kind": "verdict", "film_id": film_id, "comparison_id": cid, "placed_tier": placed_tier},
    )
    return session_state(repo, source, today)


def pass_film(
    repo: Repository, source: str, film_id: int, candidate_unseen: bool, anchor_unseen: bool, today: date
) -> dict[str, object]:
    s, pair = _current_pair(repo, source, today)
    cand = pair["candidate"]
    anchor = pair["anchor"]
    assert isinstance(cand, dict) and isinstance(anchor, dict)
    if cand["film_id"] != film_id:
        raise RankError(409, "that candidate is no longer current")
    if anchor_unseen:
        # D10: a bad anchor. Placement rows go with the unseen mark (set_unseen deletes them).
        repo.set_unseen(int(anchor["film_id"]), True, today)
        tier = pair["tier"]
        assert isinstance(tier, int)
        repo.set_rank_anchor(s.id, tier, None, today)
    if candidate_unseen:
        repo.set_unseen(film_id, True, today)
        repo.set_last_action(
            s.id, {"mode": "tiers", "kind": "unseen", "film_id": film_id} if not anchor_unseen else None
        )
    else:
        repo.defer_film(s.id, film_id, today.isoformat())
        repo.set_last_action(
            s.id, {"mode": "tiers", "kind": "defer", "film_id": film_id} if not anchor_unseen else None
        )
    return session_state(repo, source, today)


def undo(repo: Repository, source: str, today: date) -> dict[str, object]:
    s = _session(repo, source)
    action = s.last_action
    if action is None:
        raise RankError(409, "nothing to undo")
    raw_fid = action["film_id"]
    assert isinstance(raw_fid, int)
    fid = raw_fid
    kind = action["kind"]
    if kind == "verdict":
        # Deleting the row shortens a valid sequence to a valid sequence (§4.1); with verdicts
        # still logged the film leads `_queue`, so it is the current candidate again at once.
        comparison_id = action["comparison_id"]
        assert isinstance(comparison_id, int)
        repo.delete_comparison(comparison_id)
        if action.get("placed_tier") is not None:
            repo.unplace_film(s.id, fid)
            # A tier 1 placement can have been free-inserted into the order by an order_state
            # read since (O7) with no last_action of its own; unplace_film never touches
            # rank_order, so purge it here. No order-comparison cleanup is needed: it had none
            # as a candidate (free-inserted, never probed), and undo is one level deep, so no
            # other candidate can have been probed against it since this placement.
            repo.remove_ordered(fid, s.id)
    elif kind == "defer":
        repo.undefer_film(s.id, fid)
    elif kind == "unseen":
        repo.set_unseen(fid, False, today)
    elif kind == "order_verdict":
        comparison_id = action["comparison_id"]
        assert isinstance(comparison_id, int)
        repo.delete_order_comparison(comparison_id)
        if action.get("inserted"):
            repo.remove_ordered(fid, s.id)  # the film leads the order queue again with one verdict fewer
    elif kind == "order_defer":
        repo.undefer_order_film(s.id, fid)
    repo.set_last_action(s.id, None)
    if action.get("mode") == "order":
        return order_state(repo, source, today)
    return session_state(repo, source, today)


def swap_anchor(repo: Repository, source: str, tier: int, film_id: int, today: date) -> dict[str, object]:
    s = _session(repo, source)
    if tier not in range(1, TIERS + 1):
        raise RankError(400, "tier must be 1–5")
    if film_id not in repo.owned_film_ids() or film_id in repo.disposed_film_ids():
        raise RankError(400, "anchor must be an owned film")
    if film_id in repo.unseen_film_ids():
        raise RankError(409, "an unseen film cannot anchor a tier")
    placed = repo.rank_placements(s.id)
    if film_id in placed and placed[film_id][0] != tier:
        raise RankError(409, f"that film is placed in tier {placed[film_id][0]}, not {tier}")
    if film_id not in placed:
        repo.place_film(s.id, film_id, tier, "anchor", today)
    repo.set_rank_anchor(s.id, tier, film_id, today)
    return session_state(repo, source, today)


def save_list(repo: Repository, source: str, name: str | None, today: date, lists_dir: Path) -> dict[str, object]:
    s = _session(repo, source)
    slug = RANKER_SLUGS[source]
    if (lists_dir / f"{slug}.tsv").exists():
        raise RankError(409, f"lists/{slug}.tsv exists — that slug belongs to a checked-in list")
    placed = repo.rank_placements(s.id)
    facts = repo.film_facts(placed)
    order = {fid: pos for pos, fid in enumerate(repo.rank_order(s.id, ORDER_TIER), start=1)}
    entries = tiered_entries(
        (Placed(fid, tier, facts[fid][0], facts[fid][2]) for fid, (tier, _) in placed.items() if fid in facts),
        order,
    )
    list_name = (name or "").strip() or DEFAULT_LIST_NAME[source]
    repo.upsert_film_list(ListMeta(slug, list_name, "me", today.year, None, True), today)
    repo.replace_list_entries(slug, entries)
    repo.set_rank_session_list(s.id, slug)
    return {"slug": slug, "name": list_name, "entries": len(entries)}
