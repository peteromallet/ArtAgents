"""``astrid ack`` lifecycle verb (Phase 5 T9).

Split out of ``lifecycle.py`` to keep both modules under the ~600-line size
budget. Implements the ack decision matrix per the Phase 5 brief:

- ``approve`` (attested cursor): synthesizes the gate-bound incoming command
  as ``step.command + identity/evidence/item tokens`` (NOT ``ack --step ...``)
  so ``match_attested_command`` can strip identity tokens and compare the
  literal remainder to ``step.command`` for authored commands like
  ``review.sh``. Calls ``gate_command`` + ``record_dispatch_complete``.
  (FLAG-P5-001.)
- ``approve`` on a CodeStep cursor: rejected. Code steps advance via the
  printed argv, not via ``ack``.
- ``retry``: only valid on an AttestedStep cursor whose latest event for
  the path is ``produces_check_failed``. Calls ``validate_attested_identity``
  BEFORE mutating events, then appends ``cursor_rewind`` so the next
  ``next`` re-dispatches. (FLAG-P5-002.)
- ``iterate``: only valid on an AttestedStep cursor whose host has
  ``repeat.until.condition == 'user_approves'``. Requires non-empty
  ``--feedback``. Calls ``validate_attested_identity`` BEFORE mutating
  events, then ``write_iteration_feedback`` (cumulative ledger) and
  appends ``iteration_failed`` so the next ``next`` enters iteration N+1.
  (FLAG-P5-002.)
- ``abort``: administrative — delegates to ``cmd_abort`` and skips identity
  validation entirely.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Optional, Sequence

from astrid.core.project.paths import project_dir, validate_project_slug
from astrid.core.task.active_run import read_active_run
from astrid.core.task.events import (
    append_event,
    make_cursor_rewind_event,
    make_iteration_failed_event,
    read_events,
)
from astrid.core.task.gate import (
    AttestedArgs,
    GateDecision,
    TaskRunGateError,
    gate_command,
    peek_current_step,
    record_dispatch_complete,
    validate_attested_identity,
    write_iteration_feedback,
)
from astrid.core.task.plan import (
    STEP_PATH_SEP,
    RepeatUntil,
    is_attested_kind,
    is_code_kind,
    is_group_step,
    load_plan,
)


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _system_exit_code(exc: SystemExit) -> int:
    return int(exc.code) if isinstance(exc.code, int) else 2


def _find_step_by_path(plan, path_tuple):
    """Walk a TaskPlan to find the step at ``path_tuple``."""
    if not path_tuple:
        return None
    steps = plan.steps
    for segment in path_tuple[:-1]:
        match = next((s for s in steps if s.id == segment), None)
        if match is None or not is_group_step(match):
            return None
        steps = match.children or ()
    return next((s for s in steps if s.id == path_tuple[-1]), None)


def _latest_event_for_path(events, path_tuple):
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


def _run_started_actor(events) -> Optional[str]:
    for ev in events:
        if isinstance(ev, dict) and ev.get("kind") == "run_started":
            actor = ev.get("actor")
            return actor if isinstance(actor, str) else None
    return None


def cmd_ack(
    argv: Sequence[str],
    *,
    projects_root: Optional[Path] = None,
) -> int:
    # --- Early abort decision: handle before argparse so identity flags are not required ---
    argv_list = list(argv)
    abort_idx = None
    for i, a in enumerate(argv_list):
        if a == "--decision" and i + 1 < len(argv_list) and argv_list[i + 1] == "abort":
            abort_idx = i
            break
    if abort_idx is not None:
        # Extract --project for cmd_abort.
        proj = None
        for i, a in enumerate(argv_list):
            if a == "--project" and i + 1 < len(argv_list):
                proj = argv_list[i + 1]
                break
        if proj is None:
            _print_err("ack: --project is required for abort")
            return 1
        from astrid.core.task.lifecycle import cmd_abort
        return cmd_abort(["--project", proj], projects_root=projects_root)

    parser = argparse.ArgumentParser(prog="astrid ack", add_help=True)
    parser.add_argument("step", help="STEP_PATH_SEP-joined plan step path (e.g. 'review' or 'outer/inner')")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument(
        "--decision",
        required=True,
        choices=["approve", "retry", "iterate", "abort"],
        help="ack decision",
    )
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="repeatable; evidence path or sentinel",
    )
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--agent", default=None, help="agent id (mutually exclusive with --actor)")
    identity.add_argument("--actor", default=None, help="actor name (mutually exclusive with --agent)")
    parser.add_argument("--feedback", default=None, help="iterate feedback (required for --decision=iterate)")
    parser.add_argument("--item", default=None, help="for_each item id")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return _system_exit_code(exc)

    # --- Function-boundary identity assertion (Sprint 3 T16) ---
    # argparse `required=True` catches the CLI case.  This assertion catches
    # Python callers that synthesize Namespace(agent=None, actor=None) directly.
    if args.agent is None and args.actor is None:
        _print_err(
            "ack: --agent <id> or --actor <name> is required "
            "(no anonymous acks — Sprint 3 T16)"
        )
        return 1

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        _print_err(f"ack: {exc}")
        return 1

    active_run = read_active_run(slug, root=projects_root)
    if active_run is None:
        _print_err(
            f"ack: no active run for project {slug!r}; "
            f"recovery: astrid start <orchestrator-id> --project {slug}"
        )
        return 1

    run_id = active_run["run_id"]
    proj_root = project_dir(slug, root=projects_root)
    plan_path = proj_root / "plan.json"
    events_path = proj_root / "runs" / run_id / "events.jsonl"

    # --- Read writer_epoch for stale-ack rejection (Sprint 3 T16) ---
    from astrid.core.task.events import LEASE_FILENAME
    import json as _json
    lease_path = proj_root / "runs" / run_id / LEASE_FILENAME
    writer_epoch: int | None = None
    try:
        if lease_path.exists():
            lease_payload = _json.loads(lease_path.read_text(encoding="utf-8"))
            writer_epoch = int(lease_payload.get("writer_epoch", 0))
    except Exception:
        pass  # defensive: epoch check is best-effort

    plan = load_plan(plan_path)
    events = read_events(events_path)
    peek = peek_current_step(
        plan, events, slug, project_root=proj_root, run_id=run_id
    )
    if peek.exhausted or peek.step is None:
        _print_err(
            f"ack: run is exhausted; recovery: astrid abort --project {slug}"
        )
        return 1

    expected_path = STEP_PATH_SEP.join(peek.path_tuple)
    if args.step != expected_path:
        _print_err(
            f"ack: step path {args.step!r} does not match cursor {expected_path!r}; "
            f"run `astrid next --project {slug}` to see the current step"
        )
        return 1

    try:
        if args.decision == "approve":
            return _ack_approve(args, slug, peek, projects_root, proj_root)
        if args.decision == "retry":
            return _ack_retry(
                args, slug, peek, plan, events, events_path, run_id, proj_root
            )
        if args.decision == "iterate":
            return _ack_iterate(
                args, slug, peek, plan, events, events_path, run_id, proj_root
            )
    except Exception as exc:
        from astrid.core.task.events import StaleEpochError, StaleTailError
        if isinstance(exc, (StaleEpochError, StaleTailError)):
            _print_err(f"ack: stale — {exc}; the run lease has changed under you. "
                        f"Re-run the ack to pick up the new writer_epoch.")
            return 1
        raise
    # argparse choices=... already constrains this; defensive only.
    _print_err(f"ack: unknown decision {args.decision!r}")
    return 1


def _ack_approve(args, slug, peek, projects_root, proj_root) -> int:
    if is_code_kind(peek.step):
        _print_err(
            "ack: approve is invalid for code steps. code steps advance via "
            f"subprocess; just run the printed command (astrid next --project {slug})."
        )
        return 1
    if not is_attested_kind(peek.step):
        _print_err("ack: cannot approve non-attested step")
        return 1

    # FLAG-P5-001: synthesize the incoming command as step.command +
    # identity/evidence/item tokens, NOT 'ack --step ...'. step.command may
    # already be a multi-token command (e.g., "echo review"); split it so
    # match_attested_command's canonical rejoin compares token-for-token
    # rather than treating the whole prefix as a single quoted argument.
    parts: list[str] = shlex.split(peek.step.command)
    if args.agent:
        parts += ["--agent", args.agent]
    if args.actor:
        parts += ["--actor", args.actor]
    for ev in args.evidence:
        parts += ["--evidence", ev]
    if args.item:
        parts += ["--item", args.item]
    incoming = " ".join(shlex.quote(p) for p in parts)

    try:
        decision = gate_command(slug, incoming, [], root=projects_root)
    except TaskRunGateError as exc:
        _print_err(f"ack: {exc.reason}; recovery: {exc.recovery}")
        return 1

    # Attested step is "complete" at attestation; the gate already wrote
    # step_attested + ran inline produces checks. record_dispatch_complete
    # is a no-op for attested steps but we call it for symmetry with code
    # dispatch and to keep the post-dispatch surface consistent.
    record_dispatch_complete(decision, 0)
    print(f"acknowledged {STEP_PATH_SEP.join(peek.path_tuple)}")
    return 0


def _ack_retry(args, slug, peek, plan, events, events_path, run_id, proj_root) -> int:
    if not is_attested_kind(peek.step):
        _print_err(
            "ack: retry is only valid on attested steps. Code steps "
            "redispatch implicitly when you re-run the printed argv."
        )
        return 1

    # FLAG-P5-002: validate identity BEFORE mutating events.
    attested_args = AttestedArgs(
        agent=args.agent,
        actor=args.actor,
        evidence=tuple(args.evidence),
        item=args.item,
    )
    try:
        validate_attested_identity(
            slug=slug,
            step=peek.step,
            args=attested_args,
            run_started_actor=_run_started_actor(events),
        )
    except TaskRunGateError as exc:
        _print_err(f"ack retry: {exc.reason}; recovery: {exc.recovery}")
        return 1

    latest = _latest_event_for_path(events, peek.path_tuple)
    if not isinstance(latest, dict) or latest.get("kind") != "produces_check_failed":
        _print_err(
            "ack retry: only valid after a verifier failure (the latest event "
            f"for {STEP_PATH_SEP.join(peek.path_tuple)} must be "
            "produces_check_failed)."
        )
        return 1

    append_event(
        events_path,
        make_cursor_rewind_event(peek.path_tuple, reason="ack retry"),
    )
    print(f"retry queued for {STEP_PATH_SEP.join(peek.path_tuple)}")
    return 0


def _ack_iterate(args, slug, peek, plan, events, events_path, run_id, proj_root) -> int:
    if not is_attested_kind(peek.step):
        _print_err("ack: iterate is only valid on attested steps")
        return 1
    if not args.feedback or not args.feedback.strip():
        _print_err("ack iterate: --feedback is required and must be non-empty")
        return 1

    # FLAG-P5-002: validate identity BEFORE mutating events.
    attested_args = AttestedArgs(
        agent=args.agent,
        actor=args.actor,
        evidence=tuple(args.evidence),
        item=args.item,
    )
    try:
        validate_attested_identity(
            slug=slug,
            step=peek.step,
            args=attested_args,
            run_started_actor=_run_started_actor(events),
        )
    except TaskRunGateError as exc:
        _print_err(f"ack iterate: {exc.reason}; recovery: {exc.recovery}")
        return 1

    # Find the host step in the plan (peek.step has repeat stripped because
    # it is the body of an iteration frame). peek.path_tuple == host path
    # because _make_iteration_frame uses path_prefix = parent_prefix.
    host = _find_step_by_path(plan, peek.path_tuple)
    if (
        host is None
        or not isinstance(getattr(host, "repeat", None), RepeatUntil)
        or host.repeat.condition != "user_approves"  # type: ignore[union-attr]
    ):
        condition = (
            host.repeat.condition  # type: ignore[union-attr]
            if host is not None and isinstance(getattr(host, "repeat", None), RepeatUntil)
            else "<no repeat>"
        )
        _print_err(
            "ack iterate: only valid for repeat.until.condition='user_approves' "
            f"(host condition={condition!r})"
        )
        return 1
    if peek.iteration is None:
        _print_err("ack iterate: cursor is not inside an iteration frame")
        return 1

    decision = GateDecision(
        active=True,
        run_id=run_id,
        slug=slug,
        project_root=proj_root,
        plan_step_path=peek.path_tuple,
        iteration=peek.iteration,
        events_path=events_path,
    )
    write_iteration_feedback(decision, args.feedback)
    append_event(
        events_path,
        make_iteration_failed_event(
            peek.path_tuple, peek.iteration, reason="iterate_feedback"
        ),
    )
    print(
        f"iteration {peek.iteration} marked failed; feedback recorded for "
        f"{STEP_PATH_SEP.join(peek.path_tuple)}"
    )
    return 0


__all__ = ["cmd_ack"]
