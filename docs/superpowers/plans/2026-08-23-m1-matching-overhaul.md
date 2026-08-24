# M1 Matching Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One evidence-scored matcher core behind the three existing wrapper functions, with fixed normalization, a three-level candidate index, source-aware year policy, Apple export v2 (runtime), and an offline benchmark that proves the new matcher dominates the old ones before any pipeline adoption.

**Architecture:** The benchmark harness lands FIRST (data-level TDD) with a frozen verbatim copy of today's matchers as the baseline. Then `domain/matching.py` gains a pure evidence-scoring core (`match_candidates`) + `CandidateIndex`; `match_film` / `match_owned` / `pick_tmdb_match` become thin per-source policy wrappers over it. Callers pass richer candidates (director from Criterion/OMDb COALESCE, runtime from OMDb payload / Apple export v2). No schema changes, no new write paths — M2 owns year write-back and rematch.

**Tech Stack:** Python 3.12, uv, pytest + pytest-bdd, sqlite3 (read-only URI for the benchmark), ruff (checks `scripts/`, 120 cols), mypy strict (checks `src/` only).

**Spec:** `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (binding for M1–M3). Companion: `docs/superpowers/handoffs/2026-08-23-m1-matching-handoff.md`.

## Global Constraints

- **No live-DB behavior changes in M1**: no schema migrations, no new write paths, no rematch/repair runs against `~/.config/movie-brain/movie-brain.db`. The benchmark opens the live DB **read-only** (`file:...?mode=ro`).
- Collectors never delete; the matcher only ever matches, reviews, or creates.
- `match_film`, `match_owned`, `pick_tmdb_match` keep their names, return types (`MatchResult` / `int | None`), and accept their current positional argument shapes (old 3-tuple candidate lists must still work). Extra evidence arrives via optional keyword args and richer candidate types.
- M1 Done gate (spec): new matcher **wrong-match ≈ 0** on ground truths and strictly ≤ baseline wrong-matches; **review load < 5%** of archive-replay inputs (target — report the real number either way); suite + `uv run ruff check .` + `uv run mypy` green.
- Review-queue reason strings visible to the live DB stay as-is in M1: `ambiguous-owned`, `year-drift` (apple-tv), `ambiguous-title`, `film-multiple-slugs`, `slug-conflict`, `expected-miss`, `key-conflict` (metacritic), `no-match` (tmdb). ONE additive exception: metacritic gains `year-gap` (Task 4) — a review verdict MUST reach `match_review` so `promote_top_n`'s anomalous-slug skip prevents twin-creation of review-band titles.
- Execution happens in a git worktree (superpowers:using-git-worktrees); branch name `feature/M1-matching-overhaul`.
- Commit style: brief single line, why-focused. All commands via `uv run`.

## Known-good facts (verified 2026-08-23, this session)

- Metacritic archive: `~/.config/movie-brain/metacritic/pages/` — 200 pages (~4,783 staged titles). Parse with `movie_brain.infrastructure.metacritic.parse_archive(archive_dir)`.
- Apple archive: `~/.config/movie-brain/appletv/owned-2026-08-23.txt` — 870 lines, 2-column (`name \t year`). Parse with `movie_brain.infrastructure.appletv.parse_export(text)`.
- `films` columns: `id, guid, title, year, director, key`. OMDb payload JSON has `Director` ("A, B" comma lists) and `Runtime` ("91 min"); OMDb uses the literal string `"N/A"` for missing values.
- `repo.films_for_matching()` currently returns `(id, title, year, omdb_metacritic)`.
- Live check: film 3086 (Lawrence of Arabia, 1962) still has **no** tmdb external id (only `metacritic|lawrence-of-arabia-re-release`) — the hoped-for nightly rematch did not land. Do NOT fix in M1; record in the M2 handoff.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/matching_baseline.py` | Create | Frozen verbatim copy of today's matchers — benchmark comparison anchor, never edited after Task 1 |
| `scripts/matching_benchmark.py` | Create (Task 1), extend (Task 6) | Ground-truth suite + archive replay + report; `--assert-dominance` gate |
| `src/movie_brain/domain/matching.py` | Modify | New normalization, annotation grammar, `Candidate`/`MatchQuery`/`CandidateIndex`/`match_candidates` core, wrappers become policy shells |
| `src/movie_brain/domain/models.py` | Modify | `OwnedTitle` gains `runtime_min`; `MatchResult` stays in matching.py |
| `src/movie_brain/infrastructure/database.py` | Modify | `films_for_matching` returns director + runtime (read-time COALESCE/json_extract — no schema change) |
| `src/movie_brain/infrastructure/appletv.py` | Modify | Export v2: duration column in AppleScript + 2/3-column parser |
| `src/movie_brain/application/owned.py` | Modify | Build `CandidateIndex`, pass embedded-year flag + runtime |
| `src/movie_brain/application/metacritic.py` | Modify | Build `CandidateIndex`, adapt to enriched `films_for_matching` rows |
| `src/movie_brain/application/availability.py` | No change | `pick_tmdb_match` signature unchanged |
| `tests/unit/test_matching.py` | Modify | New normalization/grammar/core tests; update intentionally-changed expectations |
| `tests/unit/test_appletv.py` | Modify | v2 parser tests |
| `tests/unit/test_database.py` | Modify | enriched `films_for_matching` test |
| `tests/unit/test_benchmark.py` | Create | Smoke: harness module loads, case runner + rate math correct on synthetic data |
| `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` | Modify (Task 7) | M1 Done line with real benchmark numbers |
| `docs/superpowers/handoffs/2026-08-23-m2-matching-handoff.md` | Create (Task 7) | M2 entry point |
| `CLAUDE.md` | Modify (Task 7) | Rules: one matcher core note; owned import runtime column |

## The evidence model (single source of truth for Tasks 1, 3, 4)

Types (all in `domain/matching.py`):

```python
class YearKind(Enum):
    DATABASE = "database"   # Criterion, TMDB, embedded-title years: tight ±1
    COMMERCE = "commerce"   # Metacritic, Apple's field year: trail originals, never precede

@dataclass(frozen=True)
class Candidate:
    id: int
    title: str
    year: int | None
    director: str | None = None
    runtime_min: int | None = None
    popularity: float | None = None

@dataclass(frozen=True)
class MatchQuery:
    title: str                      # RAW title; the index/core normalizes
    year: int | None
    year_kind: YearKind
    director: str | None = None
    runtime_min: int | None = None

@dataclass(frozen=True)
class MatchVerdict:
    kind: str                       # "match" | "review" | "create"
    film_id: int | None = None      # set iff kind == "match"
    reason: str | None = None       # set iff kind == "review": "ambiguous"|"year-gap"|"remake-suspected"|"weak-title"|"year-impossible"
    tied: tuple[int, ...] = ()      # set for reason == "ambiguous"

Arbiter = Callable[[str, int], bool]   # (title, claimed_year) -> same-titled film exists near claimed_year
                                       # M1: interface only — nothing wires a real one
```

**Normalization** (`norm_title`): casefold → NFKD + strip combining marks (Tête→tete) → `&`→` and ` → `$`→`s` → regex `\bvol\b\.?` → `volume` → keep only alnum.

**Annotation grammar** (`split_annotations(title) -> tuple[str, tuple[str, ...]]`): loop-strip trailing `(annotation)`, `[annotation]`, or ` – annotation` / ` — annotation` / ` - annotation` (case-insensitive, optional leading "the"), for annotation in the extendable constant `EDITION_ANNOTATIONS`:
`re-release, rerelease, unrated, director's cut, director's edition, extended edition, extended cut, theatrical version, theatrical cut, special edition, collector's edition, uncut, remastered, restored, restored version, 4k, 4k restoration, 4k remaster, subtitled, dubbed, english subtitles`.
Never strip to an empty title. Returns (stripped title, annotations found). `rerelease_hint = bool(annotations)` — any edition annotation means the source's year describes that edition, not the original.

**CandidateIndex** — three lookup levels, built once per corpus:
- L0: `norm_title(candidate.title)` exact.
- L1: `norm_title(split_annotations(candidate.title)[0])` (annotation-stripped).
- L2: pre-colon prefix of the candidate title when the prefix has ≥2 words: `norm_title(prefix)`.
`index.lookup(query_title)` tries the query's own L0 key against levels L0→L1→L2, then the query's annotation-stripped key, then the query's pre-colon-prefix key (≥2 words); first level with hits wins and is returned as `(level, [candidates])` where level ∈ {0,1,2} is the WEAKER of (query transform, candidate bucket).

**Scoring** one candidate against a query (`None` = disqualified):
- Title: level 0 → +3, level 1 → +2, level 2 → +1.
- Year (both present; Δ = query.year − cand.year):
  - |Δ| ≤ 1 → +2.
  - DATABASE kind, |Δ| > 1 → disqualified.
  - COMMERCE kind, Δ < −1 (commerce year impossibly EARLIER than the film) → disqualified.
  - COMMERCE kind, Δ > 1 → +0 and `gap` flag set on this candidate.
  - Either year missing → +0, no flag.
- Director (both non-empty): split both on `,`, strip + casefold each name; any shared name → +3; none shared → disqualified. Either missing → +0.
- Runtime (both present): |Δ| ≤ max(2, 5% of cand) → +2; |Δ| > 15% of cand → disqualified; else +0.

**Verdict** (`match_candidates(query, index, *, rerelease_hint=False, popularity_tiebreak=False, arbiter=None)`):
1. No candidates at any level → `create`.
2. Candidates found but ALL disqualified — split by WHY:
   - Every disqualification was the COMMERCE-early rule (query year impossibly EARLIER than every candidate) → `create`. Commerce years never precede originals, so the queried film genuinely predates everything we hold — a distinct film, not a twin (MC "Solaris" 1972 with only the 2002 film in corpus must create the 1972 original).
   - Any disqualification was DATABASE-year, director, or runtime → `review("conflict")`. Never twin silently on a hard-evidence conflict (owned "Nosferatu" 2024 whose runtime rules out the 1922 film → review, not create).
3. Rank survivors by score desc. Tie at the top: if `popularity_tiebreak` and exactly one top-scorer has strictly max popularity → it wins; otherwise `review("ambiguous", tied=(ids...))`.
4. Unique winner with `gap` flag and NO corroboration (corroboration = `rerelease_hint` or director +3 earned or runtime +2 earned): if `arbiter` given → `arbiter(query.title, query.year)` True → `review("remake-suspected")`, False → `match`; no arbiter → `review("year-gap")`.
5. Winner matched only at level 2 with no year points and no director/runtime points → `review("weak-title")`.
6. Otherwise → `match(winner.id)`.

**Wrapper policies:**
- `match_film(mc_title, mc_year, candidates)`: strip year-paren + annotations via `clean_title`/`split_annotations`; `year_kind=COMMERCE`; `rerelease_hint` from stripped annotations; no popularity tiebreak; MatchResult mapping: match→`winner`, ambiguous→`tied`, any other review→`MatchResult(None, (), reason=...)`, create→`MatchResult(None)`.
- `match_owned(title, year, candidates, *, embedded_year=False, runtime_min=None)`: `year_kind = DATABASE if embedded_year else COMMERCE`; hint from stripped annotations; no popularity tiebreak.
- `pick_tmdb_match(title, year, candidates)`: candidates are `TmdbCandidate`s → `Candidate(id=tmdb_id, popularity=popularity)` twice (title and original_title each indexed); `year_kind=DATABASE` in M1; `popularity_tiebreak=True`; returns `film_id` on match else `None`. **The old "first of top-3 within ±1 year regardless of title" fallback is deliberately dropped** — it was the Lawrence→731627 wrong-match vector.

**Intentional behavior changes** (update existing tests, don't "fix" back):
- `norm_title("Léon") == "leon"` (diacritics fold).
- `match_film("Tokyo Story", 1972, [(5, "Tokyo Story", 1953)])` → review `year-gap` (was: match). M2's arbiter auto-resolves this class; M1 keeps wrong-match ≈ 0 instead.
- `pick_tmdb_match` no-title-match near-year fallback → `None` (was: first of top 3).

---

### Task 1: Frozen baseline + benchmark harness scoring the CURRENT matchers

**Files:**
- Create: `scripts/matching_baseline.py`
- Create: `scripts/matching_benchmark.py`
- Test: `tests/unit/test_benchmark.py`

**Interfaces:**
- Produces: `matching_baseline.py` exposing today's `norm_title/clean_title/clean_apple_title/parse_apple_title/match_film/match_owned/pick_tmdb_match/MatchResult` + a local `TmdbCandidate` copy (self-contained — must not import `movie_brain.domain`, which Task 2+ changes).
- Produces: `matching_benchmark.py` exposing `GROUND_TRUTHS: list[Case]`, `run_case(case, matcher_set) -> CaseResult`, `replay_metacritic(matcher_set, films, titles) -> Rates`, `replay_apple(matcher_set, films, lines) -> Rates`, `main()`. `matcher_set` is a small namespace dataclass (`MatcherSet(norm_title=..., clean_title=..., match_film=..., match_owned=..., pick_tmdb_match=..., parse_apple_title=..., supports_runtime: bool)`) so Task 6 can plug the new matchers into the same runner.

- [ ] **Step 1: Freeze the baseline.** Copy `src/movie_brain/domain/matching.py` verbatim into `scripts/matching_baseline.py`; replace `from movie_brain.domain.models import TmdbCandidate` with an inline frozen dataclass copy of `TmdbCandidate`. Add header:

```python
"""FROZEN 2026-08-23 baseline matchers for the benchmark — verbatim copy of
domain/matching.py before the M1 evidence-scored core. Never edit; the
benchmark compares live matchers against this snapshot."""
```

- [ ] **Step 2: Write the ground-truth suite** in `scripts/matching_benchmark.py`. Case model + verdict vocabulary (`"match:<id>"`, `"review"`, `"create"` — for tmdb cases `"match:<id>"` / `"none"`):

```python
@dataclass(frozen=True)
class Case:
    name: str
    source: str                  # "metacritic" | "apple" | "tmdb"
    title: str                   # raw query title as the source shows it
    year: int | None             # the source's year field
    pool: tuple[PoolFilm, ...]   # synthetic corpus: (id, title, year, director, runtime_min)
    expect: str                  # CORRECT verdict, e.g. "match:1"
    runtime_min: int | None = None       # apple v2 evidence (baseline ignores)
    tmdb: tuple[TmdbCand, ...] = ()      # tmdb cases: (tmdb_id, title, original_title, year, popularity)
```

Bank ALL of these (ids are per-case-local; `expect` is correct behavior — baseline is allowed to fail):

| name | source | query | pool / tmdb candidates | expect |
|---|---|---|---|---|
| lawrence-mc-rerelease | metacritic | "Lawrence of Arabia (re-release)", 2002 | (1, "Lawrence of Arabia", 1962) | match:1 |
| lawrence-tmdb | tmdb | "Lawrence of Arabia", 2002 | (947,"Lawrence of Arabia","…",1962,40.0), (731627,"Lawrence: After Arabia","…",2002,2.0), (99,"Arabia","…",1990,1.0) | none |

(731627's year is 2002 ON PURPOSE: the baseline's "first of top-3 within ±1 year" fallback must reproduce the banked wrong match `match:731627`; the new matcher has no title-blind fallback and must return none.)
| stop-making-sense-no-runtime | apple | "Stop Making Sense", 2023 | (1,"Stop Making Sense",1984,None,88) | review |
| stop-making-sense-runtime | apple | "Stop Making Sense", 2023, runtime_min=88 | (1,"Stop Making Sense",1984,None,88) | match:1 |
| rear-window-embedded | apple | "Rear Window (1954)", 2013 | (1,"Rear Window",1954,"Alfred Hitchcock",112) | match:1 |
| vertigo-control | apple | "Vertigo (1958)", 1958 | (1,"Vertigo",1958,…) | match:1 |
| strangelove-control | metacritic | "Dr. Strangelove", 1964 | (1,"Dr. Strangelove",1964,…) | match:1 |
| kill-bill-vol-1 | metacritic | "Kill Bill: Vol. 1", 2003 | (1,"Kill Bill: Volume 1",2003), (2,"Kill Bill: Volume 2",2004) | match:1 |
| kill-bill-stay-distinct | metacritic | "Kill Bill: Vol. 2", 2004 | same pool | match:2 |
| diacritic-fold | metacritic | "Tête", 2007 | (1,"Tete",2007) | match:1 |
| ampersand | apple | "Willy Wonka & the Chocolate Factory", 1971 | (1,"Willy Wonka and the Chocolate Factory",1971) | match:1 |
| bracket-rerelease | metacritic | "The Red Shoes [re-release]", 2023 | (1,"The Red Shoes",1948) | match:1 |
| restored-version | apple | "The Leopard (Restored Version)", 2004 | (1,"The Leopard",1963) | match:1 |
| directors-edition-dash | apple | "Star Trek: The Motion Picture – The Director's Edition", 2022 | (1,"Star Trek: The Motion Picture",1979) | match:1 |
| nosferatu-remake-missing | apple | "Nosferatu", 2024, runtime_min=132 | (1,"Nosferatu",1922,None,94) | review |
| nosferatu-remake-present | apple | "Nosferatu", 2024 | (1,"Nosferatu",1922), (2,"Nosferatu",2024) | match:2 |
| star-is-born-2018 | apple | "A Star Is Born", 2018 | (1,…,1937),(2,…,1954),(3,…,1976),(4,…,2018) | match:4 |
| body-snatchers-78 | apple | "Invasion of the Body Snatchers", 1978 | (1,…,1956),(2,…,1978) | match:2 |
| subtitle-prefix | apple | "Hearts of Darkness", 1991 | (1,"Hearts of Darkness: A Filmmaker's Apocalypse",1991) | match:1 |
| subtitle-weak-no-year | apple | "Hearts of Darkness", None | same pool | review |
| solaris-popularity-tie | tmdb | "Solaris", 1972 | (1,"Solaris",2002,9.0),(2,"Solaris",1972,5.0),(3,"Solaris",1972,8.0) | match:3 |
| solaris-mc-wrong-era | metacritic | "Solaris", 1972 | (9,"Solaris",2002) | create |
| yearless-candidate | metacritic | "Trio", 1950 | (3,"Trio",None) | match:3 |
| yearless-query | metacritic | "Trio", None | (3,"Trio",1950) | match:3 |
| owned-tie | apple | "Twin", 1979 | (1,"Twin",1978),(2,"Twin",1980) | review |

- [ ] **Step 3: Case runner + rates.** `run_case` dispatches by source: metacritic → `clean_title` then `match_film` against pool rows whose `norm_title(title)` matches (replicating `match_archive`'s by_norm bucket); apple → `parse_apple_title`, embedded-year-else-field, `match_owned` (pass `runtime_min`/`embedded_year` only when `matcher_set.supports_runtime`); tmdb → `pick_tmdb_match`. Map returns onto the verdict vocabulary exactly as the live callers do (winner→match, tied→review, no-winner-with-candidates→review for apple, no-winner→create for metacritic/apple-empty, tmdb None→none).
- [ ] **Step 4: Archive replay.** `main()` reads config dir via `movie_brain.infrastructure.config` default (honor `MOVIE_BRAIN_CONFIG_DIR`); loads films read-only:

```python
conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
rows = conn.execute(
    "SELECT f.id, f.title, f.year, COALESCE(f.director, json_extract(o.payload,'$.Director')), "
    "json_extract(o.payload,'$.Runtime') FROM films f LEFT JOIN omdb o ON o.film_id=f.id"
).fetchall()
```

(`"N/A"`→None; `"91 min"`→91.) Replay: every parsed MC archive title through the metacritic path, every Apple archive line (glob `owned-*.txt`, latest file) through the apple path. `Rates = (n, match%, review%, create%)`.
- [ ] **Step 5: Report.** Print per-case table (case, expect, baseline verdict, PASS/FAIL) + summary (`baseline: N gt-pass / M gt-fail; wrong-matches (matched a different id than expected): K`) + archive rates. Distinguish **wrong-match** (verdict `match:X` where expect was `match:Y`, `review`, `create`, or `none`) from mere non-pass.
- [ ] **Step 6: Smoke test** `tests/unit/test_benchmark.py`: load the script via `importlib.util.spec_from_file_location`, assert case names unique, run `run_case` for `strangelove-control` + `lawrence-tmdb` with the baseline `MatcherSet` and assert observed verdicts (`match:1`, `match:731627` — the banked wrong match must reproduce), assert rate math on a 4-item synthetic list.
- [ ] **Step 7: Run** `uv run pytest tests/unit/test_benchmark.py -v` → PASS; `uv run python scripts/matching_benchmark.py` → runs end-to-end; `uv run ruff check scripts/` → clean.
- [ ] **Step 8: Record the baseline numbers** (gt pass/fail/wrong-match counts, archive rates) as a `## Baseline (Task 1)` section appended to THIS plan file.
- [ ] **Step 9: Commit** `bench: baseline harness — current matchers scored before the overhaul`

### Task 2: Normalization fixes + unified annotation grammar

**Files:**
- Modify: `src/movie_brain/domain/matching.py` (norm_title, new split_annotations/EDITION_ANNOTATIONS, rewire clean_title/clean_apple_title)
- Test: `tests/unit/test_matching.py`

**Interfaces:**
- Produces: `norm_title(str) -> str` (new folds); `EDITION_ANNOTATIONS: tuple[str, ...]`; `split_annotations(title: str) -> tuple[str, tuple[str, ...]]`; `clean_title` (MC: year-paren + editions) and `clean_apple_title` (editions only) preserved as names; `parse_apple_title` unchanged signature.

- [ ] **Step 1: Failing tests** — add to `tests/unit/test_matching.py`:

```python
def test_norm_title_folds_diacritics():
    assert norm_title("Tête") == "tete"
    assert norm_title("Léon") == "leon"

def test_norm_title_ampersand_and_volume():
    assert norm_title("Willy Wonka & the Chocolate Factory") == norm_title("Willy Wonka and the Chocolate Factory")
    assert norm_title("Kill Bill: Vol. 1") == norm_title("Kill Bill: Volume 1")
    assert norm_title("Kill Bill Vol 2") == norm_title("Kill Bill Volume 2")
    assert norm_title("Volcano") == "volcano"  # \bvol\b must not fire inside words

def test_split_annotations_grammar():
    assert split_annotations("The Red Shoes [re-release]") == ("The Red Shoes", ("re-release",))
    assert split_annotations("The Leopard (Restored Version)") == ("The Leopard", ("restored version",))
    assert split_annotations("Star Trek: The Motion Picture – The Director's Edition") == ("Star Trek: The Motion Picture", ("director's edition",))
    assert split_annotations("Blade Runner (Director's Cut) (4K)") == ("Blade Runner", ("4k", "director's cut"))
    assert split_annotations("Fanny (Part One)") == ("Fanny (Part One)", ())     # unknown parenthetical survives
    assert split_annotations("(Unrated)") == ("(Unrated)", ())                   # never strip to empty
```

Also update `test_norm_title_is_punctuation_and_case_insensitive` (`"Léon"` line) — diacritic fold is now intentional.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_matching.py -v` → new tests FAIL (`split_annotations` undefined; norm assertions differ).
- [ ] **Step 3: Implement** in `domain/matching.py`:

```python
import unicodedata

def norm_title(title: str) -> str:
    t = unicodedata.normalize("NFKD", title.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.replace("&", " and ").replace("$", "s")
    t = re.sub(r"\bvol\b\.?", "volume", t)
    return "".join(ch for ch in t if ch.isalnum())

EDITION_ANNOTATIONS: tuple[str, ...] = (…as listed in the evidence model…)
_EDITION_ALT = "|".join(re.escape(a) for a in EDITION_ANNOTATIONS)
_EDITION_RE = re.compile(
    r"\s*(?:\((?:the\s+)?(" + _EDITION_ALT + r")\)"
    r"|\[(?:the\s+)?(" + _EDITION_ALT + r")\]"
    r"|[–—-]\s+(?:the\s+)?(" + _EDITION_ALT + r"))\s*$",
    re.IGNORECASE,
)

def split_annotations(title: str) -> tuple[str, tuple[str, ...]]:
    found: list[str] = []
    t = title
    while (m := _EDITION_RE.search(t)) and t[: m.start()].strip():
        found.append(next(g for g in m.groups() if g).casefold())
        t = t[: m.start()].strip()
    return t, tuple(found)

def clean_apple_title(title: str) -> str:
    return split_annotations(title)[0]
```

`clean_title` (MC) = loop of: strip trailing `(YYYY)`/editions — keep its current docstring contract (`"Dekalog (1988)"`→`"Dekalog"`, `"Fanny (Part One)"` untouched). Delete the now-redundant `_APPLE_ANNOTATIONS`/`_APPLE_ANNOTATION` block. Keep old `_ANNOTATION` only if `clean_title` still uses it.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_matching.py tests/unit/test_appletv.py -v` → PASS (fix any existing expectations that the grammar legitimately changes; `parse_apple_title` table must still pass as-is).
- [ ] **Step 5: Full check** `uv run pytest && uv run ruff check . && uv run mypy` → green.
- [ ] **Step 6: Commit** `match: fold diacritics/&/vol in norm_title; one annotation grammar for all sources`

### Task 3: Candidate index + evidence-scored core

**Files:**
- Modify: `src/movie_brain/domain/matching.py`
- Test: `tests/unit/test_matching.py`

**Interfaces:**
- Consumes: Task 2's `norm_title`, `split_annotations`.
- Produces: `YearKind`, `Candidate`, `MatchQuery`, `MatchVerdict`, `Arbiter`, `CandidateIndex` (`__init__(candidates: Iterable[Candidate])`, `.add(c)`, `.lookup(title: str) -> tuple[int, list[Candidate]]` returning `(level, hits)` or `(‑1, [])`), `match_candidates(query, index, *, rerelease_hint=False, popularity_tiebreak=False, arbiter: Arbiter | None = None) -> MatchVerdict` — exact semantics in "The evidence model" section above, which is normative for this task.

- [ ] **Step 1: Failing tests** — one test per failure class (write them all before implementing):

```python
def C(id, title, year, director=None, runtime=None, pop=None):
    return Candidate(id, title, year, director, runtime, pop)

class TestCandidateIndex:
    def test_l0_exact_beats_l1(self): ...          # "Nosferatu" → level 0
    def test_l1_annotation_stripped(self):
        idx = CandidateIndex([C(1, "The Leopard", 1963)])
        assert idx.lookup("The Leopard (Restored Version)") == (1, [C(1, "The Leopard", 1963)])
    def test_l2_subtitle_prefix_requires_two_words(self):
        idx = CandidateIndex([C(1, "Hearts of Darkness: A Filmmaker's Apocalypse", 1991)])
        level, hits = idx.lookup("Hearts of Darkness")
        assert level == 2 and hits[0].id == 1
        # single-word prefix never indexes: "Ran: Something" must NOT be reachable via "Ran"

class TestMatchCandidates:
    # commerce year: neutral-with-gap, disqualifying-early
    def test_commerce_gap_no_corroboration_reviews(self):     # Stop Making Sense, no runtime → review("year-gap")
    def test_commerce_gap_with_runtime_matches(self):          # runtime 88≈88 → match
    def test_commerce_gap_with_rerelease_hint_matches(self):   # Lawrence MC → match
    def test_commerce_year_earlier_than_all_candidates_creates(self):  # MC "Solaris" 1972 vs film 2002 → create (distinct earlier film)
    def test_database_year_two_off_reviews(self):              # embedded 1954 vs cand 1952 → review("conflict"), never twin
    # director / runtime evidence
    def test_director_conflict_reviews(self): ...              # director mismatch disqualifies → review("conflict")
    def test_shared_director_in_comma_list_supports(self):     # "Ken Annakin, Harold French" vs "Harold French"
    def test_runtime_divergence_reviews(self):                 # 132 vs 94 (>15%) disqualifies → review("conflict")
    # verdicts
    def test_no_candidates_creates(self): ...
    def test_tie_reviews_with_tied_ids(self): ...
    def test_popularity_tiebreak_only_when_enabled(self): ...  # same score, pop 8 vs 5 → match with flag, review without
    def test_l2_alone_without_year_reviews_weak_title(self): ...
    # arbitration hook (interface only)
    def test_arbiter_hit_reviews_remake_suspected(self):       # arbiter=lambda t,y: True
    def test_arbiter_miss_matches_original(self):              # arbiter=lambda t,y: False
```

- [ ] **Step 2: Run** → FAIL (names undefined).
- [ ] **Step 3: Implement** the types + index + scorer exactly per the evidence model. Keep it one pure module — no imports beyond stdlib + `movie_brain.domain.models`. Suggested internals: `_score(query, cand, level, year_kind) -> tuple[int, bool, bool] | None` returning `(score, gap_flag, corroborated)` or None when disqualified with a `_DisqualReason` (year vs other) tracked for verdict step 2.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_matching.py -v` → PASS.
- [ ] **Step 5: Full check** `uv run pytest && uv run ruff check . && uv run mypy` → green (wrappers untouched so far — suite must still pass).
- [ ] **Step 6: Commit** `match: evidence-scored core — three-level index, source-aware years, tie→review`

### Task 4: Wrappers become policy shells; callers enriched

**Files:**
- Modify: `src/movie_brain/domain/matching.py` (rewrite `match_film`, `match_owned`, `pick_tmdb_match`; `MatchResult` gains `reason: str | None = None`)
- Modify: `src/movie_brain/infrastructure/database.py:376` (`films_for_matching`)
- Modify: `src/movie_brain/application/owned.py`, `src/movie_brain/application/metacritic.py`
- Test: `tests/unit/test_matching.py`, `tests/unit/test_database.py`, existing step_defs (`tests/step_defs/` owned + metacritic scenarios must stay green)

**Interfaces:**
- Consumes: Task 3's core.
- Produces:
  - `MatchResult(winner, tied=(), reason=None)` — old positional equality still holds.
  - `match_film(mc_title: str, mc_year: int | None, candidates: list[tuple[int, str, int | None]] | CandidateIndex) -> MatchResult`
  - `match_owned(title: str, year: int | None, candidates: list[tuple[int, str, int | None]] | CandidateIndex, *, embedded_year: bool = False, runtime_min: int | None = None) -> MatchResult`
  - `pick_tmdb_match(title: str, year: int | None, candidates: list[TmdbCandidate]) -> int | None`
  - `build_candidate_index(rows: Iterable[FilmRow]) -> CandidateIndex`
  - `Repository.films_for_matching() -> list[FilmRow]` where `FilmRow = NamedTuple(id: int, title: str, year: int | None, director: str | None, runtime_min: int | None, omdb_mc: int | None)`

- [ ] **Step 1: Failing tests.** Update `test_matching.py` for the three intentional changes (Tokyo Story → `MatchResult(None, (), "year-gap")`; tmdb fallback tests → `None`; keep every other existing expectation). Add wrapper-policy tests: `match_owned(..., embedded_year=True)` tight; `match_owned` field-year gap + `runtime_min` corroboration matches; a plain 3-tuple candidates list still works (back-compat coercion); `match_film` maps core review reasons into `MatchResult.reason`. Add `test_database.py` case: seed a film with NULL director + omdb payload `{"Director": "Jane Doe", "Runtime": "91 min"}` → `films_for_matching()` row has `("Jane Doe", 91)`; payload `"N/A"` values → `None`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
  - `FilmRow` NamedTuple in `database.py`; SQL:

```sql
SELECT f.id, f.title, f.year,
       COALESCE(f.director, NULLIF(json_extract(o.payload, '$.Director'), 'N/A')) AS director,
       NULLIF(json_extract(o.payload, '$.Runtime'), 'N/A') AS runtime,
       o.metacritic
FROM films f LEFT JOIN omdb o ON o.film_id = f.id ORDER BY f.id
```

  runtime parsed in Python: `int(m.group(1)) if (m := re.match(r"(\d+) min", r)) else None`.
  - Wrappers: coerce list inputs (`tuple` len 3 → `Candidate(id, title, year)`; already-`Candidate` passthrough; `CandidateIndex` passthrough) then call the core with their policy flags; map `MatchVerdict` → `MatchResult` (match→winner; ambiguous→tied; other review→reason; create→bare `MatchResult(None)`).
  - `owned.py`: replace the `by_norm` dict with `index = build_candidate_index(repo.films_for_matching())`; per title call `match_owned(cleaned, year, index, embedded_year=embedded_year is not None)` — `runtime_min` is wired in Task 5 when `OwnedTitle` gains the field (do NOT reference `t.runtime_min` in this task; it does not exist yet). Verdict mapping keeps EXACT current review reasons: winner→match; tied→`ambiguous-owned`; reason set→`year-drift`; bare `MatchResult(None)`→create path unchanged (including the key-collision fallback and `index.add(...)` replacing the old `by_norm[...].append`).
  - `metacritic.py`: build index once from `films_for_matching()` rows; `match_film(cleaned, t.year, index)`; winner→claim slug as today; tied→`ambiguous-title` as today; **`result.reason` set (non-tie review, e.g. year-gap band) → queue `ReviewEntry("year-gap", value=t.slug, detail=f"{t.title!r} ({t.year}) vs …")`** — this is load-bearing: `promote_top_n` skips slugs present in open reviews, so without this entry a review-band title (Tokyo Story 1972) would fall through to promotion and CREATE a twin. Bare no-winner (create verdict) stays unclaimed exactly as today. `expected_missed` loop reads `row.omdb_mc` from `FilmRow`. Add a step_def or unit assertion: a year-gap staged title is NOT promoted by `promote_top_n` and lands in `match_review`.
- [ ] **Step 4: Run** `uv run pytest -v` → whole suite PASS (step_defs prove wrapper policies per source).
- [ ] **Step 5:** `uv run ruff check . && uv run mypy` → green.
- [ ] **Step 6: Commit** `match: wrappers are policy shells over the shared core; candidates carry director+runtime`

### Task 5: Apple export v2 — runtime column

**Files:**
- Modify: `src/movie_brain/infrastructure/appletv.py`, `src/movie_brain/domain/models.py` (`OwnedTitle`), `src/movie_brain/application/owned.py` (pass runtime)
- Test: `tests/unit/test_appletv.py`

**Interfaces:**
- Produces: `OwnedTitle(title: str, year: int | None, runtime_min: int | None = None)`; `parse_export` accepts 2-column (old archives) and 3-column lines.

- [ ] **Step 1: Failing tests:**

```python
def test_parse_export_v2_three_columns():
    text = "Vertigo (1958)\t1958\t7702.5\nOld Line\t1990\n"
    titles = appletv.parse_export(text)
    assert titles[0] == OwnedTitle("Vertigo (1958)", 1958, 128)   # 7702.5 s → round(/60) = 128 min
    assert titles[1] == OwnedTitle("Old Line", 1990, None)        # v1 archive replays

def test_parse_export_missing_value_duration():
    assert appletv.parse_export("X\t1990\tmissing value\n")[0].runtime_min is None
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** AppleScript: add `set ds to duration of (every track of library playlist 1 whose media kind is movie)` to the batch reads, extend the count-mismatch guard to `ds`, emit `item i of ns & tab & item i of ys & tab & item i of ds`. Parser: `parts = line.split("\t")`; 2 parts → old path; 3 parts → parse duration as float seconds (`round(seconds / 60)` minutes; non-numeric like `missing value` → None). `OwnedTitle` gains the defaulted field (frozen dataclass — old 2-arg constructions everywhere stay valid). `owned.py` passes `runtime_min=t.runtime_min` (already wired in Task 4's call — just confirm the field flows).
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_appletv.py tests/step_defs -v` → PASS.
- [ ] **Step 5:** Full `uv run pytest && uv run ruff check . && uv run mypy` → green.
- [ ] **Step 6: Commit** `owned: export v2 carries runtime — matcher evidence against remaster years`

### Task 6: Benchmark comparison — prove dominance

**Files:**
- Modify: `scripts/matching_benchmark.py`
- Test: `tests/unit/test_benchmark.py`

**Interfaces:**
- Consumes: baseline `MatcherSet` (Task 1) + a new `MatcherSet` built from `movie_brain.domain.matching` (with `supports_runtime=True`: apple cases pass `embedded_year`/`runtime_min` kwargs).
- Produces: side-by-side report; `--assert-dominance` exit gate.

- [ ] **Step 1: Failing test:** extend `test_benchmark.py` — run `run_case` for `lawrence-tmdb`, `kill-bill-vol-1`, `diacritic-fold`, `stop-making-sense-runtime` with the NEW matcher set; assert observed == expect for all four; assert `dominates(baseline_summary, new_summary)` logic: True iff new wrong-match count ≤ baseline's AND new wrong == 0.
- [ ] **Step 2: Run** → FAIL (new `MatcherSet` not built yet).
- [ ] **Step 3: Implement:** `new_matcher_set()` importing from `movie_brain.domain.matching`; report gains columns (case | expect | baseline | new | Δ); archive replay runs both sets (new set builds a `CandidateIndex` from enriched read-only rows — director/runtime included); summary block prints wrong-match / review% / auto-match% per matcher per corpus; `--assert-dominance` exits 1 unless new gt-wrong == 0 and review% < 5.0 on both archive replays (print the numbers regardless).
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_benchmark.py -v` → PASS; then `uv run python scripts/matching_benchmark.py --assert-dominance` → exit 0. **If the review% gate fails:** do NOT loosen wrong-match safety (no gap-band auto-matching). Inspect the review-bucket sample the report prints; the permitted tuning knobs are only (a) `EDITION_ANNOTATIONS` additions, (b) the rerelease-hint set, (c) L2 word-count floor. If the gate still fails, record the real number, mark the task blocked, and stop for the user — that is an M2-arbiter scope question, not an M1 knob.
- [ ] **Step 5: Record final numbers** in a `## Dominance run (Task 6)` section of this plan file (both matchers, both corpora, gt table).
- [ ] **Step 6: Commit** `bench: new matcher vs frozen baseline — dominance gate`

### Task 7: Docs, spec Done line, M2 handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-08-23-matching-overhaul-design.md` (M1 section)
- Create: `docs/superpowers/handoffs/2026-08-23-m2-matching-handoff.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1:** Append to the spec's M1 section: `**Done <date>:** benchmark — baseline <numbers> vs new <numbers>; wrong-match 0 on ground truths; review <n>% (target <5%). Wrappers are policy shells; export v2 live; no pipeline/schema change.` (real numbers from Task 6).
- [ ] **Step 2:** Write the M2 handoff: status (files landed, benchmark numbers, worktree/branch), M2 scope verbatim from the spec (shared matcher in `tmdb_step`, year write-back + key recompute + `year-collision` queue, one-shot rematch CLI for the 232 misses, arbiter wiring — the `Arbiter` interface exists and is tested with stubs), carried data debt (49 dup groups, 481 tmdb review rows, 7 apple-tv year-drift remakes, 26 suspect-year promotions), and the live finding: **film 3086 Lawrence still has no tmdb external id — the nightly rematch never fired; M2's rematch pass covers it.** Include an entry-point prompt paragraph like the M1 one.
- [ ] **Step 3:** CLAUDE.md rule updates (keep terse): matching bullet — one evidence-scored core in `domain/matching.py`, wrappers are per-source policy; `owned import` archives are 3-column since v2 (2-column replays fine); benchmark command `uv run python scripts/matching_benchmark.py`.
- [ ] **Step 4:** `uv run pytest && uv run ruff check . && uv run mypy` one last time → green. Playwright: `uv run pytest tests/web -v` → unchanged surfaces pass.
- [ ] **Step 5: Commit** `docs: M1 done — benchmark numbers banked; M2 handoff`
- [ ] **Step 6:** Use superpowers:finishing-a-development-branch to integrate `feature/M1-matching-overhaul`.

## Self-review notes

- Spec coverage: normalization fixes → Task 2; annotation grammar → Task 2; three-level index → Task 3; evidence scorer incl. director/runtime/popularity/arbiter hook → Task 3; policy wrappers with kept signatures → Task 4; source-aware year policy → Tasks 3–4; Apple export v2 → Task 5; benchmark-first with baseline → Task 1, dominance → Task 6; Done-line + M2 handoff → Task 7. Out of M1 by design: arbiter wiring, year write-back, rematch, merges.
- The Tokyo-Story / tmdb-fallback / Léon expectation changes are deliberate spec consequences, listed under "Intentional behavior changes" — implementers must not "fix" them back.
- `scripts/matching_baseline.py` is exempt from the DRY instinct: it is a frozen snapshot, duplication is its job.
