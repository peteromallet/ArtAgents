from __future__ import annotations

from pathlib import Path

import pytest

from artagents.core.project.paths import ProjectPathError
from artagents.core.task.plan import TaskPlanError, step_dir_for, step_dir_for_path


def test_step_dir_for_path_nested_tuple(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s2", "c1"), root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s2" / "c1"


def test_step_dir_for_path_with_iteration_zero_pads_three_digits(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s1",), iteration=3, root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "iterations" / "003"


def test_step_dir_for_path_with_item_id(tmp_path: Path) -> None:
    result = step_dir_for_path("demo", "run1", ("s1",), item_id="v1", root=tmp_path)
    assert result == tmp_path / "demo" / "runs" / "run1" / "steps" / "s1" / "items" / "v1"


def test_step_dir_for_path_rejects_both_iteration_and_item_id(tmp_path: Path) -> None:
    with pytest.raises(TaskPlanError, match="mutually exclusive"):
        step_dir_for_path("demo", "run1", ("s1",), iteration=1, item_id="v1", root=tmp_path)


def test_step_dir_for_path_rejects_segment_with_slash(tmp_path: Path) -> None:
    with pytest.raises(ProjectPathError):
        step_dir_for_path("demo", "run1", ("bad/seg",), root=tmp_path)


def test_step_dir_for_path_rejects_iteration_below_one(tmp_path: Path) -> None:
    with pytest.raises(TaskPlanError, match=">= 1"):
        step_dir_for_path("demo", "run1", ("s1",), iteration=0, root=tmp_path)


def test_step_dir_for_path_rejects_empty_path(tmp_path: Path) -> None:
    with pytest.raises(TaskPlanError, match="at least one segment"):
        step_dir_for_path("demo", "run1", (), root=tmp_path)


def test_step_dir_for_legacy_wrapper_matches_single_segment_path(tmp_path: Path) -> None:
    legacy = step_dir_for("demo", "run1", "s1", root=tmp_path)
    new = step_dir_for_path("demo", "run1", ("s1",), root=tmp_path)
    assert legacy == new
