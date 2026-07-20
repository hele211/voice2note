# tests/test_state.py
import json
import os
import tempfile
import unittest
from pathlib import Path

from voice2note.state import State


class TestState(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = Path(self.dir) / "state.json"

    def test_record_and_is_seen(self):
        s = State(self.path)
        self.assertFalse(s.is_seen("a.m4a"))
        s.record("a.m4a", "Memory/voiceMemo/x.md", "complete", "record")
        self.assertTrue(s.is_seen("a.m4a"))

    def test_migrates_processed_ids(self):
        self.path.write_text(json.dumps({"processed_ids": ["a.m4a", "b.m4a"]}),
                             encoding="utf-8")
        s = State(self.path)
        self.assertTrue(s.is_seen("a.m4a"))
        self.assertEqual(s.memos["a.m4a"]["analysis"], "complete")

    def test_save_roundtrip(self):
        s = State(self.path)
        s.record("a.m4a", "Memory/voiceMemo/x.md", "pending", "record")
        s.save(last_run="2026-06-18T14:00:00")
        again = State(self.path)
        self.assertTrue(again.is_seen("a.m4a"))
        self.assertEqual(again.last_run, "2026-06-18T14:00:00")

    def test_pending_automation_is_retried_for_note_but_item_is_preserved(self):
        s = State(self.path)
        item = {"kind": "reminder", "id": "r-1", "title": "Call Mum"}
        s.record_automation("a.m4a", item)
        s.save()
        again = State(self.path)
        self.assertFalse(again.is_seen("a.m4a"))
        self.assertEqual(again.automation_for("a.m4a"), item)
        again.record("a.m4a", "Memory/voiceMemo/x.md", "complete", "record")
        self.assertTrue(again.is_seen("a.m4a"))
        self.assertEqual(again.automation_for("a.m4a"), item)

    def test_save_is_atomic_on_failure(self):
        self.path.write_text(json.dumps({"memos": {"old.m4a": {"analysis": "complete"}}}),
                             encoding="utf-8")
        s = State(self.path)
        s.record("new.m4a", "Memory/voiceMemo/n.md", "complete", "record")
        real_replace = os.replace

        def boom(src, dst):
            raise OSError("simulated crash during replace")

        os.replace = boom
        try:
            with self.assertRaises(OSError):
                s.save()
        finally:
            os.replace = real_replace
        # Original file must be intact (not truncated/corrupted).
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("old.m4a", data["memos"])
        self.assertNotIn("new.m4a", data["memos"])


if __name__ == "__main__":
    unittest.main()
