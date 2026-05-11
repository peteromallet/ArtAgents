"""Run-lease helpers.

The lease lives at ``runs/<run_id>/lease.json`` with schema::

    {"writer_epoch": int, "attached_session_id": str | None, "plan_hash": str}

The epoch is the fence: every event append CAS-checks it (see
:func:`astrid.core.task.events.append_event_locked`), so a stale writer that
loses a takeover race is rejected at append time, not silently committed.

Takeover/orphan-claim/release ALL acquire the same ``fcntl.flock(LOCK_EX)``
on ``events.jsonl`` that :func:`append_event_locked` uses — this is what
serializes a takeover against an in-flight append.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astrid.core.project.jsonio import write_json_atomic
from astrid.core.task.events import (
    EVENTS_FILENAME,
    LEASE_FILENAME,
    ZERO_HASH,
    EventLogError,
    _event_hash,  # noqa: PLC2701 -- internal hash helper reused on purpose
    _read_tail_hash,  # noqa: PLC2701
    append_event_locked,
)

LEASE_DEFAULTS: dict[str, Any] = {
    "writer_epoch": 0,
    "attached_session_id": None,
    "plan_hash": "",
}


class LeaseError(RuntimeError):
    """Raised when the lease file is malformed or operation preconditions fail."""


def read_lease(run_dir: str | Path) -> dict[str, Any]:
    """Return the lease dict; defaults when the file is absent."""

    lease_path = Path(run_dir) / LEASE_FILENAME
    try:
        raw = lease_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return dict(LEASE_DEFAULTS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LeaseError(f"invalid JSON in lease {lease_path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise LeaseError(f"lease {lease_path} must be a JSON object")
    return _normalize_lease(data, lease_path)


def write_lease_init(
    run_dir: str | Path,
    *,
    session_id: str,
    plan_hash: str,
) -> dict[str, Any]:
    """Write the initial lease for a new run (atomic tmp+os.replace).

    Use this in ``cmd_start`` BEFORE writing ``current_run.json`` so that any
    reader observing the new current-run pointer is guaranteed to find a
    lease behind it.
    """

    payload = {
        "writer_epoch": 0,
        "attached_session_id": session_id,
        "plan_hash": plan_hash,
    }
    write_json_atomic(Path(run_dir) / LEASE_FILENAME, payload)
    return payload


def bump_epoch_and_swap_session(
    run_dir: str | Path,
    *,
    new_session_id: str,
    prev_session_id: str | None,
    reason: str,
) -> dict[str, Any]:
    """Atomically bump ``writer_epoch`` and swap the lease writer.

    Holds the SAME ``fcntl.flock(LOCK_EX)`` on ``events.jsonl`` that
    :func:`append_event_locked` uses, then:

    1. Reads the current lease (under the lock).
    2. Increments ``writer_epoch`` (N → N+1), swaps ``attached_session_id``
       to ``new_session_id``, preserves ``plan_hash``, atomically rewrites
       ``lease.json``.
    3. Appends a ``takeover`` event with ``expected_writer_epoch = N+1`` (the
       lease already holds N+1 by the time we call into append_event_locked,
       which re-reads the epoch under the same flock).
    """

    run_path = Path(run_dir)
    events_path = run_path / EVENTS_FILENAME
    lease_path = run_path / LEASE_FILENAME
    run_path.mkdir(parents=True, exist_ok=True)
    events_path.touch(exist_ok=True)

    with events_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = _read_lease_under_lock(lease_path)
            prev_epoch = current["writer_epoch"]
            new_epoch = prev_epoch + 1
            updated = {
                "writer_epoch": new_epoch,
                "attached_session_id": new_session_id,
                "plan_hash": current["plan_hash"],
            }
            write_json_atomic(lease_path, updated)

            tail_hash = _read_tail_hash(handle)
            takeover_event = {
                "kind": "takeover",
                "prev_session": prev_session_id,
                "new_session": new_session_id,
                "prev_epoch": prev_epoch,
                "new_epoch": new_epoch,
                "reason": reason,
                "ts": _utc_now_iso(),
            }
            # Recompute the new event line ourselves and write it under the
            # already-held lock; we cannot reenter append_event_locked because
            # it would try to re-acquire the same flock on the same fd. The
            # CAS checks it performs are already satisfied here (we read the
            # tail under the lock; we just wrote the lease with new_epoch),
            # so this is the locked-append contract executed inline.
            stored = dict(takeover_event)
            stored.pop("hash", None)
            stored["hash"] = _event_hash(tail_hash, stored)
            line = (
                json.dumps(stored, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            handle.seek(0, os.SEEK_END)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return updated


def claim_orphan_lease(
    run_dir: str | Path,
    *,
    new_session_id: str,
) -> dict[str, Any]:
    """Claim a lease whose ``attached_session_id`` is ``None``.

    Same flock as :func:`bump_epoch_and_swap_session`. Sets the writer AND
    bumps the epoch by 1 so any stale appender from the previous era is
    rejected via :class:`StaleEpochError`.
    """

    run_path = Path(run_dir)
    events_path = run_path / EVENTS_FILENAME
    lease_path = run_path / LEASE_FILENAME
    run_path.mkdir(parents=True, exist_ok=True)
    events_path.touch(exist_ok=True)

    with events_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = _read_lease_under_lock(lease_path)
            if current["attached_session_id"] is not None:
                raise LeaseError(
                    "claim_orphan_lease requires lease.attached_session_id == None; "
                    f"current writer is {current['attached_session_id']!r}"
                )
            prev_epoch = current["writer_epoch"]
            new_epoch = prev_epoch + 1
            updated = {
                "writer_epoch": new_epoch,
                "attached_session_id": new_session_id,
                "plan_hash": current["plan_hash"],
            }
            write_json_atomic(lease_path, updated)

            tail_hash = _read_tail_hash(handle)
            event = {
                "kind": "takeover",
                "prev_session": None,
                "new_session": new_session_id,
                "prev_epoch": prev_epoch,
                "new_epoch": new_epoch,
                "reason": "orphan-claim",
                "ts": _utc_now_iso(),
            }
            stored = dict(event)
            stored.pop("hash", None)
            stored["hash"] = _event_hash(tail_hash, stored)
            line = (
                json.dumps(stored, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            handle.seek(0, os.SEEK_END)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return updated


def release_writer_lease(run_dir: str | Path) -> dict[str, Any]:
    """Clear ``attached_session_id`` under the same flock; preserve epoch + plan_hash."""

    run_path = Path(run_dir)
    events_path = run_path / EVENTS_FILENAME
    lease_path = run_path / LEASE_FILENAME
    run_path.mkdir(parents=True, exist_ok=True)
    events_path.touch(exist_ok=True)

    with events_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = _read_lease_under_lock(lease_path)
            updated = {
                "writer_epoch": current["writer_epoch"],
                "attached_session_id": None,
                "plan_hash": current["plan_hash"],
            }
            write_json_atomic(lease_path, updated)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return updated


def _read_lease_under_lock(lease_path: Path) -> dict[str, Any]:
    try:
        raw = lease_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return dict(LEASE_DEFAULTS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LeaseError(f"invalid JSON in lease {lease_path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise LeaseError(f"lease {lease_path} must be a JSON object")
    return _normalize_lease(data, lease_path)


def _normalize_lease(data: dict[str, Any], lease_path: Path) -> dict[str, Any]:
    out = dict(LEASE_DEFAULTS)
    out.update(data)
    epoch = out["writer_epoch"]
    if not isinstance(epoch, int) or isinstance(epoch, bool):
        raise LeaseError(f"lease {lease_path} writer_epoch must be an int, got {epoch!r}")
    attached = out["attached_session_id"]
    if attached is not None and not isinstance(attached, str):
        raise LeaseError(
            f"lease {lease_path} attached_session_id must be a string or null, got {attached!r}"
        )
    plan_hash = out["plan_hash"]
    if not isinstance(plan_hash, str):
        raise LeaseError(f"lease {lease_path} plan_hash must be a string, got {plan_hash!r}")
    return out


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# Silence the static checker — these are deliberate internal-API reuses.
_ = ZERO_HASH
_ = EventLogError
