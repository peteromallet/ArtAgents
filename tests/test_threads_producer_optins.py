from __future__ import annotations

from pathlib import Path

from artagents.packs.builtin.generate_image.run import _variant_artifacts_for_generated_images
from artagents.packs.builtin.logo_ideas.run import _variant_artifacts_for_logo_ideas


def test_generate_image_variant_artifact_metadata() -> None:
    artifacts = _variant_artifacts_for_generated_images(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        prompt_index=2,
        prompt="make a mark",
        payload={"model": "gpt-image-2", "size": "1024x1024", "quality": "medium", "output_format": "png"},
        response={"created": 123},
        paths=["/tmp/one.png", "/tmp/two.png"],
    )

    assert [item["role"] for item in artifacts] == ["variant", "variant"]
    assert artifacts[0]["group"] == artifacts[1]["group"]
    assert [item["group_index"] for item in artifacts] == [1, 2]
    assert artifacts[0]["variant_meta"]["prompt"] == "make a mark"


def test_logo_ideas_variant_artifact_metadata() -> None:
    artifacts = _variant_artifacts_for_logo_ideas(
        [
            {
                "candidate_id": "logo-001",
                "name": "One",
                "rationale": "Because",
                "prompt": "mark",
                "generated": {"path": "/tmp/logo.png", "width": 100},
            }
        ],
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
    )

    assert artifacts[0]["role"] == "variant"
    assert artifacts[0]["group_index"] == 1
    assert artifacts[0]["variant_meta"]["name"] == "One"
    assert artifacts[0]["variant_meta"]["generated"]["width"] == 100


def test_only_allowed_run_py_files_opt_into_variants() -> None:
    repo = Path(__file__).resolve().parents[1]
    allowed = {
        repo / "artagents" / "executors" / "generate_image" / "run.py",
        repo / "artagents" / "orchestrators" / "logo_ideas" / "run.py",
    }
    offenders = []
    for run_py in list((repo / "artagents" / "executors").glob("*/run.py")) + list((repo / "artagents" / "orchestrators").glob("*/run.py")):
        text = run_py.read_text(encoding="utf-8")
        if "write_variant_sidecar" in text or "variant_meta" in text:
            if run_py not in allowed:
                offenders.append(run_py.relative_to(repo).as_posix())
    assert offenders == []
