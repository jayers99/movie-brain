# Curated top-N lists — seed (backlog item 10)

**Date:** 2026-08-28 · **Status:** brainstormed, four decisions locked by the owner, design PROPOSED but not yet ratified. No code written, no schema changed. Next session takes this through spec → plan → implementation.

**Origin:** `docs/backlog.md` item 10, which already sketched a data model and named Cahiers du Cinéma as the first list. The 2026-08-25 thumbprint handoff also anticipated this: *"Many more lists are coming: individual critics' top-100s, cult classics…"*

## 1. What the owner asked for, in their words

> "I want to be able to collect top lists — Top 100, Top 10 by different people, different organizations, of different types of film. Examples: top 20 cult classics, top 10 action films, top 5 kung fu films. Just all these definitive lists of top movies by genre. I want to import a bunch of them. Once they're in the database in a way that they can be reused for different movies: if I go into a drawer, it'll say 'Oh! That's on this top 100 list' and give the name of the list. Then once I determine which lists are really good, I might want to change my GUI just to filter out and display those on the list and put them in the right order of the list."

First list: **Cahiers du Cinéma's 100** — `https://www.filmdetail.com/2008/11/23/cahiers-du-cinemas-100-greatest-films/`. The blog titles it "100 Greatest Films"; it is Cahiers' 2008 *"100 films pour une cinémathèque idéale"* (100 Films for an Ideal Cinematheque). Prefer the real name in the registry.

## 2. Why this is much smaller than it looks

T5 (merged 2026-08-28) already built every hard part. A list entry is just another ingester's claim about a work, and the resolver already turns *title + director* into an IMDb id and lands it on the film that already holds it. Reuse, don't rebuild:

- `domain/thumbprint.resolve(query, candidates)` — the evidence-scoring resolver, 0 wrong on 526 eval cases.
- `application/keying.key_film(...)` — the ONE identity write path; every holder check runs before any write.
- `infrastructure/thumbprint_fetch.session_fetcher(config_dir, tmdb, omdb)` — the candidate source; never writes the eval fixture.
- `application/owned.py` and `application/metacritic.py::promote_top_n` — two worked precedents of "resolve first, land on the existing holder, else create and key". **Read `owned.py` lines ~105-130 before designing the import loop; the list importer is a third sibling of those two and should look like them.**
- `match_review` + `review resolve --pick/--tt/--none` — the existing human drain for ambiguous entries.

## 3. Evidence gathered (read-only probe, 2026-08-28)

Naive normalized-title matching of the 100 Cahiers entries against the live 4,666-film catalog: **67 hit, 33 miss.** But the misses are overwhelmingly *alternate titles*, not absent films — `À bout de souffle` (held as *Breathless*), `La Grande Illusion` (*Grand Illusion*), `The Seven Samurai` (*Seven Samurai*), `Hiroshima, My Love` (*Hiroshima mon amour*), `Tales of Ugetsu` (*Ugetsu*), `The Adventure` (*L'Avventura*), `Diamond Earrings (Madame de…)` (*The Earrings of Madame de…*).

**So 67% is a floor, not the expected rate.** The resolver keys on IMDb id via director-corroborated search, which is exactly the signal that fixes these. Expect the true "genuinely absent" count to be well under 33 — but measure it on the dry run rather than trusting this estimate.

The list has **no years**, which is a feature here rather than a problem: the resolver's `Query` takes an optional year, a wrong year actively misleads it, and director corroboration is its strongest rule (memo §3 verdict order, rule 2). Parenthetical original titles (`The Rules of the Game (La Règle du jeu)`) already parse as alt-titles via `parse_title`'s `_ALT` rule and are used for matching.

## 4. Decisions LOCKED by the owner (do not relitigate)

| # | Question | Decision |
|---|---|---|
| D1 | How does a list get from a web page into the DB? | **Claude extracts → checked-in normalized file.** For each list, Claude fetches the page and writes `lists/<slug>.tsv`; a CLI verb imports that file. No scraper code, no per-site selectors. Adding a list = one short conversation + a committed, diffable file. Same habit as `scripts/eval/*.csv`. |
| D2 | An entry resolves to a real film not in the DB at all | **Create it as a discovery film**, keyed by the resolver, exactly as Mode-B promotion does. The dashboard's default `reachable` scope already hides unreachable discovery films, so normal browsing stays clean while a list filter can later show the complete 100 including the unwatchable ones. Serves the vision's "canon coverage". |
| D3 | v1 scope | **Import + drawer badges.** Filtering and rank-order sorting are a deliberate follow-on, once the owner has several lists and knows which they trust. |
| D4 | What the registry records per list | **name, curator, published year, source URL, ordered flag.** Enough to badge honestly ("Cahiers du Cinéma 2008 #3") and to tell two Sight & Sound polls apart. **No tags/taxonomy yet** — add them when there are enough lists to group. |

## 5. Design PROPOSED (owner has not ratified this section — confirm before speccing)

### Data model — migration 013

```
film_list        slug PK · name · curator · published_year · source_url · ordered · imported_at
film_list_entry  list_slug · rank · film_id (nullable) · title_listed · director_listed
                 UNIQUE(list_slug, rank)
```

Entries keep `title_listed` / `director_listed` verbatim forever — a list is a historical artifact, so what the curator actually wrote survives matching.

**Naming:** the backlog says `lists` / `list_entries`. This proposes `film_list` / `film_list_entry` instead, because `Repository.list_views()` already exists and means something else entirely — `repo.lists()` sitting beside `repo.list_views()` reads badly. The owner may overrule.

### Import — `movie-brain lists import lists/<slug>.tsv [--apply]`

Dry-run by default, like every other verb in this project. The file is self-describing, one per list:

```
# slug: cahiers-100
# name: 100 Films for an Ideal Cinematheque
# curator: Cahiers du Cinéma
# published: 2008
# source: https://www.filmdetail.com/2008/11/23/cahiers-du-cinemas-100-greatest-films/
# ordered: true
1	Citizen Kane	Orson Welles
```

Per entry: `make_query(title_listed, None, "list", director=director_listed)` → `resolve()` → then

| verdict | action |
|---|---|
| `match`, a film already holds that imdb (or tmdb) id | link the entry to that film — **no new film minted** |
| `match`, nobody holds it | `create_film` + `key_film` — born keyed, exactly like Mode-B promotion |
| `review` | store the entry with `film_id` NULL and queue ONE durable `match_review` row under authority `list`, drained with the existing `review resolve --pick/--tt/--none` |

Every linked film also gets a `claim` (authority `list`, value `<slug>#<rank>`, `title_ingested` = the listed title), consistent with T5's claims-at-ingest, so a later re-resolution sees what the list actually said. Re-import is idempotent: ranks update, nothing duplicates, no film is created twice.

Auto matches are **never** ratified into `scripts/eval/thumbprint_eval_v1.csv` — same rule as `repair nomatch`, so the gate cannot score itself. Human `review resolve` verdicts ratify as they already do.

### Read model + drawer

`FilmView.lists: list[dict]` = `[{slug, name, curator, published, rank}]`, fetched per film the same way `services` already is (a separate keyed query, not a join into `_VIEW_SQL` — a film on five lists must not fan out into five view rows). Drawer gains one line beside "Also streaming on:":

```
On lists:  Cahiers du Cinéma 2008 #3
```

### Testing

Unit tests for the TSV header/row parser (odd titles, curly apostrophes, the `#` header block). pytest-bdd scenarios for all four import outcomes plus idempotence and the dry-run-writes-nothing case. A Playwright assertion that the drawer's Lists row renders. Follow the existing `PoolFetcher`-style injected fake rather than HTTP mocks for the resolver.

## 6. Out of scope for v1

Filter chip and rank-order sort; list tags/taxonomy; re-fetching a list from its source URL; any second list beyond Cahiers (the mechanism is what is being proven).

## 7. Risks to watch

- **Film creation compounding.** ~30 new discovery films per list, across "a bunch of them", adds up. The dry run reports the real creation count before anything is written — check it against the §3 estimate and stop if it is wildly higher, since that would mean resolution is underperforming.
- **`owned import` is now slow** (10+ min for 870 titles) because it resolves every title. A 100-entry list is fine; a 1,000-entry list would not be. Note the cost before importing anything large.
- **`--none` discipline.** A canon film the indexes genuinely lack is a real film the index merely misses — per the project rule, that is NOT a `--none` candidate. Leave such entries unlinked rather than marking them verified-unkeyed.

## 8. Gates (unchanged from T5)

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526** as of 2026-08-28) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Never hand-edit the eval CSV or the fixture.

## Appendix — the Cahiers 100, extracted 2026-08-28

Captured here so the next session need not re-fetch. Format is `rank<TAB>title<TAB>director`, verbatim from the source page including its typos (`Howard Hawkes` at 12, `Joseph Mankiewitz` at 31, `Ernst Shoedsack` at 55 — leave them as the list wrote them; the resolver matches on title and the director is corroboration, not an exact key).

```
1	Citizen Kane	Orson Welles
2	The Night of the Hunter	Charles Laughton
3	The Rules of the Game (La Règle du jeu)	Jean Renoir
4	Sunrise	Friedrich Wilhelm Murnau
5	L'Atalante	Jean Vigo
6	M	Fritz Lang
7	Singin' in the Rain	Stanley Donen & Gene Kelly
8	Vertigo	Alfred Hitchcock
9	Children of Paradise (Les Enfants du Paradis)	Marcel Carné
10	The Searchers	John Ford
11	Greed	Erich von Stroheim
12	Rio Bravo	Howard Hawkes
13	To Be or Not to Be	Ernst Lubitsch
14	Tokyo Story	Yasujiro Ozu
15	Contempt (Le Mépris)	Jean-Luc Godard
16	Tales of Ugetsu (Ugetsu monogatari)	Kenji Mizoguchi
17	City Lights	Charlie Chaplin
18	The General	Buster Keaton
19	Nosferatu the Vampire	Friedrich Wilhelm Murnau
20	The Music Room	Satyajit Ray
21	Freaks	Tod Browning
22	Johnny Guitar	Nicholas Ray
23	The Mother and the Whore (La Maman et la Putain)	Jean Eustache
24	The Great Dictator	Charlie Chaplin
25	The Leopard (Le Guépard)	Luchino Visconti
26	Hiroshima, My Love	Alain Resnais
27	The Box of Pandora (Loulou)	Georg Wilhelm Pabst
28	North by Northwest	Alfred Hitchcock
29	Pickpocket	Robert Bresson
30	Golden Helmet (Casque d'or)	Jacques Becker
31	The Barefoot Contessa	Joseph Mankiewitz
32	Moonfleet	Fritz Lang
33	Diamond Earrings (Madame de…)	Max Ophüls
34	Pleasure	Max Ophüls
35	The Deer Hunter	Michael Cimino
36	The Adventure	Michelangelo Antonioni
37	Battleship Potemkin	Sergei M. Eisenstein
38	Notorious	Alfred Hitchcock
39	Ivan the Terrible	Sergei M. Eisenstein
40	The Godfather	Francis Ford Coppola
41	Touch of Evil	Orson Welles
42	The Wind	Victor Sjöström
43	2001: A Space Odyssey	Stanley Kubrick
44	Fanny and Alexander	Ingmar Bergman
45	The Crowd	King Vidor
46	8 1/2	Federico Fellini
47	La Jetée	Chris Marker
48	Pierrot le Fou	Jean-Luc Godard
49	Confessions of a Cheat (Le Roman d'un tricheur)	Sacha Guitry
50	Amarcord	Federico Fellini
51	Beauty and the Beast (La Belle et la Bête)	Jean Cocteau
52	Some Like It Hot	Billy Wilder
53	Some Came Running	Vincente Minnelli
54	Gertrud	Carl Theodor Dreyer
55	King Kong	Ernst Shoedsack & Merian J. Cooper
56	Laura	Otto Preminger
57	The Seven Samurai	Akira Kurosawa
58	The 400 Blows	François Truffaut
59	La Dolce Vita	Federico Fellini
60	The Dead	John Huston
61	Trouble in Paradise	Ernst Lubitsch
62	It's a Wonderful Life	Frank Capra
63	Monsieur Verdoux	Charlie Chaplin
64	The Passion of Joan of Arc	Carl Theodor Dreyer
65	À bout de souffle	Jean-Luc Godard
66	Apocalypse Now	Francis Ford Coppola
67	Barry Lyndon	Stanley Kubrick
68	La Grande Illusion	Jean Renoir
69	Intolerance	David Wark Griffith
70	A Day in the Country (Partie de campagne)	Jean Renoir
71	Playtime	Jacques Tati
72	Rome, Open City	Roberto Rossellini
73	Livia (Senso)	Luchino Visconti
74	Modern Times	Charlie Chaplin
75	Van Gogh	Maurice Pialat
76	An Affair to Remember	Leo McCarey
77	Andrei Rublev	Andrei Tarkovsky
78	The Scarlet Empress	Joseph von Sternberg
79	Sansho the Bailiff	Kenji Mizoguchi
80	Talk to Her	Pedro Almodóvar
81	The Party	Blake Edwards
82	Tabu	Friedrich Wilhelm Murnau
83	The Bandwagon	Vincente Minnelli
84	A Star Is Born	George Cukor
85	Mr. Hulot's Holiday	Jacques Tati
86	America, America	Elia Kazan
87	El	Luis Buñuel
88	Kiss Me Deadly	Robert Aldrich
89	Once Upon a Time in America	Sergio Leone
90	Daybreak (Le Jour se lève)	Marcel Carné
91	Letter from an Unknown Woman	Max Ophüls
92	Lola	Jacques Demy
93	Manhattan	Woody Allen
94	Mulholland Dr.	David Lynch
95	My Night at Maud's (Ma nuit chez Maud)	Eric Rohmer
96	Night and Fog (Nuit et Brouillard)	Alain Resnais
97	The Gold Rush	Charlie Chaplin
98	Scarface	Howard Hawks
99	Bicycle Thieves	Vittorio de Sica
100	Napoléon	Abel Gance
```
