"""Pure search helpers — no SQL, no I/O. Plan B's parser and resolver grow here.

`trigram_query` is the one thing Plan A needs: the FTS5 `trigram` tokenizer makes a bare
MATCH a SUBSTRING test ('bogrt' finds nothing), so misspelling tolerance is an OR of the
query's own trigrams — every name sharing at least one window comes back as a candidate,
and the resolver ranks those candidates. Verified against the stdlib sqlite3 2026-09-06.
"""

from __future__ import annotations


def trigram_query(text: str) -> str:
    """'Bogrt' → '"bog" OR "ogr" OR "grt"'. Empty when the text has no 3-character window —
    the tokenizer cannot match shorter terms, so the caller must not send MATCH at all."""
    s = text.lower()
    windows = [s[i : i + 3] for i in range(len(s) - 2)]
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in windows)
