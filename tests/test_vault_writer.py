# tests/test_vault_writer.py
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from voice2note.vault_writer import (build_write_cmd, write_note, note_exists,
                                     read_frontmatter)


class TestBuildCmd(unittest.TestCase):
    def test_argv_and_json(self):
        cmd = build_write_cmd("cricknote", "Memory/voiceMemo/x.md", "body\nlines")
        self.assertEqual(cmd[:3], ["cricknote", "tool", "vault_write"])
        payload = json.loads(cmd[3])
        self.assertEqual(payload, {"path": "Memory/voiceMemo/x.md", "content": "body\nlines"})


class TestWriteNote(unittest.TestCase):
    def test_raises_on_nonzero(self):
        def runner(cmd, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with self.assertRaises(RuntimeError):
            write_note("cricknote", "Memory/voiceMemo/x.md", "c", runner=runner)

    def test_returns_stdout_on_success(self):
        def runner(cmd, **kw):
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        self.assertEqual(write_note("cricknote", "p", "c", runner=runner), "ok")


class TestFsHelpers(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())

    def test_note_exists(self):
        rel = "Memory/voiceMemo/x.md"
        self.assertFalse(note_exists(self.vault, rel))
        (self.vault / "Memory/voiceMemo").mkdir(parents=True)
        (self.vault / rel).write_text("---\nsource_id: \"a.m4a\"\n---\n", encoding="utf-8")
        self.assertTrue(note_exists(self.vault, rel))

    def test_read_frontmatter_source_id(self):
        rel = "Memory/voiceMemo/x.md"
        (self.vault / "Memory/voiceMemo").mkdir(parents=True)
        (self.vault / rel).write_text(
            "---\nsource_id: \"a.m4a\"\nanalysis: pending\nrecording_type: record\n---\nbody",
            encoding="utf-8")
        fm = read_frontmatter(self.vault, rel)
        self.assertEqual(fm["source_id"], "a.m4a")
        self.assertEqual(fm["analysis"], "pending")
        self.assertEqual(fm["recording_type"], "record")


class TestRoundTrip(unittest.TestCase):
    def test_source_id_with_quote_roundtrips(self):
        from datetime import datetime
        from voice2note.notes import render_memo_note
        m = SimpleNamespace(id='A"B\\C.m4a', title="t",
                            recorded_at=datetime(2026, 6, 18, 14, 32))
        analysis = {"summary": "s", "action_items": [], "topics": [],
                    "notable_details": []}
        content = render_memo_note(m, analysis, "x", recording_type="record",
                                   confidence=0.0, status="draft",
                                   analysis_status="pending", include_todos=False)
        vault = Path(tempfile.mkdtemp())
        (vault / "Memory" / "voiceMemo").mkdir(parents=True)
        rel = "Memory/voiceMemo/note.md"
        (vault / rel).write_text(content, encoding="utf-8")
        self.assertEqual(read_frontmatter(vault, rel)["source_id"], 'A"B\\C.m4a')


if __name__ == "__main__":
    unittest.main()
