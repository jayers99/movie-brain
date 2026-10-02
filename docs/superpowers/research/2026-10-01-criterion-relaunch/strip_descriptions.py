"""Owner ruling 2026-10-01: this repo is public, so Criterion's own prose stays out of it.

JW JSON captures keep every key but blank the prose ones (description*, introduction_primary).
The two HTML pages are cut down to the exact tokens the leaving parser reads — the
`/discover/…` links and the RSC `playlistID` fields, verbatim, in page order — inside a
minimal HTML shell. Run once after a fresh capture; idempotent.
"""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).parent
PROSE = ("description", "description_long", "description_medium", "description_pull_quote",
         "description_staff", "introduction_primary")


def blank(obj):
    if isinstance(obj, dict):
        return {k: ("" if k in PROSE and isinstance(v, str) else blank(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [blank(v) for v in obj]
    return obj


for f in sorted(HERE.glob("jw-*.json")):
    f.write_text(json.dumps(blank(json.loads(f.read_text())), ensure_ascii=False, indent=1))
    print("blanked", f.name)

TOKEN = re.compile(r'href="/discover/[^"]*"|\\"playlistID\\":\\"[A-Za-z0-9]{8}\\"')
for f in sorted(HERE.glob("*.html")):
    text = f.read_text()
    if text.startswith("<!-- excerpt"):
        continue
    tokens = TOKEN.findall(text)
    body = "\n".join(f'<a {t}></a>' if t.startswith("href") else f'<script>self.__next_f.push([1,"{t}"])</script>'
                     for t in tokens)
    f.write_text(f"<!-- excerpt of {f.name}: the parser's tokens only, verbatim and in order; prose removed (public repo) -->\n<html><body>\n{body}\n</body></html>\n")
    print("excerpted", f.name, len(tokens), "tokens")
