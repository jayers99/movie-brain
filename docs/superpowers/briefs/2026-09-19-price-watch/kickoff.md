# Kickoff prompt — build "Wishlist it" (paste into a fresh session)

Build backlog item 3's remaining half, "Wishlist it", from a FROZEN task brief. This is the first trial of a new process, and the trial covers the upstream half only — **the build process is unchanged**: write the plan, then subagent-driven development with TDD, then finishing. Do not re-open design questions.

**Read first, in this order:**

1. `docs/superpowers/briefs/2026-09-19-price-watch/brief.md` — version 1.0, frozen. It is the source of truth: what ships, what deliberately does not, acceptance examples with real films, every decision marked *your choice* / *agent default*, the execution authority, and the CheapCharts account API exactly as it was proven against the owner's real account.
2. `docs/superpowers/briefs/2026-09-19-price-watch/mockup-3.html` — the approved preview (open it in a browser). Where it and the brief disagree, the brief wins.
3. `docs/superpowers/briefs/2026-09-19-price-watch/trial-log.md` — what went wrong upstream, so it is not repeated.
4. `CLAUDE.md`, then `scripts/discovery/cheapcharts_wishlist_probe.py` (the proven calls in ~140 lines).

**Rules that bind the build (all from the brief — it has the detail):**

- No brainstorming and no multiple-choice questions to the owner. An *agent default* in the brief is decided; anything not covered and not visible, decide it and record it as a new agent default in the brief (amend to 1.1, never silently rewrite).
- Return to the owner only if new evidence breaks an approved behaviour, exceeds the authority in the brief, or prevents trustworthy verification — as a short decision packet worded as what he would SEE. He tags every interruption "needed" / "not needed"; log it in `trial-log.md`.
- **During the build nothing touches his real CheapCharts account — no login, no read, no write.** Tests mock HTTP with `responses`. Never print, log, fixture or commit a credential, session token, customer id, username or email. Never read `~/.config/movie-brain/credentials.toml` yourself.
- Not without a separate yes from him: any write to his real wishlist, `cheapcharts resolve --apply`, `migrate --apply` on the live database, a merge, a push.
- First slice is a thin end-to-end path tied to one acceptance example (button → route → mocked CheapCharts → heart on the row), so something visible exists early.
- Branch `feature/STORY-22-wishlist-it`. Migration 027. Gates after every task: `uv run pytest`, `uv run ruff check .`, `uv run mypy`, both benchmarks.

**Delivery, in this order:** the dashboard running on a scratch COPY of the live database; the acceptance examples passing as tests; a spoken summary under 100 words (the `play-it` skill); a plain list of anything unverified — including that the preview's 0.9-second click was not realistic (expect 5–10 s), the failure wording, and the two owned-and-wishlisted films he has never seen previewed. Then HIS hands-on test, including one real click on a film he chooses. Only after his say-so: `cheapcharts resolve` run (prerequisite — most films show no button until it runs), live migration, merge, push. Then update `CLAUDE.md`, tick backlog 3, and fill in the trial scorecard in `trial-log.md` (his total active minutes, interruptions needed / not needed, corrections by kind).
