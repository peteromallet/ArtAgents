from __future__ import annotations

import json
from pathlib import Path

from artagents.core.task.events import (
    append_event,
    canonical_event_json,
    make_run_started_event,
    make_step_completed_event,
    make_step_dispatched_event,
    verify_chain,
)


def test_append_three_events_then_verify_chain(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"

    append_event(events_path, make_run_started_event("run-1", "sha256:" + "1" * 64))
    append_event(events_path, make_step_dispatched_event("step-1", "echo one"))
    append_event(events_path, make_step_completed_event("step-1", 0))

    assert verify_chain(events_path) == (True, 2, None)


def test_mutating_non_hash_field_rejects_chain(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    append_event(events_path, make_run_started_event("run-1", "sha256:" + "1" * 64))
    append_event(events_path, make_step_dispatched_event("step-1", "echo one"))
    append_event(events_path, make_step_completed_event("step-1", 0))

    lines = events_path.read_text(encoding="utf-8").splitlines()
    mutated = json.loads(lines[1])
    mutated["command"] = "echo edited"
    lines[1] = json.dumps(mutated, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, index, error = verify_chain(events_path)
    assert ok is False
    assert index == 1
    assert error


def test_truncated_mid_line_rejects_chain(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    append_event(events_path, make_run_started_event("run-1", "sha256:" + "1" * 64))
    append_event(events_path, make_step_dispatched_event("step-1", "echo one"))

    events_path.write_text(events_path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")

    ok, index, error = verify_chain(events_path)
    assert ok is False
    assert index == 1
    assert error


def test_canonical_event_json_is_key_order_stable() -> None:
    left = {"kind": "step_completed", "plan_step_id": "step-1", "returncode": 0, "hash": "ignored"}
    right = {"returncode": 0, "hash": "also-ignored", "plan_step_id": "step-1", "kind": "step_completed"}

    assert canonical_event_json(left) == canonical_event_json(right)
    assert "hash" not in canonical_event_json(left)
