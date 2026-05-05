from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from artagents.core.project.project import create_project
from artagents.core.task import gate as task_gate
from artagents.core.task.active_run import write_active_run
from artagents.core.task.env import (
    TASK_ITEM_ID_ENV,
    TASK_ITERATION_ENV,
    TASK_PROJECT_ENV,
    TASK_RUN_ID_ENV,
    TASK_STEP_ID_ENV,
)
from artagents.core.task.events import read_events
from artagents.core.task.plan import compute_plan_hash, step_dir_for_path


def _clear_task_env() -> None:
    for name in (
        TASK_RUN_ID_ENV,
        TASK_PROJECT_ENV,
        TASK_STEP_ID_ENV,
        TASK_ITEM_ID_ENV,
        TASK_ITERATION_ENV,
    ):
        os.environ.pop(name, None)


def test_produces_pass_interns_into_cas_and_links(tmp_projects_root: Path) -> None:
    plan = {
        "plan_id": "p",
        "version": 1,
        "steps": [
            {
                "id": "step-1",
                "kind": "code",
                "command": "echo go",
                "produces": {
                    "out": {
                        "path": "out.json",
                        "check": {"check_id": "json_file", "params": {}, "sentinel": False},
                    }
                },
            }
        ],
    }
    slug = "demo"
    run_id = "run-1"
    create_project(slug, root=tmp_projects_root)
    plan_path = tmp_projects_root / slug / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    write_active_run(slug, run_id=run_id, plan_hash=compute_plan_hash(plan_path), root=tmp_projects_root)
    events_path = tmp_projects_root / slug / "runs" / run_id / "events.jsonl"

    try:
        decision = task_gate.gate_command(slug, "echo go", ["echo", "go"], root=tmp_projects_root)
        step_dir = step_dir_for_path(slug, run_id, ("step-1",), root=tmp_projects_root)
        step_dir.mkdir(parents=True, exist_ok=True)
        payload = b'{"ok": 1}'
        artifact = step_dir / "out.json"
        artifact.write_bytes(payload)
        expected_sha = hashlib.sha256(payload).hexdigest()

        task_gate.record_dispatch_complete(decision, 0)

        assert artifact.is_symlink() is True
        link_target = os.readlink(artifact)
        assert not link_target.startswith("/"), f"symlink target must be relative, got {link_target!r}"

        project_root = tmp_projects_root / slug
        resolved = artifact.resolve()
        cas_dir = (project_root / ".cas").resolve()
        assert cas_dir in resolved.parents
        assert resolved.name == expected_sha
        assert resolved.read_bytes() == payload

        events = read_events(events_path)
        passed = [e for e in events if e["kind"] == "produces_check_passed"]
        assert passed, "expected at least one produces_check_passed event"
        assert passed[-1].get("cas_sha256") == expected_sha
    finally:
        _clear_task_env()
