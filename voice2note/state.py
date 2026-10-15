"""Tracks which memos have been processed, so reruns never duplicate work."""
import fcntl
import json
import os
import tempfile
from pathlib import Path


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.processed_ids = set()
        self.last_run = None
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.processed_ids = set(data.get("processed_ids", []))
            self.last_run = data.get("last_run")

    def is_processed(self, memo_id):
        return memo_id in self.processed_ids

    def mark_processed(self, memo_id):
        self.processed_ids.add(memo_id)

    def save(self, last_run=None):
        if last_run is not None:
            self.last_run = last_run
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.parent / f".{self.path.name}.lock"
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # A second local process may have completed another memo since this
                # State was loaded. Preserve its IDs rather than overwriting them.
                if self.path.exists():
                    disk_data = json.loads(self.path.read_text(encoding="utf-8"))
                    self.processed_ids.update(disk_data.get("processed_ids", []))
                payload = json.dumps(
                    {"processed_ids": sorted(self.processed_ids), "last_run": self.last_run},
                    indent=2,
                ) + "\n"
                fd, temporary_name = tempfile.mkstemp(
                    prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(payload)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(temporary_name, self.path)
                except Exception:
                    try:
                        os.unlink(temporary_name)
                    except FileNotFoundError:
                        pass
                    raise
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
