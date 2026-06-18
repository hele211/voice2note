# tests/test_lock.py
import tempfile
import unittest
from pathlib import Path

from voice2note.lock import SingleInstanceLock, AlreadyRunning


class TestLock(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "v2n.lock"

    def test_second_acquire_raises(self):
        first = SingleInstanceLock(self.path)
        first.acquire()
        try:
            with self.assertRaises(AlreadyRunning):
                SingleInstanceLock(self.path).acquire()
        finally:
            first.release()

    def test_release_allows_reacquire(self):
        a = SingleInstanceLock(self.path)
        a.acquire()
        a.release()
        b = SingleInstanceLock(self.path)
        b.acquire()  # should not raise
        b.release()

    def test_context_manager(self):
        with SingleInstanceLock(self.path):
            with self.assertRaises(AlreadyRunning):
                SingleInstanceLock(self.path).acquire()


if __name__ == "__main__":
    unittest.main()
