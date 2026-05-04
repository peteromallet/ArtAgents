"""``artagents ack`` lifecycle verb (Phase 5 T9).

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

from artagents.core.project.paths import project_dir, validate_project_slug
from artagents.core.task.active_run import read_active_run
from artagents.core.task.events import (
    append_event,
    make_cursor_rewind_event,
    make_iteration_failed_event,
    read_events,
)
from artagents.core.task.gate import (
    AttestedArgs,
    GateDecision,
    TaskRunGateError,
    gate_command,
    peek_current_step,
    record_dispatch_complete,
    validate_attested_identity,
    write_iteration_feedback,
)
from artagents.core.task.plan import (
    STEP_PATH_SEP,
    AttestedStep,
    CodeStep,
    NestedStep,
    RepeatUntil,
    load_plan,
)


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _find_step_by_path(plan, path_tuple):
    """Walk a TaskPlan to find the step at ``path_tuple``."""
    if not path_tuple:
        return None
    steps = plan.steps
    for segment in path_tuple[:-1]:
        match = next((s for s in steps if s.id == segment), None)
        if match is None or not isinstance(match, NestedStep):
            return None
        steps = match.plan.steps
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
    parser = argparse.ArgumentParser(prog="artagents ack", add_help=True)
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
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--agent", default=None, help="agent id (mutually exclusive with --actor)")
    identity.add_argument("--actor", default=None, help="actor name (mutually exclusive with --agent)")
    parser.add_argument("--feedback", default=None, help="iterate feedback (required for --decision=iterate)")
    parser.add_argument("--item", default=None, help="for_each item id")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    try:
        slug = validate_project_slug(args.project)
    except Exception as exc:
        _print_err(f"ack: {exc}")
        return 1

    # abort decision is administrative: delegate to cmd_abort, no identity required.
    if args.decision == "abort":
        from artagents.core.task.lifecycle import cmd_abort
        return cmd_abort(["--project", slug], projects_root=projects_root)

    active_run = read_active_run(slug, root=projects_root)
    if active_run is None:
        _print_err(
            f"ack: no active run for project {slug!r}; "
            f"recovery: artagents start <orchestrator-id> --project {slug}"
        )
        return 1

    run_id = active_run["run_id"]
    proj_root = project_dir(slug, root=projects_root)
    plan_path = proj_root / "plan.json"
    events_path = proj_root / "runs" / run_id / "events.jsonl"

    plan = load_plan(plan_path)
    events = read_events(events_path)
    peek = peek_current_step(
        plan, events, slug, project_root=proj_root, run_id=run_id
    )
    if peek.exhausted or peek.step is None:
        _print_err(
            f"ack: run is exhausted; recovery: artagents abort --project {slug}"
        )
        return 1

    expected_path = STEP_PATH_SEP.join(peek.path_tuple)
    if args.step != expected_path:
        _print_err(
            f"ack: step path {args.step!r} does not match cursor {expected_path!r}; "
            f"run `artagents next --project {slug}` to see the current step"
        )
        return 1

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
    # argparse choices=... already constrains this; defensive only.
    _print_err(f"ack: unknown decision {args.decision!r}")
    return 1


def _ack_approve(args, slug, peek, projects_root, proj_root) -> int:
    if isinstance(peek.step, CodeStep):
        _print_err(
            "ack: approve is invalid for code steps. code steps advance via "
            f"subprocess; just run the printed command (artagents next --project {slug})."
        )
        return 1
    if not isinstance(peek.step, AttestedStep):
        _print_err(
            f"ack: cannot approve step kind {type(peek.step).__name__}"
        )
        return 1

    # FLAG-P5-001: synthesize the incoming command as step.command +
    # identity/evidence/item tokens, NOT 'ack --step ...'.
    parts: list[str] = [peek.step.command]
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
    if not isinstance(peek.step, AttestedStep):
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
    if not isinstance(peek.step, AttestedStep):
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
