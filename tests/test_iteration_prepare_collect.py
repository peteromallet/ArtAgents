import json
from pathlib import Path

from astrid.packs.iteration.prepare import run as prepare


THREAD_ID = "01ARZ3NDEKTSV4RRFFQ69G5FA0"
OTHER_THREAD_ID = "01ARZ3NDEKTSV4RRFFQ69G5FA1"
ROOT_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FB0"
EXTERNAL_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FB1"
TARGET_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FB2"
MISSING_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FB3"


def test_prepare_walks_typed_parent_edges_and_labels_ancestry(tmp_path: Path) -> None:
    repo = tmp_path
    _write_run(
        repo,
        "root",
        _record(
            ROOT_RUN_ID,
            thread_id=THREAD_ID,
            input_artifacts=[],
            output_artifacts=[_artifact("image", "a" * 64)],
        ),
    )
    _write_run(
        repo,
        "external",
        _record(
            EXTERNAL_RUN_ID,
            thread_id=OTHER_THREAD_ID,
            input_artifacts=[],
            output_artifacts=[_artifact("image", "b" * 64)],
        ),
    )
    _write_run(
        repo,
        "target",
        _record(
            TARGET_RUN_ID,
            thread_id=THREAD_ID,
            parent_run_ids=[
                {"run_id": ROOT_RUN_ID, "kind": "causal"},
                {"run_id": EXTERNAL_RUN_ID, "kind": "chosen", "group": "logo-choices"},
            ],
            input_artifacts=[_artifact("image", "b" * 64, path="runs/external/out.png")],
            output_artifacts=[_artifact("image", "c" * 64)],
        ),
    )

    result = prepare.prepare_iteration(
        repo_root=repo,
        out_path=repo / "runs" / "prepare",
        target_run_id=TARGET_RUN_ID,
        max_iterations=10,
    )

    runs = {item["run_id"]: item for item in result["manifest"]["runs"]}
    assert set(runs) == {ROOT_RUN_ID, EXTERNAL_RUN_ID, TARGET_RUN_ID}
    assert runs[ROOT_RUN_ID]["label"] == "in_thread"
    assert runs[TARGET_RUN_ID]["label"] == "in_thread"
    assert runs[EXTERNAL_RUN_ID]["label"] == "pulled_by_ancestry"
    assert {"run_id": EXTERNAL_RUN_ID, "kind": "chosen", "group": "logo-choices"} in runs[TARGET_RUN_ID]["parent_run_ids"]


def test_unresolved_producer_report_names_only_missing_producers(tmp_path: Path) -> None:
    repo = tmp_path
    _write_run(
        repo,
        "root",
        _record(ROOT_RUN_ID, thread_id=THREAD_ID, input_artifacts=[], output_artifacts=[]),
    )
    _write_run(
        repo,
        "target",
        _record(
            TARGET_RUN_ID,
            thread_id=THREAD_ID,
            parent_run_ids=[{"run_id": MISSING_RUN_ID, "kind": "causal"}],
            input_artifacts=[_artifact("image", "d" * 64, path="runs/missing/out.png")],
            output_artifacts=[],
        ),
    )

    result = prepare.prepare_iteration(
        repo_root=repo,
        out_path=repo / "runs" / "prepare",
        target_run_id=TARGET_RUN_ID,
        max_iterations=10,
    )

    quality = result["quality"]
    assert ROOT_RUN_ID not in {item["run_id"] for item in quality["unresolved_producer_runs"]}
    assert quality["unresolved_producer_runs"] == [
        {
            "run_id": TARGET_RUN_ID,
            "missing_parent_run_ids": [MISSING_RUN_ID],
            "reason": "missing referenced producer",
        }
    ]


def _write_run(repo: Path, slug: str, record: dict) -> None:
    run_dir = repo / "runs" / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record(
    run_id: str,
    *,
    thread_id: str,
    parent_run_ids: list[dict] | None = None,
    input_artifacts: list[dict] | None = None,
    output_artifacts: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "thread_id": thread_id,
        "parent_run_ids": parent_run_ids or [],
        "executor_id": "builtin.generate_image",
        "orchestrator_id": None,
        "kind": "executor",
        "status": "succeeded",
        "returncode": 0,
        "out_path": f"runs/{run_id}",
        "brief_content_sha256": "e" * 64,
        "input_artifacts": input_artifacts or [],
        "output_artifacts": output_artifacts or [],
        "provenance": {"contributing_runs": []},
    }


def _artifact(kind: str, sha: str, path: str | None = None) -> dict:
    artifact = {"kind": kind, "role": "other", "sha256": sha}
    if path is not None:
        artifact["path"] = path
    else:
        artifact["path"] = f"runs/artifact-{sha[:8]}.dat"
    return artifact
