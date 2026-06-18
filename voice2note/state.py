"""Tracks which memos have been handled (write-once), keyed by source_id.
Saved atomically so a crash mid-write can't corrupt the file."""
import json
import os
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
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps({"memos": self.memos, "last_run": self.last_run}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
