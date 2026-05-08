"""Phase 8 — stale and malformed inbox files don't corrupt run state."""

from __future__ import annotations

import io
import json
import logging
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lifecycle_fixtures import setup_run  # noqa: E402

from astrid.core.task.events import read_events
from astrid.core.task.lifecycle import cmd_next


_BODY_AGENT = '''from astrid.orchestrate import orchestrator, attested
@orchestrator("demo.review_agent")
def main(): return [attested("review", command="review.sh", instructions="please review", ack="agent")]
'''

_BODY_ACTOR = '''from astrid.orchestrate import orchestrator, attested
@orchestrator("demo.review_actor")
def main(): return [attested("review", command="ok.sh", instructions="confirm", ack="actor")]
'''


def _drop(run_dir: Path, name: str, payload) -> Path:
    inbox = run_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    file_path = inbox / name
    if isinstance(payload, str):
        file_path.write_text(payload, encoding="utf-8")
    else:
        file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def _run_next(projects: Path) -> int:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cmd_next(["--project", "p"], projects_root=projects)


def test_step_id_mismatch_leaves_file_in_place(tmp_path: Path) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "review_agent", _BODY_AGENT, "demo.review_agent",
        run_id="r-stale-a",
    )
    run_dir = projects / "p" / "runs" / "r-stale-a"
    events_path = run_dir / "events.jsonl"
    initial_count = len(read_events(events_path))

    inbox_file = _drop(
        run_dir,
        "wrong.json",
        {
            "step_id": "not-the-current-step",
            "decision": "approve",
            "evidence": {"note": "x"},
            "submitted_at": "2026-05-01T10:00:00Z",
            "submitted_by": "external-script",
        },
    )

    os.environ["ARTAGENTS_ACTOR"] = "bob"
    rc = _run_next(projects)
    assert rc == 0

    # No new event — cursor unchanged.
    assert len(read_events(events_path)) == initial_count
    # File still in inbox/ (not in .consumed or .rejected).
    assert inbox_file.exists()


def test_approve_on_actor_step_quarantined_to_rejected(
    tmp_path: Path, caplog
) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "review_actor", _BODY_ACTOR, "demo.review_actor",
        run_id="r-stale-b",
    )
    run_dir = projects / "p" / "runs" / "r-stale-b"
    events_path = run_dir / "events.jsonl"
    initial_count = len(read_events(events_path))

    inbox_file = _drop(
        run_dir,
        "actor-approve.json",
        {
            "step_id": "review",
            "decision": "approve",
            "evidence": {"note": "x"},
            "submitted_at": "2026-05-01T10:00:00Z",
            "submitted_by": "external-script",
        },
    )

    os.environ["ARTAGENTS_ACTOR"] = "bob"
    with caplog.at_level(logging.WARNING, logger="astrid.core.task.inbox"):
        rc = _run_next(projects)
    assert rc == 0

    # No event written.
    assert len(read_events(events_path)) == initial_count
    # File quarantined to inbox/.rejected/.
    rejected_dir = run_dir / "inbox" / ".rejected"
    assert rejected_dir.is_dir()
    assert len(list(rejected_dir.iterdir())) == 1
    assert not inbox_file.exists()
    assert any(
        "ack.kind=actor" in record.message for record in caplog.records
    )


def test_malformed_json_skipped_and_logged(tmp_path: Path, caplog) -> None:
    packs, projects = setup_run(
        tmp_path, "demo", "review_agent", _BODY_AGENT, "demo.review_agent",
        run_id="r-stale-c",
    )
    run_dir = projects / "p" / "runs" / "r-stale-c"
    events_path = run_dir / "events.jsonl"
    initial_count = len(read_events(events_path))

    inbox_file = _drop(run_dir, "broken.json", "not valid json {")

    os.environ["ARTAGENTS_ACTOR"] = "bob"
    with caplog.at_level(logging.WARNING, logger="astrid.core.task.inbox"):
        rc = _run_next(projects)
    assert rc == 0

    assert len(read_events(events_path)) == initial_count
    assert inbox_file.exists()
    assert any("broken.json" in record.message for record in caplog.records)
