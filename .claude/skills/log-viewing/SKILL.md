---
name: log-viewing
description: Use when the owner says he watched a film ("I just watched…", "watched X last night", "log a viewing", "one more thing about X") — turn the dictation into ONE `movie-brain viewings add` command; never invent a date or a number; ask on AMBIGUOUS / NO-FILM.
---

# Log a viewing from a dictation

The owner dictates in this session; you run `movie-brain viewings add` and show its one line back. The verb runs the title ladder (open drawer → one match → ask), not you. Brief: `docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md`.

## Extract, from his words

- **Title**, verbatim, one film per command (a double bill is two commands, each with its own words). Pass `--year` only when HE names a year; a director he names is used to answer an AMBIGUOUS list, never to pre-empt it.
- **Date**: today unless he says otherwise; resolve relative words against today ("last Monday", "yesterday", "about last night" → `--on YYYY-MM-DD`). Never invent one.
- **Service** → a registry slug (`movie-brain services list`), mapped THROUGH THE FILM: "Apple TV" for a film he owns is `apple-tv-store`, for one streaming on Apple TV+ it is `apple-tv-plus`; "Max"/"HBO" is `max` when the film lists it; "Criterion" is `criterion`; "Kino" is `kino-film-collection`. Two slugs fit, or none → ask before running. A disc or a cinema → no `--service`.
- **Rating** → `--rate N` only when he offers ONE whole number 0–10 AS a rating, however hedged ("about a six", "a strong seven", "rate it ten"). Two candidates or a fraction ("a 9 or a 10", "seven and a half") → ask. A tier, a year, a count is not a rating. No number → no `--rate`.
- **The text** → everything he said about the film, whole, on stdin (`--text -` with a heredoc). Do not summarise it.
- **A presentation remark** (restoration, transfer quality) → also append a row to `observations/presentation.tsv` (columns `watched_on film_id title year service verdict note`), by hand, as that file is kept today.

## Run

    movie-brain viewings add --title "<title>" [--year Y] [--on YYYY-MM-DD] [--service slug] [--rate N] --text - <<'EOF'
    <his words>
    EOF

Show the verb's one line back and nothing more. Exit 0 = written. Then:

- **`AMBIGUOUS` (exit 3)**: show the candidates it printed; ask which; rerun with `--film ID`.
- **`NO-FILM` (exit 3) with a `nearest:` list**: ask "this one?" for the first; rerun with `--film ID` on yes.
- **`NO-FILM` with nothing close**: propose the IMDb id you believe it is and run `movie-brain films add ttNNN` DRY; show TMDB's title and year; run `--apply` ONLY on his yes (it enriches, then you log with `--film <new id>`). `HELD` means the catalogue has it: log against the named holder. Exit 2 for missing keys: tell him, create nothing.
- **`REFUSED` (exit 2)**: read the reason back and fix the flag; nothing was written.

## Never

- Never write a tier or a rank ("put it in tier 2" → the drawer's Tier row / Rank this; say so). Never write the watchlist (the drawer's ★ is its only writer). Never run `films add --apply` or `migrate --apply` without his yes. Never log a rating without a viewing to hang it on: no title and no open film → ask which film.
- A second sentence about the same film the same day is another `viewings add`: the verb appends the note (`ADDED-TO`). "Scratch that last remark" → `movie-brain viewings remove VID --note N`; the whole evening → `viewings remove VID`.
- "What did I watch this month?" → `movie-brain viewings list --since YYYY-MM-01`. "What's open?" → `movie-brain viewings open`.
