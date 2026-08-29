# `repair links --film ID --tt ttNNN` — re-keying a confidently-wrong film

**Date:** 2026-08-29 · **Status:** owner-chosen (option 2 of three), ready to plan. Small increment on the existing repair surface; the thumbprint contract in `.claude/rules/matching.md` and `.claude/rules/thumbprint.md` stays binding.

## 1. The gap, and the film that found it

Every repair verb keys off an **inconsistency**. `repair disagreements` fires when OMDb's `imdbID` ≠ TMDB's `imdb_id`; `repair nomatch` works open `no-match` rows; `repair links` finds links whose stored TMDB title disagrees with the film's. All of them assume the wrongness announces itself somewhere.

Film **#493** does not. It is Criterion's *One Way or Another* (Sara Gómez, Cuba, 1977) — title, year and director all correct — keyed to `imdb tt0075335` / `tmdb 47096`, which are **Elio Petri's *Todo modo* (Italy, 1976)**. The two ids agree with each other perfectly, because Petri's film is distributed in English as *One Way or Another*: an exact English-title collision one year apart. The row is not half-broken; it is cleanly keyed to the wrong work, and only the OMDb payload (ratings, plot, poster, Metascore — all Todo modo's) betrays it.

Correct identity, established 2026-08-29: `imdb tt0075915` / `tmdb 162505` — *One Way or Another* / *De cierta manera*, Sara Gómez, Cuba.

**Why the existing route cannot fix it.** `repair links --film 493 --apply` clears the TMDB link but leaves the wrong IMDb id, and the film then falls out of `films_needing_tmdb_match` **and** `nomatch_worklist` — verified on a scratch copy. Nothing will ever queue a review row for it, so `review resolve --tt`, the only reachable caller of `key_film`, has nothing to act on. Clearing the link **strands** the film rather than repairing it.

## 2. What this adds

```
movie-brain repair links --film ID --tt ttNNNNNNN [--apply]
```

A human who knows the right IMDb id re-keys one film through `key_film` — the project's single identity write path, unchanged. Dry run by default, like every other verb here.

Rehearsed on a copy of the live database, `key_film(repo, tmdb, 493, "tt0075915", today)` alone performs the whole repair:

```
BEFORE  imdb=tt0075335  tmdb=47096   year=1977
        -> status=keyed  tmdb_id=162505  detail='matched'
AFTER   imdb=tt0075915  tmdb=162505  year=1977
```

`set_external_id` replaces the value for a key authority (migration 012 policy), so **both** ids swap in one call; `mark_omdb_refresh` fires because the stored OMDb `imdbID` differs, so the next sync refetches the correct record; and the year is untouched because a film with a Criterion listing is not commerce-created. **No prior link-clearing step is needed, and the verb must not add one** — clearing first is what strands the film.

## 3. Behaviour

| condition | outcome |
|---|---|
| `--tt` without `--film` | error, exit 2 — this is a single-film repair by definition |
| `--tt` malformed (not `tt\d+`) | error, exit 2 |
| dry run (no `--apply`) | print the film's current `imdb`/`tmdb`, the proposed pair (resolving the tt through `find_by_imdb`), and what would change. **Write nothing.** |
| `--apply`, `key_film` returns `keyed`/`unlinked` | report the before/after ids and that an OMDb refetch is queued when the stored id differed |
| `key_film` returns `held` | report which film holds the id and exit non-zero — never steal an id from another film |
| `key_film` returns `error` | report the TMDB failure and exit non-zero, film untouched |
| film id unknown, tombstoned, or merged away | error, exit 2. `--film` is canonicalized first, as `review resolve` already does |

`key_film`'s own contract is unchanged and carries the safety: every holder check runs **before** any write, so `held` and `error` leave the film untouched; a post-`record_tmdb_match` failure logs `[partial]` and raises, which is the established loud-stop rule.

## 4. What this is not

Not a search — the human supplies the id. Not a sweep: it repairs exactly the film named. It does **not** look for other films in this state, and this spec does not propose that (the data-audit phase is parked by the owner). Not a new write path — `key_film` remains the only one.

## 5. Gates

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. This touches neither `domain/thumbprint.py` nor the fixture, so the thumbprint gate must not move. The eval CSV is never written by this verb — it is a human's standing decision about one film, not resolver ground truth, and `ratify` is reached only through `review resolve`.
