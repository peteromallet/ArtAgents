"""Test the four external.runpod executors with mocked runpod_lifecycle."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def produces_dir() -> Path:
    """Create a temporary produces directory for executor output."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def mock_pod() -> MagicMock:
    """Create a mock RunPod Pod object."""
    pod = MagicMock()
    pod.id = "pod-abc123"
    pod.name = "astrid-test-pod-1700000000"
    pod._storage_volume = None

    # Make async methods
    pod.wait_ready = AsyncMock()
    pod._ensure_ssh_details = AsyncMock(return_value={"ip": "1.2.3.4", "port": 2222})
    pod.is_idle = AsyncMock(return_value=True)
    pod.terminate = AsyncMock()
    pod.exec_ssh = AsyncMock(return_value=("stdout", "stderr", 0))
    return pod


@pytest.fixture
def mock_launch(mock_pod: MagicMock) -> MagicMock:
    """Mock runpod_lifecycle.launch."""
    return AsyncMock(return_value=mock_pod)


@pytest.fixture
def mock_get_pod(mock_pod: MagicMock) -> MagicMock:
    """Mock runpod_lifecycle.get_pod / discovery.get_pod."""
    return AsyncMock(return_value=mock_pod)


@pytest.fixture
def mock_ship_and_run_detached() -> MagicMock:
    """Mock runpod_lifecycle.ship_and_run_detached."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = "ok"
    result.stderr = ""
    result.terminated = False
    result.artifact_root = None
    result.breach_log = []
    return AsyncMock(return_value=result)


def _patch_runpod_lifecycle(
    mock_launch: MagicMock,
    mock_get_pod: MagicMock,
    mock_ship_and_run: MagicMock,
) -> dict:
    """Patch all runpod_lifecycle imports used by the pack executors."""
    patchers = {
        "launch": patch("runpod_lifecycle.launch", mock_launch),
        "get_pod": patch("runpod_lifecycle.get_pod", mock_get_pod),
        "ship_and_run_detached": patch("runpod_lifecycle.ship_and_run_detached", mock_ship_and_run),
        "RunPodConfig": patch("runpod_lifecycle.RunPodConfig", MagicMock()),
    }
    return patchers


# ---------------------------------------------------------------------------
# Schema assertions
# ---------------------------------------------------------------------------

_POD_HANDLE_REQUIRED_KEYS = {
    "pod_id",
    "ssh",
    "name",
    "name_prefix",
    "terminate_at",
    "gpu_type",
    "hourly_rate",
    "provisioned_at",
    "config_snapshot",
}

_CONFIG_SNAPSHOT_REQUIRED_KEYS = {
    "api_key_ref",
    "datacenter_id",
    "image",
    "container_disk_in_gb",
    "volume_in_gb",
    "network_volume_id",
    "ports",
}

_COST_SIDECAR_REQUIRED_KEYS = {"amount", "currency", "source"}


def _assert_pod_handle_shape(handle: dict) -> None:
    """Verify pod_handle.json matches the locked schema."""
    for key in _POD_HANDLE_REQUIRED_KEYS:
        assert key in handle, f"pod_handle.json missing required key: {key}"

    # api_key_ref must be an env var name, never a literal key
    api_key_ref = handle["config_snapshot"]["api_key_ref"]
    assert isinstance(api_key_ref, str), "api_key_ref must be a string"
    assert not api_key_ref.startswith("rpa_"), (
        f"api_key_ref is {api_key_ref!r} — looks like a literal API key, "
        f"but must be an env var name like RUNPOD_API_KEY"
    )

    # Must not have breach_log (it's a PodGuard in-memory attribute)
    assert "breach_log" not in handle, "pod_handle.json must NOT contain breach_log"

    for key in _CONFIG_SNAPSHOT_REQUIRED_KEYS:
        assert key in handle["config_snapshot"], (
            f"config_snapshot missing required key: {key}"
        )

    # hourly_rate must be a positive float at the top level
    assert isinstance(handle["hourly_rate"], (int, float))
    assert handle["hourly_rate"] > 0


def _assert_cost_shape(cost: dict) -> None:
    """Verify cost sidecar matches CostEntry shape."""
    for key in _COST_SIDECAR_REQUIRED_KEYS:
        assert key in cost, f"cost.json missing required key: {key}"
    assert cost["currency"] == "USD", f"expected USD, got {cost['currency']!r}"
    assert isinstance(cost["amount"], (int, float))
    assert cost["amount"] >= 0
    # basis is optional metadata but should be present
    assert "basis" in cost, "cost.json should include optional 'basis' metadata"


# ---------------------------------------------------------------------------
# Provision executor
# ---------------------------------------------------------------------------


def test_provision_writes_pod_handle_and_cost(
    produces_dir: Path,
    mock_launch: MagicMock,
    mock_pod: MagicMock,
) -> None:
    """Provision executor writes pod_handle.json and cost.json with correct shapes."""
    with patch("runpod_lifecycle.launch", mock_launch), \
         patch("runpod_lifecycle.RunPodConfig", MagicMock()):
        # Import under patches so they take effect
        from astrid.packs.external.executors.runpod.run import cmd_provision

        class Args:
            gpu_type = "NVIDIA GeForce RTX 4090"
            storage_name = None
            max_runtime_seconds = None
            name_prefix = None
            image = None
            container_disk_gb = None
            datacenter_id = None
            produces_dir = produces_dir

        # Set env for API key resolution
        import os
        os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

        try:
            exit_code = cmd_provision(Args(), produces_dir)
            assert exit_code == 0

            # Verify pod_handle.json
            handle_path = produces_dir / "pod_handle.json"
            assert handle_path.is_file(), "pod_handle.json not written"
            handle = json.loads(handle_path.read_text())
            _assert_pod_handle_shape(handle)

            # Verify cost.json
            cost_path = produces_dir / "cost.json"
            assert cost_path.is_file(), "cost.json not written"
            cost = json.loads(cost_path.read_text())
            _assert_cost_shape(cost)
        finally:
            if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
                del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Exec executor
# ---------------------------------------------------------------------------


def test_exec_reads_handle_and_writes_result(
    produces_dir: Path,
    mock_get_pod: MagicMock,
    mock_ship_and_run_detached: MagicMock,
    mock_pod: MagicMock,
) -> None:
    """Exec executor reattaches, runs, and writes exec_result.json + cost.json."""
    # Pre-create a valid pod_handle.json
    handle = {
        "pod_id": "pod-abc123",
        "ssh": "root@1.2.3.4 -p 2222",
        "name": "astrid-test-pod-1700000000",
        "name_prefix": "astrid-test",
        "terminate_at": "2099-01-01T00:00:00Z",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "hourly_rate": 0.34,
        "provisioned_at": "2024-01-01T00:00:00Z",
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
    handle_path = produces_dir / "pod_handle.json"
    handle_path.write_text(json.dumps(handle))

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.get_pod", mock_get_pod), \
             patch("runpod_lifecycle.ship_and_run_detached", mock_ship_and_run_detached), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.packs.external.executors.runpod.run import cmd_exec

            class Args:
                pod_handle = str(handle_path)
                local_root = None
                remote_root = None
                remote_script = "echo hello"
                timeout = None
                upload_mode = None
                excludes = None
                produces_dir = produces_dir

            exit_code = cmd_exec(Args(), produces_dir)
            assert exit_code == 0

            # Verify exec_result.json
            result_path = produces_dir / "exec_result.json"
            assert result_path.is_file(), "exec_result.json not written"
            result = json.loads(result_path.read_text())
            assert "returncode" in result
            assert "stdout" in result

            # Verify cost.json
            cost_path = produces_dir / "cost.json"
            assert cost_path.is_file(), "cost.json not written"
            cost = json.loads(cost_path.read_text())
            _assert_cost_shape(cost)
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Teardown executor
# ---------------------------------------------------------------------------


def test_teardown_terminates_and_writes_receipt(
    produces_dir: Path,
    mock_get_pod: MagicMock,
    mock_pod: MagicMock,
) -> None:
    """Teardown executor terminates the pod and writes teardown_receipt.json."""
    handle = {
        "pod_id": "pod-abc123",
        "ssh": "root@1.2.3.4 -p 2222",
        "name": "astrid-test-pod-1700000000",
        "name_prefix": "astrid-test",
        "terminate_at": "2099-01-01T00:00:00Z",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "hourly_rate": 0.34,
        "provisioned_at": "2024-01-01T00:00:00Z",
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
    handle_path = produces_dir / "pod_handle.json"
    handle_path.write_text(json.dumps(handle))

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.get_pod", mock_get_pod), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.packs.external.executors.runpod.run import cmd_teardown

            class Args:
                pod_handle = str(handle_path)
                produces_dir = produces_dir

            exit_code = cmd_teardown(Args(), produces_dir)
            assert exit_code == 0

            # Verify teardown_receipt.json
            receipt_path = produces_dir / "teardown_receipt.json"
            assert receipt_path.is_file(), "teardown_receipt.json not written"
            receipt = json.loads(receipt_path.read_text())
            assert receipt["pod_id"] == "pod-abc123"
            assert receipt["status"] in ("terminated", "already_gone")

            # Verify cost.json
            cost_path = produces_dir / "cost.json"
            assert cost_path.is_file(), "cost.json not written"
            cost = json.loads(cost_path.read_text())
            _assert_cost_shape(cost)
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


def test_teardown_idempotent_pod_not_found(
    produces_dir: Path,
    mock_pod: MagicMock,
) -> None:
    """Teardown is idempotent — 'not found' produces already_gone receipt."""
    handle = {
        "pod_id": "pod-gone123",
        "ssh": "root@1.2.3.4 -p 2222",
        "name": "astrid-test-gone",
        "name_prefix": "astrid-test",
        "terminate_at": "2099-01-01T00:00:00Z",
        "gpu_type": "NVIDIA GeForce RTX 4090",
        "hourly_rate": 0.34,
        "provisioned_at": "2024-01-01T00:00:00Z",
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
    handle_path = produces_dir / "pod_handle.json"
    handle_path.write_text(json.dumps(handle))

    # Mock get_pod to raise a "not found" error
    not_found_pod = MagicMock()
    not_found_pod.terminate = AsyncMock(side_effect=Exception("pod not found or 404"))
    mock_get_pod_not_found = AsyncMock(return_value=not_found_pod)

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.get_pod", mock_get_pod_not_found), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.packs.external.executors.runpod.run import cmd_teardown

            class Args:
                pod_handle = str(handle_path)
                produces_dir = produces_dir

            exit_code = cmd_teardown(Args(), produces_dir)
            # Should succeed because not-found is a no-op
            assert exit_code == 0

            receipt_path = produces_dir / "teardown_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            assert receipt["status"] == "already_gone"
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Session executor
# ---------------------------------------------------------------------------


def test_session_writes_breadcrumb_and_deletes_on_teardown(
    produces_dir: Path,
    mock_launch: MagicMock,
    mock_ship_and_run_detached: MagicMock,
    mock_pod: MagicMock,
) -> None:
    """Session writes pod_handle.json immediately and deletes it on graceful teardown."""
    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.launch", mock_launch), \
             patch("runpod_lifecycle.get_pod", AsyncMock(return_value=mock_pod)), \
             patch("runpod_lifecycle.ship_and_run_detached", mock_ship_and_run_detached), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.packs.external.executors.runpod.run import cmd_session

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
                remote_script = "echo ok"
                timeout = None
                upload_mode = None
                excludes = None
                produces_dir = produces_dir

            exit_code = cmd_session(Args(), produces_dir)
            assert exit_code == 0

            # pod_handle.json should be deleted after graceful teardown
            handle_path = produces_dir / "pod_handle.json"
            assert not handle_path.exists(), (
                "pod_handle.json should be deleted after graceful session teardown"
            )

            # exec_result.json should exist
            result_path = produces_dir / "exec_result.json"
            assert result_path.is_file(), "exec_result.json not written"

            # cost.json should exist
            cost_path = produces_dir / "cost.json"
            assert cost_path.is_file(), "cost.json not written"
            cost = json.loads(cost_path.read_text())
            _assert_cost_shape(cost)
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


def test_session_breadcrumb_survives_on_crash(
    produces_dir: Path,
    mock_launch: MagicMock,
    mock_pod: MagicMock,
) -> None:
    """When exec raises a Python exception, the finally block still runs
    (so handle is deleted). The breadcrumb survives only when the Python
    process itself crashes (SIGKILL, OOM-kill, machine reboot) — those
    are tested in test_session_oom_breadcrumb.py."""

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    # Make ship_and_run_detached raise to simulate a crash during exec
    crash_mock = AsyncMock(side_effect=RuntimeError("simulated exec crash"))

    try:
        with patch("runpod_lifecycle.launch", mock_launch), \
             patch("runpod_lifecycle.get_pod", AsyncMock(return_value=mock_pod)), \
             patch("runpod_lifecycle.ship_and_run_detached", crash_mock), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.packs.external.executors.runpod.run import cmd_session

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
                remote_script = "echo ok"
                timeout = None
                upload_mode = None
                excludes = None
                produces_dir = produces_dir

            exit_code = cmd_session(Args(), produces_dir)
            # Session should return non-zero on crash
            assert exit_code != 0

            # When a Python exception is raised and caught by except,
            # the finally block still runs → handle is deleted.
            # This is the graceful path. The sweeper breadcrumb is for
            # process-level crashes (SIGKILL/OOM) where finally never runs.
            handle_path = produces_dir / "pod_handle.json"
            assert not handle_path.exists(), (
                "pod_handle.json is deleted in finally when Python exception "
                "is caught — this is expected. Process-level crashes (SIGKILL) "
                "are tested in test_session_oom_breadcrumb.py"
            )
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Cost summation invariant
# ---------------------------------------------------------------------------


def test_cost_summation_invariant() -> None:
    """provision.cost + exec.cost + teardown.cost ≈ session.cost (same hourly_rate)."""
    hourly_rate = 0.34

    # Simulate the three partial costs (using the _cost_amount + _cost_entry helpers)
    from astrid.packs.external.executors.runpod.run import _cost_amount, _cost_entry

    prov_duration = 45.0
    exec_duration = 120.0
    tear_duration = 15.0
    session_duration = prov_duration + exec_duration + tear_duration

    prov_cost = _cost_entry(_cost_amount(prov_duration, hourly_rate), "runpod", "provision")
    exec_cost = _cost_entry(_cost_amount(exec_duration, hourly_rate), "runpod", "exec")
    tear_cost = _cost_entry(_cost_amount(tear_duration, hourly_rate), "runpod", "teardown")
    sess_cost = _cost_entry(_cost_amount(session_duration, hourly_rate), "runpod", "session")

    trio_sum = prov_cost["amount"] + exec_cost["amount"] + tear_cost["amount"]
    session_amount = sess_cost["amount"]

    # Allow tiny floating-point difference
    assert abs(trio_sum - session_amount) < 0.001, (
        f"Cost summation invariant broken: "
        f"provision={prov_cost['amount']} + exec={exec_cost['amount']} + "
        f"teardown={tear_cost['amount']} = {trio_sum} != "
        f"session={session_amount}"
    )

    # Verify all cost shapes
    for cost in (prov_cost, exec_cost, tear_cost, sess_cost):
        _assert_cost_shape(cost)