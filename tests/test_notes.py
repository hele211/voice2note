import unittest
from datetime import datetime
from types import SimpleNamespace
from voice2note import notes

MEMO = SimpleNamespace(
    id="rec1.m4a",
    title="Project ideas: Q3",
    recorded_at=datetime(2026, 6, 15, 14, 32),
)
ANALYSIS = {
    "summary": "Notes about Q3 planning.",
    "action_items": ["Email Sam about budget"],
    "topics": ["planning", "budget"],
    "notable_details": ["Deadline is July 1"],
}


class TestNotes(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(notes.slugify("Project ideas: Q3"), "project-ideas-q3")
        self.assertEqual(notes.slugify(""), "memo")

    def test_memo_filename(self):
        self.assertEqual(
            notes.memo_filename(MEMO.recorded_at, MEMO.title),
            "2026-06-15-1432-project-ideas-q3.md",
        )

    def test_render_memo_note_has_all_sections(self):
        md = notes.render_memo_note(MEMO, ANALYSIS, "hello world")
        self.assertIn("## Summary", md)
        self.assertIn("- [ ] Email Sam about budget 📅 2026-06-15", md)
        self.assertIn("#planning", md)
        self.assertIn("- Deadline is July 1", md)
        self.assertIn("> hello world", md)
        self.assertIn("source: voice-memo", md)

    def test_render_daily_block(self):
        block = notes.render_daily_block(MEMO, ANALYSIS, "2026-06-15-1432-project-ideas-q3")
        self.assertIn("**14:32 — Project ideas: Q3**", block)
        self.assertIn("[[2026-06-15-1432-project-ideas-q3|full note]]", block)
        self.assertIn("  - [ ] Email Sam about budget 📅 2026-06-15", block)


import tempfile
from pathlib import Path


class TestNoteWriting(unittest.TestCase):
    def test_write_memo_note_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = notes.write_memo_note(MEMO, ANALYSIS, "hello", Path(tmp))
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "2026-06-15-1432-project-ideas-q3.md")
            self.assertIn("## Summary", path.read_text(encoding="utf-8"))

    def test_append_to_daily_adds_header_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp)
            notes.append_to_daily(MEMO, ANALYSIS, "note-basename", daily)
            notes.append_to_daily(MEMO, ANALYSIS, "note-basename", daily)
            text = (daily / "2026-06-15.md").read_text(encoding="utf-8")
            self.assertEqual(text.count("## Voice Memos"), 1)
            self.assertEqual(text.count("**14:32 — Project ideas: Q3**"), 2)
            self.assertIn("date: 2026-06-15", text)  # frontmatter created


if __name__ == "__main__":
    unittest.main()
