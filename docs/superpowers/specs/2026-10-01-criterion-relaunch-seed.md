# Criterion relaunch — seed for brainstorming (2026-10-01)

**Status:** discovery only, nothing built. Input to `superpowers:brainstorming` → spec → plan. Raw captures and the four probe scripts live in `docs/superpowers/research/2026-10-01-criterion-relaunch/`.

## The problem in one line

On 2026-10-01 the Criterion Channel left VHX for its own Next.js + JW Player site. `infrastructure/criterion.py` is dead (`no window.TOKEN on browse page`), so sync exits 1 at step 1 and nothing after it runs; the last good walk was 2026-09-20 (3,013 current films, `films_raw_total` 3,053).

## What the new site offers (verified today)

| Need | Old (VHX) | New source | Notes |
|---|---|---|---|
| Full catalog | `api.vhx.tv/collections` + bearer token | `GET criterionchannel.com/api/all-films/results?page_limit=200[&pagination_key=N]` | No token. `page_limit` caps at 200 → **16 calls** for 3,042 items (~0.5 s each). Item = `{title, release_date, mediaid, duration, contentType}`. 3,009 `film` + 33 `series`. `release_date` is always `YYYY-01-01` (year only). Sorts: title/director/year/country/duration — **no "date added"**. |
| Per-film detail | `metadata.director`, `year_released` in the list | `GET cdn.jwplayer.com/v2/media/<mediaid>` (public JW delivery API) | Carries `director` (JSON-string list), full `release_date` (sometimes), `title_original`, `criterion_id`, `country`, `language`, `starring`, `description_long/medium`, **`license_start_date_time`** (arrival) and **`license_end_date_time`** (expiry). No token. 105 calls today, no throttling seen. |
| Leaving | "Leaving <date>" categories | Home page links `/discover/leaving-<month>-<day>` (today: `leaving-october-31`) → its RSC payload names a JW playlist (`0WbeKrrA`, 28 films, "See All") → `cdn.jwplayer.com/v2/playlists/<id>` | Every item carries `license_end_date_time` (`2026-11-01T03:59:59Z` = Oct 31 Eastern). `/discover/leaving-soon` is an editorial subset (18 films in 4 themed playlists) — not the authority. |
| New arrivals | first_seen diff | Same diff; `license_start_date_time` confirms it | `/new` "October Newly Added Films" playlist holds only **12** curated titles; the catalog diff found **67** films whose licence started 2026-10. The playlist is not the arrivals list. |
| Film URL | `criterionchannel.com/<slug>` | `criterionchannel.com/films/<mediaid>/<slug>` | Old slug URLs 307 to the new form; slug often survives a title change. |

**robots.txt** disallows `/api/` (the catalog endpoint) but allows everything else; the JW CDN is a separate host. The site's own client pages at 60 and backs off on 429.

## The finding that shapes the design: identity drift

Matching today's catalog to the DB by `film_key(title, year)` — which is exactly what `record_catalog`'s upsert does:

| Bucket | Count | What it is |
|---|---|---|
| Key hit | 2,726 | Same title + year as 2026-09-20 |
| Old URL 307s to a mediaid **in** the catalog, key differs | **178** | Criterion re-titled or re-dated the film in the migration: 97 year only (`Vulcanizadora` 2024→2025, `Test Pattern` 2019→2021), 72 title only (`Riotsville, U.S.A.`→`Riotsville, USA`, `Penkelemes`→`Penkelmes`), 9 both |
| Old URL 307s to a mediaid **not** in the catalog | 43 | Departed (incl. all 39 marked "September 30") — the redirect still resolves |
| Old URL 404 | 68 | Departed or removed |
| Old URL 307s to `/supplements/…` | 4 | Reclassified as extras — they leave the film catalog |
| Catalog films with no key hit and no redirect | 105 | 67 genuine October arrivals; 38 older items — mostly editions the T2 fold already merged (`Fanny and Alexander: Theatrical Version`, `EVE'S BAYOU: Director's Cut`), plus year/title drift on films whose old URL was not in the probe set (`Mirror` 1974→1975, `Grey Gardens` 1976→1975, `Désiré`/`Desire`) |

**Consequence if we just swap the fetcher:** ~180–220 twin films minted, the same number of false departures and false "New on Criterion" arrivals (watchlist notifications fire), and editions T2 folded come back. On top of that, the list has no director, and `record_catalog`'s `ON CONFLICT … SET director=excluded.director` would **wipe the director of every Criterion film** (2,959 of 3,083 hold one today).

## Load-bearing facts for the design

- Identity bridge exists: the stored `criterion` external id is the old URL (3,095 rows); a HEAD on it yields the mediaid for current **and** recently departed films. A one-time bridge of all 3,095 at 0.4 s ≈ 21 min (221 of 293 resolved in the probe).
- `mediaid` is unique per item (one dup: `Bad Timing` listed twice, same mediaid). `criterion_id` is a second stable id in the JW record.
- Data quirks to guard: 5 items with `release_date` `0-01-01` or `2915-01-01`; JW `director`/`country`/`language` are JSON **strings**, not arrays; licence times mix `03:59:59Z` and `04:59:59Z` (convert to America/New_York, take the date).
- Existing contracts that touch this: sync-flow steps 1–3 (cheap check, `merge_yearless`, `record_catalog` + criterion claims, `set_leaving` label format `"September 30"`), `_LISTING_CURRENT` (criterion = MAX(last_seen)), `film_disposition` alias chains, the thumbprint resolver reading claim rows, availability transitions/notifications.
- Live stakes: 99 rated films and 12 viewings sit on Criterion-listed films; nothing may be re-identified silently.

## Open questions for brainstorming (my recommendation first)

1. **Catalog source vs robots.txt.** (a) Use `/api/all-films/results` politely — 16 calls, 1 s apart, owner's personal use — *recommended*; (b) no full list at all and rely on curated playlists (cannot see departures reliably). This is an owner call, not an implementation detail.
2. **New identity value.** Store `mediaid` as the `criterion` claim/external id (new rows, old URL rows kept — claims are append-only) — *recommended*; or the full new URL.
3. **Bridging existing films.** One-shot verb (`criterion bridge [--apply]`) that HEADs every stored old URL, writes the mediaid next to it, and reports drift — run once before the first new sync — *recommended*; the new walk then matches **by mediaid first**, `film_key` only as fallback, and an unmatched catalog item goes through the thumbprint resolver (director from JW) instead of minting blind.
4. **Who wins on title/year drift?** Keep `films.title`/`year` as they are and record Criterion's new title/year only in the claim — *recommended* (year truth-holder rules in `identity.md`); vs. let Criterion overwrite.
5. **Cheap check.** Drop it — a full walk is 16 calls — *recommended*; vs. keep a `total`-only check.
6. **Director + licence dates.** Fetch the JW media record for new mediaids only (enrichment-on-add); leaving dates from the leaving playlist each sync — *recommended*; vs. a weekly 3,009-call JW refresh for every film's `license_end` (catches extensions and early exits).
7. **Leaving storage.** Keep the `"October 31"` label shape, or store an ISO date (dashboard chip and the 39 existing rows read the label).
8. **Series (33) and supplements.** Keep excluding them as the old adapter did — *recommended*.
9. **First run optics.** The first walk after the bridge will still show ~67 real arrivals and ~115 real departures in one night; suppress or allow the notification for that one run?

## Suggested story spine (for the spec, not decided)

1. Bridge old URLs → mediaid (dry run reports the drift table above; apply writes ids, touches no title/year).
2. New catalog adapter (walk + JW detail + leaving playlist) behind the same `fetch_*` seam, fixtures cut from the real captures in the research folder.
3. `record_catalog` matches by mediaid, never nulls a director, routes misses through the resolver.
4. Leaving date from `license_end_date_time`; arrivals verified against `license_start_date_time`.
5. Listing URL becomes `/films/<mediaid>/<slug>`; set `services url criterion` to `/search?q={title}`.
6. One live run, before/after counts shown to the owner (one-at-a-time rule).
