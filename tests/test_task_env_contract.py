from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from astrid.core.executor import runner as executor_runner
from astrid.core.executor.runner import ExecutorRunRequest
from astrid.core.orchestrator import runner as orchestrator_runner
from astrid.core.orchestrator.runner import OrchestratorRunRequest
from astrid.core.project.project import create_project
from astrid.core.project.run import ProjectRunContext, ProjectRunError, finalize_project_run, prepare_project_run
from astrid.core.task.env import TASK_PROJECT_ENV, TASK_RUN_ID_ENV, TASK_STEP_ID_ENV
from astrid.packs.builtin.orchestrators.hype import run as hype_run


def test_task_env_prepare_project_run_attaches_to_step_dir_without_run_json(
    tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_project("demo", root=tmp_projects_root)
    _set_task_env(monkeypatch, project="demo", run_id="task-run-1", step_id="step-1")

    context = prepare_project_run("demo", root=tmp_projects_root)

    assert context.run_root == tmp_projects_root / "demo" / "runs" / "task-run-1" / "steps" / "step-1"
    assert context.run_id == "task-run-1"
    assert not context.run_json_path.exists()
    assert context.record["status"] == "attached"
    assert context.record["metadata"]["attached_to_task_run"] is True
    assert context.record["metadata"]["task_step_id"] == "step-1"


def test_task_env_second_step_reuses_same_parent_run_dir(tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    create_project("demo", root=tmp_projects_root)
    _set_task_env(monkeypatch, project="demo", run_id="task-run-1", step_id="step-1")
    first = prepare_project_run("demo", root=tmp_projects_root)
    monkeypatch.setenv(TASK_STEP_ID_ENV, "step-2")

    second = prepare_project_run("demo", root=tmp_projects_root)

    assert first.run_root.parent == second.run_root.parent
    assert second.run_root == tmp_projects_root / "demo" / "runs" / "task-run-1" / "steps" / "step-2"


def test_task_env_project_mismatch_rejects(tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    create_project("demo", root=tmp_projects_root)
    _set_task_env(monkeypatch, project="other", run_id="task-run-1", step_id="step-1")

    with pytest.raises(ProjectRunError, match="task run is bound to project 'other'"):
        prepare_project_run("demo", root=tmp_projects_root)


def test_task_env_missing_step_id_rejects(tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    create_project("demo", root=tmp_projects_root)
    monkeypatch.setenv(TASK_RUN_ID_ENV, "task-run-1")
    monkeypatch.setenv(TASK_PROJECT_ENV, "demo")
    monkeypatch.delenv(TASK_STEP_ID_ENV, raising=False)

    with pytest.raises(ProjectRunError, match="ARTAGENTS_TASK_STEP_ID must be set"):
        prepare_project_run("demo", root=tmp_projects_root)


def test_env_unset_standalone_path_still_writes_run_json(tmp_projects_root: Path) -> None:
    create_project("demo", root=tmp_projects_root)

    context = prepare_project_run("demo", root=tmp_projects_root, run_id="standalone-run")

    assert context.run_root == tmp_projects_root / "demo" / "runs" / "standalone-run"
    assert context.run_json_path.is_file()
    assert context.record["status"] == "prepared"


def test_attached_hype_artifacts_mirror_under_step_produces(tmp_projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    create_project("demo", root=tmp_projects_root)
    _set_task_env(monkeypatch, project="demo", run_id="task-run-1", step_id="step-1")
    context = prepare_project_run("demo", root=tmp_projects_root)
    artifact_root = tmp_projects_root / "artifacts"
    artifact_root.mkdir()
    for name in ("hype.timeline.json", "hype.assets.json", "hype.metadata.json"):
        (artifact_root / name).write_text("{}\n", encoding="utf-8")

    record = finalize_project_run(context, status="success", artifact_roots=[artifact_root])

    assert not context.run_json_path.exists()
    produces = context.run_root / "produces"
    assert sorted(path.name for path in produces.iterdir()) == ["assets.json", "metadata.json", "timeline.json"]
    assert all(Path(value["path"]).parent == produces for value in record["artifacts"].values())


def test_prepare_project_run_is_central_chokepoint_for_project_callers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_prepare(project_slug: str, **kwargs: object) -> ProjectRunContext:
        calls.append((project_slug, kwargs.get("kind")))
        run_root = tmp_path / f"run-{len(calls)}"
        return ProjectRunContext(
            project_slug=project_slug,
            run_id=f"run-{len(calls)}",
            run_root=run_root,
            run_json_path=run_root / "run.json",
            record={"metadata": {}},
            root=tmp_path,
        )

    monkeypatch.setattr(executor_runner, "prepare_project_run", fake_prepare)
    monkeypatch.setattr(orchestrator_runner, "prepare_project_run", fake_prepare)
    monkeypatch.setattr(hype_run, "prepare_project_run", fake_prepare)

    executor_runner._prepare_project_request(
        ExecutorRunRequest(executor_id="builtin.noop", out="", project="demo"),
        SimpleNamespace(id="builtin.noop"),
    )
    orchestrator_runner._prepare_project_request(
        OrchestratorRunRequest(orchestrator_id="builtin.hype", project="demo"),
        SimpleNamespace(id="builtin.hype", runtime=SimpleNamespace(kind="command"), metadata={}),
    )
    hype_run._prepare_project_main(["--project", "demo", "--brief", "hello"])

    assert calls == [("demo", "executor"), ("demo", "orchestrator"), ("demo", "orchestrator")]


def _set_task_env(monkeypatch: pytest.MonkeyPatch, *, project: str, run_id: str, step_id: str) -> None:
    monkeypatch.setenv(TASK_RUN_ID_ENV, run_id)
    monkeypatch.setenv(TASK_PROJECT_ENV, project)
    monkeypatch.setenv(TASK_STEP_ID_ENV, step_id)
