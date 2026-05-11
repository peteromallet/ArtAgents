"""Sprint 1 / T11 / DEC-018: takeover-during-inbox-consume surfaces
:class:`StaleEpochError`.

The inbox consumer (``consume_inbox_entry``) holds a WriterContext-shaped
expectation about ``expected_writer_epoch``. If a competing tab takes
over the run mid-consume, the consumer's NEXT append must reject —
that's the apex contract's epoch fence carrying through to the inbox
path.

This test exercises the lease + locked-append primitives directly to
prove the epoch is a fence at the protocol level; the higher-level
``consume_inbox_entry`` invocation is exercised through the existing
task-kernel tests under the autouse session seed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.session.lease import (
    bump_epoch_and_swap_session,
    write_lease_init,
)
from astrid.core.task.events import (
    ZERO_HASH,
    StaleEpochError,
    StaleTailError,
    append_event_locked,
    read_events,
)


def test_takeover_mid_consume_surfaces_stale_epoch(tmp_path: Path) -> None:
    """A 'consumer' that captured the pre-takeover epoch loses the race."""

    run_dir = tmp_path
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "events.jsonl").touch()
    write_lease_init(run_dir, session_id="S-OLD", plan_hash="")

    # Consumer reads the inbox entry, captures epoch=0, starts processing...
    consumer_captured_epoch = 0
    ev1 = append_event_locked(
        run_dir,
        {"kind": "inbox-pre", "i": 1},
        expected_writer_epoch=consumer_captured_epoch,
        expected_prev_hash=ZERO_HASH,
    )

    # A competing session takes over before the consumer finishes.
    bump_epoch_and_swap_session(
        run_dir, new_session_id="S-NEW", prev_session_id="S-OLD", reason="mid-consume"
    )

    # Consumer's NEXT append (the cursor-advance / step-completed write)
    # uses its captured epoch=0. The epoch fence catches it. The tail
    # also moved (takeover event), so technically either StaleTailError
    # or StaleEpochError is correct depending on ordering — the lease
    # CAS doc says the apex contract is the fence, not which subclass
    # surfaces first. The test accepts either, AND verifies that on a
    # tail-matched but epoch-stale call, StaleEpochError is the
    # surfacing exception.
    with pytest.raises((StaleEpochError, StaleTailError)):
        append_event_locked(
            run_dir,
            {"kind": "inbox-post", "i": 2},
            expected_writer_epoch=consumer_captured_epoch,
            expected_prev_hash=ev1["hash"],
        )

    # Force the just-the-epoch-fence path explicitly.
    current_tail = read_events(run_dir / "events.jsonl")[-1]["hash"]
    with pytest.raises(StaleEpochError) as exc_info:
        append_event_locked(
            run_dir,
            {"kind": "inbox-post-tail-fresh", "i": 3},
            expected_writer_epoch=consumer_captured_epoch,
            expected_prev_hash=current_tail,
        )
    assert exc_info.value.expected == 0
    assert exc_info.value.actual == 1
