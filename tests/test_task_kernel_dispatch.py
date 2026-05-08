from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from astrid import pipeline
from astrid.core.executor import cli as executor_cli
from astrid.core.executor import runner as executor_runner
from astrid.core.executor.runner import ExecutorRunRequest, ExecutorRunResult, ExecutorRunnerError
from astrid.core.orchestrator.runner import OrchestratorRunRequest, OrchestratorRunnerError, run_orchestrator
from astrid.core.project.project import create_project
from astrid.core.task import gate as task_gate
from astrid.core.task.active_run import write_active_run
from astrid.core.task.env import TASK_PROJECT_ENV, TASK_RUN_ID_ENV, TASK_STEP_ID_ENV
from astrid.core.task.plan import compute_plan_hash
from astrid.packs.builtin.hype import run as hype_run


def test_pipeline_dispatch_calls_top_gate_and_executor_reentry(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = "executors run builtin.noop --project demo"
    _setup_active_plan(tmp_projects_root, command=command)
    fake_executor = SimpleNamespace(id="builtin.noop", outputs=())
    fake_registry = SimpleNamespace(get=lambda executor_id: fake_executor)

    monkeypatch.setattr(executor_cli, "load_default_registry", lambda *args, **kwargs: fake_registry)
    monkeypatch.setattr(
        executor_runner,
        "_run_executor_inner",
        lambda request, executor: ExecutorRunResult(executor_id=executor.id, kind="external", returncode=0),
    )

    with patch("astrid.core.task.gate.gate_command", wraps=task_gate.gate_command) as gate_spy:
        assert pipeline.main(["executors", "run", "builtin.noop", "--project", "demo"]) == 0

    assert gate_spy.call_count == 2
    assert gate_spy.call_args_list[0].args[:2] == ("demo", command)
    assert gate_spy.call_args_list[0].kwargs.get("reentry", False) is False
    assert gate_spy.call_args_list[1].args[:2] == ("demo", command)
    assert gate_spy.call_args_list[1].kwargs["reentry"] is True


def test_orchestrator_runner_rejects_before_project_run_side_effects(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_active_plan(tmp_projects_root, command="not the orchestrator command")
    _set_task_env(monkeypatch)

    with patch("astrid.core.task.gate.gate_command", wraps=task_gate.gate_command) as gate_spy:
        with pytest.raises(OrchestratorRunnerError, match="astrid next --project demo"):
            run_orchestrator(OrchestratorRunRequest(orchestrator_id="builtin.hype", project="demo"))

    assert gate_spy.call_count == 1
    assert gate_spy.call_args.kwargs["reentry"] is True
    assert _run_entries(tmp_projects_root) == []


def test_executor_runner_rejects_before_project_run_side_effects(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_active_plan(tmp_projects_root, command="not the executor command")
    _set_task_env(monkeypatch)

    with patch("astrid.core.task.gate.gate_command", wraps=task_gate.gate_command) as gate_spy:
        with pytest.raises(ExecutorRunnerError, match="astrid next --project demo"):
            executor_runner.run_executor(ExecutorRunRequest(executor_id="builtin.noop", out="", project="demo"))

    assert gate_spy.call_count == 1
    assert gate_spy.call_args.kwargs["reentry"] is True
    assert _run_entries(tmp_projects_root) == []


def test_hype_runtime_rejects_before_project_run_side_effects(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_active_plan(tmp_projects_root, command="not the hype command")
    _set_task_env(monkeypatch)

    with patch("astrid.core.task.gate.gate_command", wraps=task_gate.gate_command) as gate_spy:
        assert hype_run.main(["--project", "demo", "--brief", "hello"]) == 1

    assert gate_spy.call_count == 1
    assert gate_spy.call_args.kwargs["reentry"] is True
    assert _run_entries(tmp_projects_root) == []


def _setup_active_plan(tmp_projects_root: Path, *, command: str) -> None:
    create_project("demo", root=tmp_projects_root)
    plan_path = tmp_projects_root / "demo" / "plan.json"
    plan_path.write_text(
        json.dumps({"plan_id": "dispatch-plan", "version": 1, "steps": [{"id": "step-1", "command": command}]}),
        encoding="utf-8",
    )
    write_active_run("demo", run_id="task-run-1", plan_hash=compute_plan_hash(plan_path), root=tmp_projects_root)


def _set_task_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TASK_RUN_ID_ENV, "task-run-1")
    monkeypatch.setenv(TASK_PROJECT_ENV, "demo")
    monkeypatch.setenv(TASK_STEP_ID_ENV, "step-1")


def _run_entries(tmp_projects_root: Path) -> list[str]:
    runs_dir = tmp_projects_root / "demo" / "runs"
    return sorted(path.name for path in runs_dir.iterdir())
