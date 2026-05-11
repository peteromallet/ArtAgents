"""Sha256 + size helpers and offline integrity verification for final outputs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

_STREAM_CHUNK_BYTES = 1 * 1024 * 1024  # 1 MiB


def compute_sha256(path: str | Path) -> str:
    """Return the hex-encoded SHA-256 digest of *path*, streaming in 1 MiB chunks."""
    file_path = Path(path)
    hasher = hashlib.sha256()
    with file_path.open("rb", buffering=0) as fh:
        while True:
            chunk = fh.read(_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def file_size(path: str | Path) -> int:
    """Return the on-disk size in bytes of *path*."""
    return Path(path).stat().st_size


def verify(output: object) -> Literal["ok", "missing", "mismatch"]:
    """Recompute integrity for a FinalOutput-like record.

    *output* may be a :class:`FinalOutput` (checked via attribute access) or a
    plain ``dict`` with keys ``path``, ``sha256``, and ``size``.

    Returns
    -------
    Literal["ok", "missing", "mismatch"]
        ``missing`` – the file does not exist.
        ``mismatch`` – the file exists but its sha256 or size differs.
        ``ok`` – sha256 **and** size still match.
    """
    # Accept both FinalOutput dataclass and plain dicts.
    if isinstance(output, dict):
        file_path = output.get("path", "")
        expected_sha256 = output.get("sha256", "")
        expected_size = output.get("size")
    else:
        file_path = getattr(output, "path", "")
        expected_sha256 = getattr(output, "sha256", "")
        expected_size = getattr(output, "size", None)

    fp = Path(file_path)
    if not fp.is_file():
        return "missing"

    try:
        actual_size = fp.stat().st_size
    except OSError:
        return "missing"

    if expected_size is not None and actual_size != expected_size:
        return "mismatch"

    actual_sha256 = compute_sha256(fp)
    if actual_sha256 != expected_sha256:
        return "mismatch"

    return "ok"