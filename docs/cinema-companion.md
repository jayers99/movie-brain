# Feature seed: Cinema Companion

**Status: idea collection — not for the current run.** The ask today is only that the current
design stays *amenable* to these capabilities (assessment at the bottom). Sibling of
[multiple-movie-services.md](multiple-movie-services.md); pointers live in [backlog.md](backlog.md).

## The use case, end to end

> I have the big long list of movies. I choose one I want to watch, I watch the **trailer**,
> and I'm like — yes, I want to watch this. I find **what service it's on**, pull it up, watch
> it, **rate it**, make a few **notes** to cue my memory — dictate what I thought of it, my
> analysis. Then I **compare my take against what notable critics thought**. Over time that's
> **building my cinema-critical skills**: an open-book analysis of what I think, checked
> against the critics, honed as I watch more movies.

## Capabilities to collect

### 1. Richer drawer: trailer + fuller metadata + critic links

- A **reliable trailer link** per movie (candidate: TMDB's videos endpoint returns official
  YouTube trailer keys; a YouTube search URL is the zero-dependency fallback).
- **More cast than OMDb's ~4 actors** — not every extra, but real coverage (candidate: TMDB
  credits). More metadata generally.
- **Critical analysis access**: could be as simple as sub-search links (Metacritic critic
  reviews — the planned scrape gives us each film's Metacritic slug — RogerEbert.com, etc.)
  or an agent-directed activity that gathers and summarizes critic takes. Shape TBD.

### 2. My notes & the criticism-skills loop

- Dictated/typed **notes per film**: memory cues + my analysis, alongside the 0–10 rating.
- A **compare step**: my open-book analysis vs. notable critics' takes on the same film —
  possibly agent-assisted (fetch critic reviews, contrast with my note, point at what I
  missed). The long-game: deliberate practice for film criticism.

### 3. Agentic access: skills and an MCP server

- **Claude skills that talk to this system** (query the list, record a rating+note, run the
  compare step).
- An **MCP server** exposing movie-brain to any agent. Doubles as a learning project — first
  MCP server, reps on agentic-workflow programming.

### 4. Power search bar (port from yt-brain)

- One text search bar with a **field-scoped syntax** — `actor: Orson Welles` returns every
  movie he acted in — working across any field.
- Three match modes per query: **exact**, **fuzzy**, and **semantic**.
- **Semantic search over descriptions/plots** the same way the YouTube brain clusters video
  descriptions: "a movie documenting a boy's childhood, growing up through his teenage years"
  → *Boyhood*.
- Prior art: [yt-brain](https://github.com/jayers99/yt-brain) already has this working well —
  port the syntax, UX, and implementation approach (see the convergence principle below).

### 5. Taste model / clustering (long term)

- Cluster liked vs. disliked films (genre, director, era, …) to **order the watch queue
  intelligently** — "you like this type of movie and not that one, this director and not that
  director."

## Is the current design amenable? (assessed 2026-08-24)

Mostly yes — the hexagonal shape is doing the work:

- **MCP server / skills**: the application layer's use cases are already the tool surface.
  `cli.py` (Typer) and `web/` (Flask) are parallel driving adapters; an MCP server is just a
  third. No redesign needed — this is the payoff of the ports-and-adapters rule.
- **Trailer/cast/metadata**: the `omdb` table is a per-provider cache keyed by `film_id` with
  a raw payload column — that pattern generalizes to a `tmdb` table (same tripwires, same
  film_key matching). Drawer is one template function; adding links is trivial.
- **Notes**: `my_ratings(film_id, score, rated_at)` extends naturally to a
  `my_notes(film_id, text, noted_at)` sibling — same repository pattern, migration is
  additive.
- **Critic comparison**: post-scrape we'll hold each film's Metacritic slug (see the scrape
  contract), so deep links to critic reviews are free; agent-directed analysis rides on the
  MCP server.
- **One strain to watch**: queryable metadata. Genres/runtime/full cast currently live only
  inside raw OMDb payload JSON. Clustering, and `actor:` searches, will want structured
  columns or join tables — additive migrations, but worth doing deliberately rather than
  parsing JSON at query time forever.
- ~~Second strain: the search bar breaks the all-client-side rule.~~ **Retracted after
  reading yt-brain (2026-08-24): it doesn't.** yt-brain keeps ALL filtering/sorting/virtual
  scrolling client-side over the full server-rendered row set — exactly movie-brain's
  pattern — and adds exactly one search endpoint, `GET /api/search`, which returns only
  **ranked ids + distances**; the browser intersects those with rows it already has. Porting
  the search bar is therefore additive, not an architecture change. Details in the sketch
  below.

## Search implementation sketch (from reading yt-brain, 2026-08-24)

How yt-brain actually does it (`src/yt_brain/web/dashboard.py`, `application/embed.py`,
`infrastructure/database.py` there):

- **One input box, 300 ms debounce** → `GET /api/search?q=&limit=&max_distance=` → response
  `{"results": [{"youtube_id", "distance"}, …]}` → JS keeps a match-Set + rank-Map and
  filters/re-orders the rows it already rendered. Client-side model preserved.
- **Field syntax is three regexes, quotes mandatory**: `title:"…"`, `desc:"…"`,
  `channel:"…"` plus bare `"quoted phrases"`; whatever remains after stripping filters is the
  semantic query. (movie-brain fields would be `title:`, `plot:`, `director:`, `actor:` —
  actor needs the structured-cast strain fixed first.) Special prefixes (`cluster:`,
  `category:`) are intercepted client-side and never hit the server.
- **Exact mode** = case-insensitive substring **post-filter** applied server-side to a 5×
  over-fetched candidate list from the vector search — filters never scan the whole corpus.
- **Semantic mode** = `sentence-transformers` `all-MiniLM-L6-v2` (384-dim, local CPU, no
  API), stored in a **sqlite-vec** `vec0` virtual table with `distance_metric=cosine` in the
  same SQLite file; embeddings computed offline by an `embed` CLI command (incremental,
  `--rebuild` for full), input text `title + "\n" + description`; model preloaded once at
  Flask app construction; results cut by a **user-facing max-distance slider** (default 0.6).
  Graceful degradation when sqlite-vec is missing (vec migrations skipped, LIKE fallback).
- **Fuzzy mode does not exist in yt-brain.** No rapidfuzz/difflib/FTS anywhere — the
  "approximate" feel comes from semantic distance plus exact quoted filters. yt-brain's own
  backlog item 26 ("short-query-search": hybrid substring/LIKE for short inputs, semantic for
  longer) is the planned answer. **Convergence action: if movie-brain builds fuzzy, build it
  as yt-brain's item 26 in both projects, same design.**
- **Clustering** (for the taste-model feature later): HDBSCAN over the same embeddings,
  cluster labels named by Claude Haiku (2–4 word labels, slugified, `cluster-NN` fallback
  without an API key), parent categories batched through Haiku too; incremental assignment =
  nearest centroid under a 0.5 distance threshold.
- **Kinship note:** yt-brain already mirrors movie-brain's skeleton — Typer CLI, Flask,
  SQLite in `~/.config/<app>/`, `migrations/NNN_*.sql` applied by `init_db`, pytest-bdd +
  Playwright. The merge-someday idea is very plausible. Main divergence: movie-brain's
  stricter hexagonal layering (yt-brain's web layer holds inline SQL; no repository port) —
  when porting, keep movie-brain's Repository discipline while copying yt-brain's behavior.

## Convergence principle: movie-brain ↔ yt-brain (2026-08-24)

[yt-brain](https://github.com/jayers99/yt-brain) is the sibling project (Python, considerable
invested effort, works well). **Keep the two architecturally close:**

- When porting a capability (search first), follow yt-brain's implementation and
  client/server decomposition rather than inventing a movie-brain-specific variant.
- When movie-brain wants to diverge, **stop and discuss**: is the feature also appropriate
  for yt-brain, so the two stay in sync?
- Long-term direction: the projects may **merge into one "video brain"** — YouTube videos and
  movies aren't that different. (Better name TBD.)

## Open questions

- [ ] Trailer source of truth: TMDB videos vs. a constructed YouTube search link — how
      reliable is TMDB's trailer coverage on older/Criterion-ish films?
- [ ] Notes UX: dictation lands where — drawer textarea, CLI, or via the MCP server from a
      voice workflow?
- [ ] What does the critic-comparison step actually read — Metacritic critic reviews
      (per-review text is paywalled-ish/scrapy), RogerEbert, or an agent's web search?
- [ ] MCP server scope v1: read-only queries first, or rating/note writes too?
- [ ] Clustering: feature set and where it runs (SQL + a small script vs. an agent analysis
      over an export).
