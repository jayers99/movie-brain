# Backlog

Running list of ideas for movie-brain. Add new items at the bottom; strike or check them off when done.

1. [ ] **Import my purchased iTunes movies** into the database as an owned-films source, then use ownership to filter the streaming listings — a streaming movie I already own should not show up in the list.
2. [ ] **Scrape Metacritic's streaming browse** — Metacritic can filter top-rated movies by streaming service, and the services I subscribe to (Prime, Max, and a few others) are all covered there, returning roughly 10,200 titles right now. Scrape all of those movie titles to bring the other streaming services' catalogs into the database.
3. [ ] **CheapCharts price-watch integration** — I use [cheapcharts.com](https://www.cheapcharts.com), which alerts me when a movie drops below a set price to buy on the iTunes Store. Add a button on a film that adds it to my CheapCharts price watch list, so alerts come without leaving the app. (Spike: does CheapCharts have an API or watch-list endpoint, or does this need an authenticated form/deep link?)

4. [ ] **Richer drawer** — reliable trailer link, fuller cast/metadata (beyond OMDb's ~4 actors), critic-review links. Seeded in [cinema-companion.md](cinema-companion.md).
5. [ ] **My notes + criticism-skills loop** — dictated notes per film, then compare my analysis against notable critics to build cinema-critical skills. Seeded in [cinema-companion.md](cinema-companion.md).
6. [ ] **Agentic access** — Claude skills for this system and an MCP server (also a first-MCP-server learning project). Seeded in [cinema-companion.md](cinema-companion.md).
7. [ ] **Taste clustering** — model liked/disliked films (genre, director, …) to order the watch queue intelligently. Seeded in [cinema-companion.md](cinema-companion.md).
8. [ ] **Power search bar** — field-scoped syntax (`actor: Orson Welles`) with exact / fuzzy / semantic modes, semantic plot search included ("boy grows up through his teenage years" → *Boyhood*); port the working syntax/UX from my YouTube brain page. Seeded in [cinema-companion.md](cinema-companion.md).

9. [x] **"Needs revisit" flag in the drawer** — a user-set mark on a film whose facts look
   wrong (wrong year, misidentified — e.g. the Metropolis-anime and Rambo/Vahşi Kan wrong
   matches found 2026-08-24) or that otherwise needs factual work. Toggle lives in the
   drawer pane next to the watchlist toggle and follows the watchlist pattern: user-response
   data, its own table (film_id + marked_on + optional free-text note), drawer toggle is the
   only writer, never touched by sync/importers. Surface as a filter chip so flagged films
   are one click away, and feed the queue into M3's repair/review-resolution CLI so a human
   pass can drain it (resolving clears the flag). Optional nicety: pre-fill the note with
   what looks wrong ("year suspect", "wrong film"). — shipped in M3 (2026-08-24)

10. [ ] **Curated top-N lists** — import named ranked lists (top 100 / top N) and show in
    the drawer, per list, whether the film is on it and at what rank. Data model on the
    external-authority pattern: a `lists` registry (slug PK, name, source URL, size, ordered
    or unordered) plus `list_entries` (list_slug + film_id + rank + raw title/year as listed),
    matched through the shared `match_candidates` core (never a new matcher); unmatched or
    ambiguous entries queue to `match_review` under the list's authority so the human pass
    resolves them, and entries with no film in the DB become discovery films via the Mode-B
    promotion path. Drawer shows a "Lists" row of `<list name> #<rank>` badges; later, a
    filter chip / sort per list. First list to build: **Cahiers du Cinéma's 100 Ideal
    Cinematheque Films** (Cahiers' 2008 "100 films pour une cinémathèque idéale").

Items 1 and 2 have grown into a feature of their own — discovery lives in [multiple-movie-services.md](multiple-movie-services.md); items 4–7 in [cinema-companion.md](cinema-companion.md).
