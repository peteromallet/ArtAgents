"""Tests for the collapsed Step schema (Sprint 3 T21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.task.plan import (
    AckRule,
    ProducesEntry,
    RepeatForEach,
    RepeatUntil,
    Step,
    SupersededRef,
    TaskPlan,
    TaskPlanError,
    _validate_plan,
    _validate_step,
    is_group_step,
    is_leaf_step,
    iter_steps_with_path,
    load_plan,
)
from astrid.core.task.validator import (
    INVARIANTS,
    MutationInvariantError,
    validate_mutation,
)
from astrid.verify import file_nonempty


# ---------------------------------------------------------------------------
# Structural invariant tests
# ---------------------------------------------------------------------------

def test_leaf_step_with_command_constructs() -> None:
    step = Step(id="s1", adapter="local", command="echo ok")
    assert step.id == "s1"
    assert step.adapter == "local"
    assert step.command == "echo ok"
    assert step.children is None
    assert is_leaf_step(step)
    assert not is_group_step(step)


def test_group_step_with_children_constructs() -> None:
    child = Step(id="c1", adapter="local", command="echo child")
    step = Step(id="parent", adapter="local", children=(child,))
    assert step.children is not None
    assert step.command is None
    assert is_group_step(step)
    assert not is_leaf_step(step)


def test_command_xor_children_no_both_raises() -> None:
    child = Step(id="c1", adapter="local", command="echo c")
    with pytest.raises(TaskPlanError, match="cannot have both"):
        Step(id="bad", adapter="local", command="echo", children=(child,))


def test_command_xor_children_neither_raises() -> None:
    with pytest.raises(TaskPlanError, match="must have either"):
        Step(id="bad", adapter="local")


def test_requires_ack_on_group_step_constructs() -> None:
    """requires_ack is valid on group steps — no structural restriction."""
    child = Step(id="c1", adapter="local", command="echo")
    step = Step(id="parent", adapter="local", requires_ack=True, children=(child,))
    assert step.requires_ack is True
    assert is_group_step(step)


def test_instructions_optional_on_leaf() -> None:
    step = Step(id="s1", adapter="manual", command="review", instructions="Please review")
    assert step.instructions == "Please review"
    step2 = Step(id="s2", adapter="manual", command="review")
    assert step2.instructions is None


def test_version_defaults_to_1() -> None:
    step = Step(id="s1", adapter="local", command="echo")
    assert step.version == 1


def test_version_ge_1_enforced() -> None:
    with pytest.raises(TaskPlanError, match="version must be >= 1"):
        Step(id="bad", adapter="local", command="echo", version=0)


def test_v2_version_allowed_after_t8_retirement() -> None:
    """After T8 retired the v2-rejection invariant, v2 constructs cleanly."""
    step = Step(id="s1", adapter="local", command="echo", version=2)
    assert step.version == 2


# ---------------------------------------------------------------------------
# _validate_plan (v2 only) tests
# ---------------------------------------------------------------------------

def _write_plan(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_load_plan_rejects_non_v2(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {
        "plan_id": "p1", "version": 1,
        "steps": [{"id": "s1", "command": "echo"}],
    })
    with pytest.raises(TaskPlanError, match="version must be 2"):
        load_plan(plan_path)


def test_load_plan_accepts_v2(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {
        "plan_id": "p1", "version": 2,
        "steps": [{"id": "s1", "adapter": "local", "command": "echo"}],
    })
    plan = load_plan(plan_path)
    assert plan.version == 2
    assert len(plan.steps) == 1
    assert plan.steps[0].id == "s1"


def test_load_plan_with_group_step(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {
        "plan_id": "p1", "version": 2,
        "steps": [{
            "id": "parent",
            "children": [
                {"id": "c1", "adapter": "local", "command": "echo one"},
                {"id": "c2", "adapter": "manual", "command": "review", "requires_ack": True},
            ],
        }],
    })
    plan = load_plan(plan_path)
    parent = plan.steps[0]
    assert is_group_step(parent)
    assert len(parent.children) == 2
    assert parent.children[0].id == "c1"
    assert parent.children[1].requires_ack is True


def test_load_plan_with_re_export(tmp_path: Path) -> None:
    plan_path = _write_plan(tmp_path, {
        "plan_id": "p1", "version": 2,
        "steps": [{
            "id": "parent",
            "children": [
                {"id": "c1", "adapter": "local", "command": "echo",
                 "produces": {"out": {"path": "out.txt", "check": {"check_id": "file_nonempty", "params": {}, "sentinel": False}}}},
            ],
            "re_export": {"alias": "c1.produces.out"},
        }],
    })
    plan = load_plan(plan_path)
    parent = plan.steps[0]
    assert parent.re_export is not None
    assert parent.re_export[0] == ("alias", "c1.produces.out")


# ---------------------------------------------------------------------------
# Six-invariant validator tests (positive + negative)
# ---------------------------------------------------------------------------

def _v2_plan(steps: list[dict]) -> TaskPlan:
    return load_plan.__wrapped__ if False else _validate_plan(
        {"plan_id": "test", "version": 2, "steps": steps}
    )


def _valid_plan() -> TaskPlan:
    return _validate_plan({
        "plan_id": "test", "version": 2,
        "steps": [{"id": "s1", "adapter": "local", "command": "echo ok"}],
    })


def test_i1_schema_passes() -> None:
    validate_mutation(None, _valid_plan(), lease_epoch_actual=1, lease_epoch_expected=1)


def test_i1_schema_rejects_bad_adapter() -> None:
    with pytest.raises((TaskPlanError, MutationInvariantError)) as exc:
        _validate_plan({
            "plan_id": "t", "version": 2,
            "steps": [{"id": "s1", "adapter": "bogus", "command": "x"}],
        })
    # Either TaskPlanError (from _validate_plan) or MutationInvariantError is acceptable.
    error_msg = str(exc.value).lower()
    assert "adapter" in error_msg


def test_i2_sibling_uniqueness_passes() -> None:
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [
            {"id": "a", "adapter": "local", "command": "echo a"},
            {"id": "b", "adapter": "local", "command": "echo b"},
        ],
    })
    validate_mutation(None, plan, lease_epoch_actual=1, lease_epoch_expected=1)


def test_i2_sibling_uniqueness_rejects_duplicate() -> None:
    with pytest.raises((TaskPlanError, MutationInvariantError)) as exc:
        _validate_plan({
            "plan_id": "t", "version": 2,
            "steps": [
                {"id": "dup", "adapter": "local", "command": "echo a"},
                {"id": "dup", "adapter": "local", "command": "echo b"},
            ],
        })
    error_msg = str(exc.value).lower()
    assert "duplicate" in error_msg


def test_i3_produces_refs_passes() -> None:
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [{
            "id": "parent",
            "children": [
                {"id": "c1", "adapter": "local", "command": "echo",
                 "produces": {"out": {"path": "out.txt", "check": {"check_id": "file_nonempty", "params": {}, "sentinel": False}}}},
            ],
            "re_export": {"alias": "c1.produces.out"},
        }],
    })
    validate_mutation(None, plan, lease_epoch_actual=1, lease_epoch_expected=1)


def test_i3_produces_refs_rejects_unknown_step() -> None:
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [{
            "id": "parent",
            "children": [
                {"id": "c1", "adapter": "local", "command": "echo",
                 "produces": {"out": {"path": "out.txt", "check": {"check_id": "file_nonempty", "params": {}, "sentinel": False}}}},
            ],
            # Reference a step that exists but has no matching produces
            "re_export": {"alias": "c1.produces.nonexistent"},
        }],
    })
    with pytest.raises(MutationInvariantError) as exc:
        validate_mutation(None, plan, lease_epoch_actual=1, lease_epoch_expected=1)
    assert exc.value.invariant_id == "I3_produces_refs"


def test_i4_adapter_shape_passes_local() -> None:
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [{"id": "s1", "adapter": "local", "command": "echo ok"}],
    })
    validate_mutation(None, plan, lease_epoch_actual=1, lease_epoch_expected=1)


def test_i4_adapter_shape_rejects_manual_empty_command() -> None:
    with pytest.raises(TaskPlanError, match="manual adapter requires a non-empty command"):
        _validate_plan({
            "plan_id": "t", "version": 2,
            "steps": [{"id": "s1", "adapter": "manual", "command": "   "}],
        })


def test_i4_adapter_shape_passes_manual_with_command() -> None:
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [{"id": "s1", "adapter": "manual", "command": "review this", "requires_ack": True}],
    })
    validate_mutation(None, plan, lease_epoch_actual=1, lease_epoch_expected=1)


def test_i4_adapter_shape_allows_group_without_command() -> None:
    """Group steps don't carry commands, so I4 skips them."""
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [{
            "id": "parent",
            "children": [{"id": "c1", "adapter": "local", "command": "echo"}],
        }],
    })
    validate_mutation(None, plan, lease_epoch_actual=1, lease_epoch_expected=1)


def test_i5_repeat_source_passes() -> None:
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [
            {"id": "src", "adapter": "local", "command": "echo",
             "produces": {"items": {"path": "items.json", "check": {"check_id": "file_nonempty", "params": {}, "sentinel": False}}}},
            {"id": "consumer", "adapter": "local", "command": "echo",
             "repeat": {"for_each": {"from": "src.produces.items"}}},
        ],
    })
    validate_mutation(None, plan, lease_epoch_actual=1, lease_epoch_expected=1)


def test_i5_repeat_source_rejects_unknown_prior() -> None:
    with pytest.raises(TaskPlanError, match="unknown prior sibling"):
        _validate_plan({
            "plan_id": "t", "version": 2,
            "steps": [
                {"id": "consumer", "adapter": "local", "command": "echo",
                 "repeat": {"for_each": {"from": "nonexistent.produces.x"}}},
            ],
        })


def test_i6_lease_epoch_cas_passes() -> None:
    validate_mutation(None, _valid_plan(), lease_epoch_actual=5, lease_epoch_expected=5)


def test_i6_lease_epoch_cas_rejects_stale() -> None:
    with pytest.raises(MutationInvariantError) as exc:
        validate_mutation(None, _valid_plan(), lease_epoch_actual=3, lease_epoch_expected=5)
    assert exc.value.invariant_id == "I6_lease_epoch_cas"


def test_all_six_invariant_ids_are_stable() -> None:
    assert len(INVARIANTS) == 6
    assert INVARIANTS == (
        "I1_schema",
        "I2_sibling_uniqueness",
        "I3_produces_refs",
        "I4_adapter_shape",
        "I5_repeat_source",
        "I6_lease_epoch_cas",
    )


# ---------------------------------------------------------------------------
# Legacy import compatibility (CodeStep/AttestedStep/NestedStep are placeholders)
# ---------------------------------------------------------------------------

def test_legacy_imports_still_resolve() -> None:
    """Ensure CodeStep, AttestedStep, NestedStep are still importable placeholders."""
    from astrid.core.task.plan import AttestedStep, CodeStep, NestedStep
    assert CodeStep is not None
    assert AttestedStep is not None
    assert NestedStep is not None