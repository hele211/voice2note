"""Central configuration for voice2note.

Settings come from environment variables, optionally pre-loaded from a
`voice2note.env` file in the project root (or the file named by
$VOICE2NOTE_CONFIG). The only required setting is VOICE2NOTE_VAULT — the path to
your Obsidian vault (or wherever notes should be written).
"""
import os
import shutil
from pathlib import Path

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
DAILY_DIR = _path("VOICE2NOTE_DAILY_DIR", str(VAULT / "00_Journal" / "Daily"))
MEMO_DIR = _path("VOICE2NOTE_MEMO_DIR", str(VAULT / "00_Journal" / "VoiceMemos"))

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
