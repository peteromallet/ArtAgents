import contextlib
import io
import json
from pathlib import Path

from artagents.packs.builtin.iteration_video import run as iteration_video
from artagents.core.orchestrator.runner import OrchestratorRunRequest, run_orchestrator
from artagents.threads.index import ThreadIndexStore
from artagents.threads.schema import make_thread_record


THREAD_ID = "01ARZ3NDEKTSV4RRFFQ69G5FV0"
TARGET_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FV1"
ROOT_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FV2"


def test_iteration_video_renders_hype_adapter_and_records_five_output_variant_group(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path
    out_dir = repo / "runs" / "iteration-video"
    forwarded: dict[str, object] = {}
    _write_thread(repo)

    def fake_prepare_iteration(**kwargs):
        forwarded["max_iterations"] = kwargs["max_iterations"]
        _write_prepare_outputs(kwargs["out_path"])
        return {"manifest_path": str(kwargs["out_path"] / "iteration.manifest.json")}

    def fake_render(brief_out: Path) -> Path:
        forwarded["render_timeline"] = brief_out / "hype.timeline.json"
        forwarded["render_assets"] = brief_out / "hype.assets.json"
        assert (brief_out / "hype.timeline.json").is_file()
        assert (brief_out / "hype.assets.json").is_file()
        hype_mp4 = brief_out / "hype.mp4"
        hype_mp4.write_bytes(b"rendered-mp4")
        return hype_mp4

    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    monkeypatch.setattr(iteration_video.prepare, "prepare_iteration", fake_prepare_iteration)
    monkeypatch.setattr(iteration_video, "run_builtin_render", fake_render)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = run_orchestrator(
            OrchestratorRunRequest(
                orchestrator_id="builtin.iteration_video",
                out=out_dir,
                thread=THREAD_ID,
                inputs={"target_run_id": TARGET_RUN_ID, "repo_root": str(repo)},
                orchestrator_args=("--max-iterations", "7", "--direction", "label only", "--clip-mode", "hold"),
            )
        )

    assert result.ok
    assert forwarded["max_iterations"] == 7
    assert Path(forwarded["render_timeline"]).name == "hype.timeline.json"
    assert Path(forwarded["render_assets"]).name == "hype.assets.json"
    assert (out_dir / "iteration.mp4").read_bytes() == b"rendered-mp4"
    assert not (out_dir / "hype.mp4").exists()
    assert not (out_dir / "_prepare").exists()

    run_record = _read_json(out_dir / "run.json")
    variant_artifacts = [artifact for artifact in run_record["output_artifacts"] if artifact.get("role") == "variant"]
    assert [Path(item["path"]).name for item in variant_artifacts] == [
        "iteration.manifest.json",
        "iteration.mp4",
        "iteration.quality.json",
        "iteration.report.html",
        "iteration.timeline.json",
    ]
    assert {item["group"] for item in variant_artifacts} == {f"iteration-video:{TARGET_RUN_ID}"}
    assert all(item["variant_meta"]["target_run_id"] == TARGET_RUN_ID for item in variant_artifacts)

    groups = _read_json(repo / ".artagents" / "threads" / THREAD_ID / "groups.json")
    group = groups["groups"][f"iteration-video:{TARGET_RUN_ID}"]
    assert len(group["artifacts"]) == 5
    assert {item["run_id"] for item in group["artifacts"]} == {run_record["run_id"]}


def test_iteration_video_inspect_does_not_render_or_summarize_and_suppresses_content(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path
    _write_thread(repo)
    _write_run(
        repo,
        "root",
        _record(ROOT_RUN_ID, output_artifacts=[_artifact("image", "a" * 64)]),
    )
    _write_run(
        repo,
        "target",
        _record(
            TARGET_RUN_ID,
            parent_run_ids=[{"run_id": ROOT_RUN_ID, "kind": "causal"}],
            output_artifacts=[
                _artifact("image", "b" * 64),
                _artifact("model_3d", "c" * 64),
            ],
        ),
    )
    cache_dir = repo / ".artagents" / "iteration_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{ROOT_RUN_ID}__builtin.understand.v1.json").write_text("{}\n", encoding="utf-8")

    def fail_prepare(*args, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("inspect must not summarize")

    def fail_render(*args, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("inspect must not render")

    monkeypatch.setattr(iteration_video.prepare, "prepare_iteration", fail_prepare)
    monkeypatch.setattr(iteration_video, "run_builtin_render", fail_render)

    report = iteration_video.inspect_iteration_thread(repo_root=repo, thread_ref=THREAD_ID, target_run_id=TARGET_RUN_ID)
    text = iteration_video.format_inspection(report, no_content=True)

    assert report["summary_cache"] == {"hits": 1, "misses": 1}
    assert report["detected_modalities"] == ["image", "model_3d"]
    assert {item["renderer"] for item in report["chosen_renderers"]} == {"image_grid", "generic_card"}
    assert "Estimated cost: ~$0.009" in text
    assert "content: suppressed" in text
    assert "SECRET prompt" not in text


def test_iteration_video_orchestrator_declares_no_cut_child() -> None:
    manifest = _read_json(Path("artagents/packs/builtin/iteration_video/orchestrator.yaml"))
    assert manifest["child_executors"] == ["iteration.prepare", "iteration.assemble", "builtin.render"]
    assert "builtin.cut" not in manifest["child_executors"]


def _write_thread(repo: Path) -> None:
    thread = make_thread_record(thread_id=THREAD_ID, label="Logo Sprint")
    thread["run_ids"] = [ROOT_RUN_ID, TARGET_RUN_ID]
    ThreadIndexStore(repo).write({"schema_version": 1, "active_thread_id": THREAD_ID, "threads": {THREAD_ID: thread}})


def _write_prepare_outputs(out_path: Path) -> None:
    out_path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "target_run_id": TARGET_RUN_ID,
        "thread_id": THREAD_ID,
        "runs": [
            {
                "run_id": TARGET_RUN_ID,
                "thread_id": THREAD_ID,
                "label": "in_thread",
                "causal_depth": 0,
                "output_artifacts": [
                    {"kind": "image", "role": "other", "path": "runs/source/image.png", "sha256": "a" * 64, "duration": 4}
                ],
                "summary": {"summary": "SECRET prompt should not appear in no-content output"},
            }
        ],
        "quality": {"data_quality": 0.95},
    }
    quality = {
        "schema_version": 1,
        "target_run_id": TARGET_RUN_ID,
        "data_quality": 0.95,
        "valid_roots": [TARGET_RUN_ID],
        "unresolved_producer_runs": [],
    }
    _write_json(out_path / "iteration.manifest.json", manifest)
    _write_json(out_path / "iteration.quality.json", quality)


def _write_run(repo: Path, slug: str, record: dict) -> None:
    run_dir = repo / "runs" / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "run.json", record)


def _record(
    run_id: str,
    *,
    parent_run_ids: list[dict] | None = None,
    output_artifacts: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "thread_id": THREAD_ID,
        "parent_run_ids": parent_run_ids or [],
        "executor_id": "builtin.generate_image",
        "orchestrator_id": None,
        "kind": "executor",
        "status": "succeeded",
        "returncode": 0,
        "out_path": f"runs/{run_id}",
        "brief_content_sha256": "e" * 64,
        "input_artifacts": [],
        "output_artifacts": output_artifacts or [],
        "provenance": {"contributing_runs": []},
    }


def _artifact(kind: str, sha: str) -> dict:
    return {"kind": kind, "role": "other", "sha256": sha, "path": f"runs/artifact-{sha[:8]}.dat"}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

