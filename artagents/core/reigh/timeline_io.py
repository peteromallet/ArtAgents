"""Versioned timeline read/write loop against reigh-data-fetch + RPC.

The ``save_timeline`` helper here is the canonical write path used by both the
worker (T9) and the DataProvider write API (T6). It implements the
optimistic-concurrency contract documented in
``docs/integration_contracts.md``: load ``(timeline, config_version)`` via the
``reigh-data-fetch`` Edge Function, apply a caller-supplied mutator, then call
the ``update_timeline_config_versioned(p_timeline_id, p_expected_version,
p_config)`` RPC. On version-mismatch, re-load and re-apply the mutator up to
``retries`` times before raising :class:`TimelineVersionConflictError`.

Auth scopes (FLAG-012 / SD-009): the worker write path uses ``service_role``
auth so it can write any timeline once it has verified ownership separately;
non-worker callers (CLI, ``open_in_reigh``) should pass a ``user_jwt`` or
``pat`` Auth tuple via ``write_auth=``. The helper does not bake in either
choice; callers select the auth scheme.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from artagents import timeline as timeline_mod

from .errors import TimelineNotFoundError, TimelineVersionConflictError
from .supabase_client import Auth, SupabaseHTTPError, post_json, rpc

logger = logging.getLogger(__name__)


TimelineConfig = dict[str, Any]
Mutator = Callable[[TimelineConfig, int], TimelineConfig]


@dataclass(frozen=True)
class SaveResult:
    timeline: TimelineConfig
    new_version: int
    attempts: int


def _round_trip(payload: Mapping[str, Any]) -> TimelineConfig:
    """Round-trip a fetched timeline through artagents.timeline so byte-equivalent
    allowlist parity stays intact."""

    return timeline_mod.Timeline.from_json_data(dict(payload)).to_config()  # type: ignore[return-value]


def _to_storage_payload(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate + emit the JSON shape the DB column expects."""

    return timeline_mod.Timeline.from_config(dict(config)).to_json_data()


def _looks_like_version_conflict(exc: SupabaseHTTPError) -> bool:
    if exc.status == 409:
        return True
    body = (exc.body or "").lower()
    return any(
        marker in body
        for marker in (
            "version_conflict",
            "version conflict",
            "expected_version",
            "stale config_version",
        )
    )


def fetch_timeline(
    *,
    fetch_url: str,
    project_id: str,
    timeline_id: str,
    auth: Auth,
    timeout: float = 60.0,
) -> tuple[TimelineConfig, int]:
    """Call ``reigh-data-fetch`` and return ``(timeline_config, config_version)``."""

    payload = post_json(
        fetch_url,
        {"project_id": project_id, "timeline_id": timeline_id},
        auth=auth,
        timeout=timeout,
    )
    if not isinstance(payload, dict):
        raise TimelineNotFoundError(
            f"reigh-data-fetch returned non-object payload for timeline {timeline_id}"
        )
    timelines = payload.get("timelines")
    if not isinstance(timelines, list) or not timelines:
        raise TimelineNotFoundError(
            f"reigh-data-fetch returned no timelines for {timeline_id}"
        )
    match: Mapping[str, Any] | None = None
    for entry in timelines:
        if isinstance(entry, dict) and entry.get("id") == timeline_id:
            match = entry
            break
    if match is None:
        first = timelines[0]
        if isinstance(first, dict):
            match = first
    if match is None:
        raise TimelineNotFoundError(
            f"reigh-data-fetch did not return timeline {timeline_id}"
        )

    raw_config = match.get("config")
    if not isinstance(raw_config, dict):
        raise TimelineNotFoundError(
            f"reigh-data-fetch row for {timeline_id} has no config object"
        )
    raw_version = match.get("config_version")
    if not isinstance(raw_version, int):
        raise TimelineNotFoundError(
            "reigh-data-fetch payload is missing config_version. "
            "Phase 2 requires the reigh-app PR adding config_version to TIMELINES_SELECT."
        )
    return _round_trip(raw_config), raw_version


def save_timeline(
    *,
    timeline_id: str,
    project_id: str,
    mutator: Mutator,
    fetch_url: str,
    supabase_url: str,
    read_auth: Auth,
    write_auth: Auth,
    expected_version: int | None = None,
    retries: int = 3,
    force: bool = False,
    timeout: float = 60.0,
) -> SaveResult:
    """Apply ``mutator`` to the timeline and persist via the versioned RPC.

    The mutator receives ``(current_config, current_version)`` and must return
    a new ``TimelineConfig`` dict. On version-mismatch responses (HTTP 409 or
    body markers like ``version_conflict`` / ``expected_version``), the helper
    re-fetches and re-applies the mutator. ``retries`` is the total attempt
    count (including the first one).

    ``expected_version=None`` is rejected unless ``force=True`` — this protects
    the worker path which must always carry ``task.params.expected_version``.
    ``force=True`` is logged at WARNING because it bypasses the optimistic
    concurrency contract.
    """

    if retries < 1:
        raise ValueError("retries must be >= 1")
    if expected_version is None and not force:
        raise ValueError(
            "save_timeline requires expected_version unless force=True"
        )
    if force:
        logger.warning(
            "save_timeline called with force=True for timeline_id=%s expected_version=%s",
            timeline_id,
            expected_version,
        )

    last_version: int | None = expected_version
    last_exc: SupabaseHTTPError | None = None
    for attempt in range(1, retries + 1):
        config, current_version = fetch_timeline(
            fetch_url=fetch_url,
            project_id=project_id,
            timeline_id=timeline_id,
            auth=read_auth,
            timeout=timeout,
        )
        last_version = current_version

        if (
            not force
            and expected_version is not None
            and current_version != expected_version
            and attempt == 1
        ):
            logger.info(
                "save_timeline expected_version=%s but DB has %s; retrying with fresh load",
                expected_version,
                current_version,
            )

        new_config = mutator(config, current_version)
        if not isinstance(new_config, dict):
            raise TypeError("save_timeline mutator must return a TimelineConfig dict")

        storage_payload = _to_storage_payload(new_config)
        try:
            response = rpc(
                "update_timeline_config_versioned",
                {
                    "p_timeline_id": timeline_id,
                    "p_expected_version": current_version,
                    "p_config": storage_payload,
                },
                supabase_url=supabase_url,
                auth=write_auth,
                timeout=timeout,
            )
        except SupabaseHTTPError as exc:
            last_exc = exc
            if _looks_like_version_conflict(exc) and not force:
                logger.info(
                    "save_timeline version conflict on attempt %d/%d for %s (expected=%s)",
                    attempt,
                    retries,
                    timeline_id,
                    current_version,
                )
                continue
            raise

        new_version = _extract_new_version(response, fallback=current_version + 1)
        return SaveResult(
            timeline=new_config,
            new_version=new_version,
            attempts=attempt,
        )

    raise TimelineVersionConflictError(
        f"save_timeline exhausted {retries} attempts for timeline_id={timeline_id}",
        attempts=retries,
        last_expected_version=last_version,
    ) from last_exc


def _extract_new_version(response: Any, *, fallback: int) -> int:
    if isinstance(response, int):
        return response
    if isinstance(response, dict):
        for key in ("config_version", "new_version", "version"):
            value = response.get(key)
            if isinstance(value, int):
                return value
    if isinstance(response, list) and response:
        first = response[0]
        if isinstance(first, dict):
            for key in ("config_version", "new_version", "version"):
                value = first.get(key)
                if isinstance(value, int):
                    return value
    return fallback
