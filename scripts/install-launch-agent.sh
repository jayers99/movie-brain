#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="${MOVIE_BRAIN_CONFIG_DIR:-$HOME/.config/movie-brain}"
PLIST="$HOME/Library/LaunchAgents/com.jayers.movie-brain.plist"
mkdir -p "$CONFIG_DIR" "$HOME/Library/LaunchAgents"
if [ ! -f "$CONFIG_DIR/omdb-api-key.txt" ] && [ -z "${OMDB_API_KEY:-}" ]; then
  echo "First: put your OMDb API key in $CONFIG_DIR/omdb-api-key.txt (free at omdbapi.com/apikey.aspx)" >&2
  exit 1
fi
sed -e "s|__REPO__|$REPO|g" -e "s|__CONFIG_DIR__|$CONFIG_DIR|g" \
  "$REPO/launchd/com.jayers.movie-brain.plist.template" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Loaded. Daily sync: 3:00 AM. Log: $CONFIG_DIR/sync.log"
