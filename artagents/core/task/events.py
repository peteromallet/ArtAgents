"""Hash-chained task-run event log."""

from __future__ import annotations

import errno
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ZERO_HASH = "sha256:" + "0" * 64


class EventLogError(RuntimeError):
    """Raised when a task event log cannot be read or written."""


def canonical_event_json(event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def append_event(path: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    events_path = Path(path)
    ok, _last_index, error = verify_chain(events_path)
    if not ok:
        raise EventLogError(error or f"invalid event hash chain in {events_path}")

    previous_events = read_events(events_path)
    prev_hash = previous_events[-1]["hash"] if previous_events else ZERO_HASH

    stored = dict(event)
    stored.pop("hash", None)
    stored["hash"] = _event_hash(prev_hash, stored)

    events_path.parent.mkdir(parents=True, exist_ok=True)
    created = not events_path.exists()
    try:
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(stored, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if created:
            _fsync_dir(events_path.parent)
    except OSError as exc:
        raise EventLogError(f"failed to append event to {events_path}: {exc}") from exc
    return stored


def verify_chain(path: str | Path) -> tuple[bool, int, str | None]:
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


def make_run_started_event(run_id: str, plan_hash: str) -> dict[str, Any]:
    return {
        "kind": "run_started",
        "plan_hash": plan_hash,
        "run_id": run_id,
        "ts": _utc_now_iso(),
    }


def make_step_dispatched_event(plan_step_id: str, command: str) -> dict[str, Any]:
    return {
        "command": command,
        "kind": "step_dispatched",
        "plan_step_id": plan_step_id,
        "ts": _utc_now_iso(),
    }


def make_step_completed_event(plan_step_id: str, returncode: int) -> dict[str, Any]:
    return {
        "kind": "step_completed",
        "plan_step_id": plan_step_id,
        "returncode": returncode,
        "ts": _utc_now_iso(),
    }


def _event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    digest = hashlib.sha256((prev_hash + canonical_event_json(event)).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
