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


if __name__ == "__main__":
    unittest.main()
