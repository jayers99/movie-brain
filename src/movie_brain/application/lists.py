"""Curated top-N lists: the resolution helpers the import and create verbs share.

A list entry is a curator's title plus, usually, a director — no year, no id, no url. Turning
that into a film id is the accuracy test of the T1-T5 identity stack, and **duplicate films
are the failure it must not produce**: under-creating costs one review row, over-creating
costs a merge. So the four helpers here are deliberately timid.

- `entry_forms` — every title string one entry could be known by, primary first.
- `resolve_entry` — the fallback-only form ladder over those forms (design §1 A2).
- `find_holder` — gates 1 / 2 / 2b: does a film in the catalog already hold this work's ids?
- `corpus_veto` — gate 3: does the catalog hold anything *resembling* any of these titles?

`import_list` is phase 1 (design §5): it links, it asks, and it **never creates a film**.
`create_films` is phase 2 (design §6) and is the ONLY path in this feature that creates one.
`scorecard` renders either result, and is the deliverable of the accuracy test — a wrong *link*
is silent in a way a duplicate film is not, so every entry gets a printed line.

`find_holder` is the third sibling of the resolve-first block in `owned.py::import_owned` and
`metacritic.py::promote_top_n`, with one addition — gate 2b (design §1 A4): a resolver winner
that exists only in OMDb carries no TMDB id, so the plain gate 2 asks nothing at all. Asking
TMDB for the mapping — the same `find_by_imdb` call `key_film` already trusts on every keying
path — can only find *more* holders, so it strictly reduces creations.

The four helpers write nothing; the two verbs write, and only with `apply=True`.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.keying import key_film
from movie_brain.domain.matching import Candidate, CandidateIndex, build_candidate_index
from movie_brain.domain.models import Film, ListEntry, ListMeta, ReviewEntry
from movie_brain.domain.thumbprint import Candidate as WorkCandidate
from movie_brain.domain.thumbprint import Verdict, make_query, parse_title, resolve
from movie_brain.infrastructure.database import FilmRow, Repository
from movie_brain.infrastructure.omdb import QuotaExceeded
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

AUTHORITY = "list"

# match_review reasons these verbs queue, all under AUTHORITY with film_id NULL.
UNRESOLVED = "unresolved"
CORPUS_VETO = "corpus-veto"
DUPLICATE_ENTRY = "duplicate-entry"
TOMBSTONED_HOLDER = "tombstoned-holder"
KEY_COLLISION = "key-collision"

# key_film results that leave the new film identified; anything else waits for the next sync.
KEYED_OK = ("keyed", "unlinked")


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def _winner(verdict: Verdict) -> WorkCandidate | None:
    """The candidate the verdict actually chose — `None` when it fell outside the top three.

    `resolve` truncates `ranked` to three, so a match can carry a `tt` no listed candidate
    holds. Every caller must cope with that instead of assuming the winner is present.
    """
    return next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)


def entry_forms(title_listed: str) -> list[str]:
    """Every title string this entry could be known by, primary form first.

    One shared definition for the ladder and for gate 3's veto — the two must never disagree
    about what counts as "this entry's title". `ParsedTitle.forms()` already returns
    `(title, base, *alt_titles)` de-duplicated; a plain title therefore yields one form.
    """
    return list(parse_title(title_listed).forms())


def resolve_entry(
    fetcher: CandidateFetcher,
    entry: ListEntry,
    log: Callable[[str], None] = _stderr,
) -> tuple[Verdict | None, str]:
    """Resolve one list entry through the fallback-only form ladder; returns (verdict, form).

    The primary form is asked first and a `match` there is returned immediately — a form
    further down the ladder can never override an already-corroborated match. Only when the
    primary misses are `base` and then each alt title tried, stopping at the first `match`.
    When nothing matches, the **primary** form's verdict is what comes back — it was asked
    against the title the curator actually wrote, so its reason is the one worth reviewing —
    or the first form that answered at all, when the primary's own lookup failed. When every
    form's lookup failed, `(None, primary_form)` comes back.

    The query year is always `None`: the list carries no years, and inventing one actively
    misleads the resolver. Source `"list"` lands on `YearClass.APPLE_FIELD`, inert while
    `q.year is None`.
    """
    forms = entry_forms(entry.title_listed)
    answered: tuple[Verdict, str] | None = None
    for form in forms:
        # The literal, not AUTHORITY: the resolver's `source` and the claim/review authority
        # are different concepts that happen to share a string. Renaming one must not move
        # the query's YearClass.
        q = make_query(form, None, "list", director=entry.director_listed)
        try:
            verdict = resolve(q, fetcher.fetch(q))
        except (CacheMiss, requests.RequestException, AuthError, QuotaExceeded) as exc:
            log(f"resolver lookup failed for {form!r}: {exc}")
            continue
        if verdict.kind == "match" and verdict.tt is not None:
            return verdict, form
        if answered is None:
            answered = (verdict, form)
    return answered if answered is not None else (None, forms[0])


def find_holder(
    repo: Repository,
    tmdb: TmdbClient | None,
    verdict: Verdict,
    log: Callable[[str], None] = _stderr,
) -> tuple[int | None, str]:
    """Gates 1, 2 and 2b: the film already holding this work, and the gate that found it.

    The label is contract text the scorecard reads; a caller may branch on it. Seven values:

    | label | film_id | meaning |
    |---|---|---|
    | `imdb tt0006864`     | set  | gate 1 — a film is already keyed to this IMDb id |
    | `tmdb 3059`          | set  | gate 2 — a film holds the winning candidate's TMDB id |
    | `tmdb(find 3059)`    | set  | gate 2b — a film holds the TMDB id `find_by_imdb` maps this tt to |
    | `tombstoned #412`    | None | a holder exists but a human hid it: never create over it |
    | `no holder`          | None | every gate ran and missed — the would-create path |
    | `tmdb lookup failed` | None | gate 2b raised: the holder is unknown, NOT disproved |
    | `""`                 | None | the verdict is not a match, so nothing was asked |
    """
    if verdict.kind != "match" or verdict.tt is None:
        return None, ""

    # Gate 1 — a film already keyed to this IMDb id is the same work under some other title.
    holder = repo.film_id_for_external("imdb", verdict.tt)
    label = f"imdb {verdict.tt}"

    if holder is None:
        winner = _winner(verdict)
        if winner is not None and winner.tmdb_id is not None:
            # Gate 2 — the winning candidate's own TMDB id.
            holder = repo.film_id_for_external("tmdb", str(winner.tmdb_id))
            label = f"tmdb {winner.tmdb_id}"
        elif tmdb is not None:
            # Gate 2b — gate 2 asked nothing, either because the winner is OMDb-only and
            # carries no TMDB id, or because `resolve` truncates `ranked` to the top three
            # and the winner fell outside it. Both are the same question here, and gate 2b's
            # only input is `verdict.tt` — never the winner (design §1 A4, live case #69
            # Intolerance). Failing to ask fails in the CREATING direction, which is the one
            # failure this import must not make.
            try:
                tmdb_id = tmdb.find_by_imdb(verdict.tt)
            except (requests.RequestException, AuthError) as exc:
                log(f"tmdb find_by_imdb failed for {verdict.tt}: {exc}")
                return None, "tmdb lookup failed"
            if tmdb_id is not None:
                holder = repo.film_id_for_external("tmdb", str(tmdb_id))
                label = f"tmdb(find {tmdb_id})"

    if holder is None:
        return None, "no holder"
    film_id = repo.canonical_film_id(holder)
    d = repo.disposition_of(film_id)
    if d is not None and d[0] == "tombstoned":
        return None, f"tombstoned #{film_id}"
    return film_id, label


def corpus_veto(index: CandidateIndex, forms: list[str]) -> list[Candidate]:
    """Gate 3: every catalog film resembling ANY of these forms, de-duplicated, order stable.

    A veto, not a matcher — a weak, ambiguous or tied hit is reason enough for the caller to
    refuse creation and hand the entry to a human. This deliberately inverts `owned import`,
    where the corpus matcher is a *fallback* that picks a winner. Gate 3 covers the films
    holding neither id, and the case where TMDB's own id mapping does not reunite two records
    of one work.
    """
    hits: dict[int, Candidate] = {}
    for form in forms:
        for c in index.lookup(form)[1]:
            hits.setdefault(c.id, c)
    return list(hits.values())


@dataclass(frozen=True)
class EntryOutcome:
    """One entry's fate, plus everything the scorecard needs to render it.

    `reason` is the resolver's own reason string — contract text, carried verbatim and never
    reworded — and `detail` is the rendered tail of the entry's scorecard line, reused as the
    body of its review row so the printed page and the queued row can never disagree.
    """

    rank: int
    title_listed: str
    director_listed: str | None
    kind: str  # linked | created | would-create | review | blocked | error
    film_id: int | None
    tt: str | None
    reason: str
    form_used: str
    detail: str


@dataclass(frozen=True)
class ListImportReport:
    exit_code: int
    total: int
    linked: int
    would_create: int
    review: int
    blocked: int
    errors: int
    rows: list[EntryOutcome]


def queue_list_review_once(repo: Repository, entry: ReviewEntry, today: date) -> bool:
    """Append one durable `list` review row unless that entry's row already exists.

    **Dedup is on reason + value, NOT reason + film_id** — the difference matters. The shared
    `application/availability.py::queue_review_once` keys on reason + film_id, and every list
    row carries `film_id = NULL`, so under that helper the first open `unresolved` row would
    silently suppress the `unresolved` row of every later entry on the list. `value` is
    `<slug>#<rank>`, which is exactly one entry, so it is the right key here.

    A resolved row is a standing decision, consulted the same way every other authority does
    it: a `--dismiss` is permanent and is never re-queued by a later import.
    """
    for r in repo.open_reviews(AUTHORITY):
        if r["reason"] == entry.reason and r["value"] == entry.value:
            return False
    if (entry.reason, entry.film_id, entry.value) in repo.resolved_review_keys(AUTHORITY):
        return False  # a human already decided this one
    repo.append_reviews(AUTHORITY, [entry], today)
    return True


def _outcome(
    entry: ListEntry,
    kind: str,
    detail: str,
    *,
    film_id: int | None = None,
    tt: str | None = None,
    reason: str = "",
    form: str = "",
) -> EntryOutcome:
    return EntryOutcome(
        entry.rank, entry.title_listed, entry.director_listed, kind, film_id, tt, reason, form, detail
    )


def _listed(entry: ListEntry) -> str:
    return f"{entry.title_listed!r} / {entry.director_listed or '?'}"


def _review_detail(entry: ListEntry, form: str, detail: str) -> str:
    """What a human draining this row sees: the listed title/director, then the entry's own
    scorecard tail (resolver reason plus candidates or vetoing films), then the form asked."""
    return f"{_listed(entry)} — {detail} [form {form!r}]"


def _would_create_label(verdict: Verdict) -> str:
    """`tt0028950 'Grand Illusion' (1937)` — the work phase 2 would mint, named by the winner.

    With no winner in `ranked`, the tt alone is still the honest answer.
    """
    winner = _winner(verdict)
    if winner is None or not winner.titles:
        return str(verdict.tt)
    return f"{verdict.tt} {winner.titles[0]!r} ({winner.year or '-'})"


def _candidates(verdict: Verdict) -> str:
    """The resolver's top three, in the `repair nomatch` shape a reviewer already reads."""
    if not verdict.ranked:
        return "none"
    return " / ".join(
        f"{letter} {s.candidate.tt} {(s.candidate.titles[0] if s.candidate.titles else '')!r} "
        f"({s.candidate.year or '-'}) dir {s.candidate.directors or '-'}"
        for letter, s in zip("ABC", verdict.ranked, strict=False)
    )


def _film_label(catalog: dict[int, tuple[str, int | None, str | None]], film_id: int) -> str:
    """`#1207 'The Rules of the Game' (1939) dir Jean Renoir` — enough to eyeball a link."""
    row = catalog.get(film_id)
    if row is None:
        return f"#{film_id}"
    title, year, director = row
    return f"#{film_id} {title!r} ({year or '-'})" + (f" dir {director}" if director else "")


def _catalog(repo: Repository, film_rows: Sequence[FilmRow]) -> dict[int, tuple[str, int | None, str | None]]:
    """film_id -> (title, year, director) for `_film_label`, one read of the catalog per run.

    films_for_matching aliases a merged loser's evidence under its SURVIVOR's id, so one id
    can carry several rows and none of them says which is the film's own. films_for_repair is
    one authoritative row per film; the matching row whose title agrees with it is the
    survivor's own, and only that one may lend its director to the scorecard label.
    """
    catalog: dict[int, tuple[str, int | None, str | None]] = {
        f.id: (f.title, f.year, None) for f in repo.films_for_repair()
    }
    for f in film_rows:
        row = catalog.get(f.id)
        if row is not None and f.title == row[0]:
            catalog[f.id] = (row[0], row[1], f.director)
    return catalog


def _veto_label(hits: list[Candidate]) -> str:
    shown = "; ".join(f"#{c.id} {c.title!r} ({c.year or '-'})" for c in hits[:3])
    return shown + (f"; +{len(hits) - 3} more" if len(hits) > 3 else "")


def import_list(
    repo: Repository,
    meta: ListMeta,
    entries: Sequence[ListEntry],
    today: date,
    *,
    fetcher: CandidateFetcher,
    tmdb: TmdbClient | None,
    apply: bool = False,
    log: Callable[[str], None] = _stderr,
) -> ListImportReport:
    """Phase 1 (design §5): resolve every entry, link what the catalog already holds, ask about the rest.

    A third sibling of `owned.py::import_owned` and `metacritic.py::promote_top_n`, with one
    hard difference: **it never creates a film — not on any path, not with `apply=True`**.
    Creation is `lists create`'s own confirmed run, because a link is cheap to undo and a
    duplicate film is a merge to clean up (seed §0). Every gate that cannot prove a link
    refuses and queues a durable review row for a human.

    Dry run by default: with `apply=False` **nothing at all** is written — no registry row, no
    entries, no claims, no review rows — and the report says what would have happened.

    Re-import is idempotent: an entry that already carries a `film_id` is settled and is
    skipped before the fetcher is touched, so a re-run costs no API calls for the links it
    already made; `upsert_list_entry` refreshes title/director without clearing a link.

    `exit_code` is reserved for a whole-run failure. A per-entry exception logs, counts as
    `error`, and never aborts the run.
    """
    prior = {row.rank: row.film_id for row in repo.list_entries(meta.slug)}
    # film_id -> the rank already holding it. Seeded from the stored links and extended as
    # this run links, so the duplicate-entry guard sees this run's own work too — which the
    # stored-state query `film_rank_on_list` cannot, since a dry run writes nothing.
    linked_at = {fid: rank for rank, fid in prior.items() if fid is not None}

    if apply:
        repo.upsert_film_list(meta, today)
        for entry in entries:
            repo.upsert_list_entry(meta.slug, entry)

    # Once, before the loop — never per entry: these read the whole catalog.
    film_rows = repo.films_for_matching()
    index = build_candidate_index(film_rows)
    catalog = _catalog(repo, film_rows)

    rows: list[EntryOutcome] = []
    reviews: list[ReviewEntry] = []
    for entry in entries:
        value = f"{meta.slug}#{entry.rank}"
        try:
            settled = prior.get(entry.rank)
            if settled is not None:
                detail = f"{_film_label(catalog, settled)}  already linked"
                rows.append(_outcome(entry, "linked", detail, film_id=settled))
                continue

            forms = entry_forms(entry.title_listed)
            verdict, form = resolve_entry(fetcher, entry, log)
            if verdict is None:
                # Every form's lookup failed. That is a transient failure, not a verdict, so
                # it must not become a durable review row a human has to dismiss.
                rows.append(_outcome(entry, "error", "resolver lookup failed for every form", form=form))
                continue

            if verdict.kind != "match" or verdict.tt is None:
                detail = f"resolver {verdict.reason!r}  cands: {_candidates(verdict)}"
                rows.append(_outcome(entry, "review", detail, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(UNRESOLVED, value=value, detail=_review_detail(entry, form, detail)))
                continue

            holder, label = find_holder(repo, tmdb, verdict, log)
            if label == "tmdb lookup failed":
                # Gate 2b raised: the holder is unknown, NOT disproved. Calling this a
                # would-create would point phase 2 at a film that may already exist.
                detail = f"gate 2b: tmdb lookup failed — holder unknown  [{verdict.reason}]"
                rows.append(_outcome(entry, "error", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                continue

            if holder is None and label.startswith("tombstoned"):
                # A human hid that film; the list re-surfacing its title is not a
                # resurrection request, and creating a twin beside it is worse still.
                detail = f"{TOMBSTONED_HOLDER}  {label}  [{verdict.reason}]"
                rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(TOMBSTONED_HOLDER, value=value, detail=_review_detail(entry, form, detail)))
                continue

            if holder is not None:
                twin_rank = linked_at.get(holder)
                if twin_rank is not None:
                    # Two ranks on one list resolving to one film is the list-shaped mirror
                    # of the duplicate-film risk: block, never silently double-link.
                    detail = (
                        f"{DUPLICATE_ENTRY}  {_film_label(catalog, holder)} is already linked "
                        f"at rank {twin_rank}  [{verdict.reason}]"
                    )
                    rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                    reviews.append(
                        ReviewEntry(DUPLICATE_ENTRY, value=value, detail=_review_detail(entry, form, detail))
                    )
                    continue
                if apply:
                    repo.link_list_entry(meta.slug, entry.rank, holder)
                    repo.add_claim(holder, AUTHORITY, value, entry.title_listed, first_seen=today.isoformat())
                linked_at[holder] = entry.rank
                detail = f"{_film_label(catalog, holder)}  via {label}  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "linked", detail, film_id=holder, tt=verdict.tt, reason=verdict.reason, form=form)
                )
                continue

            hits = corpus_veto(index, forms)
            if hits:
                # Gate 3 is a veto, not a matcher: a weak or ambiguous look-alike is reason
                # enough to stop, because ids genuinely differ for one work (design §5.5).
                detail = f"{CORPUS_VETO}  {_veto_label(hits)}  [{verdict.reason}]"
                rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(CORPUS_VETO, value=value, detail=_review_detail(entry, form, detail)))
                continue

            detail = f"{_would_create_label(verdict)}  [{verdict.reason}]"
            rows.append(_outcome(entry, "would-create", detail, tt=verdict.tt, reason=verdict.reason, form=form))
        except Exception as exc:  # one bad entry must never abort the run
            log(f"list entry {value} failed: {exc}")
            rows.append(_outcome(entry, "error", f"unexpected failure: {exc}"))

    if apply:
        for review in reviews:
            queue_list_review_once(repo, review, today)

    tally = Counter(r.kind for r in rows)
    return ListImportReport(
        exit_code=0,
        total=len(entries),
        linked=tally["linked"],
        would_create=tally["would-create"],
        review=tally["review"],
        blocked=tally["blocked"],
        errors=tally["error"],
        rows=rows,
    )


@dataclass(frozen=True)
class ListCreateReport:
    exit_code: int
    total: int
    created: int
    keyed: int
    linked: int
    blocked: int
    errors: int
    rows: list[EntryOutcome]


def _key_new_film(
    repo: Repository,
    tmdb: TmdbClient | None,
    film_id: int,
    tt: str,
    tmdb_id: int | None,
    today: date,
    log: Callable[[str], None],
) -> str:
    """Key a just-created film through the one identity write path, and never re-raise.

    Born keyed is the point (design §6, exactly as Mode-B promotion does it), but a keying
    failure must not undo a creation that already happened: `key_film` leaves the film
    untouched on `held`/`error`, and the next `sync` keying step picks it up. The returned
    status is scorecard text.
    """
    try:
        result = key_film(repo, tmdb, film_id, tt, today, log, tmdb_id=tmdb_id)
    except Exception as exc:  # includes key_film's own [partial] RuntimeError
        log(f"created #{film_id} unkeyed (key_film failed: {exc}); the next sync will retry")
        return "keying failed"
    if result.status not in KEYED_OK:
        log(f"created #{film_id} unkeyed ({result.status}: {result.detail}); the next sync will retry")
    return result.status


def create_films(
    repo: Repository,
    slug: str,
    today: date,
    *,
    fetcher: CandidateFetcher,
    tmdb: TmdbClient | None,
    apply: bool = False,
    log: Callable[[str], None] = _stderr,
) -> ListCreateReport:
    """Phase 2 (design §6): the ONE path in this feature that creates a film.

    The worklist is every entry with no `film_id` and **no `list` review row at all** for its
    `<slug>#<rank>` — open or resolved. Either kind means a human owns that entry: an open row
    is work in progress, a resolved one is a standing decision, exactly as resolved rows are
    treated everywhere else in this project.

    Every entry is **re-resolved and re-gated** here; phase 1's verdict is never trusted,
    because the world may have moved since the import (the same re-derive-at-resolution-time
    rule the repair verbs follow). So a holder that has appeared since is linked rather than
    twinned, a look-alike that has appeared since vetoes, and a verdict that no longer matches
    blocks. Refusing costs one review row; creating a twin costs a merge.

    Dry run by default: with `apply=False` **nothing at all** is written — no film, no link,
    no claim, no review row — and the report says what would have happened. One consequence
    worth knowing before the live run: a dry run never calls `create_film`, so it cannot see a
    `films.key` collision, and a rehearsal can report a create the confirmed run then blocks.

    Nothing here writes to the eval CSV: an auto match is never ratified, or the benchmark
    would be scoring itself.
    """
    if repo.film_list(slug) is None:
        log(f"no list {slug!r} — import it first")
        return ListCreateReport(1, 0, 0, 0, 0, 0, 0, [])

    stored = repo.list_entries(slug)
    # A row of EITHER kind means a human owns that entry: an open one is work in progress, a
    # resolved one is a standing decision. Neither is an invitation to create.
    human_owned: set[str] = {str(r["value"]) for r in repo.open_reviews(AUTHORITY) if r["value"]}
    human_owned |= {str(v) for _reason, _film_id, v in repo.resolved_review_keys(AUTHORITY) if v}
    worklist = [
        ListEntry(row.rank, row.title_listed, row.director_listed)
        for row in stored
        if row.film_id is None and f"{slug}#{row.rank}" not in human_owned
    ]
    # film_id -> the rank already holding it, seeded from the stored links and extended as
    # this run links AND creates, so the duplicate-entry guard sees this run's own work.
    linked_at = {row.film_id: row.rank for row in stored if row.film_id is not None}

    # Once, before the loop — never per entry: these read the whole catalog.
    film_rows = repo.films_for_matching()
    index = build_candidate_index(film_rows)
    catalog = _catalog(repo, film_rows)
    tombstoned = repo.tombstoned_keys()

    rows: list[EntryOutcome] = []
    reviews: list[ReviewEntry] = []
    keyed = 0
    for entry in worklist:
        value = f"{slug}#{entry.rank}"
        try:
            forms = entry_forms(entry.title_listed)
            verdict, form = resolve_entry(fetcher, entry, log)
            if verdict is None:
                # Every form's lookup failed. A transient failure is not a verdict, so it
                # must not become a durable review row a human has to dismiss.
                rows.append(_outcome(entry, "error", "resolver lookup failed for every form", form=form))
                continue

            if verdict.kind != "match" or verdict.tt is None:
                # Phase 1 said would-create; today's resolver does not. Creation needs a
                # standing yes, so the disagreement goes to a human, not to `films`.
                detail = f"{UNRESOLVED}  resolver {verdict.reason!r}  cands: {_candidates(verdict)}"
                rows.append(_outcome(entry, "blocked", detail, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(UNRESOLVED, value=value, detail=_review_detail(entry, form, detail)))
                continue

            holder, label = find_holder(repo, tmdb, verdict, log)
            if label == "tmdb lookup failed":
                # Gate 2b raised: the holder is unknown, NOT disproved. Creating now is
                # exactly the failure this verb exists to avoid; retry when TMDB is back.
                detail = f"gate 2b: tmdb lookup failed — holder unknown  [{verdict.reason}]"
                rows.append(_outcome(entry, "error", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                continue

            if holder is None and label.startswith("tombstoned"):
                detail = f"{TOMBSTONED_HOLDER}  {label}  [{verdict.reason}]"
                rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(TOMBSTONED_HOLDER, value=value, detail=_review_detail(entry, form, detail)))
                continue

            if holder is not None:
                # The world moved since the import: link what exists, create nothing.
                twin_rank = linked_at.get(holder)
                if twin_rank is not None:
                    detail = (
                        f"{DUPLICATE_ENTRY}  {_film_label(catalog, holder)} is already linked "
                        f"at rank {twin_rank}  [{verdict.reason}]"
                    )
                    rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                    reviews.append(
                        ReviewEntry(DUPLICATE_ENTRY, value=value, detail=_review_detail(entry, form, detail))
                    )
                    continue
                if apply:
                    repo.link_list_entry(slug, entry.rank, holder)
                    repo.add_claim(holder, AUTHORITY, value, entry.title_listed, first_seen=today.isoformat())
                linked_at[holder] = entry.rank
                detail = f"{_film_label(catalog, holder)}  via {label}  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "linked", detail, film_id=holder, tt=verdict.tt, reason=verdict.reason, form=form)
                )
                continue

            hits = corpus_veto(index, forms)
            if hits:
                detail = f"{CORPUS_VETO}  {_veto_label(hits)}  [{verdict.reason}]"
                rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(CORPUS_VETO, value=value, detail=_review_detail(entry, form, detail)))
                continue

            # Every gate green. The film is minted under the WINNER's title and year — TMDB's
            # own — so the row looks like the rest of the catalog and lands on the right year;
            # the listed title survives verbatim in the claim.
            winner = _winner(verdict)
            title = winner.titles[0] if winner is not None and winner.titles else entry.title_listed
            year = winner.year if winner is not None else None
            film = Film(title, year, entry.director_listed, "")
            if film.key in tombstoned:
                # A human hid that identity; a curator listing its title is not a
                # resurrection request, and a twin beside it is worse still.
                detail = f"{TOMBSTONED_HOLDER}  key {film.key!r} is tombstoned  [{verdict.reason}]"
                rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(TOMBSTONED_HOLDER, value=value, detail=_review_detail(entry, form, detail)))
                continue

            if not apply:
                detail = f"{_would_create_label(verdict)}  [{verdict.reason}]"
                rows.append(_outcome(entry, "created", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                continue

            film_id = repo.create_film(film)
            if film_id is None:
                # A `films.key` holder the gates did not surface — the world moved in a way
                # nothing here can explain. Never adopt it: that is how a wrong link is made.
                clash = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
                detail = (
                    f"{KEY_COLLISION}  {film.key!r} is held by {_film_label(catalog, clash)}"
                    f"  [{verdict.reason}]"
                )
                rows.append(_outcome(entry, "blocked", detail, tt=verdict.tt, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(KEY_COLLISION, value=value, detail=_review_detail(entry, form, detail)))
                continue

            index.add(Candidate(id=film_id, title=title, year=year))
            catalog[film_id] = (title, year, entry.director_listed)
            repo.link_list_entry(slug, entry.rank, film_id)
            repo.add_claim(film_id, AUTHORITY, value, entry.title_listed, first_seen=today.isoformat())
            linked_at[film_id] = entry.rank
            status = _key_new_film(repo, tmdb, film_id, verdict.tt, winner.tmdb_id if winner else None, today, log)
            if status in KEYED_OK:
                keyed += 1
            detail = (
                f"{_film_label(catalog, film_id)}  {status}  from {_would_create_label(verdict)}"
                f"  [{verdict.reason}]"
            )
            rows.append(
                _outcome(entry, "created", detail, film_id=film_id, tt=verdict.tt, reason=verdict.reason, form=form)
            )
        except Exception as exc:  # one bad entry must never abort the run
            log(f"list entry {value} failed: {exc}")
            rows.append(_outcome(entry, "error", f"unexpected failure: {exc}"))

    if apply:
        for review in reviews:
            queue_list_review_once(repo, review, today)

    tally = Counter(r.kind for r in rows)
    return ListCreateReport(
        exit_code=0,
        total=len(worklist),
        created=tally["created"],
        keyed=keyed,
        linked=tally["linked"],
        blocked=tally["blocked"],
        errors=tally["error"],
        rows=rows,
    )


_LABELS = {
    "linked": "LINKED",
    "created": "CREATED",
    "would-create": "WOULD-CREATE",
    "review": "REVIEW",
    "blocked": "BLOCKED",
    "error": "ERROR",
}
# Both verbs print the same tally, so phase 1's `created 0` is a standing restatement of its
# one hard promise: the import never mints a film.
_TALLY_ORDER = ("linked", "created", "would-create", "review", "blocked", "error")


def scorecard(rows: Sequence[EntryOutcome]) -> str:
    """Design §7: one two-line block per entry, EVERY entry, eyeballable in a single pass.

    This is the deliverable of the accuracy test, not optional polish: a duplicate film
    announces itself, but a list entry attached to the wrong existing film does not, so a
    link is printed as fully as a would-create — the film it landed on, the gate that found
    it, and the resolver's own reason verbatim.
    """
    out: list[str] = []
    for r in rows:
        who = f"{r.title_listed} / {r.director_listed}" if r.director_listed else r.title_listed
        out.append(f"{f'#{r.rank}'.ljust(6)}{who}")
        line = f"→ {_LABELS.get(r.kind, r.kind.upper())} {r.detail}".rstrip()
        if r.form_used and r.form_used != r.title_listed:
            line += f"  [via form {r.form_used!r}]"
        out.append(f"      {line}")
    tally = Counter(r.kind for r in rows)
    out.append(" · ".join(f"{k} {tally[k]}" for k in _TALLY_ORDER))
    return "\n".join(out)
