"""Test ensure-storage with mocked runpod_lifecycle."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Find path (volume exists)
# ---------------------------------------------------------------------------


def test_ensure_storage_finds_existing() -> None:
    """ensure_storage returns immediately when volume exists."""
    existing_volume = {"id": "vol-abc", "name": "my-volume", "size": 50}

    with patch("runpod_lifecycle.Pod.get_storage", AsyncMock(return_value=existing_volume)):
        from astrid.core.runpod.storage import ensure_storage

        import asyncio

        result = asyncio.run(ensure_storage("my-volume", datacenter_id="US-GA-1"))
        assert result == existing_volume
        # Pod.create_storage should NOT have been called
        # (get_storage returned non-None, so we short-circuit)


# ---------------------------------------------------------------------------
# Create path (volume missing)
# ---------------------------------------------------------------------------


def test_ensure_storage_creates_when_missing() -> None:
    """ensure_storage calls create_storage when get_storage returns None."""
    created_volume = {"id": "vol-new", "name": "new-volume", "size": 100}

    with patch("runpod_lifecycle.Pod.get_storage", AsyncMock(return_value=None)), \
         patch("runpod_lifecycle.Pod.create_storage", AsyncMock(return_value=created_volume)):
        from astrid.core.runpod.storage import ensure_storage

        import asyncio

        result = asyncio.run(ensure_storage("new-volume", size_gb=100, datacenter_id="US-GA-1"))
        assert result == created_volume


def test_ensure_storage_raises_without_datacenter_when_missing() -> None:
    """ensure_storage raises ValueError without datacenter_id when volume missing."""
    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.Pod.get_storage", AsyncMock(return_value=None)):
            from astrid.core.runpod.storage import ensure_storage

            import asyncio

            with pytest.raises(ValueError, match="datacenter_id"):
                asyncio.run(ensure_storage("missing-vol"))
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_ensure_storage_idempotent() -> None:
    """Calling ensure_storage twice is idempotent."""
    existing = {"id": "vol-abc", "name": "idem-vol", "size": 50}

    call_count = 0

    async def get_storage(name: str):
        nonlocal call_count
        call_count += 1
        return existing

    async def create_storage(name: str, size_gb: int, datacenter_id: str):
        pytest.fail("create_storage should not be called when volume exists")

    with patch("runpod_lifecycle.Pod.get_storage", get_storage), \
         patch("runpod_lifecycle.Pod.create_storage", create_storage):
        from astrid.core.runpod.storage import ensure_storage

        import asyncio

        r1 = asyncio.run(ensure_storage("idem-vol", datacenter_id="US-GA-1"))
        r2 = asyncio.run(ensure_storage("idem-vol", datacenter_id="US-GA-1"))
        assert r1 == r2 == existing


# ---------------------------------------------------------------------------
# Provision/session executors do NOT auto-create storage
# ---------------------------------------------------------------------------

# Note: The provision and session executors in run.py do NOT call
# ensure_storage — they just pass storage_name through to launch().
# If that fails, the error propagates naturally. This test confirms
# the executors don't silently create volumes as a side-effect.


def test_provision_does_not_auto_create_storage() -> None:
    """provision executor does NOT invoke ensure_storage or create_storage."""
    # Read the run.py source and verify no auto-create paths
    run_py = Path(__file__).parent.parent.parent.parent / "astrid" / "packs" / "external" / "runpod" / "run.py"
    source = run_py.read_text()
    # The cmd_provision function should NOT reference ensure_storage
    # or Pod.create_storage
    assert "ensure_storage" not in source, (
        "provision executor must NOT auto-create storage volumes"
    )
    assert "create_storage" not in source, (
        "provision executor must NOT call create_storage"
    )


# ---------------------------------------------------------------------------
# list_volumes
# ---------------------------------------------------------------------------


def test_list_volumes_passthrough() -> None:
    """list_volumes passes through to api.get_network_volumes."""
    mock_volumes = [{"id": "v1", "name": "vol-a"}, {"id": "v2", "name": "vol-b"}]

    import os
    os.environ["RUNPOD_API_KEY"] = "test-key-rpa_0000000000000000000000000000000000000000000000"

    try:
        with patch("runpod_lifecycle.api.get_network_volumes", return_value=mock_volumes):
            from astrid.core.runpod.storage import list_volumes

            import asyncio

            result = asyncio.run(list_volumes())
            assert result == mock_volumes
    finally:
        if os.environ.get("RUNPOD_API_KEY") == "test-key-rpa_0000000000000000000000000000000000000000000000":
            del os.environ["RUNPOD_API_KEY"]