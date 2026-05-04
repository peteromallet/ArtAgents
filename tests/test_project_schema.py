from __future__ import annotations

import json
from pathlib import Path

import pytest

from artagents.core.project import paths
from artagents.core.project.project import create_project, show_project
from artagents.core.project.schema import ProjectValidationError, build_placement, run_ref, source_ref, validate_project_timeline
from artagents.core.project.source import add_source, require_source
from artagents.core.project.timeline import add_placement, remove_placement


def test_project_helpers_resolve_env_root_and_write_deterministic_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))
    media = tmp_path / "source.mp4"
    media.write_bytes(b"stub")

    project = create_project("demo", name="Demo")
    source = add_source("demo", "intro", asset={"file": str(media), "type": "video/mp4"})

    project_json = projects_root / "demo" / "project.json"
    source_json = projects_root / "demo" / "sources" / "intro" / "source.json"
    assert project["slug"] == "demo"
    assert json.loads(project_json.read_text(encoding="utf-8"))["name"] == "Demo"
    assert project_json.read_text(encoding="utf-8").endswith("\n")
    assert list(json.loads(source_json.read_text(encoding="utf-8")).keys()) == sorted(json.loads(source_json.read_text(encoding="utf-8")))
    assert source["asset"]["file"] == str(media.resolve())
    assert source["kind"] == "video"
    assert show_project("demo")["sources"] == ["intro"]


def test_project_source_and_placement_validation_rejects_bad_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    create_project("demo")

    with pytest.raises(ValueError):
        create_project("../bad")
    with pytest.raises(ProjectValidationError, match="exactly one"):
        add_source("demo", "bad", asset={"file": str(tmp_path / "a.mp4"), "url": "https://example.com/a.mp4"})
    with pytest.raises(ValueError):
        add_source("demo", "../bad", asset={"url": "https://example.com/a.mp4"})
    with pytest.raises(ProjectValidationError, match="source.kind"):
        add_source("demo", "bad-kind", asset={"url": "https://example.com/a.mp4"}, kind="document")

    source = add_source("demo", "intro", asset={"url": "https://example.com/a.mp4"}, kind="video")
    assert source["kind"] == "video"
    timeline = add_placement("demo", "p1", track="main", at=0, source=source_ref("intro"))
    assert timeline["placements"][0]["source"] == {"kind": "source", "id": "intro"}
    with pytest.raises(FileExistsError):
        add_placement("demo", "p1", track="main", at=1, source=source_ref("intro"))
    with pytest.raises(ProjectValidationError, match="placement.at"):
        build_placement("bad-at", track="main", at=-1, source=source_ref("intro"))
    with pytest.raises(ProjectValidationError, match="placement.from"):
        build_placement("bad-from", track="main", at=0, source=source_ref("intro"), from_=-1)
    with pytest.raises(ProjectValidationError, match="placement.to"):
        build_placement("bad-to", track="main", at=0, source=source_ref("intro"), from_=5, to=2)
    with pytest.raises(ProjectValidationError, match="effects"):
        build_placement("bad-effects", track="main", at=0, source=source_ref("intro"), effects={"not": "a-list"})  # type: ignore[arg-type]
    with pytest.raises(ProjectValidationError, match="params"):
        build_placement("bad-params", track="main", at=0, source=source_ref("intro"), params=[])  # type: ignore[arg-type]

    removed = remove_placement("demo", "p1")
    assert removed["placements"] == []


def test_project_references_validate_source_and_run_forms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    create_project("demo")
    add_source("demo", "intro", asset={"url": "https://example.com/a.mp4"})

    source = require_source("demo", "intro")
    assert source["asset"]["url"] == "https://example.com/a.mp4"
    timeline = {
        "schema_version": 1,
        "project_slug": "demo",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "tracks": [],
        "placements": [
            {"id": "source-p", "track": "main", "at": 0, "source": source_ref("intro")},
            {"id": "run-p", "track": "main", "at": 1, "source": run_ref("01ARZ3NDEKTSV4RRFFQ69G5FAV", "clip-a")},
        ],
    }
    normalized = validate_project_timeline(timeline)
    assert normalized["placements"][1]["source"]["clip_id"] == "clip-a"

    timeline["placements"].append({"id": "run-p", "track": "main", "at": 2, "source": source_ref("intro")})
    with pytest.raises(ProjectValidationError, match="duplicate placement"):
        validate_project_timeline(timeline)
