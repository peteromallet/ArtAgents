from __future__ import annotations

import json
from pathlib import Path

import pytest

from artagents.core.project.project import create_project
from artagents.core.task.active_run import write_active_run
from artagents.core.task.events import (
    append_event,
    make_run_started_event,
    read_events,
    verify_chain,
)
from artagents.core.task.gate import (
    TaskRunGateError,
    derive_cursor,
    gate_command,
    record_dispatch_complete,
)
from artagents.core.task.plan import compute_plan_hash, load_plan


def _write_nested_plan(tmp_projects_root: Path, plan_payload: dict) -> Path:
    create_project("demo", root=tmp_projects_root)
    plan_path = tmp_projects_root / "demo" / "plan.json"
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")
    plan_hash = compute_plan_hash(plan_path)
    write_active_run("demo", run_id="run-1", plan_hash=plan_hash, root=tmp_projects_root)
    events_path = tmp_projects_root / "demo" / "runs" / "run-1" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    append_event(events_path, make_run_started_event("run-1", plan_hash))
    return plan_path


def _parent_with_two_children() -> dict:
    return {
        "plan_id": "p1",
        "version": 1,
        "steps": [
            {"id": "s1", "command": "echo s1"},
            {
                "id": "s2",
                "kind": "nested",
                "plan": {
                    "plan_id": "c",
                    "version": 1,
                    "steps": [
                        {"id": "c1", "command": "echo c1"},
                        {"id": "c2", "command": "echo c2"},
                    ],
                },
            },
            {"id": "s3", "command": "echo s3"},
        ],
    }


def test_nested_plan_walk_emits_path_qualified_events(tmp_projects_root: Path) -> None:
    plan_path = _write_nested_plan(tmp_projects_root, _parent_with_two_children())
    events_path = tmp_projects_root / "demo" / "runs" / "run-1" / "events.jsonl"

    d1 = gate_command("demo", "echo s1", [], root=tmp_projects_root)
    assert d1.plan_step_id == "s1"
    record_dispatch_complete(d1, 0)

    d2 = gate_command("demo", "echo c1", [], root=tmp_projects_root)
    assert d2.plan_step_id == "s2/c1"
    record_dispatch_complete(d2, 0)

    d3 = gate_command("demo", "echo c2", [], root=tmp_projects_root)
    assert d3.plan_step_id == "s2/c2"
    record_dispatch_complete(d3, 0)

    d4 = gate_command("demo", "echo s3", [], root=tmp_projects_root)
    assert d4.plan_step_id == "s3"
    record_dispatch_complete(d4, 0)

    # Note: nested_exited("s2") was already emitted lazily when we transitioned from
    # c2 -> s3 at d4's gate call (top frame exhausted on entry-loop traversal).
    events = read_events(events_path)
    kinds_paths = [(e["kind"], e.get("plan_step_id")) for e in events if e["kind"] != "run_started"]

    assert ("step_dispatched", "s1") in kinds_paths
    assert ("step_completed", "s1") in kinds_paths
    assert ("nested_entered", "s2") in kinds_paths
    assert ("step_dispatched", "s2/c1") in kinds_paths
    assert ("step_completed", "s2/c1") in kinds_paths
    assert ("step_dispatched", "s2/c2") in kinds_paths
    assert ("step_completed", "s2/c2") in kinds_paths
    assert ("nested_exited", "s2") in kinds_paths
    assert ("step_dispatched", "s3") in kinds_paths

    nested_entered = next(e for e in events if e["kind"] == "nested_entered")
    assert nested_entered["child_plan_hash"].startswith("sha256:")
    nested_exited = next(e for e in events if e["kind"] == "nested_exited")
    assert nested_exited["returncode"] == 0

    assert verify_chain(events_path)[0] is True


def test_nested_two_level_path_g1(tmp_projects_root: Path) -> None:
    plan_payload = {
        "plan_id": "p1",
        "version": 1,
        "steps": [
            {"id": "s1", "command": "echo s1"},
            {
                "id": "s2",
                "kind": "nested",
                "plan": {
                    "plan_id": "c",
                    "version": 1,
                    "steps": [
                        {"id": "c1", "command": "echo c1"},
                        {
                            "id": "c2",
                            "kind": "nested",
                            "plan": {
                                "plan_id": "g",
                                "version": 1,
                                "steps": [{"id": "g1", "command": "echo g1"}],
                            },
                        },
                    ],
                },
            },
        ],
    }
    _write_nested_plan(tmp_projects_root, plan_payload)
    events_path = tmp_projects_root / "demo" / "runs" / "run-1" / "events.jsonl"

    d = gate_command("demo", "echo s1", [], root=tmp_projects_root)
    assert d.plan_step_id == "s1"
    record_dispatch_complete(d, 0)

    d = gate_command("demo", "echo c1", [], root=tmp_projects_root)
    assert d.plan_step_id == "s2/c1"
    record_dispatch_complete(d, 0)

    d = gate_command("demo", "echo g1", [], root=tmp_projects_root)
    assert d.plan_step_id == "s2/c2/g1"
    record_dispatch_complete(d, 0)

    # Auto-emit deferred nested_exited events on the next gate call (plan exhausted).
    with pytest.raises(TaskRunGateError):
        gate_command("demo", "echo anything", [], root=tmp_projects_root)

    events = read_events(events_path)
    enter_paths = [e["plan_step_id"] for e in events if e["kind"] == "nested_entered"]
    exit_paths = [e["plan_step_id"] for e in events if e["kind"] == "nested_exited"]
    assert enter_paths == ["s2", "s2/c2"]
    assert exit_paths == ["s2/c2", "s2"]
    assert verify_chain(events_path)[0] is True


def test_sibling_subtrees_disambiguate_reused_leaf_ids(tmp_projects_root: Path) -> None:
    plan_payload = {
        "plan_id": "p1",
        "version": 1,
        "steps": [
            {
                "id": "s1",
                "kind": "nested",
                "plan": {
                    "plan_id": "c1",
                    "version": 1,
                    "steps": [{"id": "c1", "command": "echo a"}],
                },
            },
            {
                "id": "s2",
                "kind": "nested",
                "plan": {
                    "plan_id": "c2",
                    "version": 1,
                    "steps": [{"id": "c1", "command": "echo b"}],
                },
            },
        ],
    }
    _write_nested_plan(tmp_projects_root, plan_payload)

    d1 = gate_command("demo", "echo a", [], root=tmp_projects_root)
    assert d1.plan_step_id == "s1/c1"
    record_dispatch_complete(d1, 0)

    d2 = gate_command("demo", "echo b", [], root=tmp_projects_root)
    assert d2.plan_step_id == "s2/c1"


def test_mutating_child_changes_parent_compute_plan_hash(tmp_path: Path) -> None:
    base_payload = _parent_with_two_children()
    base_path = tmp_path / "a" / "plan.json"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text(json.dumps(base_payload), encoding="utf-8")
    base_hash = compute_plan_hash(base_path)

    mutated = json.loads(json.dumps(base_payload))
    mutated["steps"][1]["plan"]["steps"][0]["command"] = "echo changed"
    mutated_path = tmp_path / "b" / "plan.json"
    mutated_path.parent.mkdir(parents=True, exist_ok=True)
    mutated_path.write_text(json.dumps(mutated), encoding="utf-8")
    mutated_hash = compute_plan_hash(mutated_path)

    assert base_hash != mutated_hash


def test_derive_cursor_partial_replay_resumes_mid_nested_walk(
    tmp_projects_root: Path,
) -> None:
    plan_path = _write_nested_plan(tmp_projects_root, _parent_with_two_children())
    plan = load_plan(plan_path)

    # Walk part-way: complete s1, enter s2, complete c1.
    d1 = gate_command("demo", "echo s1", [], root=tmp_projects_root)
    record_dispatch_complete(d1, 0)
    d2 = gate_command("demo", "echo c1", [], root=tmp_projects_root)
    record_dispatch_complete(d2, 0)

    events_path = tmp_projects_root / "demo" / "runs" / "run-1" / "events.jsonl"
    events = read_events(events_path)
    cursor = derive_cursor(plan, events)

    # Frame stack should be at parent[s2] -> child frame with child_index=1 (c2 next).
    assert len(cursor.frames) == 2
    assert cursor.frames[0].child_index == 1  # parent advanced past s1
    assert cursor.frames[1].child_index == 1  # child advanced past c1

    # Continuation works correctly post-resume.
    d3 = gate_command("demo", "echo c2", [], root=tmp_projects_root)
    assert d3.plan_step_id == "s2/c2"


def test_nested_entered_event_carries_child_plan_hash(tmp_projects_root: Path) -> None:
    _write_nested_plan(tmp_projects_root, _parent_with_two_children())
    events_path = tmp_projects_root / "demo" / "runs" / "run-1" / "events.jsonl"

    # First gate dispatches s1 -- no nested entry yet.
    d1 = gate_command("demo", "echo s1", [], root=tmp_projects_root)
    record_dispatch_complete(d1, 0)
    # Second gate auto-emits nested_entered for s2 before dispatching c1.
    gate_command("demo", "echo c1", [], root=tmp_projects_root)

    events = read_events(events_path)
    entered = next(e for e in events if e["kind"] == "nested_entered")
    assert entered["plan_step_id"] == "s2"
    assert entered["child_plan_hash"].startswith("sha256:")
    assert len(entered["child_plan_hash"]) == len("sha256:") + 64


def test_plan_exhausted_at_root_after_nested_walk_rejects(tmp_projects_root: Path) -> None:
    _write_nested_plan(tmp_projects_root, _parent_with_two_children())

    for command, expected in [
        ("echo s1", "s1"),
        ("echo c1", "s2/c1"),
        ("echo c2", "s2/c2"),
        ("echo s3", "s3"),
    ]:
        d = gate_command("demo", command, [], root=tmp_projects_root)
        assert d.plan_step_id == expected
        record_dispatch_complete(d, 0)

    with pytest.raises(TaskRunGateError) as exc:
        gate_command("demo", "echo anything", [], root=tmp_projects_root)
    assert exc.value.recovery == "artagents abort --project demo"
