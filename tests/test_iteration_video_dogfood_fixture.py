import contextlib
import io
import json
import shutil
from pathlib import Path

from artagents.packs.builtin.iteration_video import run as iteration_video
from artagents.threads.attribute import AttributionDecision, infer_lineage_thread_id
from artagents.threads.cli import main as thread_cli
from artagents.threads.index import ThreadIndexStore
from artagents.threads.prefix import format_prefix_lines
from artagents.threads.variants import keep_selection, variant_prefix_message


FIXTURE = Path("tests/fixtures/iteration_video")
THREAD_ID = "01ARZ3NDEKTSV4RRFFQ69G5FX0"
ROOT_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FX1"
VARIANT_A_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FX2"
VARIANT_B_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FX3"
TARGET_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FX4"


def test_dogfood_fixture_backfill_active_thread_no_content_and_local_path_policy(tmp_path: Path, monkeypatch) -> None:
    repo = _install_fixture(tmp_path)
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        assert thread_cli(["backfill"]) == 0

    assert "backfilled run_records=4" in stdout.getvalue()
    assert (repo / "runs" / "artagents_logo_v3_orphan" / "note.txt").is_file()

    index = ThreadIndexStore(repo).read()
    assert index["active_thread_id"] == THREAD_ID
    assert index["threads"][THREAD_ID]["label"] == "artagents_logo_v3"
    assert index["threads"][THREAD_ID]["run_ids"] == [ROOT_RUN_ID, VARIANT_A_RUN_ID, VARIANT_B_RUN_ID, TARGET_RUN_ID]

    show = io.StringIO()
    with contextlib.redirect_stdout(show):
        assert thread_cli(["show", "@active", "--no-content"]) == 0
    shown = show.getvalue()
    assert "Thread: artagents_logo_v3" in shown
    assert "output:" not in shown
    assert "Synthetic orphan note" not in shown

    assert "runs/" in Path(".gitignore").read_text(encoding="utf-8").splitlines()
    assert not any(path.suffix in {".mp4", ".mov", ".wav", ".mp3"} for path in FIXTURE.rglob("*"))


def test_dogfood_fixture_inspect_report_and_fallback_without_render_or_summarize(tmp_path: Path, monkeypatch) -> None:
    repo = _install_fixture(tmp_path)

    def fail_prepare(*args, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("inspect must not summarize")

    def fail_render(*args, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("inspect must not render")

    monkeypatch.setattr(iteration_video.prepare, "prepare_iteration", fail_prepare)
    monkeypatch.setattr(iteration_video, "run_builtin_render", fail_render)

    report = iteration_video.inspect_iteration_thread(repo_root=repo, thread_ref=THREAD_ID, target_run_id=TARGET_RUN_ID)
    text = iteration_video.format_inspection(report, no_content=True)

    assert report["detected_modalities"] == ["audio", "image", "model_3d"]
    renderers = {(item["kind"], item["renderer"], item["fallback"]) for item in report["chosen_renderers"]}
    assert ("image", "image_grid", False) in renderers
    assert ("audio", "audio_waveform", False) in renderers
    assert ("model_3d", "generic_card", True) in renderers
    assert report["quality"]["data_quality"] == 1.0
    assert report["summary_cache"] == {"hits": 0, "misses": 4}
    assert report["cost_estimate"]["estimated_cost"] == 0.036
    assert "Estimated cost: ~$0.036" in text
    assert "content: suppressed" in text
    assert "artagents_logo_v3" in text


def test_dogfood_fixture_render_handoff_outputs_sidecar_report_and_no_cut(tmp_path: Path, monkeypatch) -> None:
    repo = _install_fixture(tmp_path)
    out_dir = repo / "runs" / "artagents_logo_v3_iteration"
    render_inputs: dict[str, Path] = {}

    def fake_render(brief_out: Path) -> Path:
        render_inputs["timeline"] = brief_out / "hype.timeline.json"
        render_inputs["assets"] = brief_out / "hype.assets.json"
        assert render_inputs["timeline"].is_file()
        assert render_inputs["assets"].is_file()
        hype_mp4 = brief_out / "hype.mp4"
        hype_mp4.write_bytes(b"fixture-render")
        return hype_mp4

    monkeypatch.setattr(iteration_video, "run_builtin_render", fake_render)

    result = iteration_video.run_iteration_video(
        repo_root=repo,
        out_path=out_dir,
        thread_ref=THREAD_ID,
        target_run_id=TARGET_RUN_ID,
        max_iterations=10,
        direction="fixture",
        clip_mode="hold",
        renderers="auto",
        no_content=True,
    )

    assert Path(result["outputs"]["iteration.mp4"]).read_bytes() == b"fixture-render"
    assert not (out_dir / "hype.mp4").exists()
    assert render_inputs["timeline"].name == "hype.timeline.json"
    assert render_inputs["assets"].name == "hype.assets.json"

    expected = {"iteration.mp4", "iteration.timeline.json", "iteration.manifest.json", "iteration.report.html", "iteration.quality.json"}
    assert expected == {path.name for path in map(Path, result["outputs"].values())}
    assert expected <= {path.name for path in out_dir.iterdir()}

    manifest = _read_json(out_dir / "iteration.manifest.json")
    assert manifest["iteration_video"]["no_content"] is True
    assert manifest["assembly"]["direction_label"] == "fixture"
    assert "renderer-fallback" in (out_dir / "iteration.report.html").read_text(encoding="utf-8")

    sidecar = _read_json(out_dir / ".artagents.variants.json")
    artifacts = sidecar["artifacts"]
    assert len(artifacts) == 5
    assert {item["group"] for item in artifacts} == {f"iteration-video:{TARGET_RUN_ID}"}
    assert {item["variant_meta"]["target_run_id"] for item in artifacts} == {TARGET_RUN_ID}
    assert all(item["variant_meta"]["fallback_diagnostics"] for item in artifacts)

    orchestrator = _read_json(Path("artagents/packs/builtin/iteration_video/orchestrator.yaml"))
    assert orchestrator["child_executors"] == ["iteration.prepare", "iteration.assemble", "builtin.render"]
    assert "builtin.cut" not in json.dumps(orchestrator)


def test_dogfood_fixture_prefix_lineage_variant_nag_silence_and_prerender_transcript(tmp_path: Path) -> None:
    repo = _install_fixture(tmp_path)
    request = type(
        "Request",
        (),
        {"brief": None, "from_ref": None, "inputs": {"source": "runs/artagents_logo_v3_variant_a/run.json"}, "orchestrator_args": ()},
    )()
    assert infer_lineage_thread_id(repo, request) == THREAD_ID

    nag = variant_prefix_message(repo, THREAD_ID)
    assert nag is not None
    prefix = format_prefix_lines(
        AttributionDecision(thread_id=THREAD_ID, label="artagents_logo_v3", source="fixture", run_number=4),
        variants_message=nag,
    )
    assert prefix[0].startswith("[thread] artagents_logo_v3")
    assert prefix[1].startswith("[variants] 1 unresolved variant group")

    keep_selection(repo, THREAD_ID, f"{VARIANT_A_RUN_ID}:1")
    assert variant_prefix_message(repo, THREAD_ID) is None

    transcript = (FIXTURE / "dogfood_transcript.txt").read_text(encoding="utf-8")
    assert "[thread]" in transcript
    assert "[variants]" in transcript
    assert "thread show @active --no-content" in transcript
    assert "iteration_video.run inspect" in transcript


def _install_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURE / "repo_runs", repo / "runs")
    state_dir = repo / ".artagents"
    state_dir.mkdir()
    shutil.copyfile(FIXTURE / "state" / "threads.json", state_dir / "threads.json")
    thread_dir = state_dir / "threads" / THREAD_ID
    thread_dir.mkdir(parents=True)
    shutil.copyfile(FIXTURE / "state" / "thread_groups.json", thread_dir / "groups.json")
    return repo


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
