# tests/test_config.py
import os
import tempfile
import unittest
from pathlib import Path

from voice2note.config import env_bool, validate_memo_reldir, assert_vault_match


class TestEnvBool(unittest.TestCase):
    def test_true_values(self):
        for v in ["1", "true", "TRUE", "yes", "on"]:
            os.environ["V2N_T"] = v
            self.assertTrue(env_bool("V2N_T", False))

    def test_false_default_when_unset(self):
        os.environ.pop("V2N_MISSING", None)
        self.assertFalse(env_bool("V2N_MISSING", False))


class TestRelDir(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validate_memo_reldir("Memory/voiceMemo"), "Memory/voiceMemo")

    def test_rejects_absolute(self):
        with self.assertRaises(ValueError):
            validate_memo_reldir("/etc/passwd")

    def test_rejects_traversal(self):
        with self.assertRaises(ValueError):
            validate_memo_reldir("Memory/../../etc")


class TestVaultMatch(unittest.TestCase):
    def test_match_ok(self):
        d = tempfile.mkdtemp()
        assert_vault_match(d, d)  # no raise

    def test_mismatch_raises(self):
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        with self.assertRaises(SystemExit):
            assert_vault_match(a, b)


if __name__ == "__main__":
    unittest.main()
