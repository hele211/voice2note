"""Tracks which memos have been handled (write-once), keyed by source_id.
Saved atomically so a crash mid-write can't corrupt the file."""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.memos = {}
        self.last_run = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data.get("memos"), dict):
                self.memos = data["memos"]
            elif isinstance(data.get("processed_ids"), list):  # migrate v1
                self.memos = {mid: {"analysis": "complete"} for mid in data["processed_ids"]}
            self.last_run = data.get("last_run")

    def is_seen(self, source_id):
        return source_id in self.memos

    def record(self, source_id, note_rel, analysis, recording_type):
        self.memos[source_id] = {
            "note_rel": note_rel,
            "analysis": analysis,
            "recording_type": recording_type,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }

    def save(self, last_run=None):
        if last_run is not None:
            self.last_run = last_run
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Unique temp name in the same dir (same filesystem → os.replace is atomic);
        # clean up on any failure so a crashed save never orphans a .tmp file.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"memos": self.memos, "last_run": self.last_run}, fh, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
