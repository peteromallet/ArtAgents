"""Sprint 1 migration script smoke tests (T14).

Covers: malformed-aborts (default), --force-skip-malformed opt-in, happy
path, idempotency, default-timeline-sentinel stamp, threads audit no-op.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from astrid.core.project import paths
from astrid.core.project.project import create_project
from astrid.core.project.schema import validate_project

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent


def _load(module_name: str):
    path = MIGRATIONS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _seed_project(root: Path, slug: str, *, run_id: str = "01HXYZRUN", plan_hash: str | None = None) -> Path:
    project_dir = root / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-11T00:00:00Z",
                "name": slug,
                "schema_version": 1,
                "slug": slug,
                "updated_at": "2026-05-11T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (project_dir / "sources").mkdir(exist_ok=True)
    runs = project_dir / "runs"
    (runs / run_id).mkdir(parents=True, exist_ok=True)
    (runs / run_id / "events.jsonl").write_bytes(b"")
    plan = plan_hash if plan_hash is not None else "sha256:" + "a" * 64
    (project_dir / "active_run.json").write_text(
        json.dumps({"run_id": run_id, "plan_hash": plan}),
        encoding="utf-8",
    )
    return project_dir


def test_migrate_active_run_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_active_run_to_current_run")
    project_dir = _seed_project(tmp_path, "demo")
    events_bytes_before = (project_dir / "runs" / "01HXYZRUN" / "events.jsonl").read_bytes()

    assert mod.main(["--apply"]) == 0
    # Lease written first with the migrated plan_hash.
    lease = json.loads((project_dir / "runs" / "01HXYZRUN" / "lease.json").read_text())
    assert lease == {
        "writer_epoch": 0,
        "attached_session_id": None,
        "plan_hash": "sha256:" + "a" * 64,
    }
    # current_run pointer matches.
    cur = json.loads((project_dir / "current_run.json").read_text())
    assert cur == {"run_id": "01HXYZRUN"}
    # Active-run pointer removed; events.jsonl bytes unchanged.
    assert not (project_dir / "active_run.json").exists()
    assert (project_dir / "runs" / "01HXYZRUN" / "events.jsonl").read_bytes() == events_bytes_before


def test_migrate_active_run_dry_run_previews_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_active_run_to_current_run")
    project_dir = _seed_project(tmp_path, "demo")
    assert mod.main([]) == 0  # dry-run is default
    assert (project_dir / "active_run.json").exists()
    assert not (project_dir / "current_run.json").exists()
    assert not (project_dir / "runs" / "01HXYZRUN" / "lease.json").exists()
    err = capsys.readouterr().err
    assert "WOULD MIGRATE" in err


def test_migrate_active_run_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_active_run_to_current_run")
    _seed_project(tmp_path, "demo")
    assert mod.main(["--apply"]) == 0
    assert mod.main(["--apply"]) == 0  # second run: nothing to do
    assert mod.main([]) == 0  # dry-run also no-ops


def test_migrate_active_run_apply_aborts_on_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_active_run_to_current_run")
    _seed_project(tmp_path, "demo", plan_hash="NOT-A-HASH")
    rc = mod.main(["--apply"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "STOP-LINE" in err
    # Source file untouched on abort.
    assert (tmp_path / "demo" / "active_run.json").exists()


def test_migrate_active_run_dry_run_previews_malformed_without_aborting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_active_run_to_current_run")
    _seed_project(tmp_path, "demo", plan_hash="NOT-A-HASH")
    rc = mod.main([])
    assert rc == 0
    err = capsys.readouterr().err
    assert "WOULD ABORT" in err


def test_migrate_active_run_force_skip_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_active_run_to_current_run")
    _seed_project(tmp_path, "bad", plan_hash="NOT-A-HASH")
    _seed_project(tmp_path, "good")
    rc = mod.main(["--apply", "--force-skip-malformed"])
    assert rc == 0
    # Good project migrated; bad project untouched.
    assert (tmp_path / "good" / "current_run.json").exists()
    assert (tmp_path / "bad" / "active_run.json").exists()
    assert not (tmp_path / "bad" / "current_run.json").exists()


def test_migrate_active_run_aborts_when_events_jsonl_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_active_run_to_current_run")
    project_dir = _seed_project(tmp_path, "demo")
    (project_dir / "runs" / "01HXYZRUN" / "events.jsonl").unlink()
    rc = mod.main(["--apply"])
    assert rc == 2
    assert (project_dir / "active_run.json").exists()


def test_migrate_default_timeline_sentinel_stamps_each_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_set_default_timeline_sentinel")
    # Seed two legacy projects without default_timeline_id key.
    for slug in ("alpha", "beta"):
        d = tmp_path / slug
        d.mkdir(parents=True)
        d.joinpath("project.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-05-11T00:00:00Z",
                    "name": slug,
                    "schema_version": 1,
                    "slug": slug,
                    "updated_at": "2026-05-11T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
    assert mod.main(["--apply"]) == 0
    for slug in ("alpha", "beta"):
        payload = json.loads((tmp_path / slug / "project.json").read_text())
        assert payload["default_timeline_id"] is None
        # Round-trip through validator.
        validate_project(payload)
    # Idempotent.
    assert mod.main(["--apply"]) == 0


def test_migrate_default_timeline_sentinel_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_set_default_timeline_sentinel")
    d = tmp_path / "demo"
    d.mkdir()
    d.joinpath("project.json").write_text(
        json.dumps(
            {
                "created_at": "2026-05-11T00:00:00Z",
                "name": "demo",
                "schema_version": 1,
                "slug": "demo",
                "updated_at": "2026-05-11T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    assert mod.main([]) == 0
    err = capsys.readouterr().err
    assert "WOULD STAMP" in err
    payload = json.loads((d / "project.json").read_text())
    assert "default_timeline_id" not in payload


def test_migrate_threads_audit_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(paths.PROJECTS_ROOT_ENV, str(tmp_path))
    mod = _load("migrate_threads_audit")
    create_project("demo")
    assert mod.main(["--apply"]) == 0
    err = capsys.readouterr().err
    assert "STAYS (DEC-001)" in err
