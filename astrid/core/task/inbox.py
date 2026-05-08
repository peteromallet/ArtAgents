"""Inbox surface for external completion signals (Phase 8).

External processes drop JSON files into ``runs/<run-id>/inbox/`` to signal
that an attested step has completed. ``astrid next`` consumes these
entries before computing the next step.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from astrid.core.project.paths import project_dir
from astrid.core.task.active_run import clear_active_run
from astrid.core.task.events import (
    append_event,
    make_cursor_rewind_event,
    make_run_aborted_event,
)
from astrid.core.task.gate import (
    AttestedArgs,
    TaskRunGateError,
    gate_command,
    peek_current_step,
    validate_attested_identity,
)
from astrid.core.task.plan import (
    STEP_PATH_SEP,
    AttestedStep,
    CodeStep,
    load_plan,
)
from astrid.core.task.events import read_events

INBOX_DIR_NAME = "inbox"
CONSUMED_DIR_NAME = ".consumed"
REJECTED_DIR_NAME = ".rejected"

_VALID_DECISIONS = ("approve", "retry", "abort")

_LOGGER = logging.getLogger("astrid.core.task.inbox")


class InboxValidationError(Exception):
    """Raised internally when an inbox file fails schema validation."""


@dataclass(frozen=True)
class InboxEntry:
    path: Path
    step_id: str
    decision: str
    evidence: tuple[str, ...]
    submitted_at: str
    submitted_by: str
    item_id: str | None
    raw: dict


def inbox_dir(run_dir: Path) -> Path:
    return run_dir / INBOX_DIR_NAME


def _parse_entry(file_path: Path, raw: dict) -> InboxEntry:
    if not isinstance(raw, dict):
        raise InboxValidationError("payload must be a JSON object")

    step_id = raw.get("step_id")
    if not isinstance(step_id, str) or not step_id:
        raise InboxValidationError("missing or empty step_id")

    decision = raw.get("decision")
    if decision not in _VALID_DECISIONS:
        raise InboxValidationError(
            f"decision must be one of {_VALID_DECISIONS}, got {decision!r}"
        )

    submitted_at = raw.get("submitted_at")
    if not isinstance(submitted_at, str):
        raise InboxValidationError("submitted_at must be a string")

    submitted_by = raw.get("submitted_by")
    if not isinstance(submitted_by, str):
        raise InboxValidationError("submitted_by must be a string")

    evidence_raw = raw.get("evidence")
    if evidence_raw is None:
        evidence: tuple[str, ...] = ()
    else:
        if not isinstance(evidence_raw, dict):
            raise InboxValidationError("evidence must be a JSON object")
        evidence_values: list[str] = []
        for key, value in evidence_raw.items():
            if not isinstance(value, str) or not value:
                raise InboxValidationError(
                    f"evidence value for {key!r} must be a non-empty string"
                )
            evidence_values.append(value)
        evidence = tuple(evidence_values)

    item_id_raw = raw.get("item_id")
    if item_id_raw is None:
        item_id: str | None = None
    elif isinstance(item_id_raw, str) and item_id_raw:
        item_id = item_id_raw
    else:
        raise InboxValidationError("item_id must be a non-empty string when present")

    return InboxEntry(
        path=file_path,
        step_id=step_id,
        decision=decision,
        evidence=evidence,
        submitted_at=submitted_at,
        submitted_by=submitted_by,
        item_id=item_id,
        raw=raw,
    )


def scan_inbox(run_dir: Path) -> list[InboxEntry]:
    """Read and validate inbox entries.

    Returns ``[]`` when the inbox directory is absent (opt-in behavior).
    Subdirectories and dot-prefixed names are skipped. Malformed files are
    logged via ``_LOGGER.warning`` and skipped — never raised.
    Entries are sorted by ``(submitted_at, filename)`` for deterministic ordering.
    """
    directory = inbox_dir(run_dir)
    if not directory.is_dir():
        return []

    entries: list[InboxEntry] = []
    for child in directory.iterdir():
        if child.name.startswith("."):
            continue
        if not child.is_file():
            continue
        try:
            data = child.read_bytes()
            payload = json.loads(data)
            entry = _parse_entry(child, payload)
        except (OSError, json.JSONDecodeError, InboxValidationError) as exc:
            _LOGGER.warning("inbox: skipping %s: %s", child.name, exc)
            continue
        entries.append(entry)

    entries.sort(key=lambda e: (e.submitted_at, e.path.name))
    return entries


def pending_count(run_dir: Path) -> int:
    return len(scan_inbox(run_dir))


def _move_to(file_path: Path, dest_dir: Path) -> None:
    """Move ``file_path`` to ``dest_dir/<sha256>``.

    The sha256-of-file-bytes filename (FLAG-P8-002) avoids any post-hoc
    events.jsonl re-read to derive the just-appended event hash. On OSError
    we unlink the original so a stuck file does not loop the inbox.
    """
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        target = dest_dir / digest
        os.replace(file_path, target)
    except OSError as exc:
        _LOGGER.warning(
            "inbox: failed to move %s to %s (%s); unlinking", file_path.name, dest_dir.name, exc
        )
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass


def consume_inbox_entry(
    run_dir: Path,
    entry: InboxEntry,
    *,
    slug: str,
    projects_root: Path | None,
) -> bool:
    """Validate ``entry`` against the current cursor and consume it.

    Returns ``True`` when an event was appended (file moved to .consumed/),
    ``False`` for stale or rejected entries. Stale-cursor entries are left
    in inbox/ so a future call can revisit them once the cursor advances;
    rejected entries (actor-step approve, gate failure, mismatched evidence)
    move to .rejected/<sha256> so they do not loop.
    """
    project_root = project_dir(slug, root=projects_root)
    plan_path = project_root / "plan.json"
    run_id = run_dir.name
    events_path = run_dir / "events.jsonl"
    consumed_dir = run_dir / INBOX_DIR_NAME / CONSUMED_DIR_NAME
    rejected_dir = run_dir / INBOX_DIR_NAME / REJECTED_DIR_NAME

    plan = load_plan(plan_path)
    events = read_events(events_path)
    peek = peek_current_step(
        plan, events, slug, project_root=project_root, run_id=run_id
    )

    if entry.decision == "abort":
        append_event(
            events_path,
            make_run_aborted_event(run_id, reason=f"inbox abort by {entry.submitted_by}"),
        )
        clear_active_run(slug, root=projects_root)
        _move_to(entry.path, consumed_dir)
        return True

    # approve / retry both require the cursor to be on a matching attested step.
    if peek.exhausted or peek.step is None or isinstance(peek.step, CodeStep):
        _LOGGER.warning(
            "inbox: skipping %s: cursor not on an attested step", entry.path.name
        )
        return False
    if not isinstance(peek.step, AttestedStep):
        _LOGGER.warning(
            "inbox: skipping %s: cursor not on an attested step", entry.path.name
        )
        return False

    cursor_step_id = peek.path_tuple[-1] if peek.path_tuple else ""
    if entry.step_id != cursor_step_id:
        _LOGGER.warning(
            "inbox: skipping %s: step_id %r does not match current cursor %r",
            entry.path.name,
            entry.step_id,
            cursor_step_id,
        )
        return False

    if entry.decision == "approve":
        if peek.step.ack.kind == "actor":
            _LOGGER.warning(
                "inbox: skipping %s: ack.kind=actor not supported by inbox protocol "
                "(use astrid ack ...)",
                entry.path.name,
            )
            _move_to(entry.path, rejected_dir)
            return False
        # ack.kind == 'agent'
        parts: list[str] = [peek.step.command, "--agent", entry.submitted_by]
        for ev in entry.evidence:
            parts.extend(["--evidence", ev])
        if entry.item_id is not None:
            parts.extend(["--item", entry.item_id])
        synthesized = " ".join(shlex.quote(p) for p in parts)
        try:
            gate_command(slug, synthesized, [], root=projects_root)
        except TaskRunGateError as exc:
            _LOGGER.warning("inbox: rejecting %s: %s", entry.path.name, exc.reason)
            _move_to(entry.path, rejected_dir)
            return False
        _move_to(entry.path, consumed_dir)
        return True

    # retry
    latest = _latest_event_for_path(events, peek.path_tuple)
    if not isinstance(latest, dict) or latest.get("kind") != "produces_check_failed":
        _LOGGER.warning(
            "inbox: skipping %s: retry requires latest event to be produces_check_failed",
            entry.path.name,
        )
        return False
    if peek.step.ack.kind != "agent":
        _LOGGER.warning(
            "inbox: skipping %s: retry only supported for ack.kind=agent",
            entry.path.name,
        )
        _move_to(entry.path, rejected_dir)
        return False
    args = AttestedArgs(
        agent=entry.submitted_by,
        actor=None,
        evidence=entry.evidence,
        item=entry.item_id,
    )
    try:
        validate_attested_identity(
            slug=slug, step=peek.step, args=args, run_started_actor=None
        )
    except TaskRunGateError as exc:
        _LOGGER.warning("inbox: rejecting %s: %s", entry.path.name, exc.reason)
        _move_to(entry.path, rejected_dir)
        return False
    append_event(
        events_path,
        make_cursor_rewind_event(peek.path_tuple, reason="inbox retry"),
    )
    _move_to(entry.path, consumed_dir)
    return True


def _latest_event_for_path(events, path_tuple: tuple[str, ...]):
    path_str = STEP_PATH_SEP.join(path_tuple)
    path_list = list(path_tuple)
    for ev in reversed(events):
        if not isinstance(ev, dict):
            continue
        if ev.get("plan_step_id") == path_str:
            return ev
        if ev.get("plan_step_path") == path_list:
            return ev
    return None
