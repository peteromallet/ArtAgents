import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from astrid.packs.iteration.executors.prepare import run as prepare


THREAD_ID = "01ARZ3NDEKTSV4RRFFQ69G5FE0"
ROOT_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FE1"
TARGET_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FE2"


def test_prepare_refuses_above_cap_before_uncached_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_two_run_graph(tmp_path)
    calls = []

    def fail_if_called(*args, **kwargs):
        calls.append(args)
        raise AssertionError("summary dispatch should not happen before cap refusal")

    monkeypatch.setattr(prepare, "summarize_run_with_backoff", fail_if_called)

    with pytest.raises(prepare.PrepareError) as raised:
        prepare.prepare_iteration(
            repo_root=repo,
            out_path=repo / "runs" / "prepare",
            target_run_id=TARGET_RUN_ID,
            max_iterations=1,
        )

    message = str(raised.value)
    assert "max_iterations=1" in message
    assert "--max-iterations" in message
    assert "ARTAGENTS_ITERATION_MAX" in message
    assert "default cap is 200" in message
    assert calls == []


def test_executor_gateway_invocation_enforces_same_cap(tmp_path: Path) -> None:
    repo = _repo_with_two_run_graph(tmp_path)
    env = {
        **os.environ,
        "ARTAGENTS_REPO_ROOT": str(repo),
        "ARTAGENTS_THREADS_OFF": "1",
        "ARTAGENTS_ITERATION_MAX": "1",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "astrid",
            "executors",
            "run",
            "iteration.prepare",
            "--out",
            str(repo / "runs" / "prepare"),
            "--input",
            f"target_run_id={TARGET_RUN_ID}",
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "ARTAGENTS_ITERATION_MAX" in completed.stderr
    assert not (repo / "runs" / "prepare" / "iteration.manifest.json").exists()


def test_summary_cache_key_hits_misses_and_cost_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo_with_two_run_graph(tmp_path)
    model_version = "test.model.v1"
    cache_dir = repo / ".astrid" / "iteration_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = {
        "schema_version": 1,
        "run_id": ROOT_RUN_ID,
        "summary": "cached root",
        "summarizer_model_version": model_version,
    }
    (cache_dir / f"{ROOT_RUN_ID}__{model_version}.json").write_text(json.dumps(cached), encoding="utf-8")
    dispatched = []

    def fake_summary(node: prepare.RunNode, **kwargs):
        dispatched.append(node.run_id)
        return {
            "schema_version": 1,
            "run_id": node.run_id,
            "summary": f"fresh {node.run_id}",
            "summarizer_model_version": kwargs["summarizer_model_version"],
        }

    monkeypatch.setenv("ARTAGENTS_SUMMARIZE_SEQUENTIAL", "1")
    monkeypatch.setattr(prepare, "summarize_run_with_backoff", fake_summary)

    result = prepare.prepare_iteration(
        repo_root=repo,
        out_path=repo / "runs" / "prepare",
        target_run_id=TARGET_RUN_ID,
        max_iterations=1,
        summarizer_model_version=model_version,
        cost_per_call=0.25,
    )

    manifest = result["manifest"]
    assert dispatched == [TARGET_RUN_ID]
    assert manifest["summary_cache"] == {"hits": 1, "misses": 1}
    assert manifest["cost_estimate"]["summarize_calls"] == 2
    assert manifest["cost_estimate"]["uncached_summarize_calls"] == 1
    assert manifest["cost_estimate"]["estimated_cost"] == 0.25
    assert (cache_dir / f"{TARGET_RUN_ID}__{model_version}.json").is_file()


def test_ordering_is_causal_depth_then_selection_then_ulid() -> None:
    older = prepare.RunNode(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FF2",
        record={},
        depth=2,
        label="in_thread",
        selection_order=5,
    )
    selected = prepare.RunNode(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FF1",
        record={},
        depth=1,
        label="in_thread",
        selection_order=0,
    )
    unselected = prepare.RunNode(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FF0",
        record={},
        depth=1,
        label="in_thread",
        selection_order=9,
    )

    assert [node.run_id for node in prepare.order_nodes([unselected, selected, older])] == [
        older.run_id,
        selected.run_id,
        unselected.run_id,
    ]


def _repo_with_two_run_graph(tmp_path: Path) -> Path:
    repo = tmp_path
    _write_run(
        repo,
        "root",
        {
            "schema_version": 1,
            "run_id": ROOT_RUN_ID,
            "thread_id": THREAD_ID,
            "parent_run_ids": [],
            "executor_id": "builtin.generate_image",
            "kind": "executor",
            "out_path": "runs/root",
            "brief_content_sha256": "a" * 64,
            "input_artifacts": [],
            "output_artifacts": [{"kind": "image", "role": "other", "sha256": "b" * 64, "path": "runs/root/image.png"}],
        },
    )
    _write_run(
        repo,
        "target",
        {
            "schema_version": 1,
            "run_id": TARGET_RUN_ID,
            "thread_id": THREAD_ID,
            "parent_run_ids": [{"run_id": ROOT_RUN_ID, "kind": "causal"}],
            "executor_id": "builtin.generate_image",
            "kind": "executor",
            "out_path": "runs/target",
            "brief_content_sha256": "a" * 64,
            "input_artifacts": [{"kind": "image", "role": "other", "sha256": "b" * 64, "path": "runs/root/image.png"}],
            "output_artifacts": [{"kind": "image", "role": "other", "sha256": "c" * 64, "path": "runs/target/image.png"}],
        },
    )
    return repo


def _write_run(repo: Path, slug: str, record: dict) -> None:
    run_dir = repo / "runs" / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
