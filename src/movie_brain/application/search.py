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

from collections.abc import Callable
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
    trigram_query,
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
        self.hints: list[str] = []  # too-short-to-correct notices from person()/character() (I5)

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
        return None

    def person(self, term: Term) -> None:
        spec = FIELDS[term.field]
        ids = self.repo.persons_named(term.value, spec.credit_kind, spec.jobs)
        if not ids and not term.exact:
            chosen = self._pick(term, self.repo.person_candidates(term.value, spec.credit_kind, spec.jobs))
            ids = [int(chosen.key)] if chosen else []
            if not ids and trigram_query(term.value) == "":
                self.hints.append(f"'{term.value}' is too short to correct — try three characters or more")
        self.filters.append(Filter("person", ids=tuple(ids), credit_kind=spec.credit_kind, jobs=spec.jobs))

    def character(self, term: Term) -> None:
        names = self.repo.characters_named(term.value)
        if not names and not term.exact:
            chosen = self._pick(term, self.repo.character_candidates(term.value))
            names = [str(chosen.key)] if chosen else []
            if not names and trigram_query(term.value) == "":
                self.hints.append(f"'{term.value}' is too short to correct — try three characters or more")
        self.filters.append(Filter("character", values=tuple(names)))

    def keyword(self, term: Term) -> None:
        all_kw = self.repo.keyword_candidates()
        exact = [c.name for c in all_kw if c.name.lower() == term.value.lower().strip()]
        if not exact and not term.exact:
            chosen = self._pick(term, all_kw)
            exact = [str(chosen.key)] if chosen else []
        self.filters.append(Filter("keyword", values=tuple(exact)))

    def title(self, term: Term) -> None:
        # A title term is a substring filter, like the column filter it sits beside; when it
        # matches nothing, the nearest titles are offered but never substituted.
        candidates = self.repo.title_candidates()
        hits = [c for c in candidates if term.value.lower() in c.name.lower()]
        if not hits and not term.exact:
            ranked = rank_candidates(term.value, candidates)
            options = [r.name for r in ranked if r.score >= SUGGESTION_FLOOR][:MAX_SUGGESTIONS]
            if options:
                self.suggestions.append({"field": "title", "typed": term.value, "options": options})
        self.filters.append(Filter("title", values=(term.value,)))

    def genre(self, term: Term) -> None:
        self.filters.append(Filter("genre", values=(norm_genre(term.value),)))

    def year(self, term: Term) -> None:
        rng = parse_year_range(term.value)
        if rng is None:
            # Unparseable, not "no constraint": `_filter_sql` turns a bare Filter("year") into
            # `0 = 1` inside its OR group (I2), same as any other unresolvable value.
            self.filters.append(Filter("year"))
            return
        self.filters.append(Filter("year", lo=rng[0], hi=rng[1]))

    def text(self, term: Term) -> None:
        self.filters.append(Filter("text", values=(term.value,)))


def run_search(repo: Repository, text: str) -> SearchResult:
    parsed = parse_query(text)
    hints = list(parsed.hints)
    resolver = _Resolver(repo)
    dispatch: dict[str, Callable[[Term], None]] = {
        "person": resolver.person,
        "character": resolver.character,
        "keyword": resolver.keyword,
        "title": resolver.title,
        "genre": resolver.genre,
        "year": resolver.year,
        "text": resolver.text,
    }
    by_field: dict[str, list[Term]] = {}
    for term in parsed.terms:
        by_field.setdefault(term.field, []).append(term)
    people_asked = False
    for field, terms in by_field.items():
        kind = FIELDS[field].kind
        if kind in ("person", "character"):
            people_asked = True
        for term in terms:
            dispatch[kind](term)
    if people_asked and repo.credits_summary()["films_with_credits"] == 0:
        hints.append(NO_CREDITS_HINT)
    hints.extend(resolver.hints)
    ids = repo.search_films(resolver.filters, parsed.free)
    # Only when the freeform words stood alone: a field term that emptied the result is
    # its own explanation (a correction, a suggestion or a too-short hint), and blaming the
    # words would send the user to fix the wrong thing.
    if not ids and not parsed.terms and len(parsed.free.split()) >= 2:
        n = len(parsed.free.split())
        hints.append(f"no film matches all {n} words — try fewer, or quote a phrase")
    return SearchResult(
        ids=tuple(i for i, _ in ids),
        ranked=bool(parsed.free.strip()) and bool(ids),
        corrections=tuple(resolver.corrections),
        suggestions=tuple(resolver.suggestions),
        hints=tuple(hints),
    )
