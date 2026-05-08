from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from astrid.core.project.project import create_project
from astrid.core.task.active_run import write_active_run
from astrid.core.task.env import child_subprocess_env
from astrid.core.task.events import read_events, verify_chain
from astrid.core.task.gate import TaskRunGateError, gate_command, record_dispatch_complete
from astrid.core.task.plan import compute_plan_hash, load_plan


def test_two_step_plan_drives_kernel_end_to_end(tmp_projects_root: Path) -> None:
    create_project("demo", root=tmp_projects_root)
    plan_path = tmp_projects_root / "demo" / "plan.json"
    plan_payload = {
        "plan_id": "p1",
        "version": 1,
        "steps": [
            {"id": "step-1", "command": "python3 -c \"print('ok')\""},
            {"id": "step-2", "command": "python3 -c \"print('ok')\""},
        ],
    }
    plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

    plan = load_plan(plan_path)
    plan_hash = compute_plan_hash(plan_path)
    write_active_run("demo", run_id="run-1", plan_hash=plan_hash, root=tmp_projects_root)

    events_path = None
    for step in plan.steps:
        decision = gate_command("demo", step.command, [], root=tmp_projects_root)
        assert decision.active is True
        assert decision.reentry is False
        assert decision.plan_step_id == step.id
        events_path = decision.events_path

        env = child_subprocess_env(base=os.environ)
        completed = subprocess.run(
            shlex.split(step.command),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        assert completed.stdout.strip() == "ok"

        record_dispatch_complete(decision, completed.returncode)

    assert events_path is not None
    ok, last_index, error = verify_chain(events_path)
    assert ok is True
    assert error is None
    assert last_index == 3

    events = read_events(events_path)
    completed_events = [event for event in events if event.get("kind") == "step_completed"]
    assert len(completed_events) == 2
    assert [event["plan_step_id"] for event in completed_events] == ["step-1", "step-2"]
    assert all(event["returncode"] == 0 for event in completed_events)

    with pytest.raises(TaskRunGateError) as exc_info:
        gate_command("demo", plan.steps[0].command, [], root=tmp_projects_root)
    assert exc_info.value.reason == "plan is exhausted"
    assert exc_info.value.recovery == "astrid abort --project demo"
