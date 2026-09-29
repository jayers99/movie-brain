# Preflight for the second-lineage gap checker

You are being run to confirm that this harness (Codex CLI, sandboxed) can do everything the gap checker will later need on a snapshot of movie-brain. This is NOT a gap check: find nothing, judge nothing, report only whether each step below works here. Every failure you hit is a harness failure to report with its exact error text, never something to work around silently.

You are read-only on everything except the two files this checklist tells you to write. Never edit anything under the project directory.

## Paths (filled in by the launcher)

```
Point: A | C
Project directory: <PROJECT>
Config directory (set MOVIE_BRAIN_CONFIG_DIR to this): <CONFIG>
Findings file to write: <FINDINGS>
Dashboard port range: <e.g. 5700–5709>
```

## The checklist, in order

1. **Read the snapshot.** `ls` the project directory and print the first 20 lines of its `CLAUDE.md`. Then `ls` the config directory. Do NOT read anything outside these two directories, do not run `git`, and do not look for a `credentials.toml`.
2. **Query the database copy.** `sqlite3 <CONFIG>/movie-brain.db "SELECT COUNT(*) FROM films; SELECT MAX(version) FROM schema_version;"` and record both numbers.
3. **Start the dashboard.** From the project directory, with `MOVIE_BRAIN_CONFIG_DIR` set to the config directory, run `uv run --no-sync movie-brain dashboard --port <a port in the range>` in the background, wait for it, and `curl -s http://127.0.0.1:<port>/api/films | head -c 300`. Record whether it answered and how many films the page lists (`curl -s .../api/films | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'` from the project directory's own interpreter, `uv run --no-sync python`). If `uv run` fails, record the exact error.
4. **Drive it with Playwright.** With `uv run --no-sync python -c '...'` and `playwright.sync_api` (chromium is installed): open the dashboard page, wait for `#films tbody[data-count]`, click the `.c-year` cell of the first row, wait for `#drawer h2`, print its text, and save a screenshot to `<CONFIG>/../preflight-screenshot.png`. Record whether the browser launched, whether the drawer opened, and whether the screenshot file exists afterwards (`ls -l`).
5. **Write a scratch file** beside the findings file: `<CONFIG>/../preflight-write.txt` containing the word `ok`. Record whether the write succeeded.
6. **Stop the dashboard** you started (kill the background process) and confirm the port is free.

## Your one final message

Your LAST message is written to the findings file by the launcher, so make it exactly this — nothing before it, nothing after:

```
# Codex preflight

| Step | Result | Evidence |
|---|---|---|
| 1 read snapshot | ok / FAILED | … |
| 2 sqlite | ok / FAILED | films=N schema=N |
| 3 dashboard | ok / FAILED | port, films listed, or the error |
| 4 playwright | ok / FAILED | drawer title, screenshot path or the error |
| 5 write | ok / FAILED | path or the error |
| 6 stop | ok / FAILED | … |

Failures are harness failures: <one line naming each failed step and the exact error, or "none">.
```
