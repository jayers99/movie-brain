# Criterion relaunch — handoff into Plan B

*2026-10-02. From the session that built Plan A and ran rollout steps 1–2. Read beside the spec (`../specs/2026-10-01-criterion-relaunch-design.md`) before writing Plan B; where this page and the spec's measured numbers disagree, this page is newer (a full live run, not a sample).*

## State

- Plan A built on `feature/STORY-50-criterion-relaunch`, commits `3e5fd90..700938c`, not merged to main, not pushed. Full suite 1985 passed; `mypy src` shows only main's 3 pre-existing errors.
- Rollout step 1 done: `<config_dir>/backups/pre-criterion-bridge-2026-10-02.db` (5,403 films, 3,095 old Criterion links, schema 32, integrity ok).
- Rollout step 2 done: bridge dry run 2026-10-02, exit 0. Observation file `<config_dir>/criterion-bridge.jsonl` (3,095 lines), summary in `<config_dir>/criterion-bridge-dryrun-2026-10-02.log`. Nothing written to the database.
- `--apply` (step 3) still waits for Plans B and C and gap check point C (spec §8). By then the answers are older than 24 hours, so `--apply` re-asks every unsettled link (~30 min) before writing.

## The dry run, measured

| Outcome | Count |
|---|---|
| film (forwards to `/films/<mediaid>/…`) | 2,836 |
| gone (404) | 250 |
| supplement | 9 |
| clash (`held`) | 0 |
| same film | 0 |
| retry | 0 |
| films binding two different mediaids | 3 |

Drift: 214 films (99 year · 105 title · 10 both). The 293 links probed on 2026-10-01 (`old-url-redirects.tsv`) all answered identically on 2026-10-02.

## Where the spec's numbers are superseded

- **D13 "68 old URLs now 404"** came from the 293-link sample. The full run has **250**; 241 films are left with no working link (49 of them rated, 0 watchlisted, 0 viewed — live DB read-only, 2026-10-02). Plan B's first-walk departure expectation must use these numbers.
- **D13 / rollout step 3: "the bridge records the series mediaid on the first film of each set and queues the rest as `id-conflict`"** — no longer true. All 15 multi-part episode films (Agnès de ci de là Varda #1368–1372, Four Journeys into Mystic Time #1579–1582, Lone Wolf and Cub #1720, #2067–2071) now answer **404**. No `id-conflict` rows will exist; rollout step 3's "12 dismissals" disappears. They still depart on the first walk, as D13 intends.
- **Plan A Review Focus 5 / D3 "12 films whose two old URLs land on the same mediaid (e.g. Eve's Bayou)"** — no longer true. Of the 12 films holding two links, eight keep one working link (the other 404s), Betty Blue #1240 loses both, and three bind **two different** mediaids:
  - Eve's Bayou #1150 — `6tfyfj2f` (theatrical) and `gOkSarah` (director's cut)
  - Dr. Dolittle #1285 — `YM0kT8PG` (English) and `BgC4kIqZ` (German)
  - Darwin #759 — `9DlZ3IcB` (`darwin-what`) and `HjxbRX53` (`darwin-what-what`) — **open for the owner**: confirm these are one work before `--apply`.
- **The Beast:** the old `the-beast` link now forwards to a supplement. The spec's two mediaids for The Beast 2023 (`1n2wLfer`, `7G9Sr5tL`) therefore arrive through D5 as unknown ids, not through the bridge.

## What Plan B must handle because of this

1. **One film, two listed mediaids** (the three films above, if both ids stay in the catalog): the walk sees two catalog items mapping to ONE film. `record_criterion_walk` must write ONE criterion listing for that film (listings are per film × source), both claims, and must not count the second item as an arrival. Add a scenario (Eve's Bayou).
2. **Departures are about 241, not ~115.** Rated departed films stay visible as departed (no data loss), but the owner should hear the number before the first walk. Some rejoin through D5 when the resolver keys a new mediaid to them (spec names Grey Gardens, Mirror, Being Frank, Factory, Fanny and Alexander).
3. **Plan A's adapter raises `CriterionError` on every malformed answer** (non-JSON 200, a catalog item missing `mediaid`/`title`, a bad `duration`, an empty JW `playlist`) — a deliberate deviation from the plan's code. Plan B's walk catches only `CriterionError` and writes nothing for Criterion; that contract now holds.
4. **`fetch_leaving` raises when a dated leaving page yields no playlist id** (a markup change keeps last-known labels; only "home page loaded, no dated link" clears them). D7's soft-failure path should treat this like any other leaving failure.
5. **`fetch_media` returns `None` only on a JW 404**; an empty playlist on a 200 now raises.

## Parked findings for Plan B (from Plan A's reviews)

- Home page and dated leaving page (criterionchannel.com) are paced on the JW 0.25 s pacer; site pages should use the site's pace.
- A film on two dated leaving pages takes whichever page sorts last — decide deliberately (earliest date is the useful one).
- A leaving playlist above 500 items is silently truncated (`total` never checked).
- `assert label is not None` sits in production code in `fetch_leaving`.
- A catalog JSON body that is a list (not an object) raises `AttributeError`, not `CriterionError`.
- `thumbprint backfill` reads `listings.url`; after `--apply` that is the new `/films/<mediaid>/<slug>` form, a third claim-value shape — note it in `.claude/rules/thumbprint.md` with Plan B's other rule updates.
- Bridge: a tombstoned film is its own canonical id, so a mediaid could bind to one (0 such old links live); no progress output during the 30-minute run; `asked_at` is the run start time.

## Rollout reminders

- Report only the FIRST fresh dry run: a later dry run reuses saved answers and prints stale counts.
- Every live step stays one at a time on the owner's yes (backup → apply → dated copy → sync).
