from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from artagents.contracts.schema import CommandSpec, Port
from artagents.core.executor.registry import ExecutorRegistry
from artagents.core.executor.runner import ExecutorRunRequest, ExecutorRunnerError, run_executor
from artagents.core.executor.schema import ConditionSpec, ExecutorDefinition
from artagents.core.orchestrator.registry import OrchestratorRegistry
from artagents.core.orchestrator.runner import OrchestratorRunRequest, run_orchestrator
from artagents.core.orchestrator.schema import OrchestratorDefinition, RuntimeSpec
from artagents.core.project import paths
from artagents.core.project.project import create_project
from artagents.packs.builtin.hype import run as hype


def test_executor_project_runs_finalize_success_error_skip_and_avoid_thread_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    projects_root = repo / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    _clear_thread_env(monkeypatch)
    create_project("demo")
    registry = ExecutorRegistry([_writer_executor("test.writer"), _requires_executor("test.requires"), _skip_executor("test.skip")])

    success = run_executor(ExecutorRunRequest("test.writer", out="", project="demo"), registry)
    with pytest.raises(ExecutorRunnerError):
        run_executor(ExecutorRunRequest("test.requires", out="", project="demo"), registry)
    skipped = run_executor(ExecutorRunRequest("test.skip", out="", project="demo", inputs={"skip_me": "1"}), registry)

    assert success.returncode == 0
    assert skipped.skipped is True
    records = _project_records(projects_root)
    assert [record["status"] for record in records] == ["success", "error", "skipped"]
    writer_out = Path(records[0]["out"])
    assert (writer_out / "env.txt").read_text(encoding="utf-8") == "1"
    assert (writer_out / "run.json").exists()
    assert not (repo / ".artagents" / "threads.json").exists()


def test_executor_legacy_out_still_writes_thread_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    _clear_thread_env(monkeypatch)
    registry = ExecutorRegistry([_writer_executor("test.writer")])
    out = repo / "runs" / "legacy"

    result = run_executor(ExecutorRunRequest("test.writer", out=out), registry)

    assert result.returncode == 0
    record = _read_json(out / "run.json")
    assert record["kind"] == "executor"
    assert record["status"] == "succeeded"
    assert (repo / ".artagents" / "threads.json").exists()
    assert not (tmp_path / "projects").exists()


def test_orchestrator_project_run_injects_hype_out_and_command_runtime_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))
    create_project("demo")
    registry = OrchestratorRegistry([_writer_orchestrator("test.orch")])

    result = run_orchestrator(OrchestratorRunRequest("test.orch", project="demo"), registry)

    assert result.returncode == 0
    record = _project_records(projects_root)[0]
    assert record["status"] == "success"
    assert record["tool_id"] == "test.orch"
    assert (Path(record["out"]) / "orch-env.txt").read_text(encoding="utf-8") == "1"

    hype_registry = OrchestratorRegistry([_hype_command_orchestrator()])
    dry = run_orchestrator(
        OrchestratorRunRequest(
            "builtin.hype",
            project="demo",
            dry_run=True,
            orchestrator_args=("--brief", str(tmp_path / "brief.txt"), "--target-duration", "1"),
        ),
        hype_registry,
    )
    assert dry.dry_run is True
    assert "--out" in dry.command
    assert str(projects_root / "demo" / "runs") in " ".join(dry.command)


def test_direct_hype_project_validation_error_and_nested_artifact_mirroring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))
    create_project("demo")

    code = hype.main(["--project", "demo", "--target-duration", "1"])
    assert code == 2
    error_record = _project_records(projects_root)[0]
    assert error_record["status"] == "error"
    assert error_record["metadata"]["returncode"] == 2

    brief = tmp_path / "brief.txt"
    brief.write_text("make a short thing", encoding="utf-8")

    def fake_pool(args):
        args.brief_out.mkdir(parents=True, exist_ok=True)
        (args.brief_out / "hype.timeline.json").write_text(json.dumps({"theme": "banodoco-default", "clips": []}), encoding="utf-8")
        (args.brief_out / "hype.assets.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
        (args.brief_out / "hype.metadata.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        return 0

    monkeypatch.setattr(hype, "pool_main", fake_pool)
    code = hype.main(["--project", "demo", "--brief", str(brief), "--target-duration", "1", "--brief-slug", "brief-a"])
    assert code == 0
    success_record = _project_records(projects_root)[1]
    assert success_record["status"] == "success"
    assert sorted(success_record["artifacts"]) == ["assets", "metadata", "timeline"]
    assert success_record["artifacts"]["timeline"]["source_path"].endswith("briefs/brief-a/hype.timeline.json")
    assert (Path(success_record["out"]) / "timeline.json").exists()


def test_project_run_rejects_project_plus_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    create_project("demo")
    registry = ExecutorRegistry([_writer_executor("test.writer")])

    with pytest.raises(Exception, match="--project cannot be combined with --out"):
        run_executor(ExecutorRunRequest("test.writer", out=tmp_path / "out", project="demo"), registry)
    assert list((tmp_path / "projects" / "demo" / "runs").glob("*")) == []


def _writer_executor(executor_id: str) -> ExecutorDefinition:
    script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[1])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'env.txt').write_text(os.environ.get('ARTAGENTS_PROJECT_RUN', ''), encoding='utf-8')\n"
    )
    return ExecutorDefinition(
        id=executor_id,
        name="Writer",
        kind="external",
        version="1.0",
        command=CommandSpec(argv=(sys.executable, "-c", script, "{out}")),
    )


def _requires_executor(executor_id: str) -> ExecutorDefinition:
    return ExecutorDefinition(
        id=executor_id,
        name="Requires",
        kind="external",
        version="1.0",
        inputs=(Port(name="needed", type="string", required=True),),
        command=CommandSpec(argv=(sys.executable, "-c", "print('unused')")),
    )


def _skip_executor(executor_id: str) -> ExecutorDefinition:
    return ExecutorDefinition(
        id=executor_id,
        name="Skip",
        kind="external",
        version="1.0",
        inputs=(Port(name="skip_me", type="string", required=False),),
        conditions=(ConditionSpec(kind="skip_if_input", input="skip_me"),),
        command=CommandSpec(argv=(sys.executable, "-c", "print('unused')")),
    )


def _writer_orchestrator(orchestrator_id: str) -> OrchestratorDefinition:
    script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[1])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'orch-env.txt').write_text(os.environ.get('ARTAGENTS_PROJECT_RUN', ''), encoding='utf-8')\n"
    )
    return OrchestratorDefinition(
        id=orchestrator_id,
        name="Orchestrator",
        kind="built_in",
        version="1.0",
        runtime=RuntimeSpec(kind="command", command=CommandSpec(argv=(sys.executable, "-c", script, "{out}"))),
    )


def _hype_command_orchestrator() -> OrchestratorDefinition:
    return OrchestratorDefinition(
        id="builtin.hype",
        name="Hype",
        kind="built_in",
        version="1.0",
        runtime=RuntimeSpec(
            kind="command",
            command=CommandSpec(argv=(sys.executable, "-m", "artagents.packs.builtin.hype.run", "{orchestrator_args}")),
        ),
        metadata={"requires_output_path": True},
    )


def _project_records(projects_root: Path) -> list[dict]:
    return [_read_json(path) for path in sorted((projects_root / "demo" / "runs").glob("*/run.json"))]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _clear_thread_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ARTAGENTS_THREADS_OFF",
        "ARTAGENTS_THREAD_INHERITED",
        "ARTAGENTS_THREAD_ID",
        "ARTAGENTS_RUN_ID",
        "ARTAGENTS_PARENT_RUN_ID",
        "ARTAGENTS_PROJECT_RUN",
    ):
        monkeypatch.delenv(name, raising=False)
