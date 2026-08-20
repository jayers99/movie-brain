#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_DIR="${MOVIE_BRAIN_CONFIG_DIR:-$HOME/.config/movie-brain}"
PLIST="$HOME/Library/LaunchAgents/com.jayers.movie-brain.plist"
mkdir -p "$CONFIG_DIR" "$HOME/Library/LaunchAgents"
KEY_FILE="$CONFIG_DIR/omdb-api-key.txt"
if [ ! -f "$KEY_FILE" ]; then
  if [ -n "${OMDB_API_KEY:-}" ]; then
    # launchd jobs don't inherit the shell environment, so the key must live in a
    # file the daemon can read regardless of who launched the installer.
    printf '%s' "$OMDB_API_KEY" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    echo "Wrote OMDB_API_KEY to $KEY_FILE (launchd does not inherit environment variables)"
  else
    echo "First: put your OMDb API key in $KEY_FILE (free at omdbapi.com/apikey.aspx)" >&2
    exit 1
  fi
fi
sed -e "s|__REPO__|$REPO|g" -e "s|__CONFIG_DIR__|$CONFIG_DIR|g" \
  "$REPO/launchd/com.jayers.movie-brain.plist.template" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Loaded. Daily sync: 3:00 AM. Log: $CONFIG_DIR/sync.log"
