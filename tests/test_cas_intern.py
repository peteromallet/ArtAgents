from __future__ import annotations

import hashlib
from pathlib import Path

from artagents.core.task.cas import cas_dir, cas_path, intern


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_intern_creates_cas_entry(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    src = project_dir / "a.bin"
    payload = b"hello cas"
    src.write_bytes(payload)

    result = intern(project_dir, src)

    sha = _sha256(payload)
    expected = cas_path(project_dir, sha)
    assert result == expected
    assert expected.exists()
    assert expected.read_bytes() == payload


def test_intern_idempotent_discards_duplicate_source(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    payload = b"identical content"
    a = project_dir / "a.bin"
    b = project_dir / "b.bin"
    a.write_bytes(payload)
    b.write_bytes(payload)

    first = intern(project_dir, a)
    second = intern(project_dir, b)

    assert first == second
    assert not b.exists()
    entries = list(cas_dir(project_dir).iterdir())
    assert len(entries) == 1
    assert entries[0] == first


def test_intern_distinct_content_creates_two_entries(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    a = project_dir / "a.bin"
    b = project_dir / "b.bin"
    a.write_bytes(b"alpha")
    b.write_bytes(b"beta")

    first = intern(project_dir, a)
    second = intern(project_dir, b)

    assert first != second
    entries = sorted(p.name for p in cas_dir(project_dir).iterdir())
    assert len(entries) == 2
    assert sorted([first.name, second.name]) == entries
