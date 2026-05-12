"""RunPod storage helpers — ensure-storage and volume listing."""

from __future__ import annotations

import asyncio
import os
from typing import Any


async def ensure_storage(
    name: str,
    *,
    size_gb: int = 50,
    datacenter_id: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Find or create a RunPod network volume by *name*.

    Calls ``Pod.get_storage(name)``; if missing, calls
    ``Pod.create_storage(name, size_gb, datacenter_id)``.

    Idempotent — no cost event emitted.

    Parameters
    ----------
    name:
        Volume name to find or create.
    size_gb:
        Size in GB for the new volume (only used on create).  Default 50.
    datacenter_id:
        RunPod datacenter ID (e.g. ``"US-GA-1"``).  Required when creating
        a new volume; raises :class:`ValueError` if omitted and the volume
        does not exist.
    api_key:
        RunPod API key.  When ``None`` (default), reads ``RUNPOD_API_KEY``
        from the environment.  The parameter exists for test injection but
        is not forwarded to ``Pod.*`` methods (which read the env var
        directly).
    """
    from runpod_lifecycle import Pod

    existing = await Pod.get_storage(name)
    if existing is not None:
        return existing

    if datacenter_id is None:
        raise ValueError(
            f"datacenter_id is required to create a new network volume "
            f"(volume {name!r} not found)"
        )

    return await Pod.create_storage(name, size_gb, datacenter_id)


async def list_volumes(api_key: str | None = None) -> list[dict[str, Any]]:
    """Return all RunPod network volumes for the account.

    Thin passthrough to :func:`api.get_network_volumes`.

    Parameters
    ----------
    api_key:
        RunPod API key.  When ``None`` (default), reads ``RUNPOD_API_KEY``
        from the environment.
    """
    from runpod_lifecycle import api

    resolved_key = api_key or os.environ.get("RUNPOD_API_KEY", "")
    if not resolved_key:
        raise RuntimeError("RUNPOD_API_KEY is not set")

    return await asyncio.to_thread(api.get_network_volumes, resolved_key)