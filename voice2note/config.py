"""Central configuration for voice2note.

Settings come from environment variables, optionally pre-loaded from a
`voice2note.env` file in the project root (or the file named by
$VOICE2NOTE_CONFIG). The only required setting is VOICE2NOTE_VAULT — the path to
your Obsidian vault (or wherever notes should be written).
"""
import json
import os
import shutil
from pathlib import Path, PurePosixPath

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _load_env_file():
    candidates = []
    if os.environ.get("VOICE2NOTE_CONFIG"):
        candidates.append(Path(os.environ["VOICE2NOTE_CONFIG"]).expanduser())
    candidates.append(PROJECT_DIR / "voice2note.env")
    for path in candidates:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            break


_load_env_file()


def _path(env, default):
    return Path(os.environ.get(env, default) or default).expanduser()


# --- Where notes are written (your Obsidian vault). VOICE2NOTE_VAULT is required. ---
VAULT = _path("VOICE2NOTE_VAULT", "")

# --- Engine state/logs (kept inside the project by default). ---
STATE_PATH = _path("VOICE2NOTE_STATE", str(PROJECT_DIR / "state.json"))
LOG_PATH = _path("VOICE2NOTE_LOG", str(PROJECT_DIR / "logs" / "run.log"))

# --- macOS Voice Memos source (TCC-protected; needs Full Disk Access). ---
RECORDINGS_DIR = _path(
    "VOICE2NOTE_RECORDINGS",
    str(Path.home() / "Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"),
)
DB_PATH = RECORDINGS_DIR / "CloudRecordings.db"

# --- Transcription via whisper.cpp (local, offline). ---
WHISPER_CLI_BIN = os.environ.get("VOICE2NOTE_WHISPER_CLI") or shutil.which("whisper-cli") or "whisper-cli"
FFMPEG_BIN = os.environ.get("VOICE2NOTE_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
WHISPER_MODEL_PATH = _path("VOICE2NOTE_MODEL", str(PROJECT_DIR / "models" / "ggml-small.bin"))
WHISPER_LANGUAGE = os.environ.get("VOICE2NOTE_LANGUAGE", "auto")  # 'auto', 'en', 'zh', ...

# --- Analysis via the Codex CLI (`codex exec`), using your Codex/ChatGPT login. ---
CODEX_BIN = os.environ.get("VOICE2NOTE_CODEX") or shutil.which("codex") or "codex"
CODEX_MODEL = os.environ.get("VOICE2NOTE_CODEX_MODEL", "gpt-5.5")

# --- iCloud download helper. ---
BRCTL_BIN = os.environ.get("VOICE2NOTE_BRCTL") or shutil.which("brctl") or "/usr/bin/brctl"


def env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# --- Optional, explicitly-triggered macOS Apple app automation. ---
# Disabled by default so upgrading voice2note never creates external items until
# the owner enables it in voice2note.env.  The phrase "CrickNote please" is a
# second gate before either app is contacted.
APPLE_AUTOMATION_ENABLED = env_bool("VOICE2NOTE_APPLE_AUTOMATION", False)
APPLE_REMINDERS_LIST = os.environ.get("VOICE2NOTE_APPLE_REMINDERS_LIST", "").strip()
APPLE_CALENDAR = os.environ.get("VOICE2NOTE_APPLE_CALENDAR", "").strip()
OSASCRIPT_BIN = os.environ.get("VOICE2NOTE_OSASCRIPT", "/usr/bin/osascript")


def validate_memo_reldir(reldir):
    p = PurePosixPath(reldir)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"VOICE2NOTE_MEMO_RELDIR must be relative without '..': {reldir!r}")
    return str(p)


def cricknote_vault_path():
    """Read vaultPath from ~/.cricknote/config.json (raises if absent/malformed)."""
    cfg = Path.home() / ".cricknote" / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    return data["vaultPath"]


def assert_vault_match(v2n_vault, cricknote_vault):
    if os.path.realpath(v2n_vault) != os.path.realpath(cricknote_vault):
        raise SystemExit(
            "VOICE2NOTE_VAULT does not match ~/.cricknote/config.json vaultPath:\n"
            f"  voice2note: {v2n_vault}\n  cricknote:  {cricknote_vault}\n"
            "Point both at the same vault, or set VOICE2NOTE_USE_CRICKNOTE=false.")


USE_CRICKNOTE = env_bool("VOICE2NOTE_USE_CRICKNOTE", False)
CRICKNOTE_BIN = os.environ.get("VOICE2NOTE_CRICKNOTE_BIN") or shutil.which("cricknote") or "cricknote"
MEMO_RELDIR = validate_memo_reldir(os.environ.get("VOICE2NOTE_MEMO_RELDIR", "Memory/voiceMemo"))
CONFIDENCE_MIN = float(os.environ.get("VOICE2NOTE_CONFIDENCE_MIN", "0.5"))
LOCK_PATH = _path("VOICE2NOTE_LOCK", str(PROJECT_DIR / "voice2note.lock"))
