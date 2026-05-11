"""Hash-chained task-run event log.

Sprint 1 — apex contract: every event appended to ``runs/<id>/events.jsonl``
is gated by a single :func:`fcntl.flock(LOCK_EX)` critical section that
re-reads the tail hash and the lease's ``writer_epoch`` *under the lock*
before computing the new prev-hash and writing the line. Tail CAS catches
concurrent appenders; epoch CAS catches stale writers that lost a takeover
race. The takeover event in ``events.jsonl`` is observability — the lock +
two CAS checks are the actual fence (see DEC-007).

``verify_chain`` is retained as an offline / audit primitive only. The
production hot path uses :func:`append_event_locked` which relies on the
tail-hash CAS for integrity (DEC-007 / FLAG-019 — events do not store a
``prev_hash`` field, so a v3-style "re-verify the last link" is not
expressible without reading the full chain).
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ZERO_HASH = "sha256:" + "0" * 64

LEASE_FILENAME = "lease.json"
EVENTS_FILENAME = "events.jsonl"

_TAIL_SEEK_INITIAL_WINDOW = 4096


class EventLogError(RuntimeError):
    """Raised when a task event log cannot be read or written."""


class StaleTailError(EventLogError):
    """Raised when the on-disk tail hash differs from the writer's expectation.

    Carries the conflicting hashes in ``.expected`` / ``.actual`` and the same
    values are interpolated into the message so log scrapers can pick them up.
    """

    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected: str = expected
        self.actual: str = actual
        super().__init__(
            f"stale tail: expected prev_hash={expected!r} but events.jsonl tail is {actual!r}"
        )


class StaleEpochError(EventLogError):
    """Raised when the on-disk ``writer_epoch`` differs from the writer's expectation.

    Carries the conflicting epochs in ``.expected`` / ``.actual``.
    """

    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected: int = expected
        self.actual: int = actual
        super().__init__(
            f"stale epoch: expected writer_epoch={expected!r} but lease.json holds {actual!r}"
        )


class NotWriterError(EventLogError):
    """Raised when a session attempts to append without holding the lease.

    Carries the offending session id and the actual lease writer in
    ``.session_id`` / ``.writer_id`` (the writer may be ``None`` for an
    orphan-pending lease).
    """

    def __init__(self, *, session_id: str, writer_id: str | None) -> None:
        self.session_id: str = session_id
        self.writer_id: str | None = writer_id
        super().__init__(
            f"session {session_id!r} is not the writer for this run "
            f"(lease.attached_session_id={writer_id!r})"
        )


def canonical_event_json(event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def append_event_locked(
    run_dir: str | Path,
    event: dict[str, Any],
    *,
    expected_writer_epoch: int,
    expected_prev_hash: str,
) -> dict[str, Any]:
    """Atomically append ``event`` to ``run_dir/events.jsonl``.

    Holds a single ``fcntl.flock(LOCK_EX)`` on the events file across:
      1. Tail re-read + CAS against ``expected_prev_hash`` → :class:`StaleTailError`.
      2. ``lease.json`` re-read + CAS against ``expected_writer_epoch`` →
         :class:`StaleEpochError`.
      3. New event hash computation, append, ``flush``+``os.fsync``.

    Raises :class:`StaleTailError` / :class:`StaleEpochError` on CAS failure
    with no retry. Callers (typically :class:`WriterContext`) decide whether
    to surface or rebind.
    """

    run_path = Path(run_dir)
    events_path = run_path / EVENTS_FILENAME
    lease_path = run_path / LEASE_FILENAME
    run_path.mkdir(parents=True, exist_ok=True)

    created = not events_path.exists()
    try:
        # ``a+b`` opens for append+read in binary mode; the OS guarantees the
        # write happens at end-of-file under POSIX append semantics, and we
        # additionally hold an exclusive flock across the full critical
        # section so concurrent writers serialize.
        with events_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                tail_hash = _read_tail_hash(handle)
                if tail_hash != expected_prev_hash:
                    raise StaleTailError(expected=expected_prev_hash, actual=tail_hash)

                actual_epoch = _read_lease_epoch(lease_path)
                if actual_epoch != expected_writer_epoch:
                    raise StaleEpochError(
                        expected=expected_writer_epoch, actual=actual_epoch
                    )

                stored = dict(event)
                stored.pop("hash", None)
                stored["hash"] = _event_hash(tail_hash, stored)

                line = (
                    json.dumps(
                        stored,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
                handle.seek(0, os.SEEK_END)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        if created:
            _fsync_dir(run_path)
    except (StaleTailError, StaleEpochError, NotWriterError):
        raise
    except OSError as exc:
        raise EventLogError(f"failed to append event to {events_path}: {exc}") from exc
    return stored


def append_event(path: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    """Test/migration only. Production code MUST use WriterContext.

    Reads the current ``(writer_epoch, tail_hash)`` from disk and calls
    :func:`append_event_locked` once. Raises :class:`StaleTailError` /
    :class:`StaleEpochError` / :class:`NotWriterError` with no retry.
    """

    events_path = Path(path)
    run_dir = events_path.parent
    lease_path = run_dir / LEASE_FILENAME
    # Read tail without taking the lock — append_event_locked re-reads under
    # the lock and CAS-checks. This pre-read just supplies an "expected"
    # value so the contract shape matches the locked helper.
    pre_tail = _peek_tail_hash(events_path)
    pre_epoch = _read_lease_epoch(lease_path)
    return append_event_locked(
        run_dir,
        event,
        expected_writer_epoch=pre_epoch,
        expected_prev_hash=pre_tail,
    )


def verify_chain(path: str | Path) -> tuple[bool, int, str | None]:
    """Walk ``events.jsonl`` end-to-end and verify every prev-hash link.

    Audit primitive: callers must NOT use this on the hot append path.
    The locked-append contract relies on tail-only CAS (DEC-007); this
    function exists so offline tooling can still detect mid-chain
    corruption.
    """

    events_path = Path(path)
    try:
        handle = events_path.open("r", encoding="utf-8")
    except FileNotFoundError:
        return True, -1, None
    except OSError as exc:
        return False, -1, f"failed to read {events_path}: {exc}"

    prev_hash = ZERO_HASH
    last_index = -1
    with handle:
        for index, line in enumerate(handle):
            if not line.endswith("\n"):
                return False, index, f"event log line {index + 1} is not newline-terminated"
            raw = line[:-1]
            if not raw:
                return False, index, f"event log line {index + 1} is empty"
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                return False, index, f"invalid JSON on event log line {index + 1}: {exc.msg}"
            if not isinstance(event, dict):
                return False, index, f"event log line {index + 1} is not an object"
            stored_hash = event.get("hash")
            if not isinstance(stored_hash, str):
                return False, index, f"event log line {index + 1} is missing hash"
            expected_hash = _event_hash(prev_hash, event)
            if stored_hash != expected_hash:
                return (
                    False,
                    index,
                    f"event log line {index + 1} hash mismatch: expected {expected_hash}, got {stored_hash}",
                )
            prev_hash = stored_hash
            last_index = index
    return True, last_index, None


def read_events(path: str | Path) -> list[dict[str, Any]]:
    events_path = Path(path)
    try:
        with events_path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise EventLogError(f"invalid JSON in {events_path}: {exc.msg}") from exc
    except OSError as exc:
        raise EventLogError(f"failed to read {events_path}: {exc}") from exc


def make_run_started_event(
    run_id: str,
    plan_hash: str,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "run_started",
        "plan_hash": plan_hash,
        "run_id": run_id,
        "ts": _utc_now_iso(),
    }
    if actor is not None:
        payload["actor"] = actor
    return payload


def make_run_aborted_event(run_id: str, *, reason: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "run_aborted",
        "run_id": run_id,
        "ts": _utc_now_iso(),
    }
    if reason is not None:
        payload["reason"] = reason
    return payload


def make_step_dispatched_event(plan_step_path: str, command: str) -> dict[str, Any]:
    return {
        "command": command,
        "kind": "step_dispatched",
        "plan_step_id": plan_step_path,
        "ts": _utc_now_iso(),
    }


def make_step_completed_event(plan_step_path: str, returncode: int) -> dict[str, Any]:
    return {
        "kind": "step_completed",
        "plan_step_id": plan_step_path,
        "returncode": returncode,
        "ts": _utc_now_iso(),
    }


def make_step_attested_event(
    plan_step_path: str,
    attestor_kind: str,
    attestor_id: str,
    evidence: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "attestor_id": attestor_id,
        "attestor_kind": attestor_kind,
        "evidence": list(evidence),
        "kind": "step_attested",
        "plan_step_id": plan_step_path,
        "ts": _utc_now_iso(),
    }


def make_nested_entered_event(plan_step_path: str, child_plan_hash: str) -> dict[str, Any]:
    return {
        "child_plan_hash": child_plan_hash,
        "kind": "nested_entered",
        "plan_step_id": plan_step_path,
        "ts": _utc_now_iso(),
    }


def make_nested_exited_event(plan_step_path: str, returncode: int) -> dict[str, Any]:
    return {
        "kind": "nested_exited",
        "plan_step_id": plan_step_path,
        "returncode": returncode,
        "ts": _utc_now_iso(),
    }


def make_produces_check_passed_event(
    plan_step_path: tuple[str, ...],
    produces_name: str,
    *,
    check_id: str,
    cas_sha256: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "check_id": check_id,
        "kind": "produces_check_passed",
        "plan_step_path": list(plan_step_path),
        "produces_name": produces_name,
        "ts": _utc_now_iso(),
    }
    if cas_sha256 is not None:
        event["cas_sha256"] = cas_sha256
    return event


def make_produces_check_failed_event(
    plan_step_path: tuple[str, ...],
    produces_name: str,
    *,
    check_id: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "kind": "produces_check_failed",
        "plan_step_path": list(plan_step_path),
        "produces_name": produces_name,
        "reason": reason,
        "ts": _utc_now_iso(),
    }


def make_iteration_started_event(
    plan_step_path: tuple[str, ...],
    iteration: int,
) -> dict[str, Any]:
    return {
        "iteration": int(iteration),
        "kind": "iteration_started",
        "plan_step_path": list(plan_step_path),
        "ts": _utc_now_iso(),
    }


def make_iteration_failed_event(
    plan_step_path: tuple[str, ...],
    iteration: int,
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "iteration": int(iteration),
        "kind": "iteration_failed",
        "plan_step_path": list(plan_step_path),
        "reason": reason,
        "ts": _utc_now_iso(),
    }


def make_iteration_exhausted_event(
    plan_step_path: tuple[str, ...],
    *,
    on_exhaust: str,
    max_iterations: int,
) -> dict[str, Any]:
    return {
        "kind": "iteration_exhausted",
        "max_iterations": int(max_iterations),
        "on_exhaust": on_exhaust,
        "plan_step_path": list(plan_step_path),
        "ts": _utc_now_iso(),
    }


def make_for_each_expanded_event(
    plan_step_path: tuple[str, ...],
    item_ids: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "item_ids": list(item_ids),
        "kind": "for_each_expanded",
        "plan_step_path": list(plan_step_path),
        "ts": _utc_now_iso(),
    }


def make_item_started_event(
    plan_step_path: tuple[str, ...],
    item_id: str,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "kind": "item_started",
        "plan_step_path": list(plan_step_path),
        "ts": _utc_now_iso(),
    }


def make_item_completed_event(
    plan_step_path: tuple[str, ...],
    item_id: str,
    returncode: int,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "kind": "item_completed",
        "plan_step_path": list(plan_step_path),
        "returncode": int(returncode),
        "ts": _utc_now_iso(),
    }


def make_item_attested_event(
    plan_step_path: tuple[str, ...],
    item_id: str,
    *,
    attestor_kind: str,
    attestor_id: str,
    evidence: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "attestor_id": attestor_id,
        "attestor_kind": attestor_kind,
        "evidence": list(evidence),
        "item_id": item_id,
        "kind": "item_attested",
        "plan_step_path": list(plan_step_path),
        "ts": _utc_now_iso(),
    }


def make_cursor_rewind_event(
    plan_step_path: tuple[str, ...],
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "kind": "cursor_rewind",
        "plan_step_path": list(plan_step_path),
        "reason": reason,
        "ts": _utc_now_iso(),
    }


def _event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    digest = hashlib.sha256((prev_hash + canonical_event_json(event)).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_tail_hash(handle) -> str:
    """Return the ``hash`` of the last non-empty JSONL line, or ZERO_HASH if empty.

    Caller must already hold an exclusive flock on ``handle``. Reads a
    chunked window from end-of-file, doubling until a newline is found or
    the whole file has been read (no fixed cap — single events larger than
    any starting window are still handled).
    """

    handle.seek(0, os.SEEK_END)
    file_size = handle.tell()
    if file_size == 0:
        return ZERO_HASH

    window = min(_TAIL_SEEK_INITIAL_WINDOW, file_size)
    while True:
        start = max(0, file_size - window)
        handle.seek(start)
        chunk = handle.read(file_size - start)
        last_newline = chunk.rfind(b"\n")
        if start == 0:
            # Whole file in chunk.
            trimmed = chunk.rstrip(b"\n")
            nl = trimmed.rfind(b"\n")
            last_line = trimmed[nl + 1 :] if nl != -1 else trimmed
            break
        if last_newline == -1:
            if window >= file_size:
                # Walked off the start without finding any newline — file is
                # one giant line. Use the whole chunk.
                last_line = chunk.rstrip(b"\n")
                break
            window = min(window * 2, file_size)
            continue
        # We have at least one newline in the chunk; the final line is what
        # comes after the *last* newline of the rstripped chunk.
        trimmed = chunk.rstrip(b"\n")
        if not trimmed:
            return ZERO_HASH
        nl = trimmed.rfind(b"\n")
        if nl == -1:
            # Chunk after rstrip has no newline — need more.
            if window >= file_size:
                last_line = trimmed
                break
            window = min(window * 2, file_size)
            continue
        last_line = trimmed[nl + 1 :]
        break

    if not last_line:
        return ZERO_HASH
    try:
        record = json.loads(last_line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EventLogError(f"events.jsonl tail is not valid JSON: {exc}") from exc
    tail_hash = record.get("hash") if isinstance(record, dict) else None
    if not isinstance(tail_hash, str):
        raise EventLogError("events.jsonl tail is missing 'hash' field")
    return tail_hash


def _peek_tail_hash(events_path: Path) -> str:
    """Best-effort read of the tail hash without acquiring the flock.

    Only the legacy :func:`append_event` wrapper uses this; the real CAS
    happens inside :func:`append_event_locked` under the lock.
    """

    if not events_path.exists():
        return ZERO_HASH
    with events_path.open("rb") as handle:
        return _read_tail_hash(handle)


def _read_lease_epoch(lease_path: Path) -> int:
    """Return ``lease.json``'s ``writer_epoch`` (default 0 when absent / malformed key).

    A missing lease file means the run pre-dates the Sprint 1 contract; the
    apex contract treats that as ``writer_epoch=0`` so the wrapper / legacy
    callers can still operate. Malformed JSON raises :class:`EventLogError`
    so corruption is loud.
    """

    try:
        raw = lease_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise EventLogError(f"failed to read lease {lease_path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EventLogError(f"invalid JSON in lease {lease_path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise EventLogError(f"lease {lease_path} must be a JSON object")
    epoch = data.get("writer_epoch", 0)
    if not isinstance(epoch, int) or isinstance(epoch, bool):
        raise EventLogError(
            f"lease {lease_path} writer_epoch must be an integer, got {epoch!r}"
        )
    return epoch


def _fsync_dir(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EBADF}:
            raise
    finally:
        if fd is not None:
            os.close(fd)
