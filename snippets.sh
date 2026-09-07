# movie-brain snippets — copy-paste, or run a block with: bash snippets.sh
# Ordered by how often each is needed. Anything that writes is dry-run by default unless it
# says --apply; the review verbs and `lists trust` write immediately.


# ── Daily ────────────────────────────────────────────────────────────────────────────────────

# The dashboard (http://localhost:5556)
uv run movie-brain dashboard


# ── After adding films, or a week of drift ───────────────────────────────────────────────────
# Order matters: sync keys new films and fetches their OMDb record + availability; enrich needs
# the TMDB id that keying wrote; embed needs the overview/plot text that enrich (and OMDb) wrote.
# None of the three is run by any other verb — sync never enriches or embeds.

# Catalog refresh + OMDb by IMDb id + weekly TMDB availability
uv run movie-brain sync

# TMDB cast/crew/keywords/overview for films holding a TMDB id and no stamp
uv run movie-brain enrich credits --apply

# Vectors for the semantic search stage (needs `uv sync --extra semantic`)
uv run movie-brain embed --apply

# What the catalog holds now (films, ratings, lists, embeddings, prose)
uv run movie-brain status


# ── Adding a curated list ────────────────────────────────────────────────────────────────────
# Rehearse against a COPY first: cp the DB into a scratch dir with the two key files and set
# MOVIE_BRAIN_CONFIG_DIR=<dir> on every command below. Read the whole scorecard, then go live.

# Phase 1: link what the catalog holds, queue the rest — never creates a film (dry run without --apply)
uv run movie-brain lists import lists/<slug>.tsv --apply

# Phase 2: mint the films the list still needs, born keyed — the only creating path
uv run movie-brain lists create <slug> --apply --yes

# Weight the list (0 legal: visible, scores nothing). Bare: show every list's trust
uv run movie-brain lists trust <slug> N
uv run movie-brain lists trust

# Renaming a list = edit its `# name:` header, then re-import; links are untouched
uv run movie-brain lists import lists/<slug>.tsv --apply


# ── Draining the review queue ────────────────────────────────────────────────────────────────

# What's open, optionally by authority (list, tmdb, metacritic, apple-tv)
uv run movie-brain review list
uv run movie-brain review list --authority list

# A list entry: link to an existing film / create from the listed title / never mind
# (when an ambiguous row's A/B/C shows a film the catalog holds, use --film, NOT --create)
uv run movie-brain review resolve ID --film FILM_ID
uv run movie-brain review resolve ID --create
uv run movie-brain review resolve ID --dismiss

# A film that queued A/B/C candidates after sync: pick one, or key it by IMDb id outright
uv run movie-brain review resolve ID --pick A
uv run movie-brain review resolve ID --tt tt0000000

# A created film that duplicates one the catalog already held (no shared ids, so `repair dupes`
# can't see it): give it the twin's year to force a year-collision row, then merge INTO the twin
uv run movie-brain repair years FILM_ID YEAR --apply
uv run movie-brain review resolve COLLISION_ID --film TWIN_ID

# Films flagged "needs revisit" in the drawer
uv run movie-brain review revisits


# ── Occasional ───────────────────────────────────────────────────────────────────────────────

# Mark/create owned films from the Apple TV library (macOS AppleScript export; never in sync)
uv run movie-brain owned import

# Direct CheapCharts product links (stops itself on a 429; nothing lost, re-run later)
uv run movie-brain cheapcharts resolve --apply

# Extend the Metacritic browse archive (polite, checkpointed), then match it offline
uv run movie-brain metacritic crawl --pages 42
uv run movie-brain metacritic match

# Show/set the Mode-B top-N that nightly sync promotes into the catalog
uv run movie-brain metacritic dial
uv run movie-brain metacritic dial N

# Export everything list_views knows as CSV
uv run movie-brain export csv ~/Desktop/movie-brain.csv


# ── After pulling code ───────────────────────────────────────────────────────────────────────

# Deps (a bare `uv sync` REMOVES the semantic extra — always include it)
uv sync --extra semantic

# Schema: list pending migrations, then apply (backs up first)
uv run movie-brain migrate
uv run movie-brain migrate --apply

# Tests, lint, types
uv run pytest
uv run ruff check . && uv run mypy


# ── Rare: identity repair (read the scorecard, then --apply) ────────────────────────────────

# Audit norm-title + id-conflict duplicate groups; --apply merges TWIN groups only
uv run movie-brain repair dupes

# Re-validate stored TMDB links; --film audits one; --tt re-keys one film outright
uv run movie-brain repair links
uv run movie-brain repair links --film FILM_ID --tt tt0000000

# Fill IMDb ids TMDB already publishes
uv run movie-brain repair imdb

# Rerun open TMDB no-match films through the resolver
uv run movie-brain repair nomatch

# Read-only consistency checks → audit_flags (a thermometer, not a to-do list)
uv run movie-brain audit run
