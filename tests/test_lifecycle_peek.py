"""T18: peek_current_step direct unit tests covering empty events, repeat.until
iteration>=2, repeat.for_each item, nested. Parity assertion against
gate_command on a parallel events copy (FLAG-P5-003 — divergence here would
silently mis-print the cursor in cmd_next/cmd_status). Also verifies peek
does NOT write to events.jsonl (hash before/after).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from astrid.core.task.active_run import write_active_run
from astrid.core.task.env import (
    TASK_ITEM_ID_ENV,
    TASK_ITERATION_ENV,
    TASK_PROJECT_ENV,
    TASK_RUN_ID_ENV,
    TASK_STEP_ID_ENV,
)
from astrid.core.task.events import (
    append_event,
    make_iteration_failed_event,
    make_iteration_started_event,
    make_run_started_event,
)
from astrid.core.task.gate import (
    PeekResult,
    gate_command,
    peek_current_step,
)
from astrid.core.task.plan import (
    AckRule,
    AttestedStep,
    CodeStep,
    NestedStep,
    RepeatForEach,
    RepeatUntil,
    TaskPlan,
    compute_plan_hash,
)


def _clear_task_env() -> None:
    """gate_command's _dispatch_code calls apply_task_run_env which sets
    TASK_RUN_ID_ENV / TASK_PROJECT_ENV / etc. via raw os.environ writes.
    The conftest tmp_projects_root fixture's explicit teardown delenv
    would otherwise capture these as the 'original' values for monkeypatch's
    undo stack, leaking them across tests. Pop directly so monkeypatch's
    teardown sees the env back at its pre-test absent state.
    """
    for var in (TASK_RUN_ID_ENV, TASK_PROJECT_ENV, TASK_STEP_ID_ENV, TASK_ITEM_ID_ENV, TASK_ITERATION_ENV):
        os.environ.pop(var, None)


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stage_run(
    tmp_projects_root: Path, plan: TaskPlan, slug: str, run_id: str
) -> Path:
    """Create projects/<slug>/{plan.json,active_run.json,runs/<run-id>/events.jsonl}.
    Returns events_path. run_started event written.
    """
    proj = tmp_projects_root / slug
    proj.mkdir(parents=True, exist_ok=True)
    plan_path = proj / "plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    plan_hash = compute_plan_hash(plan_path)
    write_active_run(slug, run_id=run_id, plan_hash=plan_hash, root=tmp_projects_root)
    runs_dir = proj / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    events_path = runs_dir / "events.jsonl"
    append_event(events_path, make_run_started_event(run_id, plan_hash, actor="bob"))
    return events_path


def test_peek_empty_events_returns_first_step(tmp_projects_root: Path) -> None:
    plan = TaskPlan(plan_id="p", version=1, steps=(
        CodeStep(id="step_a", command="echo a"),
        CodeStep(id="step_b", command="echo b"),
    ))
    events_path = _stage_run(tmp_projects_root, plan, "demo", "r1")
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    sz_before = _hash_file(events_path)
    peek = peek_current_step(plan, events, "demo", project_root=tmp_projects_root/"demo", run_id="r1")
    assert isinstance(peek, PeekResult)
    assert not peek.exhausted
    assert peek.step.id == "step_a"
    assert peek.path_tuple == ("step_a",)
    assert peek.iteration is None and peek.item_id is None
    assert _hash_file(events_path) == sz_before


def test_peek_iteration_ge_2(tmp_projects_root: Path) -> None:
    plan = TaskPlan(plan_id="p", version=1, steps=(
        AttestedStep(
            id="review", command="r.sh", instructions="ok", ack=AckRule(kind="actor"),
            repeat=RepeatUntil(condition="user_approves", max_iterations=3, on_exhaust="fail"),
        ),
    ))
    events_path = _stage_run(tmp_projects_root, plan, "demo", "r2")
    # Simulate iteration 1 attempted+failed.
    append_event(events_path, make_iteration_started_event(("review",), 1))
    append_event(events_path, make_iteration_failed_event(("review",), 1, reason="iterate_feedback"))
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    before = _hash_file(events_path)
    peek = peek_current_step(plan, events, "demo", project_root=tmp_projects_root/"demo", run_id="r2")
    assert not peek.exhausted
    assert peek.step.id == "review"
    assert peek.iteration == 2, "next iteration after iter 1 failed"
    assert _hash_file(events_path) == before


def test_peek_for_each_item(tmp_projects_root: Path) -> None:
    plan = TaskPlan(plan_id="p", version=1, steps=(
        AttestedStep(
            id="review_each", command="r.sh", instructions="check", ack=AckRule(kind="actor"),
            repeat=RepeatForEach(items_source="static", items=("a", "b", "c")),
        ),
    ))
    events_path = _stage_run(tmp_projects_root, plan, "demo", "r3")
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    before = _hash_file(events_path)
    peek = peek_current_step(plan, events, "demo", project_root=tmp_projects_root/"demo", run_id="r3")
    assert not peek.exhausted
    # Body of the for_each frame surfaces; path_tuple == host path; item_id is "a".
    assert peek.path_tuple == ("review_each",)
    assert peek.item_id == "a"
    assert _hash_file(events_path) == before


def test_peek_inside_nested_plan(tmp_projects_root: Path) -> None:
    inner = TaskPlan(plan_id="inner", version=1, steps=(
        CodeStep(id="inner_step", command="echo inner"),
    ))
    plan = TaskPlan(plan_id="root", version=1, steps=(
        NestedStep(id="outer", plan=inner),
    ))
    events_path = _stage_run(tmp_projects_root, plan, "demo", "r4")
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    before = _hash_file(events_path)
    peek = peek_current_step(plan, events, "demo", project_root=tmp_projects_root/"demo", run_id="r4")
    # Peek descends through NestedStep wrapper and surfaces the inner CodeStep.
    assert not peek.exhausted
    assert peek.path_tuple == ("outer", "inner_step")
    assert peek.step.id == "inner_step"
    assert _hash_file(events_path) == before


def test_peek_parity_with_gate_command_on_parallel_events(tmp_projects_root: Path) -> None:
    """FLAG-P5-003 load-bearing parity test.

    peek runs first; gate_command runs second on the same on-disk events
    (peek doesn't write). The two implementations must agree on the leaf
    plan_step_path.
    """
    inner = TaskPlan(plan_id="inner", version=1, steps=(
        CodeStep(id="inner_step", command="echo hello"),
    ))
    plan = TaskPlan(plan_id="root", version=1, steps=(
        NestedStep(id="outer", plan=inner),
    ))
    events_path = _stage_run(tmp_projects_root, plan, "demo", "r5")
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    peek = peek_current_step(plan, events, "demo", project_root=tmp_projects_root/"demo", run_id="r5")
    # gate_command dispatches the inner_step's command through the gate; it
    # auto-traverses into the nested frame and the resulting decision's
    # plan_step_path must equal peek.path_tuple.
    decision = gate_command("demo", "echo hello", ["echo", "hello"], root=tmp_projects_root)
    assert decision.active is True
    assert decision.plan_step_path == peek.path_tuple
    # gate's apply_task_run_env writes raw os.environ entries; clear them so
    # monkeypatch's teardown sees the env back at its pre-test absent state.
    _clear_task_env()


def test_peek_exhausted_returns_step_none(tmp_projects_root: Path) -> None:
    plan = TaskPlan(plan_id="p", version=1, steps=(
        CodeStep(id="solo", command="echo solo"),
    ))
    events_path = _stage_run(tmp_projects_root, plan, "demo", "r6")
    # Mark solo step complete via a step_completed event so cursor advances past root.
    from astrid.core.task.events import make_step_completed_event
    append_event(events_path, make_step_completed_event("solo", 0))
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    peek = peek_current_step(plan, events, "demo", project_root=tmp_projects_root/"demo", run_id="r6")
    assert peek.exhausted is True
    assert peek.step is None
