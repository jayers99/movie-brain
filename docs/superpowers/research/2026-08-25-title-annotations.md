# Title annotations: what's in the parentheses, brackets, and colons — RESEARCH INPUT

**Date:** 2026-08-25 · **Status:** collected evidence, no decisions · **Feeds:** the title-resolution
spec (`docs/superpowers/specs/2026-08-24-title-resolution-seed.md`) and a future normalized-title /
edition / year-model spec. Read-only analysis of the live `films.title` column (4,638 non-disposed
films). Scratch data: every annotated title with its buckets is reproducible with the script in §7.

## 1. Headline numbers

| | count |
|---|---|
| films | 4,638 |
| titles carrying any annotation | **139 (3.0%)** |
| …by source | owned (Apple) **104** · Metacritic 19 · Criterion 16 |
| director-less films today | 60 |
| director-less AND annotated | **28** (so annotations explain ~half of the residue; the rest are Criterion shorts OMDb lacks) |
| annotated films with an OMDb record whose year differs from ours by > 2 | 1 of 105 |

The last row is the important surprise: **the year drift we fear is mostly not on annotated films
that matched — it's that annotated films never matched at all** (most edition titles have no
OMDb record: `omdb_y=None` in §4). Where an edition title *did* match, `films.year` already holds
the *edition's* year (Blade Runner 2007, Phantasm 2016), i.e. the original year was lost at ingest.

## 2. Buckets found (delimiter × class), with live examples

| delimiter | bucket | n | director-less | examples |
|---|---|---|---|---|
| `( )` | **YEAR** | 82 | 1 | `Ran (1985)`, `Vertigo (1958)`, `Rear Window (1954)` (film year stored **2013**) |
| `( )` | TRANSLATION / ALT | 27 | 7 | `Mad Bills to Pay (or Destiny, dile que no soy malo)`, `Makeshift (for Mekas)`, `MOTV (My Own TV)`, `Egungun (Ancestor Can't Find Me)` |
| `( )` | **EDITION_CUT** | 8 | 4 | `Apocalypse Now (Final Cut)`, `Blade Runner (The Final Cut)`, `American Psycho (Uncut Version)`, `Straight Outta Compton (Unrated Director's Cut)`, `Paul (Unrated) [2011]` |
| `:` | **EDITION_CUT** | 7 | 5 | `Donnie Darko: The Director's Cut`, `FANNY AND ALEXANDER: Theatrical Version`, `How the Grinch Stole Christmas: The Ultimate Edition`, `National Lampoon's Van Wilder: The Unrated Version`, `The Exorcist: Extended Director's Cut` |
| `[ ]` | **RESTORATION** | 7 | 6 | `Eyes Without a Face [re-release]`, `I Vitelloni [re-release]`, `Piccadilly [re-release]` (all Metacritic) |
| `( )` | RESTORATION | 4 | 4 | `The Umbrellas of Cherbourg (re-released)`, `Lawrence of Arabia (Restored Version)`, `My Man Godfrey (In Color & Restored)`, `Goodfellas (Remastered Feature)` |
| `[ ]` | YEAR | 3 | 0 | `Paul (Unrated) [2011]` — Apple stacks two annotations |
| `:` | RESTORATION | 1 | 0 | `Phantasm: Remastered` |
| `( )` | ANNIVERSARY | 1 | 1 | `Ghost In the Shell (25th Anniversary Edition)` |
| `( )` | OTHER | 2 | 0 | `(500) Days of Summer` (**leading** parens = part of the title), `Concrete Resources (Thank you for keeping me a company of images)` |

Observations:
- **Apple is the annotation factory.** 82 of 88 `(YYYY)` titles and every `(Unrated) [YYYY]`
  stack are Apple. Apple's convention is `Title (Edition) [Year]` or `Title (Year)`.
- **Metacritic uses `[re-release]`** exclusively (square brackets), plus one `(re-released)`.
- **Criterion uses `TITLE: Theatrical Version`** (uppercase title, colon) for the Bergman cuts —
  and those are *legitimately distinct catalog entries* (Criterion streams both cuts).
- **Parenthesized translations are part of the title** on Criterion shorts (`Egungun (Ancestor
  Can't Find Me)`) and on Metacritic imports (`L'Enfant (The Child)`, `Genèse (Genesis)`,
  `Our Land (Nuestra Tierra)`). Stripping them would *lose* an alt-title we want for matching.
- `(500) Days of Summer`: annotation detection must be **trailing-only** (or bracket-aware);
  a leading paren group is title.

## 3. Vocabulary observed (for the grammar)

```
EDITION_CUT   : director's cut · the director's cut · final cut · the final cut · extended director's cut
                uncut version · unrated · unrated director's cut · the unrated version · theatrical version
                the ultimate edition · anniversary special edition · redux (Apocalypse Now Redux — no delimiter!)
RESTORATION   : re-release · re-released · restored version · in color & restored · remastered · remastered feature
ANNIVERSARY   : 25th anniversary edition
YEAR          : (1985) · [2011]
FORMAT (none live yet, expect from Apple): 3D · IMAX · 4K · HDR · Dolby Vision · English Version · Dubbed · Subtitled
```
Two undelimited forms already exist and defeat a delimiter-only parser:
`Apocalypse Now Redux` (2001), `Donnie Darko: Anniversary Special Edition` — and the Criterion
uppercase `SCENES FROM A MARRIAGE: Theatrical Version`.

## 4. Edition / restoration titles — the full live set (28) with what we know

| id | title | films.year | OMDb year | director | source |
|---|---|---|---|---|---|
| 1909 | SCENES FROM A MARRIAGE: Theatrical Version | 1973 | – | yes | crit |
| 2416 | FANNY AND ALEXANDER: Theatrical Version | 1982 | – | yes | crit |
| 3393 | Eyes Without a Face [re-release] | **2003** (orig 1960) | – | NO | mc |
| 3414 | Investigation of a Citizen Above Suspicion [re-release] | 1970 | 1970 | yes | mc |
| 3459 | Piccadilly [re-release] | **2004** (orig 1929) | – | NO | mc |
| 3461 | Quai des Orfèvres [re-release] | **2002** (orig 1947) | – | NO | mc |
| 3498 | Overlord [re-release] | **2006** (orig 1975) | – | NO | mc |
| 3508 | Mafioso [re-release] | **2007** (orig 1962) | – | NO | mc |
| 3517 | Donnie Darko: The Director's Cut | **2004** (orig 2001) | – | NO | mc |
| 3582 | I Vitelloni [re-release] | **2003** (orig 1953) | – | NO | mc |
| 3745 | The Umbrellas of Cherbourg (re-released) | **2004** (orig 1964) | – | NO | mc |
| 3999 | How the Grinch Stole Christmas: The Ultimate Edition | **2015** (orig 2000) | – | NO | owned |
| 4048 | Lawrence of Arabia (Restored Version) | **1989** (orig 1962) | – | NO | owned |
| 4070 | Phantasm: Remastered | **2016** (orig 1979) | 2016 | yes | owned |
| 4094 | Straight Outta Compton (Unrated Director's Cut) | 2015 | 2015 | yes | owned |
| 4098 | Apocalypse Now (Final Cut) | 1979 | – | NO | owned |
| 4131 | Paul (Unrated) [2011] | 2011 | 2011 | yes | owned |
| 4133 | My Man Godfrey (In Color & Restored) | 1936 | – | NO | owned |
| 4293 | Ghost In the Shell (25th Anniversary Edition) | 1996 (orig 1995) | – | NO | owned |
| 4303 | Goodfellas (Remastered Feature) | **2015** (orig 1990) | – | NO | owned |
| 4304 | American Psycho (Uncut Version) | 2000 | – | NO | owned |
| 4404 | Donnie Darko: Anniversary Special Edition | 2001 | – | NO | owned |
| 4409 | Blade Runner (The Final Cut) | **2007** (orig 1982) | 2007 | NO | owned |
| 4412 | Waiting (Unrated) [2005] | 2005 | 2005 | yes | owned |
| 4503 | Moonwalk One (The Director's Cut) | **2009** (orig 1970) | – | NO | owned |
| 4532 | National Lampoon's Van Wilder: The Unrated Version | 2002 | – | NO | owned |
| 4557 | Funny People (Unrated) [2009] | 2009 | 2009 | yes | owned |
| 4599 | The Exorcist: Extended Director's Cut | **2000** (orig 1973) | – | NO | owned |

("orig" years are from general knowledge, to be confirmed against TMDB in the spec phase.)
**15 of 28 carry the edition's year as `films.year`**, exactly the "silly year" the owner named.
Note Metacritic's `[re-release]` year is *always* the re-release year, by construction.

## 5. Owner's stated preferences (2026-08-25, to carry into the spec)

- Keep the **original release year** as the film's year. The edition's year is trivia; the fact
  that it *is* the Director's Cut is the important information.
- Have a **normalized title** as a separate attribute, used for matching (Levenshtein etc.);
  keep the ingested string.
- The edition ("Director's Cut", "Final Cut", "Unrated") should be captured as **data**, not
  lost and not left inside the title.
- Open question raised by the owner: two year attributes (original vs re-release)? And what about
  a film with *many* editions (Blade Runner: 1982 theatrical, 1992 Director's Cut, 2007 Final Cut)?

## 6. Candidate models (collected, NOT decided)

**M1 — attributes on the film row**: `title_norm`, `edition` (free text or enum), `edition_year`;
`films.year` stays original. Simple; but Blade Runner-with-three-editions becomes three films or
one film with one edition. Apple ownership is per *edition* (you own *The Final Cut*), Criterion
streams specific cuts — so editions are real things the sources talk about.

**M2 — edition as a child record**: `film` = the work (original year, normalized title, parent key
`tt`); `edition` rows = (film_id, label, year, source-specific ids); `owned`/`listings` attach to an
edition when the source is edition-specific, else to the film. Cleanest for Blade Runner; more
schema; the dashboard shows one row per work with edition badges.

**M3 — treat editions as alt-titles only**: strip to the work, keep the label in an `aliases`
table for matching, ignore edition identity. Cheapest; loses "I own the Final Cut".

Both M1 and M2 need the same first step: the **grammar** in §3 producing
`(title_norm, edition_label, edition_year_hint, alt_titles[])` from any ingested string, applied at
ingest and at search time. That grammar is source-aware only in delimiter style; the vocabulary is
shared. Trailing-only; bracket-aware; leading parens are title; parenthesized translations become
`alt_titles`, not stripped.

Matching implications (from the 110-case evidence set): the normalized title is what Levenshtein
compares; an edition label on the ingested title *raises* tolerance for a longer official title
(`Episode VII - …`) and *lowers* trust in the ingested year (use ±2 band, search without year
first); the parent key (`tt`) is still the goal, and OMDb is fetched by id only.

## 7. Reproduce

```bash
uv run python - <<'EOF'
# see this session's scratch: annotations.json was produced by the bucket script
# (trailing () and [] groups, ':'/'-' suffixes matched against the §3 vocabulary)
EOF
```
The bucket regexes used: EDITION_CUT `director's cut|final cut|extended|uncut|unrated|theatrical|
ultimate|special edition|definitive|redux`, RESTORATION `restored|restoration|remaster|4k|re-?release|
reissue`, ANNIVERSARY `\d+(st|nd|rd|th) anniversary`, YEAR `^\d{4}$`, PART_VOL
`(part|vol|volume|chapter|episode) [ivx\d]+`, else TRANSLATION/ALT if it contains letters and ≤ 8 words.
