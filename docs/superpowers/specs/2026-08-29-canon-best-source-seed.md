# Seed prompt — closing the "best source" design

Paste everything below the line into a fresh session. It kicks off brainstorming on the two open questions that need the owner in the room (§7.1 and §7.2 of the design), and carries the facts needed to settle the other three without further research.

---

We are finishing the design of a feature in `~/code/movie-brain`. **Read `docs/superpowers/specs/2026-08-29-canon-best-source-design.md` first, all of it, before saying anything.** Then read `CLAUDE.md`, `.claude/rules/lists.md` and `.claude/rules/thumbprint.md`.

**Do not write code this session.** The design is deliberately incomplete: §1 records seven owner decisions (C1-C7) that are settled and must not be relitigated, §2 records measurements already taken against live TMDB that must not be re-derived, and §7 lists five open questions. Your job is to close all five — two by asking me, three by reasoning from what the spec already contains — and then write the amended spec. Use the brainstorming skill; ask questions one at a time.

## The two questions that need me

**Q1 — is the product per-film, portfolio, or both?** *"For Grand Illusion, watch it here, because…"* attached to each canon film, versus *"these subscriptions cover N of your 139 unowned canon films for $X; Kanopy is free and adds 24."* They share data but are different features, and "best" means different things: a single winner per film versus coverage per dollar across a set, where a film available in five places is *less* interesting than one available in exactly one. Ask me this first. It determines whether this is a per-film enrichment that runs continuously or an analysis I run a few times a year.

**Q2 — how is quality (C7) actually measured?** I said resolution, bitrate and streaming quality matter. TMDB's watch-provider data carries **none** of that — it returns only provider id, name, logo and display priority. Before asking me anything, go and find out what is actually obtainable: whether JustWatch, the provider's own API, or any other source exposes per-film-per-service quality for a US catalogue, and at what cost in calls. Then bring me the options rather than the question. If the honest answer is "no machine-readable source exists", say so and propose the fallback — a per-service quality constant I set by hand, which is probably fine given a service's quality is fairly uniform.

## The three you can close yourself, with the facts already in hand

**Q3 — how does the Apple TV app preference (C6) enter the ranking?** C6 says an Apple TV app is preferred but explicitly not a veto (*"if it's available nowhere else, I'm fine with that option"*). Of the services that matter to my canon, Criterion, Kanopy, Tubi, Fawesome, HBO Max and Prime all have Apple TV apps. Propose the simplest thing that honours a preference without inventing precision I did not ask for.

**Q4 — stored per film, or computed on read?** The relevant facts: the catalogue is 4,735 films of which the canon is 200; provider data already lands in the `listings` table via the weekly TMDB refresh, which is gated by `meta.tmdb_providers_refreshed_at` with `REFRESH_DAYS = 7` and a `FIRST_CHECK_BATCH = 500` pass that runs ahead of the gate for never-checked films; `listings` currently holds ~6,054 rows. Note that §4's proposal — record every provider from `flatrate` + `free` + `ads` — will grow that table substantially, and that `_SERVICES_SQL` already reads it in one query for the whole view.

**Q5 — refresh cadence.** Syncs are manual by my deliberate choice; there is no launchd agent and you must never propose one. The existing weekly gate already exists and is respected by `sync`.

## What is already true, so you do not rebuild it

Merged to `main` earlier today: `repair imdb` (3,571 IMDb ids backfilled live, zero years moved), both 1992 Sight & Sound polls imported, `canon_score` and the `acquire` chip in `domain/filters.py` mirrored in `static/app.js`, and a fix to `record_tmdb_match` so a missing year is filled from TMDB regardless of source (120 years filled live). The live DB is **schema v16** and migration **017 is unwritten** — §4's registry work would be the first to claim it.

Two pending reversals that belong in the same conversation, both recorded in the design: the `acquire` chip's gate excludes rated films and C5 says they belong, and the chip is named "Worth buying" while checking nothing about buyability. D1 of `docs/superpowers/specs/2026-08-29-on-sale-canon-acquisition-design.md` has been reversed by me — streamable films should appear, badged — measured at 480 candidates rather than 263.

## How I work

Short, scannable answers; lead with the conclusion. Push back where I am wrong rather than agreeing. Never run a command that writes to `~/.config/movie-brain/movie-brain.db` without rehearsing on a scratch copy with `MOVIE_BRAIN_CONFIG_DIR` set and showing me the result first. Markdown is never hard-wrapped. Open documents with `open -a Typora`. Gate baselines: `thumbprint_benchmark.py --assert` at **n=573 / WRONG=0 / 92.0% over 526**, and `matching_benchmark.py --assert-dominance` with the apple review ceiling at **6.0** (raised deliberately — the benchmark reads my live catalogue, so correcting a missing year raises review% rather than lowering it).

Finish by amending `docs/superpowers/specs/2026-08-29-canon-best-source-design.md` in place: fold the five answers in, delete §7, and change the status line to say it is ready to plan.
