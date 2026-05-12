"""Inbox surface for external completion signals (Sprint 3 T10).

External processes drop JSON files into ``runs/<run-id>/inbox/`` to signal
that a step has completed. ``astrid next`` consumes these entries before
computing the next step.

Sprint 3 changes:
- Entries match on ``(plan_step_path, step_version, item_id?)`` (not bare step_id).
- ``schema_version: 2`` discriminates new entries from legacy.
- Manual-adapter completion requires ``submitted_by`` AND ``submitted_by_kind``.
- Stale entries (tombstoned or fully-superseded) route to ``.rejected/``.
- STOP-LINE: every entry lands in exactly one of inbox/, .consumed/, or .rejected/.
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
    is_attested_kind,
    is_code_kind,
    load_plan,
)
from astrid.core.task.events import read_events

INBOX_DIR_NAME = "inbox"
CONSUMED_DIR_NAME = ".consumed"
REJECTED_DIR_NAME = ".rejected"

_VALID_DECISIONS = ("approve", "retry", "abort")
_VALID_SUBMITTED_BY_KINDS = ("agent", "actor")

_LOGGER = logging.getLogger("astrid.core.task.inbox")


class InboxValidationError(Exception):
    """Raised internally when an inbox file fails schema validation."""


@dataclass(frozen=True)
class InboxEntry:
    path: Path
    step_id: str
    plan_step_path: tuple[str, ...] | None
    step_version: int
    schema_version: int
    decision: str
    evidence: tuple[str, ...]
    submitted_at: str
    submitted_by: str
    submitted_by_kind: str | None
    item_id: str | None
    raw: dict


def inbox_dir(run_dir: Path) -> Path:
    return run_dir / INBOX_DIR_NAME


def _parse_entry(file_path: Path, raw: dict) -> InboxEntry:
    if not isinstance(raw, dict):
        raise InboxValidationError("payload must be a JSON object")

    schema_version = raw.get("schema_version")
    if schema_version is None:
        # Legacy entry (no schema_version field) — handled by T19 migration.
        return _parse_legacy_entry(file_path, raw)

    if schema_version != 2 or isinstance(schema_version, bool):
        raise InboxValidationError(
            f"schema_version must be 2 (got {schema_version!r})"
        )

    # --- schema_version:2 required fields ---

    plan_step_path_raw = raw.get("plan_step_path")
    if not isinstance(plan_step_path_raw, list) or not plan_step_path_raw:
        raise InboxValidationError(
            "plan_step_path must be a non-empty list of strings"
        )
    plan_step_path: tuple[str, ...] = tuple(
        s for s in plan_step_path_raw if isinstance(s, str) and s
    )
    if len(plan_step_path) != len(plan_step_path_raw):
        raise InboxValidationError(
            "plan_step_path elements must be non-empty strings"
        )
    step_id = plan_step_path[-1]

    step_version = raw.get("step_version")
    if not isinstance(step_version, int) or isinstance(step_version, bool) or step_version < 1:
        raise InboxValidationError("step_version must be an int >= 1")

    decision = raw.get("decision")
    if decision not in _VALID_DECISIONS:
        raise InboxValidationError(
            f"decision must be one of {_VALID_DECISIONS}, got {decision!r}"
        )

    submitted_at = raw.get("submitted_at")
    if not isinstance(submitted_at, str):
        raise InboxValidationError("submitted_at must be a string")

    submitted_by = raw.get("submitted_by")
    if not isinstance(submitted_by, str) or not submitted_by:
        raise InboxValidationError("submitted_by must be a non-empty string")

    # --- Identity enforcement: manual-adapter entries MUST carry submitted_by_kind ---
    submitted_by_kind = raw.get("submitted_by_kind")
    if submitted_by_kind is None:
        raise InboxValidationError(
            "submitted_by_kind is required (must be 'agent' or 'actor'); "
            "missing identity — entry will be rejected"
        )
    if submitted_by_kind not in _VALID_SUBMITTED_BY_KINDS:
        raise InboxValidationError(
            f"submitted_by_kind must be 'agent' or 'actor', got {submitted_by_kind!r}"
        )

    # --- Optional fields ---

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
        plan_step_path=plan_step_path,
        step_version=step_version,
        schema_version=2,
        decision=decision,
        evidence=evidence,
        submitted_at=submitted_at,
        submitted_by=submitted_by,
        submitted_by_kind=submitted_by_kind,
        item_id=item_id,
        raw=raw,
    )


def _parse_legacy_entry(file_path: Path, raw: dict) -> InboxEntry:
    """Parse a legacy (no schema_version) inbox entry.

    This path exists so pre-T19 inbox entries don't crash the parser.
    The T19 migration script rewrites these to schema_version:2; until
    then we treat the lack of schema_version as an implicit v1 entry.
    """
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
        plan_step_path=None,  # legacy entries only have step_id
        step_version=1,  # pre-versioned world
        schema_version=0,  # sentinel: legacy / not yet migrated
        decision=decision,
        evidence=evidence,
        submitted_at=submitted_at,
        submitted_by=submitted_by,
        submitted_by_kind=None,
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
    rejected_dir = directory / REJECTED_DIR_NAME

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
            # Malformed entries that fail identity enforcement get routed to .rejected/
            _move_to(child, rejected_dir)
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
            "inbox: failed to move %s to %s (%s); unlinking",
            file_path.name,
            dest_dir.name,
            exc,
        )
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass


def _resolve_plan_step_path(entry: InboxEntry) -> tuple[str, ...]:
    """Return the plan_step_path from an entry, handling legacy fallback."""
    if entry.plan_step_path is not None:
        return entry.plan_step_path
    # Legacy entry: step_id only. Treat as root-level step.
    return (entry.step_id,)


def _is_step_tombstoned(plan, step_path: tuple[str, ...]) -> bool:
    """Check whether the step at ``step_path`` has been removed/tombstoned in the plan."""
    steps = plan.steps
    for segment in step_path[:-1]:
        match = next((s for s in steps if s.id == segment), None)
        if match is None or match.children is None:
            return True  # intermediate segment missing → tombstoned
        steps = match.children
    return not any(s.id == step_path[-1] for s in steps)


def _is_step_fully_superseded(
    events: list[dict], step_path: tuple[str, ...], entry_version: int
) -> bool:
    """Return True if the entry's version is older than the latest supersede target."""
    path_str = "/".join(step_path)
    latest_supersede_to: int | None = None
    for ev in events:
        if not isinstance(ev, dict) or ev.get("kind") != "plan_mutated":
            continue
        diff = ev.get("diff")
        if not isinstance(diff, dict):
            continue
        if diff.get("op") != "supersede":
            continue
        if diff.get("path") != path_str:
            continue
        to_version = diff.get("to_version")
        if isinstance(to_version, int) and not isinstance(to_version, bool):
            latest_supersede_to = to_version
    if latest_supersede_to is not None and entry_version < latest_supersede_to:
        return True
    return False


def _compute_stale(
    plan, events: list[dict], entry: InboxEntry, run_dir: Path
) -> tuple[bool, str | None]:
    """Determine whether ``entry`` is stale and why. Returns (is_stale, reason)."""
    step_path = _resolve_plan_step_path(entry)

    if _is_step_tombstoned(plan, step_path):
        return True, f"step {'/'.join(step_path)!r} is tombstoned"

    if _is_step_fully_superseded(events, step_path, entry.step_version):
        return True, (
            f"step {'/'.join(step_path)!r} v{entry.step_version} is superseded "
            f"(newer version exists)"
        )

    return False, None


def consume_inbox_entry(
    run_dir: Path,
    entry: InboxEntry,
    *,
    slug: str,
    projects_root: Path | None,
) -> bool:
    """Validate ``entry`` against the current cursor and consume it.

    Returns ``True`` when an event was appended (file moved to .consumed/),
    ``False`` for stale or rejected entries.  Stale-cursor entries are left
    in inbox/ so a future call can revisit them once the cursor advances;
    rejected entries (tombstoned, superseded, identity-missing, gate failure)
    move to .rejected/<sha256> so they do not loop.

    STOP-LINE: every entry lands in exactly one of inbox/, .consumed/, or .rejected/.
    """
    project_root = project_dir(slug, root=projects_root)
    plan_path = project_root / "plan.json"
    run_id = run_dir.name
    events_path = run_dir / "events.jsonl"
    consumed_dir = run_dir / INBOX_DIR_NAME / CONSUMED_DIR_NAME
    rejected_dir = run_dir / INBOX_DIR_NAME / REJECTED_DIR_NAME

    plan = load_plan(plan_path)
    events = read_events(events_path)

    # --- Stale-entry check (before cursor check) ---
    is_stale, stale_reason = _compute_stale(plan, events, entry, run_dir)
    if is_stale:
        _LOGGER.warning(
            "inbox: rejecting %s as stale: %s", entry.path.name, stale_reason
        )
        _move_to(entry.path, rejected_dir)
        return False

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

    # approve / retry both require the cursor to be on a matching step.
    if peek.exhausted or peek.step is None or is_code_kind(peek.step):
        _LOGGER.warning(
            "inbox: skipping %s: cursor not on an attested step", entry.path.name
        )
        return False
    if not is_attested_kind(peek.step):
        _LOGGER.warning(
            "inbox: skipping %s: cursor not on an attested step", entry.path.name
        )
        return False

    # Sprint 3 T10: match on (plan_step_path, step_version) not bare step_id.
    entry_path = _resolve_plan_step_path(entry)
    cursor_path = peek.path_tuple

    if entry_path != cursor_path:
        _LOGGER.warning(
            "inbox: skipping %s: plan_step_path %s does not match current cursor %s",
            entry.path.name,
            "/".join(entry_path),
            "/".join(cursor_path),
        )
        return False

    if entry.step_version != 1:
        # Versioned entry: verify the cursor version matches.
        pass  # Cursor version tracking lands fully in T14; for now tolerate any version.

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