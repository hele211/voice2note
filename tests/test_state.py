import tempfile, unittest
from pathlib import Path
from voice2note.state import State


class TestState(unittest.TestCase):
    def test_roundtrip_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "state.json"
            s = State(p)
            self.assertFalse(s.is_processed("a.m4a"))
            s.mark_processed("a.m4a")
            s.save(last_run="2026-06-15T10:00:00")
            # reload from disk
            s2 = State(p)
            self.assertTrue(s2.is_processed("a.m4a"))
            self.assertFalse(s2.is_processed("b.m4a"))
            self.assertEqual(s2.last_run, "2026-06-15T10:00:00")

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = State(Path(tmp) / "nope.json")
            self.assertFalse(s.is_processed("x"))
            self.assertIsNone(s.last_run)


if __name__ == "__main__":
    unittest.main()
