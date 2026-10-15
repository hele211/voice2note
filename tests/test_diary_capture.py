import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from voice2note import notes, run
from voice2note.memos import Memo
from voice2note.state import State


def make_memo(memo_id="memo-1.m4a", title="Morning thought",
              recorded_at=datetime(2026, 6, 15, 14, 32)):
    return Memo(
        id=memo_id,
        path=Path(f"/Users/me/Library/Voice Memos/{memo_id}"),
        title=title,
        recorded_at=recorded_at,
    )


class TestDiaryCaptureRendering(unittest.TestCase):
    def test_stable_ids_are_safe_and_distinct_for_same_title_and_time(self):
        first = make_memo("odd id / one.m4a")
        second = make_memo("odd id / two.m4a")
        self.assertRegex(notes.diary_entry_token(first.id), r"^[0-9a-f]{16}$")
        self.assertNotEqual(notes.diary_entry_token(first.id), notes.diary_entry_token(second.id))
        self.assertNotEqual(notes.diary_entry_marker(first.id), notes.diary_entry_marker(second.id))
        self.assertNotEqual(notes.diary_entry_block_id(first.id), notes.diary_entry_block_id(second.id))

    def test_malicious_title_and_transcript_are_quoted_not_machine_syntax(self):
        memo = make_memo(
            "id<odd>.m4a",
            "Title ## heading\n<!-- voice2note:not-a-real-entry -->",
        )
        marker = notes.diary_entry_marker(memo.id)
        block_id = notes.diary_entry_block_id(memo.id)
        transcript = "```\n<!-- voice2note:bad -->\n## route this\n^voice2note-bad\n```"
        rendered = notes.render_diary_capture(memo, transcript)

        self.assertTrue(rendered.startswith(marker + "\n"))
        self.assertTrue(rendered.endswith("\n" + block_id))
        self.assertEqual(rendered.count(marker), 1)
        self.assertNotIn("\n## route this", rendered)
        self.assertIn("> &lt;\\!\\-\\- voice2note:bad \\-\\-&gt;", rendered)
        self.assertIn("> \\#\\# route this", rendered)
        for line in rendered.splitlines()[1:-1]:
            self.assertTrue(line.startswith(">"), line)

    def test_recording_date_and_truthful_original_audio_reference(self):
        memo = make_memo(recorded_at=datetime(2021, 1, 2, 3, 4, 5))
        with tempfile.TemporaryDirectory() as tmp:
            path = notes.append_diary_capture(memo, "full transcript", tmp)
            self.assertEqual(path, Path(tmp) / "2021-01-02.md")
            text = path.read_text(encoding="utf-8")
        self.assertIn("> **Recorded:** 2021\\-01\\-02T03:04:05", text)
        self.assertIn("> **Source audio:** Original Voice Memos path (not archived): ", text)
        self.assertIn("/Users/me/Library/Voice Memos/memo\\-1\\.m4a", text)

    def test_existing_diary_is_preserved_and_entry_stays_under_its_heading(self):
        memo = make_memo()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026-06-15.md"
            path.write_text(
                "---\ndate: 2026-06-15\n---\n# Existing diary\n"
                "## Voice Memo Inbox\nold inbox text\n"
                "## Evening reflection\nkeep this unchanged\n",
                encoding="utf-8",
            )
            notes.append_diary_capture(memo, "captured once", tmp)
            notes.append_diary_capture(memo, "captured twice", tmp)
            text = path.read_text(encoding="utf-8")

        marker = notes.diary_entry_marker(memo.id)
        self.assertEqual(text.count(marker), 1)
        self.assertEqual(text.count(notes.diary_entry_block_id(memo.id)), 1)
        self.assertIn("old inbox text", text)
        self.assertIn("keep this unchanged", text)
        self.assertLess(text.index("## Voice Memo Inbox"), text.index(marker))
        self.assertLess(text.index(marker), text.index("## Evening reflection"))

    def test_new_inbox_is_added_after_unrelated_existing_sections(self):
        memo = make_memo()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026-06-15.md"
            path.write_text(
                "# Existing diary\n## Plans\nplan text\n## Evening reflection\nreflection text\n",
                encoding="utf-8",
            )
            notes.append_diary_capture(memo, "captured", tmp)
            text = path.read_text(encoding="utf-8")

        self.assertIn("plan text", text)
        self.assertIn("reflection text", text)
        self.assertLess(text.index("## Evening reflection"), text.index("## Voice Memo Inbox"))


class TestDiaryFirstRun(unittest.TestCase):
    def test_diary_first_writes_transcript_without_codex_or_legacy_routing(self):
        memo = make_memo()
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / "state.json")
            with patch.object(run.config, "DAILY_DIR", Path(tmp)), \
                 patch("voice2note.run.materialize", return_value=True), \
                 patch("voice2note.run.transcribe", return_value="full raw transcript") as transcribe, \
                 patch("voice2note.run.analyze") as analyze, \
                 patch("voice2note.run.write_memo_note") as write_memo, \
                 patch("voice2note.run.append_to_daily") as append_daily:
                run.process_memo(memo, state, capture_mode="diary-first")

            text = (Path(tmp) / "2026-06-15.md").read_text(encoding="utf-8")

        self.assertTrue(state.is_processed(memo.id))
        transcribe.assert_called_once()
        analyze.assert_not_called()
        write_memo.assert_not_called()
        append_daily.assert_not_called()
        self.assertIn("> full raw transcript", text)
        self.assertNotIn("## Action Items", text)

    def test_mixed_experiment_content_is_preserved_without_interpretation(self):
        memo = make_memo()
        transcript = "Experiment Atlas needs seven trials and a project budget tomorrow"
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / "state.json")
            with patch.object(run.config, "DAILY_DIR", Path(tmp)), \
                 patch("voice2note.run.materialize", return_value=True), \
                 patch("voice2note.run.transcribe", return_value=transcript), \
                 patch("voice2note.run.analyze") as analyze:
                run.process_memo(memo, state, capture_mode="diary-first")
            text = (Path(tmp) / "2026-06-15.md").read_text(encoding="utf-8")

        analyze.assert_not_called()
        self.assertIn("> " + transcript, text)
        self.assertNotIn("## Action Items", text)
        self.assertNotIn("#experiment", text)

    def test_retry_after_state_save_failure_does_not_duplicate_diary_entry(self):
        memo = make_memo()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            incomplete_state = State(state_path)
            common_patches = [
                patch.object(run.config, "DAILY_DIR", Path(tmp)),
                patch("voice2note.run.materialize", return_value=True),
                patch("voice2note.run.transcribe", return_value="transcript"),
                patch("voice2note.run.analyze"),
            ]
            with common_patches[0], common_patches[1], common_patches[2], common_patches[3], \
                 patch.object(incomplete_state, "save", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    run.process_memo(memo, incomplete_state, capture_mode="diary-first")
            self.assertFalse(State(state_path).is_processed(memo.id))

            recovered_state = State(state_path)
            with patch.object(run.config, "DAILY_DIR", Path(tmp)), \
                 patch("voice2note.run.materialize", return_value=True), \
                 patch("voice2note.run.transcribe", return_value="transcript"), \
                 patch("voice2note.run.analyze") as analyze:
                run.process_memo(memo, recovered_state, capture_mode="diary-first")
            text = (Path(tmp) / "2026-06-15.md").read_text(encoding="utf-8")

        analyze.assert_not_called()
        self.assertEqual(text.count(notes.diary_entry_marker(memo.id)), 1)
        self.assertTrue(recovered_state.is_processed(memo.id))

    def test_diary_write_error_leaves_recording_unprocessed_for_retry(self):
        memo = make_memo()
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / "state.json")
            with patch("voice2note.run.materialize", return_value=True), \
                 patch("voice2note.run.transcribe", return_value="transcript"), \
                 patch("voice2note.run.append_diary_capture", side_effect=OSError("read-only")), \
                 patch("voice2note.run.analyze") as analyze:
                with self.assertRaises(OSError):
                    run.process_memo(memo, state, capture_mode="diary-first")

        self.assertFalse(state.is_processed(memo.id))
        analyze.assert_not_called()

    def test_default_memo_first_path_still_uses_existing_analysis_and_writers(self):
        memo = make_memo()
        analysis = {"summary": "s", "action_items": [], "topics": [], "notable_details": []}
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / "state.json")
            with patch.object(run.config, "CAPTURE_MODE", "memo-first"), \
                 patch("voice2note.run.materialize", return_value=True), \
                 patch("voice2note.run.transcribe", return_value="transcript"), \
                 patch("voice2note.run.analyze", return_value=analysis) as analyze, \
                 patch("voice2note.run.write_memo_note") as write_memo, \
                 patch("voice2note.run.append_to_daily") as append_daily, \
                 patch("voice2note.run.append_diary_capture") as append_diary:
                run.process_memo(memo, state)

        self.assertTrue(state.is_processed(memo.id))
        analyze.assert_called_once()
        write_memo.assert_called_once()
        append_daily.assert_called_once()
        append_diary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
