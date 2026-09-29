#!/usr/bin/env bash
# The second-lineage gap checker (spec docs/superpowers/specs/2026-09-29-two-lineage-gap-check.md,
# step 2): ONE Codex CLI subprocess on the same snapshot and the same prompt the Claude checker
# gets, its last message written out as the findings file. Files in, a subprocess, a file out —
# no MCP, no chat, no diff reviewer, no findings cap.
#
#   scripts/gap_check_codex.sh --point C --feature <brief-folder> --project P --config C \
#       --findings F [--ports 5710–5719] [--prompt docs/superpowers/checks/gap-check.md] \
#       [--recheck "1, 4, 7"] [--model gpt-6-astra] [--effort high] [--sandbox danger-full-access]
#
# P, C, F are the three lines scripts/gap_check_snapshot.sh printed (F may be a sibling name such
# as FINDINGS-codex.md so the Claude checker's own findings file is never overwritten). The
# filled prompt is written beside F (F.prompt.md) so the exact words are on record; Codex's
# stdout/stderr go to F.log; the script prints the elapsed seconds and Codex's exit code.
#
# Sandbox (preflight 2026-09-29, docs/superpowers/checks/codex-preflight-2026-09-29.md): the
# page's `-s read-only` cannot run `uv` (it opens its cache read-write), write a screenshot or
# a findings file; `workspace-write` can write but cannot bind the dashboard's port or launch
# chromium (its seatbelt denies the mach bootstrap chromium's renderers need). Only
# `danger-full-access` reaches the app, so that is the default: the Codex checker is then held
# by the same things that hold the Claude subagent — the prompt (read nothing outside the two
# directories, run no git, look for no credential) and the snapshot itself (a git-archive plus a
# database copy holding no credentials.toml, never the repository). "Read-only" is the prompt's
# rule, not an OS guarantee, on both sides.
#
# Before launching, the snapshot's virtualenv is built once (`uv sync --extra semantic`, from
# the local cache) — the same prepared tree the Claude checker then runs on.
set -euo pipefail

POINT=""; FEATURE=""; PROJECT=""; CONFIG=""; FINDINGS=""; PORTS="5710–5719"
PROMPT="docs/superpowers/checks/gap-check.md"; RECHECK=""
MODEL="${GAP_CODEX_MODEL:-gpt-6-astra}"; EFFORT="${GAP_CODEX_EFFORT:-high}"; SANDBOX="${GAP_CODEX_SANDBOX:-danger-full-access}"
usage() { sed -n '2,10p' "$0" >&2; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --point) POINT="$2"; shift 2 ;;
    --feature) FEATURE="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --findings) FINDINGS="$2"; shift 2 ;;
    --ports) PORTS="$2"; shift 2 ;;
    --prompt) PROMPT="$2"; shift 2 ;;
    --recheck) RECHECK="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --effort) EFFORT="$2"; shift 2 ;;
    --sandbox) SANDBOX="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$POINT" ] && [ -n "$PROJECT" ] && [ -n "$CONFIG" ] && [ -n "$FINDINGS" ] || usage
[ -d "$PROJECT" ] || { echo "no such project snapshot: $PROJECT" >&2; exit 2; }
[ -f "$CONFIG/movie-brain.db" ] || { echo "no database copy in $CONFIG" >&2; exit 2; }
[ -f "$PROMPT" ] || { echo "no such prompt: $PROMPT" >&2; exit 2; }
command -v codex >/dev/null || { echo "codex CLI not on PATH" >&2; exit 2; }
ROOT="$(cd "$(dirname "$PROJECT")" && pwd)"
case "$FINDINGS" in "$ROOT"/*) ;; *) echo "findings file must sit inside the snapshot root $ROOT" >&2; exit 2 ;; esac

# Fill the Paths block exactly as the session fills it for the Claude checker.
FILLED="${FINDINGS}.prompt.md"
sed -e "s|^Point: A \| C$|Point: $POINT|" \
    -e "s|<PROJECT>|$PROJECT|g" \
    -e "s|<CONFIG>|$CONFIG|g" \
    -e "s|<FINDINGS>|$FINDINGS|g" \
    -e "s|<feature>|$FEATURE|g" \
    -e "s|<e.g. 5700–5709>|$PORTS|g" \
    "$PROMPT" > "$FILLED"
if [ -n "$RECHECK" ]; then printf '\nRe-check only findings: %s\n' "$RECHECK" >> "$FILLED"; fi

# Prepare the snapshot's own virtualenv once, outside the sandbox, from the local uv cache.
if [ ! -x "$PROJECT/.venv/bin/python" ]; then
  ( cd "$PROJECT" && uv sync --extra semantic --quiet )
fi

LOG="${FINDINGS}.log"
echo "codex $(codex --version 2>/dev/null) · model $MODEL · effort $EFFORT · sandbox $SANDBOX · root $ROOT · prompt $FILLED" | tee "$LOG"
START=$(date +%s)
set +e
MOVIE_BRAIN_CONFIG_DIR="$CONFIG" codex exec \
  -C "$ROOT" -s "$SANDBOX" -m "$MODEL" -c "model_reasoning_effort=\"$EFFORT\"" \
  -c "shell_environment_policy.inherit=\"all\"" \
  --skip-git-repo-check --ephemeral --color never \
  --output-last-message "$FINDINGS" - < "$FILLED" >> "$LOG" 2>&1
RC=$?
set -e
END=$(date +%s)
echo "elapsed=$((END - START))s exit=$RC findings=$FINDINGS log=$LOG"
[ -s "$FINDINGS" ] || echo "WARNING: no findings file was written (harness failure — see $LOG)" >&2
exit $RC
