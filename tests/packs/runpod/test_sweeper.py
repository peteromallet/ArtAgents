"""Test the RunPod sweeper with mocked lifecycle."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from astrid.core.runpod.sweeper import (
    POD_HANDLE_FILENAME,
    _derive_run_dir,
    collect_handles,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handle(pod_id: str = "pod-test123", **overrides) -> dict:
    """Build a minimal valid pod_handle dict."""
    base = {
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
    base.update(overrides)
    return base


def _write_handle_tree(base_dir: Path, project: str, run_id: str, step_id: str, handle: dict) -> Path:
    """Create the directory structure and write a pod_handle.json."""
    produces_dir = base_dir / project / "runs" / run_id / "steps" / step_id / "v1" / "produces"
    produces_dir.mkdir(parents=True)
    handle_path = produces_dir / POD_HANDLE_FILENAME
    handle_path.write_text(json.dumps(handle))
    return handle_path


def _write_lease(base_dir: Path, project: str, run_id: str, lease: dict) -> None:
    """Write a lease.json into a run directory."""
    run_dir = base_dir / project / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "lease.json").write_text(json.dumps(lease))


def _write_events(base_dir: Path, project: str, run_id: str, events: list[dict]) -> None:
    """Write events.jsonl into a run directory."""
    from astrid.core.task.events import EVENTS_FILENAME, ZERO_HASH, _event_hash

    run_dir = base_dir / project / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    prev_hash = ZERO_HASH
    lines = []
    for evt in events:
        stored = dict(evt)
        stored.pop("hash", None)
        stored["hash"] = _event_hash(prev_hash, stored)
        lines.append(json.dumps(stored, sort_keys=True, separators=(",", ":")))
        prev_hash = stored["hash"]

    (run_dir / EVENTS_FILENAME).write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# collect_handles
# ---------------------------------------------------------------------------


def test_collect_handles_empty_dir() -> None:
    """collect_handles returns empty list when no handles exist."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        handles = collect_handles(base)
        assert handles == []


def test_collect_handles_finds_pod_handles() -> None:
    """collect_handles discovers pod_handle.json files in the canonical path."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        handle = _make_handle(pod_id="pod-xyz")
        _write_handle_tree(base, "myproject", "run-001", "step-a", handle)

        results = collect_handles(base)
        assert len(results) == 1
        path, data = results[0]
        assert data["pod_id"] == "pod-xyz"
        assert path.name == POD_HANDLE_FILENAME


def test_collect_handles_skips_invalid_json() -> None:
    """collect_handles skips files that aren't valid JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        produces_dir = base / "proj" / "runs" / "r1" / "steps" / "s1" / "v1" / "produces"
        produces_dir.mkdir(parents=True)
        (produces_dir / POD_HANDLE_FILENAME).write_text("not json {{{")

        results = collect_handles(base)
        assert len(results) == 0  # invalid JSON is skipped


def test_collect_handles_skips_handles_without_pod_id() -> None:
    """collect_handles skips dicts that don't have a pod_id key."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        produces_dir = base / "proj" / "runs" / "r1" / "steps" / "s1" / "v1" / "produces"
        produces_dir.mkdir(parents=True)
        (produces_dir / POD_HANDLE_FILENAME).write_text(json.dumps({"not_a_handle": True}))

        results = collect_handles(base)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# _derive_run_dir
# ---------------------------------------------------------------------------


def test_derive_run_dir_from_handle_path() -> None:
    """_derive_run_dir extracts the owning run directory."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        handle = _make_handle()
        handle_path = _write_handle_tree(base, "proj", "run-abc", "step-x", handle)

        run_dir = _derive_run_dir(handle_path, base)
        assert run_dir is not None
        assert run_dir.name == "run-abc"


def test_derive_run_dir_returns_none_for_outside_path() -> None:
    """_derive_run_dir returns None when the handle is outside the projects root."""
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        base = Path(tmp1)
        other = Path(tmp2)
        handle_path = other / "orphan.json"
        handle_path.write_text(json.dumps(_make_handle()))

        run_dir = _derive_run_dir(handle_path, base)
        assert run_dir is None


# ---------------------------------------------------------------------------
# Sweeper default-mode: skip cases
# ---------------------------------------------------------------------------


@pytest.fixture
def sweeper_projects_root() -> Path:
    """Create a temporary projects root with test data."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def test_sweeper_skip_terminate_at_not_passed(sweeper_projects_root: Path) -> None:
    """Default mode skips pods whose terminate_at is in the future."""
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    handle = _make_handle(pod_id="pod-future", terminate_at=future)
    _write_handle_tree(sweeper_projects_root, "proj", "run-1", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-1", {"writer_epoch": 0, "attached_session_id": None})

    from astrid.core.runpod.sweeper import sweep as run_sweep

    summary = run_sweep(sweeper_projects_root, mode="default", dry_run=True)
    assert summary["terminated"] == 0
    assert summary["skipped"] >= 1
    # The skip reason should mention time
    reasons = [d["reason"] for d in summary["details"]]
    assert any("not yet passed" in r for r in reasons)


def test_sweeper_skip_live_session_acked(sweeper_projects_root: Path) -> None:
    """Default mode skips pods whose owning run has a live session."""
    handle = _make_handle(pod_id="pod-live")
    _write_handle_tree(sweeper_projects_root, "proj", "run-live", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-live", {
        "writer_epoch": 5,
        "attached_session_id": "sess-live-123",
    })

    from astrid.core.runpod.sweeper import sweep as run_sweep

    summary = run_sweep(sweeper_projects_root, mode="default", dry_run=True)
    assert summary["terminated"] == 0
    reasons = [d["reason"] for d in summary["details"]]
    assert any("live session" in r for r in reasons)


def test_sweeper_skip_pod_not_idle(sweeper_projects_root: Path) -> None:
    """Default mode skips pods that are not idle."""
    handle = _make_handle(pod_id="pod-busy")
    _write_handle_tree(sweeper_projects_root, "proj", "run-busy", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-busy", {
        "writer_epoch": 0,
        "attached_session_id": None,
    })

    # Mock Pod.is_idle to return False
    mock_pod = MagicMock()
    mock_pod.is_idle = AsyncMock(return_value=False)

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.discovery.get_pod", AsyncMock(return_value=mock_pod)), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.core.runpod.sweeper import sweep as run_sweep

            summary = run_sweep(sweeper_projects_root, mode="default", dry_run=True)
            reasons = [d["reason"] for d in summary["details"]]
            assert any("not idle" in r for r in reasons)
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Sweeper default-mode: terminate
# ---------------------------------------------------------------------------


def test_sweeper_default_terminate_idle_pod(sweeper_projects_root: Path) -> None:
    """Default mode terminates idle pods with no live session and past terminate_at."""
    handle = _make_handle(pod_id="pod-idle")
    _write_handle_tree(sweeper_projects_root, "proj", "run-idle", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-idle", {
        "writer_epoch": 0,
        "attached_session_id": None,
    })

    # Pre-seed events.jsonl so append_event_locked has a chain to CAS against
    _write_events(sweeper_projects_root, "proj", "run-idle", [
        {"kind": "run_started", "ts": "2024-01-01T00:00:00Z"},
    ])

    mock_pod = MagicMock()
    mock_pod.is_idle = AsyncMock(return_value=True)

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.discovery.get_pod", AsyncMock(return_value=mock_pod)), \
             patch("runpod_lifecycle.discovery.terminate", AsyncMock()), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.core.runpod.sweeper import sweep as run_sweep

            # Dry run: just assert it would terminate
            summary = run_sweep(sweeper_projects_root, mode="default", dry_run=True)
            assert summary["terminated"] == 1
            # Verify details
            terminated = [d for d in summary["details"] if d["action"] == "would_terminate"]
            assert len(terminated) == 1
            assert terminated[0]["pod_id"] == "pod-idle"
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Sweeper --hard mode
# ---------------------------------------------------------------------------


def test_sweeper_hard_overrides_live_session_check(sweeper_projects_root: Path) -> None:
    """--hard mode bypasses the live-session check."""
    handle = _make_handle(pod_id="pod-hard-live")
    _write_handle_tree(sweeper_projects_root, "proj", "run-hard-live", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-hard-live", {
        "writer_epoch": 5,
        "attached_session_id": "sess-live-active",
    })

    # Pre-seed events.jsonl
    _write_events(sweeper_projects_root, "proj", "run-hard-live", [
        {"kind": "run_started", "ts": "2024-01-01T00:00:00Z"},
    ])

    mock_pod = MagicMock()
    mock_pod.is_idle = AsyncMock(return_value=False)  # Even if not idle, --hard bypasses

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.discovery.get_pod", AsyncMock(return_value=mock_pod)), \
             patch("runpod_lifecycle.discovery.terminate", AsyncMock()), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.core.runpod.sweeper import sweep as run_sweep

            summary = run_sweep(sweeper_projects_root, mode="hard", dry_run=True)
            # --hard should permit termination despite live session and busy pod
            assert summary["terminated"] == 1
            terminated = [d for d in summary["details"] if d["action"] == "would_terminate"]
            assert len(terminated) == 1
            assert terminated[0]["pod_id"] == "pod-hard-live"
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


def test_sweeper_hard_requires_terminate_at_passed(sweeper_projects_root: Path) -> None:
    """--hard mode still requires terminate_at passed."""
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    handle = _make_handle(pod_id="pod-hard-future", terminate_at=future)
    _write_handle_tree(sweeper_projects_root, "proj", "run-hard-future", "step-1", handle)

    from astrid.core.runpod.sweeper import sweep as run_sweep

    summary = run_sweep(sweeper_projects_root, mode="hard", dry_run=True)
    assert summary["terminated"] == 0
    assert summary["skipped"] >= 1


# ---------------------------------------------------------------------------
# pod_terminated_by_sweep event emission
# ---------------------------------------------------------------------------


def test_sweeper_emits_pod_terminated_event(sweeper_projects_root: Path) -> None:
    """Sweeper appends pod_terminated_by_sweep events to events.jsonl."""
    handle = _make_handle(pod_id="pod-event-test")
    _write_handle_tree(sweeper_projects_root, "proj", "run-event", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-event", {
        "writer_epoch": 0,
        "attached_session_id": None,
    })

    # Pre-seed events.jsonl
    _write_events(sweeper_projects_root, "proj", "run-event", [
        {"kind": "run_started", "ts": "2024-01-01T00:00:00Z"},
    ])

    mock_pod = MagicMock()
    mock_pod.is_idle = AsyncMock(return_value=True)

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.discovery.get_pod", AsyncMock(return_value=mock_pod)), \
             patch("runpod_lifecycle.discovery.terminate", AsyncMock()), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.core.runpod.sweeper import sweep as run_sweep
            from astrid.core.task.events import EVENTS_FILENAME

            # Real (non-dry-run) sweep
            summary = run_sweep(sweeper_projects_root, mode="default", dry_run=False)
            assert summary["terminated"] == 1

            # Verify events.jsonl now has the pod_terminated_by_sweep event
            events_path = sweeper_projects_root / "proj" / "runs" / "run-event" / EVENTS_FILENAME
            assert events_path.is_file()
            lines = events_path.read_text().strip().split("\n")
            # Should have the original run_started + the sweeper event
            assert len(lines) >= 2
            sweeper_events = [json.loads(line) for line in lines if "sweep" in line]
            assert len(sweeper_events) >= 1
            sweeper_event = sweeper_events[0]
            assert sweeper_event["kind"] == "pod_terminated_by_sweep"
            assert sweeper_event["pod_id"] == "pod-event-test"
            assert sweeper_event["mode"] == "default"
            assert "hash" in sweeper_event  # Hash-chained
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


def test_sweeper_hard_emits_event_with_epoch_none(sweeper_projects_root: Path) -> None:
    """--hard mode emits pod_terminated_by_sweep with expected_writer_epoch=None."""
    handle = _make_handle(pod_id="pod-hard-event")
    _write_handle_tree(sweeper_projects_root, "proj", "run-hard-event", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-hard-event", {
        "writer_epoch": 99,  # Active high epoch — --hard should bypass
        "attached_session_id": "sess-active-hard",
    })

    # Pre-seed events.jsonl
    _write_events(sweeper_projects_root, "proj", "run-hard-event", [
        {"kind": "run_started", "ts": "2024-01-01T00:00:00Z"},
    ])

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.discovery.terminate", AsyncMock()), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.core.runpod.sweeper import sweep as run_sweep
            from astrid.core.task.events import EVENTS_FILENAME

            summary = run_sweep(sweeper_projects_root, mode="hard", dry_run=False)
            assert summary["terminated"] == 1

            events_path = sweeper_projects_root / "proj" / "runs" / "run-hard-event" / EVENTS_FILENAME
            lines = events_path.read_text().strip().split("\n")
            sweeper_events = [json.loads(line) for line in lines if "sweep" in line]
            assert len(sweeper_events) >= 1
            sweeper_event = sweeper_events[0]
            assert sweeper_event["kind"] == "pod_terminated_by_sweep"
            assert sweeper_event["mode"] == "hard"
            assert "hash" in sweeper_event
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Hash-chain integrity under --hard against active run
# ---------------------------------------------------------------------------


def test_sweeper_hard_hash_chain_integrity(sweeper_projects_root: Path) -> None:
    """--hard mode events maintain hash-chain integrity."""
    handle = _make_handle(pod_id="pod-chain-test")
    _write_handle_tree(sweeper_projects_root, "proj", "run-chain", "step-1", handle)
    _write_lease(sweeper_projects_root, "proj", "run-chain", {
        "writer_epoch": 42,
        "attached_session_id": "sess-chain-active",
    })

    # Pre-seed with chain-starting events
    _write_events(sweeper_projects_root, "proj", "run-chain", [
        {"kind": "run_started", "ts": "2024-01-01T00:00:00Z"},
        {"kind": "step_completed", "step": "intro", "ts": "2024-01-01T00:01:00Z"},
    ])

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.discovery.terminate", AsyncMock()), \
             patch("runpod_lifecycle.RunPodConfig", MagicMock()):
            from astrid.core.runpod.sweeper import sweep as run_sweep
            from astrid.core.task.events import EVENTS_FILENAME, verify_chain

            run_sweep(sweeper_projects_root, mode="hard", dry_run=False)

            # Verify the full chain is intact
            events_path = sweeper_projects_root / "proj" / "runs" / "run-chain" / EVENTS_FILENAME
            ok, bad_idx, err = verify_chain(events_path)
            assert ok, f"Chain broken at event {bad_idx}: {err}"
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]