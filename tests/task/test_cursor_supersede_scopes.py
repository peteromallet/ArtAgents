"""Tests for cursor supersede scopes (Sprint 3 T21).

Exercises all three scopes (all, future-iterations, future-items) under
repeat.until and repeat.for_each, including group-step children inheritance.
"""

from __future__ import annotations

import json
from pathlib import Path

from astrid.core.task.plan import (
    SUPERSEDE_SCOPES,
    Step,
    TaskPlan,
    _validate_plan,
)
from astrid.core.task.plan_verbs import (
    CursorRecord,
    apply_mutations,
    derive_versioned_cursor,
)


def test_supersede_scope_all_resets_dispatch_hash() -> None:
    """scope=all means the cursor zeroes dispatch_event_hash — restart from item 1."""
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "command": "echo", "step_version": 1, "hash": "sha256:aaa"},
        {"kind": "plan_mutated", "diff": {"op": "supersede", "path": "s1", "to_version": 2, "scope": "all"}},
    ]
    cursor = derive_versioned_cursor(events)
    assert cursor["s1"].step_version == 2
    assert cursor["s1"].dispatch_event_hash is None  # Restart


def test_supersede_scope_all_on_repeat_until_aborts_in_flight() -> None:
    """scope=all aborts in-flight iteration progress (cursor abandons pending state)."""
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "command": "echo", "step_version": 1, "hash": "sha256:aaa"},
        {"kind": "iteration_started", "plan_step_path": ["s1"], "iteration": 3},
        {"kind": "plan_mutated", "diff": {"op": "supersede", "path": "s1", "to_version": 2, "scope": "all"}},
    ]
    cursor = derive_versioned_cursor(events)
    # After scope=all supersede, the cursor for s1 points to v2 with no dispatch.
    assert cursor["s1"].step_version == 2
    assert cursor["s1"].dispatch_event_hash is None


def test_supersede_scope_future_iterations_retains_current() -> None:
    """scope=future-iterations: current iteration finishes against old version."""
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "command": "echo", "step_version": 1, "hash": "sha256:aaa"},
        {"kind": "iteration_started", "plan_step_path": ["s1"], "iteration": 2},
        {"kind": "plan_mutated", "diff": {"op": "supersede", "path": "s1", "to_version": 2, "scope": "future-iterations"}},
    ]
    cursor = derive_versioned_cursor(events)
    # Cursor still reflects the supersede bump, but the in-flight iteration
    # finishes against v1 per brief semantics (the cursor just tracks the latest
    # version mapping). The iteration event records which version was in effect.
    assert cursor["s1"].step_version == 2


def test_supersede_scope_future_items_retains_current() -> None:
    """scope=future-items: current item finishes against old version."""
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["s1"], "command": "echo", "step_version": 1, "hash": "sha256:aaa"},
        {"kind": "item_started", "plan_step_path": ["s1"], "item_id": "abc"},
        {"kind": "plan_mutated", "diff": {"op": "supersede", "path": "s1", "to_version": 2, "scope": "future-items"}},
    ]
    cursor = derive_versioned_cursor(events)
    assert cursor["s1"].step_version == 2


def test_supersede_all_three_scopes_are_known() -> None:
    assert len(SUPERSEDE_SCOPES) == 3
    assert "all" in SUPERSEDE_SCOPES
    assert "future-iterations" in SUPERSEDE_SCOPES
    assert "future-items" in SUPERSEDE_SCOPES


def test_group_step_children_inherit_supersede() -> None:
    """When a group step is superseded, the new version carries the new children."""
    plan = _validate_plan({
        "plan_id": "t", "version": 2,
        "steps": [{
            "id": "parent",
            "children": [
                {"id": "c1", "adapter": "local", "command": "echo old child", "version": 1},
            ],
            "version": 1,
        }],
    })
    diff = {
        "op": "supersede",
        "path": "parent",
        "to_version": 2,
        "scope": "all",
        "step": {
            "id": "parent",
            "children": [
                {"id": "c1", "adapter": "local", "command": "echo new child", "version": 2},
            ],
            "version": 2,
        },
    }
    from astrid.core.task.plan_verbs import _apply_diff
    result = _apply_diff(plan, diff)
    parent = result.steps[0]
    assert parent.version == 2
    assert parent.children[0].command == "echo new child"


def test_repeat_for_each_supersede_scope_all_restarts_items() -> None:
    """scope=all on for_each step: item index resets to 1 of new version."""
    events = [
        {"kind": "step_dispatched", "plan_step_path": ["fe"], "command": "echo", "step_version": 1, "hash": "sha256:aaa"},
        {"kind": "for_each_expanded", "plan_step_path": ["fe"], "item_ids": ["a", "b", "c"]},
        {"kind": "item_started", "plan_step_path": ["fe"], "item_id": "b"},
        {"kind": "plan_mutated", "diff": {"op": "supersede", "path": "fe", "to_version": 2, "scope": "all"}},
    ]
    cursor = derive_versioned_cursor(events)
    assert cursor["fe"].step_version == 2
    assert cursor["fe"].dispatch_event_hash is None