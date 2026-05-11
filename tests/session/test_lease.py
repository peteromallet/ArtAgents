"""Round-trip + atomic-swap tests for the lease helpers (Sprint 1 / T4)."""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from astrid.core.session.lease import (
    LEASE_DEFAULTS,
    LeaseError,
    bump_epoch_and_swap_session,
    claim_orphan_lease,
    read_lease,
    release_writer_lease,
    write_lease_init,
)
from astrid.core.task.events import (
    ZERO_HASH,
    EventLogError,
    StaleEpochError,
    StaleTailError,
    append_event_locked,
    read_events,
    verify_chain,
)


def test_read_lease_defaults_when_missing(tmp_path: Path) -> None:
    assert read_lease(tmp_path) == dict(LEASE_DEFAULTS)


def test_write_lease_init_round_trip(tmp_path: Path) -> None:
    payload = write_lease_init(tmp_path, session_id="S1", plan_hash="sha256:" + "a" * 64)
    on_disk = read_lease(tmp_path)
    assert on_disk == payload
    assert on_disk["writer_epoch"] == 0
    assert on_disk["attached_session_id"] == "S1"
    assert on_disk["plan_hash"].startswith("sha256:")


def test_bump_epoch_appends_takeover_event_with_post_bump_epoch(tmp_path: Path) -> None:
    """The takeover event itself must carry expected_writer_epoch = N+1 (post-bump)."""

    write_lease_init(tmp_path, session_id="S1", plan_hash="")
    # Seed one prior event so the takeover event is event #2 in the chain.
    ev1 = append_event_locked(
        tmp_path,
        {"kind": "seed", "i": 0},
        expected_writer_epoch=0,
        expected_prev_hash=ZERO_HASH,
    )

    updated = bump_epoch_and_swap_session(
        tmp_path, new_session_id="S2", prev_session_id="S1", reason="manual"
    )
    assert updated["writer_epoch"] == 1
    assert updated["attached_session_id"] == "S2"
    # Plan hash preserved.
    assert updated["plan_hash"] == ""

    events = read_events(tmp_path / "events.jsonl")
    assert len(events) == 2
    takeover = events[-1]
    assert takeover["kind"] == "takeover"
    assert takeover["prev_session"] == "S1"
    assert takeover["new_session"] == "S2"
    assert takeover["prev_epoch"] == 0
    assert takeover["new_epoch"] == 1
    # Chain still verifies.
    ok, _, err = verify_chain(tmp_path / "events.jsonl")
    assert ok and err is None
    # The original writer (still believing epoch=0, last-seen tail = ev1) is
    # rejected by the locked-append fence. Either StaleTailError OR
    # StaleEpochError is correct — after a takeover both have shifted; the
    # tail-CAS happens first inside append_event_locked, so it's the one
    # that surfaces here. The point of the test is that the stale writer
    # CANNOT commit, not which specific CAS catches it.
    with pytest.raises((StaleTailError, StaleEpochError)):
        append_event_locked(
            tmp_path,
            {"kind": "after", "i": 1},
            expected_writer_epoch=0,
            expected_prev_hash=ev1["hash"],
        )
    # And if it had somehow guessed the right tail, the epoch CAS still
    # catches the stale epoch:
    current_tail = read_events(tmp_path / "events.jsonl")[-1]["hash"]
    with pytest.raises(StaleEpochError):
        append_event_locked(
            tmp_path,
            {"kind": "after", "i": 2},
            expected_writer_epoch=0,
            expected_prev_hash=current_tail,
        )


def test_claim_orphan_lease_sets_writer_and_bumps_epoch(tmp_path: Path) -> None:
    write_lease_init(tmp_path, session_id="S1", plan_hash="")
    release_writer_lease(tmp_path)
    pre = read_lease(tmp_path)
    assert pre["attached_session_id"] is None
    assert pre["writer_epoch"] == 0

    claimed = claim_orphan_lease(tmp_path, new_session_id="S2")
    assert claimed["attached_session_id"] == "S2"
    assert claimed["writer_epoch"] == 1

    events = read_events(tmp_path / "events.jsonl")
    takeover = events[-1]
    assert takeover["kind"] == "takeover"
    assert takeover["prev_session"] is None
    assert takeover["new_session"] == "S2"
    assert takeover["reason"] == "orphan-claim"


def test_claim_orphan_refuses_warm_lease(tmp_path: Path) -> None:
    write_lease_init(tmp_path, session_id="S1", plan_hash="")
    with pytest.raises(LeaseError, match="orphan"):
        claim_orphan_lease(tmp_path, new_session_id="S2")


def test_release_writer_lease_preserves_epoch_and_plan_hash(tmp_path: Path) -> None:
    write_lease_init(tmp_path, session_id="S1", plan_hash="sha256:" + "b" * 64)
    bump_epoch_and_swap_session(
        tmp_path, new_session_id="S2", prev_session_id="S1", reason="x"
    )
    pre = read_lease(tmp_path)
    released = release_writer_lease(tmp_path)
    assert released["attached_session_id"] is None
    assert released["writer_epoch"] == pre["writer_epoch"]
    assert released["plan_hash"] == pre["plan_hash"]


def test_read_lease_rejects_malformed_json(tmp_path: Path) -> None:
    (tmp_path / "lease.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(LeaseError, match="invalid JSON"):
        read_lease(tmp_path)


def test_read_lease_rejects_bad_epoch_type(tmp_path: Path) -> None:
    (tmp_path / "lease.json").write_text(
        json.dumps({"writer_epoch": "zero", "attached_session_id": None, "plan_hash": ""}),
        encoding="utf-8",
    )
    with pytest.raises(LeaseError, match="writer_epoch"):
        read_lease(tmp_path)


def _concurrent_takeover_worker(barrier, run_dir_str: str, new_sid: str, result_q) -> None:
    """Module-level worker for the concurrent takeover test (spawn-pickleable)."""

    from astrid.core.session.lease import bump_epoch_and_swap_session

    barrier.wait()
    try:
        updated = bump_epoch_and_swap_session(
            Path(run_dir_str), new_session_id=new_sid, prev_session_id="S1", reason="race"
        )
        result_q.put({"sid": new_sid, "ok": True, "epoch": updated["writer_epoch"]})
    except Exception as exc:  # pragma: no cover - failure surfaces in assertion
        result_q.put({"sid": new_sid, "ok": False, "err": repr(exc)})


def test_concurrent_takeover_is_serialized(tmp_path: Path) -> None:
    """Two takeovers race; both succeed in some order, epochs reach 2, chain ok."""

    write_lease_init(tmp_path, session_id="S1", plan_hash="")
    append_event_locked(
        tmp_path, {"kind": "seed", "i": 0}, expected_writer_epoch=0, expected_prev_hash=ZERO_HASH
    )

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    q: "mp.Queue[dict]" = ctx.Queue()
    p1 = ctx.Process(target=_concurrent_takeover_worker, args=(barrier, str(tmp_path), "S2", q))
    p2 = ctx.Process(target=_concurrent_takeover_worker, args=(barrier, str(tmp_path), "S3", q))
    p1.start(); p2.start()
    p1.join(timeout=30); p2.join(timeout=30)
    assert p1.exitcode == 0 and p2.exitcode == 0

    results = []
    while not q.empty():
        results.append(q.get_nowait())
    assert len(results) == 2 and all(r["ok"] for r in results), results

    # Final epoch reached 2 (both bumps applied serially).
    final = read_lease(tmp_path)
    assert final["writer_epoch"] == 2
    assert final["attached_session_id"] in {"S2", "S3"}

    # Two takeover events written; chain re-verifies clean.
    events = read_events(tmp_path / "events.jsonl")
    assert sum(1 for e in events if e["kind"] == "takeover") == 2
    ok, _, err = verify_chain(tmp_path / "events.jsonl")
    assert ok and err is None
