"""Tests for ManualAdapter (Sprint 3 T22).

Covers: dispatch payload at runs/<run>/steps/<id>/v<N>/dispatch.json,
ack-driven AND inbox-driven completion equivalent, missing submitted_by_kind rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrid.core.adapter import RunContext
from astrid.core.adapter.manual import ManualAdapter
from astrid.core.task.plan import AckRule, Step


@pytest.fixture
def adapter() -> ManualAdapter:
    return ManualAdapter()


def _make_ctx(tmp_path: Path, **kwargs) -> RunContext:
    defaults = {
        "slug": "demo",
        "run_id": "run-1",
        "project_root": tmp_path,
        "plan_step_path": ("review",),
        "step_version": 1,
    }
    defaults.update(kwargs)
    return RunContext(**defaults)


def _make_step(**kwargs) -> Step:
    defaults = {"id": "review", "adapter": "manual", "command": "Please review the output", "requires_ack": True}
    defaults.update(kwargs)
    return Step(**defaults)


# ---------------------------------------------------------------------------
# dispatch writes payload
# ---------------------------------------------------------------------------

def test_dispatch_writes_payload(adapter: ManualAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(instructions="Check for errors")
    result = adapter.dispatch(step, ctx)
    assert result.status == "dispatched"
    assert result.started_at is not None

    dp = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "dispatch.json"
    assert dp.exists()
    payload = json.loads(dp.read_text())
    assert payload["step_id"] == "review"
    assert payload["step_version"] == 1
    assert payload["command"] == "Please review the output"
    assert payload["adapter"] == "manual"
    assert payload["requires_ack"] is True
    assert payload["instructions"] == "Check for errors"


def test_dispatch_payload_path_is_versioned(adapter: ManualAdapter, tmp_path: Path) -> None:
    """Verify the dispatch payload lands at the versioned path."""
    ctx = _make_ctx(tmp_path, step_version=2)
    step = _make_step(version=2)
    adapter.dispatch(step, ctx)

    dp = tmp_path / "runs" / "run-1" / "steps" / "review" / "v2" / "dispatch.json"
    assert dp.exists()


def test_dispatch_preserves_ack_rule(adapter: ManualAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(ack=AckRule(kind="agent"))
    adapter.dispatch(step, ctx)

    dp = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "dispatch.json"
    payload = json.loads(dp.read_text())
    assert payload.get("ack") == {"kind": "agent"}


def test_dispatch_rejects_empty_command(adapter: ManualAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step(command="   ")
    result = adapter.dispatch(step, ctx)
    assert result.status == "rejected"


# ---------------------------------------------------------------------------
# poll
# ---------------------------------------------------------------------------

def test_poll_pending_without_completion(adapter: ManualAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    # No dispatch yet, no completion
    result = adapter.poll(step, ctx)
    assert result.status == "pending"


# ---------------------------------------------------------------------------
# ack-driven completion
# ---------------------------------------------------------------------------

def test_complete_ack_driven(adapter: ManualAdapter, tmp_path: Path) -> None:
    """Ack-driven completion: cmd_ack writes produces/completion.json."""
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    adapter.dispatch(step, ctx)

    # Simulate what cmd_ack writes
    completion_dir = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "produces"
    completion_dir.mkdir(parents=True)
    (completion_dir / "completion.json").write_text(json.dumps({
        "status": "completed",
        "source": "ack",
        "submitted_by": "agent-1",
        "submitted_by_kind": "agent",
    }))

    result = adapter.complete(step, ctx)
    assert result.status == "completed"
    assert result.cost is None


def test_complete_ack_driven_failed(adapter: ManualAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    adapter.dispatch(step, ctx)

    completion_dir = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "produces"
    completion_dir.mkdir(parents=True)
    (completion_dir / "completion.json").write_text(json.dumps({
        "status": "failed",
        "reason": "Not approved",
        "source": "ack",
        "submitted_by": "agent-1",
        "submitted_by_kind": "agent",
    }))

    result = adapter.complete(step, ctx)
    assert result.status == "failed"


# ---------------------------------------------------------------------------
# inbox-driven completion
# ---------------------------------------------------------------------------

def test_complete_inbox_driven(adapter: ManualAdapter, tmp_path: Path) -> None:
    """Inbox-driven completion: inbox consumer writes produces/completion.json."""
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    adapter.dispatch(step, ctx)

    completion_dir = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "produces"
    completion_dir.mkdir(parents=True)
    (completion_dir / "completion.json").write_text(json.dumps({
        "status": "completed",
        "source": "inbox",
        "submitted_by": "agent-2",
        "submitted_by_kind": "agent",
    }))

    result = adapter.complete(step, ctx)
    assert result.status == "completed"


def test_complete_inbox_driven_missing_submitted_by_kind(adapter: ManualAdapter, tmp_path: Path) -> None:
    """Inbox completion without submitted_by_kind → rejected."""
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    adapter.dispatch(step, ctx)

    completion_dir = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "produces"
    completion_dir.mkdir(parents=True)
    (completion_dir / "completion.json").write_text(json.dumps({
        "status": "completed",
        "source": "inbox",
        "submitted_by": "agent-2",
        # missing submitted_by_kind
    }))

    result = adapter.complete(step, ctx)
    assert result.status == "failed"
    assert "submitted_by_kind" in result.reason.lower()


def test_complete_inbox_driven_missing_submitted_by(adapter: ManualAdapter, tmp_path: Path) -> None:
    """Inbox completion without submitted_by → rejected."""
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    adapter.dispatch(step, ctx)

    completion_dir = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "produces"
    completion_dir.mkdir(parents=True)
    (completion_dir / "completion.json").write_text(json.dumps({
        "status": "completed",
        "source": "inbox",
        "submitted_by_kind": "agent",
        # missing submitted_by
    }))

    result = adapter.complete(step, ctx)
    assert result.status == "failed"


def test_complete_with_cost(adapter: ManualAdapter, tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    step = _make_step()
    adapter.dispatch(step, ctx)

    completion_dir = tmp_path / "runs" / "run-1" / "steps" / "review" / "v1" / "produces"
    completion_dir.mkdir(parents=True)
    (completion_dir / "completion.json").write_text(json.dumps({
        "status": "completed",
        "source": "inbox",
        "submitted_by": "agent-3",
        "submitted_by_kind": "agent",
        "cost": {"amount": 0.10, "currency": "USD", "source": "openai"},
    }))

    result = adapter.complete(step, ctx)
    assert result.status == "completed"
    assert result.cost is not None
    assert result.cost.amount == 0.10
    assert result.cost.currency == "USD"