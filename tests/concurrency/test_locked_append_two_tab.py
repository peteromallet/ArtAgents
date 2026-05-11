"""Subprocess race STOP-LINE for the locked-append apex contract (Sprint 1 / T3).

Two ``multiprocessing.spawn`` workers synchronize on a barrier and each call
:func:`append_event_locked` ``N`` times against the SAME run directory. The
contract:

* Every write is serialized → exactly ``2 * N`` events on disk, no
  interleaved bytes, no partial lines.
* The chain re-verifies clean (:func:`verify_chain` returns ok).
* Workers retry on :class:`StaleTailError` (concurrent appender wins) but
  must NOT silently swallow :class:`StaleEpochError` (none should arise
  because no takeover happens here).

Run as 5 rounds of 20 appends per worker; if any seed surfaces interleaved
writes or silent epoch violations, this is a STOP-LINE failure for the
entire Sprint 1 reshape.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from astrid.core.task.events import (
    ZERO_HASH,
    StaleEpochError,
    StaleTailError,
    append_event_locked,
    read_events,
    verify_chain,
)

PER_WORKER = 20
ROUNDS = 100


def _seed_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "lease.json").write_text(
        json.dumps(
            {
                "writer_epoch": 0,
                "attached_session_id": "shared-writer",
                "plan_hash": "",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").touch()


def _worker(
    barrier,  # mp.Barrier
    run_dir_str: str,
    worker_id: str,
    n: int,
    result_queue,  # mp.Queue
) -> None:
    """Run inside a spawned subprocess — module-level so spawn can pickle it."""

    from astrid.core.task.events import (  # local import for spawn
        ZERO_HASH,
        StaleEpochError,
        StaleTailError,
        append_event_locked,
        _peek_tail_hash,  # noqa: PLC2701
    )

    run_dir = Path(run_dir_str)
    events_path = run_dir / "events.jsonl"
    successes = 0
    stale_tail = 0
    stale_epoch = 0
    barrier.wait()
    for i in range(n):
        # Each call retries on StaleTailError (loser sees the winner's tail
        # and chains onto it next attempt). StaleEpochError must never
        # appear in this test — no takeover is happening.
        while True:
            try:
                expected_prev = _peek_tail_hash(events_path)
                append_event_locked(
                    run_dir,
                    {"kind": "race", "w": worker_id, "i": i},
                    expected_writer_epoch=0,
                    expected_prev_hash=expected_prev,
                )
                successes += 1
                break
            except StaleTailError:
                stale_tail += 1
                continue
            except StaleEpochError:
                stale_epoch += 1
                # Don't loop forever on an unexpected epoch fence; surface it.
                break
    result_queue.put(
        {
            "worker_id": worker_id,
            "successes": successes,
            "stale_tail": stale_tail,
            "stale_epoch": stale_epoch,
        }
    )


@pytest.mark.parametrize("round_idx", list(range(ROUNDS)))
def test_two_tab_race_locked_append(tmp_path: Path, round_idx: int) -> None:
    run_dir = tmp_path / f"run-{round_idx}"
    _seed_run(run_dir)

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue: "mp.Queue[dict]" = ctx.Queue()

    p1 = ctx.Process(target=_worker, args=(barrier, str(run_dir), "A", PER_WORKER, queue))
    p2 = ctx.Process(target=_worker, args=(barrier, str(run_dir), "B", PER_WORKER, queue))
    p1.start()
    p2.start()
    p1.join(timeout=60)
    p2.join(timeout=60)
    assert not p1.is_alive() and not p2.is_alive()
    assert p1.exitcode == 0 and p2.exitcode == 0

    results: list[dict] = []
    while not queue.empty():
        results.append(queue.get_nowait())
    assert len(results) == 2

    total_successes = sum(r["successes"] for r in results)
    total_epoch = sum(r["stale_epoch"] for r in results)
    assert total_successes == 2 * PER_WORKER, results
    assert total_epoch == 0, f"unexpected stale-epoch events in pure-append race: {results}"

    # No partial / torn lines.
    events_path = run_dir / "events.jsonl"
    raw = events_path.read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.split(b"\n")
    assert lines[-1] == b""
    actual_lines = lines[:-1]
    assert len(actual_lines) == 2 * PER_WORKER, len(actual_lines)
    for ln in actual_lines:
        json.loads(ln)

    # Chain verifies clean — mid-chain integrity is preserved despite the
    # tail-only CAS being the only in-loop integrity gate (DEC-007).
    ok, last_index, err = verify_chain(events_path)
    assert ok is True, err
    assert last_index == 2 * PER_WORKER - 1

    # Each worker's writes are still individually present (interleaved order
    # is fine; loss is not).
    events = read_events(events_path)
    seen_a = sorted(e["i"] for e in events if e.get("w") == "A")
    seen_b = sorted(e["i"] for e in events if e.get("w") == "B")
    assert seen_a == list(range(PER_WORKER))
    assert seen_b == list(range(PER_WORKER))
