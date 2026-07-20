# tests/test_yamllite.py
import unittest
from voice2note.yamllite import dq, seq


class TestDq(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(dq("hello"), '"hello"')

    def test_colon_is_safe_when_quoted(self):
        self.assertEqual(dq("a: b"), '"a: b"')

    def test_escapes_double_quote(self):
        self.assertEqual(dq('say "hi"'), '"say \\"hi\\""')

    def test_escapes_backslash(self):
        self.assertEqual(dq("a\\b"), '"a\\\\b"')

    def test_collapses_newline(self):
        self.assertEqual(dq("line1\nline2"), '"line1\\nline2"')

    def test_control_char_hex(self):
        self.assertEqual(dq("a\x01b"), '"a\\x01b"')

    def test_emoji_preserved(self):
        self.assertEqual(dq("🎙 memo"), '"🎙 memo"')

    def test_none(self):
        self.assertEqual(dq(None), '""')


class TestSeq(unittest.TestCase):
    def test_flow_sequence(self):
        self.assertEqual(seq(["voice-memo", "qpcr"]), '["voice-memo", "qpcr"]')

    def test_empty(self):
        self.assertEqual(seq([]), "[]")

    def test_quotes_each_item(self):
        self.assertEqual(seq(['a:b', 'c']), '["a:b", "c"]')


if __name__ == "__main__":
    unittest.main()
