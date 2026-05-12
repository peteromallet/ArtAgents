"""``astrid skip`` lifecycle verb (Sprint 5b: optional steps).

Skips an ``optional=True`` step (leaf or group) at the current cursor
frontier without dispatching its command. Emits ``step_skipped`` (or
``item_skipped`` if ``--item`` is set) under the writer-epoch + tail-hash
CAS, mirroring the locking pattern used by ``cmd_ack``.

Refuses to skip arbitrary future steps — the target path must match the
top-of-cursor's pending step. For group steps with ``optional=True`` the
skip is operative on the un-traversed cursor (no ``nested_entered``); the
cursor advances past the whole subtree on the next replay.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from astrid.core.project.paths import project_dir, validate_project_slug
from astrid.core.task.active_run import read_active_run
from astrid.core.task.events import (
    EventLogError,
    LEASE_FILENAME,
    StaleEpochError,
    StaleTailError,
    append_event_locked,
    make_item_skipped_event,
    make_step_skipped_event,
    read_events,
)
from astrid.core.task.gate import derive_cursor
from astrid.core.task.plan import (
    STEP_PATH_SEP,
    RepeatForEach,
    load_plan,
)


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _read_lease_epoch_safe(lease_path: Path) -> int | None:
    """Best-effort read of the current writer_epoch from lease.json."""
    import json as _json
    try:
        if lease_path.exists():
            payload = _json.loads(lease_path.read_text(encoding="utf-8"))
            return int(payload.get("writer_epoch", 0))
    except Exception:
        return None
    return None


def _read_tail_hash_safe(events_path: Path) -> str:
    from astrid.core.task.events import _peek_tail_hash
    return _peek_tail_hash(events_path)


def _resolve_frontier_step(plan, events):
    """Return ``(step, path_tuple)`` for the top-of-cursor pending step.

    Uses ``derive_cursor`` (NOT ``peek_current_step``) so group steps are
    surfaced un-traversed — a group step with ``optional=True`` is
    skippable as a single unit before any ``nested_entered`` fires.
    Returns ``(None, ())`` when the cursor is exhausted.
    """
    cursor = derive_cursor(plan, events)
    if cursor.pinned_failure is not None or cursor.at_root_done:
        return None, ()
    top = cursor.frames[-1]
    if top.child_index >= len(top.plan.steps):
        return None, ()
    step = top.plan.steps[top.child_index]
    path_tuple = top.path_prefix + (step.id,)
    return step, path_tuple


def cmd_skip(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(prog="astrid skip", add_help=True)
    parser.add_argument(
        "step",
        help="STEP_PATH_SEP-joined plan step path of the optional step to skip",
    )
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument(
        "--reason",
        default=None,
        help="optional human-readable reason recorded on the skip event",
    )
    parser.add_argument(
        "--item",
        default=None,
        help="for_each item id (emits item_skipped instead of step_skipped)",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="agent id (mutually exclusive with --actor); defaults to 'cli' when neither given",
    )
    parser.add_argument(
        "--actor",
        default=None,
        help="actor name (mutually exclusive with --agent)",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    if args.agent is not None and args.actor is not None:
        _print_err("skip: --agent and --actor are mutually exclusive")
        return 1
    if args.agent is not None:
        actor_kind, actor_id = "agent", args.agent
    elif args.actor is not None:
        actor_kind, actor_id = "actor", args.actor
    else:
        actor_kind, actor_id = "agent", "cli"

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        _print_err(f"skip: {exc}")
        return 1

    active_run = read_active_run(slug, root=projects_root)
    if active_run is None:
        _print_err(
            f"skip: no active run for project {slug!r}; "
            f"recovery: astrid start <orchestrator-id> --project {slug}"
        )
        return 1

    run_id = active_run["run_id"]
    proj_root = project_dir(slug, root=projects_root)
    plan_path = proj_root / "plan.json"
    run_dir = proj_root / "runs" / run_id
    events_path = run_dir / "events.jsonl"

    plan = load_plan(plan_path)
    events = read_events(events_path)

    step, path_tuple = _resolve_frontier_step(plan, events)
    if step is None:
        _print_err(
            f"skip: run is exhausted; recovery: astrid abort --project {slug}"
        )
        return 1

    expected_path = STEP_PATH_SEP.join(path_tuple)
    if args.step != expected_path:
        _print_err(
            f"skip: step path {args.step!r} does not match cursor frontier "
            f"{expected_path!r}; only the current step may be skipped. "
            f"Run `astrid next --project {slug}` to see the active step."
        )
        return 1

    # --item: validate that the host has repeat.for_each and the item exists.
    if args.item is not None:
        repeat = getattr(step, "repeat", None)
        if not isinstance(repeat, RepeatForEach):
            _print_err(
                f"skip: --item requires a step with repeat.for_each, "
                f"step {expected_path!r} has none"
            )
            return 1
        # If the body step itself is required (optional=False on the host),
        # we still allow per-item skip — the spec calls out:
        #   "for_each parent with optional=False, item-level skip via --item:
        #    that item skipped, others run."
        # So we do NOT require step.optional=True for --item skip.
    else:
        if not step.optional:
            _print_err(
                f"skip: step {expected_path!r} is not optional "
                f"(set optional=True in plan.json to allow skipping)"
            )
            return 1

    # Build the event.
    if args.item is not None:
        event = make_item_skipped_event(
            path_tuple,
            args.item,
            actor_kind=actor_kind,
            actor_id=actor_id,
            reason=args.reason,
        )
    else:
        event = make_step_skipped_event(
            expected_path,
            actor_kind=actor_kind,
            actor_id=actor_id,
            reason=args.reason,
        )

    # Append under the writer epoch + tail-hash CAS, mirroring cmd_ack's
    # locking pattern (lifecycle_ack.py imports the underlying lock).
    lease_path = run_dir / LEASE_FILENAME
    expected_epoch = _read_lease_epoch_safe(lease_path)
    expected_prev_hash = _read_tail_hash_safe(events_path)
    try:
        append_event_locked(
            run_dir,
            event,
            expected_writer_epoch=expected_epoch,
            expected_prev_hash=expected_prev_hash,
        )
    except StaleEpochError as exc:
        _print_err(
            f"skip: stale writer_epoch ({exc}); re-run after the active "
            f"writer releases the lease"
        )
        return 1
    except StaleTailError as exc:
        _print_err(
            f"skip: stale events tail ({exc}); another writer appended "
            f"under us — re-run"
        )
        return 1
    except EventLogError as exc:
        _print_err(f"skip: {exc}")
        return 1

    if args.item is not None:
        print(f"skipped item {args.item} of {expected_path}")
    else:
        print(f"skipped {expected_path}")
    return 0


__all__ = ["cmd_skip"]
