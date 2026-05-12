from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.project.paths import ProjectPathError
from astrid.core.task.plan import TaskPlanError, step_dir_for, step_dir_for_path


def test_step_dir_for_path_nested_tuple(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s2", "c1"), step_version=1, root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s2" / "c1" / "v1"


def test_step_dir_for_path_with_iteration_zero_pads_three_digits(tmp_path: Path) -> None:
    result = step_dir_for_path(
        "demo", "run1", ("s1",), step_version=1, iteration=3, root=tmp_path
    )
    assert (
        result
        == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "v1" / "iterations" / "003"
    )


def test_step_dir_for_path_with_item_id(tmp_path: Path) -> None:
    result = step_dir_for_path(
        "demo", "run1", ("s1",), step_version=1, item_id="v1", root=tmp_path
    )
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "v1" / "items" / "v1"


def test_step_dir_for_path_rejects_both_iteration_and_item_id(tmp_path: Path) -> None:
    with pytest.raises(TaskPlanError, match="mutually exclusive"):
        step_dir_for_path(
            "demo", "run1", ("s1",), step_version=1, iteration=1, item_id="v1", root=tmp_path
        )


def test_step_dir_for_path_rejects_segment_with_slash(tmp_path: Path) -> None:
    with pytest.raises(ProjectPathError):
        step_dir_for_path("demo", "run1", ("bad/seg",), step_version=1, root=tmp_path)


def test_step_dir_for_path_rejects_iteration_below_one(tmp_path: Path) -> None:
    with pytest.raises(TaskPlanError, match=">= 1"):
        step_dir_for_path("demo", "run1", ("s1",), step_version=1, iteration=0, root=tmp_path)


def test_step_dir_for_path_rejects_empty_path(tmp_path: Path) -> None:
    with pytest.raises(TaskPlanError, match="at least one segment"):
        step_dir_for_path("demo", "run1", (), step_version=1, root=tmp_path)


def test_step_dir_for_legacy_wrapper_matches_single_segment_path(tmp_path: Path) -> None:
    legacy = step_dir_for("demo", "run1", "s1", step_version=1, root=tmp_path)
    new = step_dir_for_path("demo", "run1", ("s1",), step_version=1, root=tmp_path)
    assert legacy == new


def test_step_dir_for_path_v2_supersede(tmp_path: Path) -> None:
    """Path reflects v2/ when step_version=2 (superseded)."""
    result = step_dir_for_path("demo", "run1", ("s1",), step_version=2, root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "v2"


def test_step_dir_for_path_rejects_missing_step_version(tmp_path: Path) -> None:
    """step_version is required (no default)."""
    with pytest.raises(TypeError):
        step_dir_for_path("demo", "run1", ("s1",), root=tmp_path)  # type: ignore[call-arg]