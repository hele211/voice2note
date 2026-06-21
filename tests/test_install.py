# tests/test_install.py
"""Tests for scripts/install.sh — CrickNote plist wiring + safe discovery (Task 1).

Each test runs install.sh in an isolated subprocess with:
  - a temporary HOME (so ~/Library/LaunchAgents and ~/.cricknote are sandboxed),
  - a stub `launchctl` early on PATH (so the real LaunchAgent is never touched),
  - a stub `cricknote` (or none) to drive auto-detection,
  - VOICE2NOTE_CONFIG pointing at a temp config file (so the repo's real
    voice2note.env is never read),
  - a controlled environment (no inherited VOICE2NOTE_* vars).
"""
import json
import os
import plistlib
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
INSTALL_SH = PROJECT_DIR / "scripts" / "install.sh"


def _make_exec(path: Path, body: str = "#!/bin/bash\nexit 0\n"):
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class InstallTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        # Stub directory placed early on PATH.
        self.stubdir = self.tmp / "stubs"
        self.stubdir.mkdir()
        # Stub launchctl records its invocations so tests can assert load/no-load.
        self.launchctl_log = self.tmp / "launchctl.log"
        _make_exec(
            self.stubdir / "launchctl",
            f'#!/bin/bash\necho "$@" >> "{self.launchctl_log}"\nexit 0\n',
        )
        self.config = self.tmp / "voice2note.env"
        self.config.write_text("", encoding="utf-8")
        self.plist = self.home / "Library" / "LaunchAgents" / "com.voice2note.agent.plist"

    def tearDown(self):
        self._tmp.cleanup()

    def make_cricknote(self, name="cricknote"):
        """Create a discoverable, executable stub binary; return its absolute path."""
        return _make_exec(self.stubdir / name)

    def write_cricknote_config(self, vault_path):
        d = self.home / ".cricknote"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(
            json.dumps({"vaultPath": str(vault_path)}), encoding="utf-8"
        )

    def run_install(self, vault="/tmp/Vault", args=None, env=None):
        """Run install.sh with a clean, controlled environment. Returns CompletedProcess."""
        full_env = {
            "HOME": str(self.home),
            # Stub dir first so launchctl/cricknote stubs win; keep system bins for sed/grep.
            "PATH": f"{self.stubdir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "VOICE2NOTE_CONFIG": str(self.config),
            "VOICE2NOTE_PYTHON": "/usr/bin/python3",
        }
        if env:
            full_env.update(env)
        argv = [str(INSTALL_SH)]
        if vault is not None:
            argv.append(vault)
        if args:
            argv += args
        return subprocess.run(
            argv, env=full_env, capture_output=True, text=True
        )

    def load_plist(self):
        with open(self.plist, "rb") as fh:
            return plistlib.load(fh)

    def env_vars(self, data):
        return data["EnvironmentVariables"]

    def assert_launchctl_loaded(self):
        self.assertTrue(self.launchctl_log.exists(), "launchctl was never invoked")
        self.assertIn("load", self.launchctl_log.read_text())

    def assert_launchctl_not_loaded(self):
        if self.launchctl_log.exists():
            self.assertNotIn("load", self.launchctl_log.read_text(),
                             "launchctl load should not have run")


class TestAutoDetectEnable(InstallTestBase):
    def test_cricknote_on_path_enables_with_matching_vault(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(vault)
        r = self.run_install(vault=str(vault))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_USE_CRICKNOTE"], "true")
        bin_path = env["VOICE2NOTE_CRICKNOTE_BIN"]
        self.assertTrue(os.path.isabs(bin_path), bin_path)
        self.assertTrue(os.access(bin_path, os.X_OK), bin_path)
        self.assertEqual(env["VOICE2NOTE_MEMO_RELDIR"], "Memory/voiceMemo")

    def test_binary_dir_in_plist_path(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        binpath = self.make_cricknote()
        self.write_cricknote_config(vault)
        r = self.run_install(vault=str(vault))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertIn(str(binpath.parent), env["PATH"].split(":"))


class TestAutoDetectDisable(InstallTestBase):
    def test_no_binary_standalone(self):
        r = self.run_install(vault="/tmp/Vault")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_USE_CRICKNOTE"], "false")
        combined = (r.stdout + r.stderr).lower()
        self.assertIn("standalone", combined)

    def test_vault_mismatch_installs_standalone(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        other = self.tmp / "OtherVault"
        other.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(other)  # mismatch
        r = self.run_install(vault=str(vault))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_USE_CRICKNOTE"], "false")
        self.assert_launchctl_loaded()
        self.assertIn("vault", (r.stdout + r.stderr).lower())


class TestExplicitTrue(InstallTestBase):
    def test_explicit_true_no_binary_fails_closed(self):
        r = self.run_install(
            vault="/tmp/Vault", env={"VOICE2NOTE_USE_CRICKNOTE": "true"}
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.plist.exists(), "no plist should be written")
        self.assert_launchctl_not_loaded()

    def test_explicit_true_vault_mismatch_fails_closed(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        other = self.tmp / "OtherVault"
        other.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(other)
        r = self.run_install(
            vault=str(vault), env={"VOICE2NOTE_USE_CRICKNOTE": "true"}
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.plist.exists())
        self.assert_launchctl_not_loaded()


class TestNoCricknoteFlag(InstallTestBase):
    def test_flag_wins_over_discovery(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(vault)  # would otherwise enable
        r = self.run_install(vault=str(vault), args=["--no-cricknote"])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_USE_CRICKNOTE"], "false")


class TestPrecedence(InstallTestBase):
    def test_env_wins_over_config(self):
        # config says true, env says false -> false
        self.config.write_text("VOICE2NOTE_USE_CRICKNOTE=true\n", encoding="utf-8")
        vault = self.tmp / "Vault"
        vault.mkdir()
        r = self.run_install(
            vault=str(vault), env={"VOICE2NOTE_USE_CRICKNOTE": "false"}
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_USE_CRICKNOTE"], "false")

    def test_config_wins_over_auto(self):
        # config says false; a binary is discoverable -> still false
        self.config.write_text("VOICE2NOTE_USE_CRICKNOTE=false\n", encoding="utf-8")
        vault = self.tmp / "Vault"
        vault.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(vault)
        r = self.run_install(vault=str(vault))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_USE_CRICKNOTE"], "false")

    def test_explicit_false_with_binary_stays_false(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(vault)
        r = self.run_install(
            vault=str(vault), env={"VOICE2NOTE_USE_CRICKNOTE": "false"}
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_USE_CRICKNOTE"], "false")

    def test_memo_reldir_config_value(self):
        self.config.write_text("VOICE2NOTE_MEMO_RELDIR=Foo/bar\n", encoding="utf-8")
        vault = self.tmp / "Vault"
        vault.mkdir()
        r = self.run_install(vault=str(vault))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        env = self.env_vars(self.load_plist())
        self.assertEqual(env["VOICE2NOTE_MEMO_RELDIR"], "Foo/bar")


class TestValidation(InstallTestBase):
    def test_invalid_boolean_fails_closed(self):
        r = self.run_install(
            vault="/tmp/Vault", env={"VOICE2NOTE_USE_CRICKNOTE": "maybe"}
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.plist.exists())
        self.assert_launchctl_not_loaded()

    def test_absolute_memo_reldir_rejected(self):
        r = self.run_install(
            vault="/tmp/Vault", env={"VOICE2NOTE_MEMO_RELDIR": "/etc/passwd"}
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.plist.exists())

    def test_traversal_memo_reldir_rejected(self):
        r = self.run_install(
            vault="/tmp/Vault", env={"VOICE2NOTE_MEMO_RELDIR": "Memory/../../etc"}
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.plist.exists())


class TestEscaping(InstallTestBase):
    def test_special_chars_round_trip(self):
        vault = self.tmp / "My Vault & Notes"
        vault.mkdir()
        binpath = self.make_cricknote("crick & note")
        self.write_cricknote_config(vault)
        r = self.run_install(
            vault=str(vault),
            env={"VOICE2NOTE_CRICKNOTE_BIN": str(binpath),
                 "VOICE2NOTE_USE_CRICKNOTE": "true"},
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        # plistlib.load must parse without error and values round-trip exactly.
        data = self.load_plist()
        env = self.env_vars(data)
        self.assertEqual(env["VOICE2NOTE_VAULT"], str(vault))
        self.assertEqual(env["VOICE2NOTE_CRICKNOTE_BIN"], str(binpath))


class TestIdempotent(InstallTestBase):
    def test_reinstall_overwrites_cleanly(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(vault)
        r1 = self.run_install(vault=str(vault))
        self.assertEqual(r1.returncode, 0, r1.stderr + r1.stdout)
        first = self.plist.read_bytes()
        r2 = self.run_install(vault=str(vault))
        self.assertEqual(r2.returncode, 0, r2.stderr + r2.stdout)
        # Still exactly one valid plist, parseable.
        data = self.load_plist()
        self.assertEqual(data["Label"], "com.voice2note.agent")
        self.assertEqual(self.plist.read_bytes(), first)


class TestNoUnresolvedPlaceholders(InstallTestBase):
    def test_no_double_underscore_tokens(self):
        vault = self.tmp / "Vault"
        vault.mkdir()
        self.make_cricknote()
        self.write_cricknote_config(vault)
        r = self.run_install(vault=str(vault))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        raw = self.plist.read_text(encoding="utf-8")
        self.assertNotIn("__", raw, "unresolved placeholder remains in plist")


if __name__ == "__main__":
    unittest.main()
