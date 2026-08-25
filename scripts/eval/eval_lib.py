import re, unicodedata
VOCAB=r"(?:the |a )?(?:director'?s cut|director'?s edition|final cut|extended (?:director'?s )?cut|extended edition|uncut(?: version)?|unrated(?: (?:director'?s cut|version|edition))?|theatrical (?:version|cut)|ultimate edition|(?:\d+(?:st|nd|rd|th) )?anniversary (?:special )?edition|special edition|collector'?s edition|definitive edition|re-?released?|restored(?: version)?|in color & restored|remastered(?: feature)?|4k(?: restoration| remaster)?|redux|english[- ]dubbed version|english version|german version|dubbed|subtitled|imax|3d)"
_TRAIL=re.compile(r"\s*(?:\((?P<p>"+VOCAB+r")\)|\[(?P<b>"+VOCAB+r")\]|[:–—-]\s*(?P<c>"+VOCAB+r")|\s(?P<w>redux))\s*$",re.I)
_YEAR=re.compile(r"\s*[\(\[](\d{4})[\)\]]\s*$")
def parse(title):
    """-> (title_norm_form, edition_labels[], embedded_year|None). Trailing-only; leading parens are title."""
    t=title.strip(); eds=[]; year=None
    while True:
        m=_YEAR.search(t)
        if m and t[:m.start()].strip(): year=int(m.group(1)); t=t[:m.start()].strip(); continue
        m=_TRAIL.search(t)
        if m and t[:m.start()].strip():
            eds.append(next(g for g in m.groups() if g).casefold()); t=t[:m.start()].strip(); continue
        break
    return t, eds, year
def fold(s): return "".join(ch for ch in unicodedata.normalize("NFKD",s.casefold()) if not unicodedata.combining(ch))
def surnames(s):
    out=set()
    for n in re.split(r",| and |&",fold(s or "").replace("n/a","")):
        n=n.strip()
        if n: out.add(n.split()[-1].rstrip("."))
    return out
