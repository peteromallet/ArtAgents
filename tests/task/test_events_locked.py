"""Unit tests for the locked event-append apex contract (Sprint 1 / T3).

Covers single-process correctness of :func:`append_event_locked`:

* happy-path append
* stale-tail rejection
* stale-epoch rejection
* succeeds after epoch bump
* tail-seek at the 4 KiB chunk boundary
* tail-seek with a single event larger than 64 KiB (chunked follow-back doubles)
* :func:`verify_chain` catches mid-chain corruption (50-event audit)

The two-process race is covered separately in
``tests/concurrency/test_locked_append_two_tab.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.task.events import (
    ZERO_HASH,
    StaleEpochError,
    StaleTailError,
    append_event_locked,
    verify_chain,
)


def _write_lease(run_dir: Path, *, writer_epoch: int = 0) -> None:
    (run_dir / "lease.json").write_text(
        json.dumps(
            {
                "writer_epoch": writer_epoch,
                "attached_session_id": "S1",
                "plan_hash": "",
            }
        ),
        encoding="utf-8",
    )


def test_happy_path_append_and_verify(tmp_path: Path) -> None:
    _write_lease(tmp_path)
    ev1 = append_event_locked(
        tmp_path, {"kind": "a", "i": 1}, expected_writer_epoch=0, expected_prev_hash=ZERO_HASH
    )
    ev2 = append_event_locked(
        tmp_path, {"kind": "a", "i": 2}, expected_writer_epoch=0, expected_prev_hash=ev1["hash"]
    )
    ev3 = append_event_locked(
        tmp_path, {"kind": "a", "i": 3}, expected_writer_epoch=0, expected_prev_hash=ev2["hash"]
    )
    ok, last_index, err = verify_chain(tmp_path / "events.jsonl")
    assert ok is True
    assert last_index == 2
    assert err is None
    assert ev3["hash"] != ev2["hash"] != ev1["hash"]


def test_stale_tail_rejection(tmp_path: Path) -> None:
    _write_lease(tmp_path)
    append_event_locked(
        tmp_path, {"kind": "a", "i": 1}, expected_writer_epoch=0, expected_prev_hash=ZERO_HASH
    )
    # Second writer believed it would chain to ZERO_HASH but the tail has
    # already moved on — must reject.
    with pytest.raises(StaleTailError) as exc_info:
        append_event_locked(
            tmp_path, {"kind": "a", "i": 2}, expected_writer_epoch=0, expected_prev_hash=ZERO_HASH
        )
    assert exc_info.value.expected == ZERO_HASH
    assert exc_info.value.actual != ZERO_HASH
    assert exc_info.value.expected in str(exc_info.value)
    assert exc_info.value.actual in str(exc_info.value)


def test_stale_epoch_rejection(tmp_path: Path) -> None:
    _write_lease(tmp_path, writer_epoch=5)
    with pytest.raises(StaleEpochError) as exc_info:
        append_event_locked(
            tmp_path,
            {"kind": "a", "i": 1},
            expected_writer_epoch=4,
            expected_prev_hash=ZERO_HASH,
        )
    assert exc_info.value.expected == 4
    assert exc_info.value.actual == 5
    assert "4" in str(exc_info.value)
    assert "5" in str(exc_info.value)


def test_succeeds_after_epoch_bump(tmp_path: Path) -> None:
    _write_lease(tmp_path, writer_epoch=0)
    ev1 = append_event_locked(
        tmp_path, {"kind": "a", "i": 1}, expected_writer_epoch=0, expected_prev_hash=ZERO_HASH
    )
    # Simulate takeover: epoch bumped to 1.
    _write_lease(tmp_path, writer_epoch=1)
    # The old writer (still believing epoch=0) is rejected.
    with pytest.raises(StaleEpochError):
        append_event_locked(
            tmp_path,
            {"kind": "a", "i": 2},
            expected_writer_epoch=0,
            expected_prev_hash=ev1["hash"],
        )
    # The new writer (with the post-bump epoch) succeeds.
    ev2 = append_event_locked(
        tmp_path, {"kind": "a", "i": 2}, expected_writer_epoch=1, expected_prev_hash=ev1["hash"]
    )
    ok, _, err = verify_chain(tmp_path / "events.jsonl")
    assert ok and err is None
    assert ev2["hash"] != ev1["hash"]


def test_tail_seek_handles_4kb_boundary(tmp_path: Path) -> None:
    """Pack the file so the last line straddles the 4 KiB initial chunk."""

    _write_lease(tmp_path)
    prev = ZERO_HASH
    # ~30 bytes per line × 200 lines ≈ 6 KiB total → forces at least one doubling.
    for i in range(200):
        ev = append_event_locked(
            tmp_path, {"kind": "p", "i": i}, expected_writer_epoch=0, expected_prev_hash=prev
        )
        prev = ev["hash"]
    ok, last, err = verify_chain(tmp_path / "events.jsonl")
    assert ok and err is None
    assert last == 199


def test_tail_seek_handles_oversized_single_event(tmp_path: Path) -> None:
    """A single event larger than the initial 4 KiB window forces window doubling."""

    _write_lease(tmp_path)
    payload = "x" * (80 * 1024)
    ev1 = append_event_locked(
        tmp_path,
        {"kind": "big", "p": payload},
        expected_writer_epoch=0,
        expected_prev_hash=ZERO_HASH,
    )
    # Even though the file holds a single >80 KiB line, the tail-seek must
    # recover the prev hash so the second append chains correctly.
    ev2 = append_event_locked(
        tmp_path,
        {"kind": "big", "p": payload},
        expected_writer_epoch=0,
        expected_prev_hash=ev1["hash"],
    )
    ok, last, err = verify_chain(tmp_path / "events.jsonl")
    assert ok and err is None
    assert last == 1
    assert ev2["hash"] != ev1["hash"]


def test_verify_chain_catches_midchain_corruption(tmp_path: Path) -> None:
    """verify_chain remains a working offline audit primitive (DEC-007)."""

    _write_lease(tmp_path)
    prev = ZERO_HASH
    for i in range(50):
        ev = append_event_locked(
            tmp_path, {"kind": "p", "i": i}, expected_writer_epoch=0, expected_prev_hash=prev
        )
        prev = ev["hash"]
    events_path = tmp_path / "events.jsonl"
    lines = events_path.read_bytes().split(b"\n")
    # Flip a single byte in line 25 (a JSON-significant char inside the
    # payload, not the trailing newline structure).
    target_line = bytearray(lines[25])
    idx = target_line.find(b'"i":')
    assert idx != -1
    # Mutate the digit after `"i":` so the hash recompute will not match.
    target_line[idx + 4] = ord("9") if target_line[idx + 4] != ord("9") else ord("0")
    lines[25] = bytes(target_line)
    events_path.write_bytes(b"\n".join(lines))
    ok, bad_index, err = verify_chain(events_path)
    assert ok is False
    assert bad_index == 25
    assert err is not None
