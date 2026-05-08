"""Unit tests for astrid.core.reigh.task_client."""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from typing import Any
from unittest.mock import patch

from astrid.core.reigh import task_client
from astrid.core.reigh.task_client import (
    ALLOWED_STATUSES,
    ClaimResult,
    claim_next_task,
    update_task_status,
)


class _FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _capture_urlopen(responses: list[_FakeResponse]):
    captured: list[dict[str, Any]] = []

    def fake(request, *, timeout):
        captured.append(
            {
                "url": request.full_url,
                "headers": dict(request.headers),
                "method": request.get_method(),
                "data": json.loads(request.data.decode("utf-8")) if request.data else None,
            }
        )
        return responses.pop(0)

    return fake, captured


class ClaimNextTaskTest(unittest.TestCase):
    def test_post_body_locked_to_banodoco_pool(self) -> None:
        envelope = {
            "task_id": "task-1",
            "run_id": "run-1",
            "project_id": "proj-1",
            "task_type": "banodoco_timeline_generate",
            "user_jwt": "jwt-token",
            "params": {"timeline_id": "tl-1", "expected_version": 3},
        }
        fake, captured = _capture_urlopen([_FakeResponse(200, json.dumps(envelope))])
        with patch("urllib.request.urlopen", fake):
            result = claim_next_task(
                worker_id="worker-1",
                service_role_key="srv-key",
                claim_url="https://example.supabase.co/functions/v1/claim-next-task",
            )
        self.assertIsInstance(result, ClaimResult)
        self.assertEqual(result.task_id, "task-1")
        self.assertEqual(result.task_type, "banodoco_timeline_generate")
        self.assertEqual(result.user_jwt, "jwt-token")

        # Body shape is locked to the SD-034 contract.
        self.assertEqual(len(captured), 1)
        body = captured[0]["data"]
        self.assertEqual(body["worker_id"], "worker-1")
        self.assertEqual(body["run_type"], "banodoco-worker")
        self.assertEqual(body["worker_pool"], "banodoco")
        self.assertEqual(body["task_types"], ["banodoco_timeline_generate"])

    def test_204_returns_none(self) -> None:
        fake, _ = _capture_urlopen([_FakeResponse(204, "")])
        with patch("urllib.request.urlopen", fake):
            result = claim_next_task(
                worker_id="worker-1",
                service_role_key="srv-key",
                claim_url="https://example.supabase.co/functions/v1/claim-next-task",
            )
        self.assertIsNone(result)


class UpdateTaskStatusTest(unittest.TestCase):
    def test_title_case_required_lowercase_rejected(self) -> None:
        for bad in ("complete", "FAILED", "queued", "in progress"):
            with self.assertRaises(ValueError, msg=f"status={bad!r} should be rejected"):
                update_task_status(
                    "task-1",
                    status=bad,
                    service_role_key="srv-key",
                    update_url="https://x",
                )

    def test_result_data_persisted_in_request_body(self) -> None:
        fake, captured = _capture_urlopen([_FakeResponse(200, "{}")])
        with patch("urllib.request.urlopen", fake):
            update_task_status(
                "task-1",
                status="Complete",
                result_data={"config_version": 7, "correlation_id": "corr", "timeline_id": "tl-1"},
                service_role_key="srv-key",
                update_url="https://example.supabase.co/functions/v1/update-task-status",
            )
        body = captured[0]["data"]
        self.assertEqual(body["task_id"], "task-1")
        self.assertEqual(body["status"], "Complete")
        self.assertEqual(body["result_data"], {"config_version": 7, "correlation_id": "corr", "timeline_id": "tl-1"})

    def test_allowed_statuses_locked(self) -> None:
        self.assertEqual(
            ALLOWED_STATUSES,
            frozenset({"Queued", "In Progress", "Complete", "Failed", "Cancelled"}),
        )


class NoCompleteTaskNoTaskStatusTest(unittest.TestCase):
    def test_module_exposes_no_complete_task_helpers(self) -> None:
        for forbidden in ("complete_task", "complete-task", "task_status_get", "get_task_status"):
            self.assertFalse(
                hasattr(task_client, forbidden), f"task_client should not export {forbidden}"
            )

    def test_repo_grep_finds_no_complete_task_or_task_status_callers(self) -> None:
        # AA must NEVER call /functions/v1/complete-task or /functions/v1/task-status.
        # Existing references in astrid/ are docstrings explicitly stating the
        # negative invariant — assert each occurrence sits within ~120 chars of a
        # 'NEVER' marker, which catches accidental new callers introduced in
        # actual code paths.
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "astrid"
        forbidden_substrings = ("/functions/v1/complete-task", "/functions/v1/task-status")
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden_substrings:
                idx = 0
                while True:
                    found = text.find(needle, idx)
                    if found == -1:
                        break
                    window = text[max(0, found - 120) : found + 120]
                    if "NEVER" not in window:
                        offenders.append(f"{path}:{found}: {needle}")
                    idx = found + 1
        self.assertEqual(offenders, [], "AA must not call complete-task or task-status")


if __name__ == "__main__":
    unittest.main()
