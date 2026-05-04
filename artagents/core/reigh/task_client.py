"""Worker-side task queue client for the AA banodoco worker pool.

Mirrors ``banodoco-worker/worker.py:88-130``: claims tasks via
``/functions/v1/claim-next-task`` and reports status via
``/functions/v1/update-task-status``.

ArtAgents NEVER calls ``/functions/v1/complete-task`` and NEVER calls
``/functions/v1/task-status``. The task-status GET endpoint (commit ee2e6f10c)
is reigh-app's poller path; AA only writes via ``update-task-status``'s
``result_data`` field, which the GET endpoint then surfaces back to the UI.

Status values are Title Case ONLY: ``Queued``, ``In Progress``, ``Complete``,
``Failed``, ``Cancelled``. Lowercase values will be rejected by
``update-task-status`` (see contract resolution #4 in
``docs/integration_contracts.md``).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from . import env as reigh_env

logger = logging.getLogger(__name__)


RUN_TYPE = "banodoco-worker"
WORKER_POOL = "banodoco"
SUPPORTED_TASK_TYPES: tuple[str, ...] = ("banodoco_timeline_generate",)

ALLOWED_STATUSES: frozenset[str] = frozenset(
    {"Queued", "In Progress", "Complete", "Failed", "Cancelled"}
)


@dataclass(frozen=True)
class ClaimResult:
    """SD-034 task envelope returned by ``claim-next-task``."""

    task_id: str
    run_id: str
    project_id: str | None
    task_type: str
    user_jwt: str
    params: dict[str, Any]
    raw: dict[str, Any]


class TaskClientError(RuntimeError):
    """Raised on transport-level or non-2xx status from the orchestrator."""


def _post(
    url: str,
    body: Mapping[str, Any],
    *,
    service_role_key: str,
    timeout: float = 30.0,
) -> tuple[int, str]:
    headers = {
        "Authorization": f"Bearer {service_role_key}",
        "apikey": service_role_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(dict(body)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise TaskClientError(f"Orchestrator unreachable: {exc.reason}") from exc


def claim_next_task(
    *,
    worker_id: str,
    service_role_key: str,
    claim_url: str | None = None,
    env_file: Any = None,
    timeout: float = 30.0,
) -> Optional[ClaimResult]:
    """POST to ``/functions/v1/claim-next-task`` and return a claim envelope.

    Body shape (locked by spec):
      ``{worker_id, run_type:"banodoco-worker", worker_pool:"banodoco",
        task_types:["banodoco_timeline_generate"]}``

    Returns ``None`` when the orchestrator has no claimable task (HTTP 204 or
    non-200 fallthrough).
    """

    url = claim_url or reigh_env.resolve_claim_url(env_file=env_file)
    body = {
        "worker_id": worker_id,
        "run_type": RUN_TYPE,
        "worker_pool": WORKER_POOL,
        "task_types": list(SUPPORTED_TASK_TYPES),
    }
    status, payload = _post(url, body, service_role_key=service_role_key, timeout=timeout)
    if status == 204:
        return None
    if status != 200:
        logger.warning("[claim-next-task] non-200: %s %s", status, payload[:300])
        return None
    try:
        envelope = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("[claim-next-task] non-JSON response")
        return None
    if not isinstance(envelope, dict) or not envelope:
        return None

    task_id = envelope.get("task_id") or envelope.get("id")
    if not isinstance(task_id, str):
        logger.warning("[claim-next-task] envelope missing task_id")
        return None
    run_id = str(envelope.get("run_id", ""))
    project_id = envelope.get("project_id")
    task_type = str(envelope.get("task_type") or "banodoco_timeline_generate")
    user_jwt = str(envelope.get("user_jwt", ""))
    params = envelope.get("params") if isinstance(envelope.get("params"), dict) else {}
    return ClaimResult(
        task_id=task_id,
        run_id=run_id,
        project_id=project_id if isinstance(project_id, str) else None,
        task_type=task_type,
        user_jwt=user_jwt,
        params=dict(params),
        raw=dict(envelope),
    )


def update_task_status(
    task_id: str,
    *,
    status: str,
    service_role_key: str,
    result_data: Mapping[str, Any] | None = None,
    error: str | None = None,
    output_location: str | None = None,
    update_url: str | None = None,
    env_file: Any = None,
    timeout: float = 30.0,
) -> None:
    """POST to ``/functions/v1/update-task-status`` with Title Case status.

    ``result_data`` is the optional ``Record<string, unknown>`` persisted to
    ``tasks.result_data`` (commit ee2e6f10c). The new ``task-status`` GET
    endpoint surfaces this dict back to reigh-app's poller — AA's worker
    populates ``{config_version, correlation_id, timeline_id}`` here on
    completion and ``{correlation_id}`` on failure.
    """

    if status not in ALLOWED_STATUSES:
        raise ValueError(
            f"update_task_status: status must be one of {sorted(ALLOWED_STATUSES)!r} "
            f"(Title Case); got {status!r}"
        )
    if result_data is not None and not isinstance(result_data, Mapping):
        raise TypeError("result_data must be a mapping or None")

    url = update_url or reigh_env.resolve_task_status_update_url(env_file=env_file)
    body: dict[str, Any] = {"task_id": task_id, "status": status}
    if result_data is not None:
        body["result_data"] = dict(result_data)
    if error:
        body["error"] = error[:500]
    if output_location:
        body["output_location"] = output_location

    http_status, payload = _post(url, body, service_role_key=service_role_key, timeout=timeout)
    if http_status >= 400:
        raise TaskClientError(
            f"update-task-status failed: HTTP {http_status}: {payload[:300]}"
        )


__all__ = [
    "ALLOWED_STATUSES",
    "ClaimResult",
    "RUN_TYPE",
    "SUPPORTED_TASK_TYPES",
    "TaskClientError",
    "WORKER_POOL",
    "claim_next_task",
    "update_task_status",
]
