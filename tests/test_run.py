import tempfile, unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from voice2note import run
from voice2note.memos import Memo
from voice2note.state import State


class TestRun(unittest.TestCase):
    @patch("voice2note.run.append_to_daily")
    @patch("voice2note.run.write_memo_note")
    @patch("voice2note.run.analyze", return_value={"summary": "s", "action_items": [],
                                                  "topics": [], "notable_details": []})
    @patch("voice2note.run.transcribe", return_value="hello")
    @patch("voice2note.run.materialize", return_value=True)
    def test_process_memo_marks_processed(self, *_mocks):
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / "state.json")
            memo = Memo(id="a.m4a", path=Path("/x/a.m4a"), title="A",
                        recorded_at=datetime(2026, 6, 15, 14, 32))
            run.process_memo(memo, state)
            self.assertTrue(state.is_processed("a.m4a"))

    @patch("voice2note.run.write_memo_note")
    @patch("voice2note.run.analyze", side_effect=RuntimeError("boom"))
    @patch("voice2note.run.transcribe", return_value="hello")
    @patch("voice2note.run.materialize", return_value=True)
    def test_analysis_failure_leaves_unprocessed(self, *_mocks):
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / "state.json")
            memo = Memo(id="a.m4a", path=Path("/x/a.m4a"), title="A",
                        recorded_at=datetime(2026, 6, 15, 14, 32))
            run.process_memo(memo, state)
            self.assertFalse(state.is_processed("a.m4a"))


class TestRunLock(unittest.TestCase):
    def test_acquire_lock_blocks_second_caller(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "state.lock"
            with patch("voice2note.config.LOCK_PATH", lock_path):
                first = run._acquire_lock()
                try:
                    self.assertIsNotNone(first)
                    self.assertIsNone(run._acquire_lock())
                finally:
                    first.close()
                # released now — a fresh caller can acquire it again
                second = run._acquire_lock()
                self.assertIsNotNone(second)
                second.close()

    @patch("voice2note.run.find_new_memos")
    def test_run_skips_entirely_when_lock_already_held(self, mock_find_new_memos):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with patch("voice2note.config.LOCK_PATH", tmp / "state.lock"), \
                 patch("voice2note.config.VAULT", tmp / "vault"), \
                 patch("voice2note.config.STATE_PATH", tmp / "state.json"):
                held = run._acquire_lock()
                self.assertIsNotNone(held)
                try:
                    run.run()  # a concurrent run — must see the lock held and bail out
                finally:
                    held.close()
        mock_find_new_memos.assert_not_called()


if __name__ == "__main__":
    unittest.main()
