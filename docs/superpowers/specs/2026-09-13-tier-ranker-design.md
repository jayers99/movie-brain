# Tier ranker — pairwise placement of the owned collection into five tiers

**Date:** 2026-09-13 · **Status:** approved design, awaiting plan · **Opens:** a new subsystem (`/rank`), the first `film_list` not backed by a file, and the `unseen` fact.

## 1. Goal

The owner wants the films they own sorted by their own preference, without scoring each one from a blank page. The mechanism is a side-by-side pair: one film they have not yet placed against a known **anchor** film, and a single click saying which is better. Each click halves the candidate's possible tiers; two or three clicks place it in one of five. Films the owner cannot judge (unseen, or too dimly remembered) are passed into a durable **unseen** bucket and never asked again. The result is saved as an ordinary named list in `film_list`, tiered, with ties inside each tier, so the dashboard's list picker shows it the moment it is saved.

The brainstorm's first finding shaped everything below: a strict full order of N films costs about N·log₂N comparisons and no algorithm beats that floor (858 owned films ≈ 7,000 clicks ≈ 10 hours). The owner chose tiers to stay under that floor. Five tiers cost at most three clicks per film, about 1,700 clicks for the ~640 owned films that carry no rating today.

## 2. Decisions (owner rulings, 2026-09-13)

| # | Ruling | Evidence / cost if wrong |
|---|--------|--------------------------|
| D1 | The output is **tiers, not a strict order**. Five of them. | N·log₂N floor on a strict order (§1). Five tiers = 2–3 clicks per film; seven would map one-to-one onto the owner's 7–10 scores but cost a fourth click on a third of films. Reversible: `TIERS` is one constant in `domain/rank.py`, but a saved list is a snapshot of the count it was made with. |
| D2 | Tiers are a **separate fact** from `my_ratings`, **seeded** from it. `my_ratings` is never written by this feature. | The owner keeps two verdicts per film that may disagree; the alternative (tiers ARE the rating) would overwrite 218 hand-given scores on a fixed mapping the owner has to live with. Seeding removes 218 films from the queue. |
| D3 | Each tier is defined by one **anchor film**; placement is a **binary search against the anchors**. | Deterministic, visible (the anchor is the tier's meaning on screen), 2–3 clicks. Rejected: a random placed member as opponent (no opponent exists early, and the same film lands differently on different days); a direct tier pick with no pair (not pairwise, drifts). A bad anchor skews its tier, so anchors are swappable mid-session. |
| D4 | Anchors are **proposed from the seed**, one per tier (the rated owned film nearest the tier's middle score), and **confirmed or swapped by the owner** before the first pair. | Zero typing to start; every proposed anchor is a film the owner demonstrably has an opinion on. |
| D5 | **Unseen is a durable per-film fact** in its own table on the watchlist pattern, not a per-session flag and not `needs_revisit`. | It must survive across sessions and future sources. `needs_revisit` means "the match looks wrong" and feeds `review revisits`; overloading it would poison that worklist. |
| D6 | **No ordering inside a tier** in v1. The saved list carries tied `rank_label`s (`=1` for the whole top tier, `=N+1` for the next). | The tied-rank contract already exists (migration 015); zero new list machinery. Strict-ordering one tier is a clean follow-up once the top tier's size is known. |
| D7 | **Source is `owned` only** in v1. | The session row still carries a `source` column so a list slug can become a second value later without a schema change. |
| D8 | The screen is a **second page of the existing Flask app**, `/rank`, with its own template, JS and CSS. Nothing is added to `app.js`. | Same server, repository and Playwright harness; the dashboard's URL-state and virtual table never learn a mode. |
| D9 | Controls: **`Better` and `Have not seen` above each film, `Pass` centred above both.** `Better` on either side records the verdict and advances. `Have not seen` toggles that film's unseen mark in place and does NOT advance, so both films can be marked. `Pass` advances. There is no `About the same`. | Owner ruling on the layout. Dropping `same` makes the search a pure yes/no, at most three clicks. |
| D10 | Because D9 lets the **anchor** be marked unseen, that is the "bad anchor" signal: on `Pass` with the anchor marked, the tier's anchor slot empties, the film loses its seed placement and joins the unseen bucket, and the setup card for that one tier reappears before the next pair. | An anchor the owner cannot judge is a wrong anchor; the fix is a swap, never a guess. |
| D11 | **Seeded films are never asked.** They keep their seed tier unless the owner marks them unseen or swaps them in as anchors. | Without `same` there is no one-click confirm; the owner's existing score already IS their verdict. Saves 218 clicks. |
| D12 | The result is written to `film_list` on an explicit **Save as list** action, repeatable, replacing the slug's entries each time. | A snapshot the owner names, not a live view; the list picker and `canon_score` read it exactly like an imported list. |

## 3. Data model (migration 022)

Six tables. All but `rank_session` are film-scoped through `film_id`; `merge_film` moves every one of them survivor-wins, exactly as it moves `watchlist`, `owned` and `film_list_entry`. Only the ranker's use case writes the first five; only the ranker and the drawer's toggle write `unseen`.

```sql
CREATE TABLE rank_session (
    id          INTEGER PRIMARY KEY,
    source      TEXT    NOT NULL,            -- 'owned' (D7); a list slug later
    seed        INTEGER NOT NULL,            -- RNG seed fixing the queue order (§4.3)
    started_on  TEXT    NOT NULL,
    finished_on TEXT,                        -- NULL while open
    list_slug   TEXT REFERENCES film_list(slug)   -- set by the first Save (D12)
);
CREATE UNIQUE INDEX rank_session_open ON rank_session(source) WHERE finished_on IS NULL;

CREATE TABLE rank_anchor (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id    INTEGER REFERENCES films(id),   -- NULL = slot emptied by D10, blocks the next pair
    set_on     TEXT    NOT NULL,
    PRIMARY KEY (session_id, tier)
);

CREATE TABLE rank_placement (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    film_id    INTEGER NOT NULL REFERENCES films(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    how        TEXT    NOT NULL CHECK (how IN ('seed', 'compared')),
    placed_on  TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);

CREATE TABLE rank_comparison (              -- append-only click log (§4.2); undo is its ONE delete
    id              INTEGER PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES rank_session(id),
    film_id         INTEGER NOT NULL REFERENCES films(id),
    anchor_film_id  INTEGER NOT NULL REFERENCES films(id),
    anchor_tier     INTEGER NOT NULL,
    verdict         TEXT    NOT NULL CHECK (verdict IN ('better', 'worse')),
    decided_on      TEXT    NOT NULL
);
CREATE INDEX rank_comparison_film ON rank_comparison(session_id, film_id, id);

CREATE TABLE rank_deferral (                 -- a Pass with nothing marked (§4.3): "not now", queued last
    session_id  INTEGER NOT NULL REFERENCES rank_session(id),
    film_id     INTEGER NOT NULL REFERENCES films(id),
    deferred_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);

CREATE TABLE unseen (                        -- the durable pass bucket (D5), watchlist pattern
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL,
    note      TEXT
);
```

`rank_placement.tier` is the session's whole result. `rank_comparison` is never read to compute a tier; it exists so the placement is auditable and re-derivable if `domain/rank.py` changes, and so `undo` has something to delete. An anchor swap does not touch the log: each row already names the anchor film it was decided against, so a placement made against a since-swapped anchor stays honest about that.

**Seed mapping** (D2), one table in `domain/rank.py` beside `TIERS = 5`, chosen from the live distribution of the 218 owned-and-rated films:

| Tier | `my_ratings.score` | Films today |
|---|---|---|
| 1 | 10 | 29 |
| 2 | 9 | 56 |
| 3 | 8 | 70 |
| 4 | 7 | 45 |
| 5 | 0–6 | 18 |

Score 8 is the mode and holds its own tier; 6 and below share the bottom because they are 18 films between them. Seed rows are written once, at session creation, for every owned film that carries a rating at that moment; a film rated after the session started is an ordinary unrated candidate for that session.

Implementation note (plan 2026-09-13): `rank_session` also carries `last_action TEXT` (JSON), the concrete form of §4.4's action log, giving one level of undo; and `rank_placement.how` admits `anchor` for a film swapped in as a tier's anchor while unplaced, which is the only way an empty tier gets one (§4.5). `set_unseen` deletes both a film's `rank_placement` AND its `rank_comparison` rows in every session (§4.6), since an unseen film's clicks must audit nothing — §4.4's "undo is the one place any of these rows is deleted" narrows to the one delete of a still-placed film's log; `set_unseen` is the other. `session_state` derives `needs_anchor` on every read from whichever tiers have a NULL anchor OR an anchor film that is itself unseen (§4.5 and §4.6 collapse into the one check), and self-heals a candidate whose logged verdicts already resolve to a tier — a crash between `append_comparison` and `place_film`, or a placed film an unmark returned to the queue — by finishing the placement rather than asserting. `start_session` answers a second open session with an explicit `open_rank_session` check and a 409 (`application/rank.py` imports no `sqlite3`); its anchor validation, the anchor proposal's fallback candidates, and `swap_anchor` all exclude disposed films, same as the queue. `rank_comparison.anchor_tier` carries `CHECK (anchor_tier BETWEEN 1 AND 5)` — omitted from the illustrative block above, but present in migration 022 alongside the `tier`/`how`/`verdict` checks already shown.

## 4. The algorithm (`domain/rank.py`, pure)

### 4.1 Binary search over the anchors

The search table is fixed for five tiers and lives in one function, `next_step(verdicts) -> Ask(tier) | Place(tier)`, where `verdicts` is the candidate's ordered list of `better`/`worse` against the anchors it has already met:

| Verdicts so far | Next |
|---|---|
| `[]` | ask tier 3 |
| `[better]` | ask tier 2 |
| `[better, better]` | place 1 |
| `[better, worse]` | place 2 |
| `[worse]` | ask tier 4 |
| `[worse, better]` | place 3 |
| `[worse, worse]` | ask tier 5 |
| `[worse, worse, better]` | place 4 |
| `[worse, worse, worse]` | place 5 |

`better` means "the candidate is better than this anchor." Any sequence not in the table is a corrupt log and raises; the server never constructs one, and `undo` (§4.4) only ever shortens a valid sequence.

### 4.2 State is derived, never stored in the browser

The server stores clicks; the domain derives the state. `GET /api/rank/session` recomputes, from the log, where the current candidate stands and which anchor to show next. A refresh, a crash, or a session reopened a week later lands on the right pair with no client memory. The browser holds only what it is displaying.

### 4.3 The queue

The queue is **derived at request time, never stored**: owned films, minus placed, minus unseen, minus the current anchors, in an order fixed by the session's `seed` (a seeded shuffle of film ids). Random rather than alphabetical so consecutive pairs do not walk through one director's box set. A film bought after the session started joins the queue on the next request. A `Pass` with nothing marked defers the candidate: it moves behind every other unplaced film for this session (a `rank_deferral` row, so the deferral survives a refresh; the queue orders deferred films last, by `deferred_on`).

### 4.4 Undo

Undo deletes the most recent `rank_comparison` row of the session. If that row completed a placement, the placement row is deleted too and the film returns to the head of the queue. If the last action was a pass, undo removes the deferral or the `unseen` row it wrote (for the candidate; an anchor-unseen pass, D10, is not undoable, because the slot has been re-chosen by then). The server keeps a tiny ordered action log for this in the session's own rows: the newest of (`rank_comparison.id`, `rank_deferral.deferred_on`, `unseen.marked_on` for a film in this session's source) wins. Undo is the one place any of these rows is deleted.

### 4.5 Anchors

- **Proposal** (D4): for each tier, among that tier's seeded films, the one whose score is nearest the tier's middle score, ties broken by IMDb rating desc then title. Tier 5's middle is 5.
- **Rules**: an anchor must be a placed film in its own tier. Swapping to a film from another tier is refused (HTTP 409). A tier whose slot is NULL blocks `next pair` and the API answers with `needs_anchor: [tier]` instead of a pair; the screen shows that tier's setup card.
- **Swap** replaces the slot and stamps `set_on`; the old anchor keeps its placement. Earlier comparisons are not re-run.
- **Anchor marked unseen** (D10): on `Pass`, delete the anchor's placement row, write its `unseen` row, NULL its slot. The next request answers `needs_anchor`.

### 4.6 Unseen and placements

Marking a **placed** film unseen from the drawer deletes its placement rows in every session, open or finished. Unmarking (drawer toggle) deletes the `unseen` row; the film re-enters the queue of any open session on the next request, at its shuffled position, never back in its old tier. A saved list is a snapshot and is not rewritten by either action until the owner saves again.

## 5. The screen (`/rank`)

`rank.html`, `static/rank.js`, `static/rank.css`; none of the dashboard's chip, table or search code is loaded. The film cards reuse the fields `GET /api/films/<id>` already returns (D8).

1. **Setup**, shown once per session and again for any tier with an empty slot: five poster cards in a row, each with the tier number, the proposed film's title, year and the owner's score, and a **Swap** control that opens a title search limited to that tier's seeded films. **Start** creates the session (POST) with the five confirmed ids.
2. **The pair**: two equal columns, candidate left, anchor right, the anchor column headed `Tier N anchor`. Each column: poster (grey placeholder when OMDb has none, five owned films today), title, `year · director`, then the memory prompts: TMDB overview (OMDb plot when none), top four cast, runtime, IMDb and Metacritic, the owner's score if any.
3. **Controls** (D9): above each column `Better` and `Have not seen`; centred above both, `Pass`; `Undo` in the header. A marked film's `Have not seen` button reads as pressed until Pass or a second click. Keys: `←` / `→` Better, `1` / `2` Have not seen, `space` Pass, `U` Undo. The candidate's title is a second Have-not-seen trigger.
4. **Progress line**: `placed · remaining · unseen` counts and a five-cell tier tally.
5. **Save as list**: a name field defaulting to `My owned films, tiered`, slug fixed at `my-owned-tiers` for the `owned` source. Repeatable.
6. **Dashboard hooks**: a `Rank` link in the header; an `Unseen` row in the drawer with a toggle, on the watchlist pattern; the saved list appears in the list picker like any other.

## 6. API

| Route | Does |
|---|---|
| `GET /api/rank/session` | The open session for `source=owned`, or `null`. With a session: anchors, tallies, and either `pair: {candidate, anchor, tier}` or `needs_anchor: [tiers]` or `done: true`. |
| `POST /api/rank/session` | Create: `{anchors: {1: id, …, 5: id}}`. Writes seed placements, the anchors, the seed. 409 if one is open. |
| `GET /api/rank/proposal` | The five proposed anchors plus, per tier, the seeded films a swap may choose from. |
| `POST /api/rank/verdict` | `{film_id, anchor_tier, verdict}`. Appends the log row; places when the table says so. 409 if the pair is not the current one (stale page). |
| `POST /api/rank/pass` | `{film_id, candidate_unseen, anchor_unseen}`. Applies D9/D10. |
| `POST /api/rank/undo` | §4.4. |
| `PUT /api/rank/anchor` | `{tier, film_id}`. §4.5 rules. |
| `POST /api/rank/save` | `{name}`. Writes `film_list` + entries (§7), sets `list_slug`. |
| `PUT /api/films/<id>/unseen` | `{unseen: bool, note?}`. The drawer's toggle; same handler the pass path uses. |

## 7. The saved list

`film_list` row: slug `my-owned-tiers`, name from the owner, `curator = 'me'`, `published_year` = save year, `source_url` NULL, `ordered = 1`, `trust` untouched (default on insert, preserved on re-save exactly as `upsert_film_list` preserves it for imports). Entries: placed films ordered by tier then title, `rank` = line order, `rank_label` = `=<first line of the tier>` for every film in a tier of two or more, NULL for a tier of one. Unseen and unplaced films are absent. Re-saving deletes and rewrites the slug's entries.

**Slug ownership.** This is the first list with no `lists/<slug>.tsv`. Two guards, both refusing: `lists import` exits 2 on a slug whose `film_list` row was written by the ranker (a `film_list.origin` column would be the clean marker, but migration 022 is the ranker's, so instead the ranker's slugs are a fixed set in `domain/rank.py` — `my-owned-tiers` today — that `lists import` checks), and `POST /api/rank/save` refuses (409) if `lists/<slug>.tsv` exists.

## 8. Errors and edge cases

- **Stale page**: a verdict for a pair that is no longer current (another tab advanced it) is refused 409 and the page re-fetches state. No click is ever applied to the wrong film.
- **Empty slot**: no pair is served while any tier's anchor is NULL; the API says which.
- **Nothing left**: `done: true` when the queue is empty; the screen shows the tally and Save.
- **Second source**: `POST /api/rank/session` with a source other than `owned` is 400 in v1.
- **Film without a poster / overview**: placeholder and whatever fields exist.
- **Disposed films**: every query carries the `_NOT_DISPOSED` guard like every other film read.

## 9. Tests

- `tests/unit/test_rank.py`: the search table (every row of §4.1 plus the raise on an illegal sequence), the seed mapping, anchor proposal, queue derivation (seeded shuffle is stable for a seed; placed, unseen, anchors and deferrals excluded; deferred last), tie-label computation for the save.
- `tests/features/rank.feature` + `tests/step_defs/test_rank.py`: start a session from a seeded owned set; place a film in each of the five tiers; pass with nothing marked defers; pass with the candidate marked writes unseen; pass with the anchor marked empties the slot; anchor swap refused across tiers; undo reverts a placement, a deferral and a candidate-unseen; save writes tied labels; reopening resumes the same pair; a film marked unseen from the drawer leaves its placement.
- `tests/web/test_api.py`: every route in §6, including the 409s.
- `tests/web/test_dashboard.py`: one Playwright flow: open `/rank`, accept the proposal, click through one film to a tier by keyboard, mark the anchor unseen and pass, refill the slot, save, and see the list in the dashboard picker.

## 10. Out of scope

Ordering inside a tier (D6); sources other than `owned` (D7); writing `my_ratings`; re-running placements after an anchor swap; a session history or comparison viewer; an Elo or Bradley–Terry model; any change to keying, matching or sync.

## 11. Documentation

`CLAUDE.md` gains one bullet for the ranker (tables, the single writers, the slug guard, the `unseen` fact) and the `/rank` route in the web bullet; `docs/backlog.md` gets the follow-up "strict-order the top tier"; `.claude/rules/lists.md` gets the slug-ownership rule.
