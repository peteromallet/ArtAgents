"""Tests for astrid.core.timeline.crud — full CRUD lifecycle against a temp project tree."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.timeline.crud import (
    TimelineCrudError,
    create_timeline,
    finalize_output,
    list_timelines,
    purge_timeline,
    rename_timeline,
    set_default,
    show_timeline,
    tombstone_timeline,
)
from astrid.core.timeline.paths import timelines_dir
from astrid.threads.ids import generate_ulid, is_ulid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_tree(tmp_projects_root: Path) -> Path:
    """Seed a minimal project under the monkeypatched ARTAGENTS_PROJECTS_ROOT."""
    import json

    slug = "demo"
    pdir = tmp_projects_root / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "runs").mkdir()
    (pdir / "sources").mkdir()
    (pdir / "project.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-11T00:00:00Z",
                "name": slug,
                "schema_version": 1,
                "slug": slug,
                "updated_at": "2026-05-11T00:00:00Z",
                "default_timeline_id": None,
            }
        ),
        encoding="utf-8",
    )
    return tmp_projects_root


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreateTimeline:
    def test_creates_timeline_with_all_three_files(self, project_tree: Path) -> None:
        result = create_timeline("demo", "primary", name="Primary Timeline")
        ulid = result["ulid"]
        assert is_ulid(ulid)

        tdir = project_tree / "demo" / "timelines" / ulid
        assert tdir.is_dir()
        assert (tdir / "assembly.json").is_file()
        assert (tdir / "manifest.json").is_file()
        assert (tdir / "display.json").is_file()

        from astrid.core.timeline.model import Display

        display = Display.from_json(tdir / "display.json")
        assert display.slug == "primary"
        assert display.name == "Primary Timeline"

    def test_refuses_duplicate_slug(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        with pytest.raises(TimelineCrudError, match="already exists"):
            create_timeline("demo", "primary")

    def test_creates_with_is_default(self, project_tree: Path) -> None:
        result = create_timeline("demo", "default", is_default=True)
        from astrid.core.project.project import load_project

        project = load_project("demo")
        assert project["default_timeline_id"] == result["ulid"]

    def test_rejects_invalid_slug(self, project_tree: Path) -> None:
        from astrid.core.project.paths import ProjectPathError

        with pytest.raises(ProjectPathError):
            create_timeline("demo", "BAD_SLUG")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestListTimelines:
    def test_returns_empty_list_when_no_timelines(self, project_tree: Path) -> None:
        assert list_timelines("demo") == []

    def test_lists_all_timelines(self, project_tree: Path) -> None:
        create_timeline("demo", "alpha")
        create_timeline("demo", "beta")
        create_timeline("demo", "gamma")
        rows = list_timelines("demo")
        assert len(rows) == 3
        slugs = {r.slug for r in rows}
        assert slugs == {"alpha", "beta", "gamma"}

    def test_lists_timelines_with_correct_counts(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        rows = list_timelines("demo")
        assert len(rows) == 1
        r = rows[0]
        assert r.run_count == 0
        assert r.final_output_count == 0
        assert r.last_finalized is None

    def test_shows_default_flag(self, project_tree: Path) -> None:
        create_timeline("demo", "alpha")
        result = create_timeline("demo", "beta", is_default=True)
        rows = list_timelines("demo")
        for r in rows:
            if r.ulid == result["ulid"]:
                assert r.is_default is True
            else:
                assert r.is_default is False


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------


class TestShowTimeline:
    def test_returns_none_for_missing_slug(self, project_tree: Path) -> None:
        assert show_timeline("demo", "nonexistent") is None

    def test_returns_full_record(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        data = show_timeline("demo", "primary")
        assert data is not None
        assert "ulid" in data
        assert "display" in data
        assert "assembly" in data
        assert "manifest" in data
        assert data["display"].slug == "primary"


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------


class TestRenameTimeline:
    def test_renames_slug(self, project_tree: Path) -> None:
        create_timeline("demo", "alpha")
        result = rename_timeline("demo", "alpha", "beta")
        assert result["slug"] == "beta"
        assert result["display"].slug == "beta"

        # Old slug no longer finds the timeline.
        assert find_timeline_by_slug("demo", "alpha") is None
        # New slug does.
        assert find_timeline_by_slug("demo", "beta") is not None

    def test_refuses_collision(self, project_tree: Path) -> None:
        create_timeline("demo", "alpha")
        create_timeline("demo", "beta")
        with pytest.raises(TimelineCrudError, match="already exists"):
            rename_timeline("demo", "alpha", "beta")

    def test_refuses_missing_slug(self, project_tree: Path) -> None:
        with pytest.raises(TimelineCrudError, match="not found"):
            rename_timeline("demo", "nonexistent", "new")


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


class TestFinalizeOutput:
    def test_finalize_captures_sha256_and_size(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        f = project_tree / "output.mp4"
        f.write_bytes(b"final render content goes here")

        fo = finalize_output(
            "demo", "primary", str(f),
            kind="mp4",
            recorded_by="agent:claude-1",
        )
        assert fo.kind == "mp4"
        assert fo.check_status == "ok"
        assert fo.check_at == fo.recorded_at
        assert fo.size == len(b"final render content goes here")
        assert len(fo.sha256) == 64

        # Manifest now has one final output.
        data = show_timeline("demo", "primary")
        assert data is not None
        assert len(data["manifest"].final_outputs) == 1

    def test_lists_updated_counts(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        f = project_tree / "output.mp4"
        f.write_bytes(b"content")
        finalize_output("demo", "primary", str(f), kind="mp4")
        rows = list_timelines("demo")
        assert rows[0].final_output_count == 1
        assert rows[0].last_finalized is not None

    def test_refuses_missing_file(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        with pytest.raises(TimelineCrudError, match="output file not found"):
            finalize_output("demo", "primary", str(project_tree / "nonexistent.mp4"))

    def test_refuses_missing_timeline(self, project_tree: Path) -> None:
        f = project_tree / "out.mp4"
        f.write_bytes(b"x")
        with pytest.raises(TimelineCrudError, match="not found"):
            finalize_output("demo", "nonexistent", str(f))

    def test_multiple_final_outputs(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        f1 = project_tree / "out1.mp4"
        f2 = project_tree / "out2.mp4"
        f1.write_bytes(b"first")
        f2.write_bytes(b"second")
        finalize_output("demo", "primary", str(f1), kind="mp4")
        finalize_output("demo", "primary", str(f2), kind="transcript")
        data = show_timeline("demo", "primary")
        assert data is not None
        assert len(data["manifest"].final_outputs) == 2
        kinds = {fo.kind for fo in data["manifest"].final_outputs}
        assert kinds == {"mp4", "transcript"}


# ---------------------------------------------------------------------------
# Tombstone
# ---------------------------------------------------------------------------


class TestTombstoneTimeline:
    def test_tombstone_sets_tombstoned_at(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        result = tombstone_timeline("demo", "primary")
        assert result["tombstoned_at"] is not None

        # Manifest now has tombstoned_at set.
        data = show_timeline("demo", "primary")
        assert data is not None
        assert data["manifest"].tombstoned_at is not None

    def test_refuses_double_tombstone(self, project_tree: Path) -> None:
        create_timeline("demo", "primary")
        tombstone_timeline("demo", "primary")
        with pytest.raises(TimelineCrudError, match="already tombstoned"):
            tombstone_timeline("demo", "primary")

    def test_refuses_missing_timeline(self, project_tree: Path) -> None:
        with pytest.raises(TimelineCrudError, match="not found"):
            tombstone_timeline("demo", "nonexistent")


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------


class TestPurgeTimeline:
    def test_purge_removes_directory(self, project_tree: Path) -> None:
        result = create_timeline("demo", "primary")
        ulid = result["ulid"]
        tdir = project_tree / "demo" / "timelines" / ulid
        assert tdir.exists()
        purge_timeline("demo", "primary")
        assert not tdir.exists()

    def test_refuses_purge_of_default(self, project_tree: Path) -> None:
        create_timeline("demo", "alpha")
        create_timeline("demo", "beta", is_default=True)
        with pytest.raises(TimelineCrudError, match="project default"):
            purge_timeline("demo", "beta")

    def test_refuses_missing_timeline(self, project_tree: Path) -> None:
        with pytest.raises(TimelineCrudError, match="not found"):
            purge_timeline("demo", "nonexistent")


# ---------------------------------------------------------------------------
# Set default
# ---------------------------------------------------------------------------


class TestSetDefault:
    def test_sets_default(self, project_tree: Path) -> None:
        create_timeline("demo", "alpha")
        result = set_default("demo", "alpha")
        assert result["display"].is_default is True

        from astrid.core.project.project import load_project

        project = load_project("demo")
        assert project["default_timeline_id"] == result["ulid"]

    def test_clears_old_default(self, project_tree: Path) -> None:
        a = create_timeline("demo", "alpha", is_default=True)
        b = create_timeline("demo", "beta")

        set_default("demo", "beta")

        # Old default is cleared.
        from astrid.core.timeline.model import Display

        for ulid in [a["ulid"], b["ulid"]]:
            dp = project_tree / "demo" / "timelines" / ulid / "display.json"
            display = Display.from_json(dp)
            if ulid == b["ulid"]:
                assert display.is_default is True
            else:
                assert display.is_default is False

    def test_refuses_missing_timeline(self, project_tree: Path) -> None:
        with pytest.raises(TimelineCrudError, match="not found"):
            set_default("demo", "nonexistent")


# ---------------------------------------------------------------------------
# Helper import for local scope
# ---------------------------------------------------------------------------


def find_timeline_by_slug(project_slug: str, slug: str) -> object:
    """Import inside function for local use."""
    from astrid.core.timeline.paths import find_timeline_by_slug as _find

    return _find(project_slug, slug)