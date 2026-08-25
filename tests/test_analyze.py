import subprocess
import unittest
from types import SimpleNamespace
from voice2note import analyze


class TestAnalyze(unittest.TestCase):
    def test_build_prompt_includes_transcript(self):
        self.assertIn("buy milk", analyze.build_prompt("buy milk"))

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

    def test_parse_analysis_no_json_raises(self):
        with self.assertRaises(ValueError):
            analyze.parse_analysis("no json here")

    def test_build_claude_cmd_no_model(self):
        cmd = analyze.build_claude_cmd("PROMPT", "claude", None)
        self.assertEqual(cmd, ["claude", "-p", "PROMPT"])

    def test_build_claude_cmd_with_model(self):
        cmd = analyze.build_claude_cmd("PROMPT", "claude", "claude-sonnet-5")
        self.assertEqual(cmd, ["claude", "--model", "claude-sonnet-5", "-p", "PROMPT"])
        self.assertEqual(cmd[-1], "PROMPT")

    def test_analyze_reads_claude_stdout(self):
        def fake_runner(cmd, capture_output=True, text=True, timeout=None, **kwargs):
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)
            return SimpleNamespace(
                returncode=0,
                stdout='{"summary":"s","action_items":["a"],"topics":["t"],"notable_details":[]}',
                stderr="",
            )

        out = analyze.analyze("hi", runner=fake_runner)
        self.assertEqual(out["summary"], "s")
        self.assertEqual(out["action_items"], ["a"])

    def test_analyze_nonzero_exit_raises(self):
        def fake_runner(cmd, capture_output=True, text=True, timeout=None, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        with self.assertRaises(RuntimeError):
            analyze.analyze("hi", runner=fake_runner)

    def test_analyze_empty_stdout_raises(self):
        def fake_runner(cmd, capture_output=True, text=True, timeout=None, **kwargs):
            return SimpleNamespace(returncode=0, stdout="   ", stderr="")

        with self.assertRaises(RuntimeError):
            analyze.analyze("hi", runner=fake_runner)


if __name__ == "__main__":
    unittest.main()
