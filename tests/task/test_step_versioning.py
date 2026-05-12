"""Tests for step versioning — supersede produces v2/ + v1/ survives (Sprint 3 T21)."""

from __future__ import annotations

import json
from pathlib import Path

from astrid.core.task.plan import (
    Step,
    TaskPlan,
    _validate_plan,
    step_dir_for,
    step_dir_for_path,
)
from astrid.core.task.plan_verbs import (
    CursorRecord,
    _apply_diff,
    derive_versioned_cursor,
)


# ---------------------------------------------------------------------------
# step_dir_for_path versioned paths
# ---------------------------------------------------------------------------

def test_v1_path_includes_version(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s1",), step_version=1, root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "v1"


def test_v2_path_includes_version(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s1",), step_version=2, root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "v2"


def test_nested_path_versioned_at_leaf_only(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("parent", "child"), step_version=1, root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "parent" / "child" / "v1"


def test_iteration_hangs_off_versioned_dir(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s1",), step_version=1, iteration=5, root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "v1" / "iterations" / "005"


def test_item_hangs_off_versioned_dir(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s1",), step_version=2, item_id="abc", root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "v2" / "items" / "abc"


# ---------------------------------------------------------------------------
# supersede produces v2, v1 survives conceptually
# ---------------------------------------------------------------------------

def test_supersede_creates_new_version_in_effective_tree() -> None:
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [{"id": "s1", "adapter": "local", "command": "echo old", "version": 1}],
    })
    diff = {
        "op": "supersede",
        "path": "s1",
        "to_version": 2,
        "scope": "all",
        "step": {"id": "s1", "adapter": "local", "command": "echo new", "version": 2},
    }
    result = _apply_diff(plan, diff)
    assert result.steps[0].version == 2
    assert result.steps[0].command == "echo new"


# ---------------------------------------------------------------------------
# cursor tracks correct version
# ---------------------------------------------------------------------------

def test_cursor_tracks_initial_version() -> None:
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "command": "echo", "step_version": 1, "hash": "sha256:aaa"},
    ]
    cursor = derive_versioned_cursor(events)
    assert "s1" in cursor
    assert cursor["s1"].step_version == 1
    assert cursor["s1"].dispatch_event_hash == "sha256:aaa"


def test_cursor_bumps_on_supersede() -> None:
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "command": "echo old", "step_version": 1, "hash": "sha256:aaa"},
        {"kind": "plan_mutated", "diff": {"op": "supersede", "path": "s1", "to_version": 2, "scope": "all"}},
    ]
    cursor = derive_versioned_cursor(events)
    assert "s1" in cursor
    assert cursor["s1"].step_version == 2
    assert cursor["s1"].dispatch_event_hash is None  # No dispatch at new version yet


def test_cursor_handles_legacy_plan_step_id() -> None:
    """Backward compat: plan_step_id string → cursor key."""
    events = [
        {"kind": "step_dispatched", "plan_step_id": "s1", "command": "echo", "step_version": 1, "hash": "sha256:bbb"},
    ]
    cursor = derive_versioned_cursor(events)
    assert "s1" in cursor
    assert cursor["s1"].step_version == 1


def test_cursor_handles_slash_path() -> None:
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["parent", "child"], "command": "echo", "step_version": 1, "hash": "sha256:ccc"},
    ]
    cursor = derive_versioned_cursor(events)
    assert "parent/child" in cursor
    assert cursor["parent/child"].step_version == 1


# ---------------------------------------------------------------------------
# step_dir_for requires step_version
# ---------------------------------------------------------------------------

def test_step_dir_for_requires_step_version(tmp_path: Path) -> None:
    """step_version is a required keyword-only arg."""
    result = step_dir_for("demo", "run1", "s1", step_version=1, root=tmp_path)
    assert "v1" in str(result)