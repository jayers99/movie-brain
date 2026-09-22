#!/usr/bin/env bash
# Build the three paths a gap checker needs, so it can never see the working
# tree, git history or a credential: a git-archive of one commit, a copy of one
# database backup in a config dir of its own, and the findings path.
#   scripts/gap_check_snapshot.sh <commit> <db-file> [name]
# Prints PROJECT=, CONFIG=, FINDINGS=. A rerun with the same name replaces it.
# Spec: docs/superpowers/specs/2026-09-21-gap-checker-design.md §5.
set -euo pipefail

usage() { echo "usage: $0 <commit> <db-file> [name]" >&2; exit 2; }
[ $# -ge 2 ] || usage
COMMIT="$1"; DB="$2"
[ -f "$DB" ] || { echo "no such database: $DB" >&2; exit 2; }
NAME="${3:-$(git rev-parse --short "$COMMIT")}"
ROOT="${CLAUDE_SCRATCHPAD:-${TMPDIR:-/tmp}}/gap-check/$NAME"
PROJECT="$ROOT/project"; CONFIG="$ROOT/config"

rm -rf "$ROOT"
mkdir -p "$PROJECT" "$CONFIG"
git archive "$COMMIT" | tar -x -C "$PROJECT"
cp "$DB" "$CONFIG/movie-brain.db"
chmod 600 "$CONFIG/movie-brain.db"

echo "PROJECT=$PROJECT"
echo "CONFIG=$CONFIG"
echo "FINDINGS=$ROOT/FINDINGS.md"
