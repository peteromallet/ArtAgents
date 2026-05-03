import json
from pathlib import Path

import pytest

from artagents.executors.iteration_assemble import run as assemble


RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FG0"


def test_assemble_emits_iteration_and_render_equivalent_hype_files(tmp_path: Path) -> None:
    prepare_dir = _write_prepare_outputs(tmp_path, data_quality=0.95)
    out_dir = tmp_path / "assembled"

    result = assemble.assemble_iteration(
        prepare_dir=prepare_dir,
        out_path=out_dir,
        repo_root=tmp_path,
        direction="gentle retrospective",
    )

    assert Path(result["timeline_path"]).is_file()
    assert Path(result["hype_timeline_path"]).is_file()
    assert Path(result["hype_assets_path"]).is_file()
    assert (out_dir / "iteration.report.html").is_file()
    assert _read_json(out_dir / "iteration.timeline.json") == _read_json(out_dir / "hype.timeline.json")
    manifest = _read_json(out_dir / "iteration.manifest.json")
    assert manifest["assembly"]["direction_label"] == "gentle retrospective"
    assert manifest["assembly"]["style_source"] == "direction-label"
    assert manifest["assembly"]["renderer_decisions"][0]["renderer"] == "image_grid"
    assert manifest["assembly"]["renderer_decisions"][1]["renderer"] == "audio_waveform"
    assert manifest["assembly"]["renderer_decisions"][2]["renderer"] == "generic_card"
    assert "renderer-fallback: no renderer for kind:model_3d" in result["diagnostics"]
    assert '<aside class="renderer-fallback">no renderer for kind:model_3d</aside>' in (out_dir / "iteration.report.html").read_text(encoding="utf-8")


def test_style_audio_and_mode_behavior(tmp_path: Path) -> None:
    prepare_dir = _write_prepare_outputs(tmp_path, data_quality=0.95)
    out_dir = tmp_path / "assembled"

    assemble.assemble_iteration(
        prepare_dir=prepare_dir,
        out_path=out_dir,
        repo_root=tmp_path,
        theme="banodoco-default",
        direction="kept as label",
    )

    manifest = _read_json(out_dir / "iteration.manifest.json")
    assert manifest["assembly"]["style_source"] == "theme"
    assert manifest["assembly"]["direction_label"] == "kept as label"
    assert manifest["assembly"]["audio_bed"] == "iterations-as-bed"
    with pytest.raises(assemble.AssembleError, match="only --mode chaptered"):
        assemble.assemble_iteration(prepare_dir=prepare_dir, out_path=tmp_path / "bad", repo_root=tmp_path, mode="parallel")
    with pytest.raises(assemble.AssembleError, match="never generates music"):
        assemble.assemble_iteration(prepare_dir=prepare_dir, out_path=tmp_path / "bad2", repo_root=tmp_path, audio_bed="generated_music")


def test_assemble_outputs_do_not_depend_on_deferred_preview_modes(tmp_path: Path) -> None:
    prepare_dir = _write_prepare_outputs(tmp_path, data_quality=0.95)
    out_dir = tmp_path / "assembled"

    assemble.assemble_iteration(prepare_dir=prepare_dir, out_path=out_dir, repo_root=tmp_path)

    combined = "\n".join(path.read_text(encoding="utf-8") for path in out_dir.glob("*.json"))
    assert "preview_modes" not in combined


def _write_prepare_outputs(tmp_path: Path, *, data_quality: float) -> Path:
    prepare_dir = tmp_path / "prepare"
    prepare_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "target_run_id": RUN_ID,
        "thread_id": "01ARZ3NDEKTSV4RRFFQ69G5FG1",
        "runs": [
            {
                "run_id": RUN_ID,
                "thread_id": "01ARZ3NDEKTSV4RRFFQ69G5FG1",
                "label": "in_thread",
                "causal_depth": 0,
                "output_artifacts": [
                    {"kind": "image", "role": "other", "path": "runs/source/image.png", "sha256": "a" * 64, "duration": 4},
                    {"kind": "audio", "role": "other", "path": "runs/source/audio.wav", "sha256": "b" * 64, "duration": 5},
                    {"kind": "model_3d", "role": "other", "path": "runs/source/model.glb", "sha256": "c" * 64, "duration": 2},
                ],
                "summary": {"summary": "prepared summary"},
            }
        ],
        "quality": {"data_quality": data_quality},
    }
    quality = {
        "schema_version": 1,
        "target_run_id": RUN_ID,
        "data_quality": data_quality,
        "valid_roots": [],
        "unresolved_producer_runs": [],
    }
    _write_json(prepare_dir / "iteration.manifest.json", manifest)
    _write_json(prepare_dir / "iteration.quality.json", quality)
    return prepare_dir


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
