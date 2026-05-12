"""``astrid claim`` / ``astrid unclaim`` lifecycle verbs (Sprint 3 T15).

Claim pins an agent or human identity to a step so the cursor knows who
is responsible.  Unclaim releases the pin.  Read-only sessions are blocked.
Both verbs emit a ``claim`` / ``unclaim`` event via ``append_event_locked``
under Sprint 1's writer_epoch CAS (apex contract preserved).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from astrid.core.project.paths import project_dir, validate_project_slug, validate_run_id
from astrid.core.session.binding import resolve_current_session
from astrid.core.session.model import SessionRole
from astrid.core.task.active_run import read_active_run
from astrid.core.task.events import (
    EVENTS_FILENAME,
    LEASE_FILENAME,
    append_event_locked,
    read_events,
)
from astrid.core.task.plan import STEP_PATH_SEP

CLAIM_KIND = "claim"
UNCLAIM_KIND = "unclaim"


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _read_lease_epoch(run_dir: Path) -> int:
    lease_path = run_dir / LEASE_FILENAME
    if not lease_path.exists():
        return 0
    try:
        payload = json.loads(lease_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    return int(payload.get("writer_epoch", 0))


def _resolve_session_identity() -> tuple[str, str, str]:
    """Resolve the current session's identity.

    Returns ``(agent_id, actor_name, role)``. ``actor_name`` is the human
    name if the session has one, otherwise ``None``-equivalent (empty string).
    """
    session = resolve_current_session()
    if session is None:
        return "", "", ""
    return session.agent_id, "", session.role


def _make_claim_event(
    step: str,
    *,
    claimed_by: str,
    claimed_by_kind: str,
    writer_epoch: int,
) -> dict:
    from astrid.core.task.events import _utc_now_iso
    return {
        "kind": CLAIM_KIND,
        "step": step,
        "claimed_by": claimed_by,
        "claimed_by_kind": claimed_by_kind,
        "writer_epoch": writer_epoch,
        "ts": _utc_now_iso(),
    }


def _make_unclaim_event(
    step: str,
    *,
    unclaimed_by: str,
    unclaimed_by_kind: str,
    writer_epoch: int,
) -> dict:
    from astrid.core.task.events import _utc_now_iso
    return {
        "kind": UNCLAIM_KIND,
        "step": step,
        "unclaimed_by": unclaimed_by,
        "unclaimed_by_kind": unclaimed_by_kind,
        "writer_epoch": writer_epoch,
        "ts": _utc_now_iso(),
    }


def _emit(run_dir: Path, event: dict, expected_epoch: int) -> dict:
    from astrid.core.task.events import _peek_tail_hash
    prev_hash = _peek_tail_hash(run_dir / EVENTS_FILENAME)
    return append_event_locked(
        run_dir,
        event,
        expected_writer_epoch=expected_epoch,
        expected_prev_hash=prev_hash,
    )


def _parse_for_flag(for_value: str) -> tuple[str, str]:
    """Parse ``--for agent:<id>`` or ``--for human:<name>`` into (identity, kind)."""
    if not isinstance(for_value, str) or not for_value:
        _print_err("claim: --for must be 'agent:<id>' or 'human:<name>'")
        sys.exit(1)
    if for_value.startswith("agent:"):
        ident = for_value[len("agent:"):]
        if not ident:
            _print_err("claim: --for agent:<id> missing agent id")
            sys.exit(1)
        return ident, "agent"
    if for_value.startswith("human:"):
        ident = for_value[len("human:"):]
        if not ident:
            _print_err("claim: --for human:<name> missing name")
            sys.exit(1)
        return ident, "actor"
    _print_err(f"claim: --for must be 'agent:<id>' or 'human:<name>', got {for_value!r}")
    sys.exit(1)
    return "", ""  # unreachable


def _resolve_claim_identity(args) -> tuple[str, str]:
    """Return ``(claimed_by, claimed_by_kind)`` from args or session default."""
    if args.for_claim is not None:
        return _parse_for_flag(args.for_claim)
    # Default: current session identity.
    agent_id, _actor_name, _role = _resolve_session_identity()
    if agent_id:
        return agent_id, "agent"
    _print_err(
        "claim: no --for flag supplied and no session identity available; "
        "run `astrid attach <project>` first or supply --for agent:<id> or --for human:<name>"
    )
    sys.exit(1)
    return "", ""  # unreachable


def _check_session_writable() -> None:
    """Reject read-only sessions with a clear error."""
    session = resolve_current_session()
    if session is None:
        _print_err("claim: no session bound; run `astrid attach <project>` first")
        sys.exit(1)
    if session.role == "reader":
        _print_err(
            f"claim: session {session.id!r} is read-only; "
            "only writer sessions can claim/unclaim steps. "
            f"Run `astrid sessions takeover --project {session.project}` to become writer."
        )
        sys.exit(1)


def cmd_claim(argv: Sequence[str], *, projects_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="astrid claim", add_help=True)
    parser.add_argument("step", help="step path (e.g. 'review' or 'outer/inner')")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--run-id", required=True, help="run id")
    parser.add_argument(
        "--for", dest="for_claim", default=None,
        help="identity to claim: 'agent:<id>' or 'human:<name>' (defaults to current session)",
    )

    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    _check_session_writable()

    slug = validate_project_slug(args.project)
    run_id = validate_run_id(args.run_id)
    run_dir = project_dir(slug, root=projects_root) / "runs" / run_id

    if not (run_dir / "events.jsonl").exists():
        _print_err(f"claim: no run {run_id!r} for project {slug!r}")
        return 1

    claimed_by, claimed_by_kind = _resolve_claim_identity(args)
    epoch = _read_lease_epoch(run_dir)
    event = _make_claim_event(
        args.step,
        claimed_by=claimed_by,
        claimed_by_kind=claimed_by_kind,
        writer_epoch=epoch,
    )

    try:
        _emit(run_dir, event, epoch)
    except Exception as exc:
        _print_err(f"claim: event-append failed: {exc}")
        return 1

    print(f"claimed {args.step!r} for {claimed_by_kind}:{claimed_by}")
    return 0


def cmd_unclaim(argv: Sequence[str], *, projects_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="astrid unclaim", add_help=True)
    parser.add_argument("step", help="step path (e.g. 'review' or 'outer/inner')")
    parser.add_argument("--project", required=True, help="project slug")
    parser.add_argument("--run-id", required=True, help="run id")
    parser.add_argument(
        "--for", dest="for_claim", default=None,
        help="identity to unclaim: 'agent:<id>' or 'human:<name>' (defaults to current session)",
    )

    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)

    _check_session_writable()

    slug = validate_project_slug(args.project)
    run_id = validate_run_id(args.run_id)
    run_dir = project_dir(slug, root=projects_root) / "runs" / run_id

    if not (run_dir / "events.jsonl").exists():
        _print_err(f"unclaim: no run {run_id!r} for project {slug!r}")
        return 1

    unclaimed_by, unclaimed_by_kind = _resolve_claim_identity(args)
    epoch = _read_lease_epoch(run_dir)
    event = _make_unclaim_event(
        args.step,
        unclaimed_by=unclaimed_by,
        unclaimed_by_kind=unclaimed_by_kind,
        writer_epoch=epoch,
    )

    try:
        _emit(run_dir, event, epoch)
    except Exception as exc:
        _print_err(f"unclaim: event-append failed: {exc}")
        return 1

    print(f"unclaimed {args.step!r} for {unclaimed_by_kind}:{unclaimed_by}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Return an argparse subparser for ``claim`` / ``unclaim``.

    Mirrors the session/cli.py pattern so ``astrid claim --help`` surfaces
    real help when registered in pipeline.py.
    """
    parser = argparse.ArgumentParser(prog="astrid claim", add_help=True)
    sub = parser.add_subparsers(dest="subcommand", required=True)
    # claim
    claim_p = sub.add_parser("claim", help="claim a step", add_help=True)
    claim_p.add_argument("step", help="step path")
    claim_p.add_argument("--project", required=True)
    claim_p.add_argument("--run-id", required=True)
    claim_p.add_argument(
        "--for", dest="for_claim", default=None,
        help="identity: 'agent:<id>' or 'human:<name>'",
    )
    # unclaim
    unclaim_p = sub.add_parser("unclaim", help="unclaim a step", add_help=True)
    unclaim_p.add_argument("step", help="step path")
    unclaim_p.add_argument("--project", required=True)
    unclaim_p.add_argument("--run-id", required=True)
    unclaim_p.add_argument(
        "--for", dest="for_claim", default=None,
        help="identity: 'agent:<id>' or 'human:<name>'",
    )
    return parser


__all__ = ["cmd_claim", "cmd_unclaim", "build_parser", "CLAIM_KIND", "UNCLAIM_KIND"]