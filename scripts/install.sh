#!/bin/bash
# Generate the voice2note LaunchAgent from the template and load it.
# Usage: ./scripts/install.sh [/path/to/ObsidianVault]
# Vault resolution order: argument > $VOICE2NOTE_VAULT > voice2note.env
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$PROJECT_DIR/com.voice2note.agent.plist.template"
LA_DIR="$HOME/Library/LaunchAgents"
PLIST="$LA_DIR/com.voice2note.agent.plist"
PYTHON="${VOICE2NOTE_PYTHON:-/usr/bin/python3}"
INTERVAL="${VOICE2NOTE_INTERVAL:-7200}"
PATH_VALUE="$HOME/.npm-global/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

VAULT="${1:-${VOICE2NOTE_VAULT:-}}"
if [ -z "$VAULT" ] && [ -f "$PROJECT_DIR/voice2note.env" ]; then
  VAULT="$(grep -E '^VOICE2NOTE_VAULT=' "$PROJECT_DIR/voice2note.env" | head -1 | cut -d= -f2-)"
fi
if [ -z "$VAULT" ]; then
  echo "ERROR: vault path not set."
  echo "  ./scripts/install.sh \"\$HOME/path/to/ObsidianVault\""
  echo "  (or set VOICE2NOTE_VAULT, or add it to voice2note.env)"
  exit 1
fi

command -v whisper-cli >/dev/null || echo "WARN: whisper-cli not found  ->  brew install whisper-cpp"
command -v ffmpeg      >/dev/null || echo "WARN: ffmpeg not found       ->  brew install ffmpeg"
command -v claude      >/dev/null || echo "WARN: claude not found       ->  npm i -g @anthropic-ai/claude-code && claude"
[ -f "$PROJECT_DIR/models/ggml-small.bin" ] || echo "WARN: model missing      ->  ./scripts/download-model.sh"

mkdir -p "$LA_DIR" "$PROJECT_DIR/logs"
sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__PATH__|$PATH_VALUE|g" \
    -e "s|__VAULT__|$VAULT|g" \
    -e "s|__INTERVAL__|$INTERVAL|g" \
    "$TEMPLATE" > "$PLIST"
echo "Wrote $PLIST"
echo "  vault:    $VAULT"
echo "  python:   $PYTHON"
echo "  interval: ${INTERVAL}s"
echo
echo ">> Grant Full Disk Access to $PYTHON before this can read Voice Memos:"
echo "   System Settings > Privacy & Security > Full Disk Access > +"
echo "   (in the dialog press Cmd+Shift+G, paste: $PYTHON), then toggle it ON."
echo
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Loaded com.voice2note.agent. It runs now and every ${INTERVAL}s."
echo "Watch:   tail -f \"$PROJECT_DIR/logs/run.log\""
echo "Run now: launchctl start com.voice2note.agent"
