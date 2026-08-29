"""Curated top-N lists: the resolution helpers the import and create verbs share.

A list entry is a curator's title plus, usually, a director — no year, no id, no url. Turning
that into a film id is the accuracy test of the T1-T5 identity stack, and **duplicate films
are the failure it must not produce**: under-creating costs one review row, over-creating
costs a merge. So the five helpers here are deliberately timid.

- `entry_forms` — every title string one entry could be known by, primary first.
- `resolve_entry` — the fallback-only form ladder over those forms (design §1 A2).
- `reconcile` — the supplied-id comparison policy: run the resolver anyway, then compare.
- `find_holder` — gates 1 / 2 / 2b: does a film in the catalog already hold this work's ids?
- `corpus_veto` — gate 3: does the catalog hold anything *resembling* any of these titles?
- `veto_forms` — the titles gate 3 asks about: the entry's forms plus the winner's own, shared
  by both verbs so the rehearsal card predicts the confirmed run.

A list may carry an IMDb id per entry (supplied-id spec §3). That id is **external ground
truth**, so the resolver is run anyway and the two answers are reconciled: the headline of
such an import is the AGREEMENT RATE, not the link count. An agreement is never ratified into
`scripts/eval/thumbprint_eval_v1.csv` — `application/eval_log.py::ratify` is the only writer
and only human verdicts drive it, or the benchmark would be scoring itself.

`import_list` is phase 1 (design §5): it links, it asks, and it **never creates a film**.
`create_films` is phase 2 (design §6) and is the ONLY path in this feature that creates one.
`scorecard` renders either result, and is the deliverable of the accuracy test — a wrong *link*
is silent in a way a duplicate film is not, so every entry gets a printed line.

`find_holder` is the third sibling of the resolve-first block in `owned.py::import_owned` and
`metacritic.py::promote_top_n`, with one addition — gate 2b (design §1 A4): a resolver winner
that exists only in OMDb carries no TMDB id, so the plain gate 2 asks nothing at all. Asking
TMDB for the mapping — the same `find_by_imdb` call `key_film` already trusts on every keying
path — can only find *more* holders, so it strictly reduces creations.

The five helpers write nothing; the two verbs write, and only with `apply=True`.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
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
ID_DISAGREEMENT = "id-disagreement"

# `EntryOutcome.agreement`: how the resolver's verdict stood against the curator's id.
# "" is "the entry carried no id", not "we did not check".
AGREE = "agree"
DISAGREE = "disagree"
SUPPLIED = "supplied"  # the resolver reached no match; the id is the evidence it lacked

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


# The comparison policy, spec §5, as a table rather than as nested conditionals: it is a
# short contract and it should read like one — the first five rows ARE the spec's table.
#   (what the resolver said, what the curator supplied) -> (whose tt to proceed on, agreement)
# "differs" against a "no match" means "differs from what the resolver produced", and the
# resolver produced nothing — there is no third id state to invent for that row.
_POLICY: dict[tuple[str, str], tuple[str, str]] = {
    ("match", "absent"): ("resolver", ""),  # today's behaviour, untouched
    ("match", "same"): ("resolver", AGREE),  # the normal linked / would-create path
    ("match", "differs"): ("neither", DISAGREE),  # never link, never create
    ("no match", "absent"): ("neither", ""),  # today's behaviour, untouched
    ("no match", "differs"): ("listed", SUPPLIED),  # the id is evidence the resolver lacked
    # Unreachable, and listed anyway so the table is total over its own key space rather than
    # total by argument: with no resolver tt there is nothing a supplied id can be "same" as,
    # so `reconcile` classifies every id under a non-match as "differs". Same answer as the row
    # above, because it is the same situation.
    ("no match", "same"): ("listed", SUPPLIED),
}


def reconcile(verdict: Verdict | None, tt_listed: str | None) -> tuple[str | None, str]:
    """The supplied-id comparison policy (spec §5): `(tt to proceed on, agreement)`.

    Pure — no repo, no fetcher, no clock — so the policy is testable as a table rather than
    through a whole import loop. `agreement` is `""` (no id supplied), `AGREE`, `DISAGREE` or
    `SUPPLIED`.

    A **disagreement returns no tt at all**: two independent sources disagree about identity,
    which is exactly what a human is for, so neither id may be proceeded on. Callers must
    therefore branch on `DISAGREE` BEFORE reading a `None` tt as "the resolver found nothing".

    `verdict=None` — every form's lookup failed — reads as "no match" and hands back the
    supplied id, because "the resolver had no verdict" is precisely what `SUPPLIED` counts.
    Both verbs stop one step earlier on that shape, since a transient failure is not a verdict
    and must not become a durable row; the row is here so the policy is total and a later
    caller finds the answer rather than inventing one.

    What this policy does NOT touch: the gates. A supplied id settles *which work this is*; it
    says nothing about whether the catalog already holds that work, which is the question
    gates 1/2/2b/3 answer and the only thing standing between this feature and a duplicate
    film. Every gate runs unchanged on every row above.
    """
    resolver_tt = verdict.tt if verdict is not None and verdict.kind == "match" else None
    said = "match" if resolver_tt is not None else "no match"
    supplied = "absent" if tt_listed is None else "same" if tt_listed == resolver_tt else "differs"
    source, agreement = _POLICY[said, supplied]
    return {"resolver": resolver_tt, "listed": tt_listed, "neither": None}[source], agreement


def _gate_verdict(verdict: Verdict, tt: str) -> Verdict:
    """The verdict the gates run against: the resolver's own, or the same evidence re-pointed
    at a supplied id the resolver could not confirm.

    The resolver's `reason` is carried over verbatim — it is contract text, and the scorecard's
    `[id supplied]` suffix is what says where the tt came from. Re-pointing rather than
    inventing a verdict also keeps `ranked` intact, so a supplied id that IS among the
    resolver's candidates still lends the gates its tmdb id and phase 2 its title and year.
    """
    return verdict if verdict.kind == "match" and verdict.tt == tt else replace(verdict, kind="match", tt=tt)


def _disagreement_detail(entry: ListEntry, verdict: Verdict) -> str:
    """`id-disagreement: resolver tt… [reason] vs listed tt…` — spec §6, one text for both verbs."""
    return f"{ID_DISAGREEMENT}: resolver {verdict.tt} [{verdict.reason}] vs listed {entry.tt_listed}"


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


def veto_forms(forms: list[str], winner: WorkCandidate | None) -> list[str]:
    """The titles gate 3 asks about: the entry's own forms PLUS the winning candidate's own.

    This is the ONE place the two questions are joined, and both verbs go through it so the
    rehearsal card can never predict a would-create the confirmed run turns into a block.

    It deliberately widens `entry_forms`, which stays the one definition of "what might this
    entry be called?" for the resolver ladder. The veto asks a different question — "what
    will the catalog GAIN?" — and once phase 2 mints the film under the WINNER's title rather
    than the curator's, the two stop having the same answer. A legacy unkeyed row titled like
    the winner holds no ids (gates 1/2/2b all miss it) and is titled nothing like the listed
    entry (the listed forms miss it too), leaving `films.key` — which refuses only when title
    AND year both match — as the sole backstop. Strictly in the refusing direction, the same
    argument design §1 A4 makes for gate 2b.
    """
    # `Candidate.titles` can carry an empty string (TMDB's `title`/`original_title` and each
    # alternative title are read with `or ""`), and `index.lookup("")` would veto against any
    # catalog film whose norm_title is empty — a veto on nothing at all.
    return forms + [t for t in (winner.titles if winner is not None else ()) if t and t not in forms]


@dataclass(frozen=True)
class EntryOutcome:
    """One entry's fate, plus everything the scorecard needs to render it.

    `reason` is the resolver's own reason string — contract text, carried verbatim and never
    reworded — and `detail` is the rendered tail of the entry's scorecard line, reused as the
    body of its review row so the printed page and the queued row can never disagree.

    `agreement` is `reconcile`'s verdict on the curator's id, and renders as the scorecard's
    `[id agrees]` / `[id supplied]` suffix. It is a suffix, never a replacement: `reason`
    stays the resolver's own words on every path.
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
    agreement: str = ""  # "" | AGREE | DISAGREE | SUPPLIED


def _id_tally(rows: Sequence[EntryOutcome]) -> tuple[int, int, int, int]:
    """`(agree, disagree, supplied, with_ids)` — the headline of a supplied-id import (spec §2).

    `with_ids` is the DENOMINATOR of the agreement rate, so it is the number of id-bearing
    entries the resolver actually answered for — not the number of ids in the file. An entry
    that was already linked (settled before the fetcher is touched) or whose every lookup
    failed never reaches `reconcile`, and an entry the resolver never spoke about cannot be
    scored against its id.

    So the measurement is meaningful on the FIRST import of a list: a re-import skips every
    entry it already linked before the fetcher is touched, and its tally collapses toward zero.
    That is the counters working, not a regression.

    Both report dataclasses and the scorecard read this one function, so the printed card and
    the machine tally can never drift apart.
    """
    c = Counter(r.agreement for r in rows)
    return c[AGREE], c[DISAGREE], c[SUPPLIED], c[AGREE] + c[DISAGREE] + c[SUPPLIED]


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
    # Defaulted and last so the tally is additive: every existing caller builds this
    # positionally, and these four are one derived reading of `rows` (see `_id_tally`).
    agree: int = 0
    disagree: int = 0
    supplied: int = 0
    with_ids: int = 0


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
    agreement: str = "",
) -> EntryOutcome:
    return EntryOutcome(
        entry.rank, entry.title_listed, entry.director_listed, kind, film_id, tt, reason, form, detail, agreement
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

            # `reconcile` also answers for a None verdict; no verb reaches that row — an
            # every-lookup-failure is the `error` above, not a verdict to proceed from.
            tt, agreement = reconcile(verdict, entry.tt_listed)
            if agreement == DISAGREE:
                # Two independent sources disagree about identity — never link, never create,
                # even where gate 1 would have linked this entry outright a moment ago.
                detail = _disagreement_detail(entry, verdict)
                rows.append(_outcome(entry, "review", detail, reason=verdict.reason, form=form, agreement=agreement))
                reviews.append(ReviewEntry(ID_DISAGREEMENT, value=value, detail=_review_detail(entry, form, detail)))
                continue

            if tt is None:
                detail = f"resolver {verdict.reason!r}  cands: {_candidates(verdict)}"
                rows.append(_outcome(entry, "review", detail, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(UNRESOLVED, value=value, detail=_review_detail(entry, form, detail)))
                continue

            # From here on `verdict` is the verdict the GATES run against — the resolver's own,
            # or (SUPPLIED) the same evidence re-pointed at the curator's id. Every gate below
            # is unchanged: the id settled which work this is, nothing more.
            verdict = _gate_verdict(verdict, tt)

            holder, label = find_holder(repo, tmdb, verdict, log)
            if label == "tmdb lookup failed":
                # Gate 2b raised: the holder is unknown, NOT disproved. Calling this a
                # would-create would point phase 2 at a film that may already exist.
                detail = f"gate 2b: tmdb lookup failed — holder unknown  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "error", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
                continue

            if holder is None and label.startswith("tombstoned"):
                # A human hid that film; the list re-surfacing its title is not a
                # resurrection request, and creating a twin beside it is worse still.
                detail = f"{TOMBSTONED_HOLDER}  {label}  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
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
                    rows.append(
                        _outcome(entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                    )
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
                    _outcome(
                        entry,
                        "linked",
                        detail,
                        film_id=holder,
                        tt=tt,
                        reason=verdict.reason,
                        form=form,
                        agreement=agreement,
                    )
                )
                continue

            hits = corpus_veto(index, veto_forms(forms, _winner(verdict)))
            if hits:
                # Gate 3 is a veto, not a matcher: a weak or ambiguous look-alike is reason
                # enough to stop, because ids genuinely differ for one work (design §5.5).
                # It asks about the winner's titles too, exactly as phase 2's veto does: this
                # import creates nothing either way, so the only effect here is that an entry
                # phase 2 would block is reported blocked on the card the owner authorises
                # from, instead of being promised as a would-create and refused later.
                detail = f"{CORPUS_VETO}  {_veto_label(hits)}  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
                reviews.append(ReviewEntry(CORPUS_VETO, value=value, detail=_review_detail(entry, form, detail)))
                continue

            detail = f"{_would_create_label(verdict)}  [{verdict.reason}]"
            rows.append(
                _outcome(
                    entry,
                    "would-create",
                    detail,
                    tt=tt,
                    reason=verdict.reason,
                    form=form,
                    agreement=agreement,
                )
            )
        except Exception as exc:  # one bad entry must never abort the run
            log(f"list entry {value} failed: {exc}")
            rows.append(_outcome(entry, "error", f"unexpected failure: {exc}"))

    if apply:
        for review in reviews:
            queue_list_review_once(repo, review, today)

    tally = Counter(r.kind for r in rows)
    agree, disagree, supplied, with_ids = _id_tally(rows)
    return ListImportReport(
        exit_code=0,
        total=len(entries),
        linked=tally["linked"],
        would_create=tally["would-create"],
        review=tally["review"],
        blocked=tally["blocked"],
        errors=tally["error"],
        rows=rows,
        agree=agree,
        disagree=disagree,
        supplied=supplied,
        with_ids=with_ids,
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
    # Defaulted and last, exactly as on ListImportReport, and derived by the same `_id_tally`:
    # phase 2 re-resolves every entry, so it reconciles against the ids again rather than
    # trusting phase 1's agreement.
    agree: int = 0
    disagree: int = 0
    supplied: int = 0
    with_ids: int = 0


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
    no claim, no review row — and the report says what would have happened. Two consequences
    worth knowing before the live run, both of which make a rehearsal report a create the
    confirmed run then blocks: a dry run never calls `create_film`, so it cannot see a
    `films.key` collision, and it mints nothing, so it cannot see the `duplicate-entry` block
    between two ranks that would both mint the same work.

    Nothing here writes to the eval CSV: an auto match is never ratified, or the benchmark
    would be scoring itself.

    `tmdb=None` refuses the whole run (exit 1, nothing touched): gate 2b is not optional on
    the creating path, and the invariant belongs here rather than only in the CLI.
    """
    if tmdb is None:
        # Gate 2b is not optional on the creating path: without a client `find_holder` answers
        # "no holder" for every OMDb-only winner and this verb would mint a twin beside a film
        # TMDB could have found. The CLI already refuses, but the invariant belongs in the
        # module that does the creating. `import_list` is deliberately left alone — linking
        # without gate 2b is degraded, not dangerous.
        log("no TMDB client — gate 2b cannot run, so creation would be unguarded; refusing")
        return ListCreateReport(1, 0, 0, 0, 0, 0, 0, [])

    if repo.film_list(slug) is None:
        log(f"no list {slug!r} — import it first")
        return ListCreateReport(1, 0, 0, 0, 0, 0, 0, [])

    stored = repo.list_entries(slug)
    # A row of EITHER kind means a human owns that entry: an open one is work in progress, a
    # resolved one is a standing decision. Neither is an invitation to create.
    human_owned: set[str] = {str(r["value"]) for r in repo.open_reviews(AUTHORITY) if r["value"]}
    human_owned |= {str(v) for _reason, _film_id, v in repo.resolved_review_keys(AUTHORITY) if v}
    worklist = [
        ListEntry(row.rank, row.title_listed, row.director_listed, row.tt_listed)
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
    # tt -> the film this run minted for it. The gates cannot stand in for this: a film whose
    # keying failed carries NO external ids (gates 1, 2 and 2b all miss it), and it is indexed
    # under the winner's title, not the next rank's listed one (gate 3 misses it too). The
    # verdict's tt is the one identity that survives every one of those failures.
    minted: dict[str, int] = {}
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

            # `reconcile` also answers for a None verdict; no verb reaches that row — an
            # every-lookup-failure is the `error` above, not a verdict to proceed from.
            tt, agreement = reconcile(verdict, entry.tt_listed)
            if agreement == DISAGREE:
                # Re-reconciled here, never inherited from phase 1: the resolver may reach a
                # different work today. Two sources at odds about identity is a human's call,
                # and creating under either id would be a guess.
                detail = _disagreement_detail(entry, verdict)
                rows.append(_outcome(entry, "blocked", detail, reason=verdict.reason, form=form, agreement=agreement))
                reviews.append(ReviewEntry(ID_DISAGREEMENT, value=value, detail=_review_detail(entry, form, detail)))
                continue

            if tt is None:
                # Phase 1 said would-create; today's resolver does not. Creation needs a
                # standing yes, so the disagreement goes to a human, not to `films`.
                detail = f"{UNRESOLVED}  resolver {verdict.reason!r}  cands: {_candidates(verdict)}"
                rows.append(_outcome(entry, "blocked", detail, reason=verdict.reason, form=form))
                reviews.append(ReviewEntry(UNRESOLVED, value=value, detail=_review_detail(entry, form, detail)))
                continue

            # From here on `verdict` is the verdict the GATES run against — the resolver's own,
            # or (SUPPLIED) the same evidence re-pointed at the curator's id. Every gate below
            # is unchanged, and gate 3 vetoes an id-bearing entry exactly as it does any other:
            # an id says which work this is, never whether the catalog already holds it.
            verdict = _gate_verdict(verdict, tt)

            holder, label = minted.get(tt), "minted this run"
            if holder is None:
                holder, label = find_holder(repo, tmdb, verdict, log)
            if label == "tmdb lookup failed":
                # Gate 2b raised: the holder is unknown, NOT disproved. Creating now is
                # exactly the failure this verb exists to avoid; retry when TMDB is back.
                detail = f"gate 2b: tmdb lookup failed — holder unknown  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "error", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
                continue

            if holder is None and label.startswith("tombstoned"):
                detail = f"{TOMBSTONED_HOLDER}  {label}  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
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
                    rows.append(
                        _outcome(
                            entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement
                        )
                    )
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
                    _outcome(
                        entry,
                        "linked",
                        detail,
                        film_id=holder,
                        tt=tt,
                        reason=verdict.reason,
                        form=form,
                        agreement=agreement,
                    )
                )
                continue

            # The film is minted under the WINNER's title and year (below) — TMDB's own — so
            # the row looks like the rest of the catalog and lands on the right year; the
            # listed title survives verbatim in the claim. Gate 3 therefore asks about the
            # winner's titles as well as the listed forms (`veto_forms`), which is what makes
            # the veto ask about the title the catalog will actually gain.
            winner = _winner(verdict)
            hits = corpus_veto(index, veto_forms(forms, winner))
            if hits:
                detail = f"{CORPUS_VETO}  {_veto_label(hits)}  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
                reviews.append(ReviewEntry(CORPUS_VETO, value=value, detail=_review_detail(entry, form, detail)))
                continue

            title = winner.titles[0] if winner is not None and winner.titles else entry.title_listed
            year = winner.year if winner is not None else None
            film = Film(title, year, entry.director_listed, "")
            if film.key in tombstoned:
                # A human hid that identity; a curator listing its title is not a
                # resurrection request, and a twin beside it is worse still.
                detail = f"{TOMBSTONED_HOLDER}  key {film.key!r} is tombstoned  [{verdict.reason}]"
                rows.append(
                    _outcome(entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
                reviews.append(ReviewEntry(TOMBSTONED_HOLDER, value=value, detail=_review_detail(entry, form, detail)))
                continue

            if not apply:
                # The owner reads this card before authorising the live run, so it must not
                # claim a creation that has not happened; `created` still counts the row.
                detail = f"{_would_create_label(verdict)}  [{verdict.reason}]"
                rows.append(
                    _outcome(
                        entry, "would-create", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement
                    )
                )
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
                rows.append(
                    _outcome(entry, "blocked", detail, tt=tt, reason=verdict.reason, form=form, agreement=agreement)
                )
                reviews.append(ReviewEntry(KEY_COLLISION, value=value, detail=_review_detail(entry, form, detail)))
                continue

            index.add(Candidate(id=film_id, title=title, year=year))
            catalog[film_id] = (title, year, entry.director_listed)
            minted[tt] = film_id
            repo.link_list_entry(slug, entry.rank, film_id)
            repo.add_claim(film_id, AUTHORITY, value, entry.title_listed, first_seen=today.isoformat())
            linked_at[film_id] = entry.rank
            status = _key_new_film(repo, tmdb, film_id, tt, winner.tmdb_id if winner else None, today, log)
            if status in KEYED_OK:
                keyed += 1
            detail = (
                f"{_film_label(catalog, film_id)}  {status}  from {_would_create_label(verdict)}"
                f"  [{verdict.reason}]"
            )
            rows.append(
                _outcome(
                    entry,
                    "created",
                    detail,
                    film_id=film_id,
                    tt=tt,
                    reason=verdict.reason,
                    form=form,
                    agreement=agreement,
                )
            )
        except Exception as exc:  # one bad entry must never abort the run
            log(f"list entry {value} failed: {exc}")
            rows.append(_outcome(entry, "error", f"unexpected failure: {exc}"))

    if apply:
        for review in reviews:
            queue_list_review_once(repo, review, today)

    tally = Counter(r.kind for r in rows)
    agree, disagree, supplied, with_ids = _id_tally(rows)
    return ListCreateReport(
        exit_code=0,
        total=len(worklist),
        created=tally["created"] + tally["would-create"],  # a dry run's would-creates ARE its creates
        keyed=keyed,
        linked=tally["linked"],
        blocked=tally["blocked"],
        errors=tally["error"],
        rows=rows,
        agree=agree,
        disagree=disagree,
        supplied=supplied,
        with_ids=with_ids,
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
# The supplied-id state as one SUFFIX on the verdict line (spec §6) — the resolver's own reason
# is never replaced by it. A disagreement gets none: its detail already names both ids.
_ID_SUFFIX = {AGREE: "[id agrees]", SUPPLIED: "[id supplied]"}


def scorecard(rows: Sequence[EntryOutcome]) -> str:
    """Design §7: one two-line block per entry, EVERY entry, eyeballable in a single pass.

    This is the deliverable of the accuracy test, not optional polish: a duplicate film
    announces itself, but a list entry attached to the wrong existing film does not, so a
    link is printed as fully as a would-create — the film it landed on, the gate that found
    it, and the resolver's own reason verbatim.

    A list carrying ids gains one trailing line, and it is the deliverable of spec §2: the
    agreement rate is the headline of such an import, not the link count. A list carrying none
    is printed exactly as before.
    """
    out: list[str] = []
    for r in rows:
        who = f"{r.title_listed} / {r.director_listed}" if r.director_listed else r.title_listed
        out.append(f"{f'#{r.rank}'.ljust(6)}{who}")
        line = f"→ {_LABELS.get(r.kind, r.kind.upper())} {r.detail}".rstrip()
        if r.agreement in _ID_SUFFIX:
            line += f"  {_ID_SUFFIX[r.agreement]}"
        if r.form_used and r.form_used != r.title_listed:
            line += f"  [via form {r.form_used!r}]"
        out.append(f"      {line}")
    tally = Counter(r.kind for r in rows)
    out.append(" · ".join(f"{k} {tally[k]}" for k in _TALLY_ORDER))
    agree, disagree, supplied, with_ids = _id_tally(rows)
    if with_ids:
        out.append(
            f"resolver vs supplied id:  agree {agree} · disagree {disagree} · "
            f"resolver had no verdict {supplied}  (of {with_ids} with ids)"
        )
    return "\n".join(out)
