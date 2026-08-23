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

Items 1 and 2 have grown into a feature of their own — discovery lives in [multiple-movie-services.md](multiple-movie-services.md); items 4–7 in [cinema-companion.md](cinema-companion.md).
