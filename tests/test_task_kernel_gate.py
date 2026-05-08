from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.project.project import create_project
from astrid.core.task.active_run import write_active_run
from astrid.core.task.events import (
    append_event,
    make_run_started_event,
    make_step_completed_event,
    make_step_dispatched_event,
    read_events,
    verify_chain,
)
from astrid.core.task.gate import TaskRunGateError, gate_command, record_dispatch_complete
from astrid.core.task.plan import compute_plan_hash


def test_five_event_hash_chain_append_verify_round_trip(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    append_event(events_path, make_run_started_event("run-1", "sha256:" + "1" * 64))
    append_event(events_path, make_step_dispatched_event("step-1", "echo one"))
    append_event(events_path, make_step_completed_event("step-1", 0))
    append_event(events_path, make_step_dispatched_event("step-2", "echo two"))
    append_event(events_path, make_step_completed_event("step-2", 0))

    assert verify_chain(events_path) == (True, 4, None)


def test_plan_hash_mismatch_rejects_with_abort_recovery(tmp_projects_root: Path) -> None:
    command = _write_plan(tmp_projects_root, [{"id": "step-1", "command": "echo one"}])[0]
    write_active_run("demo", run_id="run-1", plan_hash="sha256:" + "1" * 64, root=tmp_projects_root)

    with pytest.raises(TaskRunGateError) as exc_info:
        gate_command("demo", command, [], root=tmp_projects_root)

    assert exc_info.value.reason == "plan.json hash does not match active_run.json pin"
    assert exc_info.value.recovery == "astrid abort --project demo"


def test_chain_integrity_failure_rejects_with_abort_recovery(tmp_projects_root: Path) -> None:
    command = _write_plan(tmp_projects_root, [{"id": "step-1", "command": "echo one"}])[0]
    _activate_plan(tmp_projects_root)
    decision = gate_command("demo", command, [], root=tmp_projects_root)
    lines = decision.events_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["command"] = "echo edited"
    lines[0] = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    decision.events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(TaskRunGateError) as exc_info:
        gate_command("demo", command, [], root=tmp_projects_root)

    assert exc_info.value.recovery == "astrid abort --project demo"


def test_non_canonical_command_rejects_with_next_recovery(tmp_projects_root: Path) -> None:
    _write_plan(tmp_projects_root, [{"id": "step-1", "command": "echo one"}])
    _activate_plan(tmp_projects_root)

    with pytest.raises(TaskRunGateError) as exc_info:
        gate_command("demo", "echo edited", [], root=tmp_projects_root)

    assert exc_info.value.reason == "incoming command does not match plan[cursor]"
    assert exc_info.value.recovery == "astrid next --project demo"


def test_inactive_gate_is_transparent_and_writes_no_events(tmp_projects_root: Path) -> None:
    decision = gate_command("demo", "echo one", [], root=tmp_projects_root)

    assert decision.active is False
    assert not (tmp_projects_root / "demo" / "runs").exists()


def test_cursor_advances_after_record_dispatch_complete(tmp_projects_root: Path) -> None:
    first, second = _write_plan(
        tmp_projects_root,
        [{"id": "step-1", "command": "echo one"}, {"id": "step-2", "command": "echo two"}],
    )
    _activate_plan(tmp_projects_root)

    first_decision = gate_command("demo", first, [], root=tmp_projects_root)
    record_dispatch_complete(first_decision, 0)
    second_decision = gate_command("demo", second, [], root=tmp_projects_root)

    assert second_decision.plan_step_id == "step-2"
    assert [event["kind"] for event in read_events(second_decision.events_path)] == [
        "step_dispatched",
        "step_completed",
        "step_dispatched",
    ]


def test_plan_exhausted_rejects_with_abort_recovery(tmp_projects_root: Path) -> None:
    command = _write_plan(tmp_projects_root, [{"id": "step-1", "command": "echo one"}])[0]
    _activate_plan(tmp_projects_root)
    decision = gate_command("demo", command, [], root=tmp_projects_root)
    record_dispatch_complete(decision, 0)

    with pytest.raises(TaskRunGateError) as exc_info:
        gate_command("demo", command, [], root=tmp_projects_root)

    assert exc_info.value.recovery == "astrid abort --project demo"


def test_reentry_after_fresh_dispatch_does_not_double_append(tmp_projects_root: Path) -> None:
    command = _write_plan(tmp_projects_root, [{"id": "step-1", "command": "echo one"}])[0]
    _activate_plan(tmp_projects_root)

    fresh = gate_command("demo", command, [], root=tmp_projects_root)
    reentry = gate_command("demo", command, [], root=tmp_projects_root, reentry=True)

    assert reentry.reentry is True
    assert reentry.plan_step_id == "step-1"
    events = read_events(fresh.events_path)
    assert [event["kind"] for event in events] == ["step_dispatched"]


def test_phase_1_top_level_events_keep_bare_id_payload_shape(tmp_projects_root: Path) -> None:
    """Regression: Phase 1 plans (no nested) must emit bare-id plan_step_id payloads."""
    first, second = _write_plan(
        tmp_projects_root,
        [{"id": "s1", "command": "echo one"}, {"id": "s2", "command": "echo two"}],
    )
    _activate_plan(tmp_projects_root)

    d1 = gate_command("demo", first, [], root=tmp_projects_root)
    record_dispatch_complete(d1, 0)
    d2 = gate_command("demo", second, [], root=tmp_projects_root)
    record_dispatch_complete(d2, 0)

    events = read_events(d2.events_path)
    leaf_events = [e for e in events if e["kind"] in ("step_dispatched", "step_completed")]
    for event in leaf_events:
        # Phase 1 wire shape: top-level steps use the bare id, no slashes.
        assert "/" not in event["plan_step_id"]
    ids = sorted({e["plan_step_id"] for e in leaf_events})
    assert ids == ["s1", "s2"]
    # No nested_entered/nested_exited events for a flat Phase-1 plan.
    assert not any(e["kind"] in ("nested_entered", "nested_exited") for e in events)


def _write_plan(tmp_projects_root: Path, steps: list[dict[str, str]]) -> tuple[str, ...]:
    create_project("demo", root=tmp_projects_root)
    plan_path = tmp_projects_root / "demo" / "plan.json"
    plan_path.write_text(json.dumps({"plan_id": "p1", "version": 1, "steps": steps}), encoding="utf-8")
    return tuple(step["command"] for step in steps)


def _activate_plan(tmp_projects_root: Path) -> None:
    plan_path = tmp_projects_root / "demo" / "plan.json"
    write_active_run("demo", run_id="run-1", plan_hash=compute_plan_hash(plan_path), root=tmp_projects_root)
