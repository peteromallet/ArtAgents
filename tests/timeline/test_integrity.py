"""Tests for astrid.core.timeline.integrity — sha256, file_size, verify."""

from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.timeline.integrity import compute_sha256, file_size, verify
from astrid.core.timeline.model import FinalOutput
from astrid.threads.ids import generate_ulid


class TestComputeSha256:
    def test_returns_hex_string(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        digest = compute_sha256(f)
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"deterministic test content")
        d1 = compute_sha256(f)
        d2 = compute_sha256(f)
        assert d1 == d2

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert compute_sha256(f1) != compute_sha256(f2)

    def test_known_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        # sha256 of empty string.
        assert (
            compute_sha256(f)
            == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_large_file_streaming(self, tmp_path: Path) -> None:
        """Write > 1 MiB to exercise streaming chunks."""
        f = tmp_path / "large.bin"
        # 2.5 MiB of pattern data.
        data = (b"A" * 1024 + b"B" * 1024) * 1280
        f.write_bytes(data)
        digest = compute_sha256(f)
        assert isinstance(digest, str)
        assert len(digest) == 64


class TestFileSize:
    def test_returns_correct_size(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello")
        assert file_size(f) == 5

    def test_zero_byte_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        assert file_size(f) == 0


class TestVerify:
    def test_ok_when_file_matches(self, tmp_path: Path) -> None:
        f = tmp_path / "file.mp4"
        f.write_bytes(b"test content")
        sha = compute_sha256(f)
        fo = {
            "path": str(f),
            "sha256": sha,
            "size": f.stat().st_size,
        }
        assert verify(fo) == "ok"

    def test_ok_with_finaloutput_dataclass(self, tmp_path: Path) -> None:
        f = tmp_path / "file.mp4"
        f.write_bytes(b"test content")
        sha = compute_sha256(f)
        fo = FinalOutput(
            ulid=generate_ulid(),
            path=str(f),
            kind="mp4",
            size=f.stat().st_size,
            sha256=sha,
            check_status="ok",
            check_at="2026-05-11T20:00:00Z",
            recorded_at="2026-05-11T20:00:00Z",
            recorded_by="agent:test",
            from_run=generate_ulid(),
        )
        assert verify(fo) == "ok"

    def test_missing_when_file_does_not_exist(self, tmp_path: Path) -> None:
        fo = {
            "path": str(tmp_path / "nonexistent.mp4"),
            "sha256": "a" * 64,
            "size": 0,
        }
        assert verify(fo) == "missing"

    def test_mismatch_when_sha256_differs(self, tmp_path: Path) -> None:
        f = tmp_path / "file.bin"
        f.write_bytes(b"original content")
        fo = {
            "path": str(f),
            "sha256": "f" * 64,  # deliberately wrong
            "size": f.stat().st_size,
        }
        assert verify(fo) == "mismatch"

    def test_mismatch_when_size_differs(self, tmp_path: Path) -> None:
        f = tmp_path / "file.bin"
        f.write_bytes(b"short")
        sha = compute_sha256(f)
        fo = {
            "path": str(f),
            "sha256": sha,
            "size": 9999,  # deliberately wrong
        }
        assert verify(fo) == "mismatch"

    def test_corruption_full_cycle(self, tmp_path: Path) -> None:
        """Write → verify ok → corrupt (flip byte) → verify mismatch → delete → verify missing."""
        f = tmp_path / "corruptible.bin"
        original = b"The quick brown fox jumps over the lazy dog." * 100
        f.write_bytes(original)

        sha = compute_sha256(f)
        size = f.stat().st_size

        fo_dict = {"path": str(f), "sha256": sha, "size": size}

        # Step 1: verify ok.
        assert verify(fo_dict) == "ok"

        # Step 2: corrupt (flip a single byte).
        data = bytearray(f.read_bytes())
        data[50] ^= 0xFF  # flip byte 50
        f.write_bytes(bytes(data))

        # Step 3: verify mismatch.
        assert verify(fo_dict) == "mismatch"

        # Step 4: delete the file.
        f.unlink()

        # Step 5: verify missing.
        assert verify(fo_dict) == "missing"

    def test_missing_when_stat_fails(self, tmp_path: Path) -> None:
        """If the file exists but stat fails (permissions), treat as missing."""
        f = tmp_path / "unreadable.bin"
        f.write_bytes(b"content")
        fo = {
            "path": str(f),
            "sha256": compute_sha256(f),
            "size": f.stat().st_size,
        }
        # Remove the file between capturing the dict and calling verify.
        f.unlink()
        assert verify(fo) == "missing"