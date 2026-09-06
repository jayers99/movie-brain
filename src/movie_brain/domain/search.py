"""Pure search helpers — no SQL, no I/O. Plan B's parser and resolver grow here.

`trigram_query` is the one thing Plan A needs: the FTS5 `trigram` tokenizer makes a bare
MATCH a SUBSTRING test ('bogrt' finds nothing), so misspelling tolerance is an OR of the
query's own trigrams — every name sharing at least one window comes back as a candidate,
and the resolver ranks those candidates. Verified against the stdlib sqlite3 2026-09-06.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def trigram_query(text: str) -> str:
    """'Bogrt' → '"bog" OR "ogr" OR "grt"'. Empty when the text has no 3-character window —
    the tokenizer cannot match shorter terms, so the caller must not send MATCH at all."""
    s = text.lower()
    windows = [s[i : i + 3] for i in range(len(s) - 2)]
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in windows)


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
    "producer": FieldSpec(
        "producer",
        "person",
        "crew",
        ("Producer", "Executive Producer", "Co-Producer", "Associate Producer"),
    ),
    "crew": FieldSpec("crew", "person", "crew", ()),
    "genre": FieldSpec("genre", "genre"),
    "keyword": FieldSpec("keyword", "keyword"),
    "year": FieldSpec("year", "year"),
    "plot": FieldSpec("plot", "text"),
}
ALIASES: dict[str, str] = {name: name for name in FIELDS} | {
    "cast": "actor",
    "role": "character",
    "dp": "cinematographer",
    "music": "composer",
    "kw": "keyword",
    "overview": "plot",
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

    matches = list(_TOKEN.finditer(text))
    i = 0
    while i < len(matches):
        m = matches[i]
        quoted, field, word = m.group(1), m.group(2), m.group(3)
        if field is not None:
            name = field.lower()
            if name in ALIASES:
                flush()
                current = ALIASES[name]
                i += 1
                continue
            hints.append(f"unknown field '{name}'")
            word = field + ":"  # falls through as ordinary text
            # Check if the next token is a URL continuation (starts with "//")
            if i + 1 < len(matches):
                next_m = matches[i + 1]
                next_quoted, next_field, next_word = next_m.group(1), next_m.group(2), next_m.group(3)
                if next_field is None and next_quoted is None and next_word and next_word.startswith("//"):
                    # Reconstruct the URL: "https:" + "//example.com" = "https://example.com"
                    word = field + ":" + next_word
                    i += 2
                    if current is not None:
                        buf.append(word)
                    else:
                        free.append(word)
                    continue
        if quoted is not None:
            piece = quoted.replace('""', '"')
            if current is not None and not buf:
                exact = True
                buf.append(piece)
            elif current is not None:
                buf.append(piece)
            else:
                free.append(piece)
            i += 1
            continue
        if current is not None:
            buf.append(word)
        else:
            free.append(word)
        i += 1
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
