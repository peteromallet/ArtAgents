"""Per-project content-addressable store for produces artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

__all__ = ["cas_dir", "cas_path", "hash_file", "intern", "link_into_produces"]


_CHUNK_SIZE = 64 * 1024


def cas_dir(project_dir: Path) -> Path:
    return project_dir / ".cas"


def cas_path(project_dir: Path, sha256: str) -> Path:
    return cas_dir(project_dir) / sha256


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def intern(project_dir: Path, source_path: Path) -> Path:
    sha = hash_file(source_path)
    cas_dir(project_dir).mkdir(parents=True, exist_ok=True)
    target = cas_path(project_dir, sha)
    if target.exists():
        source_path.unlink()
        return target
    return source_path.replace(target)


def link_into_produces(cas_target: Path, target_path: Path) -> None:
    if target_path.exists() or target_path.is_symlink():
        target_path.unlink()
    rel = os.path.relpath(cas_target, target_path.parent)
    os.symlink(rel, target_path)
