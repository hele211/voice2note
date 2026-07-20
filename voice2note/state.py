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
        # An Apple item can be written before its vault note.  Such entries are
        # deliberately retried for the note write, but must not create the Apple
        # item a second time.  Old/migrated entries remain seen as before.
        return source_id in self.memos and not self.memos[source_id].get("automation_pending")

    def record(self, source_id, note_rel, analysis, recording_type):
        entry = dict(self.memos.get(source_id, {}))
        entry.update({
            "note_rel": note_rel,
            "analysis": analysis,
            "recording_type": recording_type,
            "updated": datetime.now().isoformat(timespec="seconds"),
        })
        entry.pop("automation_pending", None)
        self.memos[source_id] = entry

    def automation_for(self, source_id):
        """Return a previously-created Apple item, if this memo has one."""
        item = self.memos.get(source_id, {}).get("apple_item")
        return dict(item) if isinstance(item, dict) else None

    def record_automation(self, source_id, item):
        """Persist an external Apple-item creation before writing the note.

        This is the durable half of the retry protocol: after a later vault
        write failure, the next run sees this record and skips the external
        creation call.
        """
        entry = dict(self.memos.get(source_id, {}))
        entry["apple_item"] = dict(item)
        entry["automation_pending"] = True
        entry["updated"] = datetime.now().isoformat(timespec="seconds")
        self.memos[source_id] = entry

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
