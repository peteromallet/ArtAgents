"""Tests for step path migration — dir rename + idempotence (Sprint 3 T23)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Locate the migration script and load it as a module.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MIGRATE_STEP_PATHS_PATH = _REPO_ROOT / "scripts" / "migrations" / "sprint-3" / "migrate_step_paths.py"
_spec = importlib.util.spec_from_file_location("migrate_step_paths", _MIGRATE_STEP_PATHS_PATH)
_migrate_step_paths_mod = importlib.util.module_from_spec(_spec)
sys.modules["migrate_step_paths"] = _migrate_step_paths_mod
_spec.loader.exec_module(_migrate_step_paths_mod)

_find_step_dirs_to_migrate = _migrate_step_paths_mod._find_step_dirs_to_migrate
_has_versioned_child = _migrate_step_paths_mod._has_versioned_child
migrate_step_paths_main = _migrate_step_paths_mod.main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_with_step_dirs(
    tmp_path: Path,
    slug: str = "demo",
    run_id: str = "run-1",
    step_id: str = "s1",
    subdirs: list[str] | None = None,
) -> Path:
    """Create a run directory with step subdirectories."""
    steps_dir = tmp_path / slug / "runs" / run_id / "steps" / step_id
    steps_dir.mkdir(parents=True)
    if subdirs:
        for sub in subdirs:
            (steps_dir / sub).mkdir(parents=True)
    return steps_dir


# ---------------------------------------------------------------------------
# _has_versioned_child
# ---------------------------------------------------------------------------


def test_has_versioned_child_true(tmp_path: Path) -> None:
    step_dir = _make_run_with_step_dirs(tmp_path, subdirs=["v1"])
    assert _has_versioned_child(step_dir) is True


def test_has_versioned_child_v2(tmp_path: Path) -> None:
    step_dir = _make_run_with_step_dirs(tmp_path, subdirs=["v2"])
    assert _has_versioned_child(step_dir) is True


def test_has_versioned_child_mixed(tmp_path: Path) -> None:
    step_dir = _make_run_with_step_dirs(tmp_path, subdirs=["v1", "iterations", "artifacts"])
    assert _has_versioned_child(step_dir) is True


def test_has_versioned_child_false_unversioned(tmp_path: Path) -> None:
    step_dir = _make_run_with_step_dirs(tmp_path, subdirs=["iterations", "artifacts"])
    assert _has_versioned_child(step_dir) is False


def test_has_versioned_child_empty_dir(tmp_path: Path) -> None:
    step_dir = _make_run_with_step_dirs(tmp_path)
    assert _has_versioned_child(step_dir) is False


def test_has_versioned_child_nonexistent(tmp_path: Path) -> None:
    assert _has_versioned_child(tmp_path / "nonexistent") is False


# ---------------------------------------------------------------------------
# _find_step_dirs_to_migrate
# ---------------------------------------------------------------------------


def test_find_unversioned_subdirs(tmp_path: Path) -> None:
    _make_run_with_step_dirs(tmp_path, subdirs=["artifacts", "logs"])
    items = _find_step_dirs_to_migrate(tmp_path)
    assert len(items) >= 2
    names = {name for _, name in items}
    assert "artifacts" in names
    assert "logs" in names


def test_find_skips_versioned_dirs(tmp_path: Path) -> None:
    _make_run_with_step_dirs(tmp_path, subdirs=["v1", "artifacts"])
    items = _find_step_dirs_to_migrate(tmp_path)
    # Should be empty because v1 exists — entire step is skipped.
    assert len(items) == 0


def test_find_skips_v_named_children(tmp_path: Path) -> None:
    """Directories named v<N> (like v2) should not be included for rename."""
    _make_run_with_step_dirs(tmp_path, subdirs=["v1"])
    items = _find_step_dirs_to_migrate(tmp_path)
    assert len(items) == 0


def test_find_empty_workspace(tmp_path: Path) -> None:
    projects_root = tmp_path / "empty"
    projects_root.mkdir(parents=True)
    items = _find_step_dirs_to_migrate(projects_root)
    assert len(items) == 0


def test_find_missing_root(tmp_path: Path) -> None:
    items = _find_step_dirs_to_migrate(tmp_path / "nonexistent")
    assert len(items) == 0


def test_find_mixed_versioned_and_unversioned(tmp_path: Path) -> None:
    """v1 existing: entire step skipped. No v<N>: subdirs collected."""
    # Step with v1 → skipped.
    _make_run_with_step_dirs(tmp_path, step_id="already-versioned", subdirs=["v1", "old-data"])
    # Step without v<N> → collected.
    _make_run_with_step_dirs(tmp_path, step_id="not-versioned", subdirs=["data", "output"])

    items = _find_step_dirs_to_migrate(tmp_path)
    # Only "not-versioned" step's children should appear.
    names = {name for _, name in items}
    assert "data" in names
    assert "output" in names
    assert "old-data" not in names


# ---------------------------------------------------------------------------
# main: --dry-run / --apply
# ---------------------------------------------------------------------------


def test_main_dry_run_previews_without_moving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    steps_dir = _make_run_with_step_dirs(tmp_path, subdirs=["artifacts"])
    old_path = steps_dir / "artifacts"
    assert old_path.is_dir()

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", str(tmp_path), "--dry-run"],
    )
    assert migrate_step_paths_main() == 0

    # Directory should NOT have moved.
    assert old_path.is_dir()
    assert not (steps_dir / "v1").exists()


def test_main_apply_moves_dir_to_v1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    steps_dir = _make_run_with_step_dirs(tmp_path, subdirs=["artifacts"])
    old_path = steps_dir / "artifacts"

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", str(tmp_path), "--apply"],
    )
    assert migrate_step_paths_main() == 0

    # Old path should be gone.
    assert not old_path.exists()
    # New path should exist.
    new_path = steps_dir / "v1" / "artifacts"
    assert new_path.is_dir()


def test_main_idempotent_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_run_with_step_dirs(tmp_path, subdirs=["data"])

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", str(tmp_path), "--apply"],
    )
    assert migrate_step_paths_main() == 0

    # Second run should be no-op.
    assert migrate_step_paths_main() == 0

    # Verify data is in v1/.
    steps_dirs = list(tmp_path.glob("*/runs/*/steps/*"))
    for sd in steps_dirs:
        assert _has_versioned_child(sd) is True


def test_main_noop_when_all_versioned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Pre-populate with v1 already existing.
    _make_run_with_step_dirs(tmp_path, subdirs=["v1", "artifacts"])

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", str(tmp_path)],
    )
    assert migrate_step_paths_main() == 0


def test_main_empty_workspace_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = tmp_path / "no-dirs"
    projects_root.mkdir(parents=True)

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", str(projects_root)],
    )
    assert migrate_step_paths_main() == 0


def test_main_missing_root_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", "/nonexistent/xyz"],
    )
    assert migrate_step_paths_main() == 0


def test_apply_multiple_dirs_move_into_v1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    steps_dir = _make_run_with_step_dirs(tmp_path, subdirs=["a", "b", "c"])
    for sub in ("a", "b", "c"):
        (steps_dir / sub / "file.txt").write_text(sub, encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", str(tmp_path), "--apply"],
    )
    assert migrate_step_paths_main() == 0

    v1_dir = steps_dir / "v1"
    assert v1_dir.is_dir()
    for sub in ("a", "b", "c"):
        assert (v1_dir / sub).is_dir()
        assert (v1_dir / sub / "file.txt").read_text(encoding="utf-8") == sub


def test_apply_preserves_nested_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    steps_dir = _make_run_with_step_dirs(tmp_path, subdirs=["output"])
    nested = steps_dir / "output" / "deep"
    nested.mkdir(parents=True)
    (nested / "result.json").write_text('{"ok":true}', encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv",
        ["migrate_step_paths.py", "--projects-root", str(tmp_path), "--apply"],
    )
    assert migrate_step_paths_main() == 0

    assert (steps_dir / "v1" / "output" / "deep" / "result.json").read_text(encoding="utf-8") == '{"ok":true}'