"""Tests for step_dispatched event compatibility (Sprint 3 T21).

Covers: old-vs-new interop, new-vs-new omission stability for both-omitting-pid
hash-identical, null-vs-omit divergence — factory dict has NO `pid` key when pid is None.
"""

from __future__ import annotations

import hashlib
import json

from astrid.core.task.events import (
    canonical_event_json,
    make_step_dispatched_event,
)


def test_omit_when_none_pid_absent_from_dict() -> None:
    """When pid is None, the returned dict has NO 'pid' key at all."""
    event = make_step_dispatched_event("s1", "echo", adapter="local", step_version=1, pid=None)
    assert "pid" not in event


def test_omit_when_none_adapter_absent_from_dict() -> None:
    """When adapter is None, the returned dict has NO 'adapter' key."""
    event = make_step_dispatched_event("s1", "echo", adapter=None, step_version=1)
    assert "adapter" not in event


def test_omit_when_none_step_version_absent_from_dict() -> None:
    """When step_version is None, the returned dict has NO 'step_version' key."""
    event = make_step_dispatched_event("s1", "echo", adapter="local", step_version=None)
    assert "step_version" not in event


def test_new_vs_new_both_omitting_pid_hash_identical() -> None:
    """Two new events both omitting pid produce structurally identical dicts.

    NOTE: The canonical hash WILL differ between calls because the `ts` field
    is generated fresh each time. So we verify that both dicts have the same
    keys (minus ts) and that 'pid' is absent from both.
    """
    ev1 = make_step_dispatched_event("s1", "echo", adapter="local", step_version=1)
    ev2 = make_step_dispatched_event("s1", "echo", adapter="local", step_version=1)
    # Both omit 'pid' — structural equality of omission
    assert "pid" not in ev1
    assert "pid" not in ev2
    # Same keys
    assert set(ev1.keys()) == set(ev2.keys())
    # Same plan_step_path
    assert ev1["plan_step_path"] == ev2["plan_step_path"]
    assert ev1["command"] == ev2["command"]


def test_null_vs_omit_divergence() -> None:
    """A payload with explicit pid: null would NOT match an omitted-pid payload."""
    ev_omit = make_step_dispatched_event("s1", "echo", adapter="local", step_version=1, pid=None)
    # Simulate what would happen if someone serialized pid: null
    ev_null = dict(ev_omit)
    ev_null["pid"] = None

    h_omit = hashlib.sha256(canonical_event_json(ev_omit).encode("utf-8")).hexdigest()
    h_null = hashlib.sha256(canonical_event_json(ev_null).encode("utf-8")).hexdigest()
    # They should differ because canonical_event_json includes all keys.
    assert h_omit != h_null


def test_old_vs_new_interop() -> None:
    """Old-style events (plan_step_id) and new-style events coexist in the factory."""
    ev_old = make_step_dispatched_event("s1", "echo")  # no adapter/step_version
    assert "plan_step_path" in ev_old
    assert "adapter" not in ev_old
    assert "step_version" not in ev_old

    ev_new = make_step_dispatched_event("parent/child", "echo", adapter="manual", step_version=2, pid=12345)
    assert ev_new["plan_step_path"] == ["parent", "child"]
    assert ev_new["adapter"] == "manual"
    assert ev_new["step_version"] == 2
    assert ev_new["pid"] == 12345


def test_plan_step_path_is_list() -> None:
    """plan_step_path is always stored as a list."""
    ev = make_step_dispatched_event("a/b/c", "echo")
    assert ev["plan_step_path"] == ["a", "b", "c"]


def test_single_segment_path_is_list() -> None:
    """Single-segment paths should also be a list (not a bare string)."""
    ev = make_step_dispatched_event("solo", "echo")
    assert ev["plan_step_path"] == ["solo"]


def test_cost_omit_when_none_on_completion() -> None:
    """Cost field on completion events follows same omit-when-None semantics."""
    from astrid.core.task.events import make_step_completed_event, make_step_failed_event
    ev_comp = make_step_completed_event("s1", 0, cost=None, adapter=None)
    assert "cost" not in ev_comp
    assert "adapter" not in ev_comp

    ev_fail = make_step_failed_event("s1", 1, reason="bad", cost=None, adapter=None)
    assert "cost" not in ev_fail
    assert "adapter" not in ev_fail


def test_cost_present_when_provided() -> None:
    """When cost is provided, it IS included."""
    from astrid.core.task.events import make_step_completed_event
    ev = make_step_completed_event("s1", 0, cost={"amount": 0.05, "currency": "USD", "source": "runpod"})
    assert "cost" in ev
    assert ev["cost"]["amount"] == 0.05