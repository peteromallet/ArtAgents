from __future__ import annotations

import json
from pathlib import Path

import pytest

from artagents.core.project.project import create_project
from artagents.core.task import gate as task_gate
from artagents.core.task.active_run import write_active_run
from artagents.core.task.env import ARTAGENTS_ACTOR, TASK_ITERATION_ENV, child_subprocess_env
from artagents.core.task.events import read_events
from artagents.core.task.plan import compute_plan_hash, step_dir_for_path


def _setup(tmp_projects_root: Path, plan: dict, *, slug: str = "demo", run_id: str = "run-1") -> Path:
    create_project(slug, root=tmp_projects_root)
    plan_path = tmp_projects_root / slug / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    write_active_run(slug, run_id=run_id, plan_hash=compute_plan_hash(plan_path), root=tmp_projects_root)
    return plan_path


def _events_path(tmp_projects_root: Path, slug: str, run_id: str) -> Path:
    return tmp_projects_root / slug / "runs" / run_id / "events.jsonl"


def test_repeat_until_user_approves_appends_cumulative_feedback(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "attested",
                "command": "ack --project demo --step host",
                "instructions": "review",
                "ack": {"kind": "actor"},
                "repeat": {"until": "user_approves", "max_iterations": 3, "on_exhaust": "fail"},
            },
            {"id": "next", "kind": "code", "command": "echo done"},
        ],
    }
    _setup(tmp_projects_root, plan)
    monkeypatch.setenv(ARTAGENTS_ACTOR, "alice")

    # Iter 1: iterate with 'more energy'
    cmd1 = 'ack --project demo --step host --actor alice --evidence iterate_feedback=more_energy'
    d1 = task_gate.gate_command("demo", cmd1, cmd1.split(), root=tmp_projects_root)
    assert d1.iteration == 1
    feedback_path1 = step_dir_for_path("demo", "run-1", ("host",), iteration=1, root=tmp_projects_root) / "feedback.json"
    assert feedback_path1.exists()
    assert json.loads(feedback_path1.read_text(encoding="utf-8")) == ["more_energy"]

    # Iter 2: iterate with 'less reverb' — cumulative feedback grows
    cmd2 = 'ack --project demo --step host --actor alice --evidence iterate_feedback=less_reverb'
    d2 = task_gate.gate_command("demo", cmd2, cmd2.split(), root=tmp_projects_root)
    assert d2.iteration == 2
    feedback_path2 = step_dir_for_path("demo", "run-1", ("host",), iteration=2, root=tmp_projects_root) / "feedback.json"
    assert feedback_path2.exists()
    assert json.loads(feedback_path2.read_text(encoding="utf-8")) == ["more_energy", "less_reverb"]

    # Iter 3: approve (no iterate_feedback evidence) — host advances
    cmd3 = 'ack --project demo --step host --actor alice'
    d3 = task_gate.gate_command("demo", cmd3, cmd3.split(), root=tmp_projects_root)
    assert d3.iteration == 3

    # Next gate_command should now land on 'next'
    d_next = task_gate.gate_command("demo", "echo done", ["echo", "done"], root=tmp_projects_root)
    assert d_next.plan_step_id == "next"

    kinds = [e["kind"] for e in read_events(_events_path(tmp_projects_root, "demo", "run-1"))]
    # Two iteration_failed events (iter1 + iter2), three iteration_started events.
    assert kinds.count("iteration_failed") == 2
    assert kinds.count("iteration_started") == 3
    assert kinds.count("step_attested") == 3


def test_repeat_until_verifier_passes_advances_when_check_passes(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "code", "command": "echo go",
                "produces": {"out": {"path": "out.json", "check": {"check_id": "json_file", "params": {}, "sentinel": False}}},
                "repeat": {"until": "verifier_passes", "max_iterations": 2, "on_exhaust": "fail"},
            },
            {"id": "next", "kind": "code", "command": "echo done"},
        ],
    }
    _setup(tmp_projects_root, plan)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")

    d1 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d1.iteration == 1
    sd1 = step_dir_for_path("demo", "run-1", d1.plan_step_path, iteration=1, root=tmp_projects_root)
    sd1.mkdir(parents=True, exist_ok=True)
    (sd1 / "out.json").write_text("garbage", encoding="utf-8")
    task_gate.record_dispatch_complete(d1, 0)

    d2 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert d2.iteration == 2
    sd2 = step_dir_for_path("demo", "run-1", d2.plan_step_path, iteration=2, root=tmp_projects_root)
    sd2.mkdir(parents=True, exist_ok=True)
    (sd2 / "out.json").write_text('{"ok": 1}', encoding="utf-8")
    task_gate.record_dispatch_complete(d2, 0)

    d_next = task_gate.gate_command("demo", "echo done", ["echo", "done"], root=tmp_projects_root)
    assert d_next.plan_step_id == "next"

    kinds = [e["kind"] for e in read_events(events_path)]
    assert kinds.count("iteration_failed") == 1
    assert kinds.count("produces_check_failed") == 1
    assert kinds.count("produces_check_passed") == 1


def test_repeat_until_max_exhaust_fail_raises(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "code", "command": "echo go",
                "produces": {"out": {"path": "out.json", "check": {"check_id": "json_file", "params": {}, "sentinel": False}}},
                "repeat": {"until": "verifier_passes", "max_iterations": 2, "on_exhaust": "fail"},
            },
        ],
    }
    _setup(tmp_projects_root, plan)
    events_path = _events_path(tmp_projects_root, "demo", "run-1")

    for i in (1, 2):
        d = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
        sd = step_dir_for_path("demo", "run-1", d.plan_step_path, iteration=i, root=tmp_projects_root)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "out.json").write_text("garbage", encoding="utf-8")
        task_gate.record_dispatch_complete(d, 0)

    with pytest.raises(task_gate.TaskRunGateError) as excinfo:
        task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert "max_iterations exhausted" in excinfo.value.reason
    assert excinfo.value.recovery == "artagents abort --project demo"

    # Subsequent gate call should re-raise
    with pytest.raises(task_gate.TaskRunGateError) as excinfo2:
        task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert "max_iterations exhausted" in excinfo2.value.reason

    kinds = [e["kind"] for e in read_events(events_path)]
    assert kinds.count("iteration_exhausted") == 1


def test_repeat_until_max_exhaust_escalate_parks_for_attested_override(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "code", "command": "echo go",
                "produces": {"out": {"path": "out.json", "check": {"check_id": "json_file", "params": {}, "sentinel": False}}},
                "repeat": {"until": "verifier_passes", "max_iterations": 2, "on_exhaust": "escalate"},
            },
            {"id": "next", "kind": "code", "command": "echo done"},
        ],
    }
    _setup(tmp_projects_root, plan)
    monkeypatch.setenv(ARTAGENTS_ACTOR, "alice")

    for i in (1, 2):
        d = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
        sd = step_dir_for_path("demo", "run-1", d.plan_step_path, iteration=i, root=tmp_projects_root)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "out.json").write_text("garbage", encoding="utf-8")
        task_gate.record_dispatch_complete(d, 0)

    # Next call should park on host/exhaust-override; an ack with --actor advances.
    override_cmd = "ack --project demo --step host/exhaust-override --actor alice"
    d3 = task_gate.gate_command("demo", override_cmd, override_cmd.split(), root=tmp_projects_root)
    assert d3.step_kind == "attested"
    assert d3.plan_step_id == "host/exhaust-override"

    d_next = task_gate.gate_command("demo", "echo done", ["echo", "done"], root=tmp_projects_root)
    assert d_next.plan_step_id == "next"


def test_iteration_env_var_propagates_to_subprocess(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p", "version": 1, "steps": [
            {
                "id": "host", "kind": "code", "command": "echo go",
                "produces": {"out": {"path": "out.json", "check": {"check_id": "json_file", "params": {}, "sentinel": False}}},
                "repeat": {"until": "verifier_passes", "max_iterations": 2, "on_exhaust": "fail"},
            },
        ],
    }
    _setup(tmp_projects_root, plan)

    d1 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert child_subprocess_env().get(TASK_ITERATION_ENV) == "001"
    sd1 = step_dir_for_path("demo", "run-1", d1.plan_step_path, iteration=1, root=tmp_projects_root)
    sd1.mkdir(parents=True, exist_ok=True)
    (sd1 / "out.json").write_text("garbage", encoding="utf-8")
    task_gate.record_dispatch_complete(d1, 0)

    d2 = task_gate.gate_command("demo", "echo go", ["echo", "go"], root=tmp_projects_root)
    assert child_subprocess_env().get(TASK_ITERATION_ENV) == "002"
