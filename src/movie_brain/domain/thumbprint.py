"""Thumbprint: the work-identity resolver (design memo 2026-08-25, §2 grammar + §3 ALG3).

Pure: no I/O, no SQL. ``resolve()`` is a verbatim port of the eval prototype's ALG3 —
every reason string is part of the benchmark contract (``scripts/thumbprint_benchmark.py``).
Apple runtime is carried on the ``Query`` for display only and is never scored (owner Q3).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from movie_brain.domain.matching import norm_title

# --- title grammar -----------------------------------------------------------------------

VOCAB = (
    r"(?:the |a )?(?:director'?s cut|director'?s edition|final cut|extended (?:director'?s )?cut|"
    r"extended edition|uncut(?: version)?|unrated(?: (?:director'?s cut|version|edition))?|"
    r"theatrical (?:version|cut)|ultimate edition|(?:\d+(?:st|nd|rd|th) )?anniversary (?:special )?edition|"
    r"special edition|collector'?s edition|definitive edition|re-?released?|restored(?: version)?|"
    r"in color & restored|remastered(?: feature)?|4k(?: restoration| remaster)?|redux|"
    r"english[- ]dubbed version|english version|german version|dubbed|subtitled|imax|3d)"
)
_TRAIL = re.compile(
    r"\s*(?:\((?P<p>" + VOCAB + r")\)|\[(?P<b>" + VOCAB + r")\]|[:–—-]\s*(?P<c>" + VOCAB + r")|\s(?P<w>redux))\s*$",
    re.I,
)
_YEAR = re.compile(r"\s*[\(\[](\d{4})[\)\]]\s*$")
_ALT = re.compile(r"\s*\((?P<a>[^()]+)\)\s*$")


@dataclass(frozen=True)
class ParsedTitle:
    """``title`` is the search form (editions and year peeled, an alt-title parenthetical
    kept — that is what the candidate fixture was fetched with); ``base`` drops the alt
    parenthetical too; ``alt_titles`` are those parentheticals, kept for matching."""

    title: str
    editions: tuple[str, ...]
    embedded_year: int | None
    alt_titles: tuple[str, ...]

    @property
    def base(self) -> str:
        t = self.title
        for alt in self.alt_titles:
            t = t[: -len(alt) - 2].rstrip() if t.endswith(f"({alt})") else t
        return t or self.title

    def forms(self) -> tuple[str, ...]:
        """Every title string a candidate may legitimately carry."""
        return tuple(dict.fromkeys((self.title, self.base, *self.alt_titles)))


def parse_title(raw: str) -> ParsedTitle:
    t = raw.strip()
    eds: list[str] = []
    year: int | None = None
    while True:
        m = _YEAR.search(t)
        if m and t[: m.start()].strip():
            year = int(m.group(1))
            t = t[: m.start()].strip()
            continue
        m = _TRAIL.search(t)
        if m and t[: m.start()].strip():
            eds.append(next(g for g in m.groups() if g).casefold())
            t = t[: m.start()].strip()
            continue
        break
    alts: list[str] = []
    m = _ALT.search(t)
    if m and t[: m.start()].strip():
        alts.append(m.group("a").strip())
    return ParsedTitle(t, tuple(eds), year, tuple(alts))


def title_norm(raw: str) -> str:
    return norm_title(parse_title(raw).base)


# --- query / candidates --------------------------------------------------------------------


class YearClass(StrEnum):
    DATABASE = "database"
    MC = "mc"
    APPLE_FIELD = "apple-field"


@dataclass(frozen=True)
class Query:
    raw_title: str
    year: int | None
    year_class: YearClass
    source: str
    director: str | None = None
    runtime_min: int | None = None  # displayed in review rows, never scored
    parsed: ParsedTitle = field(default_factory=lambda: ParsedTitle("", (), None, ()))

    @property
    def title(self) -> str:
        return self.parsed.title

    @property
    def editions(self) -> tuple[str, ...]:
        return self.parsed.editions


def make_query(
    raw_title: str,
    year: int | None,
    source: str,
    director: str | None = None,
    runtime_min: int | None = None,
) -> Query:
    p = parse_title(raw_title)
    if source in ("criterion", "benchmark") or p.embedded_year is not None:
        yc = YearClass.DATABASE
    elif source == "metacritic":
        yc = YearClass.MC
    else:
        yc = YearClass.APPLE_FIELD
    return Query(raw_title, p.embedded_year or year, yc, source, director or None, runtime_min, p)


@dataclass(frozen=True)
class Candidate:
    tt: str
    tmdb_id: int | None
    titles: tuple[str, ...]
    year: int | None
    directors: str
    runtime_min: int | None
    votes: int
    kind: str
    in_tmdb: bool
    in_omdb: bool
    omdb_title: str = ""  # junk-shape check runs on OMDb's own title, as the prototype did


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    score: int
    title_level: int
    year_points: int
    director_points: int
    agreement: bool
    older: bool


@dataclass(frozen=True)
class Verdict:
    kind: str  # "match" | "review"
    tt: str | None
    reason: str
    ranked: tuple[Scored, ...]


# --- signals -------------------------------------------------------------------------------

JUNK = re.compile(
    r"\bmaking\b|bande-annonce|trailer|q&a|\bpanel\b|behind the scenes|a look at|featurette|"
    r"sing-along|timelapse|\bw/\b|on pov|\breviews?\b|the journey to|podcast",
    re.I,
)


def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(ch))


def name_tokens(s: str | None) -> set[str]:
    return {
        t
        for n in re.split(r",| and |&", _fold(s or "").replace("n/a", ""))
        for t in re.split(r"[\s.\-']+", n)
        if len(t) >= 3
    }


def dir_match(a: str | None, b: str | None) -> bool | None:
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return None
    common = ta & tb
    return len(common) >= 2 or (len(common) == 1 and (len(ta) <= 2 or len(tb) <= 2))


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


_ARTICLE = re.compile(r"^(the|an|a)\s+", re.I)


def article_norm(title: str) -> str:
    """`norm_title` after dropping one leading English article — *The Bride of Frankenstein*
    vs TMDB's *Bride of Frankenstein*. English only on purpose (*La Strada* is not *Strada*).
    Folding both sides means "The Ring" and "A Ring" land on the same key too. Never returns
    empty: a title that strips to nothing (e.g. "The ...") falls back to the un-stripped norm."""
    stripped = _ARTICLE.sub("", title.strip(), count=1)
    return norm_title(stripped) or norm_title(title.strip())


def title_level(q: Query, c: Candidate, *, article_ok: bool = False) -> int:
    forms = {norm_title(f) for f in q.parsed.forms()}
    nt = norm_title(q.title)
    if any(norm_title(x) in forms for x in c.titles if x):
        return 3
    if article_ok:
        aforms = {article_norm(f) for f in q.parsed.forms()}
        if any(article_norm(x) in aforms for x in c.titles if x):
            return 3
    if any(norm_title(x).startswith(nt) and len(nt) >= 8 for x in c.titles if x):
        return 2
    return 1 if max((_sim(q.title, x) for x in c.titles if x), default=0.0) >= 0.85 else 0


# --- verdict (ALG3) -------------------------------------------------------------------------


def _dominant(cands: list[Scored]) -> Scored | None:
    vs = sorted(cands, key=lambda s: -s.candidate.votes)
    top = vs[0]
    if top.candidate.votes >= 1000 and (len(vs) == 1 or top.candidate.votes >= 20 * max(1, vs[1].candidate.votes)):
        return top
    return None


def resolve(q: Query, candidates: Sequence[Candidate]) -> Verdict:  # noqa: C901 - the rule table IS the contract
    cd = q.director or ""
    surv: list[Scored] = []
    conflicts = 0
    junk_query = bool(JUNK.search(q.title))
    article_ok = not any(title_level(q, c) == 3 for c in candidates)
    for c in candidates:
        lvl = title_level(q, c, article_ok=article_ok)
        if lvl == 0:
            continue
        if JUNK.search(c.omdb_title) and not junk_query:
            continue
        dm = 0
        if cd and c.directors:
            m = dir_match(cd, c.directors)
            if m:
                dm = 3
            elif m is False:
                conflicts += 1
                continue
        if c.kind not in ("movie", "") and dm != 3:
            continue
        y, cy = q.year, c.year
        yp = 0
        older = False
        if y is not None and cy is not None:
            if abs(cy - y) <= 1:
                yp = 2
            elif abs(cy - y) <= 2:
                yp = 1
            elif dm == 3:
                yp = 0  # director match: the year is not the decider
            elif q.year_class in (YearClass.MC, YearClass.APPLE_FIELD) and cy < y:
                older = True  # commerce/edition year trails the original: neutral, not evidence
            else:
                continue
        agree = c.in_tmdb and c.in_omdb
        surv.append(Scored(c, lvl + yp + dm + (1 if agree else 0), lvl, yp, dm, agree, older))

    def out(kind: str, tt: str | None, reason: str) -> Verdict:
        return Verdict(kind, tt, reason, tuple(sorted(surv, key=lambda s: -s.score)[:3]))

    if not surv:
        return out("review", None, "no candidates" if not conflicts else "director conflicts only")
    exact = [s for s in surv if s.title_level == 3]
    if exact:
        surv = exact  # exact title beats longer-official-title candidates outright
    surv.sort(key=lambda s: -s.score)
    top = surv[0]
    dirhits = [s for s in surv if s.director_points == 3]
    if len(dirhits) == 1 and dirhits[0].title_level >= 2:
        return out("match", dirhits[0].candidate.tt, "director corroborated")
    if len(dirhits) > 1:
        strong = [s for s in dirhits if s.agreement or s.candidate.votes >= 100]
        if len(strong) == 1 and strong[0].title_level >= 2:
            return out(
                "match", strong[0].candidate.tt, "director corroborated (one keyed/voted entry among duplicates)"
            )
        return out("review", None, "ambiguous (several director hits)")
    generic = len(q.title.split()) <= 2 and not cd
    # an OMDb-only, vote-less entry duplicating a TMDB-keyed candidate at the same title+year
    # is an IMDb duplicate, not a rival
    keyed_years = {s.candidate.year for s in surv if s.candidate.in_tmdb}
    surv = [
        s for s in surv if not (not s.candidate.in_tmdb and s.candidate.votes < 10 and s.candidate.year in keyed_years)
    ]
    near = [s for s in surv if s.year_points >= 1]
    old = [s for s in surv if s.older]
    near1 = [s for s in near if s.year_points == 2]
    if old and (
        (q.year_class is YearClass.APPLE_FIELD and near)
        or (q.year_class is YearClass.MC and near and not near1)
        or (q.editions and near)
    ):
        # an exact-title film sits near the claimed year AND an older exact-title film exists:
        # Apple field years are remaster-prone and edition years are edition years → never guess
        return out("review", None, "rerelease-ambiguous")
    if near:
        n0 = near[0]
        if len(near) == 1 and (n0.agreement or n0.candidate.votes >= 1000 or (not generic and n0.year_points == 2)):
            return out("match", n0.candidate.tt, "exact title + year" + (" + agreement" if n0.agreement else ""))
        d = _dominant(near)
        if d:
            return out("match", d.candidate.tt, "votes dominate among year-near exact titles")
        return out("review", None, "ambiguous")
    if old and q.year_class in (YearClass.MC, YearClass.APPLE_FIELD):
        # nothing at the claimed year: the claimed year is a re-release/commerce date
        if len(old) == 1 and old[0].agreement:
            return out("match", old[0].candidate.tt, "unique older exact title (commerce year = re-release)")
        d = _dominant(old)
        if d and d.agreement:
            return out("match", d.candidate.tt, "votes dominate among older exact titles")
        return out("review", None, "ambiguous (older candidates)")
    if q.year is None and len(surv) == 1 and top.agreement and not generic:
        return out("match", top.candidate.tt, "dateless: unique exact + agreement")
    if top.title_level == 2 and top.year_points >= 1 and top.agreement:
        return out("match", top.candidate.tt, "longer official title + year + agreement")
    return out("review", None, "weak")
