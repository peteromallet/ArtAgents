"""Tests for scripts/migrations/sprint-2/migrate_timelines.py — fixture shapes and assertions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from astrid.threads.ids import generate_ulid, is_ulid

# ---------------------------------------------------------------------------
# Path to the migration script
# ---------------------------------------------------------------------------

_MIGRATION_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts" / "migrations" / "sprint-2" / "migrate_timelines.py"
)


def _run_migration(root: Path, *, apply: bool = False, force: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_MIGRATION_SCRIPT), "--root", str(root)]
    if apply:
        cmd.append("--apply")
    if force:
        cmd.append("--force")
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_project(root: Path, slug: str) -> Path:
    pdir = root / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "runs").mkdir(exist_ok=True)
    (pdir / "sources").mkdir(exist_ok=True)
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
    return pdir


def _add_legacy_project_timeline(pdir: Path, content: dict | None = None) -> None:
    (pdir / "timeline.json").write_text(
        json.dumps(
            content or {"version": 1, "tracks": [], "duration": 0}
        ),
        encoding="utf-8",
    )


def _add_run(pdir: Path, run_id: str, *, with_run_json: bool = True, with_legacy_timeline: bool = False) -> Path:
    rdir = pdir / "runs" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "plan.json").write_text("{}", encoding="utf-8")
    (rdir / "events.jsonl").write_text("", encoding="utf-8")
    if with_run_json:
        (rdir / "run.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_slug": pdir.name,
                    "run_id": run_id,
                    "kind": "custom",
                    "status": "prepared",
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
    if with_legacy_timeline:
        (rdir / "timeline.json").write_text(
            json.dumps({"version": 1, "elements": ["intro", "outro"]}),
            encoding="utf-8",
        )
    return rdir


# ---------------------------------------------------------------------------
# Test: neither project nor run legacy files → no-op
# ---------------------------------------------------------------------------


class TestNeitherLegacy:
    def test_dry_run_exits_zero_without_writing(self, tmp_path: Path) -> None:
        _seed_project(tmp_path, "demo")
        result = _run_migration(tmp_path, apply=False)
        assert result.returncode == 0
        assert "nothing to migrate" in result.stderr.lower() or "processing" in result.stderr

    def test_apply_no_op(self, tmp_path: Path) -> None:
        _seed_project(tmp_path, "demo")
        result = _run_migration(tmp_path, apply=True)
        assert result.returncode == 0
        # No timelines/ dir should have been created.
        tdir = tmp_path / "demo" / "timelines"
        assert not tdir.exists() or not any(tdir.iterdir())


# ---------------------------------------------------------------------------
# Test: project-only legacy file
# ---------------------------------------------------------------------------


class TestProjectOnlyLegacy:
    def test_dry_run_exits_zero(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        _add_legacy_project_timeline(pdir)
        result = _run_migration(tmp_path, apply=False)
        assert result.returncode == 0
        assert "would-set-default-timeline-id" in result.stderr

    def test_apply_creates_new_shape(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        _add_legacy_project_timeline(pdir, {"version": 1, "elements": ["intro"]})
        result = _run_migration(tmp_path, apply=True)
        assert result.returncode == 0

        tdir = tmp_path / "demo" / "timelines"
        assert tdir.is_dir()
        children = list(tdir.iterdir())
        assert len(children) == 1
        ulid = children[0].name
        assert is_ulid(ulid)

        # Check files exist.
        assert (children[0] / "assembly.json").is_file()
        assert (children[0] / "manifest.json").is_file()
        assert (children[0] / "display.json").is_file()

        # Legacy file is removed.
        assert not (pdir / "timeline.json").exists()

        # Assembly content preserved.
        assembly = json.loads((children[0] / "assembly.json").read_text())
        assert assembly["assembly"] == {"version": 1, "elements": ["intro"]}

        # Display says default.
        display = json.loads((children[0] / "display.json").read_text())
        assert display["slug"] == "default"
        assert display["name"] == "Default"
        assert display["is_default"] is True

        # Project default set.
        project = json.loads((pdir / "project.json").read_text())
        assert project["default_timeline_id"] == ulid


# ---------------------------------------------------------------------------
# Test: run-only legacy files
# ---------------------------------------------------------------------------


class TestRunOnlyLegacy:
    def test_apply_creates_timeline_and_sets_run_links(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        run_a = generate_ulid()
        run_b = generate_ulid()
        _add_run(pdir, run_a, with_legacy_timeline=True)
        _add_run(pdir, run_b, with_legacy_timeline=True)
        result = _run_migration(tmp_path, apply=True)
        assert result.returncode == 0

        tdir = tmp_path / "demo" / "timelines"
        assert tdir.is_dir()

        # One timeline created to host the runs.
        children = list(tdir.iterdir())
        assert len(children) == 1
        ulid = children[0].name
        assert is_ulid(ulid)

        # Manifest has contributing runs.
        manifest = json.loads((children[0] / "manifest.json").read_text())
        assert set(manifest["contributing_runs"]) == {run_a, run_b}

        # run.json files updated.
        for run_id in [run_a, run_b]:
            rj = pdir / "runs" / run_id / "run.json"
            run_data = json.loads(rj.read_text())
            assert run_data["timeline_id"] == ulid

        # Project default set.
        project = json.loads((pdir / "project.json").read_text())
        assert project["default_timeline_id"] == ulid


# ---------------------------------------------------------------------------
# Test: both project and run legacy files
# ---------------------------------------------------------------------------


class TestBothLegacy:
    def test_apply_preserves_both_sources(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        _add_legacy_project_timeline(pdir, {"project_level": True})
        run_id = generate_ulid()
        _add_run(pdir, run_id, with_legacy_timeline=True)
        result = _run_migration(tmp_path, apply=True)
        assert result.returncode == 0

        tdir = tmp_path / "demo" / "timelines"
        children = list(tdir.iterdir())
        assert len(children) == 1
        ulid = children[0].name

        # Assembly came from project-level file.
        assembly = json.loads((children[0] / "assembly.json").read_text())
        assert assembly["assembly"] == {"project_level": True}

        # Manifest has contributing run.
        manifest = json.loads((children[0] / "manifest.json").read_text())
        assert run_id in manifest["contributing_runs"]

        # Both legacy files removed.
        assert not (pdir / "timeline.json").exists()
        assert not (pdir / "runs" / run_id / "timeline.json").exists()

        # run.json updated.
        run_data = json.loads((pdir / "runs" / run_id / "run.json").read_text())
        assert run_data["timeline_id"] == ulid

        # Default set.
        project = json.loads((pdir / "project.json").read_text())
        assert project["default_timeline_id"] == ulid


# ---------------------------------------------------------------------------
# Test: hype artifact skipping
# ---------------------------------------------------------------------------


class TestHypeArtifactSkip:
    def test_skips_tracks_top_level_key(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        run_id = generate_ulid()
        rdir = _add_run(pdir, run_id, with_run_json=True)
        # Write a hype artifact with 'tracks' key.
        (rdir / "timeline.json").write_text(
            json.dumps({"tracks": [{"name": "Track 1"}], "clips": []}),
            encoding="utf-8",
        )
        result = _run_migration(tmp_path, apply=True)
        assert result.returncode == 0
        assert "skip-hype-artifact" in result.stderr

        # The per-run timeline.json should still exist (not deleted).
        assert (rdir / "timeline.json").exists()

    def test_skips_clips_top_level_key(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        run_id = generate_ulid()
        rdir = _add_run(pdir, run_id, with_run_json=True)
        (rdir / "timeline.json").write_text(
            json.dumps({"clips": [{"id": "c1"}]}),
            encoding="utf-8",
        )
        result = _run_migration(tmp_path, apply=True)
        assert result.returncode == 0
        assert "skip-hype-artifact" in result.stderr
        assert (rdir / "timeline.json").exists()


# ---------------------------------------------------------------------------
# Test: already-migrated guard
# ---------------------------------------------------------------------------


class TestAlreadyMigratedGuard:
    def test_refuses_without_force(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        _add_legacy_project_timeline(pdir)
        # Pre-create a timelines/ ulid directory.
        fake_ulid = generate_ulid()
        (tmp_path / "demo" / "timelines" / fake_ulid).mkdir(parents=True)
        result = _run_migration(tmp_path, apply=False)
        assert result.returncode == 1
        assert "already migrated" in result.stderr.lower()

    def test_succeeds_with_force(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        _add_legacy_project_timeline(pdir)
        fake_ulid = generate_ulid()
        (tmp_path / "demo" / "timelines" / fake_ulid).mkdir(parents=True)
        result = _run_migration(tmp_path, apply=True, force=True)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Test: safety — plan.json, events.jsonl, produces/ untouched
# ---------------------------------------------------------------------------


class TestSafety:
    def test_plan_events_and_produces_untouched(self, tmp_path: Path) -> None:
        pdir = _seed_project(tmp_path, "demo")
        run_id = generate_ulid()
        rdir = _add_run(pdir, run_id, with_run_json=True, with_legacy_timeline=True)
        (rdir / "produces").mkdir()
        (rdir / "produces" / "render.mp4").write_bytes(b"stub")
        plan_content = '{"steps": [1,2,3]}'
        (rdir / "plan.json").write_text(plan_content, encoding="utf-8")

        result = _run_migration(tmp_path, apply=True)
        assert result.returncode == 0

        # plan.json unchanged.
        assert (rdir / "plan.json").read_text() == plan_content
        # events.jsonl still exists.
        assert (rdir / "events.jsonl").exists()
        # produces/ still exists and is untouched.
        assert (rdir / "produces").is_dir()
        assert (rdir / "produces" / "render.mp4").read_bytes() == b"stub"


# ---------------------------------------------------------------------------
# Test: empty projects root → exit 0
# ---------------------------------------------------------------------------


class TestEmptyRoot:
    def test_exits_zero(self, tmp_path: Path) -> None:
        # Empty, no project.json anywhere.
        result = _run_migration(tmp_path, apply=False)
        assert result.returncode == 0

    def test_non_existent_root_exits_zero(self, tmp_path: Path) -> None:
        result = _run_migration(tmp_path / "nonexistent", apply=False)
        assert result.returncode == 0
        assert "does not exist" in result.stderr.lower()