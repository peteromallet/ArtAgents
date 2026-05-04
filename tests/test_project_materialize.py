from __future__ import annotations

import json
from pathlib import Path

import pytest

from artagents.core.project import paths
from artagents.core.project.materialize import materialize_project_timeline, require_run_clip
from artagents.core.project.project import create_project
from artagents.core.project.run import write_run_record
from artagents.core.project.schema import run_ref, source_ref
from artagents.core.project.source import add_source
from artagents.core.project.timeline import add_placement


def test_source_only_materialization_validates_timeline_and_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    media = tmp_path / "source.mp4"
    media.write_bytes(b"stub")
    create_project("demo")
    add_source("demo", "intro", asset={"file": str(media), "type": "video/mp4", "duration": 12.5})
    add_placement(
        "demo",
        "p1",
        track="main",
        at=1.25,
        from_=2,
        to=6,
        source=source_ref("intro"),
        entrance={"type": "fade", "duration": 0.5},
        exit={"type": "fade", "duration": 0.5},
        effects=[{"fade_in": 0.5}],
        params={"scale": 1},
    )

    config, registry = materialize_project_timeline("demo")

    assert config["clips"] == [
        {
            "id": "p1",
            "track": "main",
            "at": 1.25,
            "clipType": "media",
            "asset": "source:intro",
            "from": 2,
            "to": 6,
            "entrance": {"type": "fade", "duration": 0.5},
            "exit": {"type": "fade", "duration": 0.5},
            "effects": [{"fade_in": 0.5}],
            "params": {"scale": 1},
        }
    ]
    assert registry["assets"]["source:intro"]["file"] == str(media.resolve())


def test_run_placement_materialization_namespaces_asset_and_overrides_clip_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    media = tmp_path / "run.mp4"
    media.write_bytes(b"stub")
    run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    create_project("demo")
    _write_run_artifacts(tmp_path, run_id, media)
    add_placement(
        "demo",
        "placed",
        track="main",
        at=4,
        from_=1,
        to=3,
        source=run_ref(run_id, "clip-a"),
        params={"override": True},
    )

    config, registry = materialize_project_timeline("demo")

    assert config["clips"][0]["id"] == "placed"
    assert config["clips"][0]["track"] == "main"
    assert config["clips"][0]["at"] == 4
    assert config["clips"][0]["from"] == 1
    assert config["clips"][0]["to"] == 3
    assert config["clips"][0]["params"] == {"override": True}
    assert config["clips"][0]["asset"] == f"run:{run_id}:main"
    assert registry["assets"] == {f"run:{run_id}:main": {"file": str(media.resolve()), "type": "video/mp4"}}


def test_run_placement_requires_clip_id_and_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    media = tmp_path / "run.mp4"
    media.write_bytes(b"stub")
    run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    create_project("demo")

    with pytest.raises(FileNotFoundError, match="run not found"):
        require_run_clip("demo", run_id, "clip-a")

    write_run_record("demo", run_id, tool_id="test.tool", kind="executor", status="success")
    with pytest.raises(FileNotFoundError, match="run timeline not found"):
        require_run_clip("demo", run_id, "clip-a")

    run_root = tmp_path / "projects" / "demo" / "runs" / run_id
    (run_root / "timeline.json").write_text(
        json.dumps({"theme": "banodoco-default", "clips": [{"id": "clip-a", "track": "source", "at": 0, "clipType": "media", "asset": "main"}]}),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError, match="run assets not found"):
        require_run_clip("demo", run_id, "clip-a")

    (run_root / "assets.json").write_text(json.dumps({"assets": {"main": {"file": str(media.resolve()), "type": "video/mp4"}}}), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="Available clip ids: clip-a"):
        require_run_clip("demo", run_id, "missing")


def test_run_placement_missing_asset_reference_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    create_project("demo")
    write_run_record("demo", run_id, tool_id="test.tool", kind="executor", status="success")
    run_root = tmp_path / "projects" / "demo" / "runs" / run_id
    (run_root / "timeline.json").write_text(
        json.dumps({"theme": "banodoco-default", "clips": [{"id": "clip-a", "track": "source", "at": 0, "clipType": "media", "asset": "missing"}]}),
        encoding="utf-8",
    )
    (run_root / "assets.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
    add_placement("demo", "placed", track="main", at=0, source=run_ref(run_id, "clip-a"))

    with pytest.raises(FileNotFoundError, match="assets.json"):
        materialize_project_timeline("demo")


def _write_run_artifacts(tmp_path: Path, run_id: str, media: Path) -> None:
    write_run_record("demo", run_id, tool_id="test.tool", kind="executor", status="success")
    run_root = tmp_path / "projects" / "demo" / "runs" / run_id
    (run_root / "timeline.json").write_text(
        json.dumps(
            {
                "theme": "banodoco-default",
                "clips": [
                    {
                        "id": "clip-a",
                        "track": "source",
                        "at": 0,
                        "clipType": "media",
                        "asset": "main",
                        "from": 0,
                        "to": 5,
                        "params": {"keep": True},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (run_root / "assets.json").write_text(json.dumps({"assets": {"main": {"file": str(media.resolve()), "type": "video/mp4"}}}), encoding="utf-8")
