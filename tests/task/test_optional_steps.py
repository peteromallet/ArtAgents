"""Sprint 5b: optional steps + step_skipped event tests.

Covers:
- Plan schema: optional flag, requires_ack incompatibility, serialization round-trip.
- cmd_skip on optional leaf / non-optional / group / for_each item.
- cmd_next --skip behaviour on optional vs mandatory leaves.
- Cursor advances past skipped leaves, groups, repeat.until bodies, and for_each items.
- Validator (events verify --strict) rejects skips of non-optional steps.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from astrid.core.project.project import create_project
from astrid.core.task.active_run import write_active_run
from astrid.core.task.events import (
    _event_hash,
    ZERO_HASH,
    canonical_event_json,
    make_item_skipped_event,
    make_step_skipped_event,
    read_events,
)
from astrid.core.task.gate import derive_cursor
from astrid.core.task.lifecycle import cmd_next
from astrid.core.task.lifecycle_skip import cmd_skip
from astrid.core.task.plan import (
    TaskPlan,
    TaskPlanError,
    compute_plan_hash,
    load_plan,
    Step,
)
from astrid.core.task.run_audit import cmd_events_verify


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_plan(plan_path: Path, payload: dict) -> None:
    plan_path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_project_with_plan(
    projects_root: Path, slug: str, run_id: str, plan_payload: dict
) -> tuple[Path, Path]:
    create_project(slug, root=projects_root)
    proj_root = projects_root / slug
    plan_path = proj_root / "plan.json"
    _write_plan(plan_path, plan_payload)
    run_dir = proj_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_hash = compute_plan_hash(plan_path)
    write_active_run(slug, run_id=run_id, plan_hash=plan_hash, root=projects_root)
    # Seed a run_started event so the gate can read a populated log.
    events_path = run_dir / "events.jsonl"
    run_started = {
        "kind": "run_started",
        "plan_hash": plan_hash,
        "run_id": run_id,
        "ts": "2026-01-01T00:00:00Z",
    }
    run_started["hash"] = _event_hash(ZERO_HASH, run_started)
    events_path.write_text(
        json.dumps(run_started, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return proj_root, run_dir


# ---------------------------------------------------------------------------
# schema invariants
# ---------------------------------------------------------------------------


def test_optional_with_requires_ack_rejected_at_load(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    _write_plan(
        plan_path,
        {
            "plan_id": "p1",
            "version": 2,
            "steps": [
                {
                    "id": "s1",
                    "adapter": "manual",
                    "command": "review",
                    "requires_ack": True,
                    "optional": True,
                    "ack": {"kind": "actor"},
                }
            ],
        },
    )
    with pytest.raises(TaskPlanError, match="optional=True is incompatible with requires_ack=True"):
        load_plan(plan_path)


def test_optional_with_requires_ack_rejected_at_construction() -> None:
    with pytest.raises(TaskPlanError, match="optional=True is incompatible with requires_ack=True"):
        Step(id="s1", adapter="local", command="echo", optional=True, requires_ack=True)


def test_optional_serializes_only_when_true(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    _write_plan(
        plan_path,
        {
            "plan_id": "p1",
            "version": 2,
            "steps": [
                {"id": "a", "adapter": "local", "command": "echo a", "optional": True},
                {"id": "b", "adapter": "local", "command": "echo b"},
            ],
        },
    )
    plan = load_plan(plan_path)
    assert plan.steps[0].optional is True
    assert plan.steps[1].optional is False
    d = plan.to_dict()
    assert d["steps"][0].get("optional") is True
    assert "optional" not in d["steps"][1]


def test_optional_allowed_on_group_step(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    _write_plan(
        plan_path,
        {
            "plan_id": "p1",
            "version": 2,
            "steps": [
                {
                    "id": "g",
                    "adapter": "local",
                    "optional": True,
                    "children": [
                        {"id": "leaf", "adapter": "local", "command": "echo"}
                    ],
                }
            ],
        },
    )
    plan = load_plan(plan_path)
    assert plan.steps[0].optional is True
    assert plan.steps[0].children is not None


# ---------------------------------------------------------------------------
# cmd_skip — leaf
# ---------------------------------------------------------------------------


def test_cmd_skip_advances_cursor_on_optional_leaf(tmp_projects_root: Path) -> None:
    slug = "optskip-leaf"
    run_id = "run-leaf"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {"id": "s1", "adapter": "local", "command": "echo s1", "optional": True},
                {"id": "s2", "adapter": "local", "command": "echo s2"},
            ],
        },
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_skip(["s1", "--project", slug], projects_root=tmp_projects_root)
    assert rc == 0, err.getvalue()
    events = read_events(run_dir / "events.jsonl")
    skip_events = [e for e in events if e.get("kind") == "step_skipped"]
    assert len(skip_events) == 1
    assert skip_events[0]["plan_step_path"] == ["s1"]
    # Cursor should now point at s2.
    plan = load_plan(proj_root / "plan.json")
    cursor = derive_cursor(plan, events)
    top = cursor.frames[-1]
    assert top.plan.steps[top.child_index].id == "s2"


def test_cmd_skip_rejects_non_optional_step(tmp_projects_root: Path) -> None:
    slug = "optskip-mandatory"
    run_id = "run-mand"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {"id": "s1", "adapter": "local", "command": "echo s1"},
            ],
        },
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_skip(["s1", "--project", slug], projects_root=tmp_projects_root)
    assert rc != 0
    assert "not optional" in err.getvalue()
    events = read_events(run_dir / "events.jsonl")
    assert not any(e.get("kind") == "step_skipped" for e in events)


def test_cmd_skip_rejects_non_frontier_path(tmp_projects_root: Path) -> None:
    slug = "optskip-future"
    run_id = "run-future"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {"id": "s1", "adapter": "local", "command": "echo s1"},
                {"id": "s2", "adapter": "local", "command": "echo s2", "optional": True},
            ],
        },
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_skip(["s2", "--project", slug], projects_root=tmp_projects_root)
    assert rc != 0
    assert "cursor frontier" in err.getvalue() or "does not match" in err.getvalue()


# ---------------------------------------------------------------------------
# cmd_skip — group step (entire subtree)
# ---------------------------------------------------------------------------


def test_cmd_skip_group_step_advances_past_subtree(tmp_projects_root: Path) -> None:
    slug = "optskip-group"
    run_id = "run-grp"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {
                    "id": "g",
                    "adapter": "local",
                    "optional": True,
                    "children": [
                        {"id": "c1", "adapter": "local", "command": "echo c1"},
                        {"id": "c2", "adapter": "local", "command": "echo c2"},
                    ],
                },
                {"id": "after", "adapter": "local", "command": "echo after"},
            ],
        },
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_skip(["g", "--project", slug], projects_root=tmp_projects_root)
    assert rc == 0, err.getvalue()
    events = read_events(run_dir / "events.jsonl")
    # No nested_entered, no step_dispatched for children.
    assert not any(e.get("kind") == "nested_entered" for e in events)
    assert not any(e.get("kind") == "step_dispatched" for e in events)
    # Cursor at root frame points at "after".
    plan = load_plan(proj_root / "plan.json")
    cursor = derive_cursor(plan, events)
    top = cursor.frames[-1]
    assert top.path_prefix == ()
    assert top.plan.steps[top.child_index].id == "after"


# ---------------------------------------------------------------------------
# cmd_next --skip
# ---------------------------------------------------------------------------


def test_cmd_next_skip_advances_optional_leaf(tmp_projects_root: Path) -> None:
    slug = "next-skip-leaf"
    run_id = "run-ns-leaf"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {"id": "s1", "adapter": "local", "command": "echo s1", "optional": True},
                {"id": "s2", "adapter": "local", "command": "echo s2"},
            ],
        },
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_next(["--project", slug, "--skip"], projects_root=tmp_projects_root)
    assert rc == 0, err.getvalue()
    events = read_events(run_dir / "events.jsonl")
    assert any(e.get("kind") == "step_skipped" and e.get("plan_step_path") == ["s1"] for e in events)


def test_cmd_next_skip_errors_on_mandatory_leaf(tmp_projects_root: Path) -> None:
    slug = "next-skip-mand"
    run_id = "run-ns-mand"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {"id": "s1", "adapter": "local", "command": "echo s1"},
            ],
        },
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_next(["--project", slug, "--skip"], projects_root=tmp_projects_root)
    assert rc != 0
    assert "not optional" in err.getvalue()
    events = read_events(run_dir / "events.jsonl")
    assert not any(e.get("kind") == "step_skipped" for e in events)


# ---------------------------------------------------------------------------
# for_each item skip
# ---------------------------------------------------------------------------


def test_for_each_item_skip_skips_one_item_others_run(tmp_projects_root: Path) -> None:
    slug = "feeach-skip"
    run_id = "run-fes"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {
                    "id": "process",
                    "adapter": "local",
                    "command": "echo item",
                    "repeat": {"for_each": {"items": ["a", "b", "c"]}},
                }
            ],
        },
    )
    out, err = io.StringIO(), io.StringIO()
    # First, an --item skip via cmd_skip targeting the host with --item b.
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_skip(
            ["process", "--project", slug, "--item", "b"],
            projects_root=tmp_projects_root,
        )
    assert rc == 0, err.getvalue()
    events = read_events(run_dir / "events.jsonl")
    item_skipped = [e for e in events if e.get("kind") == "item_skipped"]
    assert len(item_skipped) == 1
    assert item_skipped[0]["item_id"] == "b"
    # Cursor still points at "process" host — items a and c not yet done.
    plan = load_plan(proj_root / "plan.json")
    cursor = derive_cursor(plan, events)
    assert cursor.at_root_done is False


# ---------------------------------------------------------------------------
# repeat.until body skip
# ---------------------------------------------------------------------------


def test_repeat_until_body_skip_ends_loop_cleanly(tmp_projects_root: Path) -> None:
    slug = "rep-skip"
    run_id = "run-rs"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {
                    "id": "iter",
                    "adapter": "local",
                    "command": "echo iter",
                    "optional": True,
                    "repeat": {
                        "until": "verifier_passes",
                        "max_iterations": 3,
                        "on_exhaust": "fail",
                    },
                },
                {"id": "after", "adapter": "local", "command": "echo after"},
            ],
        },
    )
    # Synthesize an iteration_started event then a step_skipped on the body.
    # The body's path tuple == host's path tuple (single-step iteration body).
    from astrid.core.task.events import (
        append_event,
        make_iteration_started_event,
    )

    events_path = run_dir / "events.jsonl"
    append_event(events_path, make_iteration_started_event(("iter",), 1))
    append_event(
        events_path,
        make_step_skipped_event(
            "iter", actor_kind="agent", actor_id="cli", reason="test"
        ),
    )
    events = read_events(events_path)
    # No iteration_exhausted should appear.
    assert not any(e.get("kind") == "iteration_exhausted" for e in events)
    # Cursor should have advanced past "iter" to "after".
    plan = load_plan(proj_root / "plan.json")
    cursor = derive_cursor(plan, events)
    top = cursor.frames[-1]
    assert top.path_prefix == ()
    assert top.plan.steps[top.child_index].id == "after"


# ---------------------------------------------------------------------------
# Validator: events verify --strict rejects illegal skips
# ---------------------------------------------------------------------------


def test_events_verify_strict_rejects_skip_of_non_optional(
    tmp_path: Path, tmp_projects_root: Path
) -> None:
    slug = "skip-strict-bad"
    run_id = "run-skb"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {"id": "s1", "adapter": "local", "command": "echo s1"},
            ],
        },
    )
    # Synthesize an illegal step_skipped event on s1 (which is not optional).
    from astrid.core.task.events import append_event
    append_event(
        run_dir / "events.jsonl",
        make_step_skipped_event(
            "s1", actor_kind="agent", actor_id="cli", reason="illegal"
        ),
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_events_verify(
            ["--run", run_id, "--project", slug, "--strict"],
            projects_root=tmp_projects_root,
        )
    assert rc != 0
    assert "non-optional" in out.getvalue() or "non-optional" in err.getvalue()


def test_events_verify_strict_accepts_skip_of_optional(
    tmp_path: Path, tmp_projects_root: Path
) -> None:
    slug = "skip-strict-ok"
    run_id = "run-sko"
    proj_root, run_dir = _seed_project_with_plan(
        tmp_projects_root,
        slug,
        run_id,
        {
            "plan_id": "p",
            "version": 2,
            "steps": [
                {"id": "s1", "adapter": "local", "command": "echo s1", "optional": True},
            ],
        },
    )
    from astrid.core.task.events import append_event
    append_event(
        run_dir / "events.jsonl",
        make_step_skipped_event(
            "s1", actor_kind="agent", actor_id="cli", reason="ok"
        ),
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_events_verify(
            ["--run", run_id, "--project", slug, "--strict"],
            projects_root=tmp_projects_root,
        )
    assert rc == 0, out.getvalue() + err.getvalue()
