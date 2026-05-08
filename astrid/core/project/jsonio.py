"""Deterministic JSON IO helpers for project state."""

from __future__ import annotations

import errno
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ProjectJsonError(RuntimeError):
    """Raised when project JSON cannot be read or written."""


def read_json(path: str | Path) -> Any:
    json_path = Path(path)
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ProjectJsonError(f"invalid JSON in {json_path}: {exc.msg}") from exc
    except OSError as exc:
        raise ProjectJsonError(f"failed to read {json_path}: {exc}") from exc


def write_json_atomic(path: str | Path, payload: Any) -> None:
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{json_path.name}.", suffix=".tmp", dir=json_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, json_path)
        _fsync_dir(json_path.parent)
    finally:
        tmp_path.unlink(missing_ok=True)


def _fsync_dir(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EBADF}:
            raise
    finally:
        if fd is not None:
            os.close(fd)
