# tests/test_notes.py
import unittest
from datetime import datetime
from types import SimpleNamespace

from voice2note.notes import source_hash, memo_note_relpath, render_memo_note


def memo(title="Lysis ideas", mid="ABCD-1234.m4a"):
    return SimpleNamespace(id=mid, title=title,
                           recorded_at=datetime(2026, 6, 18, 14, 32))


ANALYSIS = {"summary": "Did the lysis.", "action_items": ["order ECL"],
            "topics": ["western-blot"], "notable_details": ["pH 7.4"],
            "recording_type": "record", "confidence": 0.9}


class TestPath(unittest.TestCase):
    def test_hash_is_16_hex_and_stable(self):
        h = source_hash("ABCD-1234.m4a")
        self.assertEqual(len(h), 16)
        self.assertEqual(h, source_hash("ABCD-1234.m4a"))

    def test_relpath_shape(self):
        p = memo_note_relpath("Memory/voiceMemo", memo().recorded_at,
                              "Lysis ideas", "ABCD-1234.m4a")
        self.assertTrue(p.startswith("Memory/voiceMemo/2026-06-18-1432-lysis-ideas-"))
        self.assertTrue(p.endswith(".md"))

    def test_same_minute_title_different_id_no_collision(self):
        a = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "X", "a.m4a")
        b = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "X", "b.m4a")
        self.assertNotEqual(a, b)


class TestRender(unittest.TestCase):
    def test_record_has_frontmatter_and_no_checkboxes(self):
        out = render_memo_note(memo(), ANALYSIS, "raw transcript",
                               recording_type="record", confidence=0.9,
                               status="draft", analysis_status="complete",
                               include_todos=True)
        self.assertIn("recording_type: record", out)
        self.assertIn("status: draft", out)
        self.assertIn("analysis: complete", out)
        self.assertIn('source_id: "ABCD-1234.m4a"', out)
        self.assertNotIn("- [ ]", out)
        self.assertIn("## Possible to-dos", out)
        self.assertIn("- order ECL", out)
        self.assertIn("raw transcript", out)

    def test_conversation_omits_todos(self):
        out = render_memo_note(memo(), ANALYSIS, "t",
                               recording_type="conversation", confidence=0.9,
                               status="complete", analysis_status="complete",
                               include_todos=False)
        self.assertNotIn("## Possible to-dos", out)

    def test_title_with_quote_is_escaped(self):
        out = render_memo_note(memo(title='He said "go"'), ANALYSIS, "t",
                               recording_type="record", confidence=0.9,
                               status="draft", analysis_status="complete",
                               include_todos=True)
        self.assertIn('title: "He said \\"go\\""', out)

    def test_transcript_only_pending(self):
        empty = {"summary": "", "action_items": [], "topics": [],
                 "notable_details": [], "recording_type": "record", "confidence": 0.0}
        out = render_memo_note(memo(), empty, "just the words",
                               recording_type="record", confidence=0.0,
                               status="draft", analysis_status="pending",
                               include_todos=True)
        self.assertIn("analysis: pending", out)
        self.assertIn("just the words", out)

    def test_apple_item_is_visible_in_note(self):
        out = render_memo_note(memo(), ANALYSIS, "t",
                               recording_type="record", confidence=0.9,
                               status="draft", analysis_status="complete",
                               include_todos=True,
                               apple_item={"kind": "reminder", "id": "r1", "title": "Call Mum"})
        self.assertIn("apple_action: reminder", out)
        self.assertIn("## Apple action", out)
        self.assertIn("Created reminder: Call Mum", out)


if __name__ == "__main__":
    unittest.main()
