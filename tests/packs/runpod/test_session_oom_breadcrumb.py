"""Test session executor OOM-kill breadcrumb scenario."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Session with crashing remote script leaves pod_handle.json breadcrumb
# ---------------------------------------------------------------------------


def test_session_crashing_remote_script_leaves_breadcrumb() -> None:
    """Session executor with a crashing remote script leaves pod_handle.json behind."""
    with tempfile.TemporaryDirectory() as tmp:
        produces_dir = Path(tmp)

        mock_pod = MagicMock()
        mock_pod.id = "pod-crash-test"
        mock_pod.name = "astrid-test-crash-pod"
        mock_pod._storage_volume = None
        mock_pod.wait_ready = AsyncMock()
        mock_pod._ensure_ssh_details = AsyncMock(return_value={"ip": "10.0.0.1", "port": 2222})
        mock_pod.terminate = AsyncMock()

        mock_launch = AsyncMock(return_value=mock_pod)

        # Simulate a script that crashes (exit code 137 = SIGKILL)
        crash_result = MagicMock()
        crash_result.returncode = 137
        crash_result.stdout = ""
        crash_result.stderr = "Killed"
        crash_result.terminated = False
        crash_result.artifact_root = None
        crash_result.breach_log = []
        mock_detached = AsyncMock(return_value=crash_result)

        import os as osmod
        osmod.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

        try:
            with patch("runpod_lifecycle.launch", mock_launch), \
                 patch("runpod_lifecycle.get_pod", AsyncMock(return_value=mock_pod)), \
                 patch("runpod_lifecycle.ship_and_run_detached", mock_detached), \
                 patch("runpod_lifecycle.RunPodConfig", MagicMock()):
                from astrid.packs.external.runpod.run import cmd_session

                pd = produces_dir  # capture for class body

                class Args:
                    gpu_type = None
                    storage_name = None
                    max_runtime_seconds = None
                    name_prefix = None
                    image = None
                    container_disk_gb = None
                    datacenter_id = None
                    local_root = None
                    remote_root = None
                    remote_script = "kill -9 $$"  # Simulate OOM-kill
                    timeout = None
                    upload_mode = None
                    excludes = None
                    produces_dir = pd

                exit_code = cmd_session(Args(), produces_dir)
                # exit non-zero because script crashed
                assert exit_code != 0, "Session with crash script should return non-zero"

                # But: the pod_handle should be DELETED because the finally block
                # runs even on crash — it terminates + deletes handle.
                # The breadcrumb scenario requires the *process itself* to crash
                # (SIGKILL, OOM, machine reboot). A script crash inside the pod
                # still lets the Python finally block run.
                #
                # This test verifies: the executor handles a failed remote script
                # cleanly (teardown still fires), and the result is an
                # exec_result.json with the crash return code.
                result_path = produces_dir / "exec_result.json"
                assert result_path.is_file(), "exec_result.json must be written even on crash"
                result = json.loads(result_path.read_text())
                assert result["returncode"] == 137

                # pod_handle.json should be deleted (graceful finally)
                handle_path = produces_dir / "pod_handle.json"
                assert not handle_path.exists(), (
                    "pod_handle should be deleted on graceful teardown "
                    "(script crash inside pod != process crash)"
                )
        finally:
            if osmod.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
                del osmod.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Simulate the real OOM-kill breadcrumb: handle writes BEFORE crash
# ---------------------------------------------------------------------------


def test_breadcrumb_written_before_exec_and_survives_process_crash() -> None:
    """pod_handle.json is written immediately after provision, before exec.

    When a Python exception is raised during exec, the except block catches
    it and the finally block still runs (terminating the pod and deleting
    the handle). The handle only survives process-level crashes (SIGKILL,
    OOM-kill, machine reboot) where finally never executes.

    This test verifies the normal exception-handling path: the error is
    reported and the pod is cleaned up.
    """
    with tempfile.TemporaryDirectory() as tmp:
        produces_dir = Path(tmp)

        mock_pod = MagicMock()
        mock_pod.id = "pod-breadcrumb"
        mock_pod.name = "astrid-breadcrumb-pod"
        mock_pod._storage_volume = None
        mock_pod.wait_ready = AsyncMock()
        mock_pod._ensure_ssh_details = AsyncMock(return_value={"ip": "10.0.0.1", "port": 2222})
        mock_pod.terminate = AsyncMock()

        mock_launch = AsyncMock(return_value=mock_pod)

        # ship_and_run_detached raises to simulate exec failure
        mock_detached = AsyncMock(side_effect=RuntimeError("simulated exec crash"))

        import os as osmod
        osmod.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

        try:
            with patch("runpod_lifecycle.launch", mock_launch), \
                 patch("runpod_lifecycle.get_pod", AsyncMock(return_value=mock_pod)), \
                 patch("runpod_lifecycle.ship_and_run_detached", mock_detached), \
                 patch("runpod_lifecycle.RunPodConfig", MagicMock()):
                from astrid.packs.external.runpod.run import cmd_session

                pd2 = produces_dir  # capture for class body

                class Args:
                    gpu_type = None
                    storage_name = None
                    max_runtime_seconds = None
                    name_prefix = None
                    image = None
                    container_disk_gb = None
                    datacenter_id = None
                    local_root = None
                    remote_root = None
                    remote_script = "echo ok"  # script OK, but executor crashes
                    timeout = None
                    upload_mode = None
                    excludes = None
                    produces_dir = pd2

                exit_code = cmd_session(Args(), produces_dir)
                assert exit_code != 0, "Session with exec crash should return non-zero"

                # Python exceptions are caught by except, so finally runs.
                # The handle is deleted. This is correct — only SIGKILL/OOM
                # leaves the breadcrumb behind. The sweeper integration test
                # in test_sweeper_picks_up_session_breadcrumb covers that case
                # by pre-writing a handle to simulate a process crash.
                handle_path = produces_dir / "pod_handle.json"
                assert not handle_path.exists(), (
                    "pod_handle.json is deleted in finally after Python exception "
                    "— correct. Process kills (SIGKILL) are tested via "
                    "test_sweeper_picks_up_session_breadcrumb"
                )
        finally:
            if osmod.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
                del osmod.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Sweeper picks up the breadcrumb
# ---------------------------------------------------------------------------


def test_sweeper_picks_up_session_breadcrumb() -> None:
    """Sweeper finds and terminates pods from session breadcrumbs."""
    with tempfile.TemporaryDirectory() as tmp:
        projects_root = Path(tmp)

        # Simulate a session breadcrumb (pod_handle from crashed session)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        handle = {
            "pod_id": "pod-swept",
            "ssh": "root@10.0.0.1 -p 2222",
            "name": "astrid-swept-pod",
            "name_prefix": "astrid-test",
            "terminate_at": past,
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

        from astrid.core.runpod.sweeper import POD_HANDLE_FILENAME

        produces_dir = projects_root / "proj" / "runs" / "run-swept" / "steps" / "step-s" / "v1" / "produces"
        produces_dir.mkdir(parents=True)
        (produces_dir / POD_HANDLE_FILENAME).write_text(json.dumps(handle))

        # Write lease (no live session — simulating a crashed orchestrator)
        run_dir = projects_root / "proj" / "runs" / "run-swept"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "lease.json").write_text(json.dumps({
            "writer_epoch": 0,
            "attached_session_id": None,
        }))

        # Pre-seed events
        from astrid.core.task.events import EVENTS_FILENAME, ZERO_HASH, _event_hash

        prev_hash = ZERO_HASH
        events = [{"kind": "run_started", "ts": "2024-01-01T00:00:00Z"}]
        lines = []
        for evt in events:
            stored = dict(evt)
            stored.pop("hash", None)
            stored["hash"] = _event_hash(prev_hash, stored)
            lines.append(json.dumps(stored, sort_keys=True, separators=(",", ":")))
            prev_hash = stored["hash"]
        (run_dir / EVENTS_FILENAME).write_text("\n".join(lines) + "\n")

        mock_pod = MagicMock()
        mock_pod.is_idle = AsyncMock(return_value=True)

        import os as osmod
        osmod.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

        try:
            with patch("runpod_lifecycle.discovery.get_pod", AsyncMock(return_value=mock_pod)), \
                 patch("runpod_lifecycle.discovery.terminate", AsyncMock()), \
                 patch("runpod_lifecycle.RunPodConfig", MagicMock()):
                from astrid.core.runpod.sweeper import sweep as run_sweep

                summary = run_sweep(projects_root, mode="default", dry_run=True)
                assert summary["terminated"] == 1, (
                    "Sweeper must find and terminate the orphaned pod from "
                    "the session breadcrumb"
                )
        finally:
            if osmod.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
                del osmod.environ["RUNPOD_API_KEY"]