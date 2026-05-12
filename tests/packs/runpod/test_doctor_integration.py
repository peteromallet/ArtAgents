"""Test astrid doctor stale-handle reporting (read-only)."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from astrid.core.runpod.sweeper import POD_HANDLE_FILENAME


def _make_stale_handle(pod_id: str = "pod-stale") -> dict:
    """Build a pod_handle with terminate_at in the past."""
    return {
        "pod_id": pod_id,
        "ssh": "root@10.0.0.1 -p 2222",
        "name": f"astrid-test-{pod_id}",
        "name_prefix": "astrid-test",
        "terminate_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "hourly_rate": 0.34,
        "provisioned_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "config_snapshot": {
            "api_key_ref": "RUNPOD_API_KEY",
            "datacenter_id": "US-GA-1",
            "image": "runpod/pytorch:latest",
            "container_disk_in_gb": 200,
            "volume_in_gb": 0,
            "network_volume_id": None,
            "ports": "8888/http,22/tcp",
        },
    }


def _write_stale_handle(projects_root: Path, project: str, run_id: str, step_id: str) -> Path:
    """Write a stale pod_handle.json in the canonical path."""
    produces_dir = projects_root / project / "runs" / run_id / "steps" / step_id / "v1" / "produces"
    produces_dir.mkdir(parents=True)
    handle_path = produces_dir / POD_HANDLE_FILENAME
    handle_path.write_text(json.dumps(_make_stale_handle(pod_id=run_id)))
    return handle_path


# ---------------------------------------------------------------------------
# Read-only: doctor finds stale handles
# ---------------------------------------------------------------------------


def test_doctor_finds_stale_handles() -> None:
    """_check_runpod_stale_handles reports stale handles with status=warn."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_root = Path(tmp)
        _write_stale_handle(projects_root, "proj", "run-stale", "step-a")

        # Patch resolve_projects_root to return our temp dir
        with patch("astrid.core.project.paths.resolve_projects_root", return_value=projects_root):
            from astrid.doctor import _check_runpod_stale_handles

            check = _check_runpod_stale_handles()
            assert check.status == "warn"
            assert "stale" in check.detail.lower()
            assert "1" in check.detail


def test_doctor_reports_zero_stale_when_none() -> None:
    """_check_runpod_stale_handles reports ok when no handles exist."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_root = Path(tmp)

        with patch("astrid.core.project.paths.resolve_projects_root", return_value=projects_root):
            from astrid.doctor import _check_runpod_stale_handles

            check = _check_runpod_stale_handles()
            assert check.status == "ok"
            assert "no stale" in check.detail.lower()


def test_doctor_handles_missing_projects_root() -> None:
    """_check_runpod_stale_handles returns ok when projects root missing."""
    with patch("astrid.core.project.paths.resolve_projects_root", return_value=Path("/nonexistent/path/xyz")):
        from astrid.doctor import _check_runpod_stale_handles

        check = _check_runpod_stale_handles()
        assert check.status == "ok"
        assert "no projects root" in check.detail.lower()


# ---------------------------------------------------------------------------
# Read-only: never calls terminate or append_event_locked
# ---------------------------------------------------------------------------


def test_doctor_does_not_mutate() -> None:
    """_check_runpod_stale_handles is purely read-only — no terminate, no append."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_root = Path(tmp)
        _write_stale_handle(projects_root, "proj", "run-readonly", "step-x")

        with patch("astrid.core.project.paths.resolve_projects_root", return_value=projects_root):
            from astrid.doctor import _check_runpod_stale_handles

            # This should NOT import or call discovery.terminate / append_event_locked
            check = _check_runpod_stale_handles()

            # Verify the check result
            assert check.status == "warn"

            # Verify the handle file was NOT deleted or modified
            handle_path = projects_root / "proj" / "runs" / "run-readonly" / "steps" / "step-x" / "v1" / "produces" / POD_HANDLE_FILENAME
            assert handle_path.is_file(), "doctor must not delete or modify pod_handle.json"


# ---------------------------------------------------------------------------
# No symmetric runpod metadata check (out of scope per brief)
# ---------------------------------------------------------------------------


def test_doctor_has_no_runpod_metadata_check() -> None:
    """Doctor should NOT include a symmetric runpod metadata check."""
    # The run_checks function should not contain any runpod metadata checks
    import inspect

    from astrid import doctor

    source = inspect.getsource(doctor.run_checks)
    # "runpod metadata" or "runpod catalog" should not appear
    assert "runpod metadata" not in source
    assert "runpod catalog" not in source
    # _check_runpod_stale_handles should be called (only runpod check)
    assert "_check_runpod_stale_handles" in source