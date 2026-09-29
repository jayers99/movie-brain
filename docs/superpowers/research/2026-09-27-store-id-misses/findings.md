# Store-id misses — spike findings (2026-09-27, backlog 23)

Read-only. `spike.py` (throwaway, run from the repo with `uv run python`) asked CheapCharts about the 20 films Apple demonstrably sells that hold no store id: the IMDb index for all 20 (`step1-imdb-index.log`), then a title search per catalog title and per TMDB title/original/alternative (capped at six names, `step2-title-searches.log`), with every answer put through the live `_confirm` gate; the promising candidates were then put through the `_refusal` filing gate by hand (15 DetailData calls). 84 search calls in all, nothing written.

## What the index says

- 11 of 20 have NO entry in CheapCharts' IMDb index (Él, Under the Heavens, Kid, The Fountain, Factory, The Curve, Kill!, King of the Hill, JOKER doc, Irezumi, Under the Skin).
- 9 of 20 HAVE an entry, and every one is a product Apple has removed — the film is re-listed under a new id the index does not know (Pineapple Express 296672025 removed → 533284299 and 293561003 live). So for these nine the resolver correctly treats the answer as a miss and the title search is the only path.

## Why the title search misses — three defects, none of them "the index is missing them"

1. **A store title carrying its year is refused by the matcher.** `_confirm` hands `match_owned` the raw store title; `split_annotations` strips editions but not a trailing `(1993)`, so `King of the Hill (1993)` against King of the Hill 1993 loses on title. `parse_apple_title` (what `owned import` already uses) fixes it offline: Under the Skin, Basket Case, King of the Hill, Django, The Fountain all become winners.
2. **The catalog title is the only name the matcher knows.** Day of the Woman is sold as *I Spit on Your Grave*, Zombie Flesh Eaters as *Zombie*, Late Night Trains as *Night Train Murders*. `tmdb_facts.alt_titles` already holds those names (4,032 of 5,201 films carry alternatives); one `Candidate` per alternative sharing the film id makes all three winners offline.
3. **A year the matcher cannot corroborate ends the lookup before the filing is asked.** Él is listed as 1955 (1953), Don't Torture a Duckling as 2025 (a re-release year); both are refused on year drift because a search result carries no director — yet both products' filings name the right IMDb id or director.

## The filing gate held every time it was asked

Of 15 live candidates, 13 PASS the filing gate; the 2 refusals are RIGHT: `The Fountain (2006)` is Aronofsky's (tt0414993, not Dunham's short), and CheapCharts files Glazer's Under the Skin product 858619452 under tt1764725, not tt1441395 — a misfiling at their end (director agrees), the audit's `misfiled?` class, hand-place only.

## Yield per fix (of 20)

| Fix | Films placed | Cost |
|---|---|---|
| 1 embedded year parsed | Basket Case, King of the Hill, Django (3; Under the Skin then refused by filing, The Fountain rightly refused) | S, no new data |
| 2 alt titles as candidates | Day of the Woman, Zombie Flesh Eaters, Late Night Trains (3) | S, data already in `tmdb_facts` |
| 3 year-drift → ask the filing | Él, Don't Torture a Duckling (2) | owner rule: the filing outranks a year the matcher cannot corroborate |
| 4 edition ambiguity | Pineapple Express (plain vs Unrated), Ginger Snaps (two ids, same title/year) (2) | owner rule: which edition, or store the plain one |
| 5 collection prefix | Lessons of Darkness (`Werner Herzog Film Collection: …`) (1) | a prefix rule in `split_annotations` |
| — not on CheapCharts today | Under the Heavens, Kid, Factory, The Curve, Kill!, JOKER doc, Irezumi, The Fountain (Dunham), Under the Skin (misfiled) (9) | nothing to build |

Fixes 1 + 2 together place 6 of 20 with no new rule and no new call; each candidate still passes the filing gate, verified live today.
