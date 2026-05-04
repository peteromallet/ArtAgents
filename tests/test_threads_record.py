from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from artagents.contracts.schema import CommandSpec, Output, Port
from artagents.core.executor.registry import ExecutorRegistry
from artagents.core.executor.runner import ExecutorRunRequest, ExecutorRunnerError, run_executor
from artagents.core.executor.schema import ExecutorDefinition
from artagents.core.orchestrator.registry import OrchestratorRegistry
from artagents.core.orchestrator.runner import OrchestratorRunRequest, run_orchestrator
from artagents.core.orchestrator.schema import OrchestratorDefinition, RuntimeSpec
from artagents.threads.ids import is_ulid


def test_executor_success_writes_run_json_index_and_output_integrity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    out = repo / "runs" / "success"
    registry = ExecutorRegistry([_writer_executor("test.writer")])

    result = run_executor(ExecutorRunRequest("test.writer", out=out), registry)

    assert result.returncode == 0
    record = _read_json(out / "run.json")
    assert record["schema_version"] == 1
    assert is_ulid(record["run_id"])
    assert is_ulid(record["thread_id"])
    assert record["executor_id"] == "test.writer"
    assert record["orchestrator_id"] is None
    assert record["kind"] == "executor"
    assert record["status"] == "succeeded"
    assert record["returncode"] == 0
    assert record["started_at"]
    assert record["ended_at"]
    assert record["out_path"] == "runs/success"
    assert record["parent_run_ids"] == []
    assert record["output_artifacts"][0]["path"] == "runs/success/result.txt"
    assert record["output_artifacts"][0]["sha256"]
    assert record["output_artifacts"][0]["role"] == "other"
    assert "host_id" not in record
    assert "chosen_from_groups" not in record
    assert "preview_modes" not in json.dumps(record)
    assert (out / "result.txt").read_text(encoding="utf-8").startswith("1:")

    index = _read_json(repo / ".artagents" / "threads.json")
    assert index["active_thread_id"] == record["thread_id"]
    assert record["run_id"] in index["threads"][record["thread_id"]]["run_ids"]


def test_executor_nonzero_and_exception_finalize_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    failed_out = repo / "runs" / "failed"
    registry = ExecutorRegistry([_exit_executor("test.exits", 7), _requires_input_executor("test.requires")])

    result = run_executor(ExecutorRunRequest("test.exits", out=failed_out), registry)

    assert result.returncode == 7
    failed = _read_json(failed_out / "run.json")
    assert failed["status"] == "failed"
    assert failed["returncode"] == 7

    error_out = repo / "runs" / "error"
    with pytest.raises(ExecutorRunnerError):
        run_executor(ExecutorRunRequest("test.requires", out=error_out), registry)
    errored = _read_json(error_out / "run.json")
    assert errored["status"] == "error"
    assert errored["returncode"] == -1
    assert errored["error"]["type"] == "ExecutorRunnerError"
    assert "missing required input" in errored["error"]["message"]


def test_noop_gates_skip_run_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    registry = ExecutorRegistry([_writer_executor("test.writer"), _exit_executor("test.noout", 0)])

    cases = [
        ExecutorRunRequest("test.writer", out=repo / "runs" / "dry", dry_run=True),
        ExecutorRunRequest("test.writer", out=repo / "runs" / "none", thread="@none"),
        ExecutorRunRequest("test.noout", out=""),
    ]
    for request in cases:
        run_executor(request, registry)

    monkeypatch.setenv("ARTAGENTS_THREADS_OFF", "1")
    run_executor(ExecutorRunRequest("test.writer", out=repo / "runs" / "off"), registry)
    monkeypatch.delenv("ARTAGENTS_THREADS_OFF")
    monkeypatch.setenv("ARTAGENTS_THREAD_INHERITED", "1")
    run_executor(ExecutorRunRequest("test.writer", out=repo / "runs" / "inherited"), registry)
    monkeypatch.delenv("ARTAGENTS_THREAD_INHERITED")

    assert not (repo / "runs" / "dry" / "run.json").exists()
    assert not (repo / "runs" / "none" / "run.json").exists()
    assert not (repo / "runs" / "off" / "run.json").exists()
    assert not (repo / "runs" / "inherited" / "run.json").exists()


def test_upload_youtube_is_zero_artifact_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    with mock.patch(
        "artagents.packs.upload.youtube.src.social_publish.publish_youtube_video",
        return_value={"url": "https://youtube.example/video"},
    ):
        result = run_executor(
            ExecutorRunRequest(
                "upload.youtube",
                out="",
                inputs={
                    "video_url": "https://example.invalid/video.mp4",
                    "title": "Title",
                    "description": "Description",
                },
            )
        )
    assert result.payload["url"] == "https://youtube.example/video"
    assert not (repo / ".artagents").exists()


def test_redaction_private_brief_and_external_service_trim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    out = repo / "runs" / "private-case"
    private = out / "private"
    private.mkdir(parents=True)
    brief = private / "brief.txt"
    brief.write_text("secret brief", encoding="utf-8")
    registry = ExecutorRegistry([_writer_executor("test.writer")])

    run_executor(
        ExecutorRunRequest(
            "test.writer",
            out=out,
            brief=brief,
            inputs={
                "OPENAI_API_KEY": "sk-test",
                "external_service_calls": [
                    {
                        "model": "gpt-image-2",
                        "model_version": "2026-01-01",
                        "request_id": "req_123",
                        "latency_ms": 99,
                    }
                ],
            },
        ),
        registry,
    )

    record = _read_json(out / "run.json")
    assert "sk-test" not in json.dumps(record)
    assert any(arg == "--input=OPENAI_API_KEY=***REDACTED***" for arg in record["cli_args_redacted"])
    assert record["brief_content_sha256"]
    assert not (out / "brief.copy.txt").exists()
    brief_artifact = next(item for item in record["input_artifacts"] if item["kind"] == "brief")
    assert brief_artifact["private"] is True
    assert "path" not in brief_artifact
    assert brief_artifact["sha256"]
    assert record["external_service_calls"] == [
        {"model": "gpt-image-2", "model_version": "2026-01-01", "request_id": "req_123"}
    ]


def test_orchestrator_command_runtime_writes_record_and_propagates_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    out = repo / "runs" / "orch"
    registry = OrchestratorRegistry([_writer_orchestrator("test.orch")])

    result = run_orchestrator(OrchestratorRunRequest("test.orch", out=out), registry)

    assert result.returncode == 0
    record = _read_json(out / "run.json")
    assert record["kind"] == "orchestrator"
    assert record["orchestrator_id"] == "test.orch"
    assert record["executor_id"] is None
    env_text = (out / "orch-env.txt").read_text(encoding="utf-8")
    assert env_text.startswith("1:")
    assert record["thread_id"] in env_text


def test_typed_from_ref_parent_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    out = repo / "runs" / "chosen"
    parent_run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    registry = ExecutorRegistry([_writer_executor("test.writer")])

    run_executor(ExecutorRunRequest("test.writer", out=out, from_ref=f"{parent_run_id}:2"), registry)

    record = _read_json(out / "run.json")
    assert record["parent_run_ids"] == [{"kind": "chosen", "run_id": parent_run_id}]


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    for name in ("ARTAGENTS_THREADS_OFF", "ARTAGENTS_THREAD_INHERITED", "ARTAGENTS_THREAD_ID", "ARTAGENTS_RUN_ID", "ARTAGENTS_PARENT_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    return repo


def _writer_executor(executor_id: str) -> ExecutorDefinition:
    script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[1])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'result.txt').write_text(os.environ.get('ARTAGENTS_THREAD_INHERITED', '') + ':' + os.environ.get('ARTAGENTS_THREAD_ID', ''), encoding='utf-8')\n"
    )
    return ExecutorDefinition(
        id=executor_id,
        name="Writer",
        kind="external",
        version="1.0",
        command=CommandSpec(argv=(sys.executable, "-c", script, "{out}")),
        outputs=(Output(name="result", type="file", path_template="{out}/result.txt"),),
    )


def _exit_executor(executor_id: str, code: int) -> ExecutorDefinition:
    return ExecutorDefinition(
        id=executor_id,
        name="Exit",
        kind="external",
        version="1.0",
        command=CommandSpec(argv=(sys.executable, "-c", f"import sys; sys.exit({code})")),
    )


def _requires_input_executor(executor_id: str) -> ExecutorDefinition:
    return ExecutorDefinition(
        id=executor_id,
        name="Requires Input",
        kind="external",
        version="1.0",
        inputs=(Port(name="needed", type="string", required=True),),
        command=CommandSpec(argv=(sys.executable, "-c", "print('unused')")),
    )


def _writer_orchestrator(orchestrator_id: str) -> OrchestratorDefinition:
    script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[1])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'orch-env.txt').write_text(os.environ.get('ARTAGENTS_THREAD_INHERITED', '') + ':' + os.environ.get('ARTAGENTS_THREAD_ID', ''), encoding='utf-8')\n"
    )
    return OrchestratorDefinition(
        id=orchestrator_id,
        name="Orchestrator",
        kind="built_in",
        version="1.0",
        runtime=RuntimeSpec(kind="command", command=CommandSpec(argv=(sys.executable, "-c", script, "{out}"))),
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
