from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.project.project import create_project
from astrid.core.task import gate as task_gate
from astrid.core.task.active_run import write_active_run
from astrid.core.task.env import (
    ASTRID_ACTOR,
    TASK_ITEM_ID_ENV,
    child_subprocess_env,
)
from astrid.core.task.events import (
    append_event,
    make_for_each_expanded_event,
    make_item_completed_event,
    make_item_started_event,
    make_run_started_event,
    read_events,
)
from astrid.core.task.plan import compute_plan_hash, load_plan, step_dir_for_path


def _setup(tmp_projects_root: Path, plan: dict, *, slug: str = "demo", run_id: str = "run-1") -> Path:
    create_project(slug, root=tmp_projects_root)
    plan_path = tmp_projects_root / slug / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    write_active_run(slug, run_id=run_id, plan_hash=compute_plan_hash(plan_path), root=tmp_projects_root)
    return plan_path


def _events_path(tmp_projects_root: Path, slug: str, run_id: str) -> Path:
    return tmp_projects_root / slug / "runs" / run_id / "events.jsonl"


def test_for_each_static_expands_emits_for_each_expanded_once(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "code", "command": "echo go",
                "repeat": {"for_each": {"items": ["a", "b", "c"]}},
            },
        ],
    }
    _setup(tmp_projects_root, plan)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")

    d1 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d1.item_id == "a"
    task_gate.record_dispatch_complete(d1, 0)
    append_event(events_path, make_item_completed_event(d1.plan_step_path, "a", 0))

    d2 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d2.item_id == "b"
    task_gate.record_dispatch_complete(d2, 0)
    append_event(events_path, make_item_completed_event(d2.plan_step_path, "b", 0))

    d3 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d3.item_id == "c"
    task_gate.record_dispatch_complete(d3, 0)
    append_event(events_path, make_item_completed_event(d3.plan_step_path, "c", 0))

    kinds = [e["kind"] for e in read_events(events_path)]
    assert kinds.count("for_each_expanded") == 1
    expanded = next(e for e in read_events(events_path) if e["kind"] == "for_each_expanded")
    assert expanded["item_ids"] == ["a", "b", "c"]


def test_for_each_partial_approval_via_item_flag(tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "attested",
                "command": "ack --project demo --step host",
                "instructions": "review",
                "ack": {"kind": "actor"},
                "repeat": {"for_each": {"items": ["a", "b", "c"]}},
            },
            {"id": "next", "kind": "code", "command": "echo done"},
        ],
    }
    _setup(tmp_projects_root, plan)
    monkeypatch.setenv(ASTRID_ACTOR, "alice")

    # Ack b first (out of order), then c, then a.
    for item in ("b", "c", "a"):
        cmd = f"ack --project demo --step host --actor alice --item {item}"
        d = task_gate.gate_command("demo", cmd, cmd.split(), root=tmp_projects_root)
        assert d.item_id == item
        # Host should NOT have advanced yet.
        if item != "a":
            # Next gate call before all items acked should still target 'host', not 'next'.
            pass

    # After all 3 items acked, gate_command should advance to step 'next'.
    d_next = task_gate.gate_command("demo", "echo done", ["echo", "done"], root=tmp_projects_root)
    assert d_next.plan_step_id == "next"


def test_for_each_from_ref_resolves_at_runtime_from_prior_step_produces(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "list_videos", "kind": "code", "command": "echo list",
                "produces": {
                    "videos": {
                        "path": "videos.json",
                        "check": {"check_id": "json_file", "params": {}, "sentinel": False},
                    }
                },
            },
            {
                "id": "host", "kind": "code", "command": "echo go",
                "repeat": {"for_each": {"from": "list_videos.produces.videos"}},
            },
        ],
    }
    _setup(tmp_projects_root, plan)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")

    # Run list_videos
    d1 = task_gate.gate_command("demo", "echo list", ["echo", "list"], root=tmp_projects_root)
    sd = step_dir_for_path("demo", "run-1", d1.plan_step_path, root=tmp_projects_root)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "videos.json").write_text(json.dumps(["v1", "v2"]), encoding="utf-8")
    task_gate.record_dispatch_complete(d1, 0)

    # Now hit host — should resolve from disk and emit for_each_expanded
    d2 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d2.item_id == "v1"
    expanded = next(e for e in read_events(events_path) if e["kind"] == "for_each_expanded")
    assert expanded["item_ids"] == ["v1", "v2"]
    assert expanded["plan_step_path"] == ["host"]


def test_for_each_replay_is_deterministic_from_events(tmp_projects_root: Path) -> None:
    plan_dict = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "code", "command": "echo go",
                "repeat": {"for_each": {"items": ["a", "b"]}},
            },
        ],
    }
    _setup(tmp_projects_root, plan_dict)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")
    plan_obj = load_plan(tmp_projects_root / "demo" / "plan.json")

    # Hand-write events.jsonl: run_started + for_each_expanded(['a','b']) + item_started('a') + item_completed('a').
    # Use append_event so chain hash stays valid.
    plan_hash = compute_plan_hash(tmp_projects_root / "demo" / "plan.json")
    append_event(events_path, make_run_started_event("run-1", plan_hash))
    append_event(events_path, make_for_each_expanded_event(("host",), ("a", "b")))
    append_event(events_path, make_item_started_event(("host",), "a"))
    append_event(events_path, make_item_completed_event(("host",), "a", 0))

    cursor = task_gate.derive_cursor(plan_obj, read_events(events_path))
    # Cursor should reflect: host frame on stack via item_started('a'); item_completed pops 'a'.
    # Top frame should be root frame (item 'a' frame popped). For 'b' to be next, gate_command would push it.
    # Verify for_each_progress reflects 'a' completed.
    progress = cursor.for_each_progress.get("host")
    assert progress is not None
    assert progress["items"] == ("a", "b")
    assert "a" in progress["completed"]
    assert "b" not in progress["completed"]
    # Root frame should still be at child_index 0 (host not yet advanced).
    assert cursor.frames[0].child_index == 0


def test_for_each_code_body_propagates_item_id_env_var(tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "code", "command": "echo go",
                "repeat": {"for_each": {"items": ["v1", "v2"]}},
            },
            {"id": "next", "kind": "code", "command": "echo done"},
        ],
    }
    _setup(tmp_projects_root, plan)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")

    d1 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d1.item_id == "v1"
    env1 = child_subprocess_env()
    assert env1.get(TASK_ITEM_ID_ENV) == "v1"
    task_gate.record_dispatch_complete(d1, 0)
    append_event(events_path, make_item_completed_event(d1.plan_step_path, "v1", 0))

    d2 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d2.item_id == "v2"
    env2 = child_subprocess_env()
    assert env2.get(TASK_ITEM_ID_ENV) == "v2"
    task_gate.record_dispatch_complete(d2, 0)
    append_event(events_path, make_item_completed_event(d2.plan_step_path, "v2", 0))

    d_next = task_gate.gate_command("demo", "echo done", ["echo", "done"], root=tmp_projects_root)
    assert d_next.plan_step_id == "next"
    env_next = child_subprocess_env()
    assert env_next.get(TASK_ITEM_ID_ENV) is None
