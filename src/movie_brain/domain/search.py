"""Pure search helpers — no SQL, no I/O. Plan B's parser and resolver grow here.

`trigram_query` is the one thing Plan A needs: the FTS5 `trigram` tokenizer makes a bare
MATCH a SUBSTRING test ('bogrt' finds nothing), so misspelling tolerance is an OR of the
query's own trigrams — every name sharing at least one window comes back as a candidate,
and the resolver ranks those candidates. Verified against the stdlib sqlite3 2026-09-06.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher


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
LENGTH_PENALTY_EXPONENT = 0.35  # in similarity(): plain difflib ratio over-rewards a short query in a long
# token ('bogrt' inside 'Lena Brogren' scored 0.667 unpenalised); token scores are scaled by
# (min_len / max_len) ** LENGTH_PENALTY_EXPONENT; equal lengths unpenalised


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
# word start, OR a run of non-space. The regex recognizes `https:` as a field token, which becomes an
# unknown-field hint. Offsets — not joins — keep surrounding text verbatim: adjacent bare spans merge
# to preserve "https://example.com" and "a:b:c" as-is.
_TOKEN = re.compile(r'"((?:[^"]|"")*)"|(?<!\S)([A-Za-z_]+):|(\S+)')


def _merge_bare_pieces(
    pieces: list[tuple[str, tuple[int, int] | str]],
) -> list[tuple[str, tuple[int, int] | str]]:
    """Merge adjacent bare-token spans (non-quoted pieces)."""
    if not pieces:
        return pieces
    merged: list[tuple[str, tuple[int, int] | str]] = []
    for piece_type, piece_data in pieces:
        if piece_type == "bare" and merged and merged[-1][0] == "bare":
            # Merge with last bare piece
            _, last_data = merged.pop()
            assert isinstance(last_data, tuple) and isinstance(piece_data, tuple)
            merged.append(("bare", (last_data[0], piece_data[1])))
        else:
            merged.append((piece_type, piece_data))
    return merged


def _render_pieces(pieces: list[tuple[str, tuple[int, int] | str]], text: str) -> str:
    """Render pieces as a string: quoted → content, spans → text[start:end], joined by space."""
    if not pieces:
        return ""
    result = []
    for piece_type, piece_data in pieces:
        if piece_type == "quoted":
            assert isinstance(piece_data, str)
            result.append(piece_data)
        else:  # bare or field (both are spans)
            assert isinstance(piece_data, tuple)
            result.append(text[piece_data[0] : piece_data[1]])
    return " ".join(result).strip()


def parse_query(text: str) -> ParsedQuery:
    """Bare, run-to-next-field grammar (spec §7.1, D5). Pure; never raises."""
    terms: list[Term] = []
    free_pieces: list[tuple[str, tuple[int, int] | str]] = []
    hints: list[str] = []
    current: str | None = None  # canonical field collecting a value
    buf_pieces: list[tuple[str, tuple[int, int] | str]] = []
    current_field_span: tuple[int, int] | None = None
    exact = False

    def flush() -> None:
        nonlocal current, buf_pieces, exact, current_field_span
        if current is not None:
            merged = _merge_bare_pieces(buf_pieces)
            value = _render_pieces(merged, text)
            if value:
                terms.append(Term(current, value, exact))
            else:
                if current_field_span:
                    free_pieces.append(("bare", current_field_span))
                hints.append(f"field '{current}' has no value")
            current, buf_pieces, exact, current_field_span = None, [], False, None

    for m in _TOKEN.finditer(text):
        quoted, field, _ = m.group(1), m.group(2), m.group(3)
        if field is not None:
            name = field.lower()
            if name in ALIASES:
                flush()
                current = ALIASES[name]
                current_field_span = (m.start(), m.end())
                continue
            hints.append(f"unknown field '{name}'")
            # Unknown field token: treated as bare span (not a field blocker);
            # add span to current stream and let it merge with adjacent bare spans
            if current is not None:
                buf_pieces.append(("bare", (m.start(), m.end())))
            else:
                free_pieces.append(("bare", (m.start(), m.end())))
            continue
        if quoted is not None:
            piece = quoted.replace('""', '"')
            if current is not None and not buf_pieces:
                exact = True
                buf_pieces.append(("quoted", piece))
            elif current is not None:
                buf_pieces.append(("quoted", piece))
            else:
                free_pieces.append(("quoted", piece))
            continue
        if current is not None:
            buf_pieces.append(("bare", (m.start(3), m.end(3))))
        else:
            free_pieces.append(("bare", (m.start(3), m.end(3))))
    flush()
    merged_free = _merge_bare_pieces(free_pieces)
    free = _render_pieces(merged_free, text)
    return ParsedQuery(tuple(terms), free, tuple(hints))


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
    """Best of the whole name's SequenceMatcher ratio, or any single token's (each length-penalised).
    The penalty scales short-query-in-long-token mismatches down to prevent false positives.
    Verified on the live index: 'bogrt' → 'Humphrey Bogart' (best token 'bogart') scores 0.853,
    lifting it above 'Ogranya' (0.472) and rejecting 'Lena Brogren' (best token 'brogren', 0.593 < 0.6)."""
    q = query.lower().strip()
    n = name.lower()
    best = SequenceMatcher(None, q, n).ratio()
    for token in n.split():
        ratio = SequenceMatcher(None, q, token).ratio()
        len_factor = min(len(q), len(token)) / max(len(q), len(token)) if token else 0.0
        length_penalty = len_factor ** LENGTH_PENALTY_EXPONENT
        best = max(best, ratio * length_penalty)
    return best


def rank_candidates(query: str, candidates: Iterable[Candidate]) -> list[Ranked]:
    """Similarity desc, then the candidate's weight (credit count) desc, then name — so four
    Bogarts tied at 0.91 resolve to the one the catalogue credits most, deterministically."""
    cands = list(candidates)
    weights = {c.key: c.weight for c in cands}
    scored = [Ranked(c.key, c.name, similarity(query, c.name)) for c in cands]
    return sorted(scored, key=lambda r: (-r.score, -weights[r.key], r.name))
