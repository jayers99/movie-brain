# Power Search — Plan B: the bar (parser, resolution, `/api/search`, dashboard)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One search bar above the chips: freeform text searches title, people, characters, genre, keywords and plot at once; `field: value` narrows to one field; a misspelled name is corrected visibly, never silently; every existing chip, scope and column filter keeps working mid-search.

**Architecture:** Parsing is a pure function in `domain/search.py`. Fuzzy fields are resolved to exact ids/values in `application/search.py` through small repository candidate queries, with ranking done in Python by a token-aware `difflib` similarity (the FTS5 trigram index is a candidate GENERATOR only — verified on the live index: `bogrt`'s FTS rank puts "Ogranya" first). `Repository.search_films` turns the resolved filters into one ANDed SQL query plus a scored freeform union. `GET /api/search` returns a film-id set; `app.js` intersects it with its existing pipeline (yt-brain's `semanticMatchIds` pattern, spec D4) — no filter logic moves.

**Tech Stack:** Python 3.12, SQLite ≥ 3.50 (FTS5 trigram + unicode61, `bm25()` with column weights — verified), `difflib` (stdlib), Flask, vanilla JS, pytest + pytest-bdd + Playwright. No new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-09-06-power-search-design.md` §7–§10, D4–D8, D13. Plan A (`docs/superpowers/plans/2026-09-06-power-search-a-credits.md`) is merged and applied live: 4,569 films enriched, 168,511 persons, 286,429 credit rows.

## Global Constraints

- **No new runtime dependency.** `pyproject.toml` dependencies stay `typer`, `rich`, `flask`, `requests`. Similarity uses `difflib.SequenceMatcher` from the stdlib.
- **`domain/` imports nothing else; `application/` has no SQL and no HTTP** (hexagonal rule in CLAUDE.md).
- **Field filters are exact filters over the whole catalogue, never a post-filter over a top-N** (spec D6).
- **Spelling correction is exact-first, then offered and visible; never silent** (D7). Correction runs over person names, characters, keywords and titles only — never over freeform prose (D8). A quoted value is exact and is never corrected.
- **Field syntax is bare, run-to-next-field** (D5): `genre: film noir`. Quotes are legal, never required. Multiple fields AND; the same field repeated ORs. An unknown field name is not an error — it becomes freeform text plus a `hint`.
- **The search executes server-side and returns an id set; `app.js`'s chips, scope toggle, list picker and column filters intersect with it and none of their logic moves** (D4). While a freeform search is active and no column sort is set, rank leads the sort; clearing the bar restores the previous order. URL state carries `q=`.
- **The bar's `<input>` never carries class `chip`** and lives OUTSIDE `#chips` — the `#chips` click handler would add `undefined` to the chip set (CLAUDE.md, list-picker precedent).
- **Every film read model carries the `_NOT_DISPOSED` guard**; `search_films` must too.
- **Constants** (in `domain/search.py`): `CORRECTION_FLOOR = 0.8`, `SUGGESTION_FLOOR = 0.6`, `MAX_SUGGESTIONS = 3`, `CANDIDATE_LIMIT = 2000`, freeform column weights title `10.0`, overview `2.0`, plot `1.0`; person-name freeform hit `5.0`, character hit `4.0`, genre/keyword hit `3.0`, a direct `films.title` substring hit `10.0`.
- **Crew-job sets, verified against the live vocabulary 2026-09-06** (spec §7.2 is corrected in Task 8):
  - `director`: `Director`
  - `writer`: `Screenplay`, `Writer`, `Story`, `Novel`, `Original Story`, `Dialogue`, `Adaptation`, `Author`, `Book`, `Short Story`, `Theatre Play`, `Scenario Writer`, `Co-Writer`, `Screenstory`, `Original Film Writer`
  - `cinematographer` (alias `dp`): `Director of Photography`, `Cinematography`
  - `editor`: `Editor`
  - `composer` (alias `music`): `Original Music Composer`, `Music`
  - `producer`: `Producer`, `Executive Producer`, `Co-Producer`, `Associate Producer`
  - `crew`: any crew job
- **Markdown prose is never hard-wrapped** (owner's global rule) — Task 8's doc edits are single lines.
- **Commit messages:** one line, the *why*, plus the two attribution trailers used on this repo's recent commits. Work on branch `feature/power-search-b-bar` off `main`.

## One deliberate deviation from the spec, decided here

Spec §8 says stage 3 is "one SQL statement". `search_films` runs the field filters as ONE statement but computes freeform scores with a handful of small SELECTs merged in Python inside one connection. Reason: three FTS tables with different tokenizers plus a `films.title` LIKE cannot be scored in one statement without a CTE that no reviewer can read; the contract the spec cares about — one repository call, exact filters over the whole catalogue, freeform only ranks — holds. Task 8 amends §8's sentence.

## A known limitation, stated so it is not mistaken for a bug

`film_text` (title/overview/plot for FTS) is written only by `enrich credits`. Films with no TMDB id (63) and never-enriched films have no `film_text` row, so freeform PLOT search cannot see them. Freeform TITLE search still reaches every film through a direct `films.title` substring scan (Task 4). Not fixing in this plan.

---

## File structure

| File | Responsibility |
|---|---|
| `src/movie_brain/domain/search.py` | Pure: `FIELDS` registry + aliases + job sets, `parse_query`, `parse_year_range`, `norm_genre`, `fts_words`, `similarity`, `rank_candidates`, `Filter`/`Term`/`ParsedQuery` types, constants |
| `src/movie_brain/infrastructure/database.py` | `# search` section: `persons_named`, `person_candidates`, `characters_named`, `character_candidates`, `keyword_candidates`, `title_candidates`, `search_films` |
| `src/movie_brain/application/search.py` *(new)* | `run_search(repo, text) -> SearchResult`: parse → resolve (corrections/suggestions/hint) → `search_films` |
| `src/movie_brain/web/app.py` | `GET /api/search` |
| `src/movie_brain/web/templates/index.html`, `static/app.css`, `static/app.js` | The bar, its note line, state/URL/fetch/intersection/rank |
| `tests/unit/test_search.py`, `tests/unit/test_database.py`, `tests/features/search.feature` + `tests/step_defs/test_search.py`, `tests/web/test_api.py`, `tests/web/conftest.py`, `tests/web/test_dashboard.py` | Tests per layer |
| `CLAUDE.md`, `docs/backlog.md`, the spec | Task 8 docs |

---

### Task 1: The parser — `parse_query`, fields, year ranges, genre normalisation

**Files:**
- Modify: `src/movie_brain/domain/search.py` (append; `trigram_query` already lives here)
- Test: `tests/unit/test_search.py` (append)

**Interfaces:**
- Produces (all in `movie_brain.domain.search`):

```python
CORRECTION_FLOOR = 0.8; SUGGESTION_FLOOR = 0.6; MAX_SUGGESTIONS = 3; CANDIDATE_LIMIT = 2000
@dataclass(frozen=True) class FieldSpec: name: str; kind: str; credit_kind: str | None; jobs: tuple[str, ...]
FIELDS: dict[str, FieldSpec]          # canonical name → spec; kinds: person | character | title | genre | keyword | year | text
ALIASES: dict[str, str]               # every accepted token (canonical names and aliases) → canonical name
@dataclass(frozen=True) class Term: field: str; value: str; exact: bool     # field is canonical
@dataclass(frozen=True) class ParsedQuery: terms: tuple[Term, ...]; free: str; hints: tuple[str, ...]
def parse_query(text: str) -> ParsedQuery
def parse_year_range(value: str) -> tuple[int | None, int | None] | None   # '1946' → (1946, 1946); '1940-1949'; '1940-' → (1940, None); '-1949' → (None, 1949); junk → None
def norm_genre(text: str) -> str      # lowercase, strip everything but [a-z0-9]: 'Film-Noir' == 'film noir' == 'filmnoir'
def fts_words(text: str, min_len: int = 1) -> str   # 'hard boiled' → '"hard" "boiled"' (implicit AND); words shorter than min_len dropped; '' when nothing survives
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_search.py`:

```python
from movie_brain.domain.search import (
    ALIASES,
    FIELDS,
    ParsedQuery,
    Term,
    fts_words,
    norm_genre,
    parse_query,
    parse_year_range,
)


def test_freeform_only():
    assert parse_query("film noir") == ParsedQuery(terms=(), free="film noir", hints=())


def test_field_value_runs_to_end_of_input():
    assert parse_query("genre: film noir").terms == (Term("genre", "film noir", False),)


def test_field_value_runs_to_the_next_field_token():
    q = parse_query("actor: bogart genre: film noir")
    assert q.terms == (Term("actor", "bogart", False), Term("genre", "film noir", False))
    assert q.free == ""


def test_freeform_before_the_first_field_is_kept():
    q = parse_query("hard boiled private eye genre: film noir")
    assert q.free == "hard boiled private eye" and q.terms == (Term("genre", "film noir", False),)


def test_quotes_group_a_value_and_mark_it_exact():
    q = parse_query('actor: "Bogart" title: brazil')
    assert q.terms == (Term("actor", "Bogart", True), Term("title", "brazil", False))


def test_quoted_text_containing_a_field_token_is_freeform_not_a_field():
    q = parse_query('"crew: catering" title: brazil')
    assert q.free == "crew: catering" and q.terms == (Term("title", "brazil", False),)


def test_aliases_resolve_to_the_canonical_field():
    q = parse_query("cast: bacall role: vivian dp: hickox kw: whodunit")
    assert [t.field for t in q.terms] == ["actor", "character", "cinematographer", "keyword"]


def test_field_names_are_case_insensitive_and_colon_may_hug_the_value():
    assert parse_query("Director:hawks").terms == (Term("director", "hawks", False),)


def test_unknown_field_becomes_freeform_with_a_hint():
    q = parse_query("foo: bar actor: bogart")
    assert q.free == "foo: bar" and q.terms == (Term("actor", "bogart", False),)
    assert q.hints == ("unknown field 'foo'",)


def test_empty_value_becomes_freeform_with_a_hint():
    q = parse_query("actor:")
    assert q.terms == () and q.free == "actor:" and q.hints == ("field 'actor' has no value",)


def test_repeated_field_yields_two_terms():
    q = parse_query("actor: bogart actor: bacall")
    assert q.terms == (Term("actor", "bogart", False), Term("actor", "bacall", False))


def test_a_url_in_freeform_is_not_a_field():
    """'https:' would otherwise parse as a field named https."""
    q = parse_query("see https://example.com")
    assert q.terms == () and q.free == "see https://example.com" and q.hints == ("unknown field 'https'",)


def test_year_ranges():
    assert parse_year_range("1946") == (1946, 1946)
    assert parse_year_range("1940-1949") == (1940, 1949)
    assert parse_year_range("1940-") == (1940, None)
    assert parse_year_range("-1949") == (None, 1949)
    assert parse_year_range("nineteen") is None
    assert parse_year_range("1950-1940") is None  # inverted


def test_norm_genre_makes_omdb_tmdb_and_typed_forms_equal():
    assert norm_genre("Film-Noir") == norm_genre("film noir") == norm_genre("FILM NOIR") == "filmnoir"
    assert norm_genre("Sci-Fi") == "scifi" and norm_genre("Science Fiction") == "sciencefiction"


def test_fts_words_quotes_each_word_and_drops_short_ones_when_asked():
    assert fts_words('hard "boiled" eye') == '"hard" "boiled" "eye"'
    assert fts_words("a to bogart", min_len=3) == '"bogart"'
    assert fts_words("", min_len=3) == ""


def test_every_field_has_a_kind_and_every_alias_points_at_a_field():
    assert set(ALIASES.values()) <= set(FIELDS)
    assert {f.kind for f in FIELDS.values()} <= {"person", "character", "title", "genre", "keyword", "year", "text"}
    assert FIELDS["writer"].jobs == (
        "Screenplay", "Writer", "Story", "Novel", "Original Story", "Dialogue", "Adaptation", "Author", "Book",
        "Short Story", "Theatre Play", "Scenario Writer", "Co-Writer", "Screenstory", "Original Film Writer",
    )
    assert FIELDS["actor"].credit_kind == "cast" and FIELDS["crew"].credit_kind == "crew" and FIELDS["crew"].jobs == ()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_search.py -q`
Expected: FAIL at import — `ImportError: cannot import name 'ALIASES'`.

- [ ] **Step 3: Implement**

Append to `src/movie_brain/domain/search.py` (keep the existing module docstring and `trigram_query`; add `import re` and `from dataclasses import dataclass` to the imports; add `from collections.abc import Iterable` for Task 2):

```python
CORRECTION_FLOOR = 0.8  # a candidate at least this similar is used, and the correction is SHOWN (spec D7)
SUGGESTION_FLOOR = 0.6  # below CORRECTION_FLOOR but above this: offered as "did you mean", nothing used
MAX_SUGGESTIONS = 3
CANDIDATE_LIMIT = 2000  # trigram candidates fetched per lookup before Python ranks them
# freeform weights — where the text hit decides the rank (spec §8): title > person > character > genre/keyword > plot
W_TITLE, W_OVERVIEW, W_PLOT, W_PERSON, W_CHARACTER, W_TAG = 10.0, 2.0, 1.0, 5.0, 4.0, 3.0


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str  # person | character | title | genre | keyword | year | text
    credit_kind: str | None = None  # person fields: 'cast' or 'crew'
    jobs: tuple[str, ...] = ()  # person crew fields: TMDB job names; () = any crew job


_WRITER_JOBS = (
    "Screenplay", "Writer", "Story", "Novel", "Original Story", "Dialogue", "Adaptation", "Author", "Book",
    "Short Story", "Theatre Play", "Scenario Writer", "Co-Writer", "Screenstory", "Original Film Writer",
)
# The curated job sets (spec D9), verified against the live TMDB vocabulary on 2026-09-06.
FIELDS: dict[str, FieldSpec] = {
    "title": FieldSpec("title", "title"),
    "actor": FieldSpec("actor", "person", "cast"),
    "character": FieldSpec("character", "character"),
    "director": FieldSpec("director", "person", "crew", ("Director",)),
    "writer": FieldSpec("writer", "person", "crew", _WRITER_JOBS),
    "cinematographer": FieldSpec("cinematographer", "person", "crew", ("Director of Photography", "Cinematography")),
    "editor": FieldSpec("editor", "person", "crew", ("Editor",)),
    "composer": FieldSpec("composer", "person", "crew", ("Original Music Composer", "Music")),
    "producer": FieldSpec("producer", "person", "crew", ("Producer", "Executive Producer", "Co-Producer", "Associate Producer")),
    "crew": FieldSpec("crew", "person", "crew", ()),
    "genre": FieldSpec("genre", "genre"),
    "keyword": FieldSpec("keyword", "keyword"),
    "year": FieldSpec("year", "year"),
    "plot": FieldSpec("plot", "text"),
}
ALIASES: dict[str, str] = {name: name for name in FIELDS} | {
    "cast": "actor", "role": "character", "dp": "cinematographer", "music": "composer", "kw": "keyword", "overview": "plot",
}


@dataclass(frozen=True)
class Term:
    field: str  # canonical
    value: str
    exact: bool  # the value was quoted: never corrected


@dataclass(frozen=True)
class ParsedQuery:
    terms: tuple[Term, ...]
    free: str
    hints: tuple[str, ...]


# A token is: a double-quoted string (quotes may be doubled inside), OR a field token `name:` at a
# word start, OR a run of non-space. `(?<!\S)` keeps `https://…` from reading as field `https` —
# it does read as one, and then falls to "unknown field", which is the right outcome for a URL.
_TOKEN = re.compile(r'"((?:[^"]|"")*)"|(?<!\S)([A-Za-z_]+):|(\S+)')


def parse_query(text: str) -> ParsedQuery:
    """Bare, run-to-next-field grammar (spec §7.1, D5). Pure; never raises."""
    terms: list[Term] = []
    free: list[str] = []
    hints: list[str] = []
    current: str | None = None  # canonical field collecting a value
    buf: list[str] = []
    exact = False

    def flush() -> None:
        nonlocal current, buf, exact
        if current is not None:
            value = " ".join(buf).strip()
            if value:
                terms.append(Term(current, value, exact))
            else:
                free.append(current + ":")
                hints.append(f"field '{current}' has no value")
        current, buf, exact = None, [], False

    for m in _TOKEN.finditer(text):
        quoted, field, word = m.group(1), m.group(2), m.group(3)
        if field is not None:
            name = field.lower()
            if name in ALIASES:
                flush()
                current = ALIASES[name]
                continue
            hints.append(f"unknown field '{name}'")
            word = field + ":"  # falls through as ordinary text
        if quoted is not None:
            piece = quoted.replace('""', '"')
            if current is not None and not buf:
                exact = True
                buf.append(piece)
            elif current is not None:
                buf.append(piece)
            else:
                free.append(piece)
            continue
        if current is not None:
            buf.append(word)
        else:
            free.append(word)
    flush()
    return ParsedQuery(tuple(terms), " ".join(free).strip(), tuple(hints))


_YEAR = re.compile(r"^(\d{4})?-(\d{4})?$")


def parse_year_range(value: str) -> tuple[int | None, int | None] | None:
    v = value.strip()
    if v.isdigit() and len(v) == 4:
        return int(v), int(v)
    m = _YEAR.match(v)
    if not m or not (m.group(1) or m.group(2)):
        return None
    lo = int(m.group(1)) if m.group(1) else None
    hi = int(m.group(2)) if m.group(2) else None
    if lo is not None and hi is not None and lo > hi:
        return None
    return lo, hi


def norm_genre(text: str) -> str:
    """'Film-Noir', 'film noir' and 'FILM NOIR' are one genre; OMDb hyphenates, TMDB spaces."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def fts_words(text: str, min_len: int = 1) -> str:
    """Each word as its own quoted FTS5 string (implicit AND). Quotes inside a word are doubled.
    On a trigram table a word shorter than 3 cannot match, so callers pass min_len=3 there."""
    words = [w.strip('"') for w in text.split()]
    return " ".join('"' + w.replace('"', '""') + '"' for w in words if len(w) >= min_len)
```

Note on `test_quoted_text_containing_a_field_token_is_freeform_not_a_field`: the quoted token is consumed by the first regex alternative, so `crew:` inside it is never seen as a field — verify the test passes without special-casing.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_search.py -q` → all pass. Run `uv run ruff check . && uv run mypy` → clean.

- [ ] **Step 5: Commit**

```bash
git checkout -b feature/power-search-b-bar
git add src/movie_brain/domain/search.py tests/unit/test_search.py
git commit -m "the owner types genre: film noir, so the grammar reads a value to the next field, not to the next quote"
```

---

### Task 2: Similarity and candidate ranking (pure)

**Files:**
- Modify: `src/movie_brain/domain/search.py` (append)
- Test: `tests/unit/test_search.py` (append)

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True) class Candidate: key: int | str; name: str; weight: int   # key: person id or the canonical string; weight: credit/usage count (tiebreak)
@dataclass(frozen=True) class Ranked: key: int | str; name: str; score: float
def similarity(query: str, name: str) -> float                 # token-aware difflib ratio in [0, 1]
def rank_candidates(query: str, candidates: Iterable[Candidate]) -> list[Ranked]   # by score desc, weight desc, name asc
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_search.py` (extend the import to include `Candidate, rank_candidates, similarity`):

```python
def test_similarity_is_token_aware_so_a_surname_alone_scores_high():
    assert similarity("bogrt", "Humphrey Bogart") > 0.85
    assert similarity("humphrey bogrt", "Humphrey Bogart") > 0.9
    assert similarity("bogrt", "Lena Brogren") < 0.6


def test_similarity_is_case_insensitive_and_exact_is_one():
    assert similarity("HUMPHREY BOGART", "Humphrey Bogart") == 1.0


def test_rank_candidates_breaks_a_similarity_tie_on_weight_then_name():
    """On the live index 'bogrt' ties four Bogarts at 0.91 — the one with the most credits wins,
    and equal credits fall back to name order so the result is deterministic."""
    cands = [Candidate(1, "Jane Bogart", 1), Candidate(2, "Humphrey Bogart", 11), Candidate(3, "Lena Brogren", 40),
             Candidate(4, "Bogart Edwards", 11)]
    ranked = rank_candidates("bogrt", cands)
    assert [r.name for r in ranked[:3]] == ["Bogart Edwards", "Humphrey Bogart", "Jane Bogart"]
    assert ranked[0].score == ranked[1].score and ranked[-1].name == "Lena Brogren"


def test_rank_candidates_on_nothing_is_empty():
    assert rank_candidates("x", []) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_search.py -q` → `ImportError: cannot import name 'Candidate'`.

- [ ] **Step 3: Implement**

Append to `src/movie_brain/domain/search.py` (add `from difflib import SequenceMatcher` to the imports):

```python
@dataclass(frozen=True)
class Candidate:
    key: int | str  # person id, or the canonical string for characters/keywords/titles
    name: str
    weight: int  # how many credits/uses carry this name — the tiebreak between equally similar names


@dataclass(frozen=True)
class Ranked:
    key: int | str
    name: str
    score: float


def similarity(query: str, name: str) -> float:
    """Best of: the whole name, or any one token of it. 'bogrt' against 'Humphrey Bogart' is
    judged on 'bogart' (0.91), not on the full name (0.5). Verified on the live index: this is
    what lifts the Bogarts above 'Ogranya', which FTS's own rank preferred."""
    q = query.lower().strip()
    n = name.lower()
    best = SequenceMatcher(None, q, n).ratio()
    for token in n.split():
        best = max(best, SequenceMatcher(None, q, token).ratio())
    return best


def rank_candidates(query: str, candidates: Iterable[Candidate]) -> list[Ranked]:
    """Similarity desc, then the candidate's weight (credit count) desc, then name — so four
    Bogarts tied at 0.91 resolve to the one the catalogue credits most, deterministically."""
    cands = list(candidates)
    weights = {c.key: c.weight for c in cands}
    scored = [Ranked(c.key, c.name, similarity(query, c.name)) for c in cands]
    return sorted(scored, key=lambda r: (-r.score, -weights[r.key], r.name))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_search.py -q` → pass; `uv run ruff check . && uv run mypy` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/search.py tests/unit/test_search.py
git commit -m "a trigram index only proposes; the resolver has to rank, and it ranks on the surname"
```

---

### Task 3: Repository candidate queries

**Files:**
- Modify: `src/movie_brain/infrastructure/database.py` — new `# search (power search, Plan B)` section after `credits_summary`; import `CANDIDATE_LIMIT, Candidate, trigram_query` from `movie_brain.domain.search`.
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: `Candidate`, `trigram_query`, `CANDIDATE_LIMIT` (Tasks 1–2, Plan A); the Plan A `_credits()` test helper.
- Produces:

```python
def persons_named(self, name: str, credit_kind: str | None, jobs: tuple[str, ...]) -> list[int]      # exact, case-insensitive; filtered to persons holding a credit of that kind/job set
def person_candidates(self, text: str, credit_kind: str | None, jobs: tuple[str, ...]) -> list[Candidate]   # trigram OR-of-windows; key=person id, weight=credit count within the kind/job set
def characters_named(self, text: str) -> list[str]                                                    # canonical spellings whose lower() == text.lower()
def character_candidates(self, text: str) -> list[Candidate]                                          # key=name=canonical character string, weight=how many credit rows carry it
def keyword_candidates(self) -> list[Candidate]                                                       # every distinct keyword; key=name=keyword, weight=film count
def title_candidates(self) -> list[Candidate]                                                         # every live film title; key=film id, weight=0
```

`credit_kind`/`jobs` semantics: `("cast", ())` → cast rows; `("crew", ())` → any crew row; `("crew", jobs)` → crew rows whose `job` is in `jobs`; `(None, ())` → any credit.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_database.py` (add `from movie_brain.domain.search import Candidate` to the imports):

```python
def _seed_people(repo):
    """Two films: Alpha (Bogart as Marlowe, Hawks directing, Bogart also producing) and
    Beta (Jane Bogart as Nurse, Hawks directing). Bogart carries 2 credits, Jane 1."""
    day = date(2026, 9, 6)
    a = repo.create_film(Film("Alpha", 1946, None, ""))
    b = repo.create_film(Film("Beta", 1950, None, ""))
    repo.set_external_id(a, "tmdb", "910", day)
    repo.set_external_id(b, "tmdb", "911", day)
    repo.write_credits(a, _credits(), day)
    repo.write_credits(b, _credits(
        tmdb_id=911, title="Beta", original_title="Beta", overview="A nurse in the alpha ward.",
        keywords=("hospital",),
        cast=(CastRow(77, "Jane Bogart", "Nurse", 0),),
        crew=(CrewRow(2636, "Howard Hawks", "Director", "Directing"),),
    ), day)
    return a, b


def test_persons_named_is_exact_case_insensitive_and_job_aware(repo):
    a, b = _seed_people(repo)
    bogart = repo.persons_named("humphrey BOGART", "cast", ())
    assert len(bogart) == 1
    assert repo.persons_named("Humphrey Bogart", "crew", ("Director",)) == []      # he produces, never directs
    assert repo.persons_named("Humphrey Bogart", "crew", ("Producer",)) == bogart
    assert repo.persons_named("Howard Hawks", "crew", ()) != [] and repo.persons_named("Howard Hawks", "cast", ()) == []
    assert repo.persons_named("Nobody", None, ()) == []


def test_person_candidates_come_from_the_trigram_index_with_credit_counts(repo):
    _seed_people(repo)
    cands = {c.name: c for c in repo.person_candidates("bogrt", "cast", ())}
    assert {"Humphrey Bogart", "Jane Bogart"} <= set(cands)
    assert cands["Humphrey Bogart"].weight == 1 and cands["Jane Bogart"].weight == 1   # cast credits only
    assert "Howard Hawks" not in cands
    assert repo.person_candidates("bogrt", "crew", ("Producer",))[0].name == "Humphrey Bogart"
    assert repo.person_candidates("xx", "cast", ()) == []   # shorter than a trigram → nothing asked


def test_character_lookups(repo):
    _seed_people(repo)
    assert repo.characters_named("philip marlowe") == ["Philip Marlowe"]
    cands = repo.character_candidates("marlow")
    assert [c.name for c in cands] == ["Philip Marlowe"] and cands[0].weight == 1 and cands[0].key == "Philip Marlowe"


def test_keyword_and_title_candidates(repo):
    a, b = _seed_people(repo)
    kws = {c.name: c.weight for c in repo.keyword_candidates()}
    assert kws == {"film noir": 1, "private investigator": 1, "hospital": 1}
    titles = {c.name: c.key for c in repo.title_candidates()}
    assert titles == {"Alpha": a, "Beta": b}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -k "persons_named or person_candidates or character_lookups or keyword_and_title" -q` → `AttributeError: 'Repository' object has no attribute 'persons_named'`.

- [ ] **Step 3: Implement**

Add to `database.py`, after `credits_summary`:

```python
    # search (power search, Plan B) ------------------------------------------
    @staticmethod
    def _credit_clause(credit_kind: str | None, jobs: tuple[str, ...]) -> tuple[str, list[str]]:
        """SQL fragment (no leading AND) restricting film_credit rows to a field's kind/job set."""
        if credit_kind is None:
            return "1 = 1", []
        if credit_kind == "cast" or not jobs:
            return "fc.kind = ?", [credit_kind]
        return f"fc.kind = 'crew' AND fc.job IN ({','.join('?' * len(jobs))})", list(jobs)

    def persons_named(self, name: str, credit_kind: str | None, jobs: tuple[str, ...]) -> list[int]:
        clause, params = self._credit_clause(credit_kind, jobs)
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT p.id FROM person p JOIN film_credit fc ON fc.person_id = p.id "
                f"WHERE lower(p.name) = ? AND {clause} ORDER BY p.id",
                [name.lower().strip(), *params],
            ).fetchall()
            return [int(r["id"]) for r in rows]

    def person_candidates(self, text: str, credit_kind: str | None, jobs: tuple[str, ...]) -> list[Candidate]:
        """Every person sharing at least one trigram with `text`, restricted to the field's
        kind/job set, with their credit count in that set. Ranking is the caller's job."""
        match = trigram_query(text)
        if not match:
            return []
        clause, params = self._credit_clause(credit_kind, jobs)
        with self._conn() as c:
            rows = c.execute(
                "SELECT p.id, p.name, COUNT(*) AS n FROM person_fts pf "
                "JOIN person p ON p.id = pf.rowid JOIN film_credit fc ON fc.person_id = p.id "
                f"WHERE person_fts MATCH ? AND {clause} GROUP BY p.id ORDER BY n DESC, p.name LIMIT ?",
                [match, *params, CANDIDATE_LIMIT],
            ).fetchall()
            return [Candidate(int(r["id"]), str(r["name"]), int(r["n"])) for r in rows]

    def characters_named(self, text: str) -> list[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT character FROM film_credit WHERE kind = 'cast' AND lower(character) = ? ORDER BY character",
                (text.lower().strip(),),
            ).fetchall()
            return [str(r["character"]) for r in rows]

    def character_candidates(self, text: str) -> list[Candidate]:
        match = trigram_query(text)
        if not match:
            return []
        with self._conn() as c:
            rows = c.execute(
                "SELECT fc.character AS name, COUNT(*) AS n FROM character_fts cf "
                "JOIN film_credit fc ON fc.rowid = cf.rowid "
                "WHERE character_fts MATCH ? AND fc.character != '' GROUP BY fc.character ORDER BY n DESC, name LIMIT ?",
                (match, CANDIDATE_LIMIT),
            ).fetchall()
            return [Candidate(str(r["name"]), str(r["name"]), int(r["n"])) for r in rows]

    def keyword_candidates(self) -> list[Candidate]:
        with self._conn() as c:
            rows = c.execute("SELECT keyword, COUNT(*) AS n FROM film_keyword GROUP BY keyword ORDER BY keyword").fetchall()
            return [Candidate(str(r["keyword"]), str(r["keyword"]), int(r["n"])) for r in rows]

    def title_candidates(self) -> list[Candidate]:
        with self._conn() as c:
            rows = c.execute("SELECT f.id, f.title FROM films f WHERE " + _NOT_DISPOSED + " ORDER BY f.id").fetchall()
            return [Candidate(int(r["id"]), str(r["title"]), 0) for r in rows]
```

- [ ] **Step 4: Run to verify they pass**

Run the four tests → PASS. `uv run pytest -q` → all pass. `uv run ruff check . && uv run mypy` → clean.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/infrastructure/database.py tests/unit/test_database.py
git commit -m "the index hands back everyone who shares a window; who is meant is decided one layer up"
```

---

### Task 4: `Repository.search_films` — filters ANDed, freeform scored

**Files:**
- Modify: `src/movie_brain/domain/search.py` (append the `Filter` type)
- Modify: `src/movie_brain/infrastructure/database.py` (`# search` section)
- Test: `tests/unit/test_search.py` (one test), `tests/unit/test_database.py`

**Interfaces:**
- Produces:

```python
# domain/search.py
@dataclass(frozen=True)
class Filter:
    kind: str                            # person | character | title | genre | keyword | year | text
    ids: tuple[int, ...] = ()            # person: resolved person ids (OR)
    values: tuple[str, ...] = ()         # character: canonical strings; title: lowercase substrings; genre: normalised; keyword: lowercase; text: the raw text
    credit_kind: str | None = None       # person
    jobs: tuple[str, ...] = ()           # person, crew
    lo: int | None = None                # year
    hi: int | None = None
# database.py
def search_films(self, filters: Sequence[Filter], free: str) -> list[tuple[int, float]]   # (film_id, score); every filter ANDed; with `free`, only films scoring > 0, ordered score desc then title; without, score 0.0, ordered by title
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_search.py`:

```python
from movie_brain.domain.search import Filter


def test_filter_is_a_frozen_value_with_defaults():
    f = Filter("year", lo=1940, hi=1949)
    assert (f.ids, f.values, f.credit_kind, f.jobs) == ((), (), None, ())
```

Append to `tests/unit/test_database.py` (add `Filter` to the `movie_brain.domain.search` import):

```python
def _seed_search(repo):
    """Alpha (1946): Bogart as Marlowe, Hawks directs, OMDb genre Film-Noir, plot mentions Sternwood.
    Beta (1950): Jane Bogart as Nurse, Hawks directs, overview mentions 'alpha ward'.
    Gamma (1960): no credits, no tmdb id — reachable by title only. Delta: merged away, invisible."""
    day = date(2026, 9, 6)
    a, b = _seed_people(repo)
    repo.upsert_omdb(a, OmdbRating(8.0, 97, True, "English", '{"Genre": "Crime, Drama, Film-Noir", "Plot": "A private eye visits the Sternwood mansion."}'), day)
    repo.write_credits(a, _credits(), day)  # re-write so film_text picks up the plot
    g = repo.create_film(Film("Gamma", 1960, None, ""))
    d = repo.create_film(Film("Alpha Delta", 1970, None, ""))
    repo.merge_film(d, a, day, note="twin")
    return a, b, g


def test_search_films_person_filter_respects_kind_and_jobs(repo):
    a, b, g = _seed_search(repo)
    bogart = repo.persons_named("Humphrey Bogart", "cast", ())
    hawks = repo.persons_named("Howard Hawks", "crew", ("Director",))
    assert [i for i, _ in repo.search_films([Filter("person", ids=tuple(bogart), credit_kind="cast")], "")] == [a]
    assert [i for i, _ in repo.search_films([Filter("person", ids=tuple(hawks), credit_kind="crew", jobs=("Director",))], "")] == [a, b]
    assert repo.search_films([Filter("person", ids=tuple(bogart), credit_kind="crew", jobs=("Director",))], "") == []


def test_search_films_ands_fields_and_ors_values(repo):
    a, b, g = _seed_search(repo)
    both = Filter("character", values=("Philip Marlowe", "Nurse"))
    assert [i for i, _ in repo.search_films([both], "")] == [a, b]
    assert [i for i, _ in repo.search_films([both, Filter("year", lo=1950, hi=None)], "")] == [b]


def test_search_films_genre_matches_omdb_and_tmdb_forms(repo):
    a, b, g = _seed_search(repo)
    assert [i for i, _ in repo.search_films([Filter("genre", values=("filmnoir",))], "")] == [a]
    assert [i for i, _ in repo.search_films([Filter("genre", values=("mystery",))], "")] == [a]  # TMDB genre on Alpha's tmdb_facts
    assert repo.search_films([Filter("genre", values=("western",))], "") == []


def test_search_films_title_keyword_and_plot_filters(repo):
    a, b, g = _seed_search(repo)
    assert [i for i, _ in repo.search_films([Filter("title", values=("gamm",))], "")] == [g]   # substring, no credits needed
    assert [i for i, _ in repo.search_films([Filter("keyword", values=("hospital",))], "")] == [b]
    assert [i for i, _ in repo.search_films([Filter("text", values=("sternwood",))], "")] == [a]   # plot column, not title


def test_search_films_freeform_ranks_a_title_hit_above_a_plot_hit_and_reaches_unenriched_titles(repo):
    a, b, g = _seed_search(repo)
    ranked = repo.search_films([], "alpha")
    assert [i for i, _ in ranked][:2] == [a, b]        # Alpha by title (10) above Beta by overview (2)
    assert ranked[0][1] > ranked[1][1] > 0
    assert [i for i, _ in repo.search_films([], "gamma")] == [g]   # never enriched, found through films.title
    assert [i for i, _ in repo.search_films([], "bogart")] == [a, b]  # person-name hit reaches both films
    assert [i for i, _ in repo.search_films([], "marlowe")][0] == a  # character hit


def test_search_films_freeform_and_field_combine_and_disposed_films_never_appear(repo):
    a, b, g = _seed_search(repo)
    assert [i for i, _ in repo.search_films([Filter("year", lo=1950, hi=1950)], "alpha")] == [b]
    assert all(i != a + 3 for i, _ in repo.search_films([], "alpha delta"))  # the merged-away 'Alpha Delta'
    assert repo.search_films([], "zzzz") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_search.py tests/unit/test_database.py -k "Filter or search_films" -q` → `ImportError` / `AttributeError: ... 'search_films'`.

- [ ] **Step 3: Implement**

Append to `src/movie_brain/domain/search.py`:

```python
@dataclass(frozen=True)
class Filter:
    """One resolved, exact constraint. The resolver turns fuzzy text into these; the repository
    only ever sees exact values (spec D6)."""

    kind: str
    ids: tuple[int, ...] = ()
    values: tuple[str, ...] = ()
    credit_kind: str | None = None
    jobs: tuple[str, ...] = ()
    lo: int | None = None
    hi: int | None = None
```

Add to `database.py`'s `# search` section (import `Filter, fts_words, norm_genre, W_CHARACTER, W_OVERVIEW, W_PERSON, W_PLOT, W_TAG, W_TITLE` from `movie_brain.domain.search`, and `Sequence` from `collections.abc` if not present):

```python
    _GENRE_NORM = "replace(replace(replace(lower({col}), ' ', ''), '-', ''), '.', '')"

    def _filter_sql(self, flt: Filter) -> tuple[str, list[object]]:
        """One ANDed clause against alias `f` (films). Every fuzzy kind arrives already resolved."""
        if flt.kind == "person":
            if not flt.ids:
                return "0 = 1", []
            clause, params = self._credit_clause(flt.credit_kind, flt.jobs)
            marks = ",".join("?" * len(flt.ids))
            return f"EXISTS (SELECT 1 FROM film_credit fc WHERE fc.film_id = f.id AND fc.person_id IN ({marks}) AND {clause})", [*flt.ids, *params]
        if flt.kind == "character":
            if not flt.values:
                return "0 = 1", []
            marks = ",".join("?" * len(flt.values))
            return f"EXISTS (SELECT 1 FROM film_credit fc WHERE fc.film_id = f.id AND fc.kind = 'cast' AND fc.character IN ({marks}))", list(flt.values)
        if flt.kind == "title":
            parts = ["(lower(f.title) LIKE ? OR EXISTS (SELECT 1 FROM tmdb_facts t WHERE t.film_id = f.id AND lower(t.original_title) LIKE ?))"] * len(flt.values)
            params: list[object] = []
            for v in flt.values:
                params += [f"%{v.lower()}%", f"%{v.lower()}%"]
            return "(" + " OR ".join(parts) + ")", params
        if flt.kind == "genre":
            omdb = self._GENRE_NORM.format(col="json_extract(o.payload, '$.Genre')")
            tmdb = self._GENRE_NORM.format(col="value")
            parts, params = [], []
            for g in flt.values:
                parts.append(
                    f"EXISTS (SELECT 1 FROM omdb o WHERE o.film_id = f.id AND ',' || {omdb} || ',' LIKE ?) "
                    f"OR EXISTS (SELECT 1 FROM tmdb_facts t, json_each(t.genres) WHERE t.film_id = f.id AND {tmdb} = ?)"
                )
                params += [f"%,{g},%", g]
            return "(" + " OR ".join(parts) + ")", params
        if flt.kind == "keyword":
            marks = ",".join("?" * len(flt.values))
            return f"EXISTS (SELECT 1 FROM film_keyword k WHERE k.film_id = f.id AND lower(k.keyword) IN ({marks}))", [v.lower() for v in flt.values]
        if flt.kind == "year":
            parts, params = [], []
            if flt.lo is not None:
                parts.append("f.year >= ?"); params.append(flt.lo)
            if flt.hi is not None:
                parts.append("f.year <= ?"); params.append(flt.hi)
            return "(" + " AND ".join(parts) + ")" if parts else "1 = 1", params
        if flt.kind == "text":
            match = fts_words(" ".join(flt.values))
            if not match:
                return "0 = 1", []
            return "f.id IN (SELECT rowid FROM film_text_fts WHERE film_text_fts MATCH ?)", [f"{{overview plot}}: {match}"]
        raise ValueError(f"unknown filter kind {flt.kind!r}")

    def _freeform_scores(self, c: sqlite3.Connection, free: str) -> dict[int, float]:
        """Where the text hit decides the rank (spec §8): title, then person, character,
        genre/keyword, then plot — summed per film. Several small statements merged here rather
        than one CTE across three differently-tokenised FTS tables (plan §"deviation")."""
        scores: dict[int, float] = {}

        def add(rows: list[sqlite3.Row], weight: float | None = None) -> None:
            for r in rows:
                scores[int(r[0])] = scores.get(int(r[0]), 0.0) + (float(r[1]) if weight is None else weight)

        words = fts_words(free)
        if words:
            add(c.execute(
                f"SELECT rowid, -bm25(film_text_fts, {W_TITLE}, {W_OVERVIEW}, {W_PLOT}) FROM film_text_fts WHERE film_text_fts MATCH ?",
                (words,),
            ).fetchall())
        # unenriched films have no film_text row: reach their title directly
        add(c.execute("SELECT id FROM films WHERE lower(title) LIKE ?", (f"%{free.lower()}%",)).fetchall(), W_TITLE)
        tri = fts_words(free, min_len=3)
        if tri:
            add(c.execute(
                "SELECT DISTINCT fc.film_id FROM person_fts pf JOIN film_credit fc ON fc.person_id = pf.rowid WHERE person_fts MATCH ?",
                (tri,),
            ).fetchall(), W_PERSON)
            add(c.execute(
                "SELECT DISTINCT fc.film_id FROM character_fts cf JOIN film_credit fc ON fc.rowid = cf.rowid WHERE character_fts MATCH ?",
                (tri,),
            ).fetchall(), W_CHARACTER)
        g = norm_genre(free)
        if g:
            omdb = self._GENRE_NORM.format(col="json_extract(o.payload, '$.Genre')")
            add(c.execute(f"SELECT film_id FROM omdb o WHERE ',' || {omdb} || ',' LIKE ?", (f"%,{g},%",)).fetchall(), W_TAG)
            add(c.execute("SELECT film_id FROM film_keyword WHERE lower(keyword) = ?", (free.lower().strip(),)).fetchall(), W_TAG)
        return scores

    def search_films(self, filters: Sequence[Filter], free: str) -> list[tuple[int, float]]:
        """Every filter ANDed, freeform scored (spec §8). Disposed films never appear."""
        clauses = [_NOT_DISPOSED]
        params: list[object] = []
        for flt in filters:
            sql, p = self._filter_sql(flt)
            clauses.append(sql)
            params += p
        with self._conn() as c:
            scores = self._freeform_scores(c, free.strip()) if free.strip() else None
            if scores is not None:
                if not scores:
                    return []
                marks = ",".join("?" * len(scores))
                clauses.append(f"f.id IN ({marks})")
                params += list(scores)
            rows = c.execute("SELECT f.id, f.title FROM films f WHERE " + " AND ".join(clauses) + " ORDER BY f.title, f.id", params).fetchall()
        if scores is None:
            return [(int(r["id"]), 0.0) for r in rows]
        ranked = [(int(r["id"]), scores[int(r["id"])], str(r["title"])) for r in rows]
        ranked.sort(key=lambda t: (-t[1], t[2].lower(), t[0]))
        return [(i, s) for i, s, _ in ranked]
```

Notes. SQLite's variable limit is 32,766 (3.32+), comfortably above any freeform candidate set, but cap defensively: if `len(scores) > 30000`, keep the 30,000 highest-scoring before building `marks`. `{overview plot}:` is FTS5's column-filter syntax; the `{{` in the f-string produces a literal `{`. `_NOT_DISPOSED` references alias `f`, which the outer query uses.

- [ ] **Step 4: Run to verify they pass**

Run the new tests → PASS; full suite, ruff, mypy → clean. If `test_search_films_genre_matches_omdb_and_tmdb_forms`'s "mystery" assertion fails, check that `_credits()` in the test helper carries `genres=("Mystery", "Crime")` (it does since Plan A) and that `write_credits` stored it into `tmdb_facts.genres` as JSON.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/domain/search.py src/movie_brain/infrastructure/database.py tests/unit/test_search.py tests/unit/test_database.py
git commit -m "a field narrows and freeform only ranks, so the two never have to agree on a top-N"
```

---

### Task 5: `run_search` — resolution, corrections, suggestions, hints (BDD)

**Files:**
- Create: `src/movie_brain/application/search.py`
- Create: `tests/features/search.feature`, `tests/step_defs/test_search.py`

**Interfaces:**
- Consumes: Tasks 1–4; `Repository.credits_summary()` (Plan A).
- Produces:

```python
@dataclass(frozen=True)
class SearchResult:
    ids: tuple[int, ...]
    ranked: bool                               # True when freeform text drove an ordering
    corrections: tuple[dict[str, str], ...]    # {"field", "typed", "used"}
    suggestions: tuple[dict[str, object], ...] # {"field", "typed", "options": [str, ...]}
    hints: tuple[str, ...]
    def to_dict(self) -> dict[str, object]
def run_search(repo: Repository, text: str) -> SearchResult
```

- [ ] **Step 1: Write the feature file**

Create `tests/features/search.feature`:

```gherkin
Feature: Resolving a search into an exact film-id set

  A fuzzy field is corrected to an exact value BEFORE the query runs, and the
  correction is always shown (spec D7). A quoted value is exact and never
  corrected. Freeform text ranks; fields narrow. An unknown field is a hint,
  not an error.

  Background:
    Given the search corpus of Alpha, Beta and Gamma

  Scenario: An exact field query returns the set, unranked
    When I search for "character: philip marlowe"
    Then the result ids are Alpha
    And the result is not ranked
    And there are no corrections

  Scenario: A misspelled actor is corrected visibly
    When I search for "actor: bogrt"
    Then the result ids are Alpha
    And the correction for "actor" reads bogrt → Humphrey Bogart

  Scenario: A quoted value is exact and is never corrected
    When I search for "actor: \"bogrt\""
    Then the result is empty
    And there are no corrections
    And there are no suggestions

  Scenario: A name too far from any person is refused with suggestions
    When I search for "actor: bgt"
    Then the result is empty
    And the suggestions for "actor" include Humphrey Bogart

  Scenario: A director field never matches an actor of the same name
    When I search for "director: humphrey bogart"
    Then the result is empty

  Scenario: Fields AND and freeform ranks within them
    When I search for "alpha director: hawks"
    Then the result ids are Alpha then Beta
    And the result is ranked

  Scenario: An unknown field is freeform with a hint
    When I search for "foo: gamma"
    Then the result ids are Gamma
    And the hints include "unknown field 'foo'"

  Scenario: Genre matches the OMDb spelling however it is typed
    When I search for "genre: film noir"
    Then the result ids are Alpha

  Scenario: A keyword typo is corrected against the keyword vocabulary
    When I search for "keyword: hospitl"
    Then the result ids are Beta
    And the correction for "keyword" reads hospitl → hospital

  Scenario: A year range narrows
    When I search for "year: 1940-1949"
    Then the result ids are Alpha

  Scenario: A people field on a catalogue with no credits explains itself
    Given a catalogue with no credits at all
    When I search for "actor: anyone"
    Then the result is empty
    And the hints include "no credits loaded — run `movie-brain enrich credits --apply`"
```

- [ ] **Step 2: Write the step definitions**

Create `tests/step_defs/test_search.py`:

```python
from __future__ import annotations

from datetime import date

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from movie_brain.application.search import run_search
from movie_brain.domain.models import CastRow, CrewRow, Film, OmdbRating, TmdbCredits

scenarios("../features/search.feature")

DAY = date(2026, 9, 6)


def _credits(tmdb_id, title, overview, keywords, cast, crew, genres=("Mystery",)):
    return TmdbCredits(
        tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
        alt_titles=(), overview=overview, tagline=None, genres=genres, keywords=keywords, cast=cast, crew=crew,
    )


@pytest.fixture
def films() -> dict[str, int]:
    return {}


@pytest.fixture
def result() -> dict:
    return {}


@given("the search corpus of Alpha, Beta and Gamma")
def corpus(repo, films):
    a = repo.create_film(Film("Alpha", 1946, None, ""))
    b = repo.create_film(Film("Beta", 1950, None, ""))
    g = repo.create_film(Film("Gamma", 1960, None, ""))
    repo.set_external_id(a, "tmdb", "910", DAY)
    repo.set_external_id(b, "tmdb", "911", DAY)
    repo.upsert_omdb(a, OmdbRating(8.0, 97, True, "English", '{"Genre": "Crime, Film-Noir", "Plot": "Sternwood."}'), DAY)
    repo.write_credits(a, _credits(910, "Alpha", "A private eye.", ("film noir",),
                                   (CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),),
                                   (CrewRow(2636, "Howard Hawks", "Director", "Directing"),)), DAY)
    repo.write_credits(b, _credits(911, "Beta", "A nurse in the alpha ward.", ("hospital",),
                                   (CastRow(77, "Jane Bogart", "Nurse", 0),),
                                   (CrewRow(2636, "Howard Hawks", "Director", "Directing"),)), DAY)
    films.update(Alpha=a, Beta=b, Gamma=g)


@given("a catalogue with no credits at all")
def no_credits(repo, films):
    import sqlite3

    with sqlite3.connect(repo.db_path) as c:
        c.execute("DELETE FROM film_credit")
        c.execute("DELETE FROM person")
        c.execute("UPDATE tmdb_facts SET credits_fetched_on = NULL")


@when(parsers.parse('I search for "{text}"'))
def search(repo, result, text):
    result["r"] = run_search(repo, text.replace('\\"', '"'))


@then(parsers.parse("the result ids are {names}"))
def ids_are(result, films, names):
    expected = [films[n.strip()] for n in names.replace(" then ", ",").split(",")]
    assert list(result["r"].ids) == expected


@then("the result is empty")
def empty(result):
    assert result["r"].ids == ()


@then("the result is ranked")
def ranked(result):
    assert result["r"].ranked is True


@then("the result is not ranked")
def not_ranked(result):
    assert result["r"].ranked is False


@then("there are no corrections")
def no_corrections(result):
    assert result["r"].corrections == ()


@then("there are no suggestions")
def no_suggestions(result):
    assert result["r"].suggestions == ()


@then(parsers.parse('the correction for "{field}" reads {typed} → {used}'))
def correction(result, field, typed, used):
    assert {"field": field, "typed": typed, "used": used} in result["r"].corrections


@then(parsers.parse('the suggestions for "{field}" include {name}'))
def suggestion(result, field, name):
    assert any(s["field"] == field and name in s["options"] for s in result["r"].suggestions), result["r"].suggestions


@then(parsers.parse('the hints include "{hint}"'))
def hint(result, hint):
    assert hint in result["r"].hints, result["r"].hints
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/step_defs/test_search.py -q` → `ModuleNotFoundError: No module named 'movie_brain.application.search'`.

- [ ] **Step 4: Implement**

Create `src/movie_brain/application/search.py`:

```python
"""Turn a typed query into an exact film-id set — the three stages of spec §8.

1. Parse (pure, `domain/search.py`). 2. Resolve every fuzzy field to exact values through the
repository's candidate queries: exact match first; else the trigram candidates ranked by
`similarity`, the top one used when it clears CORRECTION_FLOOR and always reported in
`corrections`; below that floor nothing is used and the nearest names are `suggestions`
(spec D7, D8). A quoted value is exact and skips correction. 3. `search_films` filters and ranks.

Resolution never touches SQL; it asks the repository for candidates and decides in Python,
because the FTS trigram index is a candidate generator, not a ranker (Plan A's finding).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from movie_brain.domain.search import (
    CORRECTION_FLOOR,
    FIELDS,
    MAX_SUGGESTIONS,
    SUGGESTION_FLOOR,
    Candidate,
    Filter,
    Term,
    norm_genre,
    parse_query,
    parse_year_range,
    rank_candidates,
)
from movie_brain.infrastructure.database import Repository

NO_CREDITS_HINT = "no credits loaded — run `movie-brain enrich credits --apply`"


@dataclass(frozen=True)
class SearchResult:
    ids: tuple[int, ...]
    ranked: bool
    corrections: tuple[dict[str, str], ...]
    suggestions: tuple[dict[str, object], ...]
    hints: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["total"] = len(self.ids)
        return d


class _Resolver:
    """Collects filters, corrections and suggestions for one query."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.filters: list[Filter] = []
        self.corrections: list[dict[str, str]] = []
        self.suggestions: list[dict[str, object]] = []
        self.unresolved = False  # a fuzzy field found nothing usable → the whole result is empty (AND)

    def _pick(self, term: Term, candidates: list[Candidate]) -> Candidate | None:
        """Exact-first has already failed. Rank, then use / suggest / refuse (spec §7.3)."""
        ranked = rank_candidates(term.value, candidates)
        if ranked and ranked[0].score >= CORRECTION_FLOOR:
            top = ranked[0]
            self.corrections.append({"field": term.field, "typed": term.value, "used": top.name})
            return Candidate(top.key, top.name, 0)
        options = [r.name for r in ranked if r.score >= SUGGESTION_FLOOR][:MAX_SUGGESTIONS]
        if options:
            self.suggestions.append({"field": term.field, "typed": term.value, "options": options})
        self.unresolved = True
        return None

    def person(self, term: Term) -> None:
        spec = FIELDS[term.field]
        ids = self.repo.persons_named(term.value, spec.credit_kind, spec.jobs)
        if not ids and not term.exact:
            chosen = self._pick(term, self.repo.person_candidates(term.value, spec.credit_kind, spec.jobs))
            ids = [int(chosen.key)] if chosen else []
        if not ids:
            self.unresolved = True
        self.filters.append(Filter("person", ids=tuple(ids), credit_kind=spec.credit_kind, jobs=spec.jobs))

    def character(self, term: Term) -> None:
        names = self.repo.characters_named(term.value)
        if not names and not term.exact:
            chosen = self._pick(term, self.repo.character_candidates(term.value))
            names = [str(chosen.key)] if chosen else []
        if not names:
            self.unresolved = True
        self.filters.append(Filter("character", values=tuple(names)))

    def keyword(self, term: Term) -> None:
        all_kw = self.repo.keyword_candidates()
        exact = [c.name for c in all_kw if c.name.lower() == term.value.lower().strip()]
        if not exact and not term.exact:
            chosen = self._pick(term, all_kw)
            exact = [str(chosen.key)] if chosen else []
        if not exact:
            self.unresolved = True
        self.filters.append(Filter("keyword", values=tuple(exact)))

    def title(self, term: Term) -> None:
        # A title term is a substring filter, like the column filter it sits beside; when it
        # matches nothing, the nearest titles are offered but never substituted.
        hits = [c for c in self.repo.title_candidates() if term.value.lower() in c.name.lower()]
        if not hits and not term.exact:
            ranked = rank_candidates(term.value, self.repo.title_candidates())
            options = [r.name for r in ranked if r.score >= SUGGESTION_FLOOR][:MAX_SUGGESTIONS]
            if options:
                self.suggestions.append({"field": "title", "typed": term.value, "options": options})
        self.filters.append(Filter("title", values=(term.value,)))

    def genre(self, term: Term) -> None:
        self.filters.append(Filter("genre", values=(norm_genre(term.value),)))

    def year(self, term: Term) -> None:
        rng = parse_year_range(term.value)
        if rng is None:
            self.unresolved = True
            return
        self.filters.append(Filter("year", lo=rng[0], hi=rng[1]))

    def text(self, term: Term) -> None:
        self.filters.append(Filter("text", values=(term.value,)))


def run_search(repo: Repository, text: str) -> SearchResult:
    parsed = parse_query(text)
    hints = list(parsed.hints)
    resolver = _Resolver(repo)
    by_field: dict[str, list[Term]] = {}
    for term in parsed.terms:
        by_field.setdefault(term.field, []).append(term)
    people_asked = False
    for field, terms in by_field.items():
        kind = FIELDS[field].kind
        if kind in ("person", "character"):
            people_asked = True
        for term in terms:
            getattr(resolver, kind)(term)
    if people_asked and repo.credits_summary()["films_with_credits"] == 0:
        hints.append(NO_CREDITS_HINT)
    filters = _merge_same_field(resolver.filters)
    if resolver.unresolved:
        ids: list[tuple[int, float]] = []
    else:
        ids = repo.search_films(filters, parsed.free)
    return SearchResult(
        ids=tuple(i for i, _ in ids),
        ranked=bool(parsed.free.strip()) and bool(ids),
        corrections=tuple(resolver.corrections),
        suggestions=tuple(resolver.suggestions),
        hints=tuple(hints),
    )


def _merge_same_field(filters: list[Filter]) -> list[Filter]:
    """The same field repeated ORs (spec §7.1): fold its filters' ids/values into one."""
    merged: dict[tuple[str, str | None, tuple[str, ...]], Filter] = {}
    out: list[Filter] = []
    for flt in filters:
        if flt.kind == "year":
            out.append(flt)
            continue
        key = (flt.kind, flt.credit_kind, flt.jobs)
        if key in merged:
            prev = merged[key]
            merged[key] = Filter(flt.kind, ids=prev.ids + flt.ids, values=prev.values + flt.values, credit_kind=flt.credit_kind, jobs=flt.jobs)
        else:
            merged[key] = flt
    return out + list(merged.values())
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/step_defs/test_search.py -q` → 11 passed. Then full suite, ruff, mypy. If "director: humphrey bogart" is not empty, check `persons_named` receives `("crew", ("Director",))` — the scenario is what proves a job set is a real restriction, not a hint.

- [ ] **Step 6: Commit**

```bash
git add src/movie_brain/application/search.py tests/features/search.feature tests/step_defs/test_search.py
git commit -m "a correction the owner cannot see is worse than no result, so every substitution is reported"
```

---

### Task 6: `GET /api/search`

**Files:**
- Modify: `src/movie_brain/web/app.py` (import `run_search`; add the route after `/api/config`)
- Test: `tests/web/test_api.py`

**Interfaces:**
- Produces: `GET /api/search?q=<text>` → `200 {"q": str, "ids": [int…], "ranked": bool, "corrections": [...], "suggestions": [...], "hints": [...], "total": int}`; missing/blank `q` → `400 {"error": "q is required"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_api.py` (its `client` fixture seeds Trio/Quartet via `record_catalog`; add credits inside the tests):

```python
def _enrich_trio(repo):
    from movie_brain.domain.models import CastRow, CrewRow, TmdbCredits

    trio = repo.film_id_by_key("trio (1950)")
    repo.set_external_id(trio, "tmdb", "3", D)
    repo.write_credits(trio, TmdbCredits(
        tmdb_id=3, imdb_id=None, title="Trio", original_title="Trio", year=1950, runtime_min=None, alt_titles=(),
        overview="Three tales of a private eye.", tagline=None, genres=("Drama",), keywords=("anthology",),
        cast=(CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),), crew=(CrewRow(1, "Ken", "Director", "Directing"),),
    ), D)
    return trio


def test_search_requires_q(client):
    assert client.get("/api/search").status_code == 400
    assert client.get("/api/search?q=%20").status_code == 400


def test_search_field_query_returns_ids_and_correction(client, repo):
    trio = _enrich_trio(repo)
    r = client.get("/api/search?q=actor:%20bogrt")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ids"] == [trio] and body["ranked"] is False and body["total"] == 1
    assert body["corrections"] == [{"field": "actor", "typed": "bogrt", "used": "Humphrey Bogart"}]
    assert body["q"] == "actor: bogrt"


def test_search_freeform_is_ranked_and_reaches_titles_without_credits(client, repo):
    _enrich_trio(repo)
    body = client.get("/api/search?q=quartet").get_json()
    quartet = repo.film_id_by_key("quartet (1948)")
    assert body["ids"] == [quartet] and body["ranked"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/web/test_api.py -k search -q` → 404s (`assert 404 == 400`).

- [ ] **Step 3: Implement**

In `src/movie_brain/web/app.py` add `from movie_brain.application.search import run_search` (alphabetical with the other application imports) and, after the `/api/config` route:

```python
    @app.get("/api/search")
    def search() -> tuple[Response, int]:
        q = (request.args.get("q") or "").strip()
        if not q:
            return jsonify({"error": "q is required"}), 400
        result = run_search(repo, q)
        return jsonify({"q": q, **result.to_dict()}), 200
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/web/test_api.py -q` → pass; full suite, ruff, mypy → clean.

- [ ] **Step 5: Commit**

```bash
git add src/movie_brain/web/app.py tests/web/test_api.py
git commit -m "the dashboard already knows how to intersect an id set, so the endpoint returns one"
```

---

### Task 7: The bar — HTML, CSS, JS, Playwright

**Files:**
- Modify: `src/movie_brain/web/templates/index.html` (insert before `<div id="chips">`)
- Modify: `src/movie_brain/web/static/app.css` (append)
- Modify: `src/movie_brain/web/static/app.js` (state, `rowMatches`, `compare`, `syncUrl`, `readUrl`, `writeControlsFromState`, a new `search` section, `boot`)
- Modify: `tests/web/conftest.py` (seed credits on Alpha and Bravo)
- Test: `tests/web/test_dashboard.py`

**Interfaces:**
- Consumes: `/api/search` (Task 6).
- Produces: `#search` input, `#search-note` line; `state.q` (string), `state.search` (`null` or `{ids: Set<number>, rank: Map<number, number> | null}`); URL param `q`.

- [ ] **Step 1: Seed credits for the Playwright server**

In `tests/web/conftest.py::seed`, directly after the line `repo.set_external_id(ids["alpha (1950)"], "itunes", "284815525", TODAY)`, add:

```python
    # Power search (Plan B): Alpha and Bravo carry credits. Bogart plays Marlowe on Alpha (the
    # spec's own example query); Jane Bogart on Bravo is the near-name that makes the
    # correction's tiebreak real; Bravo's overview says "alpha" so a freeform 'alpha' search
    # ranks Alpha (title) above Bravo (overview). Hawks directs both.
    from movie_brain.domain.models import CastRow, CrewRow, TmdbCredits

    def _credits(tmdb_id, title, overview, cast):
        return TmdbCredits(
            tmdb_id=tmdb_id, imdb_id=None, title=title, original_title=title, year=None, runtime_min=None,
            alt_titles=(), overview=overview, tagline=None, genres=("Mystery",), keywords=("film noir",),
            cast=cast, crew=(CrewRow(2636, "Howard Hawks", "Director", "Directing"),),
        )

    repo.set_external_id(ids["alpha (1950)"], "tmdb", "910", TODAY)
    repo.set_external_id(ids["bravo (1960)"], "tmdb", "911", TODAY)
    repo.write_credits(ids["alpha (1950)"], _credits(910, "Alpha", "A private eye in the Sternwood house.",
                                                     (CastRow(4110, "Humphrey Bogart", "Philip Marlowe", 0),)), TODAY)
    repo.write_credits(ids["bravo (1960)"], _credits(911, "Bravo", "A holiday in the alpha quadrant.",
                                                     (CastRow(77, "Jane Bogart", "Nurse", 0),)), TODAY)
```

Run `uv run pytest tests/web -q` BEFORE writing any bar code: every existing test must still pass with the seed change (Bravo already carries audit flags naming a TMDB id, and `tmdb_facts` rows now exist for both — if a test asserts on `audit`/`services` payload shape, fix the seed, not the test).

- [ ] **Step 2: Write the failing Playwright tests**

Append to `tests/web/test_dashboard.py`:

```python
def _search(dash: Page, text: str) -> None:
    dash.fill("#search", text)
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")


def test_search_field_query_narrows_to_the_exact_set(dash: Page):
    clear_lang(dash)
    _search(dash, "character: philip marlowe")
    assert count(dash) == 1
    expect(dash.locator("#films tbody tr[data-id]").first).to_contain_text("Alpha")
    assert "q=character" in dash.url


def test_search_freeform_ranks_a_title_hit_first_and_sort_restores_on_clear(dash: Page):
    clear_lang(dash)
    _search(dash, "alpha")
    rows = dash.locator("#films tbody tr[data-id]")
    assert count(dash) == 2
    expect(rows.nth(0)).to_contain_text("Alpha")   # title hit (10) above Bravo's overview hit (2)
    expect(rows.nth(1)).to_contain_text("Bravo")
    _search(dash, "")
    assert count(dash) > 2 and "q=" not in dash.url


def test_search_correction_is_shown_and_undo_forces_exact(dash: Page):
    clear_lang(dash)
    _search(dash, "actor: bogrt")
    note = dash.locator("#search-note")
    expect(note).to_contain_text("Showing results for Humphrey Bogart")
    assert count(dash) == 1
    note.locator("button.undo").click()
    expect(dash.locator("#search")).to_have_value('actor: "bogrt"')
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")
    assert count(dash) == 0


def test_search_suggestion_chip_replaces_the_value(dash: Page):
    clear_lang(dash)
    _search(dash, "actor: bgt")
    assert count(dash) == 0
    dash.locator("#search-note button.suggest", has_text="Humphrey Bogart").click()
    expect(dash.locator("#search")).to_have_value('actor: "Humphrey Bogart"')
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")
    assert count(dash) == 1


def test_chips_keep_working_mid_search(dash: Page):
    clear_lang(dash)
    _search(dash, "director: hawks")
    assert count(dash) == 2   # Alpha and Bravo
    dash.click(".chip[data-chip=owned]")
    assert count(dash) == 1   # only Alpha is owned
    dash.click(".chip[data-chip=owned]")
    assert count(dash) == 2


def test_search_round_trips_through_the_url(dash: Page, server: str):
    dash.goto(f"{server}/?q=character%3A+philip+marlowe&lang=any")
    dash.wait_for_function("document.querySelector('#search').dataset.settled === document.querySelector('#search').value")
    expect(dash.locator("#search")).to_have_value("character: philip marlowe")
    assert count(dash) == 1


def test_search_input_is_not_a_chip(dash: Page):
    assert dash.locator("#search.chip").count() == 0
    assert dash.locator("#chips #search").count() == 0
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/web/test_dashboard.py -k search -q` → fail on `#search` not found (timeouts). Use `--timeout` sparingly; Playwright's default is enough to see the failure.

- [ ] **Step 4: Implement the markup and style**

`index.html` — insert directly BEFORE `<div id="chips">`:

```html
    <div id="search-row">
      <input id="search" class="search" type="search" placeholder="search — or actor: bogart · character: marlowe · genre: film noir · director: hawks year: 1940-1949" autocomplete="off" spellcheck="false" aria-label="Search films">
      <div id="search-note" class="search-note" hidden></div>
    </div>
```

`app.css` — append:

```css
/* Power search bar. It lives OUTSIDE #chips and never carries .chip: the #chips click handler
   matches .chip and would add `undefined` to the chip set (the list-picker precedent). */
#search-row { margin-top:8px; }
.search { width:100%; box-sizing:border-box; border:1px solid var(--line); background:var(--chip); border-radius:999px; padding:6px 14px; font:inherit; }
.search:focus { outline:2px solid var(--chip-on); outline-offset:1px; }
.search-note { margin-top:4px; font-size:13px; color:var(--muted, #666); }
.search-note b { font-weight:600; }
.search-note button { border:1px solid var(--line); background:var(--chip); border-radius:999px; padding:1px 8px; margin-left:4px; cursor:pointer; font:inherit; font-size:12px; }
```

- [ ] **Step 5: Implement the JS**

In `app.js`:

1. `state` gains `q: '', search: null,` (after `scope: 'reachable',`). `state.search` is `null` (no search active) or `{ ids: Set, rank: Map | null }`.

2. In `rowMatches`, immediately after the `inScope` check:
```js
    if (state.search && !state.search.ids.has(f.id)) return false;
```

3. In `compare`, at the very top of the `if (!state.sort)` branch (before the `state.list` block):
```js
      if (state.search && state.search.rank) {  // freeform text ranks; a column sort still overrides
        const ra = state.search.rank.get(a.id), rb = state.search.rank.get(b.id);
        if (ra !== rb) return ra - rb;
      }
```

4. In `syncUrl`, after `if (state.list) p.set('list', state.list);`:
```js
    if (state.q) p.set('q', state.q);
```
   In `readUrl`, after the `film` lines:
```js
    state.q = p.get('q') || '';
```
   In `writeControlsFromState`, first line: `$('#search').value = state.q;`

5. New section, placed after the list-picker `change` handler and before `const langPanel = …`:

```js
  // ---- power search (spec §9) ----
  // The server resolves the query to an id set; this pipeline only intersects with it, so chips,
  // scope, list picker and column filters all keep working mid-search. `dataset.settled` on the
  // input records the last query whose response has been applied — tests wait on it.
  const searchEl = $('#search'), noteEl = $('#search-note');
  let searchTimer = null, searchSeq = 0;
  function applySearchResponse(body) {
    state.search = { ids: new Set(body.ids), rank: body.ranked ? new Map(body.ids.map((id, i) => [id, i])) : null };
    const parts = [];
    for (const c of body.corrections) parts.push(`Showing results for <b>${esc(c.used)}</b> (you typed “${esc(c.typed)}”) <button class="undo" data-typed="${esc(c.typed)}">undo</button>`);
    for (const s of body.suggestions) parts.push(`No ${esc(s.field)} “${esc(s.typed)}” — did you mean ${s.options.map((o) => `<button class="suggest" data-typed="${esc(s.typed)}" data-use="${esc(o)}">${esc(o)}</button>`).join('')}?`);
    for (const h of body.hints) parts.push(esc(h));
    noteEl.innerHTML = parts.join('<br>');
    noteEl.hidden = parts.length === 0;
  }
  async function runSearch() {
    const q = state.q.trim();
    const seq = ++searchSeq;
    if (!q) {
      state.search = null; noteEl.hidden = true; noteEl.innerHTML = '';
      searchEl.dataset.settled = searchEl.value;
      applyFilters();
      return;
    }
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      const body = await r.json();
      if (seq !== searchSeq) return;  // a newer query is in flight
      applySearchResponse(body);
    } catch (e) {
      if (seq !== searchSeq) return;
      state.search = null; noteEl.hidden = false; noteEl.textContent = `Search failed: ${e.message}`;
    }
    searchEl.dataset.settled = searchEl.value;
    applyFilters();
  }
  searchEl.addEventListener('input', () => {
    state.q = searchEl.value;
    delete searchEl.dataset.settled;
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 300);
  });
  // Quoting a value makes it exact (spec §7.3): undo re-runs with the typed text quoted, and a
  // suggestion replaces the typed text with the chosen name, quoted.
  noteEl.addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    const typed = b.dataset.typed, use = b.classList.contains('undo') ? typed : b.dataset.use;
    state.q = state.q.replace(typed, `"${use}"`);
    searchEl.value = state.q;
    delete searchEl.dataset.settled;
    runSearch();
  });
```

6. In `boot()`, after `applyFilters();` and before `if (window.MB.onBoot)`: `if (state.q) runSearch(); else searchEl.dataset.settled = '';`

`esc` already exists in the file (used by the drawer). `readUrl` runs before `writeControlsFromState`, so the input shows `q` on load and `boot` fires the search once, undebounced.

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/web -q` → all pass (the seven new Playwright tests and every existing one). `uv run ruff check . && uv run mypy` → clean (no Python changed here except conftest).

- [ ] **Step 7: Commit**

```bash
git add src/movie_brain/web/templates/index.html src/movie_brain/web/static/app.css src/movie_brain/web/static/app.js tests/web/conftest.py tests/web/test_dashboard.py
git commit -m "the bar hands the table an id set and nothing else, so every filter keeps its job"
```

---

### Task 8: Docs, spec corrections, and a read-only live check

**Files:**
- Modify: `CLAUDE.md` (Architecture `web/` line; one Rules bullet), `docs/backlog.md` (item 8), the spec (§7.2 job table, §8 sentence)
- No code. One read-only check against the live DB through the Flask test client.

- [ ] **Step 1: Docs (every edited prose line stays ONE unbroken line)**

`CLAUDE.md` Architecture, the `web/` line currently reads "...ALL filter/sort logic is client-side vanilla JS in `static/app.js`...". Append to that sentence: " — with ONE exception: the search bar's query is resolved server-side by `GET /api/search` into a film-id set that `app.js` intersects with its own pipeline (power-search spec D4); the id set is the whole interface, and no chip, scope, list or column logic moved."

`CLAUDE.md` Rules — add one bullet after the Credits bullet:

```
- Power search (Plan B): `domain/search.py` is the pure grammar (`parse_query`: bare run-to-next-field values, quotes legal never required, unknown field → freeform + hint), similarity (`similarity`/`rank_candidates`: token-aware difflib, tiebreak on credit count then name) and the `Filter` type; `application/search.py::run_search` resolves every fuzzy field to EXACT values before any query runs — exact match first, then trigram candidates ranked in Python, the top used only above `CORRECTION_FLOOR` (0.8) and ALWAYS reported in `corrections`, below it `suggestions` and an empty result (D7); a quoted value is exact and never corrected; `Repository.search_films` ANDs the filters as one statement over the whole catalogue (never a post-filter over a top-N, D6) and scores freeform text across `film_text_fts` (bm25 title 10 / overview 2 / plot 1), `person_fts` (5), `character_fts` (4), genre/keyword (3) and a direct `films.title` LIKE (10, so never-enriched films are still found by title). The FTS trigram index is a candidate GENERATOR only — its own rank is never trusted (on the live index `bogrt` ranks "Ogranya" first). `GET /api/search?q=` returns `{ids, ranked, corrections, suggestions, hints, total}`; `app.js` keeps `state.search = {ids, rank}` and intersects in `rowMatches`, ranks in `compare` only when `ranked` and no column sort is set, encodes `q=` in the URL, and marks `#search[data-settled]` when a response is applied (tests wait on it). The input is `#search.search`, OUTSIDE `#chips`, never `.chip`. Crew-job sets per field live in `FIELDS` and were verified against the live vocabulary 2026-09-06. Known limit: plot text exists only for enriched films (`film_text` is written by `enrich credits`).
```

`docs/backlog.md` item 8 — append (one line): "**Plan B shipped <date>:** the bar. Freeform + `field: value` + visible correction; spec §7–§9. Semantic (Phase 2, spec §12) still open." Fill the date at execution.

Spec §7.2 — replace the sentence "The job sets above are the plan's to verify against the live crew-job vocabulary after enrichment; they are the current best reading of TMDB's job names on *The Big Sleep*." with: "Job sets verified against the live vocabulary 2026-09-06 (286,429 credit rows): `writer` = Screenplay, Writer, Story, Novel, Original Story, Dialogue, Adaptation, Author, Book, Short Story, Theatre Play, Scenario Writer, Co-Writer, Screenstory, Original Film Writer; `cinematographer` = Director of Photography, Cinematography; `composer` = Original Music Composer, Music; `producer` = Producer, Executive Producer, Co-Producer, Associate Producer; `director` = Director; `editor` = Editor. The registry is `domain/search.py::FIELDS`."

Spec §8 — replace "Everything stays in one query per search." with: "The field filters are one statement; freeform scores are a handful of small statements merged in Python inside the same connection (three FTS tables with different tokenisers plus a `films.title` scan do not fit one readable statement). One repository call either way."

Spec §7.3 — append one sentence: "Ranking is the resolver's, never FTS's: the trigram index proposes candidates (an OR of the query's windows) and `rank_candidates` orders them by token-aware similarity, then credit count, then name — verified necessary on the live index, where FTS's own rank put 'Ogranya' above every Bogart for `bogrt`."

Run `~/code/praxis-workspace/praxis-halo/bin/unwrap-md CLAUDE.md docs/backlog.md docs/superpowers/specs/2026-09-06-power-search-design.md` if present; confirm `git diff` shows no unrelated reflow.

- [ ] **Step 2: Read-only live check (no server, no writes)**

```bash
uv run python - <<'PY'
from datetime import date
from movie_brain.infrastructure.config import load_config
from movie_brain.infrastructure.database import Repository
from movie_brain.web.app import create_app
app = create_app(Repository(load_config().db_path), today=date.today); app.testing = True
c = app.test_client()
for q in ["character: philip marlowe", "actor: bogrt", "genre: film noir director: hawks", "hard boiled private eye", "writer: chandler", "xyzzy: nothing"]:
    b = c.get("/api/search", query_string={"q": q}).get_json()
    print(f"{q!r:45} total={b['total']:<4} ranked={b['ranked']} corrections={b['corrections']} suggestions={[s['options'] for s in b['suggestions']]} hints={b['hints']}")
PY
```

Expected: `character: philip marlowe` → total 4; `actor: bogrt` → correction `used: Humphrey Bogart`, total 11; `genre: film noir director: hawks` → The Big Sleep at least; `writer: chandler` → the Marlowe films plus *Double Indemnity*/*Strangers on a Train* if held (Chandler as Screenplay); `xyzzy: nothing` → hint `unknown field 'xyzzy'`. Paste the six lines into the commit message body or the report. `Repository(...)` opens read-only in effect: nothing in this script writes.

- [ ] **Step 3: Gate and commit**

`uv run pytest -q && uv run ruff check . && uv run mypy` → green.

```bash
git add CLAUDE.md docs/backlog.md docs/superpowers/specs/2026-09-06-power-search-design.md
git commit -m "the rules say where correction happens and why the index is never trusted to rank"
```

---

## Self-review

**Spec coverage.** §7.1 grammar → Task 1 (every example line has a test; `"crew: catering" title: brazil` included). §7.2 fields + aliases + job sets → Task 1 (`FIELDS`/`ALIASES`), Task 3/4 (kind/job clauses), Task 8 (spec table corrected). §7.3 spelling → Tasks 2, 5 (floors, corrections, suggestions, quoted-exact), Task 7 (note line, undo, suggestion buttons). §8 endpoint contract → Task 6; stages → Task 5 (parse/resolve) + Task 4 (filter/rank); bm25 weights → Task 4; "no limit parameter" honoured. §9 client → Task 7 (intersection in `rowMatches`, rank in `compare`, `q=` URL, debounce 300 ms, note line, `.search` not `.chip`, outside `#chips`). §10 degradation: no credits → `NO_CREDITS_HINT` (Task 5 scenario); films with no tmdb id → direct title LIKE (Task 4); fetch failure → note line (Task 7). §11 tests: parser ✓, resolution/ranking ✓ (Tasks 3–5), bar ✓ (Task 7: field, freeform ranked, correction + undo, chip mid-search, URL round-trip), plus suggestion click. D4–D8 ✓. D13 preserved: `search_films` returns `(id, score)` so a Phase 2 re-ranker slots in behind it.

**Placeholder scan.** Task 8's `<date>` is filled at execution. No TBD/TODO, no "similar to Task N", every code step carries its code.

**Type consistency.** `Term(field, value, exact)`, `ParsedQuery(terms, free, hints)`, `Filter(kind, ids, values, credit_kind, jobs, lo, hi)`, `Candidate(key, name, weight)`, `Ranked(key, name, score)`, `SearchResult(ids, ranked, corrections, suggestions, hints)` + `to_dict()` adding `total` — used with those names in Tasks 3–7. `persons_named(name, credit_kind, jobs)` / `person_candidates(text, credit_kind, jobs)` / `characters_named` / `character_candidates` / `keyword_candidates()` / `title_candidates()` / `search_films(filters, free)` match between Task 3/4 definitions, Task 5's calls and the tests. `_credit_clause` is shared by `persons_named`, `person_candidates` and `_filter_sql`. JSON keys `ids/ranked/corrections/suggestions/hints/total/q` match Task 6 and Task 7's `applySearchResponse`.
