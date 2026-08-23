# Vision & first principles

**Purpose, one sentence:** increase the value of my movie watching by getting the best content
matching my goals, tracking what I've watched, and continuously improving the input through an
iterative process — ultimately building real movie-critic and cinema-analysis expertise.

Feature seeds under this umbrella: [multiple-movie-services.md](multiple-movie-services.md),
[cinema-companion.md](cinema-companion.md), running list in [backlog.md](backlog.md).

## Divergent angles (2026-08-24 session)

Reframings to keep the system complete and tolerant of change:

1. **Catalog → curriculum.** If the goal is critic skill, the queue isn't a ranked list — it's
   a **syllabus**. Sequence films by movement / director / technique (film-school style:
   Ozu unit, French New Wave unit), with analysis prompts per film. Criterion's own curated
   collections are curricular gold we currently throw away during sync.
2. **Ratings → deliberate-practice loop.** Skill needs attempt → feedback → adjustment:
   **predict** before watching, **blind-analyze** after, **reveal** the critics, journal the
   delta ("what did the critics see that I missed — and in which dimension: cinematography,
   narrative, performance, context?"). Track improvement per dimension, not just overall.
3. **Skill made measurable.** Before the reveal, predict the Metascore/RT. Calibration over
   time (even a Brier-style score) is a crisp, honest metric for "am I becoming a better
   judge?" — separate from "do critics and I agree" (taste ≠ skill).
4. **Taste model → legible taste document.** Clustering that outputs weights is a black box;
   a critic knows *why*. The taste model should emit **falsifiable statements** ("you rate
   slow cinema +1.2 over baseline; you undervalue westerns") that I confirm, deny, and
   version like a document.
5. **Watching time is the scarce resource.** ~2 h/film, maybe 150 films/yr. Selection isn't
   "best movie" but **highest expected value per watched hour** across three goals:
   enjoyment, skill growth, canon coverage. A multi-objective queue, not a single sort.
6. **Critic implies output.** Practice means *writing*. Dictated notes grow into actual
   reviews (private blog is fine); agents critique my reviews against professional ones on a
   rubric (evidence, context, prose). The artifact loop is the practice loop.
7. **Movie-brain → attention-investment brain.** First-principles entity isn't "movie": it's
   *a work I invest attention in, with pre-signals (critics), my response, and my
   reflection*. YouTube videos (yt-brain), movies, maybe books/games later — same loop. The
   change-tolerant schema is works + sources + signals + my-responses; "movie" is one
   instance. This is the deep version of the yt-brain merge.
8. **Change tolerance = re-derivability.** Every external signal stored raw + timestamped
   (OMDb payloads and the scrape-archive rule already do this); every derived table
   rebuildable from archives. State you can re-derive is state you can refactor.

## Honest gap check against the purpose

- **Get the best content:** well covered by current discovery (services, scraping, TMDB,
  search) — the *selection-for-growth* framing (angles 1, 5) is not yet.
- **Track what I've watched:** ratings exist; notes are only seeded; predictions, deltas, and
  dimensions don't exist yet.
- **Iteratively improve:** thinnest leg today — the feedback loop (2, 3, 6) is the actual
  novel core of this project; everything else is plumbing for it.
