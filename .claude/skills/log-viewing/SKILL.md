---
name: log-viewing
description: Use when the owner says he HAS WATCHED a film ("I just watched…", "watched X last night", "log a viewing", "one more thing about X") — turn the dictation into ONE `movie-brain viewings add` command; never invent a date or a number; ask on AMBIGUOUS / NO-FILM. Not for "I want to watch X" or a plan for later — that is not a viewing (see "Sentences that are not viewings" below).
---

# Log a viewing from a dictation

The owner dictates in this session; you run `movie-brain viewings add` and show its one line back. The verb runs the title ladder (open drawer → one match → ask), not you. Brief: `docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md`.

## Extract, from his words

- **Title**, verbatim, one film per command (a double bill is two commands, each with its own words). Pass `--year` only when HE names a year.
- **A director he names** is used to answer an AMBIGUOUS list, never to pre-empt it — and it does NOT skip rung 1 the way a year does. If he names a director and the title is not unique in the catalogue, or you are unsure which film his words mean, run `movie-brain viewings open` first. If the open film carries the dictated title, tell him which film is open before running anything ("the drawer shows Soderbergh's 2002 Solaris; you said Tarkovsky — log the 1972 one?") and only run with `--film` or `--year` on his answer. Only a `--year` he states skips the open-film rung.
- **Date**: today unless he says otherwise; resolve relative words against today ("last Monday", "yesterday", "about last night" → `--on YYYY-MM-DD`). Never invent one.
- **After midnight**: between midnight and about 5 AM, "tonight" / "just watched" means YESTERDAY's date — pass `--on` for it and say so in your reply ("that's after midnight, so I'm dating it the 26th").
- **Service** → a registry slug (`movie-brain services list`), mapped THROUGH THE FILM: "Apple TV" for a film he owns is `apple-tv-store`, for one streaming on Apple TV+ it is `apple-tv-plus`; "Max"/"HBO" is `max` when the film lists it; "Criterion" is `criterion`; "Kino" is `kino-film-collection`. Two slugs fit, or none → ask before running. A disc or a cinema → no `--service`.
- **Rating** → `--rate N` only when he offers ONE whole number 0–10 AS a rating, however hedged ("about a six", "a strong seven", "rate it ten"). Two candidates or a fraction ("a 9 or a 10", "seven and a half") → ask. A tier, a year, a count is not a rating. No number → no `--rate`.
- **The text** → everything he said about the film, whole, on stdin (`--text -` with a heredoc). Do not summarise it. When he asks only to mark a date ("just log that I watched X on the 27th, no note"), pass `--no-note` instead of `--text`: the viewing is written with no artefact, and nothing is invented.
- **A presentation remark** (restoration, transfer quality) → also append a row to `observations/presentation.tsv` (columns `watched_on film_id title year service verdict note`), by hand, as that file is kept today.
- **If you pass both `--title` and `--film`**, they must name the same work — the verb refuses (`REFUSED --film ID is '…', not '…'`) rather than silently trusting the id, so a mistyped id in a rerun is caught, not logged.

## Run

    movie-brain viewings add --title "<title>" [--year Y] [--on YYYY-MM-DD] [--service slug] [--rate N] --text - <<'EOF'
    <his words>
    EOF

Show the verb's one line back and nothing more. Exit 0 = written. Then:

- **`AMBIGUOUS` (exit 3)**: show the candidates it printed; ask which; rerun with `--film ID`.
- **`NO-FILM` (exit 3) with a `nearest:` list**: ask "this one?" for the first; rerun with `--film ID` on yes.
- **`NO-FILM` with nothing close**: propose the IMDb id you believe it is and run `movie-brain films add ttNNN` DRY; show TMDB's title and year; run `--apply` ONLY on his yes (it enriches, then you log with `--film <new id>`). `HELD` means the catalogue has it: log against the named holder. Exit 2 for missing keys: tell him, create nothing.
- **`REFUSED` (exit 2)**: read the reason back and fix the flag; nothing was written.

## Finding a note's number

`viewings list --film ID` prints, under each viewing's own line, its notes numbered (`    note 1  <first words>…`). Before "scratch that remark" or any `remove --note N`, run this to read N off the line — never guess it and never go to raw SQL.

## Never

- Never write a tier or a rank ("put it in tier 2" → the drawer's Tier row / Rank this; say so). Never write the watchlist (the drawer's ★ is its only writer). Never run `films add --apply` or `migrate --apply` without his yes. Never log a rating without a viewing to hang it on: no title and no open film → ask which film.
- A second sentence about the same film the same day is another `viewings add`: the verb appends the note (`ADDED-TO`). "Scratch that last remark" → run `viewings list --film ID` first, read the note's number N off the line, then `movie-brain viewings remove VID --note N`; the whole evening → `viewings remove VID`.
- "What did I watch this month?" → `movie-brain viewings list --since YYYY-MM-01`. "What's open?" → `movie-brain viewings open`.

## Sentences that are not viewings

- **"Log my six Apple TV plays" / "import my watch history"** — there is no import verb. Take them one sentence each, the same as a live dictation, each with its own `--on` date; read each line back to him as you go.
- **"I want to watch X" / "I'm planning to watch X this weekend"** — a plan, not a viewing. Nothing is logged. The drawer's ★ (watchlist) is the only writer for that; say so and point at it rather than running `viewings add`.
- **A long piece — an essay, five minutes of dictation about a film he already watched** — goes in whole, as ONE note on that viewing's line, exactly like any other dictation (`--text -`). It is stored, not summarised; a distinct "essay" kind is a later build, not this one.
