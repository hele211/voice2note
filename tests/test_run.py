# tests/test_run.py
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from voice2note import run as runmod
from voice2note.state import State
from voice2note.notes import memo_note_relpath


def make_cfg(vault, use_cricknote=False):
    return SimpleNamespace(
        VAULT=Path(vault), MEMO_RELDIR="Memory/voiceMemo",
        USE_CRICKNOTE=use_cricknote, CRICKNOTE_BIN="cricknote",
        CONFIDENCE_MIN=0.5)


def memo(mid="a.m4a", title="Idea"):
    return SimpleNamespace(id=mid, path=Path("/tmp/a.m4a"), title=title,
                           recorded_at=datetime(2026, 6, 18, 14, 32))


class TestProcessMemo(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()
        self.state = State(Path(tempfile.mkdtemp()) / "state.json")
        self.cfg = make_cfg(self.vault)
        # Stub the heavy steps.
        runmod.materialize = lambda *a, **k: True
        runmod.transcribe = lambda *a, **k: "the transcript"
        runmod.analyze = lambda *a, **k: {
            "summary": "s", "action_items": [], "topics": ["t"],
            "notable_details": [], "recording_type": "record", "confidence": 0.9}

    def test_creates_note_and_records_state(self):
        runmod.process_memo(memo(), self.state, self.cfg)
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        self.assertTrue((Path(self.vault) / rel).exists())
        self.assertTrue(self.state.is_seen("a.m4a"))

    def test_skips_when_seen(self):
        self.state.record("a.m4a", "x", "complete", "record")
        called = {"n": 0}
        runmod.transcribe = lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "t"
        runmod.process_memo(memo(), self.state, self.cfg)
        self.assertEqual(called["n"], 0)

    def test_adopts_existing_matching_note_without_rewrite(self):
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        p = Path(self.vault) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('---\nsource_id: "a.m4a"\nanalysis: complete\n'
                     'recording_type: record\n---\nORIGINAL', encoding="utf-8")
        runmod.transcribe = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run"))
        runmod.process_memo(memo(), self.state, self.cfg)
        self.assertEqual(p.read_text(encoding="utf-8").split("---")[-1].strip(), "ORIGINAL")
        self.assertTrue(self.state.is_seen("a.m4a"))

    def test_adopt_mismatch_raises(self):
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        p = Path(self.vault) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('---\nsource_id: "OTHER.m4a"\n---\nx', encoding="utf-8")
        with self.assertRaises(RuntimeError):
            runmod.process_memo(memo(), self.state, self.cfg)

    def test_analysis_failure_writes_transcript_only_draft(self):
        runmod.analyze = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("codex down"))
        runmod.process_memo(memo(), self.state, self.cfg)
        rel = memo_note_relpath("Memory/voiceMemo", memo().recorded_at, "Idea", "a.m4a")
        out = (Path(self.vault) / rel).read_text(encoding="utf-8")
        self.assertIn("analysis: pending", out)
        self.assertIn("status: draft", out)
        self.assertIn("the transcript", out)


class TestCheckGating(unittest.TestCase):
    def test_standalone_check_does_not_require_cricknote_config(self):
        # USE_CRICKNOTE False → check_access must not raise even if no cricknote config.
        import voice2note.config as config
        orig = config.USE_CRICKNOTE
        config.USE_CRICKNOTE = False
        try:
            self.assertIn(runmod.vault_check_ok(config), (True, False))
        finally:
            config.USE_CRICKNOTE = orig


if __name__ == "__main__":
    unittest.main()
