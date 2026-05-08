"""Locked atomic storage for `.astrid/threads.json`."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from astrid._paths import REPO_ROOT

from .schema import empty_threads_index, validate_threads_index

LOCK_TIMEOUT_SECONDS = 30.0


class ThreadIndexError(RuntimeError):
    """Raised when the thread index cannot be read or written safely."""


class ThreadIndexLockTimeout(ThreadIndexError):
    """Raised when another process holds the thread index lock too long."""


class ThreadIndexStore:
    def __init__(self, repo_root: Path | str = REPO_ROOT, *, lock_timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.state_dir = self.repo_root / ".astrid"
        self.index_path = self.state_dir / "threads.json"
        self.lock_path = self.state_dir / "threads.json.lock"
        self.backup_path = self.state_dir / "threads.json.bak"
        self.lock_timeout = float(lock_timeout)

    def read(self) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.locked():
            return self._read_unlocked()

    def write(self, index: dict[str, Any]) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.locked():
            normalized = validate_threads_index(index)
            self._write_unlocked(normalized)
            return normalized

    def update(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.locked():
            index = self._read_unlocked()
            result = mutator(index)
            normalized = validate_threads_index(index)
            self._write_unlocked(normalized)
            return result

    @contextlib.contextmanager
    def locked(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            self._acquire_lock(handle)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _acquire_lock(self, handle) -> None:
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ThreadIndexLockTimeout(
                        "Timed out waiting for .astrid/threads.json lock. "
                        "Another Astrid process may still be writing thread state; "
                        "wait for it to finish or remove the stale lock file only after verifying no Astrid process is running."
                    ) from exc
                time.sleep(0.05)

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return empty_threads_index()
        try:
            return self._read_path(self.index_path)
        except (OSError, json.JSONDecodeError, ValueError) as current_error:
            if not self.backup_path.exists():
                raise ThreadIndexError(f"failed to read {self.index_path}: {current_error}") from current_error
            try:
                recovered = self._read_path(self.backup_path)
            except (OSError, json.JSONDecodeError, ValueError) as backup_error:
                raise ThreadIndexError(
                    f"failed to read {self.index_path} and backup {self.backup_path}: {backup_error}"
                ) from backup_error
            self._write_unlocked(recovered)
            return recovered

    def _read_path(self, path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_threads_index(data)

    def _write_unlocked(self, index: dict[str, Any]) -> None:
        normalized = validate_threads_index(index)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="threads.", suffix=".tmp", dir=self.state_dir)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(normalized, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if self.index_path.exists():
                shutil.copy2(self.index_path, self.backup_path)
                _fsync_file(self.backup_path)
            os.replace(tmp_path, self.index_path)
            _fsync_dir(self.state_dir)
        finally:
            tmp_path.unlink(missing_ok=True)


def _fsync_file(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError:
        pass


def _fsync_dir(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    fd = None
    try:
        fd = os.open(path, flags)
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EBADF}:
            raise
    finally:
        if fd is not None:
            os.close(fd)
