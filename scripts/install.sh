#!/bin/bash
# Generate the voice2note LaunchAgent from the template and load it.
# Usage: ./scripts/install.sh [/path/to/ObsidianVault] [--no-cricknote]
# Vault resolution order: argument > $VOICE2NOTE_VAULT > config file.
#
# CrickNote integration resolution (VOICE2NOTE_USE_CRICKNOTE):
#   1. --no-cricknote               -> forced standalone (false)
#   2. value in the process env     -> wins
#   3. value in the selected config -> next
#   4. otherwise auto-detect `cricknote` on PATH, gated on a vault match.
# Config file is parsed (KEY=VALUE), never sourced/executed.
set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$PROJECT_DIR/com.voice2note.agent.plist.template"
LA_DIR="$HOME/Library/LaunchAgents"
PLIST="$LA_DIR/com.voice2note.agent.plist"
PYTHON="${VOICE2NOTE_PYTHON:-/usr/bin/python3}"
INTERVAL="${VOICE2NOTE_INTERVAL:-7200}"
PATH_VALUE="$HOME/.npm-global/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
CONFIG_FILE="${VOICE2NOTE_CONFIG:-$PROJECT_DIR/voice2note.env}"

die() { echo "ERROR: $*" >&2; exit 1; }

# --- Parse args (vault positional + optional --no-cricknote). ---
NO_CRICKNOTE=0
VAULT_ARG=""
for arg in "$@"; do
  case "$arg" in
    --no-cricknote) NO_CRICKNOTE=1 ;;
    -*) die "unknown option: $arg" ;;
    *) [ -z "$VAULT_ARG" ] && VAULT_ARG="$arg" ;;
  esac
done

# --- Read a KEY from the config file without sourcing it (strip surrounding quotes). ---
config_get() {
  local key="$1"
  [ -f "$CONFIG_FILE" ] || return 0
  local line
  line="$(grep -E "^[[:space:]]*${key}=" "$CONFIG_FILE" | head -1 || true)"
  [ -z "$line" ] && return 0
  local val="${line#*=}"
  # strip leading/trailing whitespace
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  # strip one layer of matching quotes
  case "$val" in
    \"*\") val="${val%\"}"; val="${val#\"}" ;;
    \'*\') val="${val%\'}"; val="${val#\'}" ;;
  esac
  printf '%s' "$val"
}

# --- Normalize a boolean to true/false; die on invalid non-empty value. ---
# Mirrors config.py spellings; stricter (rejects unknown values).
normalize_bool() {
  local raw="$1"
  local v
  v="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  case "$v" in
    1|true|yes|on)  echo "true" ;;
    0|false|no|off) echo "false" ;;
    *) die "invalid boolean for VOICE2NOTE_USE_CRICKNOTE: '$raw' (use 1/true/yes/on or 0/false/no/off)" ;;
  esac
}

# --- Vault resolution: arg > env > config. ---
VAULT="${VAULT_ARG:-${VOICE2NOTE_VAULT:-}}"
[ -z "$VAULT" ] && VAULT="$(config_get VOICE2NOTE_VAULT)"
if [ -z "$VAULT" ]; then
  echo "ERROR: vault path not set." >&2
  echo "  ./scripts/install.sh \"\$HOME/path/to/ObsidianVault\"" >&2
  echo "  (or set VOICE2NOTE_VAULT, or add it to the config file)" >&2
  exit 1
fi

# --- MEMO_RELDIR: env > config > default; validate (reject absolute or '..'). ---
MEMO_RELDIR="${VOICE2NOTE_MEMO_RELDIR:-}"
[ -z "$MEMO_RELDIR" ] && MEMO_RELDIR="$(config_get VOICE2NOTE_MEMO_RELDIR)"
[ -z "$MEMO_RELDIR" ] && MEMO_RELDIR="Memory/voiceMemo"
case "$MEMO_RELDIR" in
  /*) die "VOICE2NOTE_MEMO_RELDIR must be relative (got absolute): '$MEMO_RELDIR'" ;;
esac
case "/$MEMO_RELDIR/" in
  */../*) die "VOICE2NOTE_MEMO_RELDIR must not contain '..': '$MEMO_RELDIR'" ;;
esac

# --- CrickNote binary name/path: env > config > default 'cricknote'. ---
CRICKNOTE_BIN_RAW="${VOICE2NOTE_CRICKNOTE_BIN:-}"
[ -z "$CRICKNOTE_BIN_RAW" ] && CRICKNOTE_BIN_RAW="$(config_get VOICE2NOTE_CRICKNOTE_BIN)"

# --- USE_CRICKNOTE resolution. ---
# Determine the explicit setting source (env > config); empty means "auto".
USE_RAW=""
USE_EXPLICIT=0
if [ -n "${VOICE2NOTE_USE_CRICKNOTE+x}" ] && [ -n "$VOICE2NOTE_USE_CRICKNOTE" ]; then
  USE_RAW="$VOICE2NOTE_USE_CRICKNOTE"
  USE_EXPLICIT=1
else
  cfg_use="$(config_get VOICE2NOTE_USE_CRICKNOTE)"
  if [ -n "$cfg_use" ]; then
    USE_RAW="$cfg_use"
    USE_EXPLICIT=1
  fi
fi

# Resolve a command/path to an absolute executable; echoes path or empty.
resolve_bin() {
  local name="${1:-cricknote}"
  local p
  p="$(command -v "$name" 2>/dev/null || true)"
  [ -n "$p" ] && { (cd "$(dirname "$p")" && printf '%s/%s' "$(pwd)" "$(basename "$p")"); return 0; }
  return 1
}

# Compare VOICE2NOTE_VAULT against ~/.cricknote/config.json vaultPath by realpath.
# Returns 0 on match, 1 otherwise (also 1 if config unreadable).
vault_matches_cricknote() {
  "$PYTHON" - "$VAULT" "$HOME/.cricknote/config.json" <<'PYEOF'
import json, os, sys
v2n, cfg = sys.argv[1], sys.argv[2]
try:
    data = json.loads(open(cfg, encoding="utf-8").read())
    ck = data["vaultPath"]
except Exception:
    sys.exit(1)
sys.exit(0 if os.path.realpath(v2n) == os.path.realpath(ck) else 1)
PYEOF
}

USE_CRICKNOTE="false"
CRICKNOTE_BIN="cricknote"   # default placeholder value when disabled
BIN_DIR=""

if [ "$NO_CRICKNOTE" -eq 1 ]; then
  USE_CRICKNOTE="false"
  echo "CrickNote integration disabled via --no-cricknote (standalone mode)."
elif [ "$USE_EXPLICIT" -eq 1 ]; then
  USE_CRICKNOTE="$(normalize_bool "$USE_RAW")"
  if [ "$USE_CRICKNOTE" = "true" ]; then
    # Fail closed: binary must resolve AND vault must match.
    if ! abs="$(resolve_bin "${CRICKNOTE_BIN_RAW:-cricknote}")"; then
      die "VOICE2NOTE_USE_CRICKNOTE=true but cricknote binary not found/executable: '${CRICKNOTE_BIN_RAW:-cricknote}'"
    fi
    if ! vault_matches_cricknote; then
      die "VOICE2NOTE_USE_CRICKNOTE=true but ~/.cricknote/config.json vaultPath does not match VOICE2NOTE_VAULT ($VAULT)"
    fi
    CRICKNOTE_BIN="$abs"
    BIN_DIR="$(dirname "$abs")"
  fi
else
  # Auto-detect, gated on vault match.
  if abs="$(resolve_bin "${CRICKNOTE_BIN_RAW:-cricknote}")"; then
    if vault_matches_cricknote; then
      USE_CRICKNOTE="true"
      CRICKNOTE_BIN="$abs"
      BIN_DIR="$(dirname "$abs")"
    else
      USE_CRICKNOTE="false"
      echo "CrickNote found but vault differs from ~/.cricknote/config.json; installing standalone (integration skipped)."
    fi
  else
    USE_CRICKNOTE="false"
    echo "CrickNote not detected; installing standalone."
    echo "  To enable later: install CrickNote, point ~/.cricknote/config.json vaultPath at this vault,"
    echo "  then re-run with VOICE2NOTE_USE_CRICKNOTE=true (or let auto-detect pick it up)."
  fi
fi

# When enabled, prepend the binary's directory to the plist PATH if absent.
if [ "$USE_CRICKNOTE" = "true" ] && [ -n "$BIN_DIR" ]; then
  case ":$PATH_VALUE:" in
    *":$BIN_DIR:"*) ;;
    *) PATH_VALUE="$BIN_DIR:$PATH_VALUE" ;;
  esac
fi

command -v whisper-cli >/dev/null || echo "WARN: whisper-cli not found  ->  brew install whisper-cpp"
command -v ffmpeg      >/dev/null || echo "WARN: ffmpeg not found       ->  brew install ffmpeg"
command -v codex       >/dev/null || echo "WARN: codex not found        ->  npm i -g @openai/codex && codex login"
[ -f "$PROJECT_DIR/models/ggml-small.bin" ] || echo "WARN: model missing      ->  ./scripts/download-model.sh"

mkdir -p "$LA_DIR" "$PROJECT_DIR/logs"

# --- Generate the plist with plistlib so all values are XML-escaped safely. ---
# The template provides the structure; structural path placeholders are substituted,
# then EnvironmentVariables is rebuilt from resolved values. No __...__ may remain.
V2N_TEMPLATE="$TEMPLATE" \
V2N_OUT="$PLIST" \
V2N_PYTHON="$PYTHON" \
V2N_PROJECT_DIR="$PROJECT_DIR" \
V2N_PATH="$PATH_VALUE" \
V2N_VAULT="$VAULT" \
V2N_USE_CRICKNOTE="$USE_CRICKNOTE" \
V2N_CRICKNOTE_BIN="$CRICKNOTE_BIN" \
V2N_MEMO_RELDIR="$MEMO_RELDIR" \
V2N_INTERVAL="$INTERVAL" \
"$PYTHON" - <<'PYEOF'
import os, plistlib

env = os.environ
template = env["V2N_TEMPLATE"]
out = env["V2N_OUT"]

# Structural placeholders (paths/integers) are safe to substitute as text because
# they go through plistlib re-parse + re-serialize below, which re-escapes everything.
text = open(template, encoding="utf-8").read()
subs = {
    "__PYTHON__": env["V2N_PYTHON"],
    "__PROJECT_DIR__": env["V2N_PROJECT_DIR"],
    "__INTERVAL__": env["V2N_INTERVAL"],
    # Provide harmless values for env placeholders; the dict is rebuilt below anyway.
    "__PATH__": "",
    "__VAULT__": "",
    "__USE_CRICKNOTE__": "",
    "__CRICKNOTE_BIN__": "",
    "__MEMO_RELDIR__": "",
}
for k, v in subs.items():
    text = text.replace(k, v)

data = plistlib.loads(text.encode("utf-8"))

# Rebuild EnvironmentVariables from resolved values (plistlib escapes on write).
data["EnvironmentVariables"] = {
    "PATH": env["V2N_PATH"],
    "PYTHONPATH": env["V2N_PROJECT_DIR"],
    "VOICE2NOTE_VAULT": env["V2N_VAULT"],
    "VOICE2NOTE_USE_CRICKNOTE": env["V2N_USE_CRICKNOTE"],
    "VOICE2NOTE_CRICKNOTE_BIN": env["V2N_CRICKNOTE_BIN"],
    "VOICE2NOTE_MEMO_RELDIR": env["V2N_MEMO_RELDIR"],
}

with open(out, "wb") as fh:
    plistlib.dump(data, fh)
PYEOF

echo "Wrote $PLIST"
echo "  vault:        $VAULT"
echo "  python:       $PYTHON"
echo "  interval:     ${INTERVAL}s"
if [ "$USE_CRICKNOTE" = "true" ]; then
  echo "  mode:         cricknote (integration enabled)"
  echo "  cricknote:    $CRICKNOTE_BIN"
else
  echo "  mode:         standalone"
fi
echo "  memo folder:  $MEMO_RELDIR"
echo "  plist PATH:   $PATH_VALUE"
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
