"""Sprint 1 / T11: takeover-during-append atomicity (STOP-LINE).

The contract: when one process is mid-append and another fires a
``bump_epoch_and_swap_session`` takeover at the same moment, the outcome
MUST be one of:

(a) The append wins. Takeover then sees the new tail when it computes
    the takeover-event prev_hash; the lease epoch advances to N+1, the
    takeover event is written under the new tail, and the original
    appender's NEXT mutating verb is rejected with :class:`StaleEpochError`.

(b) The takeover wins. The mid-flight appender's tail/epoch CAS
    discovers the shift; the in-progress append is rejected with
    :class:`StaleTailError` or :class:`StaleEpochError`. The takeover
    event lands; no data is lost.

Never (c): both succeed silently. Never (d): a partial append on disk.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from astrid.core.session.lease import (
    bump_epoch_and_swap_session,
    read_lease,
    write_lease_init,
)
from astrid.core.task.events import (
    ZERO_HASH,
    StaleEpochError,
    StaleTailError,
    append_event_locked,
    read_events,
    verify_chain,
)


def _seed_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id="S-WRITER", plan_hash="")


def _appender(barrier, run_dir_str: str, n: int, queue) -> None:
    from astrid.core.task.events import (  # local for spawn
        StaleEpochError,
        StaleTailError,
        ZERO_HASH,
        _peek_tail_hash,
        append_event_locked,
    )

    run_dir = Path(run_dir_str)
    events_path = run_dir / "events.jsonl"
    successes = 0
    stale_tail = 0
    stale_epoch = 0
    barrier.wait()
    for i in range(n):
        try:
            append_event_locked(
                run_dir,
                {"kind": "append", "i": i},
                expected_writer_epoch=0,
                expected_prev_hash=_peek_tail_hash(events_path),
            )
            successes += 1
        except StaleTailError:
            stale_tail += 1
        except StaleEpochError:
            stale_epoch += 1
            break  # stop on takeover; we're no longer the writer
    queue.put({"successes": successes, "stale_tail": stale_tail, "stale_epoch": stale_epoch})


def _taker(barrier, run_dir_str: str, queue) -> None:
    from astrid.core.session.lease import bump_epoch_and_swap_session

    run_dir = Path(run_dir_str)
    barrier.wait()
    updated = bump_epoch_and_swap_session(
        run_dir, new_session_id="S-NEW", prev_session_id="S-WRITER", reason="race"
    )
    queue.put({"epoch_after": updated["writer_epoch"]})


@pytest.mark.parametrize("round_idx", list(range(20)))
def test_takeover_during_append_is_atomic(tmp_path: Path, round_idx: int) -> None:
    """20 rounds of takeover-during-append: never both-succeed-silently,
    never silent data loss, chain always verifies clean."""

    run_dir = tmp_path / f"run-{round_idx}"
    _seed_run(run_dir)

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    q: "mp.Queue[dict]" = ctx.Queue()
    p_append = ctx.Process(target=_appender, args=(barrier, str(run_dir), 30, q))
    p_take = ctx.Process(target=_taker, args=(barrier, str(run_dir), q))
    p_append.start()
    p_take.start()
    p_append.join(timeout=30)
    p_take.join(timeout=30)
    assert p_append.exitcode == 0 and p_take.exitcode == 0

    results: list[dict] = []
    while not q.empty():
        results.append(q.get_nowait())

    # Takeover always succeeded → epoch is now 1.
    lease = read_lease(run_dir)
    assert lease["writer_epoch"] == 1
    assert lease["attached_session_id"] == "S-NEW"

    # The chain verifies — there is no partial line and the takeover
    # event is properly chained off the previous tail.
    events_path = run_dir / "events.jsonl"
    ok, last_index, err = verify_chain(events_path)
    assert ok, err

    # Exactly one takeover event present.
    events = read_events(events_path)
    takeover_count = sum(1 for ev in events if ev.get("kind") == "takeover")
    assert takeover_count == 1, f"expected exactly one takeover event, got {takeover_count}"

    # Final state never shows the appender having committed events under
    # the OLD epoch AFTER the takeover landed: every "append" event has a
    # hash that chains forward into the takeover (or precedes it). The
    # combination of chain ok + epoch=1 is sufficient: any post-takeover
    # append by the original writer (epoch=0) would have raised
    # StaleEpochError, which the appender records and stops on. Total
    # event count = appender_successes + 1 (the takeover).
    appender = next(r for r in results if "successes" in r)
    assert len(events) == appender["successes"] + 1


def test_stale_writer_post_takeover_is_rejected(tmp_path: Path) -> None:
    """A writer that didn't notice the takeover gets StaleEpochError on
    its next mutating verb (the apex contract's whole point)."""

    run_dir = tmp_path
    _seed_run(run_dir)
    ev1 = append_event_locked(
        run_dir,
        {"kind": "before", "i": 1},
        expected_writer_epoch=0,
        expected_prev_hash=ZERO_HASH,
    )

    # Take over.
    bump_epoch_and_swap_session(
        run_dir, new_session_id="S-NEW", prev_session_id="S-WRITER", reason="explicit"
    )

    # Stale writer (still believes epoch=0, last tail = ev1["hash"]) fires
    # another append. The under-lock tail-CAS sees the takeover event's
    # hash and the epoch-CAS sees epoch=1, so SOMETHING raises.
    with pytest.raises((StaleTailError, StaleEpochError)):
        append_event_locked(
            run_dir,
            {"kind": "stale-write"},
            expected_writer_epoch=0,
            expected_prev_hash=ev1["hash"],
        )
