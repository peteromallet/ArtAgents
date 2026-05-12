"""Tests for astrid step retry-fetch verb (Sprint 5a T13)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from astrid.core.adapter.remote_artifact_fetch import FetchResult
from astrid.core.task.lifecycle import cmd_step_retry_fetch
from astrid.core.task.plan import ProducesEntry, Step, Check, TaskPlan


# ---------------------------------------------------------------------------
# Synthetic run state helper
# ---------------------------------------------------------------------------


def _build_synthetic_run(
    tmp_path: Path,
    slug: str = "demo",
    run_id: str = "run-1",
    *,
    step_id: str = "render",
    step_state: str = "awaiting_fetch",
    with_plan: bool = True,
) -> tuple[Path, Path]:
    """Create minimal project/run structure for testing retry-fetch."""
    proj_root = tmp_path / "projects" / slug
    run_dir = proj_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write a minimal plan.json in project root
    if with_plan:
        plan = {
            "plan_id": f"test-{run_id}",
            "version": 2,
            "steps": [
                {
                    "id": step_id,
                    "adapter": "remote-artifact",
                    "command": "echo test-job",
                    "produces": {
                        "output": {
                            "path": "result.json",
                            "check": {
                                "check_id": "file_nonempty",
                                "params": {},
                                "sentinel": False,
                            },
                        }
                    },
                }
            ],
        }
        (proj_root / "plan.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8"
        )

    # Create step directory and remote_state.json
    step_dir = run_dir / "steps" / step_id / "v1"
    step_dir.mkdir(parents=True, exist_ok=True)
    produces_dir = step_dir / "produces"
    produces_dir.mkdir(parents=True, exist_ok=True)

    remote_state = {
        "job_id": "job-1",
        "started_at": "2025-01-01T00:00:00.000Z",
        "command": "echo test-job",
        "poll_interval_seconds": 1,
        "pid": -1,
    }
    (step_dir / "remote_state.json").write_text(
        json.dumps(remote_state), encoding="utf-8"
    )
    (step_dir / "returncode").write_text("0", encoding="utf-8")

    # Write events.jsonl (events use plan_step_path as list)
    events_path = run_dir / "events.jsonl"
    events = [
        {"kind": "run_started", "run_id": run_id, "ts": "2025-01-01T00:00:00Z"},
        {
            "kind": "step_dispatched",
            "plan_step_path": [step_id],
            "adapter": "remote-artifact",
            "ts": "2025-01-01T00:00:01Z",
        },
    ]

    if step_state == "awaiting_fetch":
        events.append({
            "kind": "step_awaiting_fetch",
            "plan_step_path": [step_id],
            "missing": ["result.json"],
            "mismatched": [],
            "reason": "1 artifact missing",
            "adapter": "remote-artifact",
            "ts": "2025-01-01T00:00:02Z",
        })
    elif step_state == "completed":
        events.append({
            "kind": "step_completed",
            "plan_step_path": [step_id],
            "adapter": "remote-artifact",
            "returncode": 0,
            "cost": None,
            "ts": "2025-01-01T00:00:03Z",
        })
    elif step_state == "dispatched":
        pass  # Only dispatched event, no terminal
    elif step_state == "failed":
        events.append({
            "kind": "step_failed",
            "plan_step_path": [step_id],
            "adapter": "remote-artifact",
            "returncode": 1,
            "ts": "2025-01-01T00:00:03Z",
        })

    events_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )

    # Write a run.json (needed by current run detection)
    run_json = {"run_id": run_id, "created_at": "2025-01-01T00:00:00Z"}
    (run_dir / "run.json").write_text(
        json.dumps(run_json), encoding="utf-8"
    )

    return proj_root, run_dir


# ---------------------------------------------------------------------------
# Tests — retry-fetch from awaiting_fetch
# ---------------------------------------------------------------------------


@patch("astrid.core.adapter.remote_artifact_fetch.fetch_artifacts")
def test_retry_fetch_round_trip_missing_to_completed(
    mock_fetch: object, tmp_path: Path
) -> None:
    """Round-trip: missing artifact -> awaiting_fetch -> retry-fetch -> completed."""
    slug, run_id = "demo", "run-1"
    proj_root, run_dir = _build_synthetic_run(
        tmp_path, slug, run_id, step_state="awaiting_fetch"
    )

    # Write the actual artifact so fetch succeeds
    (run_dir / "steps" / "render" / "v1" / "produces" / "result.json").write_text(
        '{"ok": true}', encoding="utf-8"
    )

    mock_fetch.return_value = FetchResult(
        status="completed",
        fetched=["result.json"],
        missing=[],
        mismatched=[],
        checksums={"result.json": "abc123"},
    )

    with patch(
        "astrid.core.task.lifecycle.project_dir",
        return_value=proj_root,
    ), patch("astrid.core.task.lifecycle.validate_project_slug", return_value=slug), patch(
        "astrid.core.task.lifecycle.validate_run_id", return_value=run_id
    ), patch(
        "astrid.core.task.lifecycle.append_event"
    ) as mock_append:
        rc = cmd_step_retry_fetch(
            ["render", "--project", slug, "--run", run_id],
            projects_root=tmp_path / "projects",
        )

    assert rc == 0
    # Should emit step_completed event
    assert mock_append.call_count >= 1
    # Verify at least one call has kind="step_completed"
    found_completed = False
    for call_obj in mock_append.call_args_list:
        args_tuple = call_obj.args if hasattr(call_obj, 'args') else ()
        if len(args_tuple) > 1:
            event = args_tuple[1]
            if isinstance(event, dict) and event.get("kind") == "step_completed":
                found_completed = True
                break
    assert found_completed, f"Expected step_completed event, got calls: {mock_append.call_args_list}"


@patch("astrid.core.adapter.remote_artifact_fetch.fetch_artifacts")
def test_retry_fetch_still_missing_stays_awaiting(
    mock_fetch: object, tmp_path: Path
) -> None:
    """retry-fetch re-emits step_awaiting_fetch when artifacts still missing (exits 1)."""
    slug, run_id = "demo", "run-1"
    proj_root, run_dir = _build_synthetic_run(
        tmp_path, slug, run_id, step_state="awaiting_fetch"
    )

    mock_fetch.return_value = FetchResult(
        status="awaiting_fetch",
        fetched=["result.json"],
        missing=["other.json"],
        mismatched=[],
        checksums={"result.json": "abc123"},
    )

    with patch(
        "astrid.core.task.lifecycle.project_dir",
        return_value=proj_root,
    ), patch("astrid.core.task.lifecycle.validate_project_slug", return_value=slug), patch(
        "astrid.core.task.lifecycle.validate_run_id", return_value=run_id
    ), patch(
        "astrid.core.task.lifecycle.append_event"
    ) as mock_append:
        rc = cmd_step_retry_fetch(
            ["render", "--project", slug, "--run", run_id],
            projects_root=tmp_path / "projects",
        )

    # Returns 1 because step is still awaiting_fetch
    assert rc == 1
    # But it still emits step_awaiting_fetch event
    found_awaiting = False
    for call_obj in mock_append.call_args_list:
        args_tuple = call_obj.args if hasattr(call_obj, 'args') else ()
        if len(args_tuple) > 1:
            event = args_tuple[1]
            if isinstance(event, dict) and event.get("kind") == "step_awaiting_fetch":
                found_awaiting = True
                break
    assert found_awaiting, f"Expected step_awaiting_fetch event, got: {mock_append.call_args_list}"


# ---------------------------------------------------------------------------
# Tests — guards
# ---------------------------------------------------------------------------


def test_retry_fetch_on_completed_step_noop(tmp_path: Path) -> None:
    """retry-fetch on a completed step is a no-op + warning (exit 0)."""
    slug, run_id = "demo", "run-1"
    proj_root, run_dir = _build_synthetic_run(
        tmp_path, slug, run_id, step_state="completed"
    )

    # Mock project_dir to return our synthetic project root
    with patch(
        "astrid.core.task.lifecycle.project_dir",
        return_value=proj_root,
    ), patch("astrid.core.task.lifecycle.validate_project_slug", return_value=slug), patch(
        "astrid.core.task.lifecycle.validate_run_id", return_value=run_id
    ):
        rc = cmd_step_retry_fetch(
            ["render", "--project", slug, "--run", run_id],
            projects_root=tmp_path / "projects",
        )

    assert rc == 0  # No-op exits 0


def test_retry_fetch_rejects_non_awaiting_step(tmp_path: Path) -> None:
    """retry-fetch rejects step that is dispatched (not awaiting_fetch)."""
    slug, run_id = "demo", "run-1"
    proj_root, run_dir = _build_synthetic_run(
        tmp_path, slug, run_id, step_state="dispatched"
    )

    with patch(
        "astrid.core.task.lifecycle.project_dir",
        return_value=proj_root,
    ), patch("astrid.core.task.lifecycle.validate_project_slug", return_value=slug), patch(
        "astrid.core.task.lifecycle.validate_run_id", return_value=run_id
    ):
        rc = cmd_step_retry_fetch(
            ["render", "--project", slug, "--run", run_id],
            projects_root=tmp_path / "projects",
        )

    assert rc == 1  # Rejected


def test_retry_fetch_rejects_failed_step(tmp_path: Path) -> None:
    """retry-fetch rejects a failed step."""
    slug, run_id = "demo", "run-1"
    proj_root, run_dir = _build_synthetic_run(
        tmp_path, slug, run_id, step_state="failed"
    )

    with patch(
        "astrid.core.task.lifecycle.project_dir",
        return_value=proj_root,
    ), patch("astrid.core.task.lifecycle.validate_project_slug", return_value=slug), patch(
        "astrid.core.task.lifecycle.validate_run_id", return_value=run_id
    ):
        rc = cmd_step_retry_fetch(
            ["render", "--project", slug, "--run", run_id],
            projects_root=tmp_path / "projects",
        )

    assert rc == 1  # Rejected


# ---------------------------------------------------------------------------
# Tests — run_completed re-check
# ---------------------------------------------------------------------------


@patch("astrid.core.adapter.remote_artifact_fetch.fetch_artifacts")
@patch("astrid.core.task.lifecycle._run_is_complete")
def test_retry_fetch_emits_run_completed_when_all_done(
    mock_run_complete: object, mock_fetch: object, tmp_path: Path
) -> None:
    """After retry-fetch completes last awaiting step, run_completed fires."""
    slug, run_id = "demo", "run-1"
    proj_root, run_dir = _build_synthetic_run(
        tmp_path, slug, run_id, step_state="awaiting_fetch"
    )

    (run_dir / "steps" / "render" / "v1" / "produces" / "result.json").write_text(
        '{"ok": true}', encoding="utf-8"
    )

    mock_fetch.return_value = FetchResult(
        status="completed",
        fetched=["result.json"],
        missing=[],
        mismatched=[],
        checksums={"result.json": "abc123"},
    )
    mock_run_complete.return_value = True

    with patch(
        "astrid.core.task.lifecycle.project_dir",
        return_value=proj_root,
    ), patch("astrid.core.task.lifecycle.validate_project_slug", return_value=slug), patch(
        "astrid.core.task.lifecycle.validate_run_id", return_value=run_id
    ), patch(
        "astrid.core.task.lifecycle.append_event"
    ) as mock_append:
        rc = cmd_step_retry_fetch(
            ["render", "--project", slug, "--run", run_id],
            projects_root=tmp_path / "projects",
        )

    assert rc == 0
    # Should emit step_completed and run_completed events
    found_step_completed = False
    found_run_completed = False
    for call_obj in mock_append.call_args_list:
        args_tuple = call_obj.args if hasattr(call_obj, 'args') else ()
        if len(args_tuple) > 1:
            event = args_tuple[1]
            if isinstance(event, dict):
                if event.get("kind") == "step_completed":
                    found_step_completed = True
                if event.get("kind") == "run_completed":
                    found_run_completed = True
    assert found_step_completed, f"Expected step_completed, got: {mock_append.call_args_list}"
    assert found_run_completed, f"Expected run_completed, got: {mock_append.call_args_list}"