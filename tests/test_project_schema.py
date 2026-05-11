"""Project / source / run schema tests (T10 collapsed the placement schema).

The pre-T10 file also covered build_placement / source_ref / run_ref /
validate_project_timeline / add_placement / remove_placement. Those symbols
are gone with the parallel placement schema; T13 tests the canonical timeline
contract end-to-end through SupabaseDataProvider.save_timeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.project import paths
from astrid.core.project.project import create_project, show_project
from astrid.core.project.schema import (
    PROJECT_SCHEMA_VERSION,
    ProjectValidationError,
    SOURCE_KINDS,
    SOURCE_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    build_project,
    build_run_record,
    build_source,
    validate_project,
    validate_run_record,
    validate_source,
)
from astrid.core.project.source import add_source, require_source


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
    assert source["asset"]["file"] == str(media.resolve())
    assert source["kind"] == "video"
    assert show_project("demo")["sources"] == ["intro"]


def test_create_project_does_not_write_timeline_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10 invariant: timeline.json is no longer written; sources/ + runs/ still are."""

    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))
    create_project("demo")
    project_dir = projects_root / "demo"
    assert (project_dir / "project.json").is_file()
    assert (project_dir / "sources").is_dir()
    assert (project_dir / "runs").is_dir()
    assert not (project_dir / "timeline.json").exists()


def test_project_id_field_is_optional_opaque_in_project_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(projects_root))

    plain = create_project("demo")
    assert "project_id" not in plain

    with_id = create_project("demo2", project_id="00000000-1111-2222-3333-444455556666")
    assert with_id["project_id"] == "00000000-1111-2222-3333-444455556666"

    # Empty / non-string project_id -> validation error.
    with pytest.raises(ProjectValidationError, match="project_id"):
        validate_project({**with_id, "project_id": ""})


def test_source_validation_rejects_bad_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path / "projects"))
    create_project("demo")

    with pytest.raises(ProjectValidationError, match="exactly one"):
        add_source("demo", "bad", asset={"file": str(tmp_path / "a.mp4"), "url": "https://example.com/a.mp4"})
    with pytest.raises(ValueError):
        add_source("demo", "../bad", asset={"url": "https://example.com/a.mp4"})
    with pytest.raises(ProjectValidationError, match="source.kind"):
        add_source("demo", "bad-kind", asset={"url": "https://example.com/a.mp4"}, kind="document")

    source = add_source("demo", "intro", asset={"url": "https://example.com/a.mp4"}, kind="video")
    assert source["kind"] == "video"
    assert require_source("demo", "intro")["asset"]["url"] == "https://example.com/a.mp4"


def test_build_and_validate_run_record_round_trip() -> None:
    record = build_run_record(
        "demo",
        "01HXYZ",
        tool_id="my-tool",
        kind="custom",
        status="prepared",
        argv=["--flag", "value"],
        metadata={"baseline_snapshot": "abc"},
    )
    normalized = validate_run_record(record)
    assert normalized["status"] == "prepared"
    assert normalized["argv"] == ["--flag", "value"]
    assert normalized["metadata"]["baseline_snapshot"] == "abc"
    assert normalized["schema_version"] == RUN_SCHEMA_VERSION


def test_run_record_status_must_be_known() -> None:
    record = build_run_record("demo", "01HXYZ", status="prepared")
    record["status"] = "garbage"
    with pytest.raises(ProjectValidationError, match="run.status"):
        validate_run_record(record)


def test_schema_constants_are_versioned() -> None:
    assert isinstance(PROJECT_SCHEMA_VERSION, int)
    assert isinstance(SOURCE_SCHEMA_VERSION, int)
    assert isinstance(RUN_SCHEMA_VERSION, int)
    assert {"audio", "image", "other", "video"} == SOURCE_KINDS


def test_build_project_emits_required_keys() -> None:
    payload = build_project("demo", name="Demo")
    expected = {"created_at", "name", "schema_version", "slug", "updated_at"}
    assert expected.issubset(payload.keys())
    validated = validate_project(payload)
    assert validated["slug"] == "demo"


def test_default_timeline_id_round_trip_none() -> None:
    """Sprint 1 sentinel: build emits the key explicitly with None."""

    payload = build_project("demo")
    assert "default_timeline_id" in payload
    assert payload["default_timeline_id"] is None
    validated = validate_project(payload)
    assert validated["default_timeline_id"] is None


def test_default_timeline_id_round_trip_slug() -> None:
    payload = build_project("demo", default_timeline_id="primary")
    assert payload["default_timeline_id"] == "primary"
    validated = validate_project(payload)
    assert validated["default_timeline_id"] == "primary"


def test_default_timeline_id_rejects_malformed() -> None:
    base = build_project("demo")
    # Non-string, non-None.
    with pytest.raises(ProjectValidationError, match="default_timeline_id"):
        validate_project({**base, "default_timeline_id": 42})
    # Empty string fails slug regex.
    with pytest.raises((ProjectValidationError, ValueError), match="default_timeline_id|project slug"):
        validate_project({**base, "default_timeline_id": ""})
    # Invalid slug shape.
    with pytest.raises((ProjectValidationError, ValueError), match="default_timeline_id|project slug"):
        validate_project({**base, "default_timeline_id": "Bad Slug!"})


def test_legacy_project_json_without_default_timeline_id_still_validates() -> None:
    """Files written before Sprint 1 lack the key entirely — validator must accept them."""

    legacy = build_project("demo")
    legacy.pop("default_timeline_id", None)
    validated = validate_project(legacy)
    assert "default_timeline_id" not in validated
    assert validated["slug"] == "demo"
