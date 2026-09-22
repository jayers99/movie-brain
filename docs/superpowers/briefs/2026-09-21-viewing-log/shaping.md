# Viewing log — what was shaped on 2026-09-21 (capture; fresh look tomorrow)

*Written at the end of the evening from the owner's own words, so tomorrow starts from here and not from brief 0.9. Brief 0.9 and `mockup-1.html` stand as the record of round 1 and of the gap checker's first live run (trial log); the barometer question they ask is superseded by §2 below.*

## 1. The shape, in the owner's words

- "A views table, or a watched table: a movie watching event, and it ties into the movie." One film, many events.
- "On the opposite side it needs to tie into differing levels of an agentic discussion: a dictation, a full film analysis, an essay — varying sizes and formats and media." One event, zero or many artefacts of any size.
- Rating after a viewing is dynamic: "sometimes I will just want to put it into a tier, sometimes I will want to fully rank it. It would make sense for it at least to go into a tier." Nothing is tied to a system; it is what he has time for that night. A syllabus film gets the full treatment; a casual watch gets a click.
- "We'll learn as we go." The first steps of a watch log are not known yet; the log is built to be filled, not designed to completion first.

## 2. What that does to round 1

- The three barometer variants (A / B / C) are the wrong question. What survives: **a viewing is a dated event; everything else is optional** (the D shape offered tonight): a one-word felt if he wants one, a short note if he wants one, and the drawer's existing controls (rating box, Rank this, tier row, Unseen) doing what they do today. The "worth" tags go: "worth study" and "worth comparing" are what the artefacts and the tier will say.
- The month view (Watched chip, Watched column) is unaffected.
- The ten stories mostly survive; stories 3 and 8 (tags, ladder) need rewriting once §3 is settled.

## 3. Open shapes (not decided; think tomorrow)

1. **The artefact side.** A table linked to a viewing (kind: dictation / analysis / essay / …; format and media; where it lives). It is the door to backlog 5 (notes + criticism loop) and to the tutor cartridge's study loop, which presumes a per-viewing record. Whether the first build ships the table with a single kind (a note) or nothing but the hook is tomorrow's call.
2. **Tier calibration when placing.** When a film goes into a tier, show the film at the bottom and the film at the top of that tier, because "my brain isn't necessarily calibrated to the tiers". Today's tiers (live): 1 = 95 films, 2 = 265, 3 = 86, 4 = 185, 5 = 132, every one strictly ordered, so bottom and top exist for each. The tier row already exists in the drawer for placed films (move-tier spec); this would extend it to a first placement with the two anchors shown. "A wild thought that we'll have to shape some more."
3. **Documentaries.** "Rating a documentary against a foreign fiction film doesn't quite seem right." Perhaps compared against other documentaries, and also against the canon fiction. Not thought through; touches the ranking pool (one pool today, ranking-pool spec P1).
4. **Tonight's film as the first entry.** Sans Soleil (1983, Chris Marker, #1970, on the Criterion Channel, unrated, unmarked): "pretty good"; "a tier one, probably towards the bottom of tier one, either that or towards the top of tier two"; and it is a documentary, which is what raised §3.3. Recorded in `first-viewings.tsv` (date, felt, note); the tier guess is recorded here only, not as data.

## 4. What tonight settled about history elsewhere (the spike)

- Apple TV, measured on the owner's library: 872 owned movies; a played date with time of day on 6 (all played in TV.app on this Mac, June–September 2026); a resume point on 51 (part-watched); played count is 1 on 837 and 0 on 35, a purchase artefact. No account-wide history; plays on other devices never reach the library. No Apple API. The privacy export may hold a play-activity file: unverified.
- Criterion Channel: Vimeo OTT. The per-customer `watching` endpoint needs the platform owner's key. The viewer site has Continue Watching and My List, no history, no export. The owner's Chrome was not signed in; one probe is left if he signs in himself (read the site's own calls once).
- Conclusion: the log starts empty; a later one-off import of the 6 dated Apple plays and the 51 resume points is the whole backfill.

## 5. Where things are

- Branch `feature/STORY-27-viewing-log`: brief 0.9, mock-up round 1, trial log with both gap-check rounds (16 findings: 13 fixed, 3 stories added, 0 declined), `first-viewings.tsv`.
- The owner has opened the mock-up once; no A/B/C or 1/2 verdict was given and none is needed now.
- Tomorrow: reshape from §2 and §3, then a new stories page (round 2), then the gap check again at point A.

## 6. Deferred 2026-09-22 — what the day in between left for the next look

The fresh look did not happen on 2026-09-22; the owner is thinking more and will pick the story up later. The day's work was elsewhere, and three things from it bear on the shape:

- **A film the log names may not be in the catalog.** Four 1960s–70s B-movies (The Trip, Blood Feast, The Little Shop of Horrors, The Abominable Dr. Phibes) were added by hand today because no verb creates a film outside a list, an old-ratings row or a review row: resolver verdict (director corroborated) → `create_film` → `key_film` with the confirmed ids → `enrich all`. A viewing event will hit the same gap the first time he logs a film the catalog lacks, so the log needs that path as a verb (a `film add TITLE YEAR DIRECTOR`, born keyed, then the catch-up chain) or the log's own entry form has to resolve-and-mint. Today's four went in as a one-off script; the recipe is in the session, not in the CLI.
- **"Where I watched it" has a vocabulary now.** `service:` (alias `on:`) is a search-bar field over the service registry as of today, subscribed or not, and a viewing event could carry the same slug (the film's current listings are the likely candidates; Apple purchase and disc are the two that are not services). Not decided — a candidate for the event's optional fields, beside felt and note.
- **A watch plan preceded the viewings.** The B-movie list arrived as a plain title/year/director file (`lists/b_movies_1960s_1970s.tsv`, untracked, deliberately NOT a curated list) — a personal "want to watch these" set. That is the artefact that comes BEFORE an event, the complement of §1's artefacts that come after. Whether the log's shape has a place for intent (a plan, a syllabus) as well as record is a question for the next look, not an answer.

Everything in §2–§5 stands. Next look still starts from §2–§3.
