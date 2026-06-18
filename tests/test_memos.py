import sqlite3, tempfile, unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from voice2note import memos
from voice2note.state import State


class TestMemos(unittest.TestCase):
    def _make_db(self, tmp):
        db = Path(tmp) / "CloudRecordings.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE ZCLOUDRECORDING "
            "(ZPATH TEXT, ZDATE REAL, ZCUSTOMLABEL TEXT, ZENCRYPTEDTITLE TEXT)"
        )
        # ZDATE is CFAbsoluteTime: 2026-06-15 14:32:00 local -> seconds since 2001.
        con.execute(
            "INSERT INTO ZCLOUDRECORDING VALUES (?, ?, ?, ?)",
            ("rec1.m4a", 771705120.0, "My Title", None),
        )
        con.commit()
        con.close()
        return db

    def test_load_db_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = self._make_db(tmp)
            meta = memos.load_db_metadata(db)
            self.assertIn("rec1.m4a", meta)
            title, when = meta["rec1.m4a"]
            self.assertEqual(title, "My Title")
            self.assertIsInstance(when, datetime)

    def test_load_db_metadata_missing_file(self):
        self.assertEqual(memos.load_db_metadata(Path("/no/such.db")), {})

    def test_find_new_memos_skips_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = Path(tmp)
            (rec / "rec1.m4a").write_bytes(b"x")
            (rec / "rec2.m4a").write_bytes(b"x")
            state = State(rec / "state.json")
            state.record("rec1.m4a", "x", "complete", "record")
            found = memos.find_new_memos(rec, rec / "missing.db", state)
            self.assertEqual([m.id for m in found], ["rec2.m4a"])

    def test_materialize_present_file_returns_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "rec.m4a"
            f.write_bytes(b"data")
            runner = Mock()
            self.assertTrue(memos.materialize(f, runner=runner))
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
