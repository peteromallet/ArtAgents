from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from astrid.core.project.project import create_project
from astrid.core.task import gate as task_gate
from astrid.core.task.active_run import write_active_run
from astrid.core.task.env import (
    TASK_ITEM_ID_ENV,
    TASK_ITERATION_ENV,
    TASK_PROJECT_ENV,
    TASK_RUN_ID_ENV,
    TASK_STEP_ID_ENV,
)
from astrid.core.task.plan import compute_plan_hash, step_dir_for_path


def _clear_task_env() -> None:
    for name in (
        TASK_RUN_ID_ENV,
        TASK_PROJECT_ENV,
        TASK_STEP_ID_ENV,
        TASK_ITEM_ID_ENV,
        TASK_ITERATION_ENV,
    ):
        os.environ.pop(name, None)


def _run_one_step(tmp_projects_root: Path, slug: str, payload: bytes) -> None:
    plan = {
        "plan_id": "p",
        "version": 2,
        "steps": [
            {
                "id": "step-1",
                "kind": "code",
                "adapter": "local",
                "command": "echo go",
                "cost": {"amount": 0, "currency": "USD", "source": "local"},
                "produces": {
                    "out": {
                        "path": "out.json",
                        "check": {"check_id": "json_file", "params": {}, "sentinel": False},
                    }
                },
            }
        ],
    }
    run_id = "run-1"
    create_project(slug, root=tmp_projects_root)
    plan_path = tmp_projects_root / slug / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    write_active_run(slug, run_id=run_id, plan_hash=compute_plan_hash(plan_path), root=tmp_projects_root)

    decision = task_gate.gate_command(slug, "echo go", ["echo", "go"], root=tmp_projects_root)
    step_dir = step_dir_for_path(slug, run_id, ("step-1",), root=tmp_projects_root)
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "out.json").write_bytes(payload)
    task_gate.record_dispatch_complete(decision, 0)


def test_identical_content_is_not_shared_across_projects(tmp_projects_root: Path) -> None:
    payload = b'{"shared": "bytes"}'
    sha = hashlib.sha256(payload).hexdigest()

    try:
        _run_one_step(tmp_projects_root, "proj-a", payload)
        _run_one_step(tmp_projects_root, "proj-b", payload)

        cas_a = tmp_projects_root / "proj-a" / ".cas" / sha
        cas_b = tmp_projects_root / "proj-b" / ".cas" / sha
        assert cas_a.is_file()
        assert cas_b.is_file()
        # Two distinct physical files, even though contents (and hash) are identical.
        assert cas_a.stat().st_ino != cas_b.stat().st_ino
        assert cas_a.read_bytes() == payload
        assert cas_b.read_bytes() == payload

        # No shared CAS at the projects-root level.
        assert not (tmp_projects_root / ".cas").exists()
    finally:
        _clear_task_env()
