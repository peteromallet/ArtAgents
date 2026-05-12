"""Sprint 5b: thumbnail_maker port test (T3 / T12).

Verifies the ported thumbnail_maker orchestrator emits a v2 plan.json
with correct adapter/cost assignments, and that the plan is loadable
by the kernel.
"""

from __future__ import annotations

import json
from pathlib import Path


def test_plan_template_emits_v2() -> None:
    """``build_plan_v2`` returns a plan dict with version 2."""
    from astrid.packs.builtin.thumbnail_maker.plan_template import build_plan_v2

    plan = build_plan_v2(
        python_exec="python3",
        run_root=Path("/tmp/test"),
        source=Path("/tmp/source.mp4"),
        run_id="test-run",
    )

    assert isinstance(plan, dict)
    assert plan.get("version") == 2
    assert plan.get("plan_id") is not None
    assert isinstance(plan.get("steps"), list)
    assert len(plan["steps"]) > 0

    for step in plan["steps"]:
        assert "id" in step
        assert "adapter" in step
        assert "command" in step
        assert isinstance(step.get("cost"), dict)
        assert step["adapter"] in ("local", "manual", "remote-artifact")


def test_plan_template_steps_use_local_adapter() -> None:
    """All thumbnail_maker steps use ``adapter: local``."""
    from astrid.packs.builtin.thumbnail_maker.plan_template import build_plan_v2

    plan = build_plan_v2(
        python_exec="python3",
        run_root=Path("/tmp/test"),
        source=Path("/tmp/source.mp4"),
        run_id="test-run",
    )

    for step in plan["steps"]:
        assert step["adapter"] == "local", (
            f"Step {step['id']} has adapter={step['adapter']!r}"
        )
        cost = step["cost"]
        assert cost.get("source") == "local"
        assert cost.get("amount") == 0


def test_plan_has_expected_step_ids() -> None:
    """The plan contains the five known thumbnail_maker steps."""
    from astrid.packs.builtin.thumbnail_maker.plan_template import build_plan_v2

    plan = build_plan_v2(
        python_exec="python3",
        run_root=Path("/tmp/test"),
        source=Path("/tmp/source.mp4"),
        run_id="test-run",
    )

    step_ids = {step["id"] for step in plan["steps"]}
    expected = {
        "resolve-video",
        "plan-evidence",
        "discover-video-evidence",
        "build-reference-pack",
        "generate-thumbnails",
    }
    assert step_ids == expected, f"Unexpected step ids: {step_ids}"


def test_emit_plan_json_writes_valid_json(tmp_path: Path) -> None:
    """``emit_plan_json`` writes a parsable plan.json."""
    from astrid.packs.builtin.thumbnail_maker.plan_template import (
        build_plan_v2,
        emit_plan_json,
    )

    plan = build_plan_v2(
        python_exec="python3",
        run_root=tmp_path,
        source=Path("/tmp/source.mp4"),
        run_id="test-run",
    )

    plan_path = tmp_path / "plan.json"
    emit_plan_json(plan, plan_path)

    assert plan_path.is_file()
    loaded = json.loads(plan_path.read_text(encoding="utf-8"))
    assert loaded["version"] == 2
    assert len(loaded["steps"]) == 5


def test_plan_is_round_trip_stable(tmp_path: Path) -> None:
    """The emitted plan loads cleanly through ``load_plan``."""
    from astrid.packs.builtin.thumbnail_maker.plan_template import (
        build_plan_v2,
        emit_plan_json,
    )
    from astrid.core.task.plan import load_plan

    plan = build_plan_v2(
        python_exec="python3",
        run_root=tmp_path,
        source=Path("/tmp/source.mp4"),
        run_id="test-run",
    )

    plan_path = tmp_path / "plan.json"
    emit_plan_json(plan, plan_path)

    loaded = load_plan(plan_path)
    assert loaded.plan_id == plan["plan_id"]
    assert loaded.version == 2
    assert len(loaded.steps) == len(plan["steps"])


def test_old_build_plan_not_accessible() -> None:
    """The old ``build_plan(args, layout, video_resolution)`` is removed
    from the thumbnail_maker run module."""
    from astrid.packs.builtin.thumbnail_maker import run as tm_run

    # The old build_plan should not exist as a callable attribute
    # (plan_template.build_plan_v2 is the replacement)
    old = getattr(tm_run, "build_plan", None)
    assert old is None or not callable(old), (
        "Old build_plan found in thumbnail_maker/run.py — should be removed"
    )