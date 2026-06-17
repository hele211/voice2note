"""Tracks which memos have been processed, so reruns never duplicate work."""
import json
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
        self.path.write_text(
            json.dumps(
                {"processed_ids": sorted(self.processed_ids), "last_run": self.last_run},
                indent=2,
            ),
            encoding="utf-8",
        )
