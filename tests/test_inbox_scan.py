"""Phase 8 — scan_inbox: malformed files are logged and skipped, not raised."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from astrid.core.task.inbox import inbox_dir, scan_inbox


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_scan_returns_three_valid_entries_and_logs_one_malformed(
    tmp_path: Path, caplog
) -> None:
    run_dir = tmp_path / "run-x"
    run_dir.mkdir()
    inbox = inbox_dir(run_dir)
    inbox.mkdir()

    _write(
        inbox / "a.json",
        {
            "step_id": "review",
            "decision": "approve",
            "evidence": {"note": "alpha"},
            "submitted_at": "2026-05-01T10:00:00Z",
            "submitted_by": "alice",
        },
    )
    _write(
        inbox / "b.json",
        {
            "step_id": "review",
            "decision": "retry",
            "submitted_at": "2026-05-01T11:00:00Z",
            "submitted_by": "bob",
        },
    )
    _write(
        inbox / "c.json",
        {
            "step_id": "review",
            "decision": "abort",
            "submitted_at": "2026-05-01T12:00:00Z",
            "submitted_by": "carol",
        },
    )
    (inbox / "broken.json").write_text("not json at all", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="astrid.core.task.inbox"):
        entries = scan_inbox(run_dir)

    assert len(entries) == 3
    submitters = sorted(e.submitted_by for e in entries)
    assert submitters == ["alice", "bob", "carol"]
    assert any("broken.json" in record.message for record in caplog.records)


def test_scan_returns_empty_when_inbox_dir_absent(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-y"
    run_dir.mkdir()
    # No inbox/ directory — opt-in surface.
    assert scan_inbox(run_dir) == []
