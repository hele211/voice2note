#!/usr/bin/env bash
#
# smoke-cricknote-integration.sh — isolated end-to-end integration smoke (Task 5).
#
# Proves the voice2note → CrickNote seam end-to-end:
#   * runs the REAL voice2note process (`python3 -m voice2note.run --once`)
#   * drives the REAL installed `cricknote` CLI for the vault write + index + list
#   * stubs ONLY the expensive upstream tools (ffmpeg / whisper / codex)
#
# SAFETY: everything happens under a single mktemp -d root with a throwaway HOME
# and a throwaway vault. The script NEVER reads or writes the user's real Obsidian
# vault or the real ~/.cricknote — it only references the temp root plus the
# absolute path of the real cricknote binary (captured before HOME is redirected).
# The temp root is removed on success AND failure via a trap.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve the project dir (this script lives in <project>/scripts/).
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"

PY=/usr/bin/python3

fail() { echo "FAIL: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 5.1 — Capture the REAL cricknote path BEFORE redirecting HOME.
# ---------------------------------------------------------------------------
CRICKNOTE_BIN="$(command -v cricknote || true)"
[ -n "$CRICKNOTE_BIN" ] || fail "cricknote CLI not found on PATH; cannot run integration smoke."
[ -x "$CRICKNOTE_BIN" ] || fail "cricknote at $CRICKNOTE_BIN is not executable."
echo "Real cricknote: $CRICKNOTE_BIN"

# ---------------------------------------------------------------------------
# 5.1 — One temp root; cleanup trap removes the WHOLE root on EXIT.
# We capture the script's intended exit status explicitly so the trap's own
# `rm` success never masks a failure and turns it into a 0 exit.
# ---------------------------------------------------------------------------
TROOT="$(mktemp -d)"
SMOKE_RC=1   # default to failure; set to 0 only after we explicitly PASS
cleanup() {
    rm -rf "$TROOT" 2>/dev/null || true
    exit "$SMOKE_RC"
}
trap cleanup EXIT

# Throwaway HOME + vault + recordings + state/log/lock, all under the temp root.
export HOME="$TROOT/home"
export CRICKNOTE_DATA_DIR="$HOME/.cricknote"
VAULT_DIR="$TROOT/vault"
RECORDINGS_DIR="$TROOT/recordings"
STATE_PATH="$TROOT/state.json"
LOG_PATH="$TROOT/run.log"
LOCK_PATH="$TROOT/voice2note.lock"
STUB_DIR="$TROOT/stubs"
mkdir -p "$HOME" "$CRICKNOTE_DATA_DIR" "$VAULT_DIR" "$RECORDINGS_DIR" "$STUB_DIR"

# Use the realpath of the temp vault everywhere (macOS /var → /private/var symlink),
# so voice2note's realpath() vault-match assertion holds.
VAULT_REAL="$(cd "$VAULT_DIR" && pwd -P)"
echo "Temp root:   $TROOT"
echo "Temp vault:  $VAULT_REAL"

# One config.json serves BOTH readers: voice2note reads it via Path.home(); the
# cricknote CLI honors CRICKNOTE_DATA_DIR (= $HOME/.cricknote, same file).
printf '{"vaultPath": %s}\n' "$($PY -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$VAULT_REAL")" \
    > "$CRICKNOTE_DATA_DIR/config.json"

# Isolate config loading: an empty real file so the repo's voice2note.env is never read.
CONFIG_FILE="$TROOT/empty.env"
: > "$CONFIG_FILE"

export CRICKNOTE_DATA_DIR
export VOICE2NOTE_CONFIG="$CONFIG_FILE"
export VOICE2NOTE_USE_CRICKNOTE=true
export VOICE2NOTE_CRICKNOTE_BIN="$CRICKNOTE_BIN"
export VOICE2NOTE_MEMO_RELDIR="Memory/voiceMemo"
export VOICE2NOTE_VAULT="$VAULT_REAL"
export VOICE2NOTE_RECORDINGS="$RECORDINGS_DIR"
export VOICE2NOTE_STATE="$STATE_PATH"
export VOICE2NOTE_LOG="$LOG_PATH"
export VOICE2NOTE_LOCK="$LOCK_PATH"
# A model path that need not exist (whisper is stubbed and ignores it).
export VOICE2NOTE_MODEL="$TROOT/fake-model.bin"
export VOICE2NOTE_LANGUAGE="en"

# ---------------------------------------------------------------------------
# Assert BEFORE --once that BOTH readers resolve the SAME vault.
# ---------------------------------------------------------------------------
# (a) voice2note's config.cricknote_vault_path() realpath-equals the temp vault.
V2N_VAULT="$(PYTHONPATH="$PROJECT_DIR" $PY -c \
    'import os; from voice2note import config; print(os.path.realpath(config.cricknote_vault_path()))')"
[ "$V2N_VAULT" = "$VAULT_REAL" ] \
    || fail "voice2note cricknote_vault_path ($V2N_VAULT) != temp vault ($VAULT_REAL)"
echo "voice2note resolves vault: $V2N_VAULT"

# (b) The cricknote CLI is configured for that same vault. `reindex` prints the
# vault path it is operating on; assert it is our temp vault (proves the CLI is
# reading our temp config, not the real ~/.cricknote).
REINDEX_OUT="$($CRICKNOTE_BIN reindex 2>&1)" || fail "cricknote reindex failed:\n$REINDEX_OUT"
echo "$REINDEX_OUT" | grep -qF "$VAULT_REAL" \
    || fail "cricknote reindex not operating on temp vault. Output:\n$REINDEX_OUT"
echo "cricknote configured for temp vault (confirmed via reindex)."

# ---------------------------------------------------------------------------
# 5.2 — Seed one non-empty fake .m4a (no .icloud placeholder).
# ---------------------------------------------------------------------------
M4A_NAME="smoke-memo.m4a"
M4A_PATH="$RECORDINGS_DIR/$M4A_NAME"
printf 'fake-audio-bytes-not-real\n' > "$M4A_PATH"
[ -s "$M4A_PATH" ] || fail "seeded .m4a is empty"

# ---------------------------------------------------------------------------
# 5.2 — Stub ONLY ffmpeg / whisper / codex. Force-selected via absolute paths.
# ---------------------------------------------------------------------------
# ffmpeg: WAV output is the LAST argument; create it (non-empty) and exit 0.
cat > "$STUB_DIR/ffmpeg" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
out=""
for a in "$@"; do out="$a"; done   # last arg = wav output
printf 'RIFFfake-wav' > "$out"
exit 0
STUB

# whisper-cli: write transcript to <value-after -of>.txt (whisper.cpp adds .txt).
cat > "$STUB_DIR/whisper-cli" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
of=""
prev=""
for a in "$@"; do
    if [ "$prev" = "-of" ]; then of="$a"; fi
    prev="$a"
done
[ -n "$of" ] || { echo "whisper stub: no -of argument" >&2; exit 2; }
printf 'This is a deterministic smoke-test transcript for the integration seam.\n' > "${of}.txt"
exit 0
STUB

# codex: write valid analysis JSON to <value-after -o>; record type, confidence 0.9.
cat > "$STUB_DIR/codex" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
out=""
prev=""
for a in "$@"; do
    if [ "$prev" = "-o" ]; then out="$a"; fi
    prev="$a"
done
[ -n "$out" ] || { echo "codex stub: no -o argument" >&2; exit 2; }
cat > "$out" <<'JSON'
{
  "summary": "A deterministic smoke-test memo dictated for the integration seam.",
  "action_items": ["Verify the draft reaches CrickNote's indexed inbox."],
  "topics": ["integration", "smoke-test"],
  "notable_details": ["This analysis came from a local stub, not the real model."],
  "recording_type": "record",
  "confidence": 0.9
}
JSON
exit 0
STUB

chmod +x "$STUB_DIR/ffmpeg" "$STUB_DIR/whisper-cli" "$STUB_DIR/codex"
export VOICE2NOTE_FFMPEG="$STUB_DIR/ffmpeg"
export VOICE2NOTE_WHISPER_CLI="$STUB_DIR/whisper-cli"
export VOICE2NOTE_CODEX="$STUB_DIR/codex"
# Deliberately do NOT stub cricknote — VOICE2NOTE_CRICKNOTE_BIN is the real CLI.

# ---------------------------------------------------------------------------
# 5.3 — Run the REAL entry point.
# ---------------------------------------------------------------------------
echo "=== voice2note run --once (#1) ==="
( cd "$PROJECT_DIR" && PYTHONPATH="$PROJECT_DIR" $PY -m voice2note.run --once ) \
    || fail "voice2note run --once (#1) exited nonzero"

# Compute expected source hash = sha256(<m4a filename>)[:16].
SRC_HASH="$($PY -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])' "$M4A_NAME")"
echo "Expected source hash: $SRC_HASH"

MEMO_GLOB_DIR="$VAULT_REAL/Memory/voiceMemo"

# Assert EXACTLY ONE markdown note exists.
count_notes() {
    find "$MEMO_GLOB_DIR" -maxdepth 1 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' '
}
N="$(count_notes)"
[ "$N" = "1" ] || fail "expected exactly 1 note under $MEMO_GLOB_DIR, found $N"

NOTE_PATH="$(find "$MEMO_GLOB_DIR" -maxdepth 1 -type f -name '*.md')"
NOTE_BASE="$(basename "$NOTE_PATH")"
NOTE_REL="Memory/voiceMemo/$NOTE_BASE"
echo "Note: $NOTE_REL"

# Filename must contain the 16-hex source hash.
case "$NOTE_BASE" in
    *"$SRC_HASH"*) : ;;
    *) fail "note filename $NOTE_BASE does not contain source hash $SRC_HASH" ;;
esac

# Frontmatter must contain the expected scalars. Parse via the engine's own reader
# (vault_writer.read_frontmatter) so we test exactly what voice2note would read.
PYTHONPATH="$PROJECT_DIR" $PY - "$VAULT_REAL" "$NOTE_REL" "$M4A_NAME" <<'PYEOF'
import sys
from voice2note.vault_writer import read_frontmatter
vault, rel, m4a = sys.argv[1], sys.argv[2], sys.argv[3]
fm = read_frontmatter(vault, rel)
exp = {"source_id": m4a, "recording_type": "record", "analysis": "complete", "status": "draft"}
for k, v in exp.items():
    got = fm.get(k)
    if got != v:
        sys.exit(f"frontmatter {k}={got!r}, expected {v!r}")
print("Frontmatter OK:", {k: fm.get(k) for k in exp})
PYEOF
[ $? -eq 0 ] || fail "frontmatter assertions failed"

# state.json must record the memo id (the .m4a filename).
[ -f "$STATE_PATH" ] || fail "state.json not written"
PYTHONPATH="$PROJECT_DIR" $PY - "$STATE_PATH" "$M4A_NAME" <<'PYEOF'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
mid = sys.argv[2]
if mid not in state.get("memos", {}):
    sys.exit(f"state.json memos missing {mid!r}; keys={list(state.get('memos', {}))}")
print("state.json records memo:", mid)
PYEOF
[ $? -eq 0 ] || fail "state.json assertion failed"

# ---------------------------------------------------------------------------
# 5.3 — Reindex with the REAL CLI, then vault_list and verify the draft is indexed.
# ---------------------------------------------------------------------------
echo "=== cricknote reindex (post-write) ==="
$CRICKNOTE_BIN reindex 2>&1 | sed 's/^/  /'

echo "=== cricknote vault_list (draft inbox) ==="
LIST_FILE="$TROOT/vault_list.json"
$CRICKNOTE_BIN tool vault_list '{"folder":"Memory/voiceMemo","status":"draft"}' > "$LIST_FILE" 2>"$TROOT/vault_list.err" \
    || { cat "$TROOT/vault_list.err" >&2; fail "cricknote vault_list exited nonzero"; }

# Parse the ENVELOPE {"ok": true, "result": [...]}; fail closed if ok != true,
# then search result[] for the created note by relpath or basename.
PYTHONPATH="$PROJECT_DIR" $PY - "$LIST_FILE" "$NOTE_REL" "$NOTE_BASE" <<'PYEOF'
import json, os, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
rel, base = sys.argv[2], sys.argv[3]
if not isinstance(data, dict):
    sys.exit(f"vault_list output is not an envelope object: {type(data).__name__}")
if data.get("ok") is not True:
    sys.exit(f"vault_list envelope ok is not true: {data.get('ok')!r}")
result = data.get("result")
if not isinstance(result, list):
    sys.exit(f"vault_list result is not a list: {type(result).__name__}")
for entry in result:
    p = entry.get("path", "")
    if p == rel or os.path.basename(p) == base:
        print("vault_list contains the draft:", p, "status:", entry.get("status"))
        break
else:
    sys.exit(f"created note {rel!r} not found in vault_list result ({len(result)} entries)")
PYEOF
[ $? -eq 0 ] || fail "vault_list did not contain the indexed draft"

# ---------------------------------------------------------------------------
# 5.3 — Run --once AGAIN: must remain idempotent (exactly one note).
# With state.json intact this exercises the state `is_seen` short-circuit.
# ---------------------------------------------------------------------------
echo "=== voice2note run --once (#2, idempotency via state) ==="
( cd "$PROJECT_DIR" && PYTHONPATH="$PROJECT_DIR" $PY -m voice2note.run --once ) \
    || fail "voice2note run --once (#2) exited nonzero"

N2="$(count_notes)"
[ "$N2" = "1" ] || fail "after second run expected exactly 1 note, found $N2 (not idempotent)"
NOTE_PATH2="$(find "$MEMO_GLOB_DIR" -maxdepth 1 -type f -name '*.md')"
[ "$NOTE_PATH2" = "$NOTE_PATH" ] || fail "second run changed the note path ($NOTE_PATH -> $NOTE_PATH2)"
echo "Idempotent (state short-circuit): still exactly one note ($NOTE_BASE)."

# ---------------------------------------------------------------------------
# 5.3 — Run --once a THIRD time with state.json removed: the note exists in the
# vault but not in state, so this drives the create-once ADOPT branch
# (note_exists → verify source_id → state.record, never overwrite).
# ---------------------------------------------------------------------------
echo "=== voice2note run --once (#3, create-once adopt path) ==="
rm -f "$STATE_PATH"
( cd "$PROJECT_DIR" && PYTHONPATH="$PROJECT_DIR" $PY -m voice2note.run --once ) \
    || fail "voice2note run --once (#3, adopt) exited nonzero"

N3="$(count_notes)"
[ "$N3" = "1" ] || fail "after adopt run expected exactly 1 note, found $N3 (adopt overwrote/duplicated)"
NOTE_PATH3="$(find "$MEMO_GLOB_DIR" -maxdepth 1 -type f -name '*.md')"
[ "$NOTE_PATH3" = "$NOTE_PATH" ] || fail "adopt run changed the note path ($NOTE_PATH -> $NOTE_PATH3)"
# State must have been re-recorded by the adopt branch.
PYTHONPATH="$PROJECT_DIR" $PY - "$STATE_PATH" "$M4A_NAME" <<'PYEOF'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
if sys.argv[2] not in state.get("memos", {}):
    sys.exit("adopt branch did not re-record memo in state.json")
print("adopt branch re-recorded memo in state.json:", sys.argv[2])
PYEOF
[ $? -eq 0 ] || fail "adopt-path state assertion failed"
echo "Idempotent (create-once adopt): still exactly one note ($NOTE_BASE)."

# ---------------------------------------------------------------------------
# Done. Single clear PASS line. Trap removes the temp root.
# ---------------------------------------------------------------------------
echo "PASS: voice2note -> cricknote integration smoke (real process + real CLI; draft indexed; idempotent)."
SMOKE_RC=0
