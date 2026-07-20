import unittest
from types import SimpleNamespace
from voice2note import analyze
from voice2note.analyze import coerce_confidence


class TestAnalyze(unittest.TestCase):
    def test_build_prompt_includes_transcript(self):
        self.assertIn("buy milk", analyze.build_prompt("buy milk"))

    def test_apple_prompt_adds_current_time_only_when_requested(self):
        plain = analyze.build_prompt("buy milk")
        automated = analyze.build_prompt("buy milk", apple_automation_requested=True,
                                         current_time="2026-07-20T09:00+01:00")
        self.assertNotIn('"apple_action"', plain)
        self.assertIn('"apple_action"', automated)
        self.assertIn("2026-07-20T09:00+01:00", automated)

    def test_parse_analysis_with_code_fence(self):
        text = '```json\n{"summary":"s","action_items":["a"],"topics":["t"],"notable_details":["n"]}\n```'
        out = analyze.parse_analysis(text)
        self.assertEqual(out["summary"], "s")
        self.assertEqual(out["action_items"], ["a"])
        self.assertEqual(out["topics"], ["t"])
        self.assertEqual(out["notable_details"], ["n"])

    def test_parse_analysis_missing_keys_default_empty(self):
        out = analyze.parse_analysis('{"summary":"only"}')
        self.assertEqual(out["summary"], "only")
        self.assertEqual(out["action_items"], [])
        self.assertEqual(out["apple_action"]["kind"], "none")

    def test_parse_analysis_extracts_apple_action(self):
        out = analyze.parse_analysis(
            '{"summary":"s", "apple_action":{"kind":"calendar",'
            '"title":"Team meeting", "start_at":"2026-07-21T10:00"}}')
        self.assertEqual(out["apple_action"]["kind"], "calendar")
        self.assertEqual(out["apple_action"]["title"], "Team meeting")

    def test_parse_analysis_no_json_raises(self):
        with self.assertRaises(ValueError):
            analyze.parse_analysis("no json here")

    def test_build_codex_cmd(self):
        cmd = analyze.build_codex_cmd("PROMPT", "/tmp/o.json", "codex", "gpt-5.5")
        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("-o", cmd)
        self.assertIn("/tmp/o.json", cmd)
        self.assertIn("gpt-5.5", cmd)
        self.assertIn("model_reasoning_effort=low", cmd)
        self.assertEqual(cmd[-1], "PROMPT")

    def test_analyze_reads_codex_output_file(self):
        def fake_runner(cmd, capture_output=True, text=True, timeout=None, **kwargs):
            out = cmd[cmd.index("-o") + 1]
            with open(out, "w", encoding="utf-8") as fh:
                fh.write('{"summary":"s","action_items":["a"],"topics":["t"],"notable_details":[]}')
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        out = analyze.analyze("hi", runner=fake_runner)
        self.assertEqual(out["summary"], "s")
        self.assertEqual(out["action_items"], ["a"])

    def test_analyze_nonzero_exit_raises(self):
        def fake_runner(cmd, capture_output=True, text=True, timeout=None, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        with self.assertRaises(RuntimeError):
            analyze.analyze("hi", runner=fake_runner)


class TestRecordingType(unittest.TestCase):
    def _parse(self, **extra):
        import json
        from voice2note.analyze import parse_analysis
        payload = {"summary": "s", "action_items": [], "topics": [],
                   "notable_details": []}
        payload.update(extra)
        return parse_analysis(json.dumps(payload))

    def test_extracts_recording_type(self):
        self.assertEqual(self._parse(recording_type="talk")["recording_type"], "talk")

    def test_missing_type_defaults_record(self):
        self.assertEqual(self._parse()["recording_type"], "record")

    def test_invalid_type_defaults_record(self):
        self.assertEqual(self._parse(recording_type="podcast")["recording_type"], "record")

    def test_confidence_extracted(self):
        self.assertEqual(self._parse(confidence=0.8)["confidence"], 0.8)

    def test_confidence_clamped_end_to_end(self):
        self.assertEqual(self._parse(confidence=1.5)["confidence"], 1.0)


class TestCoerceConfidence(unittest.TestCase):
    def test_numeric_string(self):
        self.assertEqual(coerce_confidence("0.8"), 0.8)

    def test_garbage_defaults_zero(self):
        self.assertEqual(coerce_confidence("high"), 0.0)

    def test_missing_defaults_zero(self):
        self.assertEqual(coerce_confidence(None), 0.0)

    def test_clamps_high(self):
        self.assertEqual(coerce_confidence(1.5), 1.0)

    def test_clamps_low(self):
        self.assertEqual(coerce_confidence(-2), 0.0)


if __name__ == "__main__":
    unittest.main()
