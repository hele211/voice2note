# voice2note/lock.py
"""Mandatory single-instance lock (fcntl.flock). launchd only serializes its
own scheduled runs; a manual run could otherwise race it and double-write."""
import fcntl
from pathlib import Path


class AlreadyRunning(Exception):
    pass


class SingleInstanceLock:
    def __init__(self, path):
        self.path = Path(path)
        self._fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(self.path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fd.close()
            raise AlreadyRunning(f"another voice2note instance holds {self.path}")
        self._fd = fd
        return self

    def release(self):
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
