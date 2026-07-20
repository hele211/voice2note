"""Discover new Voice Memos and ensure their audio is downloaded locally."""
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CF_EPOCH_OFFSET = 978307200  # seconds between 1970-01-01 and 2001-01-01


@dataclass
class Memo:
    id: str
    path: Path
    title: str
    recorded_at: datetime


def list_m4a(recordings_dir):
    """List .m4a files. Raises PermissionError if Full Disk Access is missing."""
    names = [n for n in os.listdir(recordings_dir) if n.lower().endswith(".m4a")]
    return sorted(Path(recordings_dir) / n for n in names)


def load_db_metadata(db_path):
    """Best-effort read of titles/dates from CloudRecordings.db. {} on any failure."""
    if not Path(db_path).exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT ZPATH, ZDATE, COALESCE(ZCUSTOMLABEL, ZENCRYPTEDTITLE) "
                "FROM ZCLOUDRECORDING"
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    meta = {}
    for zpath, zdate, title in rows:
        if not zpath:
            continue
        name = Path(zpath).name
        when = datetime.fromtimestamp(zdate + CF_EPOCH_OFFSET) if zdate else None
        meta[name] = (title or Path(zpath).stem, when)
    return meta


def find_new_memos(recordings_dir, db_path, state):
    meta = load_db_metadata(db_path)
    result = []
    for path in list_m4a(recordings_dir):
        if state.is_seen(path.name):
            continue
        title, when = meta.get(path.name, (None, None))
        if when is None:
            when = datetime.fromtimestamp(path.stat().st_mtime)
        if not title:
            title = path.stem
        result.append(Memo(id=path.name, path=path, title=title, recorded_at=when))
    return sorted(result, key=lambda m: m.recorded_at)


def materialize(path, brctl_bin="/usr/bin/brctl", timeout=180,
                runner=subprocess.run, sleeper=time.sleep):
    """Download an iCloud-offloaded file if needed. Returns True if present afterward."""
    path = Path(path)
    placeholder = path.parent / f".{path.name}.icloud"
    if path.exists() and path.stat().st_size > 0 and not placeholder.exists():
        return True
    target = placeholder if placeholder.exists() else path
    runner([brctl_bin, "download", str(target)], capture_output=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return True
        sleeper(2)
    return path.exists() and path.stat().st_size > 0
